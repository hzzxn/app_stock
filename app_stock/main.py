from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import json
import uuid
import io
import csv
import datetime
import threading
from queue import Queue
import atexit

# Sistema de profiling interno
from performance_logger import init_profiling, profile_function

# Sistema de backups automáticos
from services.backup_service import run_startup_backup

# ═══════════════════════════════════════════════════════════════════════════
# CONTENEDOR DE DEPENDENCIAS - Servicios y Repositorios
# ═══════════════════════════════════════════════════════════════════════════
# Importamos el contenedor para acceder a los servicios de forma centralizada.
# Esto permite que la lógica de negocio viva en services/, no en las rutas.
# MYSQL READY: Cambiar implementación de repos no afecta las rutas.
# ═══════════════════════════════════════════════════════════════════════════
from app_container import get_container

app = Flask(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# INICIALIZAR SISTEMA DE PROFILING
# ═══════════════════════════════════════════════════════════════════════════
# Mide rendimiento de rutas y funciones. Logs en /logs/
# Para desactivar: ENABLE_PROFILING = False en performance_logger.py
init_profiling(app)

# ═══════════════════════════════════════════════════════════════════════════
# SISTEMA DE CACHÉ Y ESCRITURA OPTIMIZADA
# ═══════════════════════════════════════════════════════════════════════════
# - Caché en memoria para lecturas frecuentes
# - Cola de escritura para operaciones no bloqueantes
# - Locks para thread-safety
# ═══════════════════════════════════════════════════════════════════════════

class JSONCache:
    """
    Caché en memoria con escritura diferida (write-behind).
    
    Beneficios:
    - Lecturas instantáneas desde memoria
    - Escrituras asíncronas (no bloquean response)
    - Thread-safe con locks granulares
    """
    
    def __init__(self):
        self._data = {}           # Datos en caché: {filepath: data}
        self._dirty = set()       # Archivos pendientes de escribir
        self._locks = {}          # Lock por archivo para thread-safety
        self._global_lock = threading.RLock()
        self._write_queue = Queue()
        self._writer_thread = None
        self._shutdown = False
    
    def _get_lock(self, filepath):
        """Obtiene o crea un lock para un archivo específico"""
        with self._global_lock:
            if filepath not in self._locks:
                self._locks[filepath] = threading.RLock()
            return self._locks[filepath]
    
    def _start_writer(self):
        """Inicia el thread de escritura si no está corriendo"""
        if self._writer_thread is None or not self._writer_thread.is_alive():
            self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
            self._writer_thread.start()
    
    def _writer_loop(self):
        """Loop de escritura en background (no bloquea requests)"""
        while not self._shutdown:
            try:
                # Esperar con timeout para poder revisar shutdown
                item = self._write_queue.get(timeout=0.5)
                if item is None:  # Señal de shutdown
                    break
                filepath, data = item
                self._write_to_disk(filepath, data)
                self._write_queue.task_done()
            except:
                pass  # Timeout o error, continuar loop
    
    def _write_to_disk(self, filepath, data):
        """Escribe datos a disco de forma segura (atomic write)"""
        try:
            lock = self._get_lock(filepath)
            with lock:
                # Escritura atómica: escribir a temp y renombrar
                temp_path = filepath + '.tmp'
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                # Renombrar es atómico en la mayoría de sistemas
                if os.path.exists(filepath):
                    os.replace(temp_path, filepath)
                else:
                    os.rename(temp_path, filepath)
                # Limpiar flag de dirty
                self._dirty.discard(filepath)
        except Exception as e:
            # En caso de error, mantener dirty para reintentar
            pass
    
    def get(self, filepath, loader_func):
        """
        Obtiene datos del caché o los carga si no existen.
        
        Args:
            filepath: Ruta al archivo JSON
            loader_func: Función que carga los datos si no están en caché
        
        Returns:
            Datos del caché (o recién cargados)
        """
        lock = self._get_lock(filepath)
        with lock:
            if filepath not in self._data:
                # Cargar desde disco
                self._data[filepath] = loader_func()
            return self._data[filepath]
    
    def set(self, filepath, data, immediate=False):
        """
        Actualiza el caché y encola escritura a disco.
        
        Args:
            filepath: Ruta al archivo JSON
            data: Datos a guardar
            immediate: Si True, escribe inmediatamente (bloquea)
        """
        lock = self._get_lock(filepath)
        with lock:
            self._data[filepath] = data
            self._dirty.add(filepath)
            
            if immediate:
                # Escritura síncrona (para operaciones críticas)
                self._write_to_disk(filepath, data)
            else:
                # Escritura asíncrona
                self._start_writer()
                self._write_queue.put((filepath, data))
    
    def invalidate(self, filepath):
        """Invalida el caché de un archivo (fuerza recarga en próxima lectura)"""
        lock = self._get_lock(filepath)
        with lock:
            self._data.pop(filepath, None)
    
    def flush(self):
        """Escribe todos los archivos pendientes a disco (llamar al shutdown)"""
        self._shutdown = True
        for filepath in list(self._dirty):
            if filepath in self._data:
                self._write_to_disk(filepath, self._data[filepath])
        if self._writer_thread:
            self._write_queue.put(None)  # Señal de shutdown
            self._writer_thread.join(timeout=2)

# Instancia global del caché
_json_cache = JSONCache()

# Registrar flush al cerrar la aplicación
@atexit.register
def _cleanup_cache():
    _json_cache.flush()

BASE = os.path.dirname(__file__)

# ═══════════════════════════════════════════════════════════════════════════════
# MODO PRODUCCIÓN
# ═══════════════════════════════════════════════════════════════════════════════
# True = Sistema limpio, sin datos de prueba ni usuarios demo
# False = Modo desarrollo con logging verbose
PRODUCTION_MODE = True

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE SESIONES - Compatible con acceso por IP local (WiFi)
# ═══════════════════════════════════════════════════════════════════════════════
# SECRET_KEY: En producción DEBE definirse via variable de entorno
# Comando: export STOCK_SECRET_KEY="tu_clave_secreta_muy_larga_y_aleatoria"
_DEFAULT_SECRET = "app_stock_dev_secret_key_change_in_production_2024"
_SECRET_KEY = os.environ.get("STOCK_SECRET_KEY")

if PRODUCTION_MODE and not _SECRET_KEY:
    print("[ADVERTENCIA] PRODUCTION_MODE activo sin STOCK_SECRET_KEY definida")
    print("[ADVERTENCIA] Define la variable de entorno para mayor seguridad")

app.secret_key = _SECRET_KEY or _DEFAULT_SECRET

# Configuración de cookies de sesión
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,      # Protege contra XSS
    SESSION_COOKIE_SECURE=False,       # False para HTTP local (True solo para HTTPS)
    SESSION_COOKIE_SAMESITE='Lax',     # Protección CSRF básica
    SESSION_COOKIE_DOMAIN=None,        # None = acepta cualquier dominio/IP
    PERMANENT_SESSION_LIFETIME=86400,  # 24 horas
)

# Upload / limits
UPLOAD_DIR = os.path.join(BASE, "static", "productos")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB

# Users - cargados desde users.json (NUNCA hardcodeados en producción)
USERS_FILE = os.path.join(BASE, "users.json")
SALES_FILE = os.path.join(BASE, 'sales.json')

# Debug: mostrar ruta absoluta de users.json
if not PRODUCTION_MODE or os.environ.get('DEBUG_AUTH'):
    print(f"[DEBUG AUTH] USERS_FILE = {os.path.abspath(USERS_FILE)}")

def normalize_role(role):
    """Normalize role strings to canonical values.
    Accepts various casings and common synonyms.
    """
    if not role:
        return ""
    r = str(role).strip()
    low = r.lower()
    if low in ("admin", "administrator", "root"):
        return "admin"
    if low in ("operador", "operario", "operator"):
        return "operador"
    if low in ("china import", "china", "china_import"):
        return "China Import"
    return r

def save_users(users):
    # Guardar usuarios (incluye password hashed) en disco
    serial = {}
    for u, v in users.items():
        serial[u] = {"password": v.get("password"), "role": normalize_role(v.get("role", ""))}
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(serial, f, ensure_ascii=False, indent=2)

def load_users():
    """
    Carga usuarios desde users.json.
    
    En PRODUCTION_MODE: solo carga archivo existente, NO crea usuarios de prueba.
    En modo desarrollo: crea admin/operador si no existe archivo.
    """
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {u: {"password": v["password"], "role": normalize_role(v.get("role",""))} for u,v in data.items()}
        except Exception:
            pass
    
    # Si no existe el archivo
    if PRODUCTION_MODE:
        # En producción, crear archivo vacío con solo China Import
         #NO QUITAR ESTA MADRE PORQUE HACE QUE EL SISTEMA FUNCIONE xD
        users = {
            "china": {
                "password": generate_password_hash("CAMBIAR_ESTA_CLAVE_INMEDIATAMENTE"),
                "role": "China Import"
            }
        }
        print("[PRODUCCIÓN] Creado users.json con cuenta China Import")
        print("[PRODUCCIÓN] ¡IMPORTANTE! Cambia la contraseña inmediatamente")
    else:
        # En desarrollo, crear usuarios de prueba
        users = {
            "admin": {"password": generate_password_hash("1234"), "role": "admin"},
            "operador": {"password": generate_password_hash("1234"), "role": "operador"},
            "china": {"password": generate_password_hash("changeme"), "role": "China Import"}
        }
    
    save_users(users)
    return users

def migrate_plaintext_passwords():
    """
    Migración de seguridad: convierte contraseñas en texto plano a hash.
    
    Se ejecuta automáticamente al iniciar la aplicación.
    Detecta contraseñas que NO empiecen con 'pbkdf2:' o 'scrypt:' y las hashea.
    """
    global USERS
    migrated = 0
    
    for username, data in USERS.items():
        pwd = data.get('password', '')
        # Si NO es un hash válido (no empieza con pbkdf2: ni scrypt:)
        if pwd and not (pwd.startswith('pbkdf2:') or pwd.startswith('scrypt:')):
            print(f"[SEGURIDAD] Migrando contraseña de '{username}' a hash seguro")
            USERS[username]['password'] = generate_password_hash(pwd)
            migrated += 1
    
    if migrated > 0:
        save_users(USERS)
        print(f"[SEGURIDAD] {migrated} contraseña(s) migrada(s) a hash")
    
    return migrated

USERS = load_users()
migrate_plaintext_passwords()  # Migración automática al inicio

# Inventory & Audit persistence
INV_FILE = os.path.join(BASE, "inventory.json")
AUDIT_FILE = os.path.join(BASE, "audit.json")

@profile_function(name="Cargar inventario")
def load_inventory():
    """
    Carga el inventario desde inventory.json.
    
    - Si existe el archivo, lo carga y migra productos legacy si es necesario
    - Si no existe o está vacío, retorna diccionario vacío
    - NUNCA sobrescribe datos existentes con valores por defecto
    - Los productos se crean SOLO desde el panel de administración
    """
    if os.path.exists(INV_FILE):
        try:
            with open(INV_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Si el archivo está vacío o es un objeto vacío, retornar vacío
            if not data:
                return {}
            
            inv = {int(k): v for k, v in data.items()}
            
            # Migrar productos legacy a estructura de variantes si no la tienen
            needs_save = False
            for pid, prod in inv.items():
                if 'variants' not in prod:
                    normalize_product_variants(prod)
                    needs_save = True
            if needs_save:
                save_inventory(inv)
            return inv
        except (json.JSONDecodeError, ValueError):
            # Archivo corrupto - NO sobrescribir, retornar vacío
            print(f"[ADVERTENCIA] inventory.json corrupto, iniciando vacío")
            return {}
        except Exception as e:
            print(f"[ERROR] Cargando inventario: {e}")
            return {}
    else:
        # Crear archivo vacío
        save_inventory({})
        return {}

# Sale status constants
SALE_STATUSES = {"POR PAGAR", "CANCELADO", "PARA RECOJO", "PARA ENVÍO", "ANULADO", "COMPLETADA"}

# ═══════════════════════════════════════════════════════════════════════════
# MULTI-VARIANTES + MULTI-UV: Funciones helper
# ═══════════════════════════════════════════════════════════════════════════
# Nuevo modelo de datos:
# variant = {
#   variant_id: str,
#   attributes: {color: "Rojo", ...},
#   units: [
#     { uv: "UNIDAD", stock: 10, reserved: 0, price: 100, cost: 50, label: null },
#     { uv: "CAJA", stock: 5, reserved: 0, price: 550, cost: 250, label: null },
#   ]
# }
# ═══════════════════════════════════════════════════════════════════════════

# UV válidas
VALID_UVS = {'UNIDAD', 'CAJA', 'COSTAL', 'OTRA'}


def normalize_product_variants(product):
    """
    Asegura que un producto tenga estructura de variantes correcta con sistema multi-UV.
    Migra estructura antigua (unit/stock por variante) a nueva (units[] por variante).
    """
    if not isinstance(product, dict):
        return
    
    # Si ya tiene variantes, normalizarlas al nuevo formato
    if 'variants' in product and isinstance(product['variants'], list):
        for v in product['variants']:
            if 'variant_id' not in v:
                v['variant_id'] = f"{product.get('sku', 'V')}-{v.get('attributes', {}).get('color', 'DEFAULT')}"
            
            # ═══════════════════════════════════════════════════════════════
            # MIGRACIÓN: Convertir formato antiguo a nuevo sistema multi-UV
            # ═══════════════════════════════════════════════════════════════
            if 'units' not in v:
                # Migrar desde formato antiguo (unit, stock, price, cost)
                old_unit = v.pop('unit', None) or v.pop('unit_type', None) or 'UNIDAD'
                old_label = v.pop('unit_label', None)
                old_stock = v.pop('stock', 0)
                old_reserved = v.pop('reserved', 0)
                old_price = v.pop('price', None)
                old_cost = v.pop('cost', None)
                
                # Mapear valores antiguos al nuevo sistema
                unit_map = {
                    'Unidades': 'UNIDAD', 'Unidad': 'UNIDAD', 'UNIDAD': 'UNIDAD',
                    'Caja': 'CAJA', 'Cajas': 'CAJA', 'CAJA': 'CAJA',
                    'Costal': 'COSTAL', 'Costales': 'COSTAL', 'COSTAL': 'COSTAL',
                    'Saco': 'COSTAL'
                }
                uv = unit_map.get(old_unit, 'UNIDAD')
                if uv == 'UNIDAD' and old_unit not in unit_map and old_unit:
                    uv = 'OTRA'
                    old_label = old_unit
                
                v['units'] = [{
                    'uv': uv,
                    'stock': old_stock,
                    'reserved': old_reserved,
                    'price': old_price if old_price is not None else product.get('price', 0),
                    'cost': old_cost if old_cost is not None else product.get('cost', 0),
                    'label': old_label if uv == 'OTRA' else None
                }]
            else:
                # Ya tiene units[], normalizar cada UV
                for unit_entry in v.get('units', []):
                    if 'uv' not in unit_entry:
                        unit_entry['uv'] = 'UNIDAD'
                    if 'stock' not in unit_entry:
                        unit_entry['stock'] = 0
                    if 'reserved' not in unit_entry:
                        unit_entry['reserved'] = 0
                    if 'price' not in unit_entry:
                        unit_entry['price'] = product.get('price', 0)
                    if 'cost' not in unit_entry:
                        unit_entry['cost'] = product.get('cost', 0)
                    if 'label' not in unit_entry:
                        unit_entry['label'] = None
        
        product['has_variants'] = True
        return
    
    # Migrar producto sin variantes: crear variante por defecto con UV por defecto
    color = product.get('color', '').strip()
    default_variant = {
        'variant_id': f"{product.get('sku', 'V')}-DEFAULT",
        'attributes': {},
        'units': [{
            'uv': 'UNIDAD',
            'stock': product.get('cantidad', 0),
            'reserved': product.get('reserved', 0),
            'price': product.get('price', 0),
            'cost': product.get('cost', 0),
            'label': None
        }]
    }
    
    # Si tiene color, usarlo como atributo
    if color:
        default_variant['variant_id'] = f"{product.get('sku', 'V')}-{color.upper().replace(' ', '')}"
        default_variant['attributes']['color'] = color
    
    product['variants'] = [default_variant]
    product['has_variants'] = True


def get_product_total_stock(product):
    """Calcula stock total sumando todas las variantes y todas sus UV"""
    if 'variants' not in product:
        return product.get('cantidad', 0)
    total = 0
    for v in product.get('variants', []):
        for unit_entry in v.get('units', []):
            total += unit_entry.get('stock', 0)
    return total


def get_product_available_stock(product):
    """Calcula stock disponible (stock - reserved) sumando todas las variantes y UV"""
    if 'variants' not in product:
        return product.get('cantidad', 0) - product.get('reserved', 0)
    total = 0
    for v in product.get('variants', []):
        for unit_entry in v.get('units', []):
            total += unit_entry.get('stock', 0) - unit_entry.get('reserved', 0)
    return total


def get_variant_by_id(product, variant_id):
    """Obtiene una variante específica por su ID"""
    if 'variants' not in product:
        return None
    for v in product.get('variants', []):
        if v.get('variant_id') == variant_id:
            return v
    return None


# ═══════════════════════════════════════════════════════════════════════════
# MULTI-UV: Funciones helper para Unidades de Venta
# ═══════════════════════════════════════════════════════════════════════════

def get_variant_uv(variant, uv):
    """
    Obtiene una UV específica de una variante.
    Args:
        variant: dict de variante
        uv: código de UV (UNIDAD, CAJA, COSTAL, OTRA)
    Returns: dict de UV o None
    """
    if not variant or 'units' not in variant:
        return None
    for unit_entry in variant.get('units', []):
        if unit_entry.get('uv') == uv:
            return unit_entry
    return None


def get_variant_uv_stock(product, variant_id, uv):
    """Obtiene stock de una variante + UV específica"""
    variant = get_variant_by_id(product, variant_id)
    if not variant:
        return 0
    uv_entry = get_variant_uv(variant, uv)
    if uv_entry:
        return uv_entry.get('stock', 0)
    return 0


def get_variant_uv_available(product, variant_id, uv):
    """Obtiene stock disponible de una variante + UV (stock - reserved)"""
    variant = get_variant_by_id(product, variant_id)
    if not variant:
        return 0
    uv_entry = get_variant_uv(variant, uv)
    if uv_entry:
        return uv_entry.get('stock', 0) - uv_entry.get('reserved', 0)
    return 0


def update_variant_uv_stock(product, variant_id, uv, delta, field='stock'):
    """
    Actualiza el stock o reserved de una variante + UV específica.
    delta puede ser positivo (agregar) o negativo (quitar).
    field: 'stock' o 'reserved'
    Returns: True si éxito, False si no existe
    """
    variant = get_variant_by_id(product, variant_id)
    if not variant:
        return False
    
    uv_entry = get_variant_uv(variant, uv)
    if not uv_entry:
        return False
    
    current = uv_entry.get(field, 0)
    new_value = max(0, current + delta)
    uv_entry[field] = new_value
    
    # Sincronizar 'cantidad' del producto base (suma de todos los stocks)
    product['cantidad'] = get_product_total_stock(product)
    
    # Calcular reserved total
    total_reserved = 0
    for v in product.get('variants', []):
        for u in v.get('units', []):
            total_reserved += u.get('reserved', 0)
    product['reserved'] = total_reserved
    
    return True


def get_variant_stock(product, variant_id):
    """Obtiene stock total de una variante (suma de todas sus UV)"""
    variant = get_variant_by_id(product, variant_id)
    if not variant:
        return 0
    return sum(u.get('stock', 0) for u in variant.get('units', []))


def get_variant_available(product, variant_id):
    """Obtiene stock disponible de una variante (suma de todas sus UV)"""
    variant = get_variant_by_id(product, variant_id)
    if not variant:
        return 0
    return sum(u.get('stock', 0) - u.get('reserved', 0) for u in variant.get('units', []))


def update_variant_stock(product, variant_id, delta, field='stock', uv=None):
    """
    Actualiza el stock o reserved de una variante.
    Si se especifica uv, actualiza solo esa UV.
    Si no se especifica uv, usa la primera UV de la variante.
    """
    variant = get_variant_by_id(product, variant_id)
    if not variant:
        return False
    
    # Si no se especifica UV, usar la primera
    if uv is None:
        units = variant.get('units', [])
        if not units:
            return False
        uv = units[0].get('uv', 'UNIDAD')
    
    return update_variant_uv_stock(product, variant_id, uv, delta, field)


def add_uv_to_variant(product, variant_id, uv, stock=0, price=None, cost=None, label=None):
    """
    Agrega una nueva UV a una variante existente.
    Returns: True si éxito, False si la variante no existe o la UV ya existe
    """
    variant = get_variant_by_id(product, variant_id)
    if not variant:
        return False
    
    # Validar UV
    if uv not in VALID_UVS:
        return False
    
    # Verificar que no exista
    if get_variant_uv(variant, uv):
        return False
    
    if 'units' not in variant:
        variant['units'] = []
    
    new_uv = {
        'uv': uv,
        'stock': stock,
        'reserved': 0,
        'price': price if price is not None else product.get('price', 0),
        'cost': cost if cost is not None else product.get('cost', 0),
        'label': label if uv == 'OTRA' else None
    }
    
    variant['units'].append(new_uv)
    product['cantidad'] = get_product_total_stock(product)
    
    return True


def add_variant_to_product(product, attributes, stock=0, price=None, cost=None, uv='UNIDAD', uv_label=None):
    """
    Agrega una nueva variante a un producto con una UV inicial.
    
    Args:
        uv: UNIDAD | CAJA | COSTAL | OTRA
        uv_label: texto personalizado (solo si uv=OTRA)
    
    Returns: variant_id de la nueva variante
    """
    if 'variants' not in product:
        product['variants'] = []
    
    # Validar UV
    if uv not in VALID_UVS:
        uv = 'UNIDAD'
    if uv == 'OTRA' and not uv_label:
        uv_label = 'Otro'
    if uv != 'OTRA':
        uv_label = None
    
    # Generar variant_id basado en atributos
    attr_str = '-'.join(str(v).upper().replace(' ', '') for v in attributes.values()) or 'DEFAULT'
    variant_id = f"{product.get('sku', 'V')}-{attr_str}"
    
    # Verificar que no exista
    if get_variant_by_id(product, variant_id):
        # Modificar ID para hacerlo único
        variant_id = f"{variant_id}-{len(product['variants']) + 1}"
    
    new_variant = {
        'variant_id': variant_id,
        'attributes': attributes,
        'units': [{
            'uv': uv,
            'stock': stock,
            'reserved': 0,
            'price': price if price is not None else product.get('price', 0),
            'cost': cost if cost is not None else product.get('cost', 0),
            'label': uv_label
        }]
    }
    
    product['variants'].append(new_variant)
    product['cantidad'] = get_product_total_stock(product)
    product['has_variants'] = True
    
    return variant_id


def get_variant_uv_price(product, variant_id, uv):
    """Obtiene el precio de una variante + UV específica"""
    variant = get_variant_by_id(product, variant_id)
    if not variant:
        return product.get('price', 0)
    uv_entry = get_variant_uv(variant, uv)
    if uv_entry and uv_entry.get('price') is not None:
        return uv_entry.get('price')
    # Fallback: primer UV de la variante
    if variant.get('units'):
        return variant['units'][0].get('price', product.get('price', 0))
    return product.get('price', 0)


def get_variant_uv_cost(product, variant_id, uv):
    """Obtiene el costo de una variante + UV específica"""
    variant = get_variant_by_id(product, variant_id)
    if not variant:
        return product.get('cost', 0)
    uv_entry = get_variant_uv(variant, uv)
    if uv_entry and uv_entry.get('cost') is not None:
        return uv_entry.get('cost')
    # Fallback: primer UV de la variante
    if variant.get('units'):
        return variant['units'][0].get('cost', product.get('cost', 0))
    return product.get('cost', 0)


def get_variant_price(product, variant_id):
    """Obtiene el precio de la primera UV de una variante"""
    variant = get_variant_by_id(product, variant_id)
    if variant and variant.get('units'):
        return variant['units'][0].get('price', product.get('price', 0))
    return product.get('price', 0)


def get_variant_cost(product, variant_id):
    """Obtiene el costo de la primera UV de una variante"""
    variant = get_variant_by_id(product, variant_id)
    if variant and variant.get('units'):
        return variant['units'][0].get('cost', product.get('cost', 0))
    return product.get('cost', 0)


def migrate_inventory_to_variants(inventory):
    """Migra todos los productos del inventario para tener estructura de variantes"""
    for pid, product in inventory.items():
        normalize_product_variants(product)
    return inventory


# ═══════════════════════════════════════════════════════════════════════════
# FUNCIONES DE PERSISTENCIA OPTIMIZADAS CON CACHÉ
# ═══════════════════════════════════════════════════════════════════════════

@profile_function(name="Guardar inventario")
def save_inventory(inv, immediate=False):
    """
    Guarda inventario usando caché optimizado.
    
    Args:
        inv: Diccionario de inventario
        immediate: Si True, escribe inmediatamente (para operaciones críticas)
    """
    serial = {str(k): v for k, v in inv.items()}
    _json_cache.set(INV_FILE, serial, immediate=immediate)


def save_inventory_sync(inv):
    """Guarda inventario de forma síncrona (bloquea hasta completar)"""
    save_inventory(inv, immediate=True)


@profile_function(name="Cargar auditoría")
def load_audit():
    """Carga audit log desde caché o disco"""
    def _loader():
        if os.path.exists(AUDIT_FILE):
            try:
                with open(AUDIT_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []
    return _json_cache.get(AUDIT_FILE, _loader)


@profile_function(name="Cargar ventas")
def load_sales():
    """Carga ventas desde caché o disco"""
    def _loader():
        if not os.path.exists(SALES_FILE):
            return []
        try:
            with open(SALES_FILE, 'r', encoding='utf-8') as f:
                sales = json.load(f)
            # Normalize all sales to ensure payments[], paid_amount, pending_amount exist
            for sale in sales:
                normalize_sale(sale)
            return sales
        except Exception:
            return []
    return _json_cache.get(SALES_FILE, _loader)


def normalize_sale(sale):
    """Ensure sale has payments[], paid_amount, pending_amount.
    Called for all sales on load to handle legacy data.
    Does NOT call recompute_sale_totals to avoid circular dependency on load.
    """
    if not isinstance(sale, dict):
        return
    # Ensure payments list exists
    if 'payments' not in sale or not isinstance(sale.get('payments'), list):
        sale['payments'] = []
    # Ensure paid_amount exists
    if sale.get('paid_amount') is None:
        sale['paid_amount'] = 0.0
    # Ensure pending_amount exists
    if sale.get('pending_amount') is None:
        sale['pending_amount'] = float(sale.get('total', 0) or 0)
    # Recompute paid/pending from payments for consistency
    total = float(sale.get('total', 0) or 0)
    paid_sum = 0.0
    for p in sale.get('payments', []):
        try:
            paid_sum += float(p.get('amount', 0) or 0)
        except Exception:
            continue
    sale['paid_amount'] = round(max(0.0, paid_sum), 2)
    sale['pending_amount'] = round(max(0.0, total - sale['paid_amount']), 2)


@profile_function(name="Guardar ventas")
def save_sales(sales, immediate=False):
    """
    Guarda ventas usando caché optimizado.
    
    Args:
        sales: Lista de ventas
        immediate: Si True, escribe inmediatamente
    """
    _json_cache.set(SALES_FILE, sales, immediate=immediate)


def save_sales_sync(sales):
    """Guarda ventas de forma síncrona"""
    save_sales(sales, immediate=True)


def next_receipt_number(sales):
    # Simple incremental receipt numbering R0001, R0002 ...
    if not sales:
        return 'R0001'
    nums = [s.get('receipt', '') for s in sales if s.get('receipt')]
    if not nums:
        return 'R0001'
    try:
        last = sorted(nums)[-1]
        num = int(last.lstrip('R'))
        return f'R{num+1:04d}'
    except Exception:
        return f'R{len(sales)+1:04d}'


@profile_function(name="Guardar auditoría")
def save_audit(logs, immediate=False):
    """
    Guarda audit log usando caché optimizado.
    Los logs NO bloquean la respuesta por defecto.
    
    Args:
        logs: Lista de logs
        immediate: Si True, escribe inmediatamente
    """
    _json_cache.set(AUDIT_FILE, logs, immediate=immediate)


# ═══════════════════════════════════════════════════════════════════════════
# SISTEMA DE AUDITORÍA HUMANA
# Tipos válidos: VENTA, PAGO, STOCK, PRODUCTO, SISTEMA
# ═══════════════════════════════════════════════════════════════════════════
AUDIT_TYPES = {'VENTA', 'PAGO', 'STOCK', 'PRODUCTO', 'SISTEMA'}

def get_next_audit_id():
    """Genera un ID incremental para los registros de auditoría"""
    logs = load_audit()
    if not logs:
        return 1
    max_id = max((entry.get('id', 0) for entry in logs), default=0)
    return max_id + 1

def log_action(log_type, message, user=None, related_id=None):
    """
    Registra una acción de auditoría con mensaje humanizado.
    
    Args:
        log_type: Tipo de log (VENTA, PAGO, STOCK, PRODUCTO, SISTEMA)
        message: Mensaje legible para humanos (español)
        user: Usuario que realizó la acción (opcional, usa session si no se provee)
        related_id: ID relacionado (ej: receipt de venta, pid de producto)
    """
    if log_type not in AUDIT_TYPES:
        log_type = 'SISTEMA'
    
    logs = load_audit()
    entry = {
        "id": get_next_audit_id(),
        "type": log_type,
        "message": message,
        "user": user or session.get("user") or "sistema",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "related_id": related_id
    }
    logs.insert(0, entry)  # más reciente primero
    save_audit(logs)


# Funciones helper para generar mensajes humanizados
def format_variant_name(producto, variant_id, uv=None):
    """Genera nombre legible: 'Producto (Variante – UV)'"""
    nombre = producto.get('nombre', 'Producto')
    variant = get_variant_by_id(producto, variant_id) if variant_id else None
    
    if variant:
        attrs = variant.get('attributes', {})
        attr_str = ', '.join(str(v) for v in attrs.values() if v) or variant_id
        if uv:
            return f"{nombre} ({attr_str} – {uv})"
        return f"{nombre} ({attr_str})"
    return nombre


def format_money(amount):
    """Formatea dinero: S/ 100.00"""
    try:
        return f"S/ {float(amount):.2f}"
    except:
        return f"S/ {amount}"


# FUNCIÓN LEGACY para compatibilidad (redirige a log_action)
@profile_function(name="Registrar auditoría")
def log_audit(action, user, pid=None, sku=None, details=None):
    """Función legacy - convierte logs técnicos a formato humanizado"""
    # Mapear acciones antiguas a tipos nuevos
    action_mapping = {
        'sell': 'VENTA',
        'payment': 'PAGO',
        'payment_debug_received': 'PAGO',
        'payment_debug_applied': 'PAGO',
        'add_stock': 'STOCK',
        'remove_stock': 'STOCK',
        'add_variant': 'PRODUCTO',
        'add_uv': 'PRODUCTO',
        'create_product': 'PRODUCTO',
        'edit_product': 'PRODUCTO',
        'delete_product': 'PRODUCTO',
        'login': 'SISTEMA',
        'logout': 'SISTEMA',
        'sale_status': 'VENTA',
        'change_role': 'SISTEMA',
        'delete_user': 'SISTEMA',
        'create_user': 'SISTEMA',
        'password_change': 'SISTEMA'
    }
    
    log_type = action_mapping.get(action, 'SISTEMA')
    
    # Generar mensaje humanizado según la acción
    if action == 'sell':
        receipt = details.get('receipt', '?') if details else '?'
        total = details.get('total', 0) if details else 0
        status = details.get('status', 'CANCELADO') if details else 'CANCELADO'
        status_text = "Por pagar" if status == 'POR PAGAR' else status.capitalize()
        message = f"Venta registrada – Total {format_money(total)} ({status_text})"
        log_action(log_type, message, user, receipt)
    
    elif action == 'payment':
        receipt = details.get('receipt', '?') if details else '?'
        amount = details.get('amount', 0) if details else 0
        method = details.get('method', 'Efectivo') if details else 'Efectivo'
        message = f"Pago recibido – Venta {receipt} – {format_money(amount)} – {method}"
        log_action(log_type, message, user, receipt)
    
    elif action in ('payment_debug_received', 'payment_debug_applied'):
        # Estos logs de debug no se muestran al usuario
        pass
    
    elif action == 'add_stock':
        producto = INVENTARIO.get(pid, {}) if pid else {}
        nombre = producto.get('nombre', sku or f'PID:{pid}')
        variant_id = details.get('variant_id') if details else None
        uv = details.get('uv') if details else None
        cantidad = details.get('cantidad', details.get('delta', 0)) if details else 0
        if cantidad is None:
            cantidad = details.get('after', 0) - details.get('before', 0) if details else 0
        
        if variant_id:
            nombre_completo = format_variant_name(producto, variant_id, uv)
        else:
            nombre_completo = nombre
        
        message = f"Stock agregado: {nombre_completo} +{abs(cantidad)}"
        log_action(log_type, message, user, str(pid) if pid else None)
    
    elif action == 'remove_stock':
        producto = INVENTARIO.get(pid, {}) if pid else {}
        nombre = producto.get('nombre', sku or f'PID:{pid}')
        variant_id = details.get('variant_id') if details else None
        uv = details.get('uv') if details else None
        cantidad = details.get('cantidad', abs(details.get('delta', 0))) if details else 0
        
        if variant_id:
            nombre_completo = format_variant_name(producto, variant_id, uv)
        else:
            nombre_completo = nombre
        
        message = f"Stock reducido: {nombre_completo} -{abs(cantidad)}"
        log_action(log_type, message, user, str(pid) if pid else None)
    
    elif action == 'add_variant':
        producto = INVENTARIO.get(pid, {}) if pid else {}
        nombre = producto.get('nombre', sku or f'PID:{pid}')
        attrs = details.get('attributes', {}) if details else {}
        attr_str = ', '.join(str(v) for v in attrs.values() if v) or 'Nueva'
        message = f"Variante agregada: {nombre} – {attr_str}"
        log_action(log_type, message, user, str(pid) if pid else None)
    
    elif action == 'add_uv':
        producto = INVENTARIO.get(pid, {}) if pid else {}
        nombre = producto.get('nombre', sku or f'PID:{pid}')
        variant_id = details.get('variant_id') if details else None
        uv = details.get('uv', 'UNIDAD') if details else 'UNIDAD'
        
        variant = get_variant_by_id(producto, variant_id) if variant_id else None
        if variant:
            attrs = variant.get('attributes', {})
            attr_str = ', '.join(str(v) for v in attrs.values() if v) or variant_id
        else:
            attr_str = variant_id or 'Variante'
        
        message = f"Unidad de venta agregada: {nombre} ({attr_str}) – {uv}"
        log_action(log_type, message, user, str(pid) if pid else None)
    
    elif action == 'create_product':
        nombre = details.get('nombre', sku or f'PID:{pid}') if details else (sku or f'PID:{pid}')
        message = f"Producto creado: {nombre}"
        log_action(log_type, message, user, str(pid) if pid else None)
    
    elif action == 'edit_product':
        producto = INVENTARIO.get(pid, {}) if pid else {}
        nombre = producto.get('nombre', sku or f'PID:{pid}')
        message = f"Producto editado: {nombre}"
        log_action(log_type, message, user, str(pid) if pid else None)
    
    elif action == 'delete_product':
        nombre = details.get('nombre', sku or f'PID:{pid}') if details else (sku or f'PID:{pid}')
        message = f"Producto eliminado: {nombre}"
        log_action(log_type, message, user, str(pid) if pid else None)
    
    elif action == 'login':
        message = f"Sesión iniciada"
        log_action(log_type, message, user, None)
    
    elif action == 'logout':
        message = f"Sesión cerrada"
        log_action(log_type, message, user, None)
    
    elif action == 'sale_status':
        receipt = details.get('receipt', '?') if details else '?'
        from_status = details.get('from', '?') if details else '?'
        to_status = details.get('to', '?') if details else '?'
        message = f"Estado de venta cambiado: {receipt} – {from_status} → {to_status}"
        log_action(log_type, message, user, receipt)
    
    elif action == 'change_role':
        target_user = details.get('user', '?') if details else '?'
        from_role = details.get('from', '—') if details else '—'
        to_role = details.get('to', '—') if details else '—'
        message = f"Rol de usuario cambiado: {target_user} – {from_role} → {to_role}"
        log_action(log_type, message, user, target_user)
    
    elif action == 'delete_user':
        target_user = details.get('user', '?') if details else '?'
        message = f"Usuario eliminado: {target_user}"
        log_action(log_type, message, user, target_user)
    
    elif action == 'create_user':
        target_user = details.get('user', '?') if details else '?'
        role = details.get('role', '?') if details else '?'
        message = f"Usuario creado: {target_user} – Rol: {role}"
        log_action(log_type, message, user, target_user)
    
    elif action == 'password_change':
        target_user = details.get('user', '?') if details else '?'
        message = f"Contraseña cambiada: {target_user}"
        log_action(log_type, message, user, target_user)
    
    else:
        # Acción desconocida - registrar como sistema
        message = f"Acción: {action}"
        if details:
            if isinstance(details, str):
                message = details
            elif isinstance(details, dict):
                message = f"Acción: {action} – " + ', '.join(f"{k}={v}" for k, v in details.items())
        log_action('SISTEMA', message, user, str(pid) if pid else None)


# ═══════════════════════════════════════════════════════════════════════════
# FUNCIÓN CENTRALIZADA: Registro de pagos en auditoría
# ═══════════════════════════════════════════════════════════════════════════
def register_payment_log(sale, amount, user, method="Efectivo"):
    """
    Registra un pago en el log de auditoría.
    DEBE llamarse cada vez que paid_amount aumenta, sin importar el origen.
    
    Args:
        sale: Diccionario de la venta
        amount: Monto del pago (float)
        user: Usuario que realiza el pago
        method: Método de pago (Efectivo, Yape, etc.)
    """
    if not sale or amount <= 0:
        return
    
    try:
        receipt = sale.get('receipt', '?')
        total = sale.get('total', 0)
        message = f"Pago recibido – Venta {receipt} – {format_money(amount)} – {method}"
        log_action('PAGO', message, user, receipt)
    except Exception:
        pass


INVENTARIO = load_inventory()

# ═══════════════════════════════════════════════════════════════════════════════
# BACKUP AUTOMÁTICO AL INICIO
# ═══════════════════════════════════════════════════════════════════════════════
# Ejecuta backup diario de los archivos de datos.
# - Solo crea 1 backup por día
# - Mantiene los últimos 7 días
# - No rompe la app si falla
run_startup_backup(BASE)


def apply_sale_status_transition(sale, new_status, old_status=None):
    """Apply inventory transitions for a sale when changing from old_status -> new_status.
    Soporta multi-variantes + multi-UV: actualiza stock por variant_id + uv.
    Does not modify `sale['status']` itself; only adjusts `INVENTARIO` quantities/reserved.
    old_status: if None, taken from sale.get('status') or '' (use '' for creation)
    """
    if old_status is None:
        old_status = sale.get('status') or ''
    old_status = old_status or ''
    new_status = (new_status or '').strip()
    deducted_states = {'CANCELADO', 'PARA RECOJO', 'PARA ENVÍO'}

    # No-op if statuses equal
    if old_status == new_status:
        return

    def update_stock(pid, qty, variant_id, uv, delta_stock=0, delta_reserved=0):
        """Helper para actualizar stock (con soporte de variantes + UV)"""
        if pid is None or pid not in INVENTARIO:
            return
        prod = INVENTARIO[pid]
        normalize_product_variants(prod)
        
        if variant_id:
            # Actualizar variante + UV específica
            variant = get_variant_by_id(prod, variant_id)
            if variant:
                # Obtener UV específica
                uv_code = uv or 'UNIDAD'
                uv_entry = get_variant_uv(variant, uv_code)
                
                if uv_entry:
                    if delta_stock != 0:
                        uv_entry['stock'] = max(0, uv_entry.get('stock', 0) + delta_stock)
                    if delta_reserved != 0:
                        uv_entry['reserved'] = max(0, uv_entry.get('reserved', 0) + delta_reserved)
                elif variant.get('units') and len(variant['units']) > 0:
                    # Fallback: usar primera UV
                    first_uv = variant['units'][0]
                    if delta_stock != 0:
                        first_uv['stock'] = max(0, first_uv.get('stock', 0) + delta_stock)
                    if delta_reserved != 0:
                        first_uv['reserved'] = max(0, first_uv.get('reserved', 0) + delta_reserved)
                
                # Sincronizar totales del producto
                prod['cantidad'] = get_product_total_stock(prod)
                total_reserved = 0
                for v in prod.get('variants', []):
                    for u in v.get('units', []):
                        total_reserved += u.get('reserved', 0)
                prod['reserved'] = total_reserved
        else:
            # Sin variante: usar primera variante y primera UV
            if prod.get('variants') and len(prod['variants']) > 0:
                variant = prod['variants'][0]
                if variant.get('units') and len(variant['units']) > 0:
                    first_uv = variant['units'][0]
                    if delta_stock != 0:
                        first_uv['stock'] = max(0, first_uv.get('stock', 0) + delta_stock)
                    if delta_reserved != 0:
                        first_uv['reserved'] = max(0, first_uv.get('reserved', 0) + delta_reserved)
                prod['cantidad'] = get_product_total_stock(prod)
                total_reserved = 0
                for v in prod.get('variants', []):
                    for u in v.get('units', []):
                        total_reserved += u.get('reserved', 0)
                prod['reserved'] = total_reserved

    try:
        # Creation: old_status == '' -> apply according to new_status
        if old_status == '':
            if new_status == 'POR PAGAR':
                for it in sale.get('items', []):
                    pid = to_int(it.get('pid'))
                    qty = to_int(it.get('qty')) or 0
                    variant_id = it.get('variant_id')
                    uv = it.get('uv') or it.get('unit', 'UNIDAD')
                    update_stock(pid, qty, variant_id, uv, delta_reserved=qty)
            elif new_status in deducted_states:
                for it in sale.get('items', []):
                    pid = to_int(it.get('pid'))
                    qty = to_int(it.get('qty')) or 0
                    variant_id = it.get('variant_id')
                    uv = it.get('uv') or it.get('unit', 'UNIDAD')
                    update_stock(pid, qty, variant_id, uv, delta_stock=-qty)

        # POR PAGAR -> paid states: consume reserved -> decrement available
        if old_status == 'POR PAGAR' and new_status in deducted_states:
            for it in sale.get('items', []):
                pid = to_int(it.get('pid'))
                qty = to_int(it.get('qty')) or 0
                variant_id = it.get('variant_id')
                uv = it.get('uv') or it.get('unit', 'UNIDAD')
                update_stock(pid, qty, variant_id, uv, delta_stock=-qty, delta_reserved=-qty)

        # POR PAGAR -> ANULADO: release reservations
        if old_status == 'POR PAGAR' and new_status == 'ANULADO':
            for it in sale.get('items', []):
                pid = to_int(it.get('pid'))
                qty = to_int(it.get('qty')) or 0
                variant_id = it.get('variant_id')
                uv = it.get('uv') or it.get('unit', 'UNIDAD')
                update_stock(pid, qty, variant_id, uv, delta_reserved=-qty)

        # paid/deducted -> ANULADO: return stock
        if old_status in deducted_states and new_status == 'ANULADO':
            for it in sale.get('items', []):
                pid = to_int(it.get('pid'))
                qty = to_int(it.get('qty')) or 0
                variant_id = it.get('variant_id')
                uv = it.get('uv') or it.get('unit', 'UNIDAD')
                update_stock(pid, qty, variant_id, uv, delta_stock=qty)

    except Exception:
        # swallow inventory errors to avoid breaking request flow
        pass


def normalize_payments(sale):
    """Derivar `paid_amount` y `pending_amount` exclusivamente desde `sale['payments']`.
    Asegura valores numéricos y no-negativos.
    """
    if not isinstance(sale, dict):
        return
    total = 0.0
    try:
        total = float(sale.get('total', 0) or 0)
    except Exception:
        total = 0.0
    paid_sum = 0.0
    for p in sale.get('payments', []) or []:
        try:
            paid_sum += float(p.get('amount', 0) or 0)
        except Exception:
            continue
    paid_sum = round(max(0.0, paid_sum), 2)
    # Delegate to recompute function for centralized behavior
    try:
        recompute_sale_totals(sale)
    except NameError:
        # recompute not defined yet (older runtime), fallback to direct assignment
        sale['paid_amount'] = paid_sum
        sale['pending_amount'] = round(max(0.0, total - paid_sum), 2)
    except Exception:
        sale['paid_amount'] = paid_sum
        sale['pending_amount'] = round(max(0.0, total - paid_sum), 2)


def recompute_sale_totals(sale):
    """Centraliza la lógica monetaria y de estado de la venta.

    Reglas:
    - `paid_amount` = suma de `sale['payments'][].amount` (round 2)
    - `pending_amount` = max(0, total - paid_amount)
    - Si `pending_amount == 0` y estado es 'POR PAGAR' -> cambiar a 'CANCELADO'

    Returns a tuple (old_status, new_status) to let callers apply inventory transitions.
    """
    if not isinstance(sale, dict):
        return (None, None)
    total = 0.0
    try:
        total = float(sale.get('total', 0) or 0)
    except Exception:
        total = 0.0

    paid_sum = 0.0
    for p in sale.get('payments', []) or []:
        try:
            paid_sum += float(p.get('amount', 0) or 0)
        except Exception:
            continue
    paid_sum = round(max(0.0, paid_sum), 2)
    sale['paid_amount'] = paid_sum
    sale['pending_amount'] = round(max(0.0, total - paid_sum), 2)

    old_status = sale.get('status') or ''
    new_status = old_status
    try:
        if sale.get('pending_amount') == 0 and old_status == 'POR PAGAR':
            new_status = 'CANCELADO'
            sale['status'] = new_status
    except Exception:
        pass

    return (old_status, new_status)


# ═══════════════════════════════════════════════════════════════════════════
# FUNCIÓN CENTRAL: Crear venta desde carrito (única fuente de ventas)
# ═══════════════════════════════════════════════════════════════════════════
@profile_function(name="Crear venta desde carrito")
def create_sale_from_cart(cart_items, user, client_data=None, payments=None, delivery=None):
    """
    Crea una venta ÚNICAMENTE desde el carrito.
    Esta es la ÚNICA función que debe crear ventas en todo el sistema.
    Soporta multi-variantes + multi-UV por producto.
    
    Args:
        cart_items: Lista de items del carrito:
            [{producto_id, cantidad, precio_unitario, variant_id, uv, uv_label?, variant_attributes?}]
        user: Usuario que crea la venta
        client_data: Dict opcional con {client_name, client_doc, client_obs}
        payments: Lista de pagos [{amount, method}] - si None o vacío, venta queda POR PAGAR
        delivery: Dict opcional con datos de entrega:
            - tipo: 'RECOJO', 'DELIVERY', 'PROVINCIA'
            - Para RECOJO: {nombre?, telefono?, observacion?}
            - Para DELIVERY: {direccion*, telefono*, referencia?, observacion?}
            - Para PROVINCIA: {agencia*, ciudad*, nombre*, dni*, telefono*, observacion?}
    
    Returns:
        dict: {ok: True, sale: {...}, receipt: 'RXXX'} o {ok: False, error: '...'}
    """
    if not cart_items:
        return {"ok": False, "error": "El carrito está vacío"}
    
    client_data = client_data or {}
    payments = payments or []
    delivery = delivery or {}
    
    # Validar stock y construir items
    items_venta = []
    total = 0.0
    
    for item in cart_items:
        pid = item.get("producto_id")
        qty = item.get("cantidad", 0)
        price = item.get("precio_unitario", 0)
        variant_id = item.get("variant_id")
        variant_attributes = item.get("variant_attributes", {})
        uv = item.get("uv") or item.get("unit", "UNIDAD")
        uv_label = item.get("uv_label") or item.get("unit_label")
        
        if pid is None or pid not in INVENTARIO:
            return {"ok": False, "error": f"Producto {pid} no encontrado en inventario"}
        
        if qty <= 0:
            return {"ok": False, "error": "Cantidad inválida en carrito"}
        
        prod = INVENTARIO[pid]
        normalize_product_variants(prod)
        
        # Verificar disponibilidad (por variante + UV)
        if variant_id:
            variant = get_variant_by_id(prod, variant_id)
            if not variant:
                return {"ok": False, "error": f"Variante {variant_id} no encontrada"}
            
            # Obtener UV específica
            if not uv:
                # Usar primera UV de la variante
                if variant.get('units'):
                    uv = variant['units'][0].get('uv', 'UNIDAD')
                else:
                    uv = 'UNIDAD'
            
            uv_entry = get_variant_uv(variant, uv)
            if not uv_entry:
                return {"ok": False, "error": f"UV '{uv}' no encontrada en variante {variant_id}"}
            
            disponible = uv_entry.get('stock', 0) - uv_entry.get('reserved', 0)
            uv_label = uv_entry.get('label') if uv == 'OTRA' else None
        else:
            disponible = get_product_available_stock(prod)
        
        if disponible < qty:
            return {
                "ok": False, 
                "error": f"Stock insuficiente para {prod.get('nombre')} ({uv}). Disponible: {disponible}"
            }
        
        line_total = round(qty * price, 2)
        total += line_total
        
        items_venta.append({
            "pid": pid,
            "qty": qty,
            "price": price,
            "variant_id": variant_id,
            "variant_attributes": variant_attributes,
            "uv": uv,
            "uv_label": uv_label
        })
    
    # Calcular pagos
    total_rounded = round(total, 2)
    paid_sum = sum(round(float(p.get('amount', 0)), 2) for p in payments if p.get('amount'))
    paid_sum = round(min(paid_sum, total_rounded), 2)  # No permitir pagar más del total
    pending = round(total_rounded - paid_sum, 2)
    
    # Determinar estado automáticamente según pagos
    if pending <= 0:
        status = 'CANCELADO'  # Pagado completo
        paid_sum = total_rounded
        pending = 0.0
    else:
        status = 'POR PAGAR'  # Pendiente (parcial o sin pago)
    
    # Crear entrada de venta
    sales = load_sales()
    receipt = next_receipt_number(sales)
    ts_now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    # Procesar datos de entrega
    delivery_type = delivery.get('tipo', 'RECOJO') if delivery else 'RECOJO'
    if delivery_type not in ['RECOJO', 'DELIVERY', 'PROVINCIA']:
        delivery_type = 'RECOJO'
    
    # Construir objeto delivery según tipo
    delivery_data = {'tipo': delivery_type}
    if delivery_type == 'RECOJO':
        delivery_data['nombre'] = delivery.get('nombre', '').strip() if delivery else ''
        delivery_data['telefono'] = delivery.get('telefono', '').strip() if delivery else ''
        delivery_data['observacion'] = delivery.get('observacion', '').strip() if delivery else ''
    elif delivery_type == 'DELIVERY':
        delivery_data['direccion'] = delivery.get('direccion', '').strip() if delivery else ''
        delivery_data['telefono'] = delivery.get('telefono', '').strip() if delivery else ''
        delivery_data['referencia'] = delivery.get('referencia', '').strip() if delivery else ''
        delivery_data['observacion'] = delivery.get('observacion', '').strip() if delivery else ''
    elif delivery_type == 'PROVINCIA':
        delivery_data['agencia'] = delivery.get('agencia', '').strip() if delivery else ''
        delivery_data['ciudad'] = delivery.get('ciudad', '').strip() if delivery else ''
        delivery_data['nombre'] = delivery.get('nombre', '').strip() if delivery else ''
        delivery_data['dni'] = delivery.get('dni', '').strip() if delivery else ''
        delivery_data['telefono'] = delivery.get('telefono', '').strip() if delivery else ''
        delivery_data['observacion'] = delivery.get('observacion', '').strip() if delivery else ''
    
    sale_entry = {
        'receipt': receipt,
        'user': user,
        'ts': ts_now,
        'items': [],
        'client_name': client_data.get('client_name', '').strip(),
        'client_doc': client_data.get('client_doc', '').strip(),
        'client_obs': client_data.get('client_obs', '').strip(),
        'total': total_rounded,
        'status': status,
        'payments': [],
        'paid_amount': paid_sum,
        'pending_amount': pending,
        'pending_reason': None,
        'delivery_type': delivery_type,
        'delivery': delivery_data
    }
    
    # Construir items con detalle completo (incluyendo variantes + UV)
    for it in items_venta:
        pid = it['pid']
        qty = it['qty']
        price = it['price']
        variant_id = it.get('variant_id')
        variant_attributes = it.get('variant_attributes', {})
        uv = it.get('uv', 'UNIDAD')
        uv_label = it.get('uv_label')
        
        prod = INVENTARIO.get(pid, {})
        
        # Obtener costo de la variante + UV específica
        if variant_id:
            unit_cost = float(get_variant_uv_cost(prod, variant_id, uv) or 0)
        else:
            unit_cost = float(prod.get('cost') or 0)
        
        line_cost = round(qty * unit_cost, 2)
        line_total = round(qty * price, 2)
        line_profit = round(line_total - line_cost, 2)
        
        line = {
            'pid': pid,
            'sku': prod.get('sku'),
            'nombre': prod.get('nombre'),
            'qty': qty,
            'unit_price': price,
            'unit_cost': unit_cost,
            'line_cost': line_cost,
            'line_total': line_total,
            'line_profit': line_profit,
            'variant_id': variant_id,
            'variant_attributes': variant_attributes,
            'uv': uv,
            'uv_label': uv_label
        }
        sale_entry['items'].append(line)
    
    # Calcular totales de costo y ganancia
    cost_total = sum((li.get('line_cost') or 0) for li in sale_entry['items'])
    profit_total = sum((li.get('line_profit') or 0) for li in sale_entry['items'])
    sale_entry['cost_total'] = round(cost_total, 2)
    sale_entry['profit_total'] = round(profit_total, 2)
    
    # Agregar pagos al registro
    for p in payments:
        amt = round(float(p.get('amount', 0)), 2)
        if amt > 0:
            sale_entry['payments'].append({
                'amount': amt,
                'method': p.get('method', 'EFECTIVO'),
                'ts': ts_now,
                'user': user
            })
    
    # Aplicar transición de inventario (reservar o descontar según estado)
    old_status = ''
    try:
        apply_sale_status_transition(sale_entry, status, old_status=old_status)
        save_inventory(INVENTARIO)
    except Exception as e:
        return {"ok": False, "error": f"Error al actualizar inventario: {str(e)}"}
    
    # Guardar venta
    sales.insert(0, sale_entry)
    save_sales(sales)
    
    # Auditoría de la venta
    try:
        log_audit('sell', user, details={
            'receipt': receipt, 
            'total': sale_entry['total'], 
            'count': len(sale_entry['items']), 
            'status': status,
            'paid_amount': paid_sum,
            'source': 'carrito'
        })
    except Exception:
        pass
    
    # Auditoría de CADA pago individual (regla de oro: dinero = log)
    for p in sale_entry.get('payments', []):
        try:
            register_payment_log(
                sale=sale_entry,
                amount=p.get('amount', 0),
                user=user,
                method=p.get('method', 'Efectivo')
            )
        except Exception:
            pass
    
    return {
        "ok": True,
        "sale": sale_entry,
        "receipt": receipt,
        "total": total_rounded,
        "status": status,
        "paid_amount": paid_sum,
        "pending_amount": pending
    }


# User-specific settings persistence
USER_SETTINGS_FILE = os.path.join(BASE, "user_settings.json")

def load_user_settings():
    if os.path.exists(USER_SETTINGS_FILE):
        try:
            with open(USER_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_user_settings(settings):
    try:
        with open(USER_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def get_user_theme(username):
    # Returns canonical theme key 'dark' or 'light'. Supports legacy Spanish values.
    settings = load_user_settings()
    user_conf = settings.get(username, {}) if isinstance(settings, dict) else {}
    theme = (user_conf.get('theme') if user_conf else None) or ''
    theme = str(theme).strip().lower()
    # map legacy Spanish values
    if theme in ('oscuro', 'dark'):
        return 'dark'
    if theme in ('claro', 'claro', 'light'):
        return 'light'
    return 'dark'


# Helpers
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def to_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default

def normalize_role(role):
    """Normalize role strings to canonical values.
    Accepts various casings and common synonyms.
    """
    if not role:
        return ""
    r = str(role).strip()
    low = r.lower()
    if low in ("admin", "administrator", "root"):
        return "admin"
    if low in ("operador", "operario", "operator"):
        return "operador"
    if low in ("china import", "china", "china_import"):
        return "China Import"
    return r

def next_product_id():
    if not INVENTARIO:
        return 1
    return max(INVENTARIO.keys()) + 1

def generate_sku(pid):
    return f"P{int(pid):04d}"

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            flash("Debes iniciar sesión.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def role_required(role_name):
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user_role = session.get("role")
            # Si se solicita acceso exclusivo a "China Import", exigir exactamente ese rol
            if role_name == "China Import":
                if user_role != "China Import":
                    flash("Permiso denegado.", "danger")
                    return redirect(url_for("dashboard"))
            else:
                # Para cualquier otro rol, permitir si coincide o si es "China Import" (superusuario)
                if user_role != role_name and user_role != "China Import":
                    flash("Permiso denegado.", "danger")
                    return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return wrapper
    return deco


def generate_csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = uuid.uuid4().hex
    return session['csrf_token']


@app.context_processor
def inject_csrf_token():
    return {'csrf_token': generate_csrf_token()}


def verify_csrf(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if request.method == 'POST':
            token = session.get('csrf_token')
            # Check multiple sources for CSRF token
            form_token = (
                request.form.get('csrf_token') or 
                request.headers.get('X-CSRF-Token') or
                request.headers.get('X-CSRFToken')  # Common JS naming
            )
            # Also check JSON body for AJAX calls
            if not form_token and request.is_json:
                json_data = request.get_json(silent=True) or {}
                form_token = json_data.get('csrf_token')
            
            if not token or not form_token or token != form_token:
                # Return JSON error for API routes (usar "ok" para consistencia)
                if request.path.startswith('/api/'):
                    return {"ok": False, "error": "CSRF token inválido"}, 403
                flash('Sesión expirada. Por favor intenta de nuevo.', 'warning')
                # Redirigir a login si no está autenticado, de lo contrario a dashboard
                if 'user' not in session:
                    return redirect(url_for('login'))
                return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return wrapper


@app.after_request
def set_security_headers(response):
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer-when-downgrade'
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=()'
    # NOTA: HSTS solo en producción con HTTPS real
    # En desarrollo local (HTTP) este header causa problemas
    if request.is_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response


# ═══════════════════════════════════════════════════════════════════════════════
# PROTECCIÓN DE RUTAS SENSIBLES
# ═══════════════════════════════════════════════════════════════════════════════
# Bloquea acceso a carpetas que no deben ser públicas
@app.route('/backups/<path:filename>')
@app.route('/logs/<path:filename>')
def block_sensitive_routes(filename):
    """Bloquea acceso a carpetas sensibles como backups y logs."""
    return "Not Found", 404


# Routes: login/logout
@app.route("/", methods=["GET", "POST"])
@verify_csrf
def login():
    try:
        if request.method == "POST":
            user = (request.form.get("user") or "").strip()
            password = request.form.get("password") or ""
            if not user or not password:
                flash("Usuario y contraseña requeridos.", "warning")
                return redirect(url_for("login"))
            
            user_rec = USERS.get(user)
            
            # Debug de autenticación (solo si DEBUG_AUTH está activo)
            if os.environ.get('DEBUG_AUTH'):
                print(f"[DEBUG AUTH] Usuario: '{user}'")
                print(f"[DEBUG AUTH] Usuario encontrado: {user_rec is not None}")
                if user_rec:
                    pwd_hash = user_rec.get('password', '')[:50]
                    print(f"[DEBUG AUTH] Hash almacenado (primeros 50): {pwd_hash}...")
            
            # Verificación EXCLUSIVA con check_password_hash
            if user_rec and check_password_hash(user_rec["password"], password):
                session.permanent = True  # Sesión permanente (usa PERMANENT_SESSION_LIFETIME)
                session["user"] = user
                session["role"] = user_rec["role"]
                flash(f"Bienvenido, {user}.", "success")
                log_audit("login", user, details="Inicio de sesión")
                return redirect(url_for("dashboard"))
            flash("Usuario o contraseña incorrecta.", "danger")
            return redirect(url_for("login"))
        return render_template("login.html", production_mode=PRODUCTION_MODE)
    except Exception as e:
        print(f"[ERROR LOGIN] {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        flash("Error interno. Por favor intenta de nuevo.", "danger")
        return redirect(url_for("login"))

@app.route("/logout")
@login_required
def logout():
    user = session.get("user")
    session.clear()
    flash("Sesión cerrada.", "info")
    log_audit("logout", user, details="Cierre de sesión")
    return redirect(url_for("login"))

# Dashboard
@app.route("/dashboard")
@login_required
def dashboard():
    # Preparar inventario con stock calculado desde variantes
    inventario_display = {}
    for pid, p in INVENTARIO.items():
        normalize_product_variants(p)
        # Calcular stock total desde variantes (NUNCA usar p['cantidad'])
        stock_total = get_product_total_stock(p)
        stock_available = get_product_available_stock(p)
        
        # Crear copia con stock calculado para la vista
        inventario_display[pid] = {
            **p,
            'cantidad': stock_total,  # Override con suma de variantes
            'available': stock_available
        }
    
    # Estadísticas basadas en variantes
    total_products = len(INVENTARIO)
    low_stock = sum(1 for p in inventario_display.values() if p.get("cantidad", 0) <= p.get("stock_min", 0))
    total_items = sum(p.get("cantidad", 0) for p in inventario_display.values())
    
    return render_template("dashboard.html",
                           inventario=inventario_display,
                           role=session.get("role", ""),
                           total_products=total_products,
                           low_stock=low_stock,
                           total_items=total_items)


# Sales: DEPRECATED - now all sales go through cart
# Redirects to dashboard - sales only via /api/carrito/confirmar
@app.route('/sell', methods=['GET', 'POST'])
@login_required
def sell():
    """
    DEPRECATED: Esta ruta está deshabilitada.
    Todas las ventas ahora se realizan únicamente a través del carrito.
    Use el botón flotante del carrito en el dashboard para agregar productos
    y luego confirme la venta desde el panel del carrito.
    """
    flash('El registro de ventas ahora se realiza únicamente desde el carrito en el Dashboard. '
          'Agregue productos con el botón "Agregar al carrito" y confirme desde el panel lateral.', 'info')
    return redirect(url_for('dashboard'))

# Add / Remove stock (with audit)
@app.route("/add", methods=["POST"])
@login_required
@verify_csrf
def add_stock():
    pid = to_int(request.form.get("id"))
    cantidad = to_int(request.form.get("cantidad"))
    if pid is None or cantidad is None:
        flash("ID o cantidad inválida.", "warning")
        return redirect(url_for("dashboard"))
    if pid not in INVENTARIO:
        flash("Producto no encontrado.", "danger")
        return redirect(url_for("dashboard"))
    if cantidad <= 0:
        flash("La cantidad debe ser mayor que 0.", "warning")
        return redirect(url_for("dashboard"))
    before = INVENTARIO[pid].get("cantidad", 0)
    INVENTARIO[pid]["cantidad"] = before + cantidad
    save_inventory(INVENTARIO)
    flash(f"Se añadieron {cantidad} a {INVENTARIO[pid]['nombre']}.", "success")
    log_audit("add_stock", session.get("user"), pid=pid, sku=INVENTARIO[pid].get("sku"), details={"before": before, "after": INVENTARIO[pid]["cantidad"], "delta": cantidad})
    return redirect(url_for("dashboard"))

@app.route("/remove", methods=["POST"])
@login_required
@verify_csrf
def remove_stock():
    pid = to_int(request.form.get("id"))
    cantidad = to_int(request.form.get("cantidad"))
    if pid is None or cantidad is None:
        flash("ID o cantidad inválida.", "warning")
        return redirect(url_for("dashboard"))
    if pid not in INVENTARIO:
        flash("Producto no encontrado.", "danger")
        return redirect(url_for("dashboard"))
    current = INVENTARIO[pid].get("cantidad", 0)
    if cantidad <= 0:
        flash("La cantidad debe ser mayor que 0.", "warning")
        return redirect(url_for("dashboard"))
    if current < cantidad:
        flash("Stock insuficiente.", "warning")
        return redirect(url_for("dashboard"))
    INVENTARIO[pid]["cantidad"] = current - cantidad
    save_inventory(INVENTARIO)
    flash(f"Se retiraron {cantidad} de {INVENTARIO[pid]['nombre']}.", "success")
    log_audit("remove_stock", session.get("user"), pid=pid, sku=INVENTARIO[pid].get("sku"), details={"before": current, "after": INVENTARIO[pid]["cantidad"], "delta": -cantidad})
    return redirect(url_for("dashboard"))


# ═══════════════════════════════════════════════════════════════════════════
# API JSON ENDPOINTS (para AJAX sin recargar página)
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/stock/add", methods=["POST"])
@login_required
@verify_csrf
def api_add_stock():
    """Agregar stock a una VARIANTE específica vía AJAX - retorna JSON"""
    data = request.get_json(silent=True) or {}
    pid = to_int(data.get("id"))
    cantidad = to_int(data.get("cantidad"))
    variant_id = data.get("variant_id")  # OBLIGATORIO para variantes
    
    if pid is None or cantidad is None:
        return {"success": False, "error": "ID o cantidad inválida"}, 400
    if pid not in INVENTARIO:
        return {"success": False, "error": "Producto no encontrado"}, 404
    if cantidad <= 0:
        return {"success": False, "error": "La cantidad debe ser mayor que 0"}, 400
    
    producto = INVENTARIO[pid]
    normalize_product_variants(producto)
    
    # Si tiene variantes, DEBE especificar variant_id
    if producto.get('variants') and len(producto['variants']) > 0:
        if not variant_id:
            # Usar primera variante por defecto si solo hay una
            if len(producto['variants']) == 1:
                variant_id = producto['variants'][0]['variant_id']
            else:
                return {"success": False, "error": "Debe especificar la variante (variant_id)"}, 400
        
        # Buscar y actualizar la variante específica
        variant = get_variant_by_id(producto, variant_id)
        if not variant:
            return {"success": False, "error": f"Variante {variant_id} no encontrada"}, 404
        
        before = variant.get('stock', 0)
        update_variant_stock(producto, variant_id, cantidad, 'stock')
        after = variant.get('stock', 0)
        
        save_inventory(INVENTARIO)
        
        log_audit("add_stock", session.get("user"), pid=pid, sku=producto.get("sku"), 
                  details={"variant_id": variant_id, "before": before, "after": after, "delta": cantidad})
        
        return {
            "success": True,
            "message": f"Se añadieron {cantidad} a variante {variant_id}",
            "new_stock": after,
            "total_stock": get_product_total_stock(producto),
            "variant_id": variant_id,
            "product": {
                "id": pid,
                "nombre": producto['nombre'],
                "stock": get_product_total_stock(producto),
                "stock_min": producto.get("stock_min", 0)
            }
        }
    else:
        # Producto sin variantes (legacy) - crear variante default y agregar
        add_variant_to_product(producto, {}, cantidad, producto.get('price'), producto.get('cost'))
        save_inventory(INVENTARIO)
        
        return {
            "success": True,
            "message": f"Se añadieron {cantidad} a {producto['nombre']}",
            "new_stock": cantidad,
            "total_stock": get_product_total_stock(producto),
            "product": {
                "id": pid,
                "nombre": producto['nombre'],
                "stock": get_product_total_stock(producto),
                "stock_min": producto.get("stock_min", 0)
            }
        }


@app.route("/api/stock/remove", methods=["POST"])
@login_required
@verify_csrf
def api_remove_stock():
    """Retirar stock de una VARIANTE específica vía AJAX - retorna JSON"""
    data = request.get_json(silent=True) or {}
    pid = to_int(data.get("id"))
    cantidad = to_int(data.get("cantidad"))
    variant_id = data.get("variant_id")  # OBLIGATORIO para variantes
    
    if pid is None or cantidad is None:
        return {"success": False, "error": "ID o cantidad inválida"}, 400
    if pid not in INVENTARIO:
        return {"success": False, "error": "Producto no encontrado"}, 404
    if cantidad <= 0:
        return {"success": False, "error": "La cantidad debe ser mayor que 0"}, 400
    
    producto = INVENTARIO[pid]
    normalize_product_variants(producto)
    
    # Si tiene variantes, DEBE especificar variant_id
    if producto.get('variants') and len(producto['variants']) > 0:
        if not variant_id:
            # Usar primera variante por defecto si solo hay una
            if len(producto['variants']) == 1:
                variant_id = producto['variants'][0]['variant_id']
            else:
                return {"success": False, "error": "Debe especificar la variante (variant_id)"}, 400
        
        # Buscar la variante
        variant = get_variant_by_id(producto, variant_id)
        if not variant:
            return {"success": False, "error": f"Variante {variant_id} no encontrada"}, 404
        
        current = variant.get('stock', 0)
        if current < cantidad:
            return {"success": False, "error": f"Stock insuficiente en variante. Disponible: {current}"}, 400
        
        before = current
        update_variant_stock(producto, variant_id, -cantidad, 'stock')
        after = variant.get('stock', 0)
        
        save_inventory(INVENTARIO)
        
        log_audit("remove_stock", session.get("user"), pid=pid, sku=producto.get("sku"), 
                  details={"variant_id": variant_id, "before": before, "after": after, "delta": -cantidad})
        
        return {
            "success": True,
            "message": f"Se retiraron {cantidad} de variante {variant_id}",
            "new_stock": after,
            "total_stock": get_product_total_stock(producto),
            "variant_id": variant_id,
            "product": {
                "id": pid,
                "nombre": producto['nombre'],
                "stock": get_product_total_stock(producto),
                "stock_min": producto.get("stock_min", 0)
            }
        }
    else:
        # Producto sin variantes - error
        return {"success": False, "error": "Producto sin variantes configuradas"}, 400


@app.route("/api/product/<int:pid>", methods=["GET"])
@login_required
def api_get_product(pid):
    """Obtener información actualizada de un producto incluyendo variantes con multi-UV"""
    if pid not in INVENTARIO:
        return {"success": False, "error": "Producto no encontrado"}, 404
    
    p = INVENTARIO[pid]
    
    # Asegurar que tenga variantes en formato multi-UV
    normalize_product_variants(p)
    
    # Preparar variantes para respuesta con nuevo formato multi-UV
    variants_data = []
    for v in p.get('variants', []):
        # Calcular stock total de la variante (suma de todas sus UV)
        variant_total_stock = sum(u.get('stock', 0) for u in v.get('units', []))
        variant_available = sum(u.get('stock', 0) - u.get('reserved', 0) for u in v.get('units', []))
        
        # Preparar datos de cada UV
        units_data = []
        for unit_entry in v.get('units', []):
            units_data.append({
                'uv': unit_entry.get('uv', 'UNIDAD'),
                'stock': unit_entry.get('stock', 0),
                'reserved': unit_entry.get('reserved', 0),
                'available': unit_entry.get('stock', 0) - unit_entry.get('reserved', 0),
                'price': unit_entry.get('price') if unit_entry.get('price') is not None else p.get('price', 0),
                'cost': unit_entry.get('cost') if unit_entry.get('cost') is not None else p.get('cost', 0),
                'label': unit_entry.get('label')  # Solo para UV=OTRA
            })
        
        variants_data.append({
            'variant_id': v.get('variant_id'),
            'attributes': v.get('attributes', {}),
            'total_stock': variant_total_stock,  # Stock total de esta variante
            'available': variant_available,       # Disponible total de esta variante
            'units': units_data                   # Lista de UV con stock/precio individual
        })
    
    # Calcular stock total dinámicamente desde todas las variantes y UV
    total_stock = get_product_total_stock(p)
    available_stock = get_product_available_stock(p)
    
    return {
        "success": True,
        "product": {
            "id": pid,
            "sku": p.get("sku", ""),
            "nombre": p.get("nombre", ""),
            "total_stock": total_stock,  # Stock calculado dinámicamente
            "cantidad": total_stock,     # Alias para compatibilidad
            "available": available_stock,
            "stock_min": p.get("stock_min", 0),
            "cost": p.get("cost", 0),
            "price": p.get("price", 0),
            "categoria": p.get("categoria", ""),
            "color": p.get("color", ""),
            "imagen": p.get("imagen", "default.png"),
            "variants": variants_data,
            "has_variants": len(variants_data) > 0
        }
    }


@app.route("/api/product/<int:pid>/variant", methods=["POST"])
@login_required
@verify_csrf
@role_required('admin')
def api_add_variant(pid):
    """Agregar una nueva variante a un producto con UV inicial"""
    if pid not in INVENTARIO:
        return {"success": False, "error": "Producto no encontrado"}, 404
    
    data = request.get_json(silent=True)
    if not data:
        return {"success": False, "error": "Datos no recibidos"}, 400
    
    attributes = data.get('attributes', {})
    stock = to_int(data.get('stock')) or 0
    price = data.get('price')
    cost = data.get('cost')
    
    # Sistema UV (Unidad de Venta)
    uv = data.get('uv', data.get('unit', 'UNIDAD')).upper()
    uv_label = data.get('uv_label', data.get('unit_label', None))
    
    # Validar UV
    if uv not in VALID_UVS:
        return {"success": False, "error": f"Unidad de venta inválida. Opciones: {', '.join(VALID_UVS)}"}, 400
    
    if uv == 'OTRA' and not uv_label:
        return {"success": False, "error": "Debe especificar la unidad de venta personalizada"}, 400
    
    if not attributes:
        return {"success": False, "error": "Debe especificar al menos un atributo"}, 400
    
    p = INVENTARIO[pid]
    normalize_product_variants(p)
    
    # Agregar variante
    try:
        if price is not None:
            price = float(price)
        if cost is not None:
            cost = float(cost)
    except (TypeError, ValueError):
        return {"success": False, "error": "Precio o costo inválido"}, 400
    
    variant_id = add_variant_to_product(p, attributes, stock, price, cost, uv, uv_label)
    save_inventory(INVENTARIO)
    
    log_audit('add_variant', session.get('user'), pid=pid, sku=p.get('sku'), 
              details={'variant_id': variant_id, 'attributes': attributes, 'stock': stock, 'uv': uv, 'uv_label': uv_label})
    
    return {
        "success": True,
        "message": f"Variante {variant_id} agregada",
        "variant_id": variant_id
    }


@app.route("/api/product/<int:pid>/variant/<variant_id>/uv", methods=["POST"])
@login_required
@verify_csrf
@role_required('admin')
def api_add_uv_to_variant(pid, variant_id):
    """Agregar una nueva UV a una variante existente"""
    if pid not in INVENTARIO:
        return {"success": False, "error": "Producto no encontrado"}, 404
    
    data = request.get_json(silent=True)
    if not data:
        return {"success": False, "error": "Datos no recibidos"}, 400
    
    uv = data.get('uv', 'UNIDAD').upper()
    stock = to_int(data.get('stock')) or 0
    price = data.get('price')
    cost = data.get('cost')
    uv_label = data.get('uv_label', data.get('label', None))
    
    # Validar UV
    if uv not in VALID_UVS:
        return {"success": False, "error": f"UV inválida. Opciones: {', '.join(VALID_UVS)}"}, 400
    
    if uv == 'OTRA' and not uv_label:
        return {"success": False, "error": "Debe especificar la UV personalizada"}, 400
    
    p = INVENTARIO[pid]
    normalize_product_variants(p)
    
    variant = get_variant_by_id(p, variant_id)
    if not variant:
        return {"success": False, "error": "Variante no encontrada"}, 404
    
    # Verificar que la UV no exista ya en la variante
    if get_variant_uv(variant, uv):
        return {"success": False, "error": f"La UV '{uv}' ya existe en esta variante"}, 400
    
    try:
        if price is not None:
            price = float(price)
        if cost is not None:
            cost = float(cost)
    except (TypeError, ValueError):
        return {"success": False, "error": "Precio o costo inválido"}, 400
    
    success = add_uv_to_variant(p, variant_id, uv, stock, price, cost, uv_label)
    if not success:
        return {"success": False, "error": "No se pudo agregar la UV"}, 400
    
    save_inventory(INVENTARIO)
    
    log_audit('add_uv', session.get('user'), pid=pid, sku=p.get('sku'), 
              details={'variant_id': variant_id, 'uv': uv, 'stock': stock, 'uv_label': uv_label})
    
    return {
        "success": True,
        "message": f"UV '{uv}' agregada a variante {variant_id}",
        "variant_id": variant_id,
        "uv": uv
    }


@app.route("/api/product/<int:pid>/variant/<variant_id>/stock", methods=["POST"])
@login_required
@verify_csrf
def api_update_variant_stock(pid, variant_id):
    """Actualizar stock de una variante + UV específica"""
    if pid not in INVENTARIO:
        return {"success": False, "error": "Producto no encontrado"}, 404
    
    data = request.get_json(silent=True)
    if not data:
        return {"success": False, "error": "Datos no recibidos"}, 400
    
    action = data.get('action')  # 'add' o 'remove'
    cantidad = to_int(data.get('cantidad'))
    uv = data.get('uv')  # UV específica (opcional, usa primera si no se especifica)
    
    if action not in ('add', 'remove'):
        return {"success": False, "error": "Acción debe ser 'add' o 'remove'"}, 400
    
    if cantidad is None or cantidad <= 0:
        return {"success": False, "error": "Cantidad debe ser mayor a 0"}, 400
    
    p = INVENTARIO[pid]
    normalize_product_variants(p)
    
    variant = get_variant_by_id(p, variant_id)
    if not variant:
        return {"success": False, "error": "Variante no encontrada"}, 404
    
    # Si no se especifica UV, usar la primera
    if not uv:
        if variant.get('units') and len(variant['units']) > 0:
            uv = variant['units'][0].get('uv', 'UNIDAD')
        else:
            return {"success": False, "error": "Variante sin UV configurada"}, 400
    
    # Verificar que la UV existe
    uv_entry = get_variant_uv(variant, uv)
    if not uv_entry:
        return {"success": False, "error": f"UV '{uv}' no encontrada en esta variante"}, 404
    
    if action == 'remove':
        available = uv_entry.get('stock', 0) - uv_entry.get('reserved', 0)
        if cantidad > available:
            return {
                "success": False, 
                "error": f"Stock insuficiente en {uv}. Disponible: {available}",
                "available": available
            }, 400
        delta = -cantidad
    else:
        delta = cantidad
    
    update_variant_uv_stock(p, variant_id, uv, delta, 'stock')
    save_inventory(INVENTARIO)
    
    action_name = 'add_stock' if action == 'add' else 'remove_stock'
    log_audit(action_name, session.get('user'), pid=pid, sku=p.get('sku'),
              details={'variant_id': variant_id, 'uv': uv, 'cantidad': cantidad, 'new_stock': uv_entry.get('stock', 0)})
    
    return {
        "success": True,
        "message": f"Stock {'agregado' if action == 'add' else 'reducido'} en {uv}",
        "variant": {
            "variant_id": variant_id,
            "uv": uv,
            "stock": uv_entry.get('stock', 0),
            "available": uv_entry.get('stock', 0) - uv_entry.get('reserved', 0)
        },
        "variant_total_stock": get_variant_stock(p, variant_id),
        "product_total_stock": get_product_total_stock(p)
    }


@app.route("/api/cart/validate", methods=["POST"])
@login_required
@verify_csrf
def api_validate_cart():
    """Validar que un item puede agregarse al carrito (stock suficiente)"""
    data = request.get_json(silent=True) or {}
    pid = to_int(data.get("id"))
    cantidad = to_int(data.get("cantidad"))
    
    if pid is None:
        return {"success": False, "error": "ID de producto inválido"}, 400
    if pid not in INVENTARIO:
        return {"success": False, "error": "Producto no encontrado"}, 404
    if cantidad is None or cantidad <= 0:
        return {"success": False, "error": "Cantidad debe ser mayor a 0"}, 400
    
    current = INVENTARIO[pid].get("cantidad", 0)
    reserved = INVENTARIO[pid].get("reserved", 0)
    available = current - reserved
    
    if cantidad > available:
        return {
            "success": False, 
            "error": f"Stock insuficiente. Disponible: {available}",
            "available": available
        }, 400
    
    return {
        "success": True,
        "message": "Stock disponible",
        "product": {
            "id": pid,
            "nombre": INVENTARIO[pid]["nombre"],
            "available": available
        }
    }


# ═══════════════════════════════════════════════════════════════════════════
# API: CARRITO (session-based)
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/carrito/agregar", methods=["POST"])
@login_required
@verify_csrf
def api_carrito_agregar():
    """
    Agregar producto al carrito (almacenado en session).
    Espera JSON con: producto_id, cantidad, precio_unitario, variacion_id (opcional)
    Siempre retorna JSON, nunca HTML ni redirect.
    """
    data = request.get_json(silent=True)
    
    # Validar que llegó JSON
    if not data:
        return {"ok": False, "error": "Datos no recibidos o formato inválido"}, 400
    
    # Extraer parámetros
    producto_id = to_int(data.get("producto_id"))
    cantidad = to_int(data.get("cantidad"))
    precio_unitario = data.get("precio_unitario")
    variant_id = data.get("variant_id", None)  # ID de variante específica
    variant_attributes = data.get("variant_attributes", {})  # atributos de la variante
    
    # Validaciones
    if producto_id is None:
        return {"ok": False, "error": "ID de producto inválido"}, 400
    
    if producto_id not in INVENTARIO:
        return {"ok": False, "error": "Producto no encontrado"}, 404
    
    if cantidad is None or cantidad <= 0:
        return {"ok": False, "error": "Cantidad debe ser mayor a 0"}, 400
    
    try:
        precio_unitario = float(precio_unitario)
        if precio_unitario < 0:
            raise ValueError()
    except (TypeError, ValueError):
        return {"ok": False, "error": "Precio unitario inválido"}, 400
    
    # Verificar stock disponible (por variante si aplica)
    producto = INVENTARIO[producto_id]
    normalize_product_variants(producto)
    
    # Validar que el producto tenga variantes para poder vender
    variants = producto.get('variants', [])
    if not variants or len(variants) == 0:
        return {
            "ok": False, 
            "error": "Este producto no tiene variantes. Agrega una variante antes de vender."
        }, 400
    
    # Validar que se haya especificado una variante
    if not variant_id:
        return {
            "ok": False, 
            "error": "Debe seleccionar una variante para agregar al carrito."
        }, 400
    
    # ═══════════════════════════════════════════════════════════════════════════
    # MULTI-UV: Validar variante + UV específica
    # ═══════════════════════════════════════════════════════════════════════════
    variant = get_variant_by_id(producto, variant_id)
    if not variant:
        return {"ok": False, "error": "Variante no encontrada"}, 404
    
    # Obtener UV del request (obligatoria ahora)
    uv = data.get('uv', None)
    uv_label = data.get('uv_label', None)
    
    # Si no viene UV, usar la primera disponible de la variante
    if not uv:
        units = variant.get('units', [])
        if units:
            uv = units[0].get('uv', 'UNIDAD')
            uv_label = units[0].get('label')
        else:
            uv = 'UNIDAD'
    
    # Buscar la UV específica en la variante
    uv_entry = get_variant_uv(variant, uv)
    if not uv_entry:
        return {"ok": False, "error": f"UV '{uv}' no encontrada en la variante"}, 404
    
    # Calcular stock disponible de esta UV específica
    disponible = uv_entry.get('stock', 0) - uv_entry.get('reserved', 0)
    
    if cantidad > disponible:
        return {
            "ok": False, 
            "error": f"Stock insuficiente. Disponible: {disponible}",
            "disponible": disponible
        }, 400
    
    # Inicializar carrito en session si no existe
    if "carrito" not in session:
        session["carrito"] = []
    
    carrito = session["carrito"]
    
    # Buscar si ya existe el producto en el carrito (mismo id + variante + UV)
    existing = None
    for item in carrito:
        if (item.get("producto_id") == producto_id and 
            item.get("variant_id") == variant_id and 
            item.get("uv") == uv):
            existing = item
            break
    
    if existing:
        # Validar que no exceda el stock total
        nueva_cantidad = existing["cantidad"] + cantidad
        if nueva_cantidad > disponible:
            return {
                "ok": False,
                "error": f"Stock insuficiente. Ya tienes {existing['cantidad']} en carrito. Disponible: {disponible}",
                "disponible": disponible
            }, 400
        existing["cantidad"] = nueva_cantidad
        existing["precio_unitario"] = precio_unitario  # actualizar precio
    else:
        # Agregar nuevo item al carrito (con UV)
        carrito.append({
            "producto_id": producto_id,
            "sku": producto.get("sku", ""),
            "nombre": producto.get("nombre", ""),
            "cantidad": cantidad,
            "precio_unitario": precio_unitario,
            "variant_id": variant_id,
            "variant_attributes": variant_attributes,
            "uv": uv,
            "uv_label": uv_label
        })
    
    # Guardar cambios en session
    session["carrito"] = carrito
    session.modified = True
    
    # Calcular totales del carrito
    total_items = sum(item["cantidad"] for item in carrito)
    total_monto = sum(item["cantidad"] * item["precio_unitario"] for item in carrito)
    
    return {
        "ok": True,
        "mensaje": f"Producto agregado al carrito",
        "producto": {
            "id": producto_id,
            "nombre": producto.get("nombre", ""),
            "cantidad_agregada": cantidad,
            "precio_unitario": precio_unitario,
            "subtotal": cantidad * precio_unitario,
            "variant_id": variant_id
        },
        "carrito": {
            "total_items": total_items,
            "total_monto": round(total_monto, 2),
            "items_count": len(carrito)
        }
    }


@app.route("/api/carrito/ver", methods=["GET"])
@login_required
def api_carrito_ver():
    """Ver contenido actual del carrito"""
    carrito = session.get("carrito", [])
    total_items = sum(item["cantidad"] for item in carrito)
    total_monto = sum(item["cantidad"] * item["precio_unitario"] for item in carrito)
    
    return {
        "ok": True,
        "carrito": carrito,
        "total_items": total_items,
        "total_monto": round(total_monto, 2)
    }


@app.route("/api/carrito/limpiar", methods=["POST"])
@login_required
@verify_csrf
def api_carrito_limpiar():
    """Vaciar el carrito"""
    session["carrito"] = []
    session.modified = True
    return {"ok": True, "mensaje": "Carrito vaciado"}


@app.route("/api/carrito/eliminar", methods=["POST"])
@login_required
@verify_csrf
def api_carrito_eliminar():
    """Eliminar un item específico del carrito"""
    data = request.get_json(silent=True)
    if not data:
        return {"ok": False, "error": "Datos no recibidos"}, 400
    
    producto_id = to_int(data.get("producto_id"))
    # Soportar tanto variant_id (nuevo) como variacion_id (legacy)
    variant_id = data.get("variant_id") or data.get("variacion_id", None)
    
    if producto_id is None:
        return {"ok": False, "error": "ID de producto inválido"}, 400
    
    carrito = session.get("carrito", [])
    nueva_lista = [
        item for item in carrito 
        if not (item.get("producto_id") == producto_id and item.get("variant_id") == variant_id)
    ]
    
    session["carrito"] = nueva_lista
    session.modified = True
    
    total_items = sum(item["cantidad"] for item in nueva_lista)
    total_monto = sum(item["cantidad"] * item["precio_unitario"] for item in nueva_lista)
    
    return {
        "ok": True,
        "mensaje": "Producto eliminado del carrito",
        "carrito": {
            "total_items": total_items,
            "total_monto": round(total_monto, 2),
            "items_count": len(nueva_lista)
        }
    }


@app.route("/api/carrito/confirmar", methods=["POST"])
@login_required
@verify_csrf
def api_carrito_confirmar():
    """
    Confirmar carrito y crear venta real usando la función central.
    SIEMPRE devuelve JSON, NUNCA hace redirect.
    
    Body JSON opcional:
    {
        "client_name": "...",
        "client_doc": "...",
        "client_obs": "...",
        "payments": [{"amount": 100, "method": "EFECTIVO"}, ...]
    }
    
    Respuesta:
    - success: true/false
    - status: "CANCELADO" o "POR PAGAR"
    - receipt: "RXXXX"
    - redirect: "/receipt/RXXXX" (solo si CANCELADO)
    """
    try:
        carrito = session.get("carrito", [])
        
        if not carrito:
            return {"success": False, "error": "El carrito está vacío"}, 400
        
        # Obtener datos opcionales del request
        data = request.get_json(silent=True) or {}
        
        client_data = {
            "client_name": data.get("client_name", ""),
            "client_doc": data.get("client_doc", ""),
            "client_obs": data.get("client_obs", "")
        }
        
        payments = data.get("payments", [])
        
        # Datos de entrega (nuevo sistema)
        delivery = data.get("delivery", {})
        
        user = session.get("user")
        
        # Usar la función central para crear la venta
        result = create_sale_from_cart(carrito, user, client_data, payments, delivery)
        
        if not result.get("ok"):
            return {"success": False, "error": result.get("error", "Error al crear venta")}, 400
        
        # Limpiar carrito solo si la venta fue exitosa
        session["carrito"] = []
        session.modified = True
        
        # Construir respuesta JSON según estado
        status = result["status"]
        response_data = {
            "success": True,
            "receipt": result["receipt"],
            "total": result["total"],
            "status": status,
            "paid_amount": result["paid_amount"],
            "pending_amount": result["pending_amount"],
            "mensaje": f"Venta {result['receipt']} registrada como {status}"
        }
        
        # Solo incluir redirect si es CANCELADO (para mostrar boleta)
        if status == 'CANCELADO':
            response_data["redirect"] = url_for('receipt_page', receipt=result["receipt"])
        
        return response_data
        
    except Exception as e:
        # Capturar cualquier error inesperado y devolver JSON
        return {"success": False, "error": f"Error interno: {str(e)}"}, 500


# Create product (admin) with upload + validation + audit
@app.route("/products/new", methods=["POST"])
@login_required
@verify_csrf
@role_required("admin")
def create_product():
    """
    Crear producto como contenedor lógico.
    El producto NO tiene stock directo - el inventario vive en las variantes.
    """
    nombre = (request.form.get("nombre") or "").strip()
    categoria = (request.form.get("categoria") or "").strip()
    stock_min = to_int(request.form.get("stock_min")) or 0

    if not nombre:
        flash("Nombre requerido.", "warning")
        return redirect(url_for("dashboard"))

    imagen_name = "default.png"
    file = request.files.get("imagen_file")
    if file and file.filename:
        if not allowed_file(file.filename):
            flash("Formato de imagen no permitido.", "warning")
            return redirect(url_for("dashboard"))
        filename = secure_filename(file.filename)
        unique_name = f"{uuid.uuid4().hex}_{filename}"
        save_path = os.path.join(UPLOAD_DIR, unique_name)
        try:
            file.save(save_path)
            imagen_name = unique_name
        except Exception:
            flash("Error al guardar la imagen.", "warning")
            return redirect(url_for("dashboard"))

    pid = next_product_id()
    sku = generate_sku(pid)
    
    # Producto como contenedor lógico - sin stock directo
    INVENTARIO[pid] = {
        "sku": sku,
        "nombre": nombre,
        "cantidad": 0,  # Siempre 0, el stock real está en variants
        "cost": 0.0,    # Precio/costo base (heredado por variantes si no especifican)
        "price": 0.0,
        "tipo": "Unidades",
        "imagen": imagen_name,
        "stock_min": max(0, stock_min),
        "color": "",
        "categoria": categoria,
        "unidad": "Unidades",
        "variants": [],  # Array vacío - las variantes se agregan después
        "has_variants": True  # Indicador de que usa sistema de variantes
    }
    save_inventory(INVENTARIO)
    flash(f"Producto '{nombre}' creado. Ahora agrega variantes para gestionar el stock.", "success")
    log_audit("create_product", session.get("user"), pid=pid, sku=sku, details={"nombre": nombre})
    return redirect(url_for("dashboard"))

# Edit & Delete endpoints (minimal, with audit)
@app.route("/products/edit/<int:pid>", methods=["POST"])
@login_required
@verify_csrf
@role_required("admin")
def edit_product(pid):
    if pid not in INVENTARIO:
        flash("Producto no encontrado.", "danger")
        return redirect(url_for("dashboard"))
    before = INVENTARIO[pid].copy()
    nombre = (request.form.get("nombre") or before.get("nombre")).strip()
    # NOTA: cantidad ya NO se modifica aquí - el stock solo existe en variantes
    # allow editing cost/price
    try:
        cost = float(request.form.get("cost") or before.get("cost", 0))
    except Exception:
        cost = before.get("cost", 0)
    try:
        price = float(request.form.get("price") or before.get("price", 0))
    except Exception:
        price = before.get("price", 0)
    tipo = (request.form.get("tipo") or before.get("tipo", "")).strip()
    stock_min = to_int(request.form.get("stock_min"), before.get("stock_min", 0))
    color = (request.form.get("color") or before.get("color", "")).strip()
    categoria = (request.form.get("categoria") or before.get("categoria", "")).strip()
    unidad = (request.form.get("unidad") or before.get("unidad", "")).strip()

    INVENTARIO[pid].update({
        "nombre": nombre,
        # cantidad se calcula dinámicamente desde variantes, NO se guarda aquí
        "cost": round(cost, 2),
        "price": round(price, 2),
        "tipo": tipo or before.get("tipo", "Unidades"),
        "stock_min": max(0, stock_min),
        "color": color,
        "categoria": categoria,
        "unidad": unidad
    })
    save_inventory(INVENTARIO)
    flash("Producto actualizado.", "success")
    log_audit("edit_product", session.get("user"), pid=pid, sku=INVENTARIO[pid].get("sku"), details={"before": before, "after": INVENTARIO[pid]})
    return redirect(url_for("dashboard"))

@app.route("/products/delete/<int:pid>", methods=["POST"])
@login_required
@verify_csrf
@role_required("admin")
def delete_product(pid):
    if pid not in INVENTARIO:
        flash("Producto no encontrado.", "danger")
        return redirect(url_for("dashboard"))
    data = INVENTARIO.pop(pid)
    save_inventory(INVENTARIO)
    flash(f"Producto '{data.get('nombre')}' eliminado.", "info")
    # auditoría
    try:
        log_audit("delete_product", session.get("user"), pid=pid, sku=data.get("sku"), details=data)
    except Exception:
        pass
    return redirect(url_for("dashboard"))

# AUDIT page (admin) with filters
@app.route("/audit")
@login_required
@role_required("admin")
def audit_page():
    logs = load_audit()
    # Filtros para el nuevo formato de auditoría humanizada
    q_type = request.args.get("type")  # VENTA, PAGO, STOCK, PRODUCTO, SISTEMA
    q_user = request.args.get("user")
    q_global = (request.args.get("q") or "").strip().lower()
    q_from = request.args.get("from")
    q_to = request.args.get("to")

    def in_range(ts_str):
        """Verifica si el timestamp está en el rango de filtro"""
        if not (q_from or q_to):
            return True
        try:
            # Nuevo formato: "YYYY-MM-DD HH:MM:SS"
            if ' ' in ts_str:
                t = datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            else:
                # Legacy ISO format
                t = datetime.datetime.fromisoformat(ts_str.replace("Z", ""))
        except:
            return True
        if q_from:
            try:
                f = datetime.datetime.fromisoformat(q_from)
                if t < f: return False
            except: pass
        if q_to:
            try:
                to = datetime.datetime.fromisoformat(q_to)
                if t > to: return False
            except: pass
        return True

    filtered = []
    for e in logs:
        # Filtro por tipo (nuevo formato) o action (legacy)
        log_type = e.get("type") or e.get("action", "")
        if q_type and log_type != q_type: continue
        
        # Filtro por usuario
        if q_user and e.get("user") != q_user: continue
        
        # Búsqueda global (en mensaje, usuario, tipo, related_id)
        if q_global:
            s_type = (e.get("type") or e.get("action") or "").lower()
            s_user = (e.get("user") or "").lower()
            s_message = (e.get("message") or "").lower()
            s_related = str(e.get("related_id") or e.get("sku") or "").lower()
            if not (q_global in s_type or q_global in s_user or q_global in s_message or q_global in s_related):
                continue
        
        # Filtro por fecha
        ts = e.get("timestamp") or e.get("ts", "")
        if not in_range(ts): continue
        
        filtered.append(e)

    # Summary cards
    total_products = len(INVENTARIO)
    total_items = sum(get_product_total_stock(p) for p in INVENTARIO.values())
    low_stock = sum(1 for p in INVENTARIO.values() if get_product_total_stock(p) <= p.get("stock_min", 0))

    return render_template("audit.html", logs=filtered, total_products=total_products, low_stock=low_stock, total_items=total_items, query=request.args)

# Export audit CSV (same filters)
@app.route("/audit/export")
@login_required
@role_required("admin")
def audit_export():
    logs = load_audit()
    q_type = request.args.get("type")
    q_user = request.args.get("user")
    q_global = (request.args.get("q") or "").strip().lower()
    q_from = request.args.get("from")
    q_to = request.args.get("to")
    
    def in_range(ts_str):
        if not (q_from or q_to):
            return True
        try:
            if ' ' in ts_str:
                t = datetime.datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            else:
                t = datetime.datetime.fromisoformat(ts_str.replace("Z", ""))
        except:
            return True
        if q_from:
            try:
                f = datetime.datetime.fromisoformat(q_from)
                if t < f: return False
            except: pass
        if q_to:
            try:
                to = datetime.datetime.fromisoformat(q_to)
                if t > to: return False
            except: pass
        return True
    
    filtered = []
    for e in logs:
        log_type = e.get("type") or e.get("action", "")
        if q_type and log_type != q_type: continue
        if q_user and e.get("user") != q_user: continue
        if q_global:
            s_type = (e.get("type") or e.get("action") or "").lower()
            s_user = (e.get("user") or "").lower()
            s_message = (e.get("message") or "").lower()
            s_related = str(e.get("related_id") or e.get("sku") or "").lower()
            if not (q_global in s_type or q_global in s_user or q_global in s_message or q_global in s_related):
                continue
        ts = e.get("timestamp") or e.get("ts", "")
        if not in_range(ts): continue
        filtered.append(e)

    # CSV con formato humanizado
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(["Fecha", "Usuario", "Tipo", "Descripción", "Referencia"])
    for e in filtered:
        ts = e.get("timestamp") or e.get("ts", "")
        user = e.get("user", "")
        log_type = e.get("type") or e.get("action", "")
        message = e.get("message") or json.dumps(e.get("details"), ensure_ascii=False) or ""
        related = e.get("related_id") or e.get("sku") or ""
        writer.writerow([ts, user, log_type, message, related])
    output = si.getvalue()
    return Response(output, mimetype="text/csv", headers={"Content-Disposition":"attachment;filename=auditoria.csv"})


@app.route('/sales/export')
@login_required
@role_required('admin')
def sales_export():
    # allow optional filtering by user, receipt, from/to
    sales = load_sales()
    q_user = request.args.get('user')
    q_receipt = request.args.get('receipt')
    q_global = (request.args.get('q') or '').strip().lower()
    q_from = request.args.get('from')
    q_to = request.args.get('to')

    def in_range(ts_iso):
        if not (q_from or q_to):
            return True
        try:
            t = datetime.datetime.fromisoformat(ts_iso.replace('Z',''))
        except Exception:
            return False
        if q_from:
            try:
                f = datetime.datetime.fromisoformat(q_from)
                if t < f: return False
            except: pass
        if q_to:
            try:
                to = datetime.datetime.fromisoformat(q_to)
                if t > to: return False
            except: pass
        return True

    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(['receipt','user','ts','pid','sku','nombre','qty','unit_price','line_total','total'])
    for s in sales:
        if q_user and s.get('user') != q_user: continue
        if q_receipt and s.get('receipt') != q_receipt: continue
        if not in_range(s.get('ts','')): continue
        if q_global:
            sg = (s.get('user') or '').lower()
            sr = (s.get('receipt') or '').lower()
            st = (s.get('ts') or '').lower()
            found = False
            if q_global in sg or q_global in sr or q_global in st:
                found = True
            if not found:
                # search inside line items
                for item in s.get('items', []):
                    if q_global in str(item.get('pid') or '').lower() or q_global in (str(item.get('sku') or '').lower()) or q_global in (str(item.get('nombre') or '').lower()):
                        found = True
                        break
            if not found:
                continue
        for item in s.get('items', []):
            writer.writerow([
                s.get('receipt'), s.get('user'), s.get('ts'),
                item.get('pid'), item.get('sku'), item.get('nombre'),
                item.get('qty'), item.get('unit_price'), item.get('line_total'), s.get('total')
            ])
    return Response(si.getvalue(), mimetype='text/csv', headers={'Content-Disposition':'attachment;filename=sales.csv'})


@app.route('/receipt/<receipt>')
@login_required
def receipt_page(receipt):
    sales = load_sales()
    sale = next((s for s in sales if s.get('receipt') == receipt), None)
    if not sale:
        flash('Boleta no encontrada.', 'warning')
        return redirect(url_for('dashboard'))
    return render_template('receipt.html', sale=sale)


@app.route('/sales/<receipt>/complete', methods=['POST'])
@login_required
@verify_csrf
def complete_sale(receipt):
    """Marcar una venta como COMPLETADA (entregada al cliente)."""
    sales = load_sales()
    sale = next((s for s in sales if s.get('receipt') == receipt), None)
    if not sale:
        return {'ok': False, 'error': 'Venta no encontrada'}, 404

    current_status = sale.get('status', 'CANCELADO')
    
    # Solo permitir completar si está en estados válidos (pagado y listo para entregar)
    allowed_statuses = {'CANCELADO', 'PARA RECOJO', 'PARA ENVÍO'}
    if current_status not in allowed_statuses:
        return {'ok': False, 'error': f'No se puede completar una venta con estado {current_status}'}, 400

    # Cambiar estado a COMPLETADA
    old_status = current_status
    sale['status'] = 'COMPLETADA'
    sale['completion_ts'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    sale['completed_by'] = session.get('user')
    
    save_sales(sales)
    
    # Registrar en audit log
    try:
        log_audit('sale_complete', session.get('user'), details={
            'receipt': receipt,
            'from': old_status,
            'to': 'COMPLETADA',
            'by': session.get('user')
        })
    except Exception:
        pass

    return {'ok': True, 'message': f'Venta {receipt} marcada como COMPLETADA'}


@app.route('/sales/<receipt>/status', methods=['POST'])
@login_required
@verify_csrf
def change_sale_status(receipt):
    sales = load_sales()
    sale = next((s for s in sales if s.get('receipt') == receipt), None)
    if not sale:
        flash('Venta no encontrada.', 'warning')
        return redirect(request.referrer or url_for('sales_page'))

    new_status = (request.form.get('status') or '').strip().upper()
    if new_status not in SALE_STATUSES:
        flash('Estado inválido.', 'warning')
        return redirect(request.referrer or url_for('sales_page'))

    role = session.get('role', '')
    old_status = sale.get('status') or 'CANCELADO'

    # BLOCK: CANCELADO sales cannot change status (business rule)
    if old_status == 'CANCELADO' and new_status != 'CANCELADO':
        flash('Una venta CANCELADA no puede cambiar de estado.', 'warning')
        return redirect(request.referrer or url_for('sales_page'))

    # Permission rules
    if role == 'operador' and not (old_status == 'POR PAGAR' and new_status == 'CANCELADO'):
        flash('Permiso denegado para cambiar a ese estado.', 'danger')
        return redirect(request.referrer or url_for('sales_page'))

    # Apply central inventory transition logic for this manual status change
    try:
        apply_sale_status_transition(sale, new_status, old_status=old_status)
    except Exception:
        pass

    # ════════════════════════════════════════════════════════════════════════
    # BUG FIX: Si el estado cambia a CANCELADO y hay monto pendiente,
    # significa que se está marcando como "pagado" manualmente.
    # REGLA DE ORO: Si entra dinero → log de pago
    # ════════════════════════════════════════════════════════════════════════
    if old_status == 'POR PAGAR' and new_status == 'CANCELADO':
        pending = float(sale.get('pending_amount', 0) or 0)
        if pending > 0:
            # Registrar el pago del monto pendiente como "Pago manual"
            try:
                register_payment_log(
                    sale=sale,
                    amount=pending,
                    user=session.get('user'),
                    method='Manual (cambio estado)'
                )
            except Exception:
                pass
            
            # Actualizar los montos de la venta
            paid_current = float(sale.get('paid_amount', 0) or 0)
            sale['paid_amount'] = round(paid_current + pending, 2)
            sale['pending_amount'] = 0.0
            
            # Agregar el pago a la lista de pagos
            if 'payments' not in sale:
                sale['payments'] = []
            sale['payments'].append({
                'amount': round(pending, 2),
                'method': 'Manual (cambio estado)',
                'ts': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'user': session.get('user')
            })

    # update sale metadata (do not accept paid_amount from forms)
    sale['status'] = new_status
    if request.form.get('pending_reason'):
        sale['pending_reason'] = request.form.get('pending_reason')
    if request.form.get('annul_reason'):
        sale['annul_reason'] = request.form.get('annul_reason')

    # Recompute totals if there are payments (do NOT mutate amounts elsewhere)
    try:
        if sale.get('payments'):
            old_s, new_s = recompute_sale_totals(sale)
            # if recompute changed status, apply inventory transition centrally
            if old_s and new_s and old_s != new_s:
                try:
                    apply_sale_status_transition(sale, new_s, old_status=old_s)
                except Exception:
                    pass
    except Exception:
        pass

    save_inventory(INVENTARIO)
    save_sales(sales)

    # audit the change
    try:
        log_audit('sale_status', session.get('user'), details={'receipt': receipt, 'from': old_status, 'to': new_status, 'by': session.get('user')})
    except Exception:
        pass

    flash(f'Estado de venta {receipt} cambiado: {old_status} → {new_status}', 'success')
    return redirect(request.referrer or url_for('sales_page'))


@app.route('/sales/<receipt>/payment', methods=['POST'])
@login_required
@verify_csrf
def add_sale_payment(receipt):
    sales = load_sales()
    sale = next((s for s in sales if s.get('receipt') == receipt), None)
    if not sale:
        flash('Venta no encontrada.', 'warning')
        return redirect(request.referrer or url_for('sales_page'))

    if sale.get('status') == 'ANULADO':
        flash('No se pueden agregar pagos a una venta anulada.', 'warning')
        return redirect(request.referrer or url_for('sales_page'))

    # parse and validate amount
    amt_raw = request.form.get('amount')
    method = (request.form.get('method') or '').strip()
    try:
        amt = float(amt_raw or 0)
    except Exception:
        flash('Monto inválido.', 'warning')
        return redirect(request.referrer or url_for('sales_page'))

    if amt <= 0:
        flash('El monto debe ser mayor que 0.', 'warning')
        return redirect(request.referrer or url_for('sales_page'))

    # ensure payments list exists
    if 'payments' not in sale or not isinstance(sale.get('payments'), list):
        sale['payments'] = []

    # compute current pending strictly from payments (never from stored paid_amount)
    total = float(sale.get('total', 0) or 0)
    paid_current = 0.0
    for p in sale.get('payments', []):
        try:
            paid_current += float(p.get('amount', 0) or 0)
        except Exception:
            # ignore malformed entries
            continue
    paid_current = round(max(0.0, paid_current), 2)

    pending = round(max(0.0, total - paid_current), 2)
    if amt > pending:
        flash('El pago excede el monto pendiente.', 'warning')
        return redirect(request.referrer or url_for('sales_page'))

    # audit: received payment input (also write to debug file for traceability)
    try:
        log_audit('payment_debug_received', session.get('user'), details={'receipt': receipt, 'amount_raw': amt_raw, 'amount_parsed': amt, 'method': method})
    except Exception:
        pass
    try:
        dbg_path = os.path.join(BASE, 'payment_debug.log')
        with open(dbg_path, 'a', encoding='utf-8') as dbg:
            dbg.write(f"ENTER add_sale_payment receipt={receipt} user={session.get('user')} amt_raw={amt_raw} amt_parsed={amt} method={method}\n")
    except Exception:
        pass

    # append payment (always add to payments list)
    payment = {
        'amount': round(amt, 2),
        'method': method or 'Efectivo',
        'ts': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'user': session.get('user')
    }
    sale.setdefault('payments', []).append(payment)

    # recompute totals (single source of truth) and detect status transitions
    try:
        old_s, new_s = recompute_sale_totals(sale)
    except Exception:
        old_s, new_s = (None, None)

    # audit: after append and normalization (also file debug)
    try:
        log_audit('payment_debug_applied', session.get('user'), details={'receipt': receipt, 'payments_count': len(sale.get('payments', [])), 'paid_amount': sale.get('paid_amount'), 'pending_amount': sale.get('pending_amount')})
    except Exception:
        pass
    try:
        with open(os.path.join(BASE, 'payment_debug.log'), 'a', encoding='utf-8') as dbg:
            dbg.write(f"APPLIED payment receipt={receipt} payments_count={len(sale.get('payments', []))} paid_amount={sale.get('paid_amount')} pending={sale.get('pending_amount')}\n")
    except Exception:
        pass

    # if recompute changed status, apply inventory transition centrally
    try:
        if old_s and new_s and old_s != new_s:
            try:
                apply_sale_status_transition(sale, new_s, old_status=old_s)
            except Exception:
                pass
    except Exception:
        pass

    # persist inventory and sales, but capture and log any exceptions so we can trace failures
    try:
        save_inventory(INVENTARIO)
    except Exception as e:
        try:
            with open(os.path.join(BASE, 'payment_debug.log'), 'a', encoding='utf-8') as dbg:
                dbg.write(f"ERROR save_inventory: {e}\n")
        except Exception:
            pass
    try:
        save_sales(sales)
        try:
            with open(os.path.join(BASE, 'payment_debug.log'), 'a', encoding='utf-8') as dbg:
                dbg.write(f"SAVED sales.json for receipt={receipt}\n")
        except Exception:
            pass
    except Exception as e:
        try:
            with open(os.path.join(BASE, 'payment_debug.log'), 'a', encoding='utf-8') as dbg:
                dbg.write(f"ERROR save_sales: {e}\n")
        except Exception:
            pass

    # audit payment using centralized function (regla de oro: dinero = log)
    try:
        register_payment_log(
            sale=sale,
            amount=payment['amount'],
            user=session.get('user'),
            method=payment['method']
        )
    except Exception:
        pass

    flash(f'Pago registrado: S/ {payment["amount"]:.2f}', 'success')
    return redirect(request.referrer or url_for('sales_page'))


@app.route('/sales')
@login_required
def sales_page():
    # list sales with basic filtering
    sales = load_sales()
    q_user = request.args.get('user')
    q_receipt = request.args.get('receipt')
    q_global = (request.args.get('q') or '').strip().lower()
    q_from = request.args.get('from')
    q_to = request.args.get('to')

    def in_range(ts_iso):
        if not (q_from or q_to):
            return True
        try:
            t = datetime.datetime.fromisoformat(ts_iso.replace('Z',''))
        except Exception:
            return False
        if q_from:
            try:
                f = datetime.datetime.fromisoformat(q_from)
                if t < f: return False
            except: pass
        if q_to:
            try:
                to = datetime.datetime.fromisoformat(q_to)
                if t > to: return False
            except: pass
        return True

    filtered = []
    for s in sales:
        if q_user and s.get('user') != q_user: continue
        if q_receipt and s.get('receipt') != q_receipt: continue
        if not in_range(s.get('ts','')): continue
        if q_global:
            sg = (s.get('user') or '').lower()
            sr = (s.get('receipt') or '').lower()
            st = (s.get('ts') or '').lower()
            found = False
            if q_global in sg or q_global in sr or q_global in st:
                found = True
            if not found:
                for item in s.get('items', []):
                    if q_global in str(item.get('pid') or '').lower() or q_global in (str(item.get('sku') or '').lower()) or q_global in (str(item.get('nombre') or '').lower()):
                        found = True
                        break
            if not found:
                continue
        filtered.append(s)

    return render_template('sales.html', sales=filtered, query=request.args, role=session.get('role',''))


def compute_sales_stats(sales):
    """Compute KPI and leaderboard statistics from sales list.
    Returns dict with:
    - Pagos recibidos (dinero efectivamente cobrado - ventas CANCELADO)
    - Monto pendiente (dinero por cobrar - ventas POR PAGAR)
    - Ingreso total (todas las ventas)
    - Ganancia total
    - Ticket promedio
    - Top productos por cantidad y ganancia
    - Agrupaciones por día y mes
    """
    total_sales = len(sales)
    total_revenue = sum(float(s.get('total', 0) or 0) for s in sales)
    total_profit = sum(float(s.get('profit_total', 0) or 0) for s in sales)
    avg_ticket = (total_revenue / total_sales) if total_sales else 0.0
    
    # Separar por estado para cálculos financieros claros
    pagos_recibidos = 0.0  # Dinero YA cobrado (ventas completadas)
    monto_pendiente = 0.0  # Dinero por cobrar
    ventas_pagadas = 0
    ventas_pendientes = 0
    
    for s in sales:
        status = s.get('status', 'CANCELADO')
        total_venta = float(s.get('total', 0) or 0)
        paid = float(s.get('paid_amount', 0) or 0)
        pending = float(s.get('pending_amount', 0) or 0)
        
        if status == 'CANCELADO':
            # Venta pagada completamente
            pagos_recibidos += total_venta
            ventas_pagadas += 1
        elif status == 'POR PAGAR':
            # Venta pendiente de pago
            pagos_recibidos += paid  # Lo que ya pagaron
            monto_pendiente += pending  # Lo que falta
            ventas_pendientes += 1
        elif status in ('PARA RECOJO', 'PARA ENVÍO'):
            # Estados intermedios - considerar como pagadas
            pagos_recibidos += total_venta
            ventas_pagadas += 1
        # ANULADO no cuenta

    prod_map = {}
    for s in sales:
        for it in s.get('items', []) or []:
            pid = it.get('pid')
            name = it.get('nombre') or it.get('name') or ''
            sku = it.get('sku') or ''
            qty = to_int(it.get('qty'), 0) or 0
            # Prefer stored per-line profit; otherwise compute from unit_price - unit_cost
            line_profit = it.get('line_profit')
            if line_profit is None:
                try:
                    unit_price = float(it.get('unit_price') or it.get('price') or 0)
                    unit_cost = float(it.get('unit_cost') or it.get('cost') or 0)
                    line_profit = (unit_price - unit_cost) * qty
                except Exception:
                    line_profit = 0.0
            else:
                try:
                    line_profit = float(line_profit)
                except Exception:
                    line_profit = 0.0

            key = str(pid)
            if key not in prod_map:
                prod_map[key] = {'pid': pid, 'nombre': name, 'sku': sku, 'qty': 0, 'profit': 0.0}
            prod_map[key]['qty'] += qty
            prod_map[key]['profit'] += line_profit

    top_by_qty = sorted(prod_map.values(), key=lambda x: x['qty'], reverse=True)[:10]
    top_by_profit = sorted(prod_map.values(), key=lambda x: x['profit'], reverse=True)[:10]

    by_day = {}
    by_month = {}
    for s in sales:
        ts = s.get('ts')
        if not ts:
            continue
        try:
            dt = datetime.datetime.fromisoformat(ts.replace('Z', '+00:00'))
        except Exception:
            continue
        day = dt.date().isoformat()
        month = dt.strftime('%Y-%m')
        rev = float(s.get('total', 0) or 0)
        prof = float(s.get('profit_total', 0) or 0)
        by_day.setdefault(day, {'date': day, 'sales': 0, 'revenue': 0.0, 'profit': 0.0})
        by_day[day]['sales'] += 1
        by_day[day]['revenue'] += rev
        by_day[day]['profit'] += prof
        by_month.setdefault(month, {'month': month, 'sales': 0, 'revenue': 0.0, 'profit': 0.0})
        by_month[month]['sales'] += 1
        by_month[month]['revenue'] += rev
        by_month[month]['profit'] += prof

    by_day_list = sorted(by_day.values(), key=lambda x: x['date'], reverse=True)
    by_month_list = sorted(by_month.values(), key=lambda x: x['month'], reverse=True)
    
    # Calcular totales para la fila TOTAL en la tabla por día
    total_day_sales = sum(d['sales'] for d in by_day_list)
    total_day_revenue = sum(d['revenue'] for d in by_day_list)
    total_day_profit = sum(d['profit'] for d in by_day_list)

    return {
        'total_sales': total_sales,
        'total_revenue': round(total_revenue, 2),
        'total_profit': round(total_profit, 2),
        'avg_ticket': round(avg_ticket, 2),
        # Nuevos campos para claridad financiera
        'pagos_recibidos': round(pagos_recibidos, 2),
        'monto_pendiente': round(monto_pendiente, 2),
        'ventas_pagadas': ventas_pagadas,
        'ventas_pendientes': ventas_pendientes,
        # Productos
        'top_by_qty': top_by_qty[:5],  # Máximo 5
        'top_by_profit': top_by_profit[:5],  # Máximo 5
        # Agrupaciones temporales
        'by_day': by_day_list,
        'by_month': by_month_list,
        # Totales para fila TOTAL
        'total_day_sales': total_day_sales,
        'total_day_revenue': round(total_day_revenue, 2),
        'total_day_profit': round(total_day_profit, 2),
    }


@app.route('/sales/stats')
@login_required
@role_required('admin')
def sales_stats():
    sales = load_sales()
    stats = compute_sales_stats(sales)
    return render_template('sales_stats.html', stats=stats)


# ═══════════════════════════════════════════════════════════════════════════
# ESTADÍSTICAS DE GANANCIAS Y PÉRDIDAS
# ═══════════════════════════════════════════════════════════════════════════
# Solo ventas COMPLETADAS cuentan para estas estadísticas.
# Visible solo para admin y China Import.
# ═══════════════════════════════════════════════════════════════════════════

from services.stats_service import get_stats_service

@app.route('/stats/profit')
@login_required
def profit_stats():
    """
    Muestra estadísticas de ganancias y pérdidas.
    Solo accesible para admin y China Import.
    """
    user_role = session.get('role', '')
    if user_role not in ('admin', 'China Import'):
        flash('No tienes permiso para ver esta página.', 'warning')
        return redirect(url_for('dashboard'))
    
    # Obtener parámetros de filtro
    period = request.args.get('period', 'month')
    custom_start = request.args.get('start', '')
    custom_end = request.args.get('end', '')
    
    # Validar período
    if period not in ('today', 'week', 'month', 'custom'):
        period = 'month'
    
    # Obtener servicio y calcular estadísticas
    stats_service = get_stats_service(load_sales)
    stats = stats_service.calculate_profit_stats(
        period=period,
        custom_start=custom_start,
        custom_end=custom_end
    )
    
    return render_template(
        'profit_stats.html',
        stats=stats,
        period=period,
        custom_start=custom_start,
        custom_end=custom_end
    )


def count_admins():
    return sum(1 for u,v in USERS.items() if v.get("role") == "admin")

# ---- China Import panel & actions ----
@app.route("/china")
@login_required
@role_required("China Import")
def china_panel():
    # lista de usuarios (no incluye contraseñas en template)
    safe_users = {u: {"role": v["role"]} for u, v in USERS.items()}
    return render_template(
        "china_panel.html", 
        users=safe_users, 
        me=session.get("user"),
        csrf_token=session.get("csrf_token", "")
    )

@app.route("/china/role", methods=["POST"])
@login_required
@verify_csrf
@role_required("China Import")
def china_change_role():
    """
    Cambia el rol de un usuario.
    
    SEGURIDAD: La validación de roles protegidos se hace en UserService,
    no aquí. Esto garantiza que la protección funcione aunque el frontend falle.
    """
    username = (request.form.get("username") or "").strip()
    newrole = normalize_role(request.form.get("role") or "")
    admin_user = session.get("user")
    
    if not username or username not in USERS:
        flash("Usuario inválido.", "warning")
        return redirect(url_for("china_panel"))

    # ═══════════════════════════════════════════════════════════════════════
    # USAR SERVICIO PARA VALIDACIONES DE SEGURIDAD (MYSQL READY)
    # ═══════════════════════════════════════════════════════════════════════
    container = get_container(BASE)
    user_service = container.user_service
    
    # Validar si se puede modificar este usuario
    validation = user_service.validate_role_modification(username, new_role=newrole)
    if not validation.get('allowed'):
        flash(validation.get('error', 'Operación no permitida'), "warning")
        return redirect(url_for("china_panel"))
    
    old = USERS[username].get("role")
    
    # Protección adicional: no dejar sin administradores al sistema
    if old == "admin" and newrole != "admin" and count_admins() <= 1:
        flash("No se puede quitar el último admin.", "warning")
        return redirect(url_for("china_panel"))

    USERS[username]["role"] = newrole or ""
    save_users(USERS)
    flash(f"Rol de {username} cambiado: {old} → {newrole}", "success")
    log_audit("change_role", admin_user, details={"user": username, "from": old, "to": newrole})
    return redirect(url_for("china_panel"))

@app.route("/china/delete_user", methods=["POST"])
@login_required
@verify_csrf
@role_required("China Import")
def china_delete_user():
    """
    Elimina un usuario del sistema.
    
    SEGURIDAD: La validación de roles protegidos se hace en UserService,
    no aquí. El rol "China Import" está BLINDADO y no puede ser eliminado.
    """
    username = (request.form.get("username") or "").strip()
    admin_user = session.get("user")
    
    if not username or username not in USERS:
        flash("Usuario inválido.", "warning")
        return redirect(url_for("china_panel"))
    
    # ═══════════════════════════════════════════════════════════════════════
    # USAR SERVICIO PARA VALIDACIONES DE SEGURIDAD (MYSQL READY)
    # ═══════════════════════════════════════════════════════════════════════
    container = get_container(BASE)
    user_service = container.user_service
    
    # Validar si se puede eliminar este usuario
    validation = user_service.validate_role_modification(username, is_delete=True)
    if not validation.get('allowed'):
        flash(validation.get('error', 'Operación no permitida'), "warning")
        return redirect(url_for("china_panel"))
    
    data = USERS[username]
    role = data.get("role", "")
    
    # Protección: no eliminar el último admin
    if role == "admin" and count_admins() <= 1:
        flash("No se puede eliminar el último admin.", "warning")
        return redirect(url_for("china_panel"))
    
    # Protección: no eliminar al propio usuario (evita auto-bloqueo)
    if username == admin_user:
        flash("No puedes eliminar tu propia cuenta desde aquí.", "warning")
        return redirect(url_for("china_panel"))
    
    log_audit("delete_user", admin_user, details={"user": username, "role": role})
    del USERS[username]
    save_users(USERS)
    flash(f"Usuario '{username}' eliminado.", "info")
    return redirect(url_for("china_panel"))


@app.route("/china/create_user", methods=["POST"])
@login_required
@verify_csrf
@role_required("China Import")
def china_create_user():
    """
    Crea un nuevo usuario en el sistema.
    
    Solo accesible por China Import (superusuario).
    La contraseña se guarda hasheada.
    """
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    role = normalize_role(request.form.get("role") or "operador")
    admin_user = session.get("user")
    
    # Validaciones básicas
    if not username:
        flash("El nombre de usuario es requerido.", "warning")
        return redirect(url_for("china_panel"))
    
    if len(username) < 3:
        flash("El nombre de usuario debe tener al menos 3 caracteres.", "warning")
        return redirect(url_for("china_panel"))
    
    if username in USERS:
        flash(f"El usuario '{username}' ya existe.", "warning")
        return redirect(url_for("china_panel"))
    
    if not password or len(password) < 4:
        flash("La contraseña debe tener al menos 4 caracteres.", "warning")
        return redirect(url_for("china_panel"))
    
    # ═══════════════════════════════════════════════════════════════════════
    # PROTECCIÓN: No se puede crear usuarios con rol China Import
    # ═══════════════════════════════════════════════════════════════════════
    container = get_container(BASE)
    user_service = container.user_service
    
    if user_service.is_protected_role(role):
        flash(f"El rol '{role}' no puede ser asignado manualmente.", "warning")
        return redirect(url_for("china_panel"))
    
    # Crear usuario con contraseña hasheada
    password_hash = generate_password_hash(password)
    USERS[username] = {
        "password": password_hash,
        "role": role
    }
    save_users(USERS)
    
    log_audit("create_user", admin_user, details={"user": username, "role": role})
    flash(f"Usuario '{username}' creado con rol '{role}'.", "success")
    return redirect(url_for("china_panel"))


@app.route("/china/change_password", methods=["POST"])
@login_required
@verify_csrf
@role_required("China Import")
def china_change_password():
    """
    Cambia la contraseña de cualquier usuario.
    
    Solo accesible por China Import (superusuario).
    La nueva contraseña se guarda hasheada.
    """
    username = (request.form.get("username") or "").strip()
    new_password = request.form.get("new_password") or ""
    admin_user = session.get("user")
    
    if not username or username not in USERS:
        flash("Usuario inválido.", "warning")
        return redirect(url_for("china_panel"))
    
    if not new_password or len(new_password) < 4:
        flash("La contraseña debe tener al menos 4 caracteres.", "warning")
        return redirect(url_for("china_panel"))
    
    # ═══════════════════════════════════════════════════════════════════════
    # USAR SERVICIO PARA CAMBIO DE CONTRASEÑA (MYSQL READY)
    # ═══════════════════════════════════════════════════════════════════════
    container = get_container(BASE)
    user_service = container.user_service
    
    result = user_service.change_password(username, new_password, admin_user)
    
    if result.get('ok'):
        # Actualizar USERS en memoria también
        USERS[username]["password"] = generate_password_hash(new_password)
        save_users(USERS)
        # Auditar el cambio de contraseña
        log_audit("password_change", admin_user, details={"user": username})
        flash(f"Contraseña de '{username}' actualizada.", "success")
    else:
        flash(result.get('error', 'Error al cambiar contraseña'), "warning")
    
    return redirect(url_for("china_panel"))


@app.context_processor
def inject_user_theme():
    user = session.get('user')
    theme = get_user_theme(user) if user else 'dark'
    return {'user_theme': theme}


@app.route('/settings', methods=['GET', 'POST'])
@login_required
@verify_csrf
def settings():
    user = session.get('user')
    current = get_user_theme(user)
    if request.method == 'POST':
        chosen = (request.form.get('theme') or '').strip().lower()
        if chosen not in ('dark', 'light'):
            chosen = 'dark'
        settings = load_user_settings()
        if not isinstance(settings, dict):
            settings = {}
        settings.setdefault(user, {})['theme'] = chosen
        save_user_settings(settings)
        flash('Preferencia guardada.', 'success')
        return redirect(url_for('settings'))
    return render_template('settings.html', theme=current)

if __name__ == "__main__":
    import os
    # Configuración para desarrollo local y acceso desde red WiFi
    # En producción usar WSGI (gunicorn, waitress, etc.)
    DEBUG = os.environ.get('FLASK_DEBUG', '0') == '1'
    HOST = os.environ.get('FLASK_HOST', '0.0.0.0')  # Escucha en todas las interfaces
    PORT = int(os.environ.get('FLASK_PORT', 5000))
    
    if not DEBUG:
        print(f"\n{'='*50}")
        print(f"  Servidor iniciado en http://{HOST}:{PORT}")
        print(f"  Acceso local: http://localhost:{PORT}")
        print(f"  Acceso red WiFi: http://<TU_IP_LOCAL>:{PORT}")
        print(f"{'='*50}\n")
    
    app.run(host=HOST, port=PORT, debug=DEBUG)