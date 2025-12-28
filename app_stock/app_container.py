# ==============================================================================
# CONTENEDOR DE DEPENDENCIAS - Inyección de servicios
# ==============================================================================
# Este módulo proporciona una forma centralizada de obtener instancias
# de repositorios y servicios. Facilita:
#   - Inyección de dependencias
#   - Testing (se pueden mockear los repositorios)
#   - Migración gradual (cambiar repos sin tocar servicios)
#
# ═══════════════════════════════════════════════════════════════════════════════
# MIGRACIÓN A MYSQL - INSTRUCCIONES
# ═══════════════════════════════════════════════════════════════════════════════
# 
# Para migrar de JSON a MySQL, solo necesitas:
#
# 1. Crear nuevas clases de repositorio:
#    - MySQLUserRepository (implementa IUserRepository)
#    - MySQLSalesRepository (implementa ISalesRepository)
#    - etc.
#
# 2. Cambiar las importaciones en este archivo:
#    # Antes (JSON):
#    from app_stock.repositories import UserRepository
#    # Después (MySQL):
#    from app_stock.repositories.mysql import MySQLUserRepository as UserRepository
#
# 3. ¡Listo! Los servicios NO requieren cambios porque:
#    - Dependen de interfaces, no de implementaciones
#    - La lógica de negocio está en services/, no en repos
#
# NOTA: El rol "China Import" está protegido en UserService,
# no importa si usas JSON o MySQL.
# ==============================================================================

import os
from typing import Optional

# ═══════════════════════════════════════════════════════════════════════════════
# REPOSITORIOS - Capa de persistencia (JSON ahora, MySQL después)
# ═══════════════════════════════════════════════════════════════════════════════
# Para cambiar a MySQL: importar MySQLUserRepository, MySQLSalesRepository, etc.
from app_stock.repositories import (
    InventoryRepository,
    SalesRepository,
    UserRepository,
    AuditRepository,
    SettingsRepository,
)

# ═══════════════════════════════════════════════════════════════════════════════
# SERVICIOS - Capa de lógica de negocio (NO cambia con MySQL)
# ═══════════════════════════════════════════════════════════════════════════════
from app_stock.services import (
    InventoryService,
    SalesService,
    PaymentService,
    CartService,
    AuditService,
    UserService,
)


class AppContainer:
    """
    Contenedor de dependencias de la aplicación.
    
    Implementa el patrón Singleton para asegurar una única instancia
    de cada repositorio y servicio.
    
    Uso:
        container = AppContainer(base_path='/path/to/app')
        inventory_service = container.inventory_service
        sales_service = container.sales_service
    """
    
    _instance: Optional['AppContainer'] = None
    
    def __new__(cls, base_path: str = None):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, base_path: str = None):
        """
        Inicializa el contenedor.
        
        Args:
            base_path: Ruta base del proyecto (donde están los JSON)
        """
        if self._initialized:
            return
        
        self._base_path = base_path or os.path.dirname(os.path.abspath(__file__))
        
        # Inicializar repositorios (lazy loading)
        self._inventory_repo: Optional[InventoryRepository] = None
        self._sales_repo: Optional[SalesRepository] = None
        self._user_repo: Optional[UserRepository] = None
        self._audit_repo: Optional[AuditRepository] = None
        self._settings_repo: Optional[SettingsRepository] = None
        
        # Inicializar servicios (lazy loading)
        self._inventory_service: Optional[InventoryService] = None
        self._sales_service: Optional[SalesService] = None
        self._payment_service: Optional[PaymentService] = None
        self._cart_service: Optional[CartService] = None
        self._audit_service: Optional[AuditService] = None
        self._user_service: Optional[UserService] = None
        
        self._initialized = True
    
    # =========================================================================
    # REPOSITORIOS
    # =========================================================================
    
    @property
    def inventory_repo(self) -> InventoryRepository:
        """Repositorio de inventario (singleton)."""
        if self._inventory_repo is None:
            self._inventory_repo = InventoryRepository(self._base_path)
        return self._inventory_repo
    
    @property
    def sales_repo(self) -> SalesRepository:
        """Repositorio de ventas (singleton)."""
        if self._sales_repo is None:
            self._sales_repo = SalesRepository(self._base_path)
        return self._sales_repo
    
    @property
    def user_repo(self) -> UserRepository:
        """Repositorio de usuarios (singleton)."""
        if self._user_repo is None:
            self._user_repo = UserRepository(self._base_path)
        return self._user_repo
    
    @property
    def audit_repo(self) -> AuditRepository:
        """Repositorio de auditoría (singleton)."""
        if self._audit_repo is None:
            self._audit_repo = AuditRepository(self._base_path)
        return self._audit_repo
    
    @property
    def settings_repo(self) -> SettingsRepository:
        """Repositorio de configuraciones (singleton)."""
        if self._settings_repo is None:
            self._settings_repo = SettingsRepository(self._base_path)
        return self._settings_repo
    
    # =========================================================================
    # SERVICIOS
    # =========================================================================
    
    @property
    def audit_service(self) -> AuditService:
        """Servicio de auditoría (singleton)."""
        if self._audit_service is None:
            self._audit_service = AuditService(self.audit_repo)
        return self._audit_service
    
    @property
    def inventory_service(self) -> InventoryService:
        """Servicio de inventario (singleton)."""
        if self._inventory_service is None:
            self._inventory_service = InventoryService(
                self.inventory_repo,
                self.audit_service
            )
        return self._inventory_service
    
    @property
    def sales_service(self) -> SalesService:
        """Servicio de ventas (singleton)."""
        if self._sales_service is None:
            self._sales_service = SalesService(
                self.sales_repo,
                self.inventory_service,
                self.audit_service
            )
        return self._sales_service
    
    @property
    def payment_service(self) -> PaymentService:
        """Servicio de pagos (singleton)."""
        if self._payment_service is None:
            self._payment_service = PaymentService(
                self.sales_repo,
                self.audit_service
            )
        return self._payment_service
    
    @property
    def cart_service(self) -> CartService:
        """Servicio de carrito (singleton)."""
        if self._cart_service is None:
            self._cart_service = CartService(self.inventory_service)
        return self._cart_service
    
    @property
    def user_service(self) -> UserService:
        """Servicio de usuarios (singleton)."""
        if self._user_service is None:
            self._user_service = UserService(
                self.user_repo,
                self.settings_repo,
                self.audit_service
            )
        return self._user_service
    
    # =========================================================================
    # UTILIDADES
    # =========================================================================
    
    def reset(self) -> None:
        """
        Reinicia todas las instancias.
        Útil para testing o para recargar datos.
        """
        self._inventory_repo = None
        self._sales_repo = None
        self._user_repo = None
        self._audit_repo = None
        self._settings_repo = None
        
        self._inventory_service = None
        self._sales_service = None
        self._payment_service = None
        self._cart_service = None
        self._audit_service = None
        self._user_service = None
    
    @classmethod
    def get_instance(cls, base_path: str = None) -> 'AppContainer':
        """
        Obtiene la instancia singleton del contenedor.
        
        Args:
            base_path: Ruta base (solo se usa en primera llamada)
            
        Returns:
            Instancia del contenedor
        """
        if cls._instance is None:
            return cls(base_path)
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """Elimina la instancia singleton (útil para tests)."""
        if cls._instance is not None:
            cls._instance.reset()
            cls._instance = None


# Función helper para obtener el contenedor global
def get_container(base_path: str = None) -> AppContainer:
    """
    Obtiene el contenedor de dependencias global.
    
    Args:
        base_path: Ruta base del proyecto
        
    Returns:
        Instancia del contenedor
    """
    return AppContainer.get_instance(base_path)
