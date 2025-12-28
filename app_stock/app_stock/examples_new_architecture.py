# ==============================================================================
# EJEMPLO DE USO DE LA NUEVA ARQUITECTURA
# ==============================================================================
# Este archivo muestra cómo utilizar los nuevos módulos de la arquitectura
# en capas para realizar operaciones comunes.
# 
# NO SE USA EN PRODUCCIÓN - Solo para documentación y testing
# ==============================================================================

"""
ESTRUCTURA DE LA NUEVA ARQUITECTURA
=====================================

app_stock/
├── main.py                 # Aplicación Flask (rutas) - se mantiene por ahora
├── app_container.py        # Contenedor de dependencias (inyección)
│
├── models/                 # CAPA DE MODELOS (Entidades del dominio)
│   ├── __init__.py
│   └── entities.py         # Dataclasses: Product, Sale, User, Payment, etc.
│
├── repositories/           # CAPA DE REPOSITORIOS (Acceso a datos)
│   ├── __init__.py
│   ├── base.py             # Clases base: BaseRepository, DictRepository, ListRepository
│   ├── inventory_repository.py
│   ├── sales_repository.py
│   ├── user_repository.py
│   ├── audit_repository.py
│   └── settings_repository.py
│
└── services/               # CAPA DE SERVICIOS (Lógica de negocio)
    ├── __init__.py
    ├── audit_service.py    # Logging y auditoría
    ├── inventory_service.py # Productos, variantes, stock
    ├── sales_service.py    # Ventas, estados, transiciones
    ├── payment_service.py  # Pagos
    ├── cart_service.py     # Carrito de compras
    └── user_service.py     # Usuarios, autenticación, roles


BENEFICIOS DE ESTA ARQUITECTURA
================================

1. SEPARACIÓN DE RESPONSABILIDADES
   - Rutas: Solo reciben requests y devuelven responses
   - Servicios: Contienen TODA la lógica de negocio
   - Repositorios: Encapsulan el acceso a datos

2. PREPARADO PARA MYSQL
   - Solo hay que modificar los repositorios
   - Servicios y rutas no cambian
   - Los modelos ya definen la estructura de datos

3. TESTABILIDAD
   - Se pueden mockear repositorios para tests unitarios
   - Servicios son fácilmente testeables
   - Dependencias explícitas vía inyección

4. MANTENIBILIDAD
   - Código organizado y documentado
   - Fácil encontrar dónde hacer cambios
   - Reglas de negocio centralizadas


EJEMPLOS DE USO
================
"""

import os
import sys

# Asegurar que el directorio raíz esté en el path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def ejemplo_obtener_productos():
    """Ejemplo: Obtener todos los productos del inventario."""
    from app_container import get_container
    
    container = get_container(BASE_DIR)
    inventory_service = container.inventory_service
    
    # Obtener todos los productos
    products = inventory_service.get_all_products()
    
    print(f"Total de productos: {len(products)}")
    for pid, product in list(products.items())[:3]:  # Solo primeros 3
        total_stock = inventory_service.get_product_total_stock(product)
        print(f"  - {product.get('nombre')} (SKU: {product.get('sku')}): {total_stock} unidades")


def ejemplo_crear_venta():
    """Ejemplo: Crear una venta desde el carrito."""
    from app_container import get_container
    
    container = get_container(BASE_DIR)
    sales_service = container.sales_service
    
    # Items del carrito (normalmente vienen de session)
    cart_items = [
        {
            'producto_id': 1,
            'variant_id': 'v_abc123',
            'uv': 'UNIDAD',
            'cantidad': 2,
            'precio_unitario': 50.00,
            'variant_attributes': {'color': 'Rojo', 'talla': 'M'}
        }
    ]
    
    # Datos del cliente
    client_data = {
        'client_name': 'Juan Pérez',
        'client_doc': '12345678',
        'client_obs': 'Cliente frecuente'
    }
    
    # Pagos iniciales
    payments = [
        {'amount': 50.00, 'method': 'EFECTIVO'}
    ]
    
    # Datos de entrega
    delivery = {
        'type': 'DELIVERY',
        'address': 'Av. Principal 123',
        'district': 'Miraflores',
        'phone': '999888777'
    }
    
    # Crear la venta
    result = sales_service.create_sale_from_cart(
        cart_items=cart_items,
        user='admin',
        client_data=client_data,
        payments=payments,
        delivery=delivery
    )
    
    if result['ok']:
        print(f"Venta creada: {result['receipt']}")
        print(f"  Total: S/ {result['total']:.2f}")
        print(f"  Estado: {result['status']}")
        print(f"  Pagado: S/ {result['paid_amount']:.2f}")
        print(f"  Pendiente: S/ {result['pending_amount']:.2f}")
    else:
        print(f"Error: {result['error']}")


def ejemplo_registrar_pago():
    """Ejemplo: Registrar un pago en una venta."""
    from app_container import get_container
    
    container = get_container(BASE_DIR)
    payment_service = container.payment_service
    
    # Registrar pago
    result = payment_service.add_payment(
        receipt='R0001',
        amount=50.00,
        method='YAPE',
        user='admin'
    )
    
    if result['ok']:
        print(f"Pago registrado en {result['receipt']}")
        print(f"  Monto: S/ {result['payment']['amount']:.2f}")
        print(f"  Total pagado: S/ {result['paid_amount']:.2f}")
        print(f"  Pendiente: S/ {result['pending_amount']:.2f}")
        if result['status_changed']:
            print(f"  Estado cambió: {result['old_status']} → {result['new_status']}")
    else:
        print(f"Error: {result['error']}")


def ejemplo_agregar_stock():
    """Ejemplo: Agregar stock a una variante."""
    from app_container import get_container
    
    container = get_container(BASE_DIR)
    inventory_service = container.inventory_service
    
    # Agregar stock
    success = inventory_service.update_variant_uv_stock(
        pid=1,
        variant_id='v_abc123',
        uv='UNIDAD',
        delta=100,  # Agregar 100 unidades
        field='stock',
        user='admin'
    )
    
    if success:
        print("Stock agregado exitosamente")
    else:
        print("Error al agregar stock")


def ejemplo_buscar_logs():
    """Ejemplo: Buscar en el log de auditoría."""
    from app_container import get_container
    
    container = get_container(BASE_DIR)
    audit_service = container.audit_service
    
    # Buscar pagos recientes
    logs = audit_service.search_logs(
        log_type='PAGO',
        from_date='2024-01-01'
    )
    
    print(f"Pagos encontrados: {len(logs)}")
    for log in logs[:5]:  # Solo primeros 5
        print(f"  - {log.get('timestamp')}: {log.get('message')}")


def ejemplo_autenticar_usuario():
    """Ejemplo: Autenticar un usuario."""
    from app_container import get_container
    
    container = get_container(BASE_DIR)
    user_service = container.user_service
    
    # Autenticar
    user = user_service.authenticate('admin', 'admin123')
    
    if user:
        print(f"Usuario autenticado: {user['username']}")
        print(f"  Rol: {user['role']}")
        print(f"  Es admin: {user_service.is_admin(user['username'])}")
    else:
        print("Credenciales inválidas")


"""
MIGRACIÓN GRADUAL
==================

Para migrar gradualmente desde main.py:

1. Las rutas pueden empezar a usar los servicios:
   
   @app.route('/api/carrito/agregar', methods=['POST'])
   def api_carrito_agregar():
       container = get_container()
       cart_service = container.cart_service
       result = cart_service.add_item(...)
       return jsonify(result)

2. Eliminar funciones duplicadas de main.py una vez migradas.

3. Las variables globales (INVENTARIO, USERS) se reemplazan por:
   - container.inventory_service.get_all_products()
   - container.user_service.get_all_users()

4. Para testing, mockear el contenedor:
   
   def test_create_sale():
       container = AppContainer(base_path='/tmp/test')
       # Usar datos de prueba en /tmp/test/*.json
       result = container.sales_service.create_sale_from_cart(...)
       assert result['ok']


MIGRACIÓN A MYSQL
==================

Cuando se migre a MySQL:

1. Crear nuevos repositorios: inventory_repository_mysql.py, etc.
2. Implementar la misma interfaz (mismos métodos públicos)
3. Modificar app_container.py para usar los nuevos repos:
   
   @property
   def inventory_repo(self):
       if self._inventory_repo is None:
           # Cambiar de JSON a MySQL
           self._inventory_repo = InventoryRepositoryMySQL(self._db_connection)
       return self._inventory_repo

4. Los servicios NO cambian.
5. Las rutas NO cambian.
"""


if __name__ == '__main__':
    print("=" * 60)
    print("EJEMPLOS DE LA NUEVA ARQUITECTURA")
    print("=" * 60)
    
    print("\n1. Obtener productos:")
    try:
        ejemplo_obtener_productos()
    except Exception as e:
        print(f"   (Error: {e})")
    
    print("\n2. Los demás ejemplos requieren datos de prueba específicos.")
    print("   Ver el código fuente para más detalles.")
