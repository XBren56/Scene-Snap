import os

from backend.app import CEO_EMAIL, NATIVE_FILE, app, db, initialize

if len(app.secret_key) < 32 or "replace" in app.secret_key.lower():
    raise RuntimeError("Configure a long SCENESNAP_SECRET_KEY before deploying.")
if not CEO_EMAIL:
    raise RuntimeError("Configure the one CEO email before deploying.")
if os.environ.get("SCENESNAP_DEV_MODE", "0") == "1":
    raise RuntimeError("Turn SCENESNAP_DEV_MODE off before deploying.")
if not NATIVE_FILE.exists():
    raise RuntimeError("Build the C estimator before deploying.")

initialize()
with db() as conn:
    owner = conn.execute("SELECT id FROM users WHERE role='ceo' AND email=? COLLATE NOCASE AND active=1", (CEO_EMAIL,)).fetchone()
if not owner:
    raise RuntimeError("The configured CEO account is missing. Run setup.py before deployment.")
