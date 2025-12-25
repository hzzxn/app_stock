# ==============================================================================
# REPOSITORIO DE AUDITORÍA
# ==============================================================================
# Encapsula todo el acceso a audit.json
# La auditoría se almacena como lista: [{log1}, {log2}, ...]
# ==============================================================================

import os
from typing import Any, Dict, List, Optional
from datetime import datetime
from .base import ListRepository


class AuditRepository(ListRepository):
    """
    Repositorio para gestión del log de auditoría.
    
    Formato de datos en audit.json:
    [
        {
            "type": "VENTA",
            "user": "admin",
            "message": "Venta R0001 creada por admin",
            "timestamp": "2024-01-01 10:00:00",
            "related_id": "R0001",
            "details": {...}
        }
    ]
    
    Nota: El sistema también soporta formato legacy con campos:
    - "action" en lugar de "type"
    - "ts" en lugar de "timestamp"
    - "sku" en lugar de "related_id"
    """
    
    # Límite de registros para evitar archivos muy grandes
    MAX_LOGS = 10000
    
    def __init__(self, base_path: str):
        """
        Inicializa el repositorio de auditoría.
        
        Args:
            base_path: Ruta base del proyecto
        """
        file_path = os.path.join(base_path, 'audit.json')
        super().__init__(file_path)
    
    def load(self) -> List[Dict[str, Any]]:
        """
        Carga todos los logs de auditoría.
        
        Returns:
            Lista de logs (más recientes primero)
        """
        logs = self.get_all()
        # Ordenar por timestamp descendente
        return sorted(
            logs, 
            key=lambda x: x.get('timestamp', x.get('ts', '')), 
            reverse=True
        )
    
    def save(self, logs: List[Dict[str, Any]]) -> None:
        """
        Guarda todos los logs.
        Aplica límite de registros para evitar archivos muy grandes.
        
        Args:
            logs: Lista de logs
        """
        # Mantener solo los últimos MAX_LOGS registros
        if len(logs) > self.MAX_LOGS:
            logs = logs[:self.MAX_LOGS]
        self.save_all(logs)
    
    def log(
        self, 
        log_type: str, 
        user: str, 
        message: str,
        related_id: str = '',
        details: Dict[str, Any] = None
    ) -> None:
        """
        Registra un nuevo evento de auditoría.
        
        Args:
            log_type: Tipo de evento (VENTA, PAGO, STOCK, PRODUCTO, SISTEMA)
            user: Usuario que realizó la acción
            message: Mensaje descriptivo humanizado
            related_id: ID relacionado (receipt, SKU, etc.)
            details: Detalles adicionales
        """
        log_entry = {
            'type': log_type,
            'user': user or 'sistema',
            'message': message,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'related_id': related_id,
            'details': details or {}
        }
        
        logs = self.get_all()  # Sin ordenar para append eficiente
        logs.insert(0, log_entry)  # Insertar al inicio (más reciente primero)
        self.save(logs)
    
    def log_legacy(
        self, 
        action: str, 
        user: str, 
        pid: int = None,
        sku: str = None,
        details: Dict[str, Any] = None
    ) -> None:
        """
        Registra un evento en formato legacy (compatibilidad).
        
        Args:
            action: Nombre de la acción
            user: Usuario
            pid: ID de producto (opcional)
            sku: SKU (opcional)
            details: Detalles adicionales
        """
        log_entry = {
            'action': action,
            'user': user or 'sistema',
            'ts': datetime.utcnow().isoformat() + 'Z',
            'details': details or {}
        }
        if pid is not None:
            log_entry['pid'] = pid
        if sku:
            log_entry['sku'] = sku
        
        logs = self.get_all()
        logs.insert(0, log_entry)
        self.save(logs)
    
    def get_logs_by_type(self, log_type: str) -> List[Dict[str, Any]]:
        """
        Filtra logs por tipo.
        
        Args:
            log_type: Tipo a filtrar (VENTA, PAGO, etc.)
            
        Returns:
            Lista de logs del tipo especificado
        """
        logs = self.load()
        return [
            log for log in logs
            if (log.get('type') or log.get('action', '')) == log_type
        ]
    
    def get_logs_by_user(self, user: str) -> List[Dict[str, Any]]:
        """
        Filtra logs por usuario.
        
        Args:
            user: Nombre de usuario
            
        Returns:
            Lista de logs del usuario
        """
        logs = self.load()
        return [log for log in logs if log.get('user') == user]
    
    def get_logs_by_date_range(
        self, 
        from_date: str = None, 
        to_date: str = None
    ) -> List[Dict[str, Any]]:
        """
        Filtra logs por rango de fechas.
        
        Args:
            from_date: Fecha inicio (YYYY-MM-DD o ISO)
            to_date: Fecha fin (YYYY-MM-DD o ISO)
            
        Returns:
            Lista de logs en el rango
        """
        logs = self.load()
        
        if not from_date and not to_date:
            return logs
        
        def parse_timestamp(ts: str) -> Optional[datetime]:
            """Parsea timestamp en varios formatos."""
            for fmt in [
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S+00:00"
            ]:
                try:
                    return datetime.strptime(ts.split('.')[0].replace('Z', ''), fmt.replace('Z', ''))
                except ValueError:
                    continue
            return None
        
        from_dt = parse_timestamp(from_date) if from_date else None
        to_dt = parse_timestamp(to_date) if to_date else None
        
        filtered = []
        for log in logs:
            ts = log.get('timestamp', log.get('ts', ''))
            dt = parse_timestamp(ts)
            if dt is None:
                continue
            if from_dt and dt < from_dt:
                continue
            if to_dt and dt > to_dt:
                continue
            filtered.append(log)
        
        return filtered
    
    def search_logs(
        self, 
        query: str = '',
        log_type: str = None,
        user: str = None,
        from_date: str = None,
        to_date: str = None
    ) -> List[Dict[str, Any]]:
        """
        Búsqueda avanzada de logs con múltiples filtros.
        
        Args:
            query: Texto de búsqueda global
            log_type: Filtrar por tipo
            user: Filtrar por usuario
            from_date: Fecha inicio
            to_date: Fecha fin
            
        Returns:
            Lista de logs que coinciden
        """
        logs = self.load()
        
        # Aplicar filtros
        if log_type:
            logs = [
                log for log in logs
                if (log.get('type') or log.get('action', '')) == log_type
            ]
        
        if user:
            logs = [log for log in logs if log.get('user') == user]
        
        if from_date or to_date:
            logs = self.get_logs_by_date_range(from_date, to_date)
        
        # Búsqueda de texto
        if query:
            query_lower = query.lower()
            filtered = []
            for log in logs:
                # Buscar en varios campos
                searchable = [
                    log.get('type', ''),
                    log.get('action', ''),
                    log.get('user', ''),
                    log.get('message', ''),
                    str(log.get('related_id', '')),
                    str(log.get('sku', ''))
                ]
                if any(query_lower in s.lower() for s in searchable if s):
                    filtered.append(log)
            logs = filtered
        
        return logs
    
    def get_recent_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Obtiene los logs más recientes.
        
        Args:
            limit: Número máximo de logs
            
        Returns:
            Lista de logs más recientes
        """
        logs = self.load()
        return logs[:limit]
    
    def get_unique_users(self) -> List[str]:
        """
        Obtiene lista de usuarios únicos que aparecen en los logs.
        
        Returns:
            Lista de nombres de usuario
        """
        logs = self.load()
        users = set()
        for log in logs:
            user = log.get('user')
            if user:
                users.add(user)
        return sorted(list(users))
    
    def get_unique_types(self) -> List[str]:
        """
        Obtiene lista de tipos únicos de eventos.
        
        Returns:
            Lista de tipos de eventos
        """
        logs = self.load()
        types = set()
        for log in logs:
            log_type = log.get('type') or log.get('action')
            if log_type:
                types.add(log_type)
        return sorted(list(types))
