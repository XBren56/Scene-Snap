import os

from backend.app import CEO_EMAIL, NATIVE_FILE, app, initialize

if len(app.secret_key) < 32 or "replace" in app.secret_key.lower():
    raise RuntimeError("Configure a long SCENESNAP_SECRET_KEY before deploying.")
if not CEO_EMAIL or len(os.environ.get("SCENESNAP_CEO_PASSWORD", "")) < 12:
    raise RuntimeError("Configure the one CEO email and a unique password before deploying.")
if os.environ.get("SCENESNAP_DEV_MODE", "0") == "1":
    raise RuntimeError("Turn SCENESNAP_DEV_MODE off before deploying.")
if not NATIVE_FILE.exists():
    raise RuntimeError("Build the C estimator before deploying.")

initialize()
