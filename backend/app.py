from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import os
import secrets
import smtplib
import sqlite3
import ssl
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from functools import wraps
from pathlib import Path
from math import isfinite

from werkzeug.utils import secure_filename

from flask import Flask, abort, g, jsonify, redirect, render_template, request, send_from_directory, session, url_for

ROOT = Path(__file__).resolve().parents[1]
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

DB_FILE = Path(os.environ.get("SCENESNAP_DATABASE", ROOT / "instance" / "scenesnap.sqlite3"))
SCHEMA_FILE = ROOT / "database" / "schema.sql"
NATIVE_FILE = ROOT / "instance" / ("scenesnap_pricing.dll" if sys.platform == "win32" else "libscenesnap_pricing.dylib" if sys.platform == "darwin" else "libscenesnap_pricing.so")
UPLOAD_DIR = Path(os.environ.get("SCENESNAP_UPLOAD_DIR", ROOT / "instance" / "uploads"))
ALLOWED_MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".webm"}
BASE_URL = os.environ.get("SCENESNAP_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
CEO_EMAIL = os.environ.get("SCENESNAP_CEO_EMAIL", "").strip().lower()
DEV_MODE = os.environ.get("SCENESNAP_DEV_MODE", "0") == "1"
HOURLY_RATE = max(0.0, min(float(os.environ.get("SCENESNAP_HOURLY_RATE", "25")), 1000.0))

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("SCENESNAP_SECRET_KEY", "")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=not DEV_MODE, MAX_CONTENT_LENGTH=12 * 1024 * 1024)


@contextmanager
def db():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def now_utc():
    return datetime.now(timezone.utc)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        algo, salt_hex, digest_hex = stored.split("$", 2)
        if algo != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def native_lib():
    if not NATIVE_FILE.exists():
        raise RuntimeError("C pricing library is missing. Run `python build_native.py` first.")
    lib = ctypes.CDLL(str(NATIVE_FILE))
    lib.scenesnap_quote.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_int, ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_int)]
    lib.scenesnap_quote.restype = ctypes.c_int
    return lib


def quote_c(decor_price: float, sourcing_cost: float, labor_hours: float, hourly_rate: float, travel_fee: float, guest_count: int):
    total, minutes = ctypes.c_double(), ctypes.c_int()
    rc = native_lib().scenesnap_quote(decor_price, sourcing_cost, labor_hours, hourly_rate, travel_fee, guest_count, ctypes.byref(total), ctypes.byref(minutes))
    if rc != 0:
        raise ValueError("Could not calculate this estimate. Check the event details.")
    return round(total.value, 2), minutes.value


def initialize():
    with db() as conn:
        conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
        product_columns = {row["name"] for row in conn.execute("PRAGMA table_info(products)").fetchall()}
        if "image_url" not in product_columns:
            conn.execute("ALTER TABLE products ADD COLUMN image_url TEXT NOT NULL DEFAULT ''")
        products = [
            ("garden-birthday", "The Garden Birthday", "Birthday", "Soft florals, a name sign, and cheerful little details.", 6800, "🌷"),
            ("grad-moment", "The Grad Moment", "Graduation", "A photo-ready backdrop for the big next step.", 8200, "🎓"),
            ("golden-hour", "Golden Hour Tablescape", "Wedding", "Warm candlelight and a lovely welcome for your guests.", 14500, "🕯️"),
            ("little-star", "Little Star Welcome", "Milestone", "Gentle colors and a sweet setup for a new arrival.", 7400, "⭐"),
            ("winter-glow", "Winter Glow", "Holiday", "A cozy, bright scene for the holidays at home.", 5900, "❄️"),
            ("proposal-set", "Just Us Proposal Set", "Milestone", "A personal setting for a once-in-a-lifetime question.", 12000, "💍"),
        ]
        conn.executemany("INSERT OR IGNORE INTO products(slug,name,category,description,price_cents,emoji) VALUES(?,?,?,?,?,?)", products)
        services = [
            ("custom-design", "Custom design", "Personalized colors, signage, favors, and coordinated decorations.", "✦", None, 0),
            ("source-gather", "Source & gather", "We build a sourcing list, track costs, and bring all the pieces together.", "□", None, 1),
            ("setup-styling", "Setup & styling", "Choose delivery, event-day styling, and teardown. Labor and travel are included in your estimate.", "◷", None, 2),
        ]
        conn.executemany("INSERT OR IGNORE INTO services(slug,name,description,icon,price_cents,sort_order) VALUES(?,?,?,?,?,?)", services)
        conn.execute("""INSERT OR IGNORE INTO site_settings(id,hero_kicker,hero_title,hero_emphasis,hero_body,hero_note,shop_title,shop_intro,services_title,services_intro,inquiry_title,inquiry_intro)
            VALUES(1,?,?,?,?,?,?,?,?,?,?,?)""", (
            "A little wonder, made for your moment",
            "Make the room feel like",
            "your story.",
            "Thoughtful party backdrops, custom decorations, and hands-on setup for the days you want to remember. Pick a ready-made scene or make one your own.",
            "Your moment, thoughtfully set",
            "Find your starting point",
            "Choose a collection, then make it yours.",
            "We can bring the whole scene",
            "Pick the help that fits your day.",
            "Tell us what you’re celebrating.",
            "Share your date, guest count, and the feeling you want. Your inquiry is saved to your account; our team confirms availability, sourcing, setup time, travel, and the final quote."
        ))
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        owner_email = CEO_EMAIL
        owner_password = os.environ.get("SCENESNAP_CEO_PASSWORD", "")
        if owner_email and owner_password:
            owner = conn.execute("SELECT id,role FROM users WHERE email=? COLLATE NOCASE", (owner_email,)).fetchone()
            if owner is None:
                conn.execute("INSERT INTO users(email,display_name,password_hash,role,email_verified) VALUES(?,?,?,?,1)", (owner_email, "Scene Snap Owner", hash_password(owner_password), "ceo"))
            elif owner["role"] != "ceo":
                conn.execute("UPDATE users SET role='ceo',email_verified=1,active=1 WHERE id=?", (owner["id"],))


def current_user():
    sid = session.get("sid")
    if not sid:
        return None
    with db() as conn:
        row = conn.execute("SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1", (token_hash(sid), now_utc().isoformat())).fetchone()
    if not row:
        session.clear()
        return None
    return row


def require_user(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify(error="Sign in is required."), 401
        if not user["email_verified"]:
            return jsonify(error="Verify your email before continuing."), 403
        g.scene_user = user
        return fn(*args, **kwargs)
    return wrapper


def require_role(*roles):
    def decorator(fn):
        @wraps(fn)
        @require_user
        def wrapper(*args, **kwargs):
            user = g.scene_user
            if user["role"] not in roles:
                return jsonify(error="Your account does not have permission for that page."), 403
            if user["role"] == "ceo" and (not CEO_EMAIL or user["email"].lower() != CEO_EMAIL):
                return jsonify(error="The configured CEO account is required."), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def csrf_check():
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    if request.headers.get("Origin"):
        expected = f"{request.scheme}://{request.host}"
        if request.headers.get("Origin").rstrip("/") != expected.rstrip("/"):
            return jsonify(error="Request origin was not accepted."), 403
    user = current_user()
    if user:
        with db() as conn:
            row = conn.execute("SELECT csrf_token FROM sessions WHERE token_hash=?", (token_hash(session.get("sid", "")),)).fetchone()
        if not row or not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), row["csrf_token"]):
            return jsonify(error="Refresh the page and try again."), 403
    return None


@app.before_request
def protect_mutations():
    if request.path.startswith("/api/"):
        return csrf_check()


def json_body():
    return request.get_json(silent=True) or {}


def send_email(to_email: str, subject: str, body: str):
    host = os.environ.get("SCENESNAP_SMTP_HOST", "").strip()
    if not host:
        if DEV_MODE:
            return False
        raise RuntimeError("Email delivery is not configured. Ask the site owner to configure SMTP.")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("SCENESNAP_SMTP_FROM", "")
    msg["To"] = to_email
    msg.set_content(body)
    port = int(os.environ.get("SCENESNAP_SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=15) as server:
        if os.environ.get("SCENESNAP_SMTP_STARTTLS", "1") == "1":
            server.starttls(context=ssl.create_default_context())
        if os.environ.get("SCENESNAP_SMTP_USER"):
            server.login(os.environ["SCENESNAP_SMTP_USER"], os.environ.get("SCENESNAP_SMTP_PASSWORD", ""))
        server.send_message(msg)
    return True


def create_email_token(conn, user_id: int, purpose: str, email: str):
    token = secrets.token_urlsafe(32)
    expires = now_utc() + timedelta(hours=24)
    conn.execute("INSERT INTO email_tokens(user_id,token_hash,purpose,expires_at) VALUES(?,?,?,?)", (user_id, token_hash(token), purpose, expires.isoformat()))
    action = "verify" if purpose == "verify" else "accept-invite"
    link = f"{BASE_URL}/verify?token={token}&action={action}"
    try:
        sent = send_email(email, "Verify your Scene Snap account", f"Open this link within 24 hours:\n\n{link}")
    except RuntimeError:
        conn.execute("DELETE FROM email_tokens WHERE token_hash=?", (token_hash(token),))
        raise
    return link if not sent and DEV_MODE else None


def row_event(row):
    return {key: row[key] for key in row.keys()}


def content_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")[:80].strip("-")


def clean_media_url(value: str) -> str:
    url = str(value or "").strip()[:600]
    if not url:
        return ""
    if url.startswith("/") and not url.startswith("//"):
        return url
    if url.startswith("https://"):
        return url
    raise ValueError("Media must use an uploaded /uploads/ link or an https:// address.")


def price_to_cents(value, optional=False):
    if optional and value in (None, ""):
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise ValueError("Enter a valid price.")
    if not isfinite(amount) or amount < 0 or amount > 1000000:
        raise ValueError("Price must be between $0 and $1,000,000.")
    return round(amount * 100)


@app.get("/")
def index():
    return send_from_directory(ROOT, "index.html")


@app.get("/workroom")
def workroom():
    user = current_user()
    if not user or not user["email_verified"] or user["role"] == "customer":
        return redirect(url_for("index", signin="1"))
    return render_template("workroom.html")


@app.get("/ceo")
def ceo_page():
    user = current_user()
    if not CEO_EMAIL:
        abort(503, "Owner account has not been configured.")
    if not user:
        return redirect(url_for("index", signin="1"))
    if not user["email_verified"] or user["role"] != "ceo" or user["email"].lower() != CEO_EMAIL:
        abort(403)
    return render_template("ceo.html")


@app.get("/ceo/content")
@require_role("ceo")
def ceo_content_page():
    return render_template("content.html")


@app.get("/page/<slug>")
def public_page(slug):
    with db() as conn:
        page = conn.execute("SELECT * FROM site_pages WHERE slug=? AND published=1", (slug,)).fetchone()
    if not page:
        abort(404)
    return render_template("public_page.html", page=page)


@app.get("/uploads/<path:filename>")
def uploaded_media(filename):
    return send_from_directory(UPLOAD_DIR, filename, conditional=True)


@app.get("/verify")
def verify_page():
    return render_template("verify.html")


@app.get("/api/products")
def products():
    with db() as conn:
        rows = conn.execute("SELECT id,slug,name,category,description,price_cents,emoji,image_url FROM products WHERE active=1 ORDER BY id").fetchall()
    return jsonify(products=[row_event(r) for r in rows])


@app.get("/api/services")
def public_services():
    with db() as conn:
        rows = conn.execute("SELECT id,slug,name,description,icon,image_url,price_cents FROM services WHERE active=1 ORDER BY sort_order,id").fetchall()
    return jsonify(services=[row_event(r) for r in rows])


@app.get("/api/pages")
def public_pages():
    with db() as conn:
        rows = conn.execute("SELECT slug,title,summary,media_url FROM site_pages WHERE published=1 ORDER BY sort_order,id").fetchall()
    return jsonify(pages=[row_event(r) for r in rows])


@app.get("/api/site-settings")
def public_site_settings():
    with db() as conn:
        row = conn.execute("SELECT hero_kicker,hero_title,hero_emphasis,hero_body,hero_note,shop_title,shop_intro,services_title,services_intro,inquiry_title,inquiry_intro FROM site_settings WHERE id=1").fetchone()
    return jsonify(settings=row_event(row) if row else {})


@app.get("/api/me")
def me():
    user = current_user()
    if not user:
        return jsonify(user=None)
    with db() as conn:
        csrf = conn.execute("SELECT csrf_token FROM sessions WHERE token_hash=?", (token_hash(session["sid"]),)).fetchone()
    return jsonify(user={"id": user["id"], "email": user["email"], "name": user["display_name"], "role": user["role"], "verified": bool(user["email_verified"])}, csrf=csrf["csrf_token"] if csrf else None)


@app.post("/api/auth/register")
def register():
    data = json_body()
    email = str(data.get("email", "")).strip().lower()
    name = str(data.get("name", "")).strip()[:100]
    password = str(data.get("password", ""))
    if "@" not in email or len(email) > 254 or not name or len(password) < 10:
        return jsonify(error="Enter your name and a valid email. Passwords need at least 10 characters."), 400
    if not DEV_MODE and not os.environ.get("SCENESNAP_SMTP_HOST", "").strip():
        return jsonify(error="Email verification is not configured. Ask the site owner to configure email delivery."), 503
    if CEO_EMAIL and email == CEO_EMAIL:
        return jsonify(error="The owner account is created privately by the site setup, not through customer registration."), 403
    invite_token = str(data.get("invite_token", ""))
    invite = None
    with db() as conn:
        if conn.execute("SELECT 1 FROM users WHERE email=? COLLATE NOCASE", (email,)).fetchone():
            return jsonify(error="An account with this email already exists. Sign in instead."), 409
        invite = conn.execute("SELECT * FROM staff_invites WHERE email=? COLLATE NOCASE AND token_hash=? AND accepted_at IS NULL AND expires_at>?", (email, token_hash(invite_token), now_utc().isoformat())).fetchone() if invite_token else None
        pending = conn.execute("SELECT 1 FROM staff_invites WHERE email=? COLLATE NOCASE AND accepted_at IS NULL AND expires_at>?", (email, now_utc().isoformat())).fetchone()
        if pending and not invite:
            return jsonify(error="This work email needs its owner-issued invitation link."), 403
        user_id = conn.execute("INSERT INTO users(email,display_name,password_hash,role,email_verified) VALUES(?,?,?,?,0)", (email, name, hash_password(password), "customer")).lastrowid
        link = create_email_token(conn, user_id, "staff_invite" if invite else "verify", email)
        if invite and not DEV_MODE:
            conn.execute("UPDATE staff_invites SET accepted_at=NULL WHERE id=?", (invite["id"],))
    response = {"message": "Check your email for a verification link."}
    if link:
        response["development_verification_link"] = link
    return jsonify(response), 201


@app.post("/api/auth/verify")
def verify_account():
    token = str(json_body().get("token", ""))
    if not token:
        return jsonify(error="Verification link is missing its token."), 400
    with db() as conn:
        row = conn.execute("SELECT t.*,u.email FROM email_tokens t JOIN users u ON u.id=t.user_id WHERE t.token_hash=? AND t.expires_at>?", (token_hash(token), now_utc().isoformat())).fetchone()
        if not row:
            return jsonify(error="This verification link is expired or has already been used."), 400
        role = "customer"
        if row["purpose"] == "staff_invite":
            invite = conn.execute("SELECT * FROM staff_invites WHERE email=? COLLATE NOCASE AND accepted_at IS NULL AND expires_at>?", (row["email"], now_utc().isoformat())).fetchone()
            if not invite:
                return jsonify(error="The employee invitation expired. Ask the owner to send another."), 400
            role = invite["role"]
            conn.execute("UPDATE staff_invites SET accepted_at=?,token_hash=? WHERE id=?", (now_utc().isoformat(), token_hash(secrets.token_urlsafe(32)), invite["id"]))
        conn.execute("UPDATE users SET email_verified=1,role=? WHERE id=?", (role, row["user_id"]))
        conn.execute("DELETE FROM email_tokens WHERE id=?", (row["id"],))
        conn.execute("INSERT INTO audit_log(actor_id,action,entity,entity_id) VALUES(?,?,?,?)", (row["user_id"], "email_verified", "users", str(row["user_id"])))
    return jsonify(message="Email verified. You can sign in now.", role=role)


@app.post("/api/auth/accept-invite")
@require_user
def accept_existing_invite():
    token = str(json_body().get("invite_token", ""))
    if not token:
        return jsonify(error="Invitation token is missing."), 400
    user = g.scene_user
    with db() as conn:
        invite = conn.execute("SELECT * FROM staff_invites WHERE email=? COLLATE NOCASE AND token_hash=? AND expires_at>?", (user["email"], token_hash(token), now_utc().isoformat())).fetchone()
        if not invite:
            return jsonify(error="This work email has no matching active invitation."), 403
        if not user["email_verified"]:
            return jsonify(error="Verify your email address before accepting the invitation."), 403
        conn.execute("UPDATE users SET role=? WHERE id=?", (invite["role"], user["id"]))
        conn.execute("UPDATE staff_invites SET accepted_at=?,token_hash=? WHERE id=?", (now_utc().isoformat(), token_hash(secrets.token_urlsafe(32)), invite["id"]))
        conn.execute("INSERT INTO audit_log(actor_id,action,entity,entity_id) VALUES(?,?,?,?)", (user["id"], "staff_invite_accepted", "users", str(user["id"])))
    return jsonify(message="Work account verified and enabled.", role=invite["role"], redirect="/workroom")


def start_session(user_id: int):
    sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    expires = now_utc() + timedelta(days=7)
    with db() as conn:
        conn.execute("INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at) VALUES(?,?,?,?)", (token_hash(sid), user_id, csrf, expires.isoformat()))
    session.clear()
    session["sid"] = sid
    return csrf


@app.post("/api/auth/login")
def login():
    data = json_body()
    email, password = str(data.get("email", "")).strip().lower(), str(data.get("password", ""))
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE email=? COLLATE NOCASE AND active=1", (email,)).fetchone()
    if not user or not check_password(password, user["password_hash"]):
        return jsonify(error="Email or password is incorrect."), 401
    if not user["email_verified"]:
        return jsonify(error="Verify your email before signing in."), 403
    csrf = start_session(user["id"])
    return jsonify(message="Signed in.", csrf=csrf, role=user["role"], redirect="/ceo" if user["role"] == "ceo" else "/workroom" if user["role"] != "customer" else "/")


@app.post("/api/auth/logout")
@require_user
def logout():
    with db() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(session.get("sid", "")),))
    session.clear()
    return jsonify(message="Signed out.")


@app.post("/api/estimate")
def estimate():
    data = json_body()
    try:
        decor = max(0.0, min(float(data.get("decor_price", 0)), 100000))
        sourcing = max(0.0, min(float(data.get("sourcing_cost", 0)), 100000))
        hours = max(0.0, min(float(data.get("service_hours", 2)), 500))
        guests = max(0, min(int(data.get("guest_count", 0)), 10000))
        travel = max(0.0, min(float(data.get("travel_fee", 0)), 100000))
        total, minutes = quote_c(decor, sourcing, hours, HOURLY_RATE, travel, guests)
    except (TypeError, ValueError, RuntimeError, OverflowError):
        return jsonify(error="Could not calculate an estimate. Check the event details and confirm the C library is built."), 400
    return jsonify(estimate_cents=round(total * 100), planned_minutes=minutes, hourly_rate=round(HOURLY_RATE * 100), note="Planning estimate only; final quote is confirmed by Scene Snap.")


@app.get("/api/events")
@require_user
def my_events():
    user = g.scene_user
    with db() as conn:
        if user["role"] == "customer":
            rows = conn.execute("SELECT * FROM events WHERE customer_id=? ORDER BY event_date", (user["id"],)).fetchall()
        elif user["role"] in ("ceo", "operations_manager"):
            rows = conn.execute("SELECT e.*,u.email AS customer_email FROM events e JOIN users u ON u.id=e.customer_id ORDER BY e.event_date").fetchall()
        else:
            rows = conn.execute("SELECT e.*,u.email AS customer_email FROM events e JOIN users u ON u.id=e.customer_id WHERE e.assigned_to=? ORDER BY e.event_date", (user["id"],)).fetchall()
    return jsonify(events=[row_event(r) for r in rows])


@app.get("/api/orders")
@require_user
def my_orders():
    user = g.scene_user
    with db() as conn:
        if user["role"] in ("operations_manager", "ceo"):
            rows = conn.execute("SELECT o.*,u.email AS customer_email FROM orders o JOIN users u ON u.id=o.customer_id ORDER BY o.created_at DESC LIMIT 100").fetchall()
        else:
            rows = conn.execute("SELECT * FROM orders WHERE customer_id=? ORDER BY created_at DESC", (user["id"],)).fetchall()
        output = []
        for row in rows:
            item_rows = conn.execute("SELECT oi.quantity,oi.unit_price_cents,p.name,p.slug FROM order_items oi JOIN products p ON p.id=oi.product_id WHERE oi.order_id=?", (row["id"],)).fetchall()
            order = row_event(row)
            order["items"] = [row_event(item) for item in item_rows]
            output.append(order)
    return jsonify(orders=output)


@app.post("/api/orders")
@require_role("customer")
def create_order():
    data = json_body()
    items = data.get("items")
    if not isinstance(items, list) or not items or len(items) > 50:
        return jsonify(error="Add at least one product to your order."), 400
    with db() as conn:
        clean_items, subtotal = [], 0
        for item in items:
            try:
                product_id, qty = int(item.get("product_id")), int(item.get("quantity", 1))
            except (TypeError, ValueError, AttributeError):
                return jsonify(error="One of the cart items is invalid."), 400
            if qty < 1 or qty > 50:
                return jsonify(error="Product quantities must be between 1 and 50."), 400
            product = conn.execute("SELECT id,price_cents FROM products WHERE id=? AND active=1", (product_id,)).fetchone()
            if not product:
                return jsonify(error="A selected product is no longer available."), 400
            subtotal += product["price_cents"] * qty
            clean_items.append((product["id"], qty, product["price_cents"]))
        cur = conn.execute("INSERT INTO orders(customer_id,subtotal_cents,customer_notes) VALUES(?,?,?)", (g.scene_user["id"], subtotal, str(data.get("notes", "")).strip()[:2000]))
        order_id = cur.lastrowid
        conn.executemany("INSERT INTO order_items(order_id,product_id,quantity,unit_price_cents) VALUES(?,?,?,?)", [(order_id, *item) for item in clean_items])
        conn.execute("INSERT INTO audit_log(actor_id,action,entity,entity_id) VALUES(?,?,?,?)", (g.scene_user["id"], "order_quote_requested", "orders", str(order_id)))
    return jsonify(message="Order request saved. Scene Snap will confirm customization, availability, delivery, and final price.", order_id=order_id, subtotal_cents=subtotal, status="quote_requested"), 201


@app.post("/api/events")
@require_role("customer", "event_assistant", "designer", "operations_manager", "ceo")
def create_event():
    data = json_body()
    event_type = str(data.get("event_type", "")).strip()[:40]
    event_date = str(data.get("event_date", ""))
    if not event_type:
        return jsonify(error="Choose what you are celebrating."), 400
    try:
        parsed_date = date.fromisoformat(event_date)
        if parsed_date < date.today():
            return jsonify(error="Choose a future event date."), 400
        guests = max(0, min(int(data.get("guest_count", 0)), 10000))
        budget = int(float(data.get("budget", 0)) * 100) if data.get("budget") else None
        if budget is not None and budget < 0:
            raise ValueError
        decor = max(0.0, min(float(data.get("decor_price", 68)), 100000))
        sourcing = max(0.0, min(float(data.get("sourcing_cost", 0)), 100000))
        hours = max(0.0, min(float(data.get("service_hours", 2)), 500))
        travel = max(0.0, min(float(data.get("travel_fee", 0)), 100000))
        total, minutes = quote_c(decor, sourcing, hours, HOURLY_RATE, travel, guests)
    except (ValueError, TypeError, RuntimeError, OverflowError):
        return jsonify(error="Check the date, budget, and estimate details."), 400
    customer = g.scene_user
    title = str(data.get("title", "")).strip()[:120] or f"{event_type} · {parsed_date.isoformat()}"
    with db() as conn:
        cur = conn.execute("INSERT INTO events(customer_id,title,event_type,event_date,venue,guest_count,budget_cents,details,estimate_cents,estimated_minutes) VALUES(?,?,?,?,?,?,?,?,?,?)", (customer["id"], title, event_type, event_date, str(data.get("venue", "")).strip()[:200], guests, budget, str(data.get("details", "")).strip()[:4000], round(total * 100), minutes))
        event_id = cur.lastrowid
        conn.execute("INSERT INTO audit_log(actor_id,action,entity,entity_id) VALUES(?,?,?,?)", (customer["id"], "event_inquiry_created", "events", str(event_id)))
    return jsonify(message="Your event inquiry is saved.", event_id=event_id, estimate_cents=round(total * 100), planned_minutes=minutes), 201


@app.get("/api/designs")
@require_user
def designs():
    with db() as conn:
        rows = conn.execute("SELECT * FROM designs WHERE customer_id=? ORDER BY updated_at DESC", (g.scene_user["id"],)).fetchall()
    return jsonify(designs=[row_event(r) for r in rows])


@app.post("/api/designs")
@require_role("customer", "designer", "operations_manager", "ceo")
def save_design():
    data = json_body()
    title = str(data.get("title", "")).strip()[:100]
    if not title:
        return jsonify(error="Add a name or message to your design."), 400
    color = str(data.get("color", "#ecdcd0"))
    if len(color) != 7 or not color.startswith("#"):
        return jsonify(error="Choose a valid design color."), 400
    with db() as conn:
        cur = conn.execute("INSERT INTO designs(customer_id,template,title,subtitle,color,event_date,notes,status) VALUES(?,?,?,?,?,?,?,'submitted')", (g.scene_user["id"], str(data.get("template", "Garden Party"))[:60], title, str(data.get("subtitle", ""))[:140], color, str(data.get("event_date", ""))[:10], str(data.get("notes", "")).strip()[:2000]))
        design_id = cur.lastrowid
        conn.execute("INSERT INTO audit_log(actor_id,action,entity,entity_id) VALUES(?,?,?,?)", (g.scene_user["id"], "design_submitted", "designs", str(design_id)))
    return jsonify(message="Your design was saved and sent for pricing.", design_id=design_id), 201


@app.get("/api/workroom")
@require_role("event_assistant", "designer", "operations_manager", "ceo")
def workroom_data():
    user = g.scene_user
    with db() as conn:
        if user["role"] in ("operations_manager", "ceo"):
            rows = conn.execute("SELECT e.*,u.email AS customer_email FROM events e JOIN users u ON u.id=e.customer_id ORDER BY e.event_date LIMIT 100").fetchall()
            inventory = conn.execute("SELECT * FROM inventory_items ORDER BY name").fetchall()
            sourcing = conn.execute("SELECT * FROM sourcing_items ORDER BY due_date LIMIT 100").fetchall()
        else:
            rows = conn.execute("SELECT e.*,u.email AS customer_email FROM events e JOIN users u ON u.id=e.customer_id WHERE e.assigned_to=? ORDER BY e.event_date LIMIT 100", (user["id"],)).fetchall()
            inventory = conn.execute("SELECT id,name,quantity_on_hand,reorder_at,unit FROM inventory_items WHERE quantity_on_hand<=reorder_at ORDER BY name").fetchall()
            sourcing = conn.execute("SELECT * FROM sourcing_items WHERE event_id IN (SELECT id FROM events WHERE assigned_to=?) ORDER BY due_date LIMIT 100", (user["id"],)).fetchall()
        team = conn.execute("SELECT id,email,display_name,role FROM users WHERE role IN ('event_assistant','designer','operations_manager') AND active=1 ORDER BY display_name").fetchall() if user["role"] in ("operations_manager", "ceo") else []
    return jsonify(events=[row_event(r) for r in rows], inventory=[row_event(r) for r in inventory], sourcing=[row_event(r) for r in sourcing], team=[row_event(r) for r in team], role=user["role"])


@app.patch("/api/workroom/events/<int:event_id>")
@require_role("event_assistant", "designer", "operations_manager", "ceo")
def update_event(event_id):
    data = json_body()
    status = str(data.get("status", ""))
    allowed = {"inquiry", "quoted", "approved", "booked", "in_progress", "completed", "cancelled"}
    if status not in allowed:
        return jsonify(error="Choose a valid event status."), 400
    user = g.scene_user
    with db() as conn:
        row = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if not row:
            return jsonify(error="Event not found."), 404
        if user["role"] not in ("operations_manager", "ceo") and row["assigned_to"] != user["id"]:
            return jsonify(error="This event is not assigned to you."), 403
        conn.execute("UPDATE events SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, event_id))
        conn.execute("INSERT INTO audit_log(actor_id,action,entity,entity_id) VALUES(?,?,?,?)", (user["id"], "event_status_changed", "events", str(event_id)))
    return jsonify(message="Event updated.")


@app.patch("/api/workroom/events/<int:event_id>/assignment")
@require_role("operations_manager", "ceo")
def assign_event(event_id):
    data = json_body()
    staff_id = data.get("staff_id")
    try:
        staff_id = int(staff_id) if staff_id not in (None, "", "unassigned") else None
    except (TypeError, ValueError):
        return jsonify(error="Choose a valid employee."), 400
    with db() as conn:
        event = conn.execute("SELECT id FROM events WHERE id=?", (event_id,)).fetchone()
        if not event:
            return jsonify(error="Event not found."), 404
        if staff_id is not None:
            staff = conn.execute("SELECT id FROM users WHERE id=? AND role IN ('event_assistant','designer','operations_manager') AND active=1 AND email_verified=1", (staff_id,)).fetchone()
            if not staff:
                return jsonify(error="Choose an active, verified staff member."), 400
        conn.execute("UPDATE events SET assigned_to=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (staff_id, event_id))
        conn.execute("INSERT INTO audit_log(actor_id,action,entity,entity_id) VALUES(?,?,?,?)", (g.scene_user["id"], "event_assignment_changed", "events", str(event_id)))
    return jsonify(message="Event assignment saved.")


@app.post("/api/workroom/sourcing")
@require_role("event_assistant", "operations_manager", "ceo")
def add_sourcing_item():
    data = json_body()
    item_name = str(data.get("item_name", "")).strip()[:160]
    if not item_name:
        return jsonify(error="Enter the item to source."), 400
    try:
        quantity = max(0.01, min(float(data.get("quantity", 1)), 100000))
        cost_cents = max(0, min(round(float(data.get("expected_cost", 0)) * 100), 100000000))
    except (TypeError, ValueError):
        return jsonify(error="Enter a valid quantity and expected cost."), 400
    event_id = data.get("event_id")
    try:
        event_id = int(event_id) if event_id else None
    except (TypeError, ValueError):
        return jsonify(error="Choose a valid event."), 400
    user = g.scene_user
    with db() as conn:
        if event_id:
            event = conn.execute("SELECT id,assigned_to FROM events WHERE id=?", (event_id,)).fetchone()
            if not event or (user["role"] == "event_assistant" and event["assigned_to"] != user["id"]):
                return jsonify(error="You can only add sourcing to an event assigned to you."), 403
        cur = conn.execute("INSERT INTO sourcing_items(event_id,item_name,quantity,expected_cost_cents,status,due_date,notes) VALUES(?,?,?,?,?,?,?)", (event_id, item_name, quantity, cost_cents, "to_order", str(data.get("due_date", ""))[:10] or None, str(data.get("notes", "")).strip()[:1000]))
        conn.execute("INSERT INTO audit_log(actor_id,action,entity,entity_id) VALUES(?,?,?,?)", (user["id"], "sourcing_item_added", "sourcing_items", str(cur.lastrowid)))
    return jsonify(message="Sourcing item saved.", sourcing_id=cur.lastrowid), 201


@app.post("/api/workroom/inventory")
@require_role("operations_manager", "ceo")
def save_inventory_item():
    data = json_body()
    name = str(data.get("name", "")).strip()[:160]
    if not name:
        return jsonify(error="Enter an inventory item name."), 400
    try:
        quantity = max(0.0, min(float(data.get("quantity_on_hand", 0)), 1000000))
        reorder_at = max(0.0, min(float(data.get("reorder_at", 0)), 1000000))
        cost_cents = max(0, min(round(float(data.get("replacement_cost", 0)) * 100), 100000000))
    except (TypeError, ValueError):
        return jsonify(error="Enter valid stock quantities and replacement cost."), 400
    unit = str(data.get("unit", "each")).strip()[:30] or "each"
    location = str(data.get("storage_location", "")).strip()[:160]
    with db() as conn:
        conn.execute("INSERT INTO inventory_items(name,quantity_on_hand,reorder_at,unit,replacement_cost_cents,storage_location) VALUES(?,?,?,?,?,?) ON CONFLICT(name COLLATE NOCASE) DO UPDATE SET quantity_on_hand=excluded.quantity_on_hand,reorder_at=excluded.reorder_at,unit=excluded.unit,replacement_cost_cents=excluded.replacement_cost_cents,storage_location=excluded.storage_location,updated_at=CURRENT_TIMESTAMP", (name, quantity, reorder_at, unit, cost_cents, location))
        item = conn.execute("SELECT id FROM inventory_items WHERE name=? COLLATE NOCASE", (name,)).fetchone()
        conn.execute("INSERT INTO audit_log(actor_id,action,entity,entity_id) VALUES(?,?,?,?)", (g.scene_user["id"], "inventory_updated", "inventory_items", str(item["id"])))
    return jsonify(message="Inventory saved.", inventory_id=item["id"]), 201


@app.get("/api/ceo/summary")
@require_role("ceo")
def owner_summary():
    with db() as conn:
        active = conn.execute("SELECT COUNT(*) FROM events WHERE status NOT IN ('completed','cancelled')").fetchone()[0]
        inquiries = conn.execute("SELECT COUNT(*) FROM events WHERE status='inquiry'").fetchone()[0]
        designs = conn.execute("SELECT COUNT(*) FROM designs WHERE status='submitted'").fetchone()[0]
        inventory = conn.execute("SELECT COUNT(*) FROM inventory_items WHERE quantity_on_hand<=reorder_at").fetchone()[0]
        staff = conn.execute("SELECT COUNT(*) FROM users WHERE role NOT IN ('customer','ceo') AND active=1").fetchone()[0]
        events = conn.execute("SELECT e.*,u.email AS customer_email FROM events e JOIN users u ON u.id=e.customer_id ORDER BY e.created_at DESC LIMIT 100").fetchall()
        records = conn.execute("SELECT * FROM business_records ORDER BY updated_at DESC").fetchall()
        logs = conn.execute("SELECT a.*,u.email AS actor_email FROM audit_log a LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT 40").fetchall()
        open_orders = conn.execute("SELECT COUNT(*) FROM orders WHERE status IN ('quote_requested','quoted','accepted','in_production','ready')").fetchone()[0]
        orders = conn.execute("SELECT o.*,u.email AS customer_email FROM orders o JOIN users u ON u.id=o.customer_id ORDER BY o.created_at DESC LIMIT 100").fetchall()
    return jsonify(metrics={"active_events": active,"new_inquiries": inquiries,"designs_to_review": designs,"low_stock": inventory,"staff": staff,"open_orders": open_orders}, events=[row_event(r) for r in events], orders=[row_event(r) for r in orders], records=[row_event(r) for r in records], audit=[row_event(r) for r in logs])


@app.post("/api/ceo/staff-invites")
@require_role("ceo")
def invite_staff():
    data = json_body()
    email = str(data.get("email", "")).strip().lower()
    role = str(data.get("role", ""))
    if "@" not in email or role not in ("event_assistant", "designer", "operations_manager") or email == CEO_EMAIL:
        return jsonify(error="Use an employee email and a valid staff role."), 400
    token = secrets.token_urlsafe(32)
    expires = now_utc() + timedelta(days=7)
    with db() as conn:
        conn.execute("INSERT INTO staff_invites(email,role,token_hash,invited_by,expires_at) VALUES(?,?,?,?,?) ON CONFLICT(email) DO UPDATE SET role=excluded.role,token_hash=excluded.token_hash,invited_by=excluded.invited_by,expires_at=excluded.expires_at,accepted_at=NULL", (email, role, token_hash(token), g.scene_user["id"], expires.isoformat()))
        user = conn.execute("SELECT id FROM users WHERE email=? COLLATE NOCASE", (email,)).fetchone()
        if user:
            conn.execute("UPDATE staff_invites SET accepted_at=NULL WHERE email=? COLLATE NOCASE", (email,))
    link = f"{BASE_URL}/?invite={token}"
    try:
        sent = send_email(email, "Scene Snap staff invitation", f"You have been invited to Scene Snap as {role.replace('_',' ')}.\n\nCreate or verify your account here:\n{link}\n\nThis invitation expires in seven days.")
    except RuntimeError:
        return jsonify(error="Invite saved, but email delivery is not configured. Set SMTP before inviting employees."), 503
    response = {"message": "Staff invitation sent.", "role": role}
    if not sent and DEV_MODE:
        response["development_invitation_link"] = link
    return jsonify(response), 201


@app.get("/api/ceo/staff")
@require_role("ceo")
def staff_list():
    with db() as conn:
        rows = conn.execute("SELECT id,email,display_name,role,email_verified,active,created_at FROM users WHERE role<>'customer' ORDER BY role,email").fetchall()
    return jsonify(staff=[row_event(r) for r in rows])


@app.patch("/api/ceo/staff/<int:user_id>")
@require_role("ceo")
def update_staff(user_id):
    data = json_body()
    role = str(data.get("role", ""))
    active = data.get("active")
    if role and role not in ("event_assistant", "designer", "operations_manager"):
        return jsonify(error="Choose a valid employee role."), 400
    if active is not None and not isinstance(active, bool):
        return jsonify(error="Active access must be true or false."), 400
    if user_id == g.scene_user["id"]:
        return jsonify(error="You cannot change your own CEO access here."), 400
    with db() as conn:
        staff = conn.execute("SELECT id,role FROM users WHERE id=? AND role<>'customer' AND role<>'ceo'", (user_id,)).fetchone()
        if not staff:
            return jsonify(error="Staff account not found."), 404
        changes, values = [], []
        if role:
            changes.append("role=?")
            values.append(role)
        if active is not None:
            changes.append("active=?")
            values.append(int(active))
        if not changes:
            return jsonify(error="Choose a role or access change."), 400
        values.append(user_id)
        conn.execute(f"UPDATE users SET {', '.join(changes)} WHERE id=?", values)
        conn.execute("INSERT INTO audit_log(actor_id,action,entity,entity_id) VALUES(?,?,?,?)", (g.scene_user["id"], "staff_access_changed", "users", str(user_id)))
    return jsonify(message="Staff permissions updated.")


@app.post("/api/ceo/business-records")
@require_role("ceo")
def add_business_record():
    data = json_body()
    kinds = ("plan", "goal", "policy", "license", "insurance", "tax", "pricing", "marketing", "season_plan", "meeting", "other")
    record_type, title = str(data.get("record_type", "other")), str(data.get("title", "")).strip()[:160]
    if record_type not in kinds or not title:
        return jsonify(error="Add a title and choose a record type."), 400
    with db() as conn:
        cur = conn.execute("INSERT INTO business_records(record_type,title,content,visibility,updated_by) VALUES(?,?,?,?,?)", (record_type, title, str(data.get("content", ""))[:10000], "ceo", g.scene_user["id"]))
        conn.execute("INSERT INTO audit_log(actor_id,action,entity,entity_id) VALUES(?,?,?,?)", (g.scene_user["id"], "business_record_created", "business_records", str(cur.lastrowid)))
    return jsonify(message="Business record saved.", record_id=cur.lastrowid), 201


@app.get("/api/ceo/records")
@require_role("ceo")
def ceo_records():
    with db() as conn:
        rows = conn.execute("SELECT * FROM business_records ORDER BY updated_at DESC").fetchall()
    return jsonify(records=[row_event(r) for r in rows])


@app.get("/api/ceo/content")
@require_role("ceo")
def ceo_content():
    with db() as conn:
        products = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
        services = conn.execute("SELECT * FROM services ORDER BY sort_order,id").fetchall()
        pages = conn.execute("SELECT * FROM site_pages ORDER BY sort_order,id").fetchall()
        media = conn.execute("SELECT * FROM media_assets ORDER BY id DESC").fetchall()
        settings = conn.execute("SELECT * FROM site_settings WHERE id=1").fetchone()
    return jsonify(products=[row_event(r) for r in products], services=[row_event(r) for r in services], pages=[row_event(r) for r in pages], media=[row_event(r) for r in media], settings=row_event(settings) if settings else {})


@app.patch("/api/ceo/site-settings")
@require_role("ceo")
def update_site_settings():
    data = json_body()
    fields = ("hero_kicker","hero_title","hero_emphasis","hero_body","hero_note","shop_title","shop_intro","services_title","services_intro","inquiry_title","inquiry_intro")
    values = [str(data.get(key, "")).strip()[:4000] for key in fields]
    with db() as conn:
        conn.execute("UPDATE site_settings SET " + ",".join(f"{key}=?" for key in fields) + ",updated_at=CURRENT_TIMESTAMP WHERE id=1", values)
        row = conn.execute("SELECT * FROM site_settings WHERE id=1").fetchone()
        conn.execute("INSERT INTO audit_log(actor_id,action,entity,entity_id) VALUES(?,?,?,?)", (g.scene_user["id"], "homepage_content_updated", "site_settings", "1"))
    return jsonify(message="Homepage content saved.", settings=row_event(row))


def content_values(data, required_name=True):
    name = str(data.get("name", "")).strip()[:160]
    if required_name and not name:
        raise ValueError("Add a name or title.")
    slug = content_slug(data.get("slug") or name)
    if not slug:
        raise ValueError("Use letters or numbers for the page address.")
    description = str(data.get("description", "")).strip()[:2000]
    image_url = clean_media_url(data.get("image_url", ""))
    return name, slug, description, image_url


@app.post("/api/ceo/products")
@require_role("ceo")
def add_product():
    data = json_body()
    try:
        name, slug, description, image_url = content_values(data)
        category = str(data.get("category", "")).strip()[:60]
        if not category:
            raise ValueError("Add a product category.")
        price_cents = price_to_cents(data.get("price"))
        emoji = str(data.get("emoji", "✿")).strip()[:12] or "✿"
        with db() as conn:
            cur = conn.execute("INSERT INTO products(slug,name,category,description,price_cents,emoji,image_url,active) VALUES(?,?,?,?,?,?,?,1)", (slug,name,category,description,price_cents,emoji,image_url))
        return jsonify(message="Product added.", id=cur.lastrowid), 201
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except sqlite3.IntegrityError:
        return jsonify(error="That product page address is already in use."), 409


@app.patch("/api/ceo/products/<int:item_id>")
@require_role("ceo")
def update_product(item_id):
    data = json_body()
    try:
        with db() as conn:
            existing = conn.execute("SELECT * FROM products WHERE id=?", (item_id,)).fetchone()
            if not existing:
                return jsonify(error="Product not found."), 404
            merged = dict(existing)
            merged.update(data)
            name, slug, description, image_url = content_values(merged)
            category = str(merged.get("category", "")).strip()[:60]
            if not category:
                raise ValueError("Add a product category.")
            price_cents = price_to_cents(merged.get("price", round(merged.get("price_cents", 0) / 100, 2)))
            emoji = str(merged.get("emoji", "✿")).strip()[:12] or "✿"
            active = 1 if merged.get("active", True) else 0
            conn.execute("UPDATE products SET slug=?,name=?,category=?,description=?,price_cents=?,emoji=?,image_url=?,active=? WHERE id=?", (slug,name,category,description,price_cents,emoji,image_url,active,item_id))
        return jsonify(message="Product updated.")
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except sqlite3.IntegrityError:
        return jsonify(error="That product page address is already in use."), 409


@app.post("/api/ceo/services")
@require_role("ceo")
def add_service():
    data = json_body()
    try:
        name, slug, description, image_url = content_values(data)
        icon = str(data.get("icon", "✦")).strip()[:12] or "✦"
        price_cents = price_to_cents(data.get("price"), optional=True)
        with db() as conn:
            cur = conn.execute("INSERT INTO services(slug,name,description,icon,image_url,price_cents,sort_order,active) VALUES(?,?,?,?,?,?,COALESCE((SELECT MAX(sort_order)+1 FROM services),0),1)", (slug,name,description,icon,image_url,price_cents))
        return jsonify(message="Service added.", id=cur.lastrowid), 201
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except sqlite3.IntegrityError:
        return jsonify(error="That service page address is already in use."), 409


@app.patch("/api/ceo/services/<int:item_id>")
@require_role("ceo")
def update_service(item_id):
    data = json_body()
    try:
        with db() as conn:
            existing = conn.execute("SELECT * FROM services WHERE id=?", (item_id,)).fetchone()
            if not existing:
                return jsonify(error="Service not found."), 404
            merged = dict(existing)
            merged.update(data)
            name, slug, description, image_url = content_values(merged)
            icon = str(merged.get("icon", "✦")).strip()[:12] or "✦"
            price_cents = price_to_cents(merged.get("price", "" if merged.get("price_cents") is None else round(merged.get("price_cents") / 100, 2)), optional=True)
            active = 1 if merged.get("active", True) else 0
            conn.execute("UPDATE services SET slug=?,name=?,description=?,icon=?,image_url=?,price_cents=?,active=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (slug,name,description,icon,image_url,price_cents,active,item_id))
        return jsonify(message="Service updated.")
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except sqlite3.IntegrityError:
        return jsonify(error="That service page address is already in use."), 409


@app.post("/api/ceo/pages")
@require_role("ceo")
def add_site_page():
    data = json_body()
    try:
        title = str(data.get("title", "")).strip()[:160]
        if not title:
            raise ValueError("Add a page title.")
        slug = content_slug(data.get("slug") or title)
        if not slug:
            raise ValueError("Use letters or numbers for the page address.")
        media_url = clean_media_url(data.get("media_url", ""))
        summary = str(data.get("summary", "")).strip()[:500]
        body = str(data.get("body", "")).strip()[:20000]
        published = 1 if data.get("published") else 0
        with db() as conn:
            cur = conn.execute("INSERT INTO site_pages(slug,title,summary,body,media_url,published) VALUES(?,?,?,?,?,?)", (slug,title,summary,body,media_url,published))
        return jsonify(message="Page saved.", id=cur.lastrowid, url=f"/page/{slug}"), 201
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except sqlite3.IntegrityError:
        return jsonify(error="That page address is already in use."), 409


@app.patch("/api/ceo/pages/<int:item_id>")
@require_role("ceo")
def update_site_page(item_id):
    data = json_body()
    try:
        with db() as conn:
            existing = conn.execute("SELECT * FROM site_pages WHERE id=?", (item_id,)).fetchone()
            if not existing:
                return jsonify(error="Page not found."), 404
            merged = dict(existing)
            merged.update(data)
            title = str(merged.get("title", "")).strip()[:160]
            if not title:
                raise ValueError("Add a page title.")
            slug = content_slug(merged.get("slug") or title)
            if not slug:
                raise ValueError("Use letters or numbers for the page address.")
            media_url = clean_media_url(merged.get("media_url", ""))
            summary = str(merged.get("summary", "")).strip()[:500]
            body = str(merged.get("body", "")).strip()[:20000]
            published = 1 if merged.get("published") else 0
            conn.execute("UPDATE site_pages SET slug=?,title=?,summary=?,body=?,media_url=?,published=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (slug,title,summary,body,media_url,published,item_id))
        return jsonify(message="Page updated.", url=f"/page/{slug}")
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except sqlite3.IntegrityError:
        return jsonify(error="That page address is already in use."), 409


@app.post("/api/ceo/media")
@require_role("ceo")
def upload_media():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify(error="Choose an image or video to upload."), 400
    original_name = secure_filename(file.filename)
    extension = Path(original_name).suffix.lower()
    if extension not in ALLOWED_MEDIA_EXTENSIONS:
        return jsonify(error="Use JPG, PNG, WEBP, GIF, MP4, or WEBM files."), 400
    stored_name = f"{secrets.token_hex(12)}{extension}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file.save(UPLOAD_DIR / stored_name)
    mime_type = file.mimetype or "application/octet-stream"
    media_type = "video" if extension in {".mp4", ".webm"} else "image"
    with db() as conn:
        cur = conn.execute("INSERT INTO media_assets(stored_name,original_name,media_type,mime_type,size_bytes,uploaded_by) VALUES(?,?,?,?,?,?)", (stored_name,original_name,media_type,mime_type,(UPLOAD_DIR / stored_name).stat().st_size,g.scene_user["id"]))
    return jsonify(message="Media uploaded.", asset={"id":cur.lastrowid,"original_name":original_name,"media_type":media_type,"url":f"/uploads/{stored_name}"}), 201


@app.get("/health")
def health():
    return jsonify(status="ok", database=DB_FILE.exists(), c_estimator=NATIVE_FILE.exists())


if __name__ == "__main__":
    if not app.secret_key:
        raise SystemExit("Set SCENESNAP_SECRET_KEY in your environment before starting the app.")
    initialize()
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")), debug=DEV_MODE)
