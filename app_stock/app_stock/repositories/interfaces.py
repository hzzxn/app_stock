# ==============================================================================
# INTERFACES DE REPOSITORIOS - PREPARADO PARA MYSQL
# ==============================================================================
# 
# Este archivo define las interfaces (protocolos) que todos los repositorios
# deben implementar. Esto permite:
#
# 1. INDEPENDENCIA DE ALMACENAMIENTO
#    - Los servicios dependen de interfaces, NO de implementaciones concretas
#    - Cambiar JSON → MySQL solo requiere nueva implementación
#
# 2. TESTING
#    - Fácil crear mocks que implementen estas interfaces
#    - Tests unitarios sin tocar archivos reales
#
# 3. DOCUMENTACIÓN
#    - Contratos claros de qué hace cada repositorio
#
# MIGRACIÓN A MYSQL:
# 1. Crear nuevas clases: MySQLUserRepository, MySQLSalesRepository, etc.
# 2. Hacer que implementen estas interfaces
# 3. Cambiar instanciación en app_container.py
# 4. Los servicios NO requieren cambios
#
# ==============================================================================

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


# ==============================================================================
# INTERFACES BASE
# ==============================================================================

@runtime_checkable
class IRepository(Protocol):
    """
    Interfaz base para todos los repositorios.
    Define las operaciones mínimas que cualquier repositorio debe soportar.
    """
    
    def reload(self) -> None:
        """Recarga datos desde el almacenamiento."""
        ...


@runtime_checkable  
class IDictRepository(IRepository, Protocol):
    """
    Interfaz para repositorios basados en diccionarios.
    Usado por: Inventario, Usuarios, Settings.
    """
    
    def get_all(self) -> Dict[str, Any]:
        """Obtiene todos los registros."""
        ...
    
    def get_by_id(self, record_id: Any) -> Optional[Dict[str, Any]]:
        """Obtiene un registro por ID."""
        ...
    
    def save_all(self, data: Dict[str, Any]) -> None:
        """Guarda todos los registros."""
        ...
    
    def update(self, record_id: Any, record_data: Dict[str, Any]) -> None:
        """Actualiza un registro."""
        ...
    
    def delete(self, record_id: Any) -> Optional[Dict[str, Any]]:
        """Elimina un registro."""
        ...


@runtime_checkable
class IListRepository(IRepository, Protocol):
    """
    Interfaz para repositorios basados en listas.
    Usado por: Ventas, Auditoría.
    """
    
    def get_all(self) -> List[Dict[str, Any]]:
        """Obtiene todos los registros."""
        ...
    
    def save_all(self, data: List[Dict[str, Any]]) -> None:
        """Guarda todos los registros."""
        ...
    
    def append(self, record: Dict[str, Any]) -> None:
        """Agrega un registro al final."""
        ...


# ==============================================================================
# INTERFACES ESPECÍFICAS POR DOMINIO
# ==============================================================================

@runtime_checkable
class IUserRepository(Protocol):
    """
    Interfaz para el repositorio de usuarios.
    
    NOTA MYSQL: Esta interfaz define el contrato que debe cumplir
    cualquier implementación (JSONUserRepository, MySQLUserRepository).
    """
    
    def load(self) -> Dict[str, Dict[str, Any]]:
        """Carga todos los usuarios."""
        ...
    
    def save(self, users: Dict[str, Dict[str, Any]]) -> None:
        """Guarda todos los usuarios."""
        ...
    
    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        """Obtiene un usuario por nombre."""
        ...
    
    def user_exists(self, username: str) -> bool:
        """Verifica si un usuario existe."""
        ...
    
    def create_user(self, username: str, password_hash: str, role: str) -> bool:
        """Crea un nuevo usuario."""
        ...
    
    def update_user(self, username: str, updates: Dict[str, Any]) -> bool:
        """Actualiza datos de un usuario."""
        ...
    
    def delete_user(self, username: str) -> bool:
        """Elimina un usuario."""
        ...
    
    def update_role(self, username: str, new_role: str) -> bool:
        """Cambia el rol de un usuario."""
        ...
    
    def update_password(self, username: str, password_hash: str) -> bool:
        """Cambia la contraseña de un usuario."""
        ...


@runtime_checkable
class ISalesRepository(Protocol):
    """
    Interfaz para el repositorio de ventas.
    """
    
    def load(self) -> List[Dict[str, Any]]:
        """Carga todas las ventas."""
        ...
    
    def save(self, sales: List[Dict[str, Any]]) -> None:
        """Guarda todas las ventas."""
        ...
    
    def get_by_receipt(self, receipt: str) -> Optional[Dict[str, Any]]:
        """Obtiene una venta por número de recibo."""
        ...
    
    def create_sale(self, sale_data: Dict[str, Any]) -> str:
        """Crea una nueva venta, retorna el receipt."""
        ...
    
    def update_sale(self, receipt: str, updates: Dict[str, Any]) -> bool:
        """Actualiza una venta existente."""
        ...
    
    def get_next_receipt_number(self) -> str:
        """Genera el siguiente número de recibo."""
        ...


@runtime_checkable
class IInventoryRepository(Protocol):
    """
    Interfaz para el repositorio de inventario.
    """
    
    def load(self) -> Dict[int, Dict[str, Any]]:
        """Carga todo el inventario."""
        ...
    
    def save(self, inventory: Dict[int, Dict[str, Any]]) -> None:
        """Guarda todo el inventario."""
        ...
    
    def get_product(self, pid: int) -> Optional[Dict[str, Any]]:
        """Obtiene un producto por ID."""
        ...
    
    def product_exists(self, pid: int) -> bool:
        """Verifica si un producto existe."""
        ...
    
    def create_product(self, pid: int, data: Dict[str, Any]) -> None:
        """Crea un nuevo producto."""
        ...
    
    def update_product(self, pid: int, data: Dict[str, Any]) -> None:
        """Actualiza un producto."""
        ...
    
    def delete_product(self, pid: int) -> Optional[Dict[str, Any]]:
        """Elimina un producto."""
        ...


@runtime_checkable
class IAuditRepository(Protocol):
    """
    Interfaz para el repositorio de auditoría.
    """
    
    def load(self) -> List[Dict[str, Any]]:
        """Carga todos los logs."""
        ...
    
    def save(self, logs: List[Dict[str, Any]]) -> None:
        """Guarda todos los logs."""
        ...
    
    def log(
        self, 
        log_type: str, 
        user: str, 
        message: str,
        related_id: str,
        details: Dict[str, Any]
    ) -> None:
        """Registra un evento de auditoría."""
        ...


@runtime_checkable
class ISettingsRepository(Protocol):
    """
    Interfaz para el repositorio de configuraciones de usuario.
    """
    
    def load(self) -> Dict[str, Dict[str, Any]]:
        """Carga todas las configuraciones."""
        ...
    
    def save(self, settings: Dict[str, Dict[str, Any]]) -> None:
        """Guarda todas las configuraciones."""
        ...
    
    def get_user_settings(self, username: str) -> Dict[str, Any]:
        """Obtiene las preferencias de un usuario."""
        ...
    
    def set_user_settings(self, username: str, user_settings: Dict[str, Any]) -> None:
        """Establece las preferencias de un usuario."""
        ...
    
    def get_theme(self, username: str) -> str:
        """Obtiene el tema de un usuario."""
        ...
    
    def set_theme(self, username: str, theme: str) -> None:
        """Establece el tema de un usuario."""
        ...
