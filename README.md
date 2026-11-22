# Scene Snap customer storefront

Responsive storefront prototype for party decorations, customizable scene templates, event inquiries, and setup services.

## Pages and flows in this prototype

- Browse by celebration type and add products to a quote bag.
- Customize a template preview with a name, message, palette, date, and notes.
- Submit an event inquiry with date, venue, service details, and contact information.
- Explain delivery, sourcing, setup, event-day styling, and teardown as quoteable services.
- Customer accounts are the default view. Staff and owner permissions belong to the protected operations app and the shared database.

## Before accepting real customers

This repository is a front-end preview. The sign-in and inquiry forms intentionally do not accept credentials or transmit personal information. Connect a secure authentication/database provider, configure the shared schema in `Operating-Scene-Snap/database/schema.sql`, and add a payment provider before taking bookings or payments. Do not store passwords, API secrets, or owner email allowlists in this public repository.

Open `index.html` directly for the preview.
