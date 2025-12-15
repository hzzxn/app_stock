from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, Response
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os, json, uuid, io, csv, datetime

app = Flask(__name__)
BASE = os.path.dirname(__file__)
app.secret_key = os.environ.get("STOCK_SECRET_KEY") or os.urandom(24).hex()
app.config['SESSION_COOKIE_HTTPONLY'] = True

# Upload / limits
UPLOAD_DIR = os.path.join(BASE, "static", "productos")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB

# Users (hashed) - ahora persistentes en users.json
_raw_users = {"admin": ("1234", "admin"), "operador": ("1234", "operador")}
USERS_FILE = os.path.join(BASE, "users.json")

def save_users(users):
    # Guardar usuarios (incluye password hashed) en disco
    serial = {}
    for u, v in users.items():
        serial[u] = {"password": v.get("password"), "role": v.get("role", "")}
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(serial, f, ensure_ascii=False, indent=2)

def load_users():
    # Cargar desde users.json si existe; si no, crear con _raw_users + cuenta 'china'
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {u: {"password": v["password"], "role": v.get("role","")} for u,v in data.items()}
        except Exception:
            pass
    # build defaults
    users = {u: {"password": generate_password_hash(pw), "role": r} for u,(pw,r) in _raw_users.items()}
    # usuario especial
    users.setdefault("china", {"password": generate_password_hash("changeme"), "role": "China Import"})
    save_users(users)
    return users

USERS = load_users()

# Inventory & Audit persistence
INV_FILE = os.path.join(BASE, "inventory.json")
AUDIT_FILE = os.path.join(BASE, "audit.json")
INV_DEFAULT = {1: {"sku": "P0001", "nombre": "Cable USB", "cantidad": 10, "tipo": "Unidades", "imagen": "default.png", "stock_min": 3}}

def load_inventory():
    if os.path.exists(INV_FILE):
        try:
            with open(INV_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {int(k): v for k, v in data.items()}
        except Exception:
            return INV_DEFAULT.copy()
    else:
        save_inventory(INV_DEFAULT)
        return INV_DEFAULT.copy()

def save_inventory(inv):
    serial = {str(k): v for k, v in inv.items()}
    with open(INV_FILE, "w", encoding="utf-8") as f:
        json.dump(serial, f, ensure_ascii=False, indent=2)

def load_audit():
    if os.path.exists(AUDIT_FILE):
        try:
            with open(AUDIT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_audit(logs):
    with open(AUDIT_FILE, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)

def log_audit(action, user, pid=None, sku=None, details=None):
    logs = load_audit()
    entry = {
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "user": user or session.get("user"),
        "action": action,
        "pid": pid,
        "sku": sku,
        "details": details
    }
    logs.insert(0, entry)  # newest first
    save_audit(logs)

INVENTARIO = load_inventory()

# Helpers
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def to_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default

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

# Routes: login/logout
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = (request.form.get("user") or "").strip()
        password = request.form.get("password") or ""
        if not user or not password:
            flash("Usuario y contraseña requeridos.", "warning")
            return redirect(url_for("login"))
        user_rec = USERS.get(user)
        if user_rec and check_password_hash(user_rec["password"], password):
            session["user"] = user
            session["role"] = user_rec["role"]
            flash(f"Bienvenido, {user}.", "success")
            log_audit("login", user, details="Inicio de sesión")
            return redirect(url_for("dashboard"))
        flash("Usuario o contraseña incorrecta.", "danger")
        return redirect(url_for("login"))
    return render_template("login.html")

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
    # estadísticas para el control-panel
    total_products = len(INVENTARIO)
    low_stock = sum(1 for p in INVENTARIO.values() if p.get("cantidad", 0) <= p.get("stock_min", 0))
    total_items = sum(p.get("cantidad", 0) for p in INVENTARIO.values())
    return render_template("dashboard.html",
                           inventario=INVENTARIO,
                           role=session.get("role", ""),
                           total_products=total_products,
                           low_stock=low_stock,
                           total_items=total_items)

# Add / Remove stock (with audit)
@app.route("/add", methods=["POST"])
@login_required
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

# Create product (admin) with upload + validation + audit
@app.route("/products/new", methods=["POST"])
@login_required
@role_required("admin")
def create_product():
    nombre = (request.form.get("nombre") or "").strip()
    cantidad = to_int(request.form.get("cantidad")) or 0
    tipo = (request.form.get("tipo") or "Unidades").strip()
    stock_min = to_int(request.form.get("stock_min")) or 0
    color = (request.form.get("color") or "").strip()
    categoria = (request.form.get("categoria") or "").strip()
    unidad = (request.form.get("unidad") or "").strip()

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
    INVENTARIO[pid] = {
        "sku": sku,
        "nombre": nombre,
        "cantidad": max(0, cantidad),
        "tipo": tipo or "Unidades",
        "imagen": imagen_name,
        "stock_min": max(0, stock_min),
        "color": color,
        "categoria": categoria,
        "unidad": unidad
    }
    save_inventory(INVENTARIO)
    flash(f"Producto '{nombre}' creado (SKU {sku}).", "success")
    log_audit("create_product", session.get("user"), pid=pid, sku=sku, details={"nombre": nombre, "cantidad": cantidad})
    return redirect(url_for("dashboard"))

# Edit & Delete endpoints (minimal, with audit)
@app.route("/products/edit/<int:pid>", methods=["POST"])
@login_required
@role_required("admin")
def edit_product(pid):
    if pid not in INVENTARIO:
        flash("Producto no encontrado.", "danger")
        return redirect(url_for("dashboard"))
    before = INVENTARIO[pid].copy()
    nombre = (request.form.get("nombre") or before.get("nombre")).strip()
    cantidad = to_int(request.form.get("cantidad"), before.get("cantidad", 0))
    tipo = (request.form.get("tipo") or before.get("tipo", "")).strip()
    stock_min = to_int(request.form.get("stock_min"), before.get("stock_min", 0))
    color = (request.form.get("color") or before.get("color", "")).strip()
    categoria = (request.form.get("categoria") or before.get("categoria", "")).strip()
    unidad = (request.form.get("unidad") or before.get("unidad", "")).strip()

    INVENTARIO[pid].update({
        "nombre": nombre,
        "cantidad": max(0, cantidad),
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
    # simple server-side filtering by query params
    q_action = request.args.get("action")
    q_user = request.args.get("user")
    q_sku = request.args.get("sku")
    q_from = request.args.get("from")
    q_to = request.args.get("to")

    def in_range(ts_iso):
        if not (q_from or q_to):
            return True
        t = datetime.datetime.fromisoformat(ts_iso.replace("Z", ""))
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
        if q_action and e.get("action") != q_action: continue
        if q_user and e.get("user") != q_user: continue
        if q_sku and e.get("sku") != q_sku: continue
        if not in_range(e.get("ts", "")): continue
        filtered.append(e)

    # summary cards
    total_products = len(INVENTARIO)
    low_stock = sum(1 for p in INVENTARIO.values() if p.get("cantidad", 0) <= p.get("stock_min", 0))
    total_items = sum(p.get("cantidad", 0) for p in INVENTARIO.values())

    return render_template("audit.html", logs=filtered, total_products=total_products, low_stock=low_stock, total_items=total_items, query=request.args)

# Export audit CSV (same filters)
@app.route("/audit/export")
@login_required
@role_required("admin")
def audit_export():
    # reuse audit_page filtering logic: call /audit internal with args
    # Simple approach: filter same as audit_page code (duplicate small part)
    logs = load_audit()
    q_action = request.args.get("action")
    q_user = request.args.get("user")
    q_sku = request.args.get("sku")
    q_from = request.args.get("from")
    q_to = request.args.get("to")
    def in_range(ts_iso):
        if not (q_from or q_to):
            return True
        t = datetime.datetime.fromisoformat(ts_iso.replace("Z", ""))
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
        if q_action and e.get("action") != q_action: continue
        if q_user and e.get("user") != q_user: continue
        if q_sku and e.get("sku") != q_sku: continue
        if not in_range(e.get("ts", "")): continue
        filtered.append(e)

    # CSV
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(["ts","user","action","pid","sku","details"])
    for e in filtered:
        writer.writerow([e.get("ts"), e.get("user"), e.get("action"), e.get("pid"), e.get("sku"), json.dumps(e.get("details"), ensure_ascii=False)])
    output = si.getvalue()
    return Response(output, mimetype="text/csv", headers={"Content-Disposition":"attachment;filename=audit.csv"})

def count_admins():
    return sum(1 for u,v in USERS.items() if v.get("role") == "admin")

# ---- China Import panel & actions ----
@app.route("/china")
@login_required
@role_required("China Import")
def china_panel():
    # lista de usuarios (no incluye contraseñas en template)
    safe_users = {u: {"role": v["role"]} for u, v in USERS.items()}
    return render_template("china_panel.html", users=safe_users, me=session.get("user"))

@app.route("/china/role", methods=["POST"])
@login_required
@role_required("China Import")
def china_change_role():
    username = (request.form.get("username") or "").strip()
    newrole = (request.form.get("role") or "").strip()
    if not username or username not in USERS:
        flash("Usuario inválido.", "warning")
        return redirect(url_for("china_panel"))

    old = USERS[username].get("role")
    # protección: no dejar sin administradores al sistema
    if old == "admin" and newrole != "admin" and count_admins() <= 1:
        flash("No se puede quitar el último admin.", "warning")
        return redirect(url_for("china_panel"))

    USERS[username]["role"] = newrole or ""
    save_users(USERS)
    flash(f"Rol de {username} cambiado: {old} → {newrole}", "success")
    log_audit("change_role", session.get("user"), details={"user": username, "from": old, "to": newrole})
    return redirect(url_for("china_panel"))

@app.route("/china/delete_user", methods=["POST"])
@login_required
@role_required("China Import")
def china_delete_user():
    username = (request.form.get("username") or "").strip()
    if not username or username not in USERS:
        flash("Usuario inválido.", "warning")
        return redirect(url_for("china_panel"))
    data = USERS[username]
    # protección: no eliminar el último admin
    if data.get("role") == "admin" and count_admins() <= 1:
        flash("No se puede eliminar el último admin.", "warning")
        return redirect(url_for("china_panel"))
    # protección: no eliminar al propio usuario (evita auto-bloqueo)
    if username == session.get("user"):
        flash("No puedes eliminar tu propia cuenta desde aquí.", "warning")
        return redirect(url_for("china_panel"))
    log_audit("delete_user", session.get("user"), details={"user": username, "role": data.get("role")})
    flash(f"Usuario '{username}' eliminado.", "info")
    save_users(USERS)
    data = USERS.pop(username)
    return redirect(url_for("china_panel"))

if __name__ == "__main__":
    app.run(debug=True)