# -*- coding: utf-8 -*-
"""
Test del sistema de backups (formato ZIP)
"""
import os
import sys
import zipfile

# Asegurar que el proyecto esté en el path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Importación directa para evitar dependencias circulares
from datetime import datetime
from typing import List, Optional, Tuple

# Copia simplificada del servicio para testing independiente
class BackupServiceTest:
    DATA_FILES = ['inventory.json', 'sales.json', 'audit.json', 'users.json', 'user_settings.json']
    MAX_BACKUPS = 7
    BACKUP_DIR_NAME = 'backups'
    
    def __init__(self, base_path: str):
        self.base_path = base_path
        self.backup_root = os.path.join(base_path, self.BACKUP_DIR_NAME)
        os.makedirs(self.backup_root, exist_ok=True)
    
    def _get_today_zip_path(self) -> str:
        today = datetime.now().strftime('%Y-%m-%d')
        return os.path.join(self.backup_root, f'backup_{today}.zip')
    
    def _backup_exists_today(self) -> bool:
        zip_path = self._get_today_zip_path()
        return os.path.exists(zip_path) and os.path.getsize(zip_path) > 0
    
    def _get_existing_backups(self) -> List[str]:
        if not os.path.exists(self.backup_root):
            return []
        backups = []
        for item in os.listdir(self.backup_root):
            item_path = os.path.join(self.backup_root, item)
            if os.path.isfile(item_path) and item.startswith('backup_') and item.endswith('.zip'):
                try:
                    date_str = item[7:-4]
                    datetime.strptime(date_str, '%Y-%m-%d')
                    backups.append(item)
                except ValueError:
                    continue
        backups.sort(reverse=True)
        return backups
    
    def create_backup(self, force: bool = False) -> dict:
        result = {'success': False, 'message': '', 'files_added': 0, 'errors': [], 'backup_path': None}
        
        if not force and self._backup_exists_today():
            result['success'] = True
            result['message'] = 'Backup del día ya existe'
            result['backup_path'] = self._get_today_zip_path()
            return result
        
        zip_path = self._get_today_zip_path()
        added = 0
        errors = []
        
        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for filename in self.DATA_FILES:
                    src = os.path.join(self.base_path, filename)
                    if os.path.exists(src):
                        try:
                            zf.write(src, filename)
                            added += 1
                        except Exception as e:
                            errors.append(f"{filename}: {str(e)}")
            
            result['success'] = added > 0
            result['files_added'] = added
            result['errors'] = errors
            result['backup_path'] = zip_path
            
            if added > 0:
                size_kb = round(os.path.getsize(zip_path) / 1024, 2)
                result['message'] = f'Backup creado: {added} archivos ({size_kb} KB)'
        except Exception as e:
            result['message'] = f'Error: {str(e)}'
            result['errors'].append(str(e))
        
        return result
    
    def get_backup_status(self) -> dict:
        backups = self._get_existing_backups()
        backup_info = []
        
        for backup_name in backups:
            backup_path = os.path.join(self.backup_root, backup_name)
            if os.path.exists(backup_path):
                size_bytes = os.path.getsize(backup_path)
                try:
                    with zipfile.ZipFile(backup_path, 'r') as zf:
                        file_count = len(zf.namelist())
                except:
                    file_count = 0
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


def test_backup():
    print(f"Base path: {project_root}")
    print()
    
    # Crear servicio
    bs = BackupServiceTest(project_root)
    
    # Ejecutar backup
    print("=== EJECUTANDO BACKUP ===")
    result = bs.create_backup()
    
    print(f"Backup exitoso: {result['success']}")
    print(f"Mensaje: {result['message']}")
    print(f"Archivos en ZIP: {result['files_added']}")
    if result['errors']:
        print(f"Errores: {result['errors']}")
    print()
    
    # Mostrar estado
    print("=== ESTADO DE BACKUPS ===")
    status = bs.get_backup_status()
    print(f"Total backups: {status['total_backups']}")
    print(f"Max permitidos: {status['max_backups']}")
    print(f"Carpeta: {status['backup_root']}")
    print(f"Backup de hoy existe: {status['today_exists']}")
    print()
    
    if status['backups']:
        print("Backups existentes:")
        for b in status['backups']:
            print(f"  - {b['filename']}: {b['files']} archivos, {b['size_kb']} KB")
    else:
        print("No hay backups")
    
    # Verificar contenido del ZIP
    if result['backup_path'] and os.path.exists(result['backup_path']):
        print()
        print("=== CONTENIDO DEL ZIP ===")
        with zipfile.ZipFile(result['backup_path'], 'r') as zf:
            for info in zf.infolist():
                print(f"  - {info.filename}: {info.file_size} bytes")

if __name__ == '__main__':
    test_backup()
