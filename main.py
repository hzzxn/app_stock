from flask import Flask, render_template, request, redirect, url_for, session, flash
from functools import wraps
import os, json
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("STOCK_SECRET_KEY") or os.urandom(24).hex()
app.config['SESSION_COOKIE_HTTPONLY'] = True

# users (hashed)
_raw_users = {"admin": ("1234", "admin"), "operador": ("1234", "operador")}
USERS = {u: {"password": generate_password_hash(pw), "role": r} for u,(pw,r) in _raw_users.items()}

# inventory persistence
BASE = os.path.dirname(__file__)
INV_FILE = os.path.join(BASE, "inventory.json")
INV_DEFAULT = {1: {"nombre":"Cable USB","cantidad":10,"tipo":"Unidades","imagen":"default.png","stock_min":3}}

def load_inventory():
    if os.path.exists(INV_FILE):
        try:
            with open(INV_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {int(k): v for k,v in data.items()}
        except Exception:
            return INV_DEFAULT.copy()
    else:
        save_inventory(INV_DEFAULT)
        return INV_DEFAULT.copy()

def save_inventory(inv):
    serial = {str(k): v for k,v in inv.items()}
    with open(INV_FILE, "w", encoding="utf-8") as f:
        json.dump(serial, f, ensure_ascii=False, indent=2)

INVENTARIO = load_inventory()

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            flash("Debes iniciar sesión.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

@app.route("/", methods=["GET","POST"])
def login():
    if request.method=="POST":
        user = (request.form.get("user") or "").strip()
        pwd = request.form.get("password") or ""
        if user in USERS and check_password_hash(USERS[user]["password"], pwd):
            session["user"] = user
            session["role"] = USERS[user]["role"]
            flash(f"Bienvenido, {user}.", "success")
            return redirect(url_for("dashboard"))
        flash("Usuario o contraseña incorrecta.", "danger")
        return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    session.clear()
    flash("Sesión cerrada.", "info")
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", inventario=INVENTARIO, role=session.get("role",""))

def to_int(v):
    try: return int(v)
    except: return None

@app.route("/add", methods=["POST"])
@login_required
def add_stock():
    pid = to_int(request.form.get("id"))
    cantidad = to_int(request.form.get("cantidad"))
    if pid is None or cantidad is None:
        flash("ID o cantidad inválida.", "warning"); return redirect(url_for("dashboard"))
    if pid not in INVENTARIO:
        flash("Producto no encontrado.", "danger"); return redirect(url_for("dashboard"))
    if cantidad <= 0:
        flash("La cantidad debe ser mayor que 0.", "warning"); return redirect(url_for("dashboard"))
    INVENTARIO[pid]["cantidad"] = INVENTARIO[pid].get("cantidad",0) + cantidad
    save_inventory(INVENTARIO)
    flash(f"Se añadieron {cantidad} a {INVENTARIO[pid]['nombre']}.", "success")
    return redirect(url_for("dashboard"))

@app.route("/remove", methods=["POST"])
@login_required
def remove_stock():
    pid = to_int(request.form.get("id"))
    cantidad = to_int(request.form.get("cantidad"))
    if pid is None or cantidad is None:
        flash("ID o cantidad inválida.", "warning"); return redirect(url_for("dashboard"))
    if pid not in INVENTARIO:
        flash("Producto no encontrado.", "danger"); return redirect(url_for("dashboard"))
    current = INVENTARIO[pid].get("cantidad",0)
    if cantidad <= 0:
        flash("La cantidad debe ser mayor que 0.", "warning"); return redirect(url_for("dashboard"))
    if current < cantidad:
        flash("Stock insuficiente.", "warning"); return redirect(url_for("dashboard"))
    INVENTARIO[pid]["cantidad"] = current - cantidad
    save_inventory(INVENTARIO)
    flash(f"Se retiraron {cantidad} de {INVENTARIO[pid]['nombre']}.", "success")
    return redirect(url_for("dashboard"))

if __name__ == "__main__":
    app.run(debug=True)
