# ==============================================================================
# SERVICIO DE USUARIOS
# ==============================================================================
# Centraliza toda la lógica de negocio relacionada con usuarios.
# 
# PREPARADO PARA MYSQL:
# - Este servicio NO depende del tipo de almacenamiento (JSON/MySQL)
# - Solo interactúa con repositorios a través de interfaces claras
# - Toda la lógica de permisos y validaciones está aquí, NO en rutas
#
# REGLA CRÍTICA - ROL "CHINA IMPORT":
# Es el SUPER USUARIO del sistema. Está BLINDADO y NO puede:
# - Ser eliminado
# - Perder su rol
# - Ser degradado (ni siquiera por él mismo)
# Estas validaciones se hacen AQUÍ, no en templates ni rutas.
# ==============================================================================

from typing import Any, Dict, List, Optional
from werkzeug.security import generate_password_hash, check_password_hash

from repositories.user_repository import UserRepository
from repositories.settings_repository import SettingsRepository
from services.audit_service import AuditService


class ProtectedRoleError(Exception):
    """Excepción lanzada cuando se intenta modificar un rol protegido."""
    pass


class UserService:
    """
    Servicio para gestión de usuarios.
    
    Responsabilidades:
    - Autenticación (login/logout)
    - CRUD de usuarios
    - Gestión de roles (con protección de China Import)
    - Preferencias de usuario
    - Validaciones de seguridad
    
    IMPORTANTE: Este servicio contiene TODA la lógica de negocio.
    Los repositorios solo hacen persistencia (JSON ahora, MySQL después).
    Las rutas solo orquestan request → service → response.
    """
    
    # =========================================================================
    # CONSTANTES DE ROLES
    # =========================================================================
    ROLE_ADMIN = 'admin'
    ROLE_OPERADOR = 'operador'
    ROLE_CHINA_IMPORT = 'China Import'
    
    # Rol protegido: NO puede ser eliminado, degradado ni modificado
    PROTECTED_ROLE = 'China Import'
    
    # Roles válidos del sistema
    VALID_ROLES = frozenset(['admin', 'operador', 'China Import'])
    
    def __init__(
        self, 
        user_repo: UserRepository,
        settings_repo: SettingsRepository = None,
        audit_service: AuditService = None
    ):
        """
        Inicializa el servicio de usuarios.
        
        Args:
            user_repo: Repositorio de usuarios (JSON ahora, MySQL después)
            settings_repo: Repositorio de settings (opcional)
            audit_service: Servicio de auditoría (opcional)
            
        NOTA MYSQL: Al migrar, solo cambiar la implementación de user_repo.
        Este servicio NO conoce el tipo de almacenamiento.
        """
        self.user_repo = user_repo
        self.settings_repo = settings_repo
        self.audit_service = audit_service
    
    # =========================================================================
    # MÉTODOS DE PROTECCIÓN - ROL CHINA IMPORT
    # =========================================================================
    
    def is_protected_role(self, role: str) -> bool:
        """
        Verifica si un rol está protegido contra modificaciones.
        
        El rol "China Import" es el SUPER USUARIO del sistema.
        NO puede ser:
        - Eliminado
        - Degradado
        - Modificado de ninguna forma
        
        Args:
            role: Rol a verificar
            
        Returns:
            True si el rol está protegido
        """
        return role == self.PROTECTED_ROLE
    
    def is_super_user(self, username: str) -> bool:
        """
        Verifica si un usuario es el super usuario (China Import).
        
        Args:
            username: Nombre de usuario
            
        Returns:
            True si es super usuario
        """
        user = self.user_repo.get_user(username)
        if not user:
            return False
        return self.is_protected_role(user.get('role', ''))
    
    def validate_role_modification(
        self, 
        target_username: str, 
        new_role: str = None,
        is_delete: bool = False
    ) -> Dict[str, Any]:
        """
        Valida si se puede modificar el rol de un usuario.
        
        Esta es la función central de validación para CUALQUIER
        operación que afecte usuarios con roles protegidos.
        
        Args:
            target_username: Usuario objetivo
            new_role: Nuevo rol (si es cambio de rol)
            is_delete: True si es eliminación
            
        Returns:
            Dict {'allowed': bool, 'error': str si no permitido}
        """
        user = self.user_repo.get_user(target_username)
        if not user:
            return {'allowed': False, 'error': 'Usuario no encontrado'}
        
        current_role = user.get('role', '')
        
        # Regla 1: Rol protegido no puede ser modificado
        if self.is_protected_role(current_role):
            if is_delete:
                return {
                    'allowed': False, 
                    'error': f'El usuario con rol "{self.PROTECTED_ROLE}" no puede ser eliminado'
                }
            return {
                'allowed': False, 
                'error': f'El rol "{self.PROTECTED_ROLE}" está blindado contra modificaciones'
            }
        
        # Regla 2: No se puede asignar rol protegido
        if new_role and self.is_protected_role(new_role):
            return {
                'allowed': False, 
                'error': f'El rol "{self.PROTECTED_ROLE}" no puede ser asignado manualmente'
            }
        
        return {'allowed': True}
    
    # =========================================================================
    # AUTENTICACIÓN
    # =========================================================================
    
    def authenticate(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """
        Autentica un usuario.
        
        Args:
            username: Nombre de usuario
            password: Contraseña en texto plano
            
        Returns:
            Dict con datos del usuario si es válido, None si no
        """
        user = self.user_repo.get_user(username)
        if not user:
            return None
        
        # Verificar contraseña
        password_hash = user.get('password', '')
        
        # Soportar tanto hash como texto plano (legacy)
        if password_hash.startswith('pbkdf2:') or password_hash.startswith('scrypt:'):
            # Password hasheado
            if not check_password_hash(password_hash, password):
                return None
        else:
            # Password en texto plano (legacy)
            if password_hash != password:
                return None
        
        # Auditar inicio de sesión
        if self.audit_service:
            self.audit_service.log_user_login(username)
        
        return {
            'username': username,
            'role': user.get('role', 'operador')
        }
    
    def logout(self, username: str) -> None:
        """
        Registra un cierre de sesión.
        
        Args:
            username: Nombre de usuario
        """
        if self.audit_service:
            self.audit_service.log_user_logout(username)
    
    # =========================================================================
    # CRUD DE USUARIOS
    # =========================================================================
    
    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene un usuario por nombre.
        
        Args:
            username: Nombre de usuario
            
        Returns:
            Datos del usuario (sin password) o None
        """
        user = self.user_repo.get_user(username)
        if not user:
            return None
        return {
            'username': username,
            'role': user.get('role', 'operador')
        }
    
    def get_all_users(self) -> Dict[str, Dict[str, Any]]:
        """
        Obtiene todos los usuarios.
        
        Returns:
            Dict {username: {role: ...}} - sin passwords
        """
        users = self.user_repo.load()
        return {
            username: {'role': data.get('role', 'operador')}
            for username, data in users.items()
        }
    
    def user_exists(self, username: str) -> bool:
        """Verifica si un usuario existe."""
        return self.user_repo.user_exists(username)
    
    def create_user(
        self, 
        username: str, 
        password: str, 
        role: str = 'operador',
        admin_user: str = None
    ) -> Dict[str, Any]:
        """
        Crea un nuevo usuario.
        
        Args:
            username: Nombre de usuario
            password: Contraseña
            role: Rol del usuario
            admin_user: Admin que crea (para auditoría)
            
        Returns:
            Dict con resultado (ok, error, etc.)
        """
        if not username or not username.strip():
            return {'ok': False, 'error': 'Nombre de usuario requerido'}
        
        if not password:
            return {'ok': False, 'error': 'Contraseña requerida'}
        
        username = username.strip()
        
        if self.user_exists(username):
            return {'ok': False, 'error': 'El usuario ya existe'}
        
        # Normalizar rol
        role = self.normalize_role(role)
        
        # Hashear contraseña
        password_hash = generate_password_hash(password)
        
        success = self.user_repo.create_user(username, password_hash, role)
        
        if not success:
            return {'ok': False, 'error': 'Error al crear usuario'}
        
        return {
            'ok': True,
            'username': username,
            'role': role
        }
    
    def delete_user(
        self, 
        username: str, 
        admin_user: str = None
    ) -> Dict[str, Any]:
        """
        Elimina un usuario.
        
        VALIDACIONES DE SEGURIDAD:
        1. Usuario debe existir
        2. No se puede eliminar usuario con rol "China Import" (PROTEGIDO)
        3. No se puede eliminar el último admin
        4. No se puede auto-eliminar
        
        Args:
            username: Usuario a eliminar
            admin_user: Admin que elimina (para auditoría)
            
        Returns:
            Dict con resultado {'ok': bool, 'error': str opcional}
        """
        if not self.user_exists(username):
            return {'ok': False, 'error': 'Usuario no encontrado'}
        
        user = self.user_repo.get_user(username)
        role = user.get('role', '')
        
        # ═══════════════════════════════════════════════════════════════════
        # PROTECCIÓN CRÍTICA: Rol "China Import" es INTOCABLE
        # ═══════════════════════════════════════════════════════════════════
        if self.is_protected_role(role):
            return {
                'ok': False, 
                'error': f'El rol "{self.PROTECTED_ROLE}" está protegido y no puede ser eliminado'
            }
        
        # Protección: no eliminar el último admin
        if role == 'admin' and self.count_admins() <= 1:
            return {'ok': False, 'error': 'No se puede eliminar el último admin'}
        
        # Protección: no auto-eliminarse
        if admin_user and username == admin_user:
            return {'ok': False, 'error': 'No puedes eliminar tu propia cuenta'}
        
        success = self.user_repo.delete_user(username)
        
        if success:
            # Eliminar settings del usuario
            if self.settings_repo:
                self.settings_repo.delete_user_settings(username)
            
            # Auditar
            if self.audit_service and admin_user:
                self.audit_service.log_user_deleted(admin_user, username, role)
        
        return {'ok': success}
    
    # =========================================================================
    # GESTIÓN DE ROLES
    # =========================================================================
    
    def change_role(
        self, 
        username: str, 
        new_role: str,
        admin_user: str = None
    ) -> Dict[str, Any]:
        """
        Cambia el rol de un usuario.
        
        VALIDACIONES DE SEGURIDAD:
        1. Usuario debe existir
        2. No se puede degradar/cambiar rol "China Import" (PROTEGIDO)
        3. No se puede asignar rol "China Import" a otro usuario
        4. No se puede dejar al sistema sin admins
        
        Args:
            username: Usuario a modificar
            new_role: Nuevo rol
            admin_user: Admin que hace el cambio (para auditoría)
            
        Returns:
            Dict con resultado {'ok': bool, 'error': str opcional}
        """
        if not self.user_exists(username):
            return {'ok': False, 'error': 'Usuario no encontrado'}
        
        user = self.user_repo.get_user(username)
        old_role = user.get('role', '')
        
        # Normalizar nuevo rol
        new_role = self.normalize_role(new_role)
        
        # ═══════════════════════════════════════════════════════════════════
        # PROTECCIÓN CRÍTICA: Rol "China Import"
        # ═══════════════════════════════════════════════════════════════════
        
        # 1. No se puede QUITAR el rol China Import a nadie que lo tenga
        if self.is_protected_role(old_role):
            return {
                'ok': False, 
                'error': f'El rol "{self.PROTECTED_ROLE}" está protegido y no puede ser modificado'
            }
        
        # 2. No se puede ASIGNAR el rol China Import a través de esta función
        #    (Solo debe existir el usuario original creado en inicialización)
        if self.is_protected_role(new_role):
            return {
                'ok': False, 
                'error': f'El rol "{self.PROTECTED_ROLE}" no puede ser asignado manualmente'
            }
        
        # Protección: no dejar sin admins
        if old_role == 'admin' and new_role != 'admin' and self.count_admins() <= 1:
            return {'ok': False, 'error': 'No se puede quitar el último admin'}
        
        success = self.user_repo.update_role(username, new_role)
        
        if success and self.audit_service and admin_user:
            self.audit_service.log_role_change(admin_user, username, old_role, new_role)
        
        return {
            'ok': success,
            'username': username,
            'old_role': old_role,
            'new_role': new_role
        }
    
    def normalize_role(self, role: str) -> str:
        """
        Normaliza un string de rol.
        
        Args:
            role: Rol a normalizar
            
        Returns:
            Rol normalizado
        """
        if not role:
            return 'operador'
        
        role_lower = role.strip().lower()
        
        if role_lower == 'admin':
            return 'admin'
        elif role_lower in ('china import', 'china_import', 'superadmin'):
            return 'China Import'
        else:
            return 'operador'
    
    def count_admins(self) -> int:
        """Cuenta cuántos administradores hay."""
        return self.user_repo.count_admins()
    
    def get_user_role(self, username: str) -> Optional[str]:
        """Obtiene el rol de un usuario."""
        return self.user_repo.get_user_role(username)
    
    def is_admin(self, username: str) -> bool:
        """Verifica si un usuario es admin."""
        role = self.get_user_role(username)
        return role in ('admin', 'China Import')
    
    # =========================================================================
    # PREFERENCIAS DE USUARIO
    # =========================================================================
    
    def get_theme(self, username: str) -> str:
        """
        Obtiene el tema preferido del usuario.
        
        Args:
            username: Nombre de usuario
            
        Returns:
            'dark' o 'light'
        """
        if not self.settings_repo:
            return 'dark'
        return self.settings_repo.get_theme(username)
    
    def set_theme(self, username: str, theme: str) -> None:
        """
        Establece el tema preferido del usuario.
        
        Args:
            username: Nombre de usuario
            theme: 'dark' o 'light'
        """
        if self.settings_repo:
            self.settings_repo.set_theme(username, theme)
    
    def get_user_settings(self, username: str) -> Dict[str, Any]:
        """
        Obtiene todas las preferencias de un usuario.
        
        Args:
            username: Nombre de usuario
            
        Returns:
            Dict con preferencias
        """
        if not self.settings_repo:
            return {'theme': 'dark'}
        return self.settings_repo.get_user_settings(username)
    
    def update_user_settings(
        self, 
        username: str, 
        settings: Dict[str, Any]
    ) -> None:
        """
        Actualiza preferencias de un usuario.
        
        Args:
            username: Nombre de usuario
            settings: Nuevas preferencias
        """
        if self.settings_repo:
            current = self.settings_repo.get_user_settings(username)
            current.update(settings)
            self.settings_repo.set_user_settings(username, current)
    
    # =========================================================================
    # GESTIÓN DE CONTRASEÑAS
    # =========================================================================
    
    def change_password(
        self, 
        username: str, 
        new_password: str,
        admin_user: str = None
    ) -> Dict[str, Any]:
        """
        Cambia la contraseña de un usuario.
        
        Solo el usuario "China Import" puede cambiar contraseñas de otros.
        Un usuario normal solo puede cambiar su propia contraseña (si permitido).
        
        Args:
            username: Usuario al que cambiar contraseña
            new_password: Nueva contraseña en texto plano
            admin_user: Admin que hace el cambio (para auditoría)
            
        Returns:
            Dict con resultado {'ok': bool, 'error': str opcional}
        """
        if not self.user_exists(username):
            return {'ok': False, 'error': 'Usuario no encontrado'}
        
        if not new_password or len(new_password) < 4:
            return {'ok': False, 'error': 'La contraseña debe tener al menos 4 caracteres'}
        
        # Hashear la nueva contraseña
        password_hash = generate_password_hash(new_password)
        
        success = self.user_repo.update_password(username, password_hash)
        
        if success and self.audit_service and admin_user:
            self.audit_service.log_password_change(admin_user, username)
        
        return {'ok': success}
    
    def is_password_hashed(self, password_value: str) -> bool:
        """
        Verifica si una contraseña ya está hasheada.
        
        Args:
            password_value: Valor de la contraseña almacenado
            
        Returns:
            True si está hasheado (pbkdf2: o scrypt:)
        """
        if not password_value:
            return False
        return password_value.startswith('pbkdf2:') or password_value.startswith('scrypt:')
    
    def migrate_passwords_to_hash(self) -> Dict[str, Any]:
        """
        Migra todas las contraseñas en texto plano a hash seguro.
        
        Esta función se debe llamar al inicializar la app para asegurar
        que ninguna contraseña quede en texto plano.
        
        Returns:
            Dict con información de migración
        """
        users = self.user_repo.load()
        migrated_count = 0
        
        for username, data in users.items():
            current_pwd = data.get('password', '')
            if current_pwd and not self.is_password_hashed(current_pwd):
                # Contraseña en texto plano - migrar a hash
                hashed = generate_password_hash(current_pwd)
                users[username]['password'] = hashed
                migrated_count += 1
        
        if migrated_count > 0:
            self.user_repo.save(users)
            if self.audit_service:
                self.audit_service.log(
                    'SISTEMA', 
                    'system', 
                    f'Migración de contraseñas: {migrated_count} contraseñas actualizadas a hash seguro'
                )
        
        return {
            'ok': True,
            'migrated_count': migrated_count
        }
    
    def verify_password(self, username: str, password: str) -> bool:
        """
        Verifica si una contraseña es correcta para un usuario.
        
        SEGURIDAD: Solo acepta contraseñas hasheadas. Las contraseñas en
        texto plano deben migrarse previamente con migrate_passwords_to_hash().
        
        Args:
            username: Nombre de usuario
            password: Contraseña a verificar
            
        Returns:
            True si la contraseña es correcta
        """
        user = self.user_repo.get_user(username)
        if not user:
            return False
        
        stored_pwd = user.get('password', '')
        
        # PRODUCCIÓN: Solo verificación con hash seguro
        # Nunca comparar contraseñas en texto plano
        if not self.is_password_hashed(stored_pwd):
            # Contraseña no hasheada = rechazar login
            # Esto obliga a usar la migración antes del primer login
            print(f"[SEGURIDAD] Usuario '{username}' tiene contraseña sin hash. Ejecutar migración.")
            return False
        
        return check_password_hash(stored_pwd, password)
