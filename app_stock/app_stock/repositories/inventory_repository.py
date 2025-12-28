# ==============================================================================
# REPOSITORIO DE INVENTARIO
# ==============================================================================
# Encapsula todo el acceso a inventory.json
# El inventario se almacena como diccionario: {product_id: {datos_producto}}
# ==============================================================================

import os
from typing import Any, Dict, List, Optional

from app_stock.repositories.base import DictRepository


class InventoryRepository(DictRepository):
    """
    Repositorio para gestión del inventario de productos.
    
    Formato de datos en inventory.json:
    {
        "1": {
            "sku": "SKU001",
            "nombre": "Producto 1",
            "variants": [...],
            ...
        },
        "2": {...}
    }
    
    Nota: Las claves son strings en JSON pero se manejan como int internamente.
    """
    
    def __init__(self, base_path: str):
        """
        Inicializa el repositorio de inventario.
        
        Args:
            base_path: Ruta base del proyecto
        """
        file_path = os.path.join(base_path, 'inventory.json')
        super().__init__(file_path)
        # Cache en memoria para acceso rápido
        self._cache: Dict[int, Dict[str, Any]] = {}
        self._cache_loaded = False
    
    def _normalize_inventory(self, raw_data: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
        """
        Normaliza el inventario convirtiendo claves string a int.
        
        Args:
            raw_data: Datos crudos del JSON (claves string)
            
        Returns:
            Diccionario con claves int
        """
        normalized = {}
        for key, value in raw_data.items():
            try:
                int_key = int(key)
                normalized[int_key] = value
            except (ValueError, TypeError):
                # Si la clave no es convertible a int, mantenerla como está
                normalized[key] = value
        return normalized
    
    def _denormalize_inventory(self, data: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Convierte claves int a string para guardar en JSON.
        
        Args:
            data: Diccionario con claves int
            
        Returns:
            Diccionario con claves string
        """
        return {str(k): v for k, v in data.items()}
    
    def load(self) -> Dict[int, Dict[str, Any]]:
        """
        Carga el inventario completo.
        Usa caché para evitar lecturas repetidas.
        
        Returns:
            Diccionario de productos {pid: datos}
        """
        if not self._cache_loaded:
            raw = self._read_raw()
            self._cache = self._normalize_inventory(raw)
            self._cache_loaded = True
        return self._cache
    
    def save(self, inventory: Dict[int, Dict[str, Any]]) -> None:
        """
        Guarda el inventario completo.
        
        Args:
            inventory: Diccionario de productos
        """
        self._cache = inventory
        self._cache_loaded = True
        self._write_raw(self._denormalize_inventory(inventory))
    
    def reload(self) -> Dict[int, Dict[str, Any]]:
        """
        Fuerza recarga desde archivo ignorando caché.
        
        Returns:
            Inventario actualizado
        """
        self._cache_loaded = False
        return self.load()
    
    def get_product(self, pid: int) -> Optional[Dict[str, Any]]:
        """
        Obtiene un producto por su ID.
        
        Args:
            pid: ID del producto
            
        Returns:
            Datos del producto o None si no existe
        """
        inventory = self.load()
        return inventory.get(pid)
    
    def product_exists(self, pid: int) -> bool:
        """
        Verifica si un producto existe.
        
        Args:
            pid: ID del producto
            
        Returns:
            True si existe
        """
        return pid in self.load()
    
    def create_product(self, pid: int, data: Dict[str, Any]) -> None:
        """
        Crea un nuevo producto.
        
        Args:
            pid: ID del producto
            data: Datos del producto
        """
        inventory = self.load()
        inventory[pid] = data
        self.save(inventory)
    
    def update_product(self, pid: int, data: Dict[str, Any]) -> bool:
        """
        Actualiza un producto existente.
        
        Args:
            pid: ID del producto
            data: Nuevos datos (se mezclan con existentes)
            
        Returns:
            True si se actualizó, False si no existía
        """
        inventory = self.load()
        if pid not in inventory:
            return False
        inventory[pid].update(data)
        self.save(inventory)
        return True
    
    def delete_product(self, pid: int) -> Optional[Dict[str, Any]]:
        """
        Elimina un producto.
        
        Args:
            pid: ID del producto
            
        Returns:
            Datos del producto eliminado o None
        """
        inventory = self.load()
        removed = inventory.pop(pid, None)
        if removed is not None:
            self.save(inventory)
        return removed
    
    def get_all_products(self) -> List[Dict[str, Any]]:
        """
        Obtiene lista de todos los productos.
        
        Returns:
            Lista de productos con su ID incluido
        """
        inventory = self.load()
        result = []
        for pid, data in inventory.items():
            product = data.copy()
            product['id'] = pid
            result.append(product)
        return result
    
    def search_by_name(self, query: str) -> List[Dict[str, Any]]:
        """
        Busca productos por nombre (búsqueda parcial).
        
        Args:
            query: Texto a buscar
            
        Returns:
            Lista de productos que coinciden
        """
        query_lower = query.lower()
        inventory = self.load()
        results = []
        for pid, data in inventory.items():
            if query_lower in data.get('nombre', '').lower():
                product = data.copy()
                product['id'] = pid
                results.append(product)
        return results
    
    def search_by_sku(self, sku: str) -> Optional[Dict[str, Any]]:
        """
        Busca un producto por SKU exacto.
        
        Args:
            sku: SKU a buscar
            
        Returns:
            Producto encontrado o None
        """
        inventory = self.load()
        for pid, data in inventory.items():
            if data.get('sku') == sku:
                product = data.copy()
                product['id'] = pid
                return product
        return None
    
    def get_low_stock_products(self) -> List[Dict[str, Any]]:
        """
        Obtiene productos con stock bajo o agotado.
        
        Returns:
            Lista de productos bajo stock mínimo
        """
        inventory = self.load()
        results = []
        for pid, data in inventory.items():
            total_stock = self._calculate_total_stock(data)
            stock_min = data.get('stock_min', 0)
            if total_stock <= stock_min:
                product = data.copy()
                product['id'] = pid
                product['total_stock'] = total_stock
                results.append(product)
        return results
    
    def get_next_id(self) -> int:
        """
        Genera el siguiente ID disponible para un nuevo producto.
        
        Returns:
            Siguiente ID entero disponible
        """
        inventory = self.load()
        if not inventory:
            return 1
        return max(inventory.keys()) + 1
    
    def _calculate_total_stock(self, product: Dict[str, Any]) -> int:
        """
        Calcula el stock total de un producto desde sus variantes.
        
        Args:
            product: Datos del producto
            
        Returns:
            Stock total
        """
        total = 0
        for variant in product.get('variants', []):
            for unit in variant.get('units', []):
                total += unit.get('stock', 0)
        return total
    
    # ===========================================================================
    # Métodos para variantes (helpers para manipulación de variantes)
    # ===========================================================================
    
    def get_variant(self, pid: int, variant_id: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene una variante específica de un producto.
        
        Args:
            pid: ID del producto
            variant_id: ID de la variante
            
        Returns:
            Datos de la variante o None
        """
        product = self.get_product(pid)
        if not product:
            return None
        for variant in product.get('variants', []):
            if variant.get('variant_id') == variant_id:
                return variant
        return None
    
    def add_variant(self, pid: int, variant_data: Dict[str, Any]) -> bool:
        """
        Agrega una variante a un producto.
        
        Args:
            pid: ID del producto
            variant_data: Datos de la nueva variante
            
        Returns:
            True si se agregó exitosamente
        """
        inventory = self.load()
        if pid not in inventory:
            return False
        
        if 'variants' not in inventory[pid]:
            inventory[pid]['variants'] = []
        
        inventory[pid]['variants'].append(variant_data)
        self.save(inventory)
        return True
    
    def update_variant_stock(
        self, 
        pid: int, 
        variant_id: str, 
        uv: str, 
        delta: int, 
        field: str = 'stock'
    ) -> bool:
        """
        Actualiza el stock de una UV específica.
        
        Args:
            pid: ID del producto
            variant_id: ID de la variante
            uv: Unidad de venta
            delta: Cambio en cantidad (positivo o negativo)
            field: Campo a actualizar ('stock' o 'reserved')
            
        Returns:
            True si se actualizó exitosamente
        """
        inventory = self.load()
        if pid not in inventory:
            return False
        
        product = inventory[pid]
        for variant in product.get('variants', []):
            if variant.get('variant_id') == variant_id:
                for unit in variant.get('units', []):
                    if unit.get('uv') == uv:
                        current = unit.get(field, 0)
                        unit[field] = max(0, current + delta)
                        self.save(inventory)
                        return True
        return False
