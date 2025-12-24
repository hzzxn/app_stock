# -*- coding: utf-8 -*-
"""
Test del sistema de backups
"""
import os
import sys

# Asegurar que el proyecto esté en el path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.backup_service import BackupService

def test_backup():
    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print(f"Base path: {base_path}")
    print()
    
    # Crear servicio
    bs = BackupService(base_path)
    
    # Ejecutar backup
    print("=== EJECUTANDO BACKUP ===")
    result = bs.run_daily_backup()
    
    print(f"Backup exitoso: {result['backup']['success']}")
    print(f"Mensaje: {result['backup']['message']}")
    print(f"Archivos copiados: {result['backup']['files_copied']}")
    if result['backup']['errors']:
        print(f"Errores: {result['backup']['errors']}")
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
            print(f"  - {b['date']}: {b['files']} archivos, {b['size_kb']} KB")
    else:
        print("No hay backups")

if __name__ == '__main__':
    test_backup()
