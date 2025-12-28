# ==============================================================================
# WSGI Entry Point - Para Gunicorn en Render/Producción
# ==============================================================================
# Este archivo es el punto de entrada para servidores WSGI como Gunicorn.
#
# USO EN RENDER:
#   gunicorn wsgi:app --bind 0.0.0.0:$PORT
#
# ESTRUCTURA DEL PROYECTO:
#   repo_root/           <- Directorio de trabajo (en sys.path automáticamente)
#   ├── wsgi.py          <- Este archivo
#   ├── pyproject.toml
#   └── app_stock/       <- Paquete Python
#       ├── __init__.py
#       ├── main.py
#       ├── services/
#       └── repositories/
#
# Con esta estructura, los imports absolutos funcionan SIN manipular sys.path:
#   from app_stock.main import app  ✓
#   from app_stock.services import InventoryService  ✓
#
# ==============================================================================

from app_stock.main import app

# ==============================================================================
# PUNTO DE ENTRADA
# ==============================================================================
# Variable 'app' exportada para Gunicorn:
#   gunicorn wsgi:app
#
# Para desarrollo local:
#   python wsgi.py
# ==============================================================================

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
