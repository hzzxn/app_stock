# ==============================================================================
# ENTIDADES DEL DOMINIO - Definiciones de dataclasses
# ==============================================================================
# Cada entidad representa un concepto del negocio.
# Diseñadas para ser independientes del mecanismo de persistencia.
# ==============================================================================

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum
from datetime import datetime


# ==============================================================================
# ENUMERACIONES - Estados y tipos válidos
# ==============================================================================

class UserRole(str, Enum):
    """Roles de usuario disponibles en el sistema."""
    ADMIN = "admin"
    OPERADOR = "operador"
    CHINA_IMPORT = "China Import"  # Superadmin


class SaleStatus(str, Enum):
    """Estados posibles de una venta."""
    CANCELADO = "CANCELADO"      # Venta completada y pagada
    POR_PAGAR = "POR PAGAR"      # Pendiente de pago
    PARA_RECOJO = "PARA RECOJO"  # Pagada, esperando recojo
    PARA_ENVIO = "PARA ENVÍO"    # Pagada, esperando envío
    COMPLETADA = "COMPLETADA"    # Entregada al cliente
    ANULADO = "ANULADO"          # Venta cancelada/anulada


class DeliveryType(str, Enum):
    """Tipos de entrega disponibles."""
    RECOJO = "RECOJO"      # Cliente recoge en tienda
    DELIVERY = "DELIVERY"   # Envío local
    PROVINCIA = "PROVINCIA" # Envío a provincia


class PaymentMethod(str, Enum):
    """Métodos de pago aceptados."""
    EFECTIVO = "EFECTIVO"
    YAPE = "YAPE"
    PLIN = "PLIN"
    TRANSFERENCIA = "TRANSFERENCIA"
    TARJETA = "TARJETA"
    OTRO = "OTRO"


class AuditType(str, Enum):
    """Tipos de eventos de auditoría."""
    VENTA = "VENTA"
    PAGO = "PAGO"
    STOCK = "STOCK"
    PRODUCTO = "PRODUCTO"
    SISTEMA = "SISTEMA"


# Lista de UVs válidas (Unidades de Venta)
VALID_UVS = frozenset(['UNIDAD', 'PAR', 'DOCENA', 'CAJA', 'BOLSA', 'OTRA'])


# ==============================================================================
# ENTIDADES DE USUARIO
# ==============================================================================

@dataclass
class User:
    """
    Representa un usuario del sistema.
    
    Attributes:
        username: Identificador único del usuario
        password_hash: Hash de la contraseña (nunca almacenar en texto plano)
        role: Rol del usuario que define sus permisos
    """
    username: str
    password_hash: str
    role: UserRole = UserRole.OPERADOR
    
    def is_admin(self) -> bool:
        """Verifica si el usuario tiene permisos de administrador."""
        return self.role in (UserRole.ADMIN, UserRole.CHINA_IMPORT)
    
    def can_manage_products(self) -> bool:
        """Verifica si puede crear/editar/eliminar productos."""
        return self.role == UserRole.ADMIN
    
    def can_view_audit(self) -> bool:
        """Verifica si puede ver el registro de auditoría."""
        return self.role == UserRole.ADMIN
    
    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario para persistencia."""
        return {
            'password': self.password_hash,
            'role': self.role.value if isinstance(self.role, Enum) else self.role
        }
    
    @classmethod
    def from_dict(cls, username: str, data: Dict[str, Any]) -> 'User':
        """Crea instancia desde diccionario."""
        role_str = data.get('role', 'operador')
        try:
            role = UserRole(role_str)
        except ValueError:
            role = UserRole.OPERADOR
        return cls(
            username=username,
            password_hash=data.get('password', ''),
            role=role
        )


# ==============================================================================
# ENTIDADES DE INVENTARIO
# ==============================================================================

@dataclass
class VariantUnit:
    """
    Unidad de venta dentro de una variante.
    Permite manejar múltiples unidades de venta por variante (UNIDAD, PAR, DOCENA, etc.)
    
    Attributes:
        uv: Tipo de unidad de venta
        stock: Cantidad en inventario
        reserved: Cantidad reservada para ventas pendientes
        price: Precio de venta (opcional, hereda del producto)
        cost: Costo de compra (opcional, hereda del producto)
        label: Etiqueta personalizada para UV=OTRA
    """
    uv: str = 'UNIDAD'
    stock: int = 0
    reserved: int = 0
    price: Optional[float] = None
    cost: Optional[float] = None
    label: Optional[str] = None
    
    @property
    def available(self) -> int:
        """Stock disponible para venta (total - reservado)."""
        return max(0, self.stock - self.reserved)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario para persistencia."""
        d = {
            'uv': self.uv,
            'stock': self.stock,
            'reserved': self.reserved,
        }
        if self.price is not None:
            d['price'] = self.price
        if self.cost is not None:
            d['cost'] = self.cost
        if self.label is not None:
            d['label'] = self.label
        return d
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VariantUnit':
        """Crea instancia desde diccionario."""
        return cls(
            uv=data.get('uv', 'UNIDAD'),
            stock=data.get('stock', 0),
            reserved=data.get('reserved', 0),
            price=data.get('price'),
            cost=data.get('cost'),
            label=data.get('label')
        )


@dataclass
class ProductVariant:
    """
    Variante de un producto (ej: talla, color).
    Cada variante puede tener múltiples unidades de venta.
    
    Attributes:
        variant_id: Identificador único de la variante
        attributes: Atributos de la variante (color, talla, etc.)
        units: Lista de unidades de venta disponibles
    """
    variant_id: str
    attributes: Dict[str, str] = field(default_factory=dict)
    units: List[VariantUnit] = field(default_factory=list)
    
    @property
    def total_stock(self) -> int:
        """Stock total de todas las UV de esta variante."""
        return sum(u.stock for u in self.units)
    
    @property
    def available_stock(self) -> int:
        """Stock disponible de todas las UV de esta variante."""
        return sum(u.available for u in self.units)
    
    def get_unit(self, uv: str) -> Optional[VariantUnit]:
        """Busca una unidad de venta específica."""
        for unit in self.units:
            if unit.uv == uv:
                return unit
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario para persistencia."""
        return {
            'variant_id': self.variant_id,
            'attributes': self.attributes,
            'units': [u.to_dict() for u in self.units]
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProductVariant':
        """Crea instancia desde diccionario."""
        units = [VariantUnit.from_dict(u) for u in data.get('units', [])]
        return cls(
            variant_id=data.get('variant_id', ''),
            attributes=data.get('attributes', {}),
            units=units
        )


@dataclass
class Product:
    """
    Producto del inventario.
    Es un contenedor lógico - el stock real está en las variantes.
    
    Attributes:
        id: Identificador único del producto
        sku: Código SKU para identificación
        nombre: Nombre del producto
        categoria: Categoría para clasificación
        imagen: Nombre del archivo de imagen
        stock_min: Stock mínimo antes de alerta
        price: Precio base (heredado por variantes)
        cost: Costo base (heredado por variantes)
        color: Color del producto (legacy)
        tipo: Tipo de producto
        unidad: Unidad de medida
        variants: Lista de variantes del producto
    """
    id: int
    sku: str
    nombre: str
    categoria: str = ''
    imagen: str = 'default.png'
    stock_min: int = 0
    price: float = 0.0
    cost: float = 0.0
    color: str = ''
    tipo: str = 'Unidades'
    unidad: str = 'Unidades'
    variants: List[ProductVariant] = field(default_factory=list)
    
    @property
    def total_stock(self) -> int:
        """Stock total de todas las variantes."""
        return sum(v.total_stock for v in self.variants)
    
    @property
    def available_stock(self) -> int:
        """Stock disponible de todas las variantes."""
        return sum(v.available_stock for v in self.variants)
    
    @property
    def is_low_stock(self) -> bool:
        """Verifica si el stock está por debajo del mínimo."""
        return self.total_stock <= self.stock_min
    
    def get_variant(self, variant_id: str) -> Optional[ProductVariant]:
        """Busca una variante por su ID."""
        for v in self.variants:
            if v.variant_id == variant_id:
                return v
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario para persistencia JSON."""
        return {
            'sku': self.sku,
            'nombre': self.nombre,
            'cantidad': self.total_stock,  # Compatibilidad legacy
            'cost': self.cost,
            'price': self.price,
            'tipo': self.tipo,
            'imagen': self.imagen,
            'stock_min': self.stock_min,
            'color': self.color,
            'categoria': self.categoria,
            'unidad': self.unidad,
            'variants': [v.to_dict() for v in self.variants],
            'has_variants': True
        }
    
    @classmethod
    def from_dict(cls, pid: int, data: Dict[str, Any]) -> 'Product':
        """Crea instancia desde diccionario (formato JSON actual)."""
        variants = [ProductVariant.from_dict(v) for v in data.get('variants', [])]
        return cls(
            id=pid,
            sku=data.get('sku', ''),
            nombre=data.get('nombre', ''),
            categoria=data.get('categoria', ''),
            imagen=data.get('imagen', 'default.png'),
            stock_min=data.get('stock_min', 0),
            price=data.get('price', 0.0),
            cost=data.get('cost', 0.0),
            color=data.get('color', ''),
            tipo=data.get('tipo', 'Unidades'),
            unidad=data.get('unidad', 'Unidades'),
            variants=variants
        )


# ==============================================================================
# ENTIDADES DE VENTA
# ==============================================================================

@dataclass
class SaleItem:
    """
    Ítem individual dentro de una venta.
    
    Attributes:
        pid: ID del producto
        sku: SKU del producto
        nombre: Nombre del producto
        qty: Cantidad vendida
        unit_price: Precio unitario de venta
        unit_cost: Costo unitario
        line_total: Total de la línea (qty * unit_price)
        line_profit: Ganancia de la línea
        variant_id: ID de la variante vendida
        variant_attributes: Atributos de la variante
        uv: Unidad de venta
        uv_label: Etiqueta de UV personalizada
    """
    pid: int
    sku: str
    nombre: str
    qty: int
    unit_price: float
    unit_cost: float = 0.0
    line_total: float = 0.0
    line_profit: float = 0.0
    variant_id: Optional[str] = None
    variant_attributes: Dict[str, str] = field(default_factory=dict)
    uv: str = 'UNIDAD'
    uv_label: Optional[str] = None
    
    def __post_init__(self):
        """Calcula totales si no fueron proporcionados."""
        if self.line_total == 0.0:
            self.line_total = round(self.qty * self.unit_price, 2)
        if self.line_profit == 0.0:
            self.line_profit = round((self.unit_price - self.unit_cost) * self.qty, 2)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario para persistencia."""
        return {
            'pid': self.pid,
            'sku': self.sku,
            'nombre': self.nombre,
            'qty': self.qty,
            'unit_price': self.unit_price,
            'unit_cost': self.unit_cost,
            'line_total': self.line_total,
            'line_profit': self.line_profit,
            'variant_id': self.variant_id,
            'variant_attributes': self.variant_attributes,
            'uv': self.uv,
            'uv_label': self.uv_label
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SaleItem':
        """Crea instancia desde diccionario."""
        return cls(
            pid=data.get('pid', 0),
            sku=data.get('sku', ''),
            nombre=data.get('nombre', ''),
            qty=data.get('qty', 0),
            unit_price=data.get('unit_price', 0.0),
            unit_cost=data.get('unit_cost', 0.0),
            line_total=data.get('line_total', 0.0),
            line_profit=data.get('line_profit', 0.0),
            variant_id=data.get('variant_id'),
            variant_attributes=data.get('variant_attributes', {}),
            uv=data.get('uv', 'UNIDAD'),
            uv_label=data.get('uv_label')
        )


@dataclass
class Payment:
    """
    Registro de un pago.
    
    Attributes:
        amount: Monto pagado
        method: Método de pago
        ts: Timestamp del pago
        user: Usuario que registró el pago
    """
    amount: float
    method: str = 'EFECTIVO'
    ts: str = ''
    user: str = ''
    
    def __post_init__(self):
        if not self.ts:
            self.ts = datetime.utcnow().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario para persistencia."""
        return {
            'amount': round(self.amount, 2),
            'method': self.method,
            'ts': self.ts,
            'user': self.user
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Payment':
        """Crea instancia desde diccionario."""
        return cls(
            amount=data.get('amount', 0.0),
            method=data.get('method', 'EFECTIVO'),
            ts=data.get('ts', ''),
            user=data.get('user', '')
        )


@dataclass
class Delivery:
    """
    Información de entrega de una venta.
    
    Attributes:
        type: Tipo de entrega (RECOJO, DELIVERY, PROVINCIA)
        address: Dirección de entrega
        district: Distrito
        province: Provincia (para envíos)
        reference: Referencia de ubicación
        phone: Teléfono de contacto
        shipping_cost: Costo de envío
        notes: Notas adicionales
    """
    type: str = 'RECOJO'
    address: str = ''
    district: str = ''
    province: str = ''
    reference: str = ''
    phone: str = ''
    shipping_cost: float = 0.0
    notes: str = ''
    
    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario para persistencia."""
        return {
            'type': self.type,
            'address': self.address,
            'district': self.district,
            'province': self.province,
            'reference': self.reference,
            'phone': self.phone,
            'shipping_cost': self.shipping_cost,
            'notes': self.notes
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Delivery':
        """Crea instancia desde diccionario."""
        return cls(
            type=data.get('type', 'RECOJO'),
            address=data.get('address', ''),
            district=data.get('district', ''),
            province=data.get('province', ''),
            reference=data.get('reference', ''),
            phone=data.get('phone', ''),
            shipping_cost=data.get('shipping_cost', 0.0),
            notes=data.get('notes', '')
        )


@dataclass
class Sale:
    """
    Representa una venta completa.
    
    Attributes:
        receipt: Número de boleta/recibo (identificador único)
        user: Usuario que realizó la venta
        ts: Timestamp de creación
        status: Estado actual de la venta
        items: Lista de ítems vendidos
        total: Total de la venta
        profit_total: Ganancia total
        paid_amount: Monto pagado
        pending_amount: Monto pendiente
        payments: Lista de pagos registrados
        delivery: Información de entrega
        client_name: Nombre del cliente
        client_doc: Documento del cliente (DNI/RUC)
        client_obs: Observaciones del cliente
    """
    receipt: str
    user: str
    ts: str = ''
    status: str = 'POR PAGAR'
    items: List[SaleItem] = field(default_factory=list)
    total: float = 0.0
    profit_total: float = 0.0
    paid_amount: float = 0.0
    pending_amount: float = 0.0
    payments: List[Payment] = field(default_factory=list)
    delivery: Optional[Delivery] = None
    client_name: str = ''
    client_doc: str = ''
    client_obs: str = ''
    completion_ts: Optional[str] = None
    completed_by: Optional[str] = None
    pending_reason: Optional[str] = None
    annul_reason: Optional[str] = None
    
    def __post_init__(self):
        if not self.ts:
            self.ts = datetime.utcnow().isoformat()
    
    @property
    def is_paid(self) -> bool:
        """Verifica si la venta está completamente pagada."""
        return self.pending_amount <= 0
    
    @property
    def is_completed(self) -> bool:
        """Verifica si la venta fue entregada al cliente."""
        return self.status == 'COMPLETADA'
    
    @property
    def is_annulled(self) -> bool:
        """Verifica si la venta fue anulada."""
        return self.status == 'ANULADO'
    
    def calculate_totals(self):
        """Recalcula totales basándose en ítems y pagos."""
        self.total = round(sum(item.line_total for item in self.items), 2)
        self.profit_total = round(sum(item.line_profit for item in self.items), 2)
        self.paid_amount = round(sum(p.amount for p in self.payments), 2)
        self.pending_amount = round(max(0, self.total - self.paid_amount), 2)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario para persistencia JSON."""
        d = {
            'receipt': self.receipt,
            'user': self.user,
            'ts': self.ts,
            'status': self.status,
            'items': [item.to_dict() for item in self.items],
            'total': self.total,
            'profit_total': self.profit_total,
            'paid_amount': self.paid_amount,
            'pending_amount': self.pending_amount,
            'payments': [p.to_dict() for p in self.payments],
            'client_name': self.client_name,
            'client_doc': self.client_doc,
            'client_obs': self.client_obs,
        }
        if self.delivery:
            d['delivery'] = self.delivery.to_dict()
        if self.completion_ts:
            d['completion_ts'] = self.completion_ts
        if self.completed_by:
            d['completed_by'] = self.completed_by
        if self.pending_reason:
            d['pending_reason'] = self.pending_reason
        if self.annul_reason:
            d['annul_reason'] = self.annul_reason
        return d
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Sale':
        """Crea instancia desde diccionario (formato JSON actual)."""
        items = [SaleItem.from_dict(i) for i in data.get('items', [])]
        payments = [Payment.from_dict(p) for p in data.get('payments', [])]
        delivery = None
        if data.get('delivery'):
            delivery = Delivery.from_dict(data['delivery'])
        
        return cls(
            receipt=data.get('receipt', ''),
            user=data.get('user', ''),
            ts=data.get('ts', ''),
            status=data.get('status', 'POR PAGAR'),
            items=items,
            total=data.get('total', 0.0),
            profit_total=data.get('profit_total', 0.0),
            paid_amount=data.get('paid_amount', 0.0),
            pending_amount=data.get('pending_amount', 0.0),
            payments=payments,
            delivery=delivery,
            client_name=data.get('client_name', ''),
            client_doc=data.get('client_doc', ''),
            client_obs=data.get('client_obs', ''),
            completion_ts=data.get('completion_ts'),
            completed_by=data.get('completed_by'),
            pending_reason=data.get('pending_reason'),
            annul_reason=data.get('annul_reason')
        )


# ==============================================================================
# ENTIDADES DE CARRITO
# ==============================================================================

@dataclass
class CartItem:
    """
    Ítem en el carrito de compras (session-based).
    
    Attributes:
        producto_id: ID del producto
        sku: SKU del producto
        nombre: Nombre del producto
        cantidad: Cantidad en carrito
        precio_unitario: Precio unitario
        variant_id: ID de variante seleccionada
        variant_attributes: Atributos de la variante
        uv: Unidad de venta
        uv_label: Etiqueta UV personalizada
    """
    producto_id: int
    sku: str
    nombre: str
    cantidad: int
    precio_unitario: float
    variant_id: str = ''
    variant_attributes: Dict[str, str] = field(default_factory=dict)
    uv: str = 'UNIDAD'
    uv_label: Optional[str] = None
    
    @property
    def subtotal(self) -> float:
        """Subtotal de este ítem."""
        return round(self.cantidad * self.precio_unitario, 2)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario para session."""
        return {
            'producto_id': self.producto_id,
            'sku': self.sku,
            'nombre': self.nombre,
            'cantidad': self.cantidad,
            'precio_unitario': self.precio_unitario,
            'variant_id': self.variant_id,
            'variant_attributes': self.variant_attributes,
            'uv': self.uv,
            'uv_label': self.uv_label
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CartItem':
        """Crea instancia desde diccionario de session."""
        return cls(
            producto_id=data.get('producto_id', 0),
            sku=data.get('sku', ''),
            nombre=data.get('nombre', ''),
            cantidad=data.get('cantidad', 0),
            precio_unitario=data.get('precio_unitario', 0.0),
            variant_id=data.get('variant_id', ''),
            variant_attributes=data.get('variant_attributes', {}),
            uv=data.get('uv', 'UNIDAD'),
            uv_label=data.get('uv_label')
        )


# ==============================================================================
# ENTIDADES DE AUDITORÍA
# ==============================================================================

@dataclass
class AuditLog:
    """
    Registro de auditoría.
    
    Attributes:
        type: Tipo de evento (VENTA, PAGO, STOCK, etc.)
        user: Usuario que realizó la acción
        message: Mensaje descriptivo humanizado
        timestamp: Fecha y hora del evento
        related_id: ID relacionado (receipt, SKU, etc.)
        details: Detalles adicionales
    """
    type: str
    user: str
    message: str
    timestamp: str = ''
    related_id: str = ''
    details: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convierte a diccionario para persistencia."""
        return {
            'type': self.type,
            'user': self.user,
            'message': self.message,
            'timestamp': self.timestamp,
            'related_id': self.related_id,
            'details': self.details
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AuditLog':
        """Crea instancia desde diccionario."""
        return cls(
            type=data.get('type', data.get('action', '')),
            user=data.get('user', ''),
            message=data.get('message', ''),
            timestamp=data.get('timestamp', data.get('ts', '')),
            related_id=data.get('related_id', data.get('sku', '')),
            details=data.get('details', {})
        )
