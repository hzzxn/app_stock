# ==============================================================================
# SERVICIO DE PAGOS
# ==============================================================================
# Centraliza toda la lógica de negocio relacionada con pagos.
# ==============================================================================

from typing import Any, Dict, Optional, Tuple
from datetime import datetime, timezone

from repositories.sales_repository import SalesRepository
from services.audit_service import AuditService


class PaymentService:
    """
    Servicio para gestión de pagos.
    
    Responsabilidades:
    - Agregar pagos a ventas
    - Validar montos
    - Registrar pagos en auditoría (REGLA DE ORO)
    """
    
    def __init__(
        self, 
        sales_repo: SalesRepository,
        audit_service: AuditService = None
    ):
        """
        Inicializa el servicio de pagos.
        
        Args:
            sales_repo: Repositorio de ventas
            audit_service: Servicio de auditoría
        """
        self.sales_repo = sales_repo
        self.audit_service = audit_service
    
    def add_payment(
        self, 
        receipt: str,
        amount: float,
        method: str,
        user: str
    ) -> Dict[str, Any]:
        """
        Agrega un pago a una venta.
        REGLA DE ORO: Si entra dinero, siempre se registra en auditoría.
        
        Args:
            receipt: Número de boleta
            amount: Monto a pagar
            method: Método de pago
            user: Usuario que registra
            
        Returns:
            Dict con resultado (ok, error, sale, etc.)
        """
        # Validar monto
        try:
            amount = float(amount or 0)
        except (TypeError, ValueError):
            return {'ok': False, 'error': 'Monto inválido'}
        
        if amount <= 0:
            return {'ok': False, 'error': 'El monto debe ser mayor a 0'}
        
        # Obtener venta
        sale = self.sales_repo.get_by_receipt(receipt)
        if not sale:
            return {'ok': False, 'error': 'Venta no encontrada'}
        
        # Validar estado
        if sale.get('status') == 'ANULADO':
            return {'ok': False, 'error': 'No se pueden agregar pagos a una venta anulada'}
        
        # Calcular pendiente actual
        total = float(sale.get('total', 0) or 0)
        paid_current = self._calculate_paid_amount(sale)
        pending = round(max(0, total - paid_current), 2)
        
        # Validar que no exceda el pendiente
        if amount > pending:
            return {
                'ok': False, 
                'error': f'El pago excede el monto pendiente (S/ {pending:.2f})'
            }
        
        # Crear registro de pago
        payment = {
            'amount': round(amount, 2),
            'method': method or 'Efectivo',
            'ts': datetime.now(timezone.utc).isoformat(),
            'user': user
        }
        
        # Agregar a la venta
        if 'payments' not in sale:
            sale['payments'] = []
        sale['payments'].append(payment)
        
        # Recalcular totales
        old_status, new_status = self._recompute_sale_totals(sale)
        
        # Guardar cambios
        self.sales_repo.update_sale(receipt, {
            'payments': sale['payments'],
            'paid_amount': sale['paid_amount'],
            'pending_amount': sale['pending_amount'],
            'status': sale['status']
        })
        
        # REGLA DE ORO: Registrar en auditoría
        if self.audit_service:
            self.audit_service.log_payment(
                user=user,
                receipt=receipt,
                amount=payment['amount'],
                method=payment['method'],
                total=total,
                pending_after=sale['pending_amount']
            )
        
        return {
            'ok': True,
            'receipt': receipt,
            'payment': payment,
            'paid_amount': sale['paid_amount'],
            'pending_amount': sale['pending_amount'],
            'status': sale['status'],
            'status_changed': old_status != new_status,
            'old_status': old_status,
            'new_status': new_status
        }
    
    def _calculate_paid_amount(self, sale: Dict[str, Any]) -> float:
        """
        Calcula el monto pagado desde la lista de pagos.
        
        Args:
            sale: Datos de la venta
            
        Returns:
            Monto total pagado
        """
        paid = 0.0
        for p in sale.get('payments', []):
            try:
                paid += float(p.get('amount', 0) or 0)
            except (TypeError, ValueError):
                continue
        return round(max(0, paid), 2)
    
    def _recompute_sale_totals(self, sale: Dict[str, Any]) -> Tuple[str, str]:
        """
        Recalcula los totales de una venta basándose en los pagos.
        Modifica la venta in-place.
        
        Args:
            sale: Datos de la venta
            
        Returns:
            Tupla (old_status, new_status)
        """
        total = float(sale.get('total', 0) or 0)
        paid = self._calculate_paid_amount(sale)
        pending = round(max(0, total - paid), 2)
        
        sale['paid_amount'] = paid
        sale['pending_amount'] = pending
        
        old_status = sale.get('status', 'POR PAGAR')
        new_status = old_status
        
        # Si estaba pendiente y ya está pagado, cambiar estado
        if old_status == 'POR PAGAR' and pending <= 0:
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
    
    def get_payment_history(self, receipt: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene el historial de pagos de una venta.
        
        Args:
            receipt: Número de boleta
            
        Returns:
            Dict con payments, total, paid, pending
        """
        sale = self.sales_repo.get_by_receipt(receipt)
        if not sale:
            return None
        
        return {
            'receipt': receipt,
            'payments': sale.get('payments', []),
            'total': sale.get('total', 0),
            'paid_amount': sale.get('paid_amount', 0),
            'pending_amount': sale.get('pending_amount', 0),
            'status': sale.get('status', '')
        }
    
    def validate_payment(
        self, 
        receipt: str, 
        amount: float
    ) -> Dict[str, Any]:
        """
        Valida si un pago es posible sin aplicarlo.
        
        Args:
            receipt: Número de boleta
            amount: Monto a validar
            
        Returns:
            Dict con ok, error, pending, etc.
        """
        try:
            amount = float(amount or 0)
        except (TypeError, ValueError):
            return {'ok': False, 'error': 'Monto inválido'}
        
        if amount <= 0:
            return {'ok': False, 'error': 'El monto debe ser mayor a 0'}
        
        sale = self.sales_repo.get_by_receipt(receipt)
        if not sale:
            return {'ok': False, 'error': 'Venta no encontrada'}
        
        if sale.get('status') == 'ANULADO':
            return {'ok': False, 'error': 'Venta anulada'}
        
        total = float(sale.get('total', 0) or 0)
        paid = self._calculate_paid_amount(sale)
        pending = round(max(0, total - paid), 2)
        
        if amount > pending:
            return {
                'ok': False, 
                'error': f'Excede monto pendiente',
                'pending': pending
            }
        
        return {
            'ok': True,
            'receipt': receipt,
            'amount': amount,
            'pending': pending,
            'remaining_after': round(pending - amount, 2)
        }
