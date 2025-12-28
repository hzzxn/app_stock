# ==============================================================================
# REPOSITORIO DE VENTAS
# ==============================================================================
# Encapsula todo el acceso a sales.json
# Las ventas se almacenan como lista: [{venta1}, {venta2}, ...]
# ==============================================================================

import os
from typing import Any, Dict, List, Optional
from datetime import datetime

from app_stock.repositories.base import ListRepository


class SalesRepository(ListRepository):
    """
    Repositorio para gestión de ventas.
    
    Formato de datos en sales.json:
    [
        {
            "receipt": "R0001",
            "user": "admin",
            "ts": "2024-01-01T10:00:00Z",
            "status": "CANCELADO",
            "items": [...],
            "payments": [...],
            ...
        }
    ]
    """
    
    def __init__(self, base_path: str):
        """
        Inicializa el repositorio de ventas.
        
        Args:
            base_path: Ruta base del proyecto
        """
        file_path = os.path.join(base_path, 'sales.json')
        super().__init__(file_path)
    
    def load(self) -> List[Dict[str, Any]]:
        """
        Carga todas las ventas.
        
        Returns:
            Lista de ventas
        """
        return self.get_all()
    
    def save(self, sales: List[Dict[str, Any]]) -> None:
        """
        Guarda todas las ventas.
        
        Args:
            sales: Lista completa de ventas
        """
        self.save_all(sales)
    
    def get_by_receipt(self, receipt: str) -> Optional[Dict[str, Any]]:
        """
        Busca una venta por número de boleta.
        
        Args:
            receipt: Número de boleta (ej: "R0001")
            
        Returns:
            Datos de la venta o None
        """
        return self.find_by('receipt', receipt)
    
    def create_sale(self, sale_data: Dict[str, Any]) -> str:
        """
        Crea una nueva venta.
        
        Args:
            sale_data: Datos de la venta (debe incluir 'receipt')
            
        Returns:
            Número de boleta asignado
        """
        self.append(sale_data)
        return sale_data.get('receipt', '')
    
    def update_sale(self, receipt: str, updates: Dict[str, Any]) -> bool:
        """
        Actualiza una venta existente.
        
        Args:
            receipt: Número de boleta
            updates: Campos a actualizar
            
        Returns:
            True si se actualizó
        """
        sales = self.load()
        for sale in sales:
            if sale.get('receipt') == receipt:
                sale.update(updates)
                self.save(sales)
                return True
        return False
    
    def get_next_receipt_number(self) -> str:
        """
        Genera el siguiente número de boleta.
        Formato: RXXXX donde XXXX es número secuencial.
        
        Returns:
            Siguiente número de boleta disponible
        """
        sales = self.load()
        max_num = 0
        for sale in sales:
            receipt = sale.get('receipt', '')
            if receipt.startswith('R'):
                try:
                    num = int(receipt[1:])
                    max_num = max(max_num, num)
                except ValueError:
                    continue
        return f"R{max_num + 1:04d}"
    
    def get_sales_by_status(self, status: str) -> List[Dict[str, Any]]:
        """
        Obtiene ventas filtradas por estado.
        
        Args:
            status: Estado a filtrar (CANCELADO, POR PAGAR, etc.)
            
        Returns:
            Lista de ventas con ese estado
        """
        return self.find_all_by('status', status)
    
    def get_sales_by_user(self, user: str) -> List[Dict[str, Any]]:
        """
        Obtiene ventas realizadas por un usuario.
        
        Args:
            user: Nombre de usuario
            
        Returns:
            Lista de ventas del usuario
        """
        return self.find_all_by('user', user)
    
    def get_sales_by_date_range(
        self, 
        from_date: Optional[str] = None, 
        to_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Obtiene ventas en un rango de fechas.
        
        Args:
            from_date: Fecha inicio (ISO format)
            to_date: Fecha fin (ISO format)
            
        Returns:
            Lista de ventas en el rango
        """
        sales = self.load()
        
        if not from_date and not to_date:
            return sales
        
        def parse_date(ts_str: str) -> Optional[datetime]:
            """Parsea timestamp ISO."""
            try:
                return datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            except Exception:
                return None
        
        from_dt = parse_date(from_date) if from_date else None
        to_dt = parse_date(to_date) if to_date else None
        
        filtered = []
        for sale in sales:
            ts = sale.get('ts', '')
            dt = parse_date(ts)
            if dt is None:
                continue
            if from_dt and dt < from_dt:
                continue
            if to_dt and dt > to_dt:
                continue
            filtered.append(sale)
        
        return filtered
    
    def search_sales(
        self, 
        query: str = '',
        user: str = None,
        receipt: str = None,
        from_date: str = None,
        to_date: str = None
    ) -> List[Dict[str, Any]]:
        """
        Búsqueda avanzada de ventas con múltiples filtros.
        
        Args:
            query: Texto de búsqueda global
            user: Filtrar por usuario
            receipt: Filtrar por número de boleta
            from_date: Fecha inicio
            to_date: Fecha fin
            
        Returns:
            Lista de ventas que coinciden
        """
        # Empezar con todas las ventas
        sales = self.load()
        
        # Aplicar filtro de usuario
        if user:
            sales = [s for s in sales if s.get('user') == user]
        
        # Aplicar filtro de boleta
        if receipt:
            sales = [s for s in sales if s.get('receipt') == receipt]
        
        # Aplicar filtro de fechas
        if from_date or to_date:
            def in_range(ts_str: str) -> bool:
                try:
                    dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                except Exception:
                    return False
                if from_date:
                    from_dt = datetime.fromisoformat(from_date)
                    if dt < from_dt:
                        return False
                if to_date:
                    to_dt = datetime.fromisoformat(to_date)
                    if dt > to_dt:
                        return False
                return True
            sales = [s for s in sales if in_range(s.get('ts', ''))]
        
        # Aplicar búsqueda de texto global
        if query:
            query_lower = query.lower()
            filtered = []
            for sale in sales:
                # Buscar en campos principales
                if query_lower in (sale.get('user') or '').lower():
                    filtered.append(sale)
                    continue
                if query_lower in (sale.get('receipt') or '').lower():
                    filtered.append(sale)
                    continue
                if query_lower in (sale.get('ts') or '').lower():
                    filtered.append(sale)
                    continue
                # Buscar en items
                found_in_items = False
                for item in sale.get('items', []):
                    if query_lower in str(item.get('pid', '')).lower():
                        found_in_items = True
                        break
                    if query_lower in (item.get('sku') or '').lower():
                        found_in_items = True
                        break
                    if query_lower in (item.get('nombre') or '').lower():
                        found_in_items = True
                        break
                if found_in_items:
                    filtered.append(sale)
            sales = filtered
        
        return sales
    
    def add_payment(self, receipt: str, payment: Dict[str, Any]) -> bool:
        """
        Agrega un pago a una venta.
        
        Args:
            receipt: Número de boleta
            payment: Datos del pago
            
        Returns:
            True si se agregó exitosamente
        """
        sales = self.load()
        for sale in sales:
            if sale.get('receipt') == receipt:
                if 'payments' not in sale:
                    sale['payments'] = []
                sale['payments'].append(payment)
                self.save(sales)
                return True
        return False
    
    def get_pending_sales(self) -> List[Dict[str, Any]]:
        """
        Obtiene ventas pendientes de pago.
        
        Returns:
            Lista de ventas POR PAGAR
        """
        return self.get_sales_by_status('POR PAGAR')
    
    def get_completed_sales(self) -> List[Dict[str, Any]]:
        """
        Obtiene ventas completadas (entregadas).
        
        Returns:
            Lista de ventas COMPLETADA
        """
        return self.get_sales_by_status('COMPLETADA')
    
    def calculate_totals(self) -> Dict[str, float]:
        """
        Calcula totales agregados de todas las ventas.
        
        Returns:
            Dict con total_revenue, total_profit, total_pending
        """
        sales = self.load()
        total_revenue = 0.0
        total_profit = 0.0
        total_pending = 0.0
        paid_amount = 0.0
        
        for sale in sales:
            status = sale.get('status', '')
            if status == 'ANULADO':
                continue
            
            total_revenue += float(sale.get('total', 0) or 0)
            total_profit += float(sale.get('profit_total', 0) or 0)
            
            if status == 'POR PAGAR':
                total_pending += float(sale.get('pending_amount', 0) or 0)
                paid_amount += float(sale.get('paid_amount', 0) or 0)
            else:
                paid_amount += float(sale.get('total', 0) or 0)
        
        return {
            'total_revenue': round(total_revenue, 2),
            'total_profit': round(total_profit, 2),
            'total_pending': round(total_pending, 2),
            'paid_amount': round(paid_amount, 2)
        }
