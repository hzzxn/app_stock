# ==============================================================================
# REPOSITORIO DE CONFIGURACIONES DE USUARIO
# ==============================================================================
# Encapsula todo el acceso a user_settings.json
# Almacena preferencias de usuario como tema, etc.
# ==============================================================================

import os
from typing import Any, Dict, Optional
from .base import DictRepository


class SettingsRepository(DictRepository):
    """
    Repositorio para preferencias de usuario.
    
    Formato de datos en user_settings.json:
    {
        "admin": {"theme": "dark"},
        "operador1": {"theme": "light"}
    }
    """
    
    def __init__(self, base_path: str):
        """
        Inicializa el repositorio de settings.
        
        Args:
            base_path: Ruta base del proyecto
        """
        file_path = os.path.join(base_path, 'user_settings.json')
        super().__init__(file_path)
    
    def load(self) -> Dict[str, Dict[str, Any]]:
        """
        Carga todas las configuraciones.
        
        Returns:
            Diccionario {username: settings}
        """
        return self.get_all()
    
    def save(self, settings: Dict[str, Dict[str, Any]]) -> None:
        """
        Guarda todas las configuraciones.
        
        Args:
            settings: Diccionario completo de configuraciones
        """
        self.save_all(settings)
    
    def get_user_settings(self, username: str) -> Dict[str, Any]:
        """
        Obtiene configuraciones de un usuario.
        
        Args:
            username: Nombre de usuario
            
        Returns:
            Diccionario de configuraciones (vacío si no existe)
        """
        settings = self.load()
        return settings.get(username, {})
    
    def set_user_settings(self, username: str, user_settings: Dict[str, Any]) -> None:
        """
        Establece configuraciones de un usuario.
        
        Args:
            username: Nombre de usuario
            user_settings: Configuraciones a guardar
        """
        settings = self.load()
        settings[username] = user_settings
        self.save(settings)
    
    def get_setting(self, username: str, key: str, default: Any = None) -> Any:
        """
        Obtiene una configuración específica.
        
        Args:
            username: Nombre de usuario
            key: Clave de la configuración
            default: Valor por defecto si no existe
            
        Returns:
            Valor de la configuración
        """
        user_settings = self.get_user_settings(username)
        return user_settings.get(key, default)
    
    def set_setting(self, username: str, key: str, value: Any) -> None:
        """
        Establece una configuración específica.
        
        Args:
            username: Nombre de usuario
            key: Clave de la configuración
            value: Valor a guardar
        """
        settings = self.load()
        if username not in settings:
            settings[username] = {}
        settings[username][key] = value
        self.save(settings)
    
    # =========================================================================
    # Métodos específicos para configuraciones comunes
    # =========================================================================
    
    def get_theme(self, username: str) -> str:
        """
        Obtiene el tema preferido del usuario.
        
        Args:
            username: Nombre de usuario
            
        Returns:
            Tema ('dark' o 'light')
        """
        return self.get_setting(username, 'theme', 'dark')
    
    def set_theme(self, username: str, theme: str) -> None:
        """
        Establece el tema preferido del usuario.
        
        Args:
            username: Nombre de usuario
            theme: Tema a establecer ('dark' o 'light')
        """
        if theme not in ('dark', 'light'):
            theme = 'dark'
        self.set_setting(username, 'theme', theme)
    
    def delete_user_settings(self, username: str) -> bool:
        """
        Elimina todas las configuraciones de un usuario.
        
        Args:
            username: Nombre de usuario
            
        Returns:
            True si se eliminaron
        """
        settings = self.load()
        if username not in settings:
            return False
        del settings[username]
        self.save(settings)
        return True
