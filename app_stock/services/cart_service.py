# ==============================================================================
# SERVICIO DE CARRITO
# ==============================================================================
# Centraliza toda la lógica de negocio relacionada con el carrito de compras.
# El carrito se almacena en la sesión de Flask.
# ==============================================================================

from typing import Any, Dict, List, Optional, Tuple
from flask import session

from app_stock.services.inventory_service import InventoryService


class CartService:
    """
    Servicio para gestión del carrito de compras.
    
    Responsabilidades:
    - Agregar/eliminar items del carrito
    - Validar stock disponible
    - Calcular totales
    - Limpiar carrito
    
    El carrito se almacena en session['carrito'].
    """
    
    def __init__(self, inventory_service: InventoryService):
        """
        Inicializa el servicio de carrito.
        
        Args:
            inventory_service: Servicio de inventario
        """
        self.inventory_service = inventory_service
    
    def _get_cart(self) -> List[Dict[str, Any]]:
        """
        Obtiene el carrito actual de la sesión.
        
        Returns:
            Lista de items en el carrito
        """
        return session.get('carrito', [])
    
    def _save_cart(self, cart: List[Dict[str, Any]]) -> None:
        """
        Guarda el carrito en la sesión.
        
        Args:
            cart: Lista de items
        """
        session['carrito'] = cart
        session.modified = True
    
    def get_cart(self) -> Dict[str, Any]:
        """
        Obtiene el carrito con totales calculados.
        
        Returns:
            Dict con items, total_items, total_monto
        """
        cart = self._get_cart()
        total_items = sum(item.get('cantidad', 0) for item in cart)
        total_monto = sum(
            item.get('cantidad', 0) * item.get('precio_unitario', 0) 
            for item in cart
        )
        
        return {
            'items': cart,
            'total_items': total_items,
            'total_monto': round(total_monto, 2),
            'items_count': len(cart)
        }
    
    def add_item(
        self,
        producto_id: int,
        cantidad: int,
        precio_unitario: float,
        variant_id: str,
        variant_attributes: Dict[str, str] = None,
        uv: str = None,
        uv_label: str = None
    ) -> Dict[str, Any]:
        """
        Agrega un item al carrito.
        
        Args:
            producto_id: ID del producto
            cantidad: Cantidad a agregar
            precio_unitario: Precio por unidad
            variant_id: ID de la variante
            variant_attributes: Atributos de la variante
            uv: Unidad de venta
            uv_label: Etiqueta de UV
            
        Returns:
            Dict con resultado (ok, error, carrito, etc.)
        """
        # Validaciones básicas
        if producto_id is None:
            return {'ok': False, 'error': 'ID de producto inválido'}
        
        if cantidad is None or cantidad <= 0:
            return {'ok': False, 'error': 'Cantidad debe ser mayor a 0'}
        
        try:
            precio_unitario = float(precio_unitario)
            if precio_unitario < 0:
                raise ValueError()
        except (TypeError, ValueError):
            return {'ok': False, 'error': 'Precio unitario inválido'}
        
        # Obtener producto
        product = self.inventory_service.get_product(producto_id)
        if not product:
            return {'ok': False, 'error': 'Producto no encontrado'}
        
        # Validar que tenga variantes
        variants = product.get('variants', [])
        if not variants:
            return {
                'ok': False, 
                'error': 'Este producto no tiene variantes. Agrega una variante antes de vender.'
            }
        
        # Validar variante
        if not variant_id:
            return {
                'ok': False, 
                'error': 'Debe seleccionar una variante para agregar al carrito.'
            }
        
        variant = self.inventory_service.get_variant(product, variant_id)
        if not variant:
            return {'ok': False, 'error': 'Variante no encontrada'}
        
        # Obtener UV
        if not uv:
            units = variant.get('units', [])
            if units:
                uv = units[0].get('uv', 'UNIDAD')
                uv_label = units[0].get('label')
            else:
                uv = 'UNIDAD'
        
        uv_entry = self.inventory_service.get_variant_uv(variant, uv)
        if not uv_entry:
            return {'ok': False, 'error': f"UV '{uv}' no encontrada en la variante"}
        
        # Calcular disponible
        disponible = uv_entry.get('stock', 0) - uv_entry.get('reserved', 0)
        
        # Obtener carrito actual
        cart = self._get_cart()
        
        # Buscar si ya existe el item
        existing = None
        for item in cart:
            if (item.get('producto_id') == producto_id and 
                item.get('variant_id') == variant_id and 
                item.get('uv') == uv):
                existing = item
                break
        
        if existing:
            # Validar cantidad total
            nueva_cantidad = existing['cantidad'] + cantidad
            if nueva_cantidad > disponible:
                return {
                    'ok': False,
                    'error': f"Stock insuficiente. Ya tienes {existing['cantidad']} en carrito. Disponible: {disponible}",
                    'disponible': disponible
                }
            existing['cantidad'] = nueva_cantidad
            existing['precio_unitario'] = precio_unitario
        else:
            # Validar stock
            if cantidad > disponible:
                return {
                    'ok': False, 
                    'error': f'Stock insuficiente. Disponible: {disponible}',
                    'disponible': disponible
                }
            
            # Agregar nuevo item
            cart.append({
                'producto_id': producto_id,
                'sku': product.get('sku', ''),
                'nombre': product.get('nombre', ''),
                'cantidad': cantidad,
                'precio_unitario': precio_unitario,
                'variant_id': variant_id,
                'variant_attributes': variant_attributes or {},
                'uv': uv,
                'uv_label': uv_label
            })
        
        self._save_cart(cart)
        
        # Calcular totales
        total_items = sum(item['cantidad'] for item in cart)
        total_monto = sum(item['cantidad'] * item['precio_unitario'] for item in cart)
        
        return {
            'ok': True,
            'mensaje': 'Producto agregado al carrito',
            'producto': {
                'id': producto_id,
                'nombre': product.get('nombre', ''),
                'cantidad_agregada': cantidad,
                'precio_unitario': precio_unitario,
                'subtotal': round(cantidad * precio_unitario, 2),
                'variant_id': variant_id
            },
            'carrito': {
                'total_items': total_items,
                'total_monto': round(total_monto, 2),
                'items_count': len(cart)
            }
        }
    
    def remove_item(
        self, 
        producto_id: int, 
        variant_id: str = None,
        uv: str = None
    ) -> Dict[str, Any]:
        """
        Elimina un item del carrito.
        
        Args:
            producto_id: ID del producto
            variant_id: ID de variante (opcional)
            uv: Unidad de venta (opcional)
            
        Returns:
            Dict con resultado
        """
        if producto_id is None:
            return {'ok': False, 'error': 'ID de producto inválido'}
        
        cart = self._get_cart()
        
        # Filtrar el item a eliminar
        new_cart = []
        for item in cart:
            match = item.get('producto_id') == producto_id
            if variant_id:
                match = match and item.get('variant_id') == variant_id
            if uv:
                match = match and item.get('uv') == uv
            
            if not match:
                new_cart.append(item)
        
        self._save_cart(new_cart)
        
        # Calcular totales
        total_items = sum(item['cantidad'] for item in new_cart)
        total_monto = sum(item['cantidad'] * item['precio_unitario'] for item in new_cart)
        
        return {
            'ok': True,
            'mensaje': 'Producto eliminado del carrito',
            'carrito': {
                'total_items': total_items,
                'total_monto': round(total_monto, 2),
                'items_count': len(new_cart)
            }
        }
    
    def update_quantity(
        self,
        producto_id: int,
        variant_id: str,
        uv: str,
        nueva_cantidad: int
    ) -> Dict[str, Any]:
        """
        Actualiza la cantidad de un item en el carrito.
        
        Args:
            producto_id: ID del producto
            variant_id: ID de variante
            uv: Unidad de venta
            nueva_cantidad: Nueva cantidad
            
        Returns:
            Dict con resultado
        """
        if nueva_cantidad <= 0:
            return self.remove_item(producto_id, variant_id, uv)
        
        # Validar stock disponible
        product = self.inventory_service.get_product(producto_id)
        if not product:
            return {'ok': False, 'error': 'Producto no encontrado'}
        
        variant = self.inventory_service.get_variant(product, variant_id)
        if not variant:
            return {'ok': False, 'error': 'Variante no encontrada'}
        
        uv_entry = self.inventory_service.get_variant_uv(variant, uv)
        if not uv_entry:
            return {'ok': False, 'error': 'UV no encontrada'}
        
        disponible = uv_entry.get('stock', 0) - uv_entry.get('reserved', 0)
        if nueva_cantidad > disponible:
            return {
                'ok': False,
                'error': f'Stock insuficiente. Disponible: {disponible}',
                'disponible': disponible
            }
        
        # Actualizar cantidad
        cart = self._get_cart()
        for item in cart:
            if (item.get('producto_id') == producto_id and 
                item.get('variant_id') == variant_id and 
                item.get('uv') == uv):
                item['cantidad'] = nueva_cantidad
                break
        
        self._save_cart(cart)
        
        # Calcular totales
        total_items = sum(item['cantidad'] for item in cart)
        total_monto = sum(item['cantidad'] * item['precio_unitario'] for item in cart)
        
        return {
            'ok': True,
            'mensaje': 'Cantidad actualizada',
            'carrito': {
                'total_items': total_items,
                'total_monto': round(total_monto, 2),
                'items_count': len(cart)
            }
        }
    
    def clear_cart(self) -> Dict[str, Any]:
        """
        Vacía el carrito completamente.
        
        Returns:
            Dict con resultado
        """
        self._save_cart([])
        return {
            'ok': True,
            'mensaje': 'Carrito vaciado',
            'carrito': {
                'total_items': 0,
                'total_monto': 0,
                'items_count': 0
            }
        }
    
    def validate_cart(self) -> Dict[str, Any]:
        """
        Valida que todos los items del carrito tengan stock suficiente.
        
        Returns:
            Dict con ok, errors si hay problemas
        """
        cart = self._get_cart()
        if not cart:
            return {'ok': False, 'error': 'El carrito está vacío'}
        
        errors = []
        valid_items = []
        
        for item in cart:
            producto_id = item.get('producto_id')
            variant_id = item.get('variant_id')
            uv = item.get('uv', 'UNIDAD')
            cantidad = item.get('cantidad', 0)
            
            product = self.inventory_service.get_product(producto_id)
            if not product:
                errors.append(f"Producto {producto_id} no encontrado")
                continue
            
            variant = self.inventory_service.get_variant(product, variant_id)
            if not variant:
                errors.append(f"Variante {variant_id} no encontrada en {product.get('nombre')}")
                continue
            
            uv_entry = self.inventory_service.get_variant_uv(variant, uv)
            if not uv_entry:
                errors.append(f"UV '{uv}' no encontrada en variante {variant_id}")
                continue
            
            disponible = uv_entry.get('stock', 0) - uv_entry.get('reserved', 0)
            if cantidad > disponible:
                errors.append(
                    f"Stock insuficiente para {product.get('nombre')} "
                    f"(Variante: {variant_id}). "
                    f"Solicitado: {cantidad}, Disponible: {disponible}"
                )
            else:
                valid_items.append(item)
        
        if errors:
            return {
                'ok': False,
                'errors': errors,
                'valid_items': len(valid_items),
                'invalid_items': len(cart) - len(valid_items)
            }
        
        return {
            'ok': True,
            'mensaje': 'Carrito válido',
            'items_count': len(cart)
        }
    
    def get_cart_items(self) -> List[Dict[str, Any]]:
        """
        Obtiene los items del carrito.
        
        Returns:
            Lista de items
        """
        return self._get_cart()
