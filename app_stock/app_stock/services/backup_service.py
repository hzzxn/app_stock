# ==============================================================================
# SERVICIO DE BACKUPS AUTOMÁTICOS
# ==============================================================================
# Crea backups diarios de los archivos de datos del sistema en formato ZIP.
# Mantiene solo los últimos N backups (rotación automática).
#
# FORMATO: backup_YYYY-MM-DD.zip
#
# PREPARADO PARA MYSQL:
# - La interfaz create_backup() y rotate_backups() no cambia
# - Solo se reemplazaría _backup_json_files() por _backup_mysql_database()
# - La lógica de rotación es independiente del origen de datos
# ==============================================================================

import os
import shutil
import zipfile
from datetime import datetime, timedelta
from typing import List, Optional, Tuple


class BackupService:
    """
    Servicio para gestión de backups automáticos.
    
    Responsabilidades:
    - Crear backups diarios en formato ZIP
    - Rotar backups antiguos (mantener solo los últimos N)
    - Verificar integridad de backups
    
    Uso:
        backup_service = BackupService(base_path='/app')
        backup_service.run_daily_backup()
    """
    
    # Archivos a respaldar (JSON actual, MySQL después será dump)
    DATA_FILES = [
        'inventory.json',
        'sales.json',
        'audit.json',
        'users.json',
        'user_settings.json',
    ]
    
    # Cantidad de backups a mantener
    MAX_BACKUPS = 7
    
    # Nombre de la carpeta de backups
    BACKUP_DIR_NAME = 'backups'
    
    def __init__(self, base_path: str):
        """
        Inicializa el servicio de backups.
        
        Args:
            base_path: Ruta base del proyecto (donde están los JSON)
        """
        self.base_path = base_path
        self.backup_root = os.path.join(base_path, self.BACKUP_DIR_NAME)
        
        # Crear carpeta de backups si no existe
        os.makedirs(self.backup_root, exist_ok=True)
    
    def _get_today_zip_path(self) -> str:
        """Retorna la ruta del archivo ZIP de backup del día actual."""
        today = datetime.now().strftime('%Y-%m-%d')
        return os.path.join(self.backup_root, f'backup_{today}.zip')
    
    def _backup_exists_today(self) -> bool:
        """Verifica si ya existe un backup del día actual."""
        zip_path = self._get_today_zip_path()
        return os.path.exists(zip_path) and os.path.getsize(zip_path) > 0
    
    def _get_existing_backups(self) -> List[str]:
        """
        Obtiene lista de archivos ZIP de backup ordenados por fecha (más reciente primero).
        
        Returns:
            Lista de nombres de archivos backup_YYYY-MM-DD.zip ordenados descendentemente
        """
        if not os.path.exists(self.backup_root):
            return []
        
        backups = []
        for item in os.listdir(self.backup_root):
            item_path = os.path.join(self.backup_root, item)
            # Validar que sea archivo ZIP con formato correcto
            if os.path.isfile(item_path) and item.startswith('backup_') and item.endswith('.zip'):
                # Extraer fecha del nombre: backup_YYYY-MM-DD.zip
                try:
                    date_str = item[7:-4]  # Quitar "backup_" y ".zip"
                    datetime.strptime(date_str, '%Y-%m-%d')
                    backups.append(item)
                except ValueError:
                    # Ignorar archivos que no tienen formato válido
                    continue
        
        # Ordenar descendentemente (más reciente primero)
        backups.sort(reverse=True)
        return backups
    
    def _backup_json_files(self, zip_path: str) -> Tuple[int, List[str]]:
        """
        Crea un archivo ZIP con los archivos JSON de datos.
        
        Args:
            zip_path: Ruta del archivo ZIP a crear
            
        Returns:
            Tupla (archivos_agregados, lista_de_errores)
        """
        added = 0
        errors = []
        
        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for filename in self.DATA_FILES:
                    src = os.path.join(self.base_path, filename)
                    
                    if os.path.exists(src):
                        try:
                            zf.write(src, filename)  # Solo el nombre, sin ruta
                            added += 1
                        except Exception as e:
                            errors.append(f"{filename}: {str(e)}")
                    # Si no existe, no es error (puede ser sistema nuevo)
                    
        except Exception as e:
            errors.append(f"Error creando ZIP: {str(e)}")
            # Eliminar archivo ZIP corrupto si existe
            if os.path.exists(zip_path):
                try:
                    os.remove(zip_path)
                except:
                    pass
        
        return added, errors
    
    def _delete_old_backups(self) -> int:
        """
        Elimina backups antiguos, manteniendo solo los últimos MAX_BACKUPS.
        
        Returns:
            Cantidad de backups eliminados
        """
        backups = self._get_existing_backups()
        deleted = 0
        
        # Si hay más de MAX_BACKUPS, eliminar los más antiguos
        if len(backups) > self.MAX_BACKUPS:
            to_delete = backups[self.MAX_BACKUPS:]
            
            for backup_name in to_delete:
                backup_path = os.path.join(self.backup_root, backup_name)
                try:
                    os.remove(backup_path)
                    deleted += 1
                    print(f"[BACKUP] Eliminado backup antiguo: {backup_name}")
                except Exception as e:
                    print(f"[BACKUP ERROR] No se pudo eliminar {backup_name}: {e}")
        
        return deleted
    
    def create_backup(self, force: bool = False) -> dict:
        """
        Crea un backup ZIP de los archivos de datos.
        
        Args:
            force: Si True, crea backup aunque ya exista uno hoy
            
        Returns:
            Dict con resultado: {success, message, files_added, errors}
        """
        result = {
            'success': False,
            'message': '',
            'files_added': 0,
            'errors': [],
            'backup_path': None
        }
        
        # Verificar si ya existe backup del día
        if not force and self._backup_exists_today():
            result['success'] = True
            result['message'] = 'Backup del día ya existe'
            result['backup_path'] = self._get_today_zip_path()
            print(f"[BACKUP] Backup ya existe hoy: {os.path.basename(self._get_today_zip_path())}")
            return result
        
        # Crear backup ZIP
        zip_path = self._get_today_zip_path()
        
        try:
            added, errors = self._backup_json_files(zip_path)
            
            result['success'] = added > 0
            result['files_added'] = added
            result['errors'] = errors
            result['backup_path'] = zip_path
            
            if added > 0:
                size_kb = round(os.path.getsize(zip_path) / 1024, 2)
                result['message'] = f'Backup creado: {added} archivos ({size_kb} KB)'
                print(f"[BACKUP] Backup creado: {os.path.basename(zip_path)} ({added} archivos, {size_kb} KB)")
            else:
                result['message'] = 'No se encontraron archivos para respaldar'
                
        except Exception as e:
            result['message'] = f'Error al crear backup: {str(e)}'
            result['errors'].append(str(e))
            print(f"[BACKUP ERROR] {e}")
        
        return result
    
    def rotate_backups(self) -> dict:
        """
        Ejecuta la rotación de backups (elimina antiguos).
        
        Returns:
            Dict con resultado: {deleted_count, remaining_count}
        """
        deleted = self._delete_old_backups()
        remaining = len(self._get_existing_backups())
        
        return {
            'deleted_count': deleted,
            'remaining_count': remaining
        }
    
    def run_daily_backup(self) -> dict:
        """
        Ejecuta el proceso completo de backup diario.
        
        1. Verifica si ya existe backup del día
        2. Si no existe, crea uno nuevo
        3. Rota backups antiguos
        
        Returns:
            Dict con resultado completo
        """
        result = {
            'backup': None,
            'rotation': None
        }
        
        # Crear backup
        result['backup'] = self.create_backup()
        
        # Rotar backups antiguos
        result['rotation'] = self.rotate_backups()
        
        return result
    
    def get_backup_status(self) -> dict:
        """
        Obtiene el estado actual de los backups.
        
        Returns:
            Dict con información de backups existentes
        """
        backups = self._get_existing_backups()
        
        backup_info = []
        for backup_name in backups:
            backup_path = os.path.join(self.backup_root, backup_name)
            
            if os.path.exists(backup_path):
                size_bytes = os.path.getsize(backup_path)
                
                # Contar archivos dentro del ZIP
                try:
                    with zipfile.ZipFile(backup_path, 'r') as zf:
                        file_count = len(zf.namelist())
                except:
                    file_count = 0
                
                # Extraer fecha del nombre: backup_YYYY-MM-DD.zip
                date_str = backup_name[7:-4]
                
                backup_info.append({
                    'filename': backup_name,
                    'date': date_str,
                    'files': file_count,
                    'size_bytes': size_bytes,
                    'size_kb': round(size_bytes / 1024, 2)
                })
        
        return {
            'total_backups': len(backups),
            'max_backups': self.MAX_BACKUPS,
            'backup_root': self.backup_root,
            'backups': backup_info,
            'today_exists': self._backup_exists_today()
        }


# ==============================================================================
# FUNCIONES HELPER (para uso directo sin instanciar)
# ==============================================================================

_backup_service: Optional[BackupService] = None


def get_backup_service(base_path: str = None) -> BackupService:
    """
    Obtiene la instancia singleton del servicio de backup.
    
    Args:
        base_path: Ruta base del proyecto (requerido en primera llamada)
        
    Returns:
        Instancia de BackupService
    """
    global _backup_service
    
    if _backup_service is None:
        if base_path is None:
            raise ValueError("base_path es requerido en la primera llamada")
        _backup_service = BackupService(base_path)
    
    return _backup_service


def run_startup_backup(base_path: str) -> None:
    """
    Ejecuta el backup al iniciar la aplicación.
    
    Esta función está diseñada para ser llamada desde main.py al inicio.
    Maneja todos los errores internamente para no romper la app.
    
    Args:
        base_path: Ruta base del proyecto
    """
    try:
        service = get_backup_service(base_path)
        result = service.run_daily_backup()
        
        if result['backup']['success']:
            if result['backup']['files_added'] > 0:
                print(f"[BACKUP] ✓ Backup diario completado")
            # Si ya existía, el mensaje ya se imprimió en create_backup()
        else:
            if result['backup']['errors']:
                print(f"[BACKUP] ⚠ Errores: {result['backup']['errors']}")
                
    except Exception as e:
        # Nunca romper la app por un error de backup
        print(f"[BACKUP ERROR] No se pudo ejecutar backup: {e}")
