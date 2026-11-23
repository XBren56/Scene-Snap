import os

from backend.app import CEO_EMAIL, DB_FILE, NATIVE_FILE, app, db, initialize

if len(app.secret_key) < 32 or "replace" in app.secret_key.lower():
    raise SystemExit("Set SCENESNAP_SECRET_KEY to a long random value in .env before starting Scene Snap.")
if not CEO_EMAIL:
    raise SystemExit("Run `python setup.py` once to configure your private CEO email and password.")
if not NATIVE_FILE.exists():
    raise SystemExit("Build the C estimator first by running `python build_native.py`.")

initialize()
with db() as conn:
    owner = conn.execute("SELECT id FROM users WHERE role='ceo' AND email=? COLLATE NOCASE AND active=1", (CEO_EMAIL,)).fetchone()
if not owner:
    raise SystemExit("The configured CEO account is missing. Run `python setup.py` to finish setup.")
app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")), debug=os.environ.get("SCENESNAP_DEV_MODE", "0") == "1")
