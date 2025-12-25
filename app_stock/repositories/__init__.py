# ==============================================================================
# CAPA DE REPOSITORIOS - Acceso a datos
# ==============================================================================
# Esta capa encapsula todo el acceso a la persistencia (actualmente JSON).
# Cuando se migre a MySQL, solo hay que modificar esta capa.
# Las interfaces (métodos públicos) permanecen iguales.
#
# ESTRUCTURA:
# ├── interfaces.py      → Protocolos/Interfaces (contratos para MySQL)
# ├── base.py           → Clases base para JSON (DictRepository, ListRepository)
# ├── user_repository.py → Acceso a users.json
# ├── sales_repository.py → Acceso a sales.json
# ├── inventory_repository.py → Acceso a inventory.json
# ├── audit_repository.py → Acceso a audit.json
# └── settings_repository.py → Acceso a user_settings.json
#
# MIGRACIÓN A MYSQL:
# 1. Crear mysql_user_repository.py que implemente IUserRepository
# 2. Cambiar importación en app_container.py
# 3. Los services NO requieren cambios (dependen de interfaces)
# ==============================================================================

# Interfaces (para type hints y MySQL futuro)
from .interfaces import (
    IRepository,
    IDictRepository,
    IListRepository,
    IUserRepository,
    ISalesRepository,
    IInventoryRepository,
    IAuditRepository,
    ISettingsRepository,
)

# Implementaciones concretas (JSON)
from .base import BaseRepository, DictRepository, ListRepository
from .inventory_repository import InventoryRepository
from .sales_repository import SalesRepository
from .user_repository import UserRepository
from .audit_repository import AuditRepository
from .settings_repository import SettingsRepository

__all__ = [
    # Interfaces
    'IRepository',
    'IDictRepository',
    'IListRepository',
    'IUserRepository',
    'ISalesRepository',
    'IInventoryRepository',
    'IAuditRepository',
    'ISettingsRepository',
    
    # Clases base
    'BaseRepository',
    'DictRepository',
    'ListRepository',
    
    # Implementaciones JSON
    'InventoryRepository',
    'SalesRepository',
    'UserRepository',
    'AuditRepository',
    'SettingsRepository',
]
