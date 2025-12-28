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
# Opción 1: Usando wsgi.py
python wsgi.py

# Opción 2: Usando gunicorn (como en producción)
gunicorn wsgi:app --bind 0.0.0.0:5000
```

## Ejecutar en producción (Render)

La aplicación está configurada para desplegar en Render automáticamente.
El Procfile ejecuta: `gunicorn wsgi:app --bind 0.0.0.0:$PORT`

## Estructura del proyecto

```
repo_root/
├── wsgi.py              # Punto de entrada para Gunicorn
├── pyproject.toml       # Configuración del paquete Python
├── Procfile             # Comando para Render/Heroku
├── requirements.txt     # Dependencias
├── app_stock/           # Paquete Python principal
│   ├── main.py          # Aplicación Flask y rutas
│   ├── app_container.py # Inyección de dependencias
│   ├── services/        # Lógica de negocio
│   ├── repositories/    # Acceso a datos (JSON -> MySQL)
│   ├── models/          # Entidades del dominio
│   ├── templates/       # Plantillas Jinja2
│   └── static/          # CSS, imágenes
├── tests/               # Pruebas automatizadas
├── *.json               # Archivos de datos
└── backups/             # Backups automáticos
```

## Pruebas automáticas

```bash
python -m pytest tests/
```

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
