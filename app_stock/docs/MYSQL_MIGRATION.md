# 🗄️ Guía de Migración a MySQL

## Resumen de Arquitectura Actual

```
┌─────────────────────────────────────────────────────────────┐
│                       MAIN.PY                                │
│                   (Rutas/Controllers)                        │
│  Solo orquesta: recibe request → llama service → responde   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    APP_CONTAINER.PY                          │
│                 (Inyección de Dependencias)                  │
│      get_container() → singleton con todos los servicios    │
└─────────────────────────────────────────────────────────────┘
                            │
          ┌─────────────────┴─────────────────┐
          ▼                                   ▼
┌───────────────────────┐         ┌───────────────────────────┐
│      SERVICES/        │         │      REPOSITORIES/        │
│  (Lógica de negocio)  │         │   (Persistencia - JSON)   │
│                       │◄───────►│                           │
│  • Validaciones       │         │  • Leer/escribir datos    │
│  • Permisos           │         │  • CRUD básico            │
│  • Reglas de negocio  │         │  • NO tiene lógica        │
│  • Seguridad          │         │                           │
└───────────────────────┘         └───────────────────────────┘
          │                                   │
          │                                   ▼
          │                       ┌───────────────────────────┐
          │                       │    INTERFACES.PY          │
          │                       │   (Contratos/Protocols)   │
          └──────────────────────►│                           │
                                  │  IUserRepository          │
                                  │  ISalesRepository         │
                                  │  IInventoryRepository     │
                                  │  IAuditRepository         │
                                  │  ISettingsRepository      │
                                  └───────────────────────────┘
```

---

## 🔒 Rol Protegido: China Import

El rol **"China Import"** es un SUPER USUARIO blindado al 100%:

- ❌ **No puede ser eliminado** (delete_user lo rechaza)
- ❌ **No puede perder su rol** (change_role lo rechaza)
- ❌ **Nadie puede asignarse este rol** (change_role lo rechaza)

Esta protección está en `services/user_service.py` y funciona **independientemente** de si usas JSON o MySQL.

```python
# Constantes de protección
PROTECTED_ROLE = 'China Import'
VALID_ROLES = frozenset(['admin', 'operador', 'China Import'])

# Métodos de protección
UserService.is_protected_role(role)           # ¿Es rol protegido?
UserService.is_super_user(username)           # ¿Usuario tiene rol protegido?
UserService.validate_role_modification(...)   # Validación central
```

---

## 📋 Checklist de Migración

### Paso 1: Crear repositorios MySQL

Crear una carpeta `repositories/mysql/` con:

```
repositories/
├── mysql/
│   ├── __init__.py
│   ├── base_mysql.py        # Conexión y helpers
│   ├── user_mysql.py        # MySQLUserRepository
│   ├── sales_mysql.py       # MySQLSalesRepository
│   ├── inventory_mysql.py   # MySQLInventoryRepository
│   ├── audit_mysql.py       # MySQLAuditRepository
│   └── settings_mysql.py    # MySQLSettingsRepository
```

### Paso 2: Implementar interfaces

Cada repositorio MySQL debe implementar la interfaz correspondiente:

```python
# repositories/mysql/user_mysql.py
from repositories.interfaces import IUserRepository
from typing import Dict, Any, Optional

class MySQLUserRepository(IUserRepository):
    def __init__(self, connection_string: str):
        self.db = mysql.connector.connect(...)
    
    def get_all(self) -> Dict[str, Any]:
        # SELECT * FROM users
        ...
    
    def save(self, data: Dict[str, Any]) -> None:
        # INSERT/UPDATE users
        ...
    
    def get_by_key(self, key: str) -> Optional[Any]:
        # SELECT * FROM users WHERE username = ?
        ...
    
    def delete_by_key(self, key: str) -> bool:
        # DELETE FROM users WHERE username = ?
        ...
```

### Paso 3: Cambiar importaciones en app_container.py

```python
# ANTES (JSON):
from repositories import UserRepository

# DESPUÉS (MySQL):
from repositories.mysql import MySQLUserRepository as UserRepository
```

### Paso 4: Probar

```bash
python -m pytest tests/
python main.py  # Verificar que todo funciona
```

---

## 📁 Archivos Clave

| Archivo | Propósito |
|---------|-----------|
| `app_container.py` | Inyección de dependencias (cambiar repos aquí) |
| `repositories/interfaces.py` | Contratos que MySQL debe cumplir |
| `services/user_service.py` | Protección de "China Import" |
| `services/*.py` | Lógica de negocio (NO tocar para MySQL) |
| `main.py` | Rutas Flask (NO tocar para MySQL) |

---

## ⚠️ Reglas Importantes

1. **NUNCA** pongas lógica de negocio en repositorios
2. **NUNCA** pongas SQL en services
3. **SIEMPRE** usa las interfaces como guía
4. **SIEMPRE** prueba que `China Import` siga protegido después de migrar

---

## 🧪 Tests de Verificación Post-Migración

```python
# Ejecutar para verificar protección China Import
def test_china_import_protection():
    container = get_container(".")
    user_service = container.user_service
    
    # No se puede eliminar usuario China Import
    result = user_service.delete_user("admin_china")  # usuario con rol China Import
    assert result == (False, "No se puede eliminar un Super Usuario")
    
    # No se puede cambiar rol de China Import
    result = user_service.change_role("admin_china", "operador")
    assert result == (False, "No se puede modificar el rol de un Super Usuario")
    
    # No se puede asignar rol China Import a otro usuario
    result = user_service.change_role("otro_usuario", "China Import")
    assert result == (False, "El rol 'China Import' no puede ser asignado")
```

---

## 📝 Notas Técnicas

- Los servicios usan **Protocol** (typing) para las interfaces
- El contenedor es un **Singleton** (una sola instancia por app)
- Los repositorios JSON están en la carpeta `repositories/`
- Los tests están en `tests/`

---

**Última actualización:** Preparación para MySQL (JSON actual funcionando)
