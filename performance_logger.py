# ==============================================================================
# SISTEMA DE PROFILING INTERNO
# ==============================================================================
# Mide rendimiento de rutas y funciones sin afectar la experiencia del usuario.
# Guarda logs legibles en /logs/ para análisis humano.
#
# ACTIVAR/DESACTIVAR: Variable ENABLE_PROFILING
# ==============================================================================

import os
import time
import threading
from datetime import datetime
from functools import wraps
from collections import defaultdict

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════════════════

# Activar/desactivar profiling (cambiar a False en producción si no se necesita)
ENABLE_PROFILING = True

# Umbrales de tiempo (en milisegundos)
THRESHOLD_WARNING = 300   # Advertencia si supera 300ms
THRESHOLD_CRITICAL = 700  # Crítico si supera 700ms

# Directorio de logs
LOGS_DIR = os.path.join(os.path.dirname(__file__), 'logs')

# Archivos de log
PERFORMANCE_LOG = os.path.join(LOGS_DIR, 'performance.log')
SLOW_ROUTES_LOG = os.path.join(LOGS_DIR, 'slow_routes.log')
SLOW_FUNCTIONS_LOG = os.path.join(LOGS_DIR, 'slow_functions.log')

# Mapeo de rutas a nombres legibles (para logs más humanos)
ROUTE_NAMES = {
    # Autenticación
    'POST /': 'Iniciar sesión',
    'GET /logout': 'Cerrar sesión',
    
    # Dashboard
    'GET /dashboard': 'Ver panel principal',
    
    # Inventario
    'GET /api/product/<int:pid>': 'Obtener producto',
    'POST /api/stock/add': 'Agregar stock',
    'POST /api/stock/remove': 'Retirar stock',
    'POST /create_product': 'Crear producto',
    'POST /product/<int:pid>/edit': 'Editar producto',
    'POST /product/<int:pid>/delete': 'Eliminar producto',
    'POST /api/product/<int:pid>/variant': 'Agregar variante',
    'POST /api/product/<int:pid>/variant/<variant_id>/stock': 'Modificar stock variante',
    'POST /api/product/<int:pid>/variant/<variant_id>/uv': 'Agregar UV a variante',
    
    # Carrito
    'GET /api/carrito': 'Ver carrito',
    'POST /api/carrito/agregar': 'Agregar al carrito',
    'POST /api/carrito/eliminar': 'Eliminar del carrito',
    'POST /api/carrito/limpiar': 'Vaciar carrito',
    'POST /api/carrito/confirmar': 'Confirmar venta',
    
    # Ventas
    'GET /sales': 'Ver ventas',
    'GET /sales/stats': 'Ver estadísticas',
    'POST /sales/<receipt>/payment': 'Registrar pago',
    'POST /sales/<receipt>/status': 'Cambiar estado venta',
    'GET /receipt/<receipt>': 'Ver boleta',
    
    # Exportaciones
    'GET /export/sales': 'Exportar ventas CSV',
    'GET /audit/export': 'Exportar auditoría CSV',
    
    # Auditoría
    'GET /audit': 'Ver registro de actividad',
    
    # Configuración
    'GET /settings': 'Ver configuración',
    'POST /settings': 'Guardar configuración',
}


# ═══════════════════════════════════════════════════════════════════════════
# INICIALIZACIÓN
# ═══════════════════════════════════════════════════════════════════════════

def _ensure_logs_dir():
    """Crea el directorio de logs si no existe"""
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR)
        
# Crear directorio al importar el módulo
_ensure_logs_dir()


# ═══════════════════════════════════════════════════════════════════════════
# ESTADÍSTICAS DE FUNCIONES (en memoria)
# ═══════════════════════════════════════════════════════════════════════════

# Estructura: {nombre_funcion: {calls: int, total_time: float, max_time: float}}
_function_stats = defaultdict(lambda: {'calls': 0, 'total_time': 0.0, 'max_time': 0.0})
_stats_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════════════
# FUNCIONES DE LOGGING
# ═══════════════════════════════════════════════════════════════════════════

def _get_timestamp():
    """Obtiene timestamp legible"""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _write_log(filepath, content):
    """Escribe contenido a un archivo de log (thread-safe)"""
    try:
        with threading.Lock():
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write(content)
    except Exception:
        pass  # Silenciar errores de escritura para no afectar la app


def _get_route_name(method, path, rule=None):
    """
    Obtiene nombre legible para una ruta.
    Intenta hacer match con ROUTE_NAMES, si no, devuelve la ruta raw.
    """
    # Primero intentar match exacto
    key = f"{method} {path}"
    if key in ROUTE_NAMES:
        return ROUTE_NAMES[key]
    
    # Si tenemos la regla de Flask, usarla para match con parámetros
    if rule:
        rule_key = f"{method} {rule}"
        if rule_key in ROUTE_NAMES:
            return ROUTE_NAMES[rule_key]
    
    # Intentar match parcial (para rutas con parámetros)
    for route_pattern, name in ROUTE_NAMES.items():
        pattern_method, pattern_path = route_pattern.split(' ', 1)
        if pattern_method != method:
            continue
        
        # Verificar si el patrón coincide (simplificado)
        if '<' in pattern_path:
            # Convertir patrón a regex simplificado
            base_pattern = pattern_path.split('<')[0]
            if path.startswith(base_pattern):
                return name
    
    # Fallback: usar la ruta raw
    return f"{method} {path}"


# ═══════════════════════════════════════════════════════════════════════════
# 1️⃣ PROFILING DE RUTAS (Middleware Flask)
# ═══════════════════════════════════════════════════════════════════════════

def log_route_performance(method, path, rule, time_ms, user=None):
    """
    Registra el rendimiento de una ruta en performance.log
    
    Args:
        method: GET, POST, etc.
        path: Ruta solicitada (/api/carrito/agregar)
        rule: Regla de Flask (/api/carrito/agregar)
        time_ms: Tiempo en milisegundos
        user: Usuario que hizo la petición (opcional)
    """
    if not ENABLE_PROFILING:
        return
    
    action_name = _get_route_name(method, path, rule)
    user_str = user or 'anónimo'
    
    log_entry = f"""
════════════════════════════════════════
[PERFORMANCE] {_get_timestamp()}
────────────────────────────────────────
Acción: {action_name}
Usuario: {user_str}
Ruta: {method} {path}
Tiempo: {time_ms:.0f} ms
"""
    
    _write_log(PERFORMANCE_LOG, log_entry)


def log_slow_route(method, path, rule, time_ms, user=None, level='WARNING'):
    """
    Registra una ruta lenta en slow_routes.log
    
    Args:
        level: 'WARNING' (>300ms) o 'CRITICAL' (>700ms)
    """
    if not ENABLE_PROFILING:
        return
    
    action_name = _get_route_name(method, path, rule)
    user_str = user or 'anónimo'
    
    emoji = '⚠️' if level == 'WARNING' else '🔴'
    severity = 'LENTA' if level == 'WARNING' else 'MUY LENTA'
    
    log_entry = f"""
{emoji} [{level}] {_get_timestamp()}
────────────────────────────────────────
Ruta {severity}: {action_name}
Usuario: {user_str}
Detalle: {method} {path}
Tiempo: {time_ms:.0f} ms (umbral: {THRESHOLD_WARNING if level == 'WARNING' else THRESHOLD_CRITICAL} ms)
────────────────────────────────────────
"""
    
    _write_log(SLOW_ROUTES_LOG, log_entry)


# ═══════════════════════════════════════════════════════════════════════════
# 2️⃣ HOOKS PARA FLASK (before/after request)
# ═══════════════════════════════════════════════════════════════════════════

def init_profiling(app):
    """
    Inicializa el sistema de profiling en una app Flask.
    Registra hooks before_request y after_request.
    
    Uso:
        from performance_logger import init_profiling
        init_profiling(app)
    """
    if not ENABLE_PROFILING:
        return
    
    @app.before_request
    def _start_timer():
        from flask import g
        g.start_time = time.perf_counter()
    
    @app.after_request
    def _log_request(response):
        from flask import g, request, session
        
        # Calcular tiempo transcurrido
        if not hasattr(g, 'start_time'):
            return response
        
        elapsed = (time.perf_counter() - g.start_time) * 1000  # ms
        
        # Obtener datos de la petición
        method = request.method
        path = request.path
        rule = str(request.url_rule) if request.url_rule else path
        user = session.get('user')
        
        # Ignorar archivos estáticos
        if path.startswith('/static'):
            return response
        
        # Log de rendimiento general
        log_route_performance(method, path, rule, elapsed, user)
        
        # Detectar rutas lentas
        if elapsed >= THRESHOLD_CRITICAL:
            log_slow_route(method, path, rule, elapsed, user, 'CRITICAL')
        elif elapsed >= THRESHOLD_WARNING:
            log_slow_route(method, path, rule, elapsed, user, 'WARNING')
        
        return response


# ═══════════════════════════════════════════════════════════════════════════
# 3️⃣ DECORADOR PARA FUNCIONES CLAVE
# ═══════════════════════════════════════════════════════════════════════════

def profile_function(func=None, name=None):
    """
    Decorador para medir rendimiento de funciones críticas.
    
    Uso:
        @profile_function
        def mi_funcion():
            ...
        
        @profile_function(name="Crear venta desde carrito")
        def create_sale_from_cart():
            ...
    
    Registra:
        - Cantidad de llamadas
        - Tiempo promedio
        - Tiempo máximo
    """
    def decorator(fn):
        if not ENABLE_PROFILING:
            return fn
        
        func_name = name or fn.__name__
        
        @wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
                return result
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000
                
                # Actualizar estadísticas
                with _stats_lock:
                    stats = _function_stats[func_name]
                    stats['calls'] += 1
                    stats['total_time'] += elapsed_ms
                    if elapsed_ms > stats['max_time']:
                        stats['max_time'] = elapsed_ms
                
                # Si es muy lenta, loguear inmediatamente
                if elapsed_ms >= THRESHOLD_WARNING:
                    _log_slow_function_call(func_name, elapsed_ms)
        
        return wrapper
    
    # Permitir uso sin paréntesis: @profile_function
    if func is not None:
        return decorator(func)
    return decorator


def _log_slow_function_call(func_name, time_ms):
    """Registra una llamada lenta a una función"""
    severity = 'CRÍTICO' if time_ms >= THRESHOLD_CRITICAL else 'LENTO'
    emoji = '🔴' if time_ms >= THRESHOLD_CRITICAL else '⚠️'
    
    log_entry = f"""
{emoji} [{severity}] {_get_timestamp()}
Función: {func_name}
Tiempo: {time_ms:.0f} ms
────────────────────────────────────────
"""
    
    _write_log(SLOW_FUNCTIONS_LOG, log_entry)


# ═══════════════════════════════════════════════════════════════════════════
# 4️⃣ REPORTE DE ESTADÍSTICAS
# ═══════════════════════════════════════════════════════════════════════════

def get_function_stats():
    """
    Obtiene estadísticas de todas las funciones perfiladas.
    
    Returns:
        dict: {nombre: {calls, avg_time, max_time}}
    """
    with _stats_lock:
        result = {}
        for func_name, stats in _function_stats.items():
            calls = stats['calls']
            avg = stats['total_time'] / calls if calls > 0 else 0
            result[func_name] = {
                'calls': calls,
                'avg_time': round(avg, 2),
                'max_time': round(stats['max_time'], 2)
            }
        return result


def write_function_stats_report():
    """
    Escribe un reporte legible de estadísticas de funciones en slow_functions.log
    """
    if not ENABLE_PROFILING:
        return
    
    stats = get_function_stats()
    
    if not stats:
        return
    
    # Ordenar por tiempo promedio (mayor primero)
    sorted_stats = sorted(stats.items(), key=lambda x: x[1]['avg_time'], reverse=True)
    
    report = f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  REPORTE DE RENDIMIENTO DE FUNCIONES                                         ║
║  Generado: {_get_timestamp()}                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝

"""
    
    for func_name, data in sorted_stats:
        # Determinar si es problemática
        status = ''
        if data['avg_time'] >= THRESHOLD_CRITICAL:
            status = ' 🔴 CRÍTICO'
        elif data['avg_time'] >= THRESHOLD_WARNING:
            status = ' ⚠️ LENTO'
        elif data['max_time'] >= THRESHOLD_CRITICAL:
            status = ' ⚡ PICOS ALTOS'
        
        report += f"""┌──────────────────────────────────────────────────────────────────────────────┐
│ FUNCIÓN: {func_name}{status}
├──────────────────────────────────────────────────────────────────────────────┤
│ Llamadas totales: {data['calls']}
│ Tiempo promedio:  {data['avg_time']:.0f} ms
│ Tiempo máximo:    {data['max_time']:.0f} ms
└──────────────────────────────────────────────────────────────────────────────┘

"""
    
    _write_log(SLOW_FUNCTIONS_LOG, report)


def reset_stats():
    """Reinicia todas las estadísticas (útil para testing)"""
    with _stats_lock:
        _function_stats.clear()


# ═══════════════════════════════════════════════════════════════════════════
# 5️⃣ FUNCIONES DE UTILIDAD
# ═══════════════════════════════════════════════════════════════════════════

def clear_logs():
    """Limpia todos los archivos de log (útil para desarrollo)"""
    for logfile in [PERFORMANCE_LOG, SLOW_ROUTES_LOG, SLOW_FUNCTIONS_LOG]:
        try:
            if os.path.exists(logfile):
                os.remove(logfile)
        except Exception:
            pass


def get_log_summary():
    """
    Obtiene un resumen del estado actual de los logs.
    
    Returns:
        dict: {archivo: {exists, size_kb, lines}}
    """
    summary = {}
    for name, path in [('performance', PERFORMANCE_LOG), 
                       ('slow_routes', SLOW_ROUTES_LOG), 
                       ('slow_functions', SLOW_FUNCTIONS_LOG)]:
        if os.path.exists(path):
            size = os.path.getsize(path) / 1024  # KB
            with open(path, 'r', encoding='utf-8') as f:
                lines = sum(1 for _ in f)
            summary[name] = {'exists': True, 'size_kb': round(size, 2), 'lines': lines}
        else:
            summary[name] = {'exists': False, 'size_kb': 0, 'lines': 0}
    return summary


# ═══════════════════════════════════════════════════════════════════════════
# EXPORTAR API PÚBLICA
# ═══════════════════════════════════════════════════════════════════════════

__all__ = [
    'ENABLE_PROFILING',
    'init_profiling',
    'profile_function',
    'get_function_stats',
    'write_function_stats_report',
    'reset_stats',
    'clear_logs',
    'get_log_summary',
]
