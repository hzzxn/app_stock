# ==============================================================================
# REPOSITORIO DE USUARIOS
# ==============================================================================
# Encapsula todo el acceso a users.json
# Los usuarios se almacenan como diccionario: {username: {password, role}}
# ==============================================================================

import os
from typing import Any, Dict, List, Optional

from app_stock.repositories.base import DictRepository


class UserRepository(DictRepository):
    """
    Repositorio para gestión de usuarios.
    
    Formato de datos en users.json:
    {
        "admin": {"password": "hashed_pwd", "role": "admin"},
        "operador1": {"password": "hashed_pwd", "role": "operador"}
    }
    """
    
    def __init__(self, base_path: str):
        """
        Inicializa el repositorio de usuarios.
        
        Args:
            base_path: Ruta base del proyecto
        """
        file_path = os.path.join(base_path, 'users.json')
        super().__init__(file_path)
    
    def load(self) -> Dict[str, Dict[str, Any]]:
        """
        Carga todos los usuarios.
        
        Returns:
            Diccionario {username: datos}
        """
        return self.get_all()
    
    def save(self, users: Dict[str, Dict[str, Any]]) -> None:
        """
        Guarda todos los usuarios.
        
        Args:
            users: Diccionario completo de usuarios
        """
        self.save_all(users)
    
    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene un usuario por su nombre.
        
        Args:
            username: Nombre de usuario
            
        Returns:
            Datos del usuario o None
        """
        users = self.load()
        return users.get(username)
    
    def user_exists(self, username: str) -> bool:
        """
        Verifica si un usuario existe.
        
        Args:
            username: Nombre de usuario
            
        Returns:
            True si existe
        """
        return username in self.load()
    
    def create_user(self, username: str, password_hash: str, role: str = 'operador') -> bool:
        """
        Crea un nuevo usuario.
        
        Args:
            username: Nombre de usuario
            password_hash: Hash de la contraseña
            role: Rol del usuario
            
        Returns:
            True si se creó, False si ya existía
        """
        users = self.load()
        if username in users:
            return False
        users[username] = {
            'password': password_hash,
            'role': role
        }
        self.save(users)
        return True
    
    def update_user(self, username: str, updates: Dict[str, Any]) -> bool:
        """
        Actualiza datos de un usuario.
        
        Args:
            username: Nombre de usuario
            updates: Campos a actualizar
            
        Returns:
            True si se actualizó
        """
        users = self.load()
        if username not in users:
            return False
        users[username].update(updates)
        self.save(users)
        return True
    
    def delete_user(self, username: str) -> bool:
        """
        Elimina un usuario.
        
        Args:
            username: Nombre de usuario
            
        Returns:
            True si se eliminó
        """
        users = self.load()
        if username not in users:
            return False
        del users[username]
        self.save(users)
        return True
    
    def update_role(self, username: str, new_role: str) -> bool:
        """
        Cambia el rol de un usuario.
        
        Args:
            username: Nombre de usuario
            new_role: Nuevo rol
            
        Returns:
            True si se actualizó
        """
        return self.update_user(username, {'role': new_role})
    
    def update_password(self, username: str, password_hash: str) -> bool:
        """
        Cambia la contraseña de un usuario.
        
        Args:
            username: Nombre de usuario
            password_hash: Nuevo hash de contraseña
            
        Returns:
            True si se actualizó
        """
        return self.update_user(username, {'password': password_hash})
    
    def get_users_by_role(self, role: str) -> List[str]:
        """
        Obtiene lista de usuarios con un rol específico.
        
        Args:
            role: Rol a filtrar
            
        Returns:
            Lista de nombres de usuario
        """
        users = self.load()
        return [
            username for username, data in users.items()
            if data.get('role') == role
        ]
    
    def count_admins(self) -> int:
        """
        Cuenta cuántos administradores hay.
        
        Returns:
            Número de admins
        """
        return len(self.get_users_by_role('admin'))
    
    def get_all_usernames(self) -> List[str]:
        """
        Obtiene lista de todos los nombres de usuario.
        
        Returns:
            Lista de usernames
        """
        return list(self.load().keys())
    
    # NOTA: La validación de credenciales se hace SOLO en UserService
    # usando check_password_hash para seguridad.
    # El repositorio solo maneja persistencia, no lógica de autenticación.
    
    def get_user_role(self, username: str) -> Optional[str]:
        """
        Obtiene el rol de un usuario.
        
        Args:
            username: Nombre de usuario
            
        Returns:
            Rol del usuario o None
        """
        user = self.get_user(username)
        return user.get('role') if user else None
