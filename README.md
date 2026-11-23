# Scene Snap

Scene Snap is now a runnable full-stack starter with HTML/CSS/JavaScript pages, a Python Flask backend, SQLite SQL storage, and a native C pricing and setup-time estimator called through Python `ctypes`.

## What works

- Customer storefront populated from the SQL product catalog.
- Customer account registration and password sign-in. New accounts start as customers.
- Email verification links. In development, the server displays a local verification link; configure SMTP to send real verification and staff invitation emails.
- Saved customer order requests, event inquiries, and custom design requests in SQLite.
- C-powered event estimates that include decorations, sourcing, labor rate, travel, guest count, and planned time.
- Staff workroom with permission-filtered events, status updates, sourcing lists, and inventory warnings.
- CEO-only owner page, staff invitations, business binder records, event and order summaries, and audit history.
- CEO content studio for editing homepage text, products, and services; publishing custom pages; and uploading image or video media.
- One configured CEO email. Employee permissions are granted only through a specific owner invitation plus verification of the invited email; an email domain by itself grants no access.

## Edit the website

Sign in with the CEO account and open **CEO office → Edit site content**. The Content Studio lets the owner edit homepage copy, add or update shop products and event services, hide items without deleting order history, create and publish custom pages, and upload media for cards and pages.

Uploads accept JPG, PNG, WEBP, GIF, MP4, and WEBM files up to 12 MB. Media is stored under the ignored local `instance/uploads/` folder; back up that folder with the SQLite database. A hosted deployment needs persistent storage for uploads and database records.

## Run locally on Windows

1. Install Python 3.10+ and [MSYS2](https://www.msys2.org/). In the MSYS2 UCRT64 terminal, install GCC with `pacman -S mingw-w64-ucrt-x86_64-gcc`.
2. Open PowerShell in this repository. If MSYS2 is installed in its default folder, make GCC available in that PowerShell window:

   ```powershell
   $env:Path = "C:\msys64\ucrt64\bin;" + $env:Path
   $env:CC = "gcc"
   ```

   Then install the app:

   ```powershell
   py -3 -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   python setup.py
   ```

   Setup asks for the CEO email and password in the terminal. It generates a private app secret, builds the C estimator, creates the database and owner account, and saves only the password hash. Your `.env` file is ignored by Git.
3. Start the app:

   ```powershell
   python run.py
   ```

4. Open `http://127.0.0.1:5000`. The SQLite database is created in the ignored `instance/` folder.

For local account verification, create an account, copy the development verification link shown in the registration dialog, and open it. For staff access, sign in as the CEO, invite the exact work email, then use the invitation link. A staff invite does not activate until the email is verified.

## Security and launch limits

- Never commit `.env`, the SQLite database, email credentials, or payment keys. Keep the CEO email in server configuration. The `ceo/` source folder and all code are public because this GitHub repository is public; only the server-protected records and routes are private.
- `SCENESNAP_DEV_MODE=1` is for local testing. Production needs HTTPS, a long random secret, SMTP, backups, and a deployment that runs Flask and compiles the C library. Do not publish the site with GitHub Pages alone; Pages cannot run this Python backend.
- The product checkout records an order request; it does not collect money. Add a payment provider and confirm tax, refund, privacy, and booking policies before accepting paid orders.
- The app currently uses SQLite for a single-server deployment. Move to PostgreSQL before running multiple app instances or handling significant customer volume.
- The C estimator currently uses the configurable hourly rate and transparent inputs in `.env`; estimates are not final quotes.
- The `Operating-Scene-Snap` repository contains the earlier standalone workroom visual prototype. This repository is the unified app source of truth for customer, staff, and CEO routes.

The runnable storefront markup is the repository-root `index.html`; its styles and browser logic are in `backend/static/`. Flask serves it at `/` so the forms can use the same-origin backend.
