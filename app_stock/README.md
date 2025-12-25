# app_stock

Pequeña app Flask para gestionar inventario y ventas.

## Características
- Gestión de inventario con variantes y unidades de venta
- Sistema de ventas con carrito
- Estadísticas de ganancias y pérdidas
- Auditoría de acciones
- Tema claro/oscuro
- **Responsive móvil** (768px breakpoint)

## Requisitos
- Python 3.10+
- Instalar dependencias:

```bash
python -m pip install -r requirements.txt
```

## Ejecutar la app (desarrollo)

```bash
python main.py
```

## Pruebas automáticas

```bash
python tests/test_sales.py
```

La prueba usa el cliente de pruebas de Flask y verificará que `sales.json`, `inventory.json` y `audit.json` se actualicen correctamente.

## Adaptación Móvil
El sistema está optimizado para uso interno en dispositivos móviles:

### Breakpoints
- **Desktop**: > 768px (diseño completo)
- **Tablet**: 481-768px (grid 2 columnas)
- **Móvil**: ≤ 480px (grid 1 columna)

### Características móviles
- **Navbar fija superior** con hamburger menu
- **Sidebar off-canvas** con navegación completa
- **Modales fullscreen** para mejor usabilidad
- **Grid responsive** de productos
- **Filtros scrolleables** horizontalmente
- **Botones touch-friendly** (mínimo 44px)
- **FAB (Floating Action Button)** para carrito (donde aplique)
