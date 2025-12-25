# ==============================================================================
# CAPA DE MODELOS - Estructuras de datos del sistema
# ==============================================================================
# Este módulo define todas las entidades del dominio usando dataclasses.
# Beneficios:
#   - Type hints para mejor documentación y autocompletado
#   - Validación implícita de estructura
#   - Fácil serialización/deserialización para JSON o SQL
#   - Independiente del mecanismo de persistencia (JSON ahora, MySQL después)
# ==============================================================================

from .entities import (
    # Usuarios
    User,
    UserRole,
    
    # Productos e Inventario
    Product,
    ProductVariant,
    VariantUnit,
    
    # Ventas
    Sale,
    SaleItem,
    SaleStatus,
    
    # Pagos
    Payment,
    PaymentMethod,
    
    # Entregas
    Delivery,
    DeliveryType,
    
    # Carrito
    CartItem,
    
    # Auditoría
    AuditLog,
    AuditType,
)

__all__ = [
    # Usuarios
    'User',
    'UserRole',
    
    # Productos
    'Product',
    'ProductVariant',
    'VariantUnit',
    
    # Ventas
    'Sale',
    'SaleItem',
    'SaleStatus',
    
    # Pagos
    'Payment',
    'PaymentMethod',
    
    # Entregas
    'Delivery',
    'DeliveryType',
    
    # Carrito
    'CartItem',
    
    # Auditoría
    'AuditLog',
    'AuditType',
]
