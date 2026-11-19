# SRG — Sri Rama Gulkhand e-commerce starter

A Flask + SQLAlchemy full-stack foundation with a responsive storefront, relational database models, Gmail email-OTP login flow, retail/wholesale catalogue and price separation, cart calculations, best-coupon selection, COD checkout, stock deduction, order history, PDF invoices, admin dashboard, basic product/stock/customer/coupon management, CSV customer export, and activity logging.

## Run locally

1. Python 3.11+
2. `python -m venv .venv && source .venv/bin/activate` (Windows: `.venv\\Scripts\\activate`)
3. `pip install -r requirements.txt`
4. `cp .env.example .env` and set a unique `SECRET_KEY`, `ADMIN_EMAIL`, and Gmail SMTP settings.
5. `flask --app app init-db`
6. `flask --app app run`

Open `http://127.0.0.1:5000`. In debug mode, the OTP is displayed on the verification page for local testing. Do not run debug mode in production.

## Production setup

- Use PostgreSQL (`DATABASE_URL`) and a managed HTTPS host.
- Set `FLASK_DEBUG=0`, a strong `SECRET_KEY`, secure cookie settings, and configure Gmail SMTP using a Google App Password (`SMTP_USERNAME`, `SMTP_APP_PASSWORD`, `SMTP_FROM`). SMS/WhatsApp adapters are optional and separate from login.
- Configure retail delivery slabs using `RETAIL_DELIVERY_SLABS`, e.g. `0:60,500:30,1000:0`. These are examples only; obtain SRG's actual delivery slabs before accepting retail orders.
- Provision the sole admin mobile securely. The seeded admin mobile is controlled by `ADMIN_MOBILE`; no customer-facing role switch exists.
- Add database migrations, backups, monitoring, rate limiting at the edge, provider webhook verification, and security review before launch.

## Important scope notes before going live

The supplied brief references retail delivery slabs but does not provide the actual thresholds/charges. Retail checkout intentionally refuses to calculate delivery until configured. SMS and WhatsApp credentials/provider details were not supplied; the app records notification attempts and isolates provider integration, but the production HTTP provider adapters still need implementation and verification. Email OTP is sent through Gmail SMTP when configured. In debug mode only, if SMTP credentials are absent, the OTP is printed to the server console and shown on the verification page for local testing.

This is a runnable implementation foundation, not a claim that every requested production workflow has been completed or externally tested. In particular, full admin order-line/address editing, cancellation request/approval/rejection workflow, customer self-service address edit/delete/default selection, wholesale approval tooling, product/variant image uploads and full CRUD, report date filters/performance reporting, scheduled coupon expiry cleanup, 1:00 AM IST coupon reset semantics, and complete notification delivery callbacks need to be finished and tested before production. Review all business rules and have the deployment/security setup audited.

## Gmail email OTP setup

1. Choose a dedicated SRG Gmail account to send verification messages.
2. Enable 2-Step Verification on that Google account.
3. Create a Google App Password and put it in `SMTP_APP_PASSWORD` in your private `.env` file. Do not put the App Password in source code or share it in chat.
4. Set `SMTP_USERNAME` and `SMTP_FROM` to the sender Gmail address, and set `ADMIN_EMAIL` to the email address used for the SRG administrator login.
5. Restart the app and test with an email address you can access.

Customers sign in using their own email address; the sender Gmail account is only used by the server to send OTP messages. Customer mobile number is collected separately as part of the delivery address.

**Database note:** this email-login version changes the user identity schema. For a brand-new setup, initialize a fresh database. If you already have customer/order data in the earlier mobile-login database, back it up and perform a reviewed migration before using this version; `create_all` does not convert the old mobile column constraints automatically.
