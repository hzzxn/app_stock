# ==============================================================================
# REPOSITORIO BASE - Funcionalidad común para acceso a archivos JSON
# ==============================================================================

import json
import os
from typing import Any, Dict, List, Optional
from abc import ABC, abstractmethod
import threading


class BaseRepository(ABC):
    """
    Clase base abstracta para todos los repositorios.
    Proporciona funcionalidad común para lectura/escritura de archivos JSON
    con manejo de concurrencia básico mediante locks.
    
    Al migrar a MySQL:
    - Esta clase se reemplazará por una conexión a base de datos
    - Los métodos load/save se convertirán en queries SQL
    - Los locks se reemplazarán por transacciones de BD
    """
    
    # Lock global para evitar escrituras concurrentes a archivos
    _file_lock = threading.RLock()
    
    def __init__(self, file_path: str):
        """
        Inicializa el repositorio con la ruta al archivo JSON.
        
        Args:
            file_path: Ruta absoluta al archivo JSON de datos
        """
        self.file_path = file_path
        self._ensure_file_exists()
    
    def _ensure_file_exists(self) -> None:
        """Crea el archivo con datos vacíos si no existe."""
        if not os.path.exists(self.file_path):
            self._write_raw(self._empty_data())
    
    @abstractmethod
    def _empty_data(self) -> Any:
        """
        Retorna la estructura de datos vacía para este repositorio.
        Debe ser implementado por cada repositorio concreto.
        
        Returns:
            Estructura vacía (dict, list, etc.) según el repositorio
        """
        pass
    
    def _read_raw(self) -> Any:
        """
        Lee los datos crudos del archivo JSON.
        
        Returns:
            Datos parseados del JSON
            
        Raises:
            json.JSONDecodeError: Si el archivo tiene JSON inválido
            IOError: Si hay error de lectura
        """
        with self._file_lock:
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                # Si el archivo está corrupto o no existe, retornar datos vacíos
                return self._empty_data()
    
    def _write_raw(self, data: Any) -> None:
        """
        Escribe datos al archivo JSON.
        
        Args:
            data: Datos a serializar y escribir
            
        Raises:
            IOError: Si hay error de escritura
        """
        with self._file_lock:
            # Escribir a archivo temporal primero para atomicidad
            temp_path = self.file_path + '.tmp'
            try:
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                # Reemplazar archivo original (operación atómica en la mayoría de sistemas)
                os.replace(temp_path, self.file_path)
            except Exception:
                # Limpiar archivo temporal si algo falla
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise
    
    def reload(self) -> None:
        """
        Recarga los datos desde el archivo.
        Útil para sincronizar después de cambios externos.
        """
        # La implementación base solo lee el archivo
        # Las subclases pueden sobrescribir para actualizar caché
        pass


class DictRepository(BaseRepository):
    """
    Repositorio base para datos almacenados como diccionario.
    El ID es la clave del diccionario.
    
    Ejemplo: inventory.json -> {1: {...}, 2: {...}}
    """
    
    def _empty_data(self) -> Dict:
        """Retorna diccionario vacío."""
        return {}
    
    def get_all(self) -> Dict[str, Any]:
        """
        Obtiene todos los registros.
        
        Returns:
            Diccionario con todos los datos
        """
        return self._read_raw()
    
    def get_by_id(self, record_id: Any) -> Optional[Dict[str, Any]]:
        """
        Obtiene un registro por su ID.
        
        Args:
            record_id: ID del registro (puede ser int o str)
            
        Returns:
            Datos del registro o None si no existe
        """
        data = self._read_raw()
        # Soportar tanto int como str como clave
        return data.get(record_id) or data.get(str(record_id))
    
    def save_all(self, data: Dict[str, Any]) -> None:
        """
        Guarda todos los registros (reemplazo completo).
        
        Args:
            data: Diccionario completo de datos
        """
        self._write_raw(data)
    
    def update(self, record_id: Any, record_data: Dict[str, Any]) -> None:
        """
        Actualiza un registro específico.
        
        Args:
            record_id: ID del registro
            record_data: Nuevos datos del registro
        """
        data = self._read_raw()
        data[record_id] = record_data
        self._write_raw(data)
    
    def delete(self, record_id: Any) -> Optional[Dict[str, Any]]:
        """
        Elimina un registro.
        
        Args:
            record_id: ID del registro a eliminar
            
        Returns:
            Datos del registro eliminado o None si no existía
        """
        data = self._read_raw()
        removed = data.pop(record_id, None)
        if removed is not None:
            self._write_raw(data)
        return removed


class ListRepository(BaseRepository):
    """
    Repositorio base para datos almacenados como lista.
    
    Ejemplo: sales.json -> [{...}, {...}]
    """
    
    def _empty_data(self) -> List:
        """Retorna lista vacía."""
        return []
    
    def get_all(self) -> List[Dict[str, Any]]:
        """
        Obtiene todos los registros.
        
        Returns:
            Lista con todos los datos
        """
        data = self._read_raw()
        return data if isinstance(data, list) else []
    
    def save_all(self, data: List[Dict[str, Any]]) -> None:
        """
        Guarda todos los registros (reemplazo completo).
        
        Args:
            data: Lista completa de datos
        """
        self._write_raw(data)
    
    def append(self, record: Dict[str, Any]) -> None:
        """
        Agrega un registro al final.
        
        Args:
            record: Datos del nuevo registro
        """
        data = self.get_all()
        data.append(record)
        self._write_raw(data)
    
    def find_by(self, field: str, value: Any) -> Optional[Dict[str, Any]]:
        """
        Busca un registro por un campo específico.
        
        Args:
            field: Nombre del campo
            value: Valor a buscar
            
        Returns:
            Primer registro que coincide o None
        """
        for record in self.get_all():
            if record.get(field) == value:
                return record
        return None
    
    def find_all_by(self, field: str, value: Any) -> List[Dict[str, Any]]:
        """
        Busca todos los registros que coinciden con un campo.
        
        Args:
            field: Nombre del campo
            value: Valor a buscar
            
        Returns:
            Lista de registros que coinciden
        """
        return [r for r in self.get_all() if r.get(field) == value]
    
    def update_where(self, field: str, value: Any, updates: Dict[str, Any]) -> bool:
        """
        Actualiza registros que coinciden con un campo.
        
        Args:
            field: Nombre del campo para filtrar
            value: Valor a buscar
            updates: Campos a actualizar
            
        Returns:
            True si se actualizó al menos un registro
        """
        data = self.get_all()
        updated = False
        for record in data:
            if record.get(field) == value:
                record.update(updates)
                updated = True
        if updated:
            self._write_raw(data)
        return updated
