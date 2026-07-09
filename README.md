# Oriozen Healthcare — Storefront + Backend

A complete Ayurvedic e-commerce store: luxury white storefront, Flask API,
SQLite order database, and an admin dashboard.

## Run it

    pip install -r requirements.txt
    python server.py

Then open:

| URL                          | What it is                         |
|------------------------------|------------------------------------|
| http://localhost:5000        | Storefront (customers shop here)   |
| http://localhost:5000/admin  | Admin dashboard (manage orders)    |

Default admin key: `oriozen-admin` — change it before going live:

    ADMIN_KEY=your-secret-key python server.py

## What the backend does

- **GET  /api/products** — full catalog with all specifications
- **POST /api/orders** — places an order. Prices and totals are recalculated
  on the server (customers can't tamper with them). Validates Indian mobile
  numbers and PIN codes. Returns an order ID like `OZ-260709-4F7K`.
- **GET  /api/orders/<id>/track?phone=** — customers track an order using
  the ID + the phone number they checked out with.
- **GET  /api/admin/orders** — all orders + revenue summary (needs admin key)
- **PATCH /api/admin/orders/<id>** — update status:
  new → confirmed → shipped → delivered (or cancelled)

Orders are stored in `oriozen.db` (SQLite) — a single file you can back up
by copying it.

## Editing products / prices

Everything lives in `data/products.json`. Edit prices, ingredients, or add a
new product (drop its photo in `static/img/` and reference it), then restart
the server.

## Going live (later)

- Deploy on any host that runs Python (Render, Railway, a ₹300/mo VPS).
  For production use `gunicorn`:  `pip install gunicorn && gunicorn -w 2 -b 0.0.0.0:5000 server:app`
- Online payments: add Razorpay at the `/api/orders` step (currently COD only).
- Set a strong `ADMIN_KEY` and serve over HTTPS.
