"""
Oriozen Healthcare — storefront backend
=======================================
Flask + SQLite. No external services required.

Run:
    pip install -r requirements.txt
    python server.py
Then open  http://localhost:5000        (storefront)
           http://localhost:5000/admin  (order dashboard)

Environment variables (all optional):
    ADMIN_KEY   admin dashboard key            (default: oriozen-admin)
    PORT        port to listen on              (default: 5000)
    DB_PATH     SQLite file location           (default: ./oriozen.db)
"""

import json
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone

from flask import Flask, g, jsonify, render_template, request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "oriozen.db"))
ADMIN_KEY = os.environ.get("ADMIN_KEY", "oriozen-admin")
SHIPPING_FLAT = 49          # ₹, charged below the free-shipping threshold
FREE_SHIPPING_ABOVE = 499   # ₹
VALID_STATUSES = ["new", "confirmed", "shipped", "delivered", "cancelled"]

app = Flask(__name__, template_folder="templates", static_folder="static")

# ── catalog ────────────────────────────────────────────────────────────────
with open(os.path.join(BASE_DIR, "data", "products.json"), encoding="utf-8") as f:
    PRODUCTS = json.load(f)
PRODUCT_INDEX = {p["id"]: p for p in PRODUCTS}


# ── database ───────────────────────────────────────────────────────────────
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """CREATE TABLE IF NOT EXISTS orders (
               id          TEXT PRIMARY KEY,
               created_at  TEXT NOT NULL,
               status      TEXT NOT NULL DEFAULT 'new',
               name        TEXT NOT NULL,
               phone       TEXT NOT NULL,
               email       TEXT,
               address     TEXT NOT NULL,
               city        TEXT NOT NULL,
               pincode     TEXT NOT NULL,
               payment     TEXT NOT NULL DEFAULT 'cod',
               items_json  TEXT NOT NULL,
               subtotal    INTEGER NOT NULL,
               shipping    INTEGER NOT NULL,
               total       INTEGER NOT NULL,
               notes       TEXT
           )"""
    )
    con.commit()
    con.close()


def new_order_id():
    """Human-friendly order id, e.g. OZ-260709-4F7K."""
    stamp = datetime.now().strftime("%y%m%d")
    suffix = secrets.token_hex(2).upper()
    return f"OZ-{stamp}-{suffix}"


# ── validation helpers ─────────────────────────────────────────────────────
PHONE_RE = re.compile(r"^[6-9]\d{9}$")       # Indian 10-digit mobile
PIN_RE = re.compile(r"^\d{6}$")              # Indian PIN code
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_order(payload):
    errors = []
    customer = payload.get("customer") or {}
    items = payload.get("items") or []

    name = str(customer.get("name", "")).strip()
    phone = re.sub(r"[^\d]", "", str(customer.get("phone", "")))[-10:]
    email = str(customer.get("email", "")).strip()
    address = str(customer.get("address", "")).strip()
    city = str(customer.get("city", "")).strip()
    pincode = str(customer.get("pincode", "")).strip()
    payment = str(payload.get("payment", "cod")).strip().lower()

    if len(name) < 2:
        errors.append("Please enter your full name.")
    if not PHONE_RE.match(phone):
        errors.append("Please enter a valid 10-digit mobile number.")
    if email and not EMAIL_RE.match(email):
        errors.append("The email address doesn't look right.")
    if len(address) < 8:
        errors.append("Please enter your complete delivery address.")
    if len(city) < 2:
        errors.append("Please enter your city.")
    if not PIN_RE.match(pincode):
        errors.append("Please enter a valid 6-digit PIN code.")
    if payment not in ("cod",):
        errors.append("Only Cash on Delivery is available right now.")

    clean_items = []
    for it in items:
        pid = str(it.get("id", ""))
        try:
            qty = int(it.get("qty", 0))
        except (TypeError, ValueError):
            qty = 0
        product = PRODUCT_INDEX.get(pid)
        if not product or qty < 1:
            continue
        qty = min(qty, 20)  # sane per-line cap
        clean_items.append({"id": pid, "name": product["name"],
                            "price": product["price"], "qty": qty})
    if not clean_items:
        errors.append("Your cart is empty.")

    return errors, {
        "name": name, "phone": phone, "email": email, "address": address,
        "city": city, "pincode": pincode, "payment": payment,
        "items": clean_items,
    }


def require_admin():
    key = request.headers.get("X-Admin-Key") or request.args.get("key", "")
    return secrets.compare_digest(key, ADMIN_KEY)


# ── pages ──────────────────────────────────────────────────────────────────
@app.get("/")
def home():
    return render_template("index.html")


@app.get("/admin")
def admin_page():
    return render_template("admin.html")


# ── public API ─────────────────────────────────────────────────────────────
@app.get("/api/products")
def api_products():
    return jsonify(PRODUCTS)


@app.get("/api/products/<pid>")
def api_product(pid):
    product = PRODUCT_INDEX.get(pid)
    if not product:
        return jsonify({"error": "Product not found"}), 404
    return jsonify(product)


@app.post("/api/orders")
def api_create_order():
    payload = request.get_json(silent=True) or {}
    errors, clean = validate_order(payload)
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400

    subtotal = sum(i["price"] * i["qty"] for i in clean["items"])
    shipping = 0 if subtotal >= FREE_SHIPPING_ABOVE else SHIPPING_FLAT
    total = subtotal + shipping

    order_id = new_order_id()
    db = get_db()
    # regenerate id on the (very unlikely) collision
    for _ in range(3):
        try:
            db.execute(
                """INSERT INTO orders
                   (id, created_at, status, name, phone, email, address, city,
                    pincode, payment, items_json, subtotal, shipping, total)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (order_id, datetime.now(timezone.utc).isoformat(), "new",
                 clean["name"], clean["phone"], clean["email"], clean["address"],
                 clean["city"], clean["pincode"], clean["payment"],
                 json.dumps(clean["items"], ensure_ascii=False),
                 subtotal, shipping, total),
            )
            db.commit()
            break
        except sqlite3.IntegrityError:
            order_id = new_order_id()
    else:
        return jsonify({"ok": False, "errors": ["Could not create order, try again."]}), 500

    return jsonify({
        "ok": True,
        "order": {"id": order_id, "subtotal": subtotal,
                  "shipping": shipping, "total": total,
                  "payment": clean["payment"], "status": "new"},
    }), 201


@app.get("/api/orders/<order_id>/track")
def api_track(order_id):
    """Customers can track an order with its id + the phone used at checkout."""
    phone = re.sub(r"[^\d]", "", request.args.get("phone", ""))[-10:]
    row = get_db().execute(
        "SELECT id, created_at, status, total, items_json FROM orders WHERE id=? AND phone=?",
        (order_id.strip().upper(), phone),
    ).fetchone()
    if not row:
        return jsonify({"ok": False, "error": "No order found for that ID and phone number."}), 404
    return jsonify({"ok": True, "order": {
        "id": row["id"], "created_at": row["created_at"], "status": row["status"],
        "total": row["total"], "items": json.loads(row["items_json"]),
    }})


# ── admin API ──────────────────────────────────────────────────────────────
@app.get("/api/admin/orders")
def api_admin_orders():
    if not require_admin():
        return jsonify({"error": "Invalid admin key"}), 401
    rows = get_db().execute(
        "SELECT * FROM orders ORDER BY created_at DESC LIMIT 500"
    ).fetchall()
    orders = []
    for r in rows:
        o = dict(r)
        o["items"] = json.loads(o.pop("items_json"))
        orders.append(o)
    delivered = [o for o in orders if o["status"] == "delivered"]
    summary = {
        "orders": len(orders),
        "pending": sum(1 for o in orders if o["status"] in ("new", "confirmed")),
        "revenue_delivered": sum(o["total"] for o in delivered),
        "revenue_all": sum(o["total"] for o in orders if o["status"] != "cancelled"),
    }
    return jsonify({"summary": summary, "orders": orders})


@app.patch("/api/admin/orders/<order_id>")
def api_admin_update(order_id):
    if not require_admin():
        return jsonify({"error": "Invalid admin key"}), 401
    payload = request.get_json(silent=True) or {}
    status = str(payload.get("status", "")).lower()
    if status not in VALID_STATUSES:
        return jsonify({"error": f"Status must be one of {VALID_STATUSES}"}), 400
    db = get_db()
    cur = db.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
    db.commit()
    if cur.rowcount == 0:
        return jsonify({"error": "Order not found"}), 404
    return jsonify({"ok": True, "id": order_id, "status": status})


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  ORIOZEN storefront  →  http://localhost:{port}")
    print(f"  Admin dashboard     →  http://localhost:{port}/admin")
    print(f"  Admin key           →  {ADMIN_KEY}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
