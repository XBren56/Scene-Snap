"""First-run setup. Prompts for owner credentials without putting the password in .env."""
from __future__ import annotations

import os
import re
import secrets
import subprocess
import sys
from getpass import getpass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"

if ENV_FILE.exists():
    raise SystemExit(".env already exists. Start the app with `python run.py`.")

email = input("CEO sign-in email: ").strip().lower()
if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
    raise SystemExit("Enter a valid email address.")
password = getpass("Choose a CEO password (12+ characters): ")
confirmation = getpass("Enter it again: ")
if len(password) < 12 or password != confirmation:
    raise SystemExit("Passwords must match and contain at least 12 characters.")

secret = secrets.token_urlsafe(48)
env_values = {
    "SCENESNAP_SECRET_KEY": secret,
    "SCENESNAP_CEO_EMAIL": email,
    "SCENESNAP_DEV_MODE": "1",
    "SCENESNAP_BASE_URL": "http://127.0.0.1:5000",
    "SCENESNAP_HOURLY_RATE": "25",
}
os.environ.update(env_values)
os.environ["SCENESNAP_CEO_PASSWORD"] = password
password = confirmation = ""

subprocess.run([sys.executable, str(ROOT / "build_native.py")], cwd=ROOT, check=True)
from backend.app import initialize  # noqa: E402
initialize()

ENV_FILE.write_text("# Private local settings. This file is ignored by Git.\n" + "".join(f"{key}={value}\n" for key, value in env_values.items()), encoding="utf-8")
os.environ.pop("SCENESNAP_CEO_PASSWORD", None)
print("\nScene Snap setup is complete.")
print("The CEO password was saved as a password hash in the local database, not in .env.")
print("Start the app with: python run.py")
print("Then open: http://127.0.0.1:5000")
