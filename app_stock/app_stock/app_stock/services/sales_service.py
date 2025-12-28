# ==============================================================================
# SERVICIO DE VENTAS
# ==============================================================================
# Centraliza toda la lógica de negocio relacionada con ventas.
# Gestiona el ciclo de vida completo de una venta.
# ==============================================================================

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

from app_stock.repositories.sales_repository import SalesRepository
from app_stock.services.inventory_service import InventoryService
from app_stock.services.audit_service import AuditService


# Estados válidos de venta
SALE_STATUSES = frozenset([
    'CANCELADO',     # Venta completada y pagada
    'POR PAGAR',     # Pendiente de pago
    'PARA RECOJO',   # Pagada, esperando recojo
    'PARA ENVÍO',    # Pagada, esperando envío
    'COMPLETADA',    # Entregada al cliente
    'ANULADO'        # Venta cancelada
])


class SalesService:
    """
    Servicio para gestión de ventas.
    
    Responsabilidades:
    - Crear ventas desde el carrito
    - Gestionar estados de venta
    - Transiciones de inventario por estado
    - Cálculo de totales
    """
    
    def __init__(
        self, 
        sales_repo: SalesRepository,
        inventory_service: InventoryService,
        audit_service: AuditService = None
    ):
        """
        Inicializa el servicio de ventas.
        
        Args:
            sales_repo: Repositorio de ventas
            inventory_service: Servicio de inventario
            audit_service: Servicio de auditoría (opcional)
        """
        self.sales_repo = sales_repo
        self.inventory_service = inventory_service
        self.audit_service = audit_service
    
    # =========================================================================
    # CREACIÓN DE VENTAS
    # =========================================================================
    
    def create_sale_from_cart(
        self,
        cart_items: List[Dict[str, Any]],
        user: str,
        client_data: Dict[str, str] = None,
        payments: List[Dict[str, Any]] = None,
        delivery: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Crea una venta desde los items del carrito.
        Esta es la ÚNICA función que crea ventas - centralizada.
        
        Args:
            cart_items: Lista de items del carrito
            user: Usuario que crea la venta
            client_data: Datos del cliente (name, doc, obs)
            payments: Lista de pagos iniciales
            delivery: Datos de entrega
            
        Returns:
            Dict con resultado:
            - ok: True/False
            - error: mensaje si falló
            - receipt: número de boleta
            - total: total de la venta
            - status: estado asignado
            - paid_amount: monto pagado
            - pending_amount: monto pendiente
        """
        if not cart_items:
            return {'ok': False, 'error': 'El carrito está vacío'}
        
        inventory = self.inventory_service.get_all_products()
        
        # Validar stock y construir items de venta
        sale_items = []
        errors = []
        
        for cart_item in cart_items:
            pid = cart_item.get('producto_id')
            variant_id = cart_item.get('variant_id')
            uv = cart_item.get('uv', 'UNIDAD')
            qty = cart_item.get('cantidad', 0)
            
            if pid not in inventory:
                errors.append(f"Producto {pid} no encontrado")
                continue
            
            product = inventory[pid]
            self.inventory_service.normalize_product_variants(product)
            
            # Validar variante
            variant = self.inventory_service.get_variant(product, variant_id)
            if not variant:
                errors.append(f"Variante {variant_id} no encontrada en {product.get('nombre')}")
                continue
            
            # Validar stock disponible
            available = self.inventory_service.get_variant_uv_available(
                product, variant_id, uv
            )
            if qty > available:
                errors.append(
                    f"Stock insuficiente para {product.get('nombre')} "
                    f"(Variante: {variant_id}, UV: {uv}). "
                    f"Solicitado: {qty}, Disponible: {available}"
                )
                continue
            
            # Obtener precios
            unit_price = cart_item.get('precio_unitario', 0)
            unit_cost = self.inventory_service.get_variant_uv_cost(
                product, variant_id, uv
            )
            
            # Construir item de venta
            sale_item = {
                'pid': pid,
                'sku': product.get('sku', ''),
                'nombre': product.get('nombre', ''),
                'qty': qty,
                'unit_price': round(unit_price, 2),
                'unit_cost': round(unit_cost, 2),
                'line_total': round(qty * unit_price, 2),
                'line_profit': round((unit_price - unit_cost) * qty, 2),
                'variant_id': variant_id,
                'variant_attributes': cart_item.get('variant_attributes', {}),
                'uv': uv,
                'uv_label': cart_item.get('uv_label')
            }
            sale_items.append(sale_item)
        
        if errors:
            return {'ok': False, 'error': '; '.join(errors)}
        
        if not sale_items:
            return {'ok': False, 'error': 'No hay items válidos en el carrito'}
        
        # Calcular totales
        total = sum(item['line_total'] for item in sale_items)
        profit_total = sum(item['line_profit'] for item in sale_items)
        
        # Procesar pagos iniciales
        payments = payments or []
        paid_amount = sum(float(p.get('amount', 0) or 0) for p in payments)
        pending_amount = max(0, total - paid_amount)
        
        # Normalizar pagos
        normalized_payments = []
        for p in payments:
            amt = float(p.get('amount', 0) or 0)
            if amt > 0:
                normalized_payments.append({
                    'amount': round(amt, 2),
                    'method': p.get('method', 'EFECTIVO'),
                    'ts': datetime.now(timezone.utc).isoformat(),
                    'user': user
                })
        
        # Determinar estado inicial
        status = self._determine_initial_status(
            paid_amount, total, delivery
        )
        
        # Generar número de boleta
        receipt = self.sales_repo.get_next_receipt_number()
        
        # Construir venta
        sale_data = {
            'receipt': receipt,
            'user': user,
            'ts': datetime.now(timezone.utc).isoformat(),
            'status': status,
            'items': sale_items,
            'total': round(total, 2),
            'profit_total': round(profit_total, 2),
            'paid_amount': round(paid_amount, 2),
            'pending_amount': round(pending_amount, 2),
            'payments': normalized_payments,
            'client_name': (client_data or {}).get('client_name', ''),
            'client_doc': (client_data or {}).get('client_doc', ''),
            'client_obs': (client_data or {}).get('client_obs', ''),
        }
        
        # Agregar datos de entrega si existen
        if delivery:
            sale_data['delivery'] = {
                'type': delivery.get('type', 'RECOJO'),
                'address': delivery.get('address', ''),
                'district': delivery.get('district', ''),
                'province': delivery.get('province', ''),
                'reference': delivery.get('reference', ''),
                'phone': delivery.get('phone', ''),
                'shipping_cost': delivery.get('shipping_cost', 0),
                'notes': delivery.get('notes', '')
            }
        
        # Aplicar transición de inventario según estado inicial
        self._apply_inventory_transition(
            sale_data, status, None, inventory
        )
        
        # Guardar venta
        self.sales_repo.create_sale(sale_data)
        
        # Guardar inventario actualizado
        self.inventory_service.save_inventory(inventory)
        
        # Auditar
        if self.audit_service:
            self.audit_service.log_sale_created(
                user, receipt, total, status, len(sale_items)
            )
            # Si hay pagos, registrar cada uno
            for p in normalized_payments:
                self.audit_service.log_payment(
                    user, receipt, p['amount'], p['method'],
                    total, pending_amount
                )
        
        return {
            'ok': True,
            'receipt': receipt,
            'total': round(total, 2),
            'status': status,
            'paid_amount': round(paid_amount, 2),
            'pending_amount': round(pending_amount, 2)
        }
    
    def _determine_initial_status(
        self, 
        paid_amount: float, 
        total: float,
        delivery: Dict[str, Any] = None
    ) -> str:
        """
        Determina el estado inicial de la venta.
        
        Args:
            paid_amount: Monto pagado
            total: Total de la venta
            delivery: Datos de entrega
            
        Returns:
            Estado inicial
        """
        if paid_amount >= total:
            # Pagado completo
            if delivery:
                delivery_type = delivery.get('type', 'RECOJO')
                if delivery_type == 'RECOJO':
                    return 'PARA RECOJO'
                elif delivery_type in ('DELIVERY', 'PROVINCIA'):
                    return 'PARA ENVÍO'
            return 'CANCELADO'
        else:
            return 'POR PAGAR'
    
    def _apply_inventory_transition(
        self,
        sale: Dict[str, Any],
        new_status: str,
        old_status: str = None,
        inventory: Dict[int, Dict[str, Any]] = None
    ) -> None:
        """
        Aplica cambios de inventario según transición de estado.
        
        Reglas de inventario:
        - POR PAGAR: Reservar stock (no descontar aún)
        - CANCELADO/PARA RECOJO/PARA ENVÍO: Confirmar reserva (descontar)
        - ANULADO: Liberar reserva (devolver al stock disponible)
        
        Args:
            sale: Datos de la venta
            new_status: Nuevo estado
            old_status: Estado anterior (None si es nueva)
            inventory: Diccionario de inventario (se modifica in-place)
        """
        if inventory is None:
            inventory = self.inventory_service.get_all_products()
        
        for item in sale.get('items', []):
            pid = item.get('pid')
            variant_id = item.get('variant_id')
            uv = item.get('uv', 'UNIDAD')
            qty = item.get('qty', 0)
            
            if pid not in inventory:
                continue
            
            product = inventory[pid]
            self.inventory_service.normalize_product_variants(product)
            
            variant = self.inventory_service.get_variant(product, variant_id)
            if not variant:
                continue
            
            uv_entry = self.inventory_service.get_variant_uv(variant, uv)
            if not uv_entry:
                continue
            
            # Transiciones de inventario
            if old_status is None:
                # Nueva venta
                if new_status == 'POR PAGAR':
                    # Reservar stock
                    uv_entry['reserved'] = uv_entry.get('reserved', 0) + qty
                else:
                    # Venta pagada directamente - descontar stock
                    uv_entry['stock'] = max(0, uv_entry.get('stock', 0) - qty)
            
            elif old_status == 'POR PAGAR':
                if new_status in ('CANCELADO', 'PARA RECOJO', 'PARA ENVÍO'):
                    # Confirmar reserva: liberar reserva Y descontar stock
                    uv_entry['reserved'] = max(0, uv_entry.get('reserved', 0) - qty)
                    uv_entry['stock'] = max(0, uv_entry.get('stock', 0) - qty)
                elif new_status == 'ANULADO':
                    # Anular: solo liberar reserva
                    uv_entry['reserved'] = max(0, uv_entry.get('reserved', 0) - qty)
            
            elif old_status == 'ANULADO':
                # No se puede cambiar desde ANULADO (stock ya liberado)
                pass
    
    # =========================================================================
    # CONSULTA DE VENTAS
    # =========================================================================
    
    def get_sale(self, receipt: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene una venta por su número de boleta.
        
        Args:
            receipt: Número de boleta
            
        Returns:
            Datos de la venta o None
        """
        return self.sales_repo.get_by_receipt(receipt)
    
    def get_all_sales(self) -> List[Dict[str, Any]]:
        """
        Obtiene todas las ventas.
        
        Returns:
            Lista de ventas
        """
        return self.sales_repo.load()
    
    def search_sales(
        self,
        query: str = '',
        user: str = None,
        receipt: str = None,
        from_date: str = None,
        to_date: str = None
    ) -> List[Dict[str, Any]]:
        """
        Búsqueda avanzada de ventas.
        
        Args:
            query: Texto de búsqueda
            user: Filtrar por usuario
            receipt: Filtrar por boleta
            from_date: Fecha inicio
            to_date: Fecha fin
            
        Returns:
            Lista de ventas que coinciden
        """
        return self.sales_repo.search_sales(
            query, user, receipt, from_date, to_date
        )
    
    def get_pending_sales(self) -> List[Dict[str, Any]]:
        """Obtiene ventas pendientes de pago."""
        return self.sales_repo.get_pending_sales()
    
    # =========================================================================
    # CAMBIO DE ESTADO
    # =========================================================================
    
    def change_status(
        self, 
        receipt: str, 
        new_status: str,
        user: str,
        reason: str = None
    ) -> Dict[str, Any]:
        """
        Cambia el estado de una venta.
        
        Args:
            receipt: Número de boleta
            new_status: Nuevo estado
            user: Usuario que hace el cambio
            reason: Razón del cambio (para anulaciones)
            
        Returns:
            Dict con resultado (ok, error, etc.)
        """
        if new_status not in SALE_STATUSES:
            return {'ok': False, 'error': f'Estado inválido: {new_status}'}
        
        sale = self.get_sale(receipt)
        if not sale:
            return {'ok': False, 'error': 'Venta no encontrada'}
        
        old_status = sale.get('status', 'CANCELADO')
        
        # Reglas de negocio para transiciones
        if old_status == 'CANCELADO' and new_status != 'CANCELADO':
            return {
                'ok': False, 
                'error': 'Una venta CANCELADA no puede cambiar de estado'
            }
        
        if old_status == 'ANULADO':
            return {
                'ok': False, 
                'error': 'Una venta ANULADA no puede cambiar de estado'
            }
        
        if old_status == 'COMPLETADA' and new_status not in ('COMPLETADA', 'ANULADO'):
            return {
                'ok': False, 
                'error': 'Una venta COMPLETADA solo puede anularse'
            }
        
        # Aplicar transición de inventario
        inventory = self.inventory_service.get_all_products()
        self._apply_inventory_transition(sale, new_status, old_status, inventory)
        
        # Actualizar venta
        updates = {'status': new_status}
        if reason:
            if new_status == 'ANULADO':
                updates['annul_reason'] = reason
            else:
                updates['pending_reason'] = reason
        
        # Si cambia de POR PAGAR a CANCELADO manualmente, registrar pago implícito
        if old_status == 'POR PAGAR' and new_status == 'CANCELADO':
            pending = float(sale.get('pending_amount', 0) or 0)
            if pending > 0:
                # Agregar pago del monto pendiente
                payment = {
                    'amount': round(pending, 2),
                    'method': 'Manual (cambio estado)',
                    'ts': datetime.now(timezone.utc).isoformat(),
                    'user': user
                }
                if 'payments' not in sale:
                    sale['payments'] = []
                sale['payments'].append(payment)
                updates['payments'] = sale['payments']
                updates['paid_amount'] = round(
                    float(sale.get('paid_amount', 0) or 0) + pending, 2
                )
                updates['pending_amount'] = 0.0
                
                # Auditar el pago
                if self.audit_service:
                    self.audit_service.log_payment(
                        user, receipt, pending, 'Manual (cambio estado)',
                        sale.get('total'), 0
                    )
        
        self.sales_repo.update_sale(receipt, updates)
        self.inventory_service.save_inventory(inventory)
        
        # Auditar
        if self.audit_service:
            self.audit_service.log_sale_status_change(
                user, receipt, old_status, new_status
            )
        
        return {
            'ok': True,
            'receipt': receipt,
            'old_status': old_status,
            'new_status': new_status
        }
    
    def complete_sale(self, receipt: str, user: str) -> Dict[str, Any]:
        """
        Marca una venta como completada (entregada).
        
        Args:
            receipt: Número de boleta
            user: Usuario que completa
            
        Returns:
            Dict con resultado
        """
        sale = self.get_sale(receipt)
        if not sale:
            return {'ok': False, 'error': 'Venta no encontrada'}
        
        current_status = sale.get('status', 'CANCELADO')
        allowed = {'CANCELADO', 'PARA RECOJO', 'PARA ENVÍO'}
        
        if current_status not in allowed:
            return {
                'ok': False,
                'error': f'No se puede completar una venta con estado {current_status}'
            }
        
        updates = {
            'status': 'COMPLETADA',
            'completion_ts': datetime.now(timezone.utc).isoformat(),
            'completed_by': user
        }
        
        self.sales_repo.update_sale(receipt, updates)
        
        # Auditar
        if self.audit_service:
            self.audit_service.log_sale_completed(user, receipt)
        
        return {
            'ok': True,
            'receipt': receipt,
            'message': f'Venta {receipt} marcada como COMPLETADA'
        }
    
    # =========================================================================
    # RECÁLCULO DE TOTALES
    # =========================================================================
    
    def recompute_totals(self, sale: Dict[str, Any]) -> Tuple[str, str]:
        """
        Recalcula los totales de una venta basándose en los pagos.
        
        Args:
            sale: Datos de la venta (se modifica in-place)
            
        Returns:
            Tupla (old_status, new_status) si cambió el estado
        """
        total = float(sale.get('total', 0) or 0)
        
        # Calcular monto pagado desde la lista de pagos
        paid = 0.0
        for p in sale.get('payments', []):
            try:
                paid += float(p.get('amount', 0) or 0)
            except (TypeError, ValueError):
                continue
        
        paid = round(max(0, paid), 2)
        pending = round(max(0, total - paid), 2)
        
        sale['paid_amount'] = paid
        sale['pending_amount'] = pending
        
        # Determinar si debe cambiar el estado
        old_status = sale.get('status', 'POR PAGAR')
        new_status = old_status
        
        if old_status == 'POR PAGAR' and pending <= 0:
            # Ya está pagado - determinar siguiente estado
            delivery = sale.get('delivery', {})
            delivery_type = delivery.get('type', 'RECOJO') if delivery else 'RECOJO'
            
            if delivery_type == 'RECOJO':
                new_status = 'PARA RECOJO'
            elif delivery_type in ('DELIVERY', 'PROVINCIA'):
                new_status = 'PARA ENVÍO'
            else:
                new_status = 'CANCELADO'
            
            sale['status'] = new_status
        
        return (old_status, new_status)
    
    # =========================================================================
    # ESTADÍSTICAS
    # =========================================================================
    
    def compute_stats(self, sales: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Calcula estadísticas de ventas.
        
        Args:
            sales: Lista de ventas (usa todas si None)
            
        Returns:
            Dict con estadísticas
        """
        if sales is None:
            sales = self.get_all_sales()
        
        total_sales = len(sales)
        total_revenue = 0.0
        total_profit = 0.0
        pagos_recibidos = 0.0
        monto_pendiente = 0.0
        ventas_pagadas = 0
        ventas_pendientes = 0
        
        for sale in sales:
            status = sale.get('status', 'CANCELADO')
            total_venta = float(sale.get('total', 0) or 0)
            paid = float(sale.get('paid_amount', 0) or 0)
            pending = float(sale.get('pending_amount', 0) or 0)
            
            if status == 'ANULADO':
                continue
            
            total_revenue += total_venta
            total_profit += float(sale.get('profit_total', 0) or 0)
            
            if status == 'CANCELADO':
                pagos_recibidos += total_venta
                ventas_pagadas += 1
            elif status == 'POR PAGAR':
                pagos_recibidos += paid
                monto_pendiente += pending
                ventas_pendientes += 1
            else:
                pagos_recibidos += total_venta
                ventas_pagadas += 1
        
        avg_ticket = total_revenue / total_sales if total_sales else 0.0
        
        return {
            'total_sales': total_sales,
            'total_revenue': round(total_revenue, 2),
            'total_profit': round(total_profit, 2),
            'avg_ticket': round(avg_ticket, 2),
            'pagos_recibidos': round(pagos_recibidos, 2),
            'monto_pendiente': round(monto_pendiente, 2),
            'ventas_pagadas': ventas_pagadas,
            'ventas_pendientes': ventas_pendientes
        }
