import os

from backend.app import CEO_EMAIL, DB_FILE, NATIVE_FILE, app, initialize

if len(app.secret_key) < 32 or "replace" in app.secret_key.lower():
    raise SystemExit("Set SCENESNAP_SECRET_KEY to a long random value in .env before starting Scene Snap.")
if not CEO_EMAIL or not os.environ.get("SCENESNAP_CEO_PASSWORD"):
    raise SystemExit("Set the one owner email and a unique password in .env before starting Scene Snap.")
if len(os.environ["SCENESNAP_CEO_PASSWORD"]) < 12 or "replace" in os.environ["SCENESNAP_CEO_PASSWORD"].lower():
    raise SystemExit("SCENESNAP_CEO_PASSWORD must be at least 12 characters.")
if not NATIVE_FILE.exists():
    raise SystemExit("Build the C estimator first by running `python build_native.py`.")

initialize()
app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")), debug=os.environ.get("SCENESNAP_DEV_MODE", "0") == "1")
