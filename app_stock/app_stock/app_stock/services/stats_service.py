# ==============================================================================
# SERVICIO DE ESTADÍSTICAS DE GANANCIAS Y PÉRDIDAS
# ==============================================================================
# Calcula estadísticas financieras basadas SOLO en ventas COMPLETADAS.
# 
# REGLA PRINCIPAL: Solo "COMPLETADA" cuenta para estadísticas.
# - POR PAGAR ❌
# - CANCELADO ❌ (pagado pero no finalizado)
# - PARA RECOJO ❌
# - PARA ENVÍO ❌
# - ANULADO ❌
# ==============================================================================

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta, timezone
from collections import defaultdict


class StatsService:
    """
    Servicio para cálculo de estadísticas financieras.
    
    Responsabilidades:
    - Calcular ganancias y pérdidas por período
    - Filtrar solo ventas COMPLETADAS
    - Agrupar por día/semana/mes
    
    Preparado para migrar a MySQL (no acoplado a JSON).
    """
    
    # Estado válido para estadísticas
    VALID_STATUS = 'COMPLETADA'
    
    def __init__(self, sales_loader=None):
        """
        Inicializa el servicio.
        
        Args:
            sales_loader: Función que retorna la lista de ventas.
                          Permite inyectar dependencia para testing/migración.
        """
        self._sales_loader = sales_loader
    
    def set_sales_loader(self, loader):
        """Configura el cargador de ventas (útil para migración)"""
        self._sales_loader = loader
    
    def _load_sales(self) -> List[Dict[str, Any]]:
        """Carga ventas usando el loader configurado"""
        if self._sales_loader:
            return self._sales_loader()
        return []
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """
        Parsea una fecha desde string ISO.
        Retorna None si no puede parsear.
        """
        if not date_str:
            return None
        try:
            # Formato ISO con timezone
            if '+' in date_str or 'Z' in date_str:
                # Python 3.7+ puede parsear ISO directamente
                return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            # Formato sin timezone
            return datetime.fromisoformat(date_str)
        except (ValueError, TypeError):
            return None
    
    def _get_date_range(self, period: str, custom_start: str = None, custom_end: str = None) -> Tuple[datetime, datetime]:
        """
        Calcula el rango de fechas según el período solicitado.
        
        Args:
            period: 'today', 'week', 'month', 'custom'
            custom_start: Fecha inicio para período custom (YYYY-MM-DD)
            custom_end: Fecha fin para período custom (YYYY-MM-DD)
        
        Returns:
            Tupla (fecha_inicio, fecha_fin) en UTC
        """
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        if period == 'today':
            return today_start, now
        
        elif period == 'week':
            # Inicio de la semana (lunes)
            days_since_monday = now.weekday()
            week_start = today_start - timedelta(days=days_since_monday)
            return week_start, now
        
        elif period == 'month':
            # Inicio del mes
            month_start = today_start.replace(day=1)
            return month_start, now
        
        elif period == 'custom' and custom_start and custom_end:
            try:
                start = datetime.strptime(custom_start, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                end = datetime.strptime(custom_end, '%Y-%m-%d').replace(
                    hour=23, minute=59, second=59, tzinfo=timezone.utc
                )
                return start, end
            except ValueError:
                # Fallback a hoy si hay error
                return today_start, now
        
        # Default: hoy
        return today_start, now
    
    def _filter_completed_sales(
        self, 
        sales: List[Dict[str, Any]], 
        start_date: datetime, 
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """
        Filtra ventas que:
        1. Tienen estado COMPLETADA
        2. Están dentro del rango de fechas (usa completion_ts si existe, sino ts)
        """
        filtered = []
        
        for sale in sales:
            # Solo COMPLETADA
            if sale.get('status') != self.VALID_STATUS:
                continue
            
            # Usar fecha de completado si existe, sino fecha de creación
            date_str = sale.get('completion_ts') or sale.get('ts')
            sale_date = self._parse_date(date_str)
            
            if not sale_date:
                continue
            
            # Asegurar timezone
            if sale_date.tzinfo is None:
                sale_date = sale_date.replace(tzinfo=timezone.utc)
            
            # Verificar rango
            if start_date <= sale_date <= end_date:
                filtered.append(sale)
        
        return filtered
    
    def calculate_profit_stats(
        self,
        period: str = 'today',
        custom_start: str = None,
        custom_end: str = None
    ) -> Dict[str, Any]:
        """
        Calcula estadísticas de ganancia/pérdida para el período.
        
        Args:
            period: 'today', 'week', 'month', 'custom'
            custom_start: Fecha inicio (YYYY-MM-DD) si period='custom'
            custom_end: Fecha fin (YYYY-MM-DD) si period='custom'
        
        Returns:
            {
                'period': str,
                'date_range': {'start': str, 'end': str},
                'summary': {
                    'total_sales': int,           # Cantidad de ventas COMPLETADAS
                    'total_items': int,           # Cantidad de ítems vendidos
                    'gross_income': float,        # Ingresos brutos (suma de totales)
                    'total_cost': float,          # Costos totales
                    'net_profit': float,          # Ganancia neta
                    'total_loss': float,          # Pérdidas (ventas con ganancia negativa)
                    'profitable_sales': int,      # Ventas con ganancia positiva
                    'loss_sales': int,            # Ventas con pérdida
                },
                'daily_breakdown': [              # Desglose diario
                    {'date': 'YYYY-MM-DD', 'income': float, 'cost': float, 'profit': float}
                ],
                'top_products': [                 # Productos más rentables
                    {'name': str, 'qty': int, 'profit': float}
                ],
                'loss_products': [                # Productos con pérdida
                    {'name': str, 'qty': int, 'loss': float}
                ]
            }
        """
        # Obtener rango de fechas
        start_date, end_date = self._get_date_range(period, custom_start, custom_end)
        
        # Cargar y filtrar ventas
        all_sales = self._load_sales()
        completed_sales = self._filter_completed_sales(all_sales, start_date, end_date)
        
        # Inicializar contadores
        total_sales = len(completed_sales)
        total_items = 0
        gross_income = 0.0
        total_cost = 0.0
        total_loss = 0.0
        profitable_sales = 0
        loss_sales = 0
        
        # Para desglose diario
        daily_data = defaultdict(lambda: {'income': 0.0, 'cost': 0.0, 'profit': 0.0})
        
        # Para productos
        product_profits = defaultdict(lambda: {'qty': 0, 'profit': 0.0})
        
        # Procesar cada venta COMPLETADA
        for sale in completed_sales:
            sale_total = float(sale.get('total', 0) or 0)
            sale_cost = float(sale.get('cost_total', 0) or 0)
            sale_profit = float(sale.get('profit_total', 0) or 0)
            
            # Si no hay profit_total calculado, calcularlo
            if sale_profit == 0 and sale_cost > 0:
                sale_profit = sale_total - sale_cost
            
            gross_income += sale_total
            total_cost += sale_cost
            
            if sale_profit < 0:
                total_loss += abs(sale_profit)
                loss_sales += 1
            else:
                profitable_sales += 1
            
            # Desglose diario
            date_str = sale.get('completion_ts') or sale.get('ts')
            sale_date = self._parse_date(date_str)
            if sale_date:
                day_key = sale_date.strftime('%Y-%m-%d')
                daily_data[day_key]['income'] += sale_total
                daily_data[day_key]['cost'] += sale_cost
                daily_data[day_key]['profit'] += sale_profit
            
            # Procesar ítems
            for item in sale.get('items', []):
                total_items += int(item.get('qty', 1) or 1)
                
                # Datos del producto
                product_name = item.get('nombre', 'Producto')
                item_qty = int(item.get('qty', 1) or 1)
                item_profit = float(item.get('line_profit', 0) or 0)
                
                # Si no hay line_profit, calcular
                if item_profit == 0:
                    unit_price = float(item.get('unit_price', 0) or 0)
                    unit_cost = float(item.get('unit_cost', 0) or 0)
                    item_profit = (unit_price - unit_cost) * item_qty
                
                product_profits[product_name]['qty'] += item_qty
                product_profits[product_name]['profit'] += item_profit
        
        # Calcular ganancia neta
        net_profit = gross_income - total_cost
        
        # Preparar desglose diario (ordenado por fecha)
        daily_breakdown = [
            {
                'date': date,
                'income': round(data['income'], 2),
                'cost': round(data['cost'], 2),
                'profit': round(data['profit'], 2)
            }
            for date, data in sorted(daily_data.items())
        ]
        
        # Separar productos rentables y con pérdida
        top_products = []
        loss_products = []
        
        for name, data in product_profits.items():
            if data['profit'] >= 0:
                top_products.append({
                    'name': name,
                    'qty': data['qty'],
                    'profit': round(data['profit'], 2)
                })
            else:
                loss_products.append({
                    'name': name,
                    'qty': data['qty'],
                    'loss': round(abs(data['profit']), 2)
                })
        
        # Ordenar por rentabilidad
        top_products.sort(key=lambda x: x['profit'], reverse=True)
        loss_products.sort(key=lambda x: x['loss'], reverse=True)
        
        # Limitar a top 10
        top_products = top_products[:10]
        loss_products = loss_products[:10]
        
        return {
            'period': period,
            'date_range': {
                'start': start_date.strftime('%Y-%m-%d'),
                'end': end_date.strftime('%Y-%m-%d')
            },
            'summary': {
                'total_sales': total_sales,
                'total_items': total_items,
                'gross_income': round(gross_income, 2),
                'total_cost': round(total_cost, 2),
                'net_profit': round(net_profit, 2),
                'total_loss': round(total_loss, 2),
                'profitable_sales': profitable_sales,
                'loss_sales': loss_sales,
            },
            'daily_breakdown': daily_breakdown,
            'top_products': top_products,
            'loss_products': loss_products
        }
    
    def get_period_comparison(
        self,
        current_period: str = 'month'
    ) -> Dict[str, Any]:
        """
        Compara el período actual con el anterior.
        
        Returns:
            {
                'current': {...stats...},
                'previous': {...stats...},
                'change': {
                    'income': float (porcentaje),
                    'profit': float (porcentaje),
                    'sales': float (porcentaje)
                }
            }
        """
        now = datetime.now(timezone.utc)
        
        if current_period == 'month':
            # Mes actual
            current_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            # Mes anterior
            if now.month == 1:
                prev_start = now.replace(year=now.year-1, month=12, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                prev_start = now.replace(month=now.month-1, day=1, hour=0, minute=0, second=0, microsecond=0)
            prev_end = current_start - timedelta(seconds=1)
            
        elif current_period == 'week':
            days_since_monday = now.weekday()
            current_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_since_monday)
            prev_start = current_start - timedelta(days=7)
            prev_end = current_start - timedelta(seconds=1)
            
        else:  # today
            current_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            prev_start = current_start - timedelta(days=1)
            prev_end = current_start - timedelta(seconds=1)
        
        # Calcular estadísticas
        current_stats = self.calculate_profit_stats(
            period='custom',
            custom_start=current_start.strftime('%Y-%m-%d'),
            custom_end=now.strftime('%Y-%m-%d')
        )
        
        previous_stats = self.calculate_profit_stats(
            period='custom',
            custom_start=prev_start.strftime('%Y-%m-%d'),
            custom_end=prev_end.strftime('%Y-%m-%d')
        )
        
        # Calcular cambio porcentual
        def calc_change(current, previous):
            if previous == 0:
                return 100.0 if current > 0 else 0.0
            return round(((current - previous) / previous) * 100, 1)
        
        return {
            'current': current_stats,
            'previous': previous_stats,
            'change': {
                'income': calc_change(
                    current_stats['summary']['gross_income'],
                    previous_stats['summary']['gross_income']
                ),
                'profit': calc_change(
                    current_stats['summary']['net_profit'],
                    previous_stats['summary']['net_profit']
                ),
                'sales': calc_change(
                    current_stats['summary']['total_sales'],
                    previous_stats['summary']['total_sales']
                )
            }
        }


# ==============================================================================
# FUNCIONES HELPER (para uso directo sin instanciar)
# ==============================================================================

_stats_service = None

def get_stats_service(sales_loader=None) -> StatsService:
    """Obtiene una instancia del servicio (singleton)"""
    global _stats_service
    if _stats_service is None:
        _stats_service = StatsService(sales_loader)
    elif sales_loader and _stats_service._sales_loader is None:
        _stats_service.set_sales_loader(sales_loader)
    return _stats_service
