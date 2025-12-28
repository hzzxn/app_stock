# ==============================================================================
# CAPA DE SERVICIOS - Lógica de negocio
# ==============================================================================
# Esta capa contiene TODA la lógica de negocio de la aplicación.
# 
# PRINCIPIOS:
# 1. Los servicios orquestan operaciones entre repositorios
# 2. Aplican reglas de negocio y validaciones
# 3. Las rutas (controllers) solo llaman a servicios
# 4. Los servicios NO conocen el tipo de almacenamiento (JSON/MySQL)
#
# ESTRUCTURA:
# ├── user_service.py      → Usuarios, autenticación, roles (¡protección China Import!)
# ├── inventory_service.py → Productos, variantes, stock
# ├── sales_service.py     → Ventas, estados, recibos
# ├── payment_service.py   → Pagos, abonos
# ├── cart_service.py      → Carrito de compras
# ├── audit_service.py     → Logs de actividad
# └── stats_service.py     → Estadísticas de ganancias
#
# SEGURIDAD CRÍTICA - ROL "CHINA IMPORT":
# El usuario con rol "China Import" es el SUPER USUARIO del sistema.
# Las protecciones están en UserService.validate_role_modification():
# - NO puede ser eliminado
# - NO puede perder su rol
# - NO puede ser degradado (ni siquiera por él mismo)
# Estas validaciones son en BACKEND, no dependen del frontend.
#
# MIGRACIÓN A MYSQL:
# Los servicios dependen de INTERFACES de repositorios, no de implementaciones.
# Al cambiar JSON → MySQL:
# 1. Crear nuevas clases de repositorio que implementen las interfaces
# 2. Cambiar instanciación en app_container.py
# 3. Los servicios NO requieren cambios
# ==============================================================================

from app_stock.services.inventory_service import InventoryService
from app_stock.services.sales_service import SalesService
from app_stock.services.payment_service import PaymentService
from app_stock.services.cart_service import CartService
from app_stock.services.audit_service import AuditService
from app_stock.services.user_service import UserService, ProtectedRoleError
from app_stock.services.stats_service import StatsService, get_stats_service

__all__ = [
    'InventoryService',
    'SalesService',
    'PaymentService',
    'CartService',
    'AuditService',
    'UserService',
    'ProtectedRoleError',
    'StatsService',
    'get_stats_service',
]
