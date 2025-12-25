# ==============================================================================
# SERVICIO DE AUDITORÍA
# ==============================================================================
# Centraliza toda la lógica de registro de auditoría.
# Formatea mensajes humanizados y categoriza eventos.
# ==============================================================================

from typing import Any, Dict, List, Optional
from datetime import datetime

from repositories.audit_repository import AuditRepository


class AuditService:
    """
    Servicio para registro y consulta de auditoría.
    
    Centraliza:
    - Registro de eventos con mensajes humanizados
    - Categorización de eventos (VENTA, PAGO, STOCK, PRODUCTO, SISTEMA)
    - Búsqueda y filtrado de logs
    
    La regla de oro: Si entra dinero → siempre log de PAGO
    """
    
    # Tipos de eventos de auditoría
    TYPE_VENTA = 'VENTA'
    TYPE_PAGO = 'PAGO'
    TYPE_STOCK = 'STOCK'
    TYPE_PRODUCTO = 'PRODUCTO'
    TYPE_SISTEMA = 'SISTEMA'
    
    def __init__(self, audit_repo: AuditRepository):
        """
        Inicializa el servicio de auditoría.
        
        Args:
            audit_repo: Repositorio de auditoría
        """
        self.audit_repo = audit_repo
    
    # =========================================================================
    # REGISTRO DE EVENTOS
    # =========================================================================
    
    def log(
        self, 
        log_type: str, 
        user: str, 
        message: str,
        related_id: str = '',
        details: Dict[str, Any] = None
    ) -> None:
        """
        Registra un evento de auditoría genérico.
        
        Args:
            log_type: Tipo de evento (VENTA, PAGO, STOCK, etc.)
            user: Usuario que realizó la acción
            message: Mensaje descriptivo humanizado
            related_id: ID relacionado (receipt, SKU, etc.)
            details: Detalles adicionales
        """
        self.audit_repo.log(log_type, user, message, related_id, details)
    
    def log_sale_created(
        self, 
        user: str, 
        receipt: str, 
        total: float,
        status: str,
        items_count: int
    ) -> None:
        """
        Registra la creación de una venta.
        
        Args:
            user: Usuario que creó la venta
            receipt: Número de boleta
            total: Total de la venta
            status: Estado inicial
            items_count: Cantidad de items
        """
        message = f"Venta {receipt} creada por {user} - Total: S/ {total:.2f} - {items_count} items - Estado: {status}"
        self.log(
            self.TYPE_VENTA, 
            user, 
            message, 
            receipt,
            {'total': total, 'status': status, 'items_count': items_count}
        )
    
    def log_sale_status_change(
        self, 
        user: str, 
        receipt: str, 
        old_status: str, 
        new_status: str
    ) -> None:
        """
        Registra un cambio de estado de venta.
        
        Args:
            user: Usuario que cambió el estado
            receipt: Número de boleta
            old_status: Estado anterior
            new_status: Nuevo estado
        """
        message = f"Venta {receipt}: {old_status} → {new_status} por {user}"
        self.log(
            self.TYPE_VENTA, 
            user, 
            message, 
            receipt,
            {'from': old_status, 'to': new_status}
        )
    
    def log_sale_completed(self, user: str, receipt: str) -> None:
        """
        Registra la completación de una venta (entregada).
        
        Args:
            user: Usuario que completó
            receipt: Número de boleta
        """
        message = f"Venta {receipt} completada (entregada) por {user}"
        self.log(self.TYPE_VENTA, user, message, receipt)
    
    def log_payment(
        self, 
        user: str, 
        receipt: str, 
        amount: float,
        method: str,
        total: float = None,
        pending_after: float = None
    ) -> None:
        """
        Registra un pago recibido.
        REGLA DE ORO: Si entra dinero, siempre se debe llamar esta función.
        
        Args:
            user: Usuario que registró el pago
            receipt: Número de boleta
            amount: Monto pagado
            method: Método de pago
            total: Total de la venta (opcional)
            pending_after: Monto pendiente después del pago (opcional)
        """
        message = f"Pago recibido en {receipt}: S/ {amount:.2f} ({method}) - Registrado por {user}"
        if pending_after is not None:
            if pending_after <= 0:
                message += " - PAGADO COMPLETO"
            else:
                message += f" - Pendiente: S/ {pending_after:.2f}"
        
        self.log(
            self.TYPE_PAGO, 
            user, 
            message, 
            receipt,
            {
                'amount': amount, 
                'method': method, 
                'total': total,
                'pending_after': pending_after
            }
        )
    
    def log_stock_add(
        self, 
        user: str, 
        pid: int, 
        sku: str,
        product_name: str,
        quantity: int,
        variant_id: str = None,
        uv: str = None,
        new_stock: int = None
    ) -> None:
        """
        Registra una entrada de stock.
        
        Args:
            user: Usuario que agregó
            pid: ID del producto
            sku: SKU del producto
            product_name: Nombre del producto
            quantity: Cantidad agregada
            variant_id: ID de variante (opcional)
            uv: Unidad de venta (opcional)
            new_stock: Nuevo stock total (opcional)
        """
        variant_info = f" (Variante: {variant_id})" if variant_id else ""
        uv_info = f" [{uv}]" if uv else ""
        stock_info = f" - Nuevo stock: {new_stock}" if new_stock is not None else ""
        
        message = f"Entrada de stock: +{quantity} {product_name}{variant_info}{uv_info}{stock_info} - Por {user}"
        
        self.log(
            self.TYPE_STOCK, 
            user, 
            message, 
            sku or str(pid),
            {
                'pid': pid,
                'quantity': quantity,
                'variant_id': variant_id,
                'uv': uv,
                'new_stock': new_stock
            }
        )
    
    def log_stock_remove(
        self, 
        user: str, 
        pid: int, 
        sku: str,
        product_name: str,
        quantity: int,
        variant_id: str = None,
        uv: str = None,
        reason: str = 'manual'
    ) -> None:
        """
        Registra una salida de stock.
        
        Args:
            user: Usuario que retiró
            pid: ID del producto
            sku: SKU del producto
            product_name: Nombre del producto
            quantity: Cantidad retirada
            variant_id: ID de variante (opcional)
            uv: Unidad de venta (opcional)
            reason: Razón del retiro
        """
        variant_info = f" (Variante: {variant_id})" if variant_id else ""
        uv_info = f" [{uv}]" if uv else ""
        
        message = f"Salida de stock: -{quantity} {product_name}{variant_info}{uv_info} - Razón: {reason} - Por {user}"
        
        self.log(
            self.TYPE_STOCK, 
            user, 
            message, 
            sku or str(pid),
            {
                'pid': pid,
                'quantity': quantity,
                'variant_id': variant_id,
                'uv': uv,
                'reason': reason
            }
        )
    
    def log_stock_reserved(
        self, 
        user: str, 
        receipt: str,
        items: List[Dict[str, Any]]
    ) -> None:
        """
        Registra reserva de stock por una venta.
        
        Args:
            user: Usuario
            receipt: Número de boleta
            items: Lista de items reservados
        """
        items_desc = ", ".join([f"{i.get('qty')}x {i.get('nombre', '')}" for i in items[:3]])
        if len(items) > 3:
            items_desc += f" (+{len(items)-3} más)"
        
        message = f"Stock reservado para venta {receipt}: {items_desc}"
        
        self.log(
            self.TYPE_STOCK, 
            user, 
            message, 
            receipt,
            {'items': items}
        )
    
    def log_stock_released(self, user: str, receipt: str, reason: str = 'anulación') -> None:
        """
        Registra liberación de stock (por anulación u otra razón).
        
        Args:
            user: Usuario
            receipt: Número de boleta
            reason: Razón de liberación
        """
        message = f"Stock liberado de venta {receipt} por {reason}"
        self.log(self.TYPE_STOCK, user, message, receipt, {'reason': reason})
    
    def log_product_created(
        self, 
        user: str, 
        pid: int, 
        sku: str, 
        name: str
    ) -> None:
        """
        Registra la creación de un producto.
        
        Args:
            user: Usuario que creó
            pid: ID del producto
            sku: SKU asignado
            name: Nombre del producto
        """
        message = f"Producto creado: {name} (SKU: {sku}) por {user}"
        self.log(self.TYPE_PRODUCTO, user, message, sku, {'pid': pid, 'name': name})
    
    def log_product_updated(
        self, 
        user: str, 
        pid: int, 
        sku: str, 
        name: str,
        changes: Dict[str, Any] = None
    ) -> None:
        """
        Registra actualización de un producto.
        
        Args:
            user: Usuario que actualizó
            pid: ID del producto
            sku: SKU del producto
            name: Nombre del producto
            changes: Campos modificados
        """
        message = f"Producto actualizado: {name} (SKU: {sku}) por {user}"
        self.log(
            self.TYPE_PRODUCTO, 
            user, 
            message, 
            sku, 
            {'pid': pid, 'changes': changes}
        )
    
    def log_product_deleted(
        self, 
        user: str, 
        pid: int, 
        sku: str, 
        name: str
    ) -> None:
        """
        Registra eliminación de un producto.
        
        Args:
            user: Usuario que eliminó
            pid: ID del producto
            sku: SKU del producto
            name: Nombre del producto
        """
        message = f"Producto eliminado: {name} (SKU: {sku}) por {user}"
        self.log(self.TYPE_PRODUCTO, user, message, sku, {'pid': pid, 'name': name})
    
    def log_variant_added(
        self, 
        user: str, 
        pid: int, 
        sku: str,
        variant_id: str,
        attributes: Dict[str, str]
    ) -> None:
        """
        Registra la adición de una variante.
        
        Args:
            user: Usuario
            pid: ID del producto
            sku: SKU del producto
            variant_id: ID de la nueva variante
            attributes: Atributos de la variante
        """
        attrs_str = ", ".join([f"{k}:{v}" for k, v in attributes.items()])
        message = f"Variante agregada a {sku}: {variant_id} ({attrs_str}) por {user}"
        self.log(
            self.TYPE_PRODUCTO, 
            user, 
            message, 
            sku,
            {'pid': pid, 'variant_id': variant_id, 'attributes': attributes}
        )
    
    def log_user_login(self, user: str) -> None:
        """Registra un inicio de sesión."""
        message = f"Inicio de sesión: {user}"
        self.log(self.TYPE_SISTEMA, user, message)
    
    def log_user_logout(self, user: str) -> None:
        """Registra un cierre de sesión."""
        message = f"Cierre de sesión: {user}"
        self.log(self.TYPE_SISTEMA, user, message)
    
    def log_role_change(
        self, 
        admin_user: str, 
        target_user: str, 
        old_role: str, 
        new_role: str
    ) -> None:
        """
        Registra un cambio de rol de usuario.
        
        Args:
            admin_user: Admin que hizo el cambio
            target_user: Usuario afectado
            old_role: Rol anterior
            new_role: Nuevo rol
        """
        message = f"Cambio de rol: {target_user} de {old_role} a {new_role} - Por {admin_user}"
        self.log(
            self.TYPE_SISTEMA, 
            admin_user, 
            message,
            details={'target_user': target_user, 'from': old_role, 'to': new_role}
        )
    
    def log_user_deleted(self, admin_user: str, deleted_user: str, role: str) -> None:
        """
        Registra eliminación de un usuario.
        
        Args:
            admin_user: Admin que eliminó
            deleted_user: Usuario eliminado
            role: Rol del usuario eliminado
        """
        message = f"Usuario eliminado: {deleted_user} (rol: {role}) - Por {admin_user}"
        self.log(
            self.TYPE_SISTEMA, 
            admin_user, 
            message,
            details={'deleted_user': deleted_user, 'role': role}
        )
    
    def log_user_created(
        self, 
        admin_user: str, 
        new_user: str, 
        role: str
    ) -> None:
        """
        Registra la creación de un nuevo usuario.
        
        Args:
            admin_user: Admin que creó el usuario
            new_user: Nombre del nuevo usuario
            role: Rol asignado
        """
        message = f"Usuario creado: {new_user} (rol: {role}) - Por {admin_user}"
        self.log(
            self.TYPE_SISTEMA, 
            admin_user, 
            message,
            details={'new_user': new_user, 'role': role}
        )
    
    def log_password_change(self, admin_user: str, target_user: str) -> None:
        """
        Registra el cambio de contraseña de un usuario.
        
        Args:
            admin_user: Usuario que realizó el cambio
            target_user: Usuario cuya contraseña fue cambiada
        """
        if admin_user == target_user:
            message = f"Contraseña cambiada por el propio usuario: {target_user}"
        else:
            message = f"Contraseña de {target_user} cambiada por {admin_user}"
        
        self.log(
            self.TYPE_SISTEMA, 
            admin_user, 
            message,
            details={'target_user': target_user}
        )
    
    # =========================================================================
    # CONSULTA DE LOGS
    # =========================================================================
    
    def get_all_logs(self) -> List[Dict[str, Any]]:
        """Obtiene todos los logs ordenados por fecha."""
        return self.audit_repo.load()
    
    def get_recent_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Obtiene los logs más recientes."""
        return self.audit_repo.get_recent_logs(limit)
    
    def search_logs(
        self,
        query: str = '',
        log_type: str = None,
        user: str = None,
        from_date: str = None,
        to_date: str = None
    ) -> List[Dict[str, Any]]:
        """Búsqueda avanzada de logs."""
        return self.audit_repo.search_logs(query, log_type, user, from_date, to_date)
    
    def get_logs_by_type(self, log_type: str) -> List[Dict[str, Any]]:
        """Filtra logs por tipo."""
        return self.audit_repo.get_logs_by_type(log_type)
    
    def get_logs_by_user(self, user: str) -> List[Dict[str, Any]]:
        """Filtra logs por usuario."""
        return self.audit_repo.get_logs_by_user(user)
    
    def get_unique_users(self) -> List[str]:
        """Obtiene lista de usuarios únicos en los logs."""
        return self.audit_repo.get_unique_users()
    
    def get_unique_types(self) -> List[str]:
        """Obtiene lista de tipos de eventos únicos."""
        return self.audit_repo.get_unique_types()
