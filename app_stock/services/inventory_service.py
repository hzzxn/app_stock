# ==============================================================================
# SERVICIO DE INVENTARIO
# ==============================================================================
# Centraliza toda la lógica de negocio relacionada con productos y stock.
# Maneja el sistema de variantes multi-UV.
# ==============================================================================

import uuid
from typing import Any, Dict, List, Optional, Tuple

from repositories.inventory_repository import InventoryRepository
from services.audit_service import AuditService


# Lista de UVs válidas (Unidades de Venta)
VALID_UVS = frozenset(['UNIDAD', 'PAR', 'DOCENA', 'CAJA', 'BOLSA', 'OTRA'])


class InventoryService:
    """
    Servicio para gestión de inventario.
    
    Responsabilidades:
    - CRUD de productos
    - Gestión de variantes y unidades de venta
    - Control de stock (entradas, salidas, reservas)
    - Normalización de datos legacy
    - Generación de SKU
    """
    
    def __init__(
        self, 
        inventory_repo: InventoryRepository,
        audit_service: AuditService = None
    ):
        """
        Inicializa el servicio de inventario.
        
        Args:
            inventory_repo: Repositorio de inventario
            audit_service: Servicio de auditoría (opcional)
        """
        self.inventory_repo = inventory_repo
        self.audit_service = audit_service
    
    # =========================================================================
    # OPERACIONES DE PRODUCTOS
    # =========================================================================
    
    def get_all_products(self) -> Dict[int, Dict[str, Any]]:
        """
        Obtiene todos los productos del inventario.
        
        Returns:
            Diccionario {pid: producto}
        """
        return self.inventory_repo.load()
    
    def get_product(self, pid: int) -> Optional[Dict[str, Any]]:
        """
        Obtiene un producto por su ID.
        
        Args:
            pid: ID del producto
            
        Returns:
            Datos del producto o None
        """
        product = self.inventory_repo.get_product(pid)
        if product:
            self.normalize_product_variants(product)
        return product
    
    def product_exists(self, pid: int) -> bool:
        """Verifica si un producto existe."""
        return self.inventory_repo.product_exists(pid)
    
    def create_product(
        self, 
        nombre: str,
        categoria: str = '',
        stock_min: int = 0,
        imagen: str = 'default.png',
        price: float = 0.0,
        cost: float = 0.0,
        user: str = None
    ) -> Tuple[int, str]:
        """
        Crea un nuevo producto (contenedor lógico sin stock directo).
        
        Args:
            nombre: Nombre del producto
            categoria: Categoría
            stock_min: Stock mínimo
            imagen: Nombre de archivo de imagen
            price: Precio base
            cost: Costo base
            user: Usuario que crea (para auditoría)
            
        Returns:
            Tupla (pid, sku) del producto creado
        """
        pid = self.inventory_repo.get_next_id()
        sku = self.generate_sku(pid)
        
        product_data = {
            'sku': sku,
            'nombre': nombre,
            'cantidad': 0,  # Stock calculado dinámicamente
            'cost': round(cost, 2),
            'price': round(price, 2),
            'tipo': 'Unidades',
            'imagen': imagen,
            'stock_min': max(0, stock_min),
            'color': '',
            'categoria': categoria,
            'unidad': 'Unidades',
            'variants': [],  # Las variantes se agregan después
            'has_variants': True
        }
        
        self.inventory_repo.create_product(pid, product_data)
        
        # Auditar
        if self.audit_service and user:
            self.audit_service.log_product_created(user, pid, sku, nombre)
        
        return (pid, sku)
    
    def update_product(
        self, 
        pid: int, 
        updates: Dict[str, Any],
        user: str = None
    ) -> bool:
        """
        Actualiza datos de un producto.
        
        Args:
            pid: ID del producto
            updates: Campos a actualizar
            user: Usuario que actualiza (para auditoría)
            
        Returns:
            True si se actualizó
        """
        product = self.get_product(pid)
        if not product:
            return False
        
        # Campos permitidos para actualización
        allowed_fields = [
            'nombre', 'categoria', 'stock_min', 'imagen',
            'price', 'cost', 'tipo', 'color', 'unidad'
        ]
        
        filtered_updates = {
            k: v for k, v in updates.items() 
            if k in allowed_fields
        }
        
        # Normalizar valores numéricos
        if 'price' in filtered_updates:
            filtered_updates['price'] = round(float(filtered_updates['price'] or 0), 2)
        if 'cost' in filtered_updates:
            filtered_updates['cost'] = round(float(filtered_updates['cost'] or 0), 2)
        if 'stock_min' in filtered_updates:
            filtered_updates['stock_min'] = max(0, int(filtered_updates['stock_min'] or 0))
        
        success = self.inventory_repo.update_product(pid, filtered_updates)
        
        # Auditar
        if success and self.audit_service and user:
            self.audit_service.log_product_updated(
                user, pid, product.get('sku', ''), 
                filtered_updates.get('nombre', product.get('nombre', '')),
                filtered_updates
            )
        
        return success
    
    def delete_product(self, pid: int, user: str = None) -> Optional[Dict[str, Any]]:
        """
        Elimina un producto.
        
        Args:
            pid: ID del producto
            user: Usuario que elimina (para auditoría)
            
        Returns:
            Datos del producto eliminado o None
        """
        product = self.get_product(pid)
        if not product:
            return None
        
        removed = self.inventory_repo.delete_product(pid)
        
        # Auditar
        if removed and self.audit_service and user:
            self.audit_service.log_product_deleted(
                user, pid, product.get('sku', ''), product.get('nombre', '')
            )
        
        return removed
    
    def save_inventory(self, inventory: Dict[int, Dict[str, Any]]) -> None:
        """
        Guarda el inventario completo.
        
        Args:
            inventory: Diccionario completo de inventario
        """
        self.inventory_repo.save(inventory)
    
    def reload_inventory(self) -> Dict[int, Dict[str, Any]]:
        """
        Recarga el inventario desde archivo.
        
        Returns:
            Inventario actualizado
        """
        return self.inventory_repo.reload()
    
    # =========================================================================
    # GENERACIÓN DE SKU
    # =========================================================================
    
    def generate_sku(self, pid: int) -> str:
        """
        Genera un SKU único para un producto.
        
        Args:
            pid: ID del producto
            
        Returns:
            SKU en formato "SKU-XXXXX"
        """
        return f"SKU-{pid:05d}"
    
    # =========================================================================
    # NORMALIZACIÓN DE VARIANTES
    # =========================================================================
    
    def normalize_product_variants(self, product: Dict[str, Any]) -> None:
        """
        Normaliza un producto al formato multi-variante multi-UV.
        Modifica el producto in-place.
        
        Args:
            product: Datos del producto a normalizar
        """
        if 'variants' not in product:
            product['variants'] = []
        
        for variant in product['variants']:
            # Asegurar que tenga variant_id
            if 'variant_id' not in variant:
                variant['variant_id'] = f"v_{uuid.uuid4().hex[:8]}"
            
            # Migrar formato legacy (stock directo en variante) a multi-UV
            if 'units' not in variant:
                variant['units'] = []
                # Migrar stock legacy
                legacy_stock = variant.pop('stock', 0)
                legacy_reserved = variant.pop('reserved', 0)
                legacy_price = variant.pop('price', None)
                legacy_cost = variant.pop('cost', None)
                legacy_uv = variant.pop('uv', variant.pop('unit', 'UNIDAD'))
                legacy_label = variant.pop('uv_label', variant.pop('unit_label', None))
                
                if legacy_stock > 0 or legacy_reserved > 0:
                    variant['units'].append({
                        'uv': legacy_uv,
                        'stock': legacy_stock,
                        'reserved': legacy_reserved,
                        'price': legacy_price,
                        'cost': legacy_cost,
                        'label': legacy_label
                    })
            
            # Asegurar que cada UV tenga los campos requeridos
            for unit in variant.get('units', []):
                unit.setdefault('uv', 'UNIDAD')
                unit.setdefault('stock', 0)
                unit.setdefault('reserved', 0)
    
    # =========================================================================
    # OPERACIONES DE VARIANTES
    # =========================================================================
    
    def get_variant(
        self, 
        product: Dict[str, Any], 
        variant_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Busca una variante por su ID.
        
        Args:
            product: Datos del producto
            variant_id: ID de la variante
            
        Returns:
            Datos de la variante o None
        """
        for v in product.get('variants', []):
            if v.get('variant_id') == variant_id:
                return v
        return None
    
    def add_variant(
        self, 
        pid: int,
        attributes: Dict[str, str],
        stock: int = 0,
        price: float = None,
        cost: float = None,
        uv: str = 'UNIDAD',
        uv_label: str = None,
        user: str = None
    ) -> Optional[str]:
        """
        Agrega una nueva variante a un producto.
        
        Args:
            pid: ID del producto
            attributes: Atributos de la variante (color, talla, etc.)
            stock: Stock inicial
            price: Precio de la variante (hereda del producto si None)
            cost: Costo de la variante (hereda del producto si None)
            uv: Unidad de venta
            uv_label: Etiqueta para UV=OTRA
            user: Usuario (para auditoría)
            
        Returns:
            ID de la nueva variante o None si falló
        """
        product = self.get_product(pid)
        if not product:
            return None
        
        # Validar UV
        if uv not in VALID_UVS:
            return None
        
        if uv == 'OTRA' and not uv_label:
            return None
        
        # Generar ID de variante
        variant_id = f"v_{uuid.uuid4().hex[:8]}"
        
        # Crear variante con UV inicial
        variant_data = {
            'variant_id': variant_id,
            'attributes': attributes,
            'units': [{
                'uv': uv,
                'stock': stock,
                'reserved': 0,
                'price': price,
                'cost': cost,
                'label': uv_label
            }]
        }
        
        self.inventory_repo.add_variant(pid, variant_data)
        
        # Auditar
        if self.audit_service and user:
            self.audit_service.log_variant_added(
                user, pid, product.get('sku', ''), variant_id, attributes
            )
        
        return variant_id
    
    def add_uv_to_variant(
        self, 
        pid: int,
        variant_id: str,
        uv: str,
        stock: int = 0,
        price: float = None,
        cost: float = None,
        uv_label: str = None
    ) -> bool:
        """
        Agrega una nueva UV a una variante existente.
        
        Args:
            pid: ID del producto
            variant_id: ID de la variante
            uv: Nueva unidad de venta
            stock: Stock inicial
            price: Precio (hereda del producto si None)
            cost: Costo (hereda del producto si None)
            uv_label: Etiqueta para UV=OTRA
            
        Returns:
            True si se agregó exitosamente
        """
        product = self.get_product(pid)
        if not product:
            return False
        
        variant = self.get_variant(product, variant_id)
        if not variant:
            return False
        
        # Validar UV
        if uv not in VALID_UVS:
            return False
        
        if uv == 'OTRA' and not uv_label:
            return False
        
        # Verificar que no exista ya
        for unit in variant.get('units', []):
            if unit.get('uv') == uv:
                return False
        
        # Agregar la nueva UV
        variant.setdefault('units', []).append({
            'uv': uv,
            'stock': stock,
            'reserved': 0,
            'price': price,
            'cost': cost,
            'label': uv_label
        })
        
        self.save_inventory(self.get_all_products())
        return True
    
    def get_variant_uv(
        self, 
        variant: Dict[str, Any], 
        uv: str
    ) -> Optional[Dict[str, Any]]:
        """
        Busca una UV específica en una variante.
        
        Args:
            variant: Datos de la variante
            uv: Unidad de venta a buscar
            
        Returns:
            Datos de la UV o None
        """
        for unit in variant.get('units', []):
            if unit.get('uv') == uv:
                return unit
        return None
    
    # =========================================================================
    # OPERACIONES DE STOCK
    # =========================================================================
    
    def get_product_total_stock(self, product: Dict[str, Any]) -> int:
        """
        Calcula el stock total de un producto (todas las variantes y UV).
        
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
    
    def get_product_available_stock(self, product: Dict[str, Any]) -> int:
        """
        Calcula el stock disponible (total - reservado).
        
        Args:
            product: Datos del producto
            
        Returns:
            Stock disponible
        """
        available = 0
        for variant in product.get('variants', []):
            for unit in variant.get('units', []):
                stock = unit.get('stock', 0)
                reserved = unit.get('reserved', 0)
                available += max(0, stock - reserved)
        return available
    
    def get_variant_uv_available(
        self, 
        product: Dict[str, Any], 
        variant_id: str, 
        uv: str
    ) -> int:
        """
        Obtiene el stock disponible de una UV específica.
        
        Args:
            product: Datos del producto
            variant_id: ID de la variante
            uv: Unidad de venta
            
        Returns:
            Stock disponible
        """
        variant = self.get_variant(product, variant_id)
        if not variant:
            return 0
        
        uv_entry = self.get_variant_uv(variant, uv)
        if not uv_entry:
            return 0
        
        stock = uv_entry.get('stock', 0)
        reserved = uv_entry.get('reserved', 0)
        return max(0, stock - reserved)
    
    def update_variant_uv_stock(
        self, 
        pid: int,
        variant_id: str,
        uv: str,
        delta: int,
        field: str = 'stock',
        user: str = None
    ) -> bool:
        """
        Actualiza el stock de una UV específica.
        
        Args:
            pid: ID del producto
            variant_id: ID de la variante
            uv: Unidad de venta
            delta: Cambio en cantidad (positivo o negativo)
            field: Campo a actualizar ('stock' o 'reserved')
            user: Usuario (para auditoría)
            
        Returns:
            True si se actualizó
        """
        success = self.inventory_repo.update_variant_stock(
            pid, variant_id, uv, delta, field
        )
        
        # Auditar cambios de stock
        if success and self.audit_service and user and field == 'stock':
            product = self.get_product(pid)
            if product:
                if delta > 0:
                    self.audit_service.log_stock_add(
                        user, pid, product.get('sku', ''),
                        product.get('nombre', ''),
                        delta, variant_id, uv
                    )
                else:
                    self.audit_service.log_stock_remove(
                        user, pid, product.get('sku', ''),
                        product.get('nombre', ''),
                        abs(delta), variant_id, uv
                    )
        
        return success
    
    def reserve_stock(
        self, 
        pid: int, 
        variant_id: str, 
        uv: str, 
        quantity: int
    ) -> bool:
        """
        Reserva stock para una venta pendiente.
        
        Args:
            pid: ID del producto
            variant_id: ID de la variante
            uv: Unidad de venta
            quantity: Cantidad a reservar
            
        Returns:
            True si se reservó exitosamente
        """
        product = self.get_product(pid)
        if not product:
            return False
        
        # Verificar disponibilidad
        available = self.get_variant_uv_available(product, variant_id, uv)
        if quantity > available:
            return False
        
        return self.update_variant_uv_stock(
            pid, variant_id, uv, quantity, 'reserved'
        )
    
    def release_reserved_stock(
        self, 
        pid: int, 
        variant_id: str, 
        uv: str, 
        quantity: int
    ) -> bool:
        """
        Libera stock reservado (por anulación o completación).
        
        Args:
            pid: ID del producto
            variant_id: ID de la variante
            uv: Unidad de venta
            quantity: Cantidad a liberar
            
        Returns:
            True si se liberó exitosamente
        """
        return self.update_variant_uv_stock(
            pid, variant_id, uv, -quantity, 'reserved'
        )
    
    def commit_reserved_stock(
        self, 
        pid: int, 
        variant_id: str, 
        uv: str, 
        quantity: int
    ) -> bool:
        """
        Confirma el stock reservado (descuenta del stock real).
        Se usa cuando una venta pasa a CANCELADO (pagada).
        
        Args:
            pid: ID del producto
            variant_id: ID de la variante
            uv: Unidad de venta
            quantity: Cantidad a confirmar
            
        Returns:
            True si se confirmó exitosamente
        """
        # Liberar la reserva
        if not self.release_reserved_stock(pid, variant_id, uv, quantity):
            return False
        
        # Descontar del stock real
        return self.update_variant_uv_stock(
            pid, variant_id, uv, -quantity, 'stock'
        )
    
    # =========================================================================
    # OBTENCIÓN DE PRECIOS
    # =========================================================================
    
    def get_variant_uv_price(
        self, 
        product: Dict[str, Any], 
        variant_id: str, 
        uv: str
    ) -> float:
        """
        Obtiene el precio de una UV específica.
        Hereda del producto si no está definido en la UV.
        
        Args:
            product: Datos del producto
            variant_id: ID de la variante
            uv: Unidad de venta
            
        Returns:
            Precio de venta
        """
        variant = self.get_variant(product, variant_id)
        if not variant:
            return product.get('price', 0.0)
        
        uv_entry = self.get_variant_uv(variant, uv)
        if not uv_entry:
            return product.get('price', 0.0)
        
        price = uv_entry.get('price')
        if price is not None:
            return price
        
        return product.get('price', 0.0)
    
    def get_variant_uv_cost(
        self, 
        product: Dict[str, Any], 
        variant_id: str, 
        uv: str
    ) -> float:
        """
        Obtiene el costo de una UV específica.
        Hereda del producto si no está definido en la UV.
        
        Args:
            product: Datos del producto
            variant_id: ID de la variante
            uv: Unidad de venta
            
        Returns:
            Costo de compra
        """
        variant = self.get_variant(product, variant_id)
        if not variant:
            return product.get('cost', 0.0)
        
        uv_entry = self.get_variant_uv(variant, uv)
        if not uv_entry:
            return product.get('cost', 0.0)
        
        cost = uv_entry.get('cost')
        if cost is not None:
            return cost
        
        return product.get('cost', 0.0)
    
    # =========================================================================
    # UTILIDADES
    # =========================================================================
    
    def get_low_stock_products(self) -> List[Dict[str, Any]]:
        """
        Obtiene productos con stock bajo o agotado.
        
        Returns:
            Lista de productos bajo stock mínimo
        """
        return self.inventory_repo.get_low_stock_products()
    
    def search_by_name(self, query: str) -> List[Dict[str, Any]]:
        """
        Busca productos por nombre.
        
        Args:
            query: Texto a buscar
            
        Returns:
            Lista de productos que coinciden
        """
        return self.inventory_repo.search_by_name(query)
    
    def search_by_sku(self, sku: str) -> Optional[Dict[str, Any]]:
        """
        Busca un producto por SKU exacto.
        
        Args:
            sku: SKU a buscar
            
        Returns:
            Producto encontrado o None
        """
        return self.inventory_repo.search_by_sku(sku)
    
    def format_variant_name(
        self, 
        product_name: str, 
        attributes: Dict[str, str]
    ) -> str:
        """
        Formatea nombre de variante para visualización.
        
        Args:
            product_name: Nombre del producto base
            attributes: Atributos de la variante
            
        Returns:
            Nombre formateado
        """
        if not attributes:
            return product_name
        
        attrs_str = ", ".join([f"{v}" for k, v in attributes.items() if v])
        if attrs_str:
            return f"{product_name} ({attrs_str})"
        return product_name
