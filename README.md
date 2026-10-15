# Academy payment and email configuration

Paid course and resource checkout uses Paystack. Add the following environment variables before enabling paid sales:

```env
PAYSTACK_SECRET_KEY=sk_test_...
PAYSTACK_CALLBACK_URL=https://your-domain.example/student/payment/callback
MAIL_SERVER=smtp.your-provider.example
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=your-smtp-user
MAIL_PASSWORD=your-smtp-password
MAIL_DEFAULT_SENDER=noreply@your-domain.example
ENQUIRY_NOTIFICATION_EMAIL=academy-admin@your-domain.example
```

Use Paystack test credentials while validating checkout. Configure the Paystack webhook URL as `https://your-domain.example/student/payment/webhook`; the webhook verifies Paystack's signature using `PAYSTACK_SECRET_KEY`. Course access is granted only after the callback verification or signed webhook confirms the expected order reference, amount, and currency. Without a secret key, paid checkout does not grant access.

Private academy resource uploads are stored under `instance/uploads` by default, outside Flask's public static directory. Do not configure `UPLOAD_FOLDER` to a path inside `app/static`; the protected file workflow rejects that configuration.

# Axiom Gateway Consult

A full-stack Flask corporate website for Axiom Gateway Consult, including public pages, enquiry management, article and project CMS, secure admin authentication, and database-backed company settings.

## Tech stack

- Flask
- Flask-SQLAlchemy
- Flask-Migrate
- Flask-Login
- Flask-WTF
- SQLite for development; PostgreSQL-ready for production
- Jinja templates and custom CSS
- Pytest for automated verification

## Project structure

- app/ — application package
- app/templates/ — Jinja templates for public and admin pages
- app/static/ — CSS, JS, and image assets
- app/models.py — database models
- app/routes.py — public and admin routes
- app/forms.py — forms for contact, content, and settings
- tests/ — automated app tests

## Local installation

1. Create a virtual environment.
2. Install dependencies:
   
   pip install -r requirements.txt

3. Copy environment variables:
   
   cp .env.example .env

4. Update the environment file for your local setup.

## Database setup and migrations

Initialize and upgrade the database:

export FLASK_APP=wsgi.py
flask db init
flask db migrate -m "Initial schema"
flask db upgrade

The app also creates the tables automatically in non-migration contexts for local testing.

After pulling schema changes, apply them with `flask db upgrade`. The instructor portal adds an instructor application workflow, course ownership, certificates, notifications, audit records, earning ledger, and payout requests. For local use without migrations, set `AUTO_CREATE_DB=true`; normal application startup does not create or alter database tables.

## Instructor portal

Instructors apply at `/academy/instructor/register`. Administrators review applications and course submissions at `/admin/instructors`. Approved instructors can manage courses, enrolled students, admission certificates, analytics, notifications, and payout requests under `/academy/instructor/`. Paid course checkout uses the existing Paystack integration when `PAYSTACK_SECRET_KEY` is configured; without it, the existing bank-transfer receipt review remains available. Set an academy commission percentage in Company Settings before instructor net earnings are calculated. Configure SMTP to deliver application, decision, and payout email notices.

## Administrator bootstrap

To create the first administrator in a browser, set a private setup key in `.env`:

```dotenv
ADMIN_SETUP_KEY=use-a-long-random-secret
```

Then open `/admin/signup` and submit the setup key with the administrator's name, email, and password. Signup is disabled after the first administrator has been created, and is unavailable when `ADMIN_SETUP_KEY` is unset. Keep the setup key private and remove it from the environment after creating the account. Existing installations can still use the `flask create-admin` CLI command.

## Email configuration

Email delivery is configured through environment variables in the `.env` file:

- MAIL_SERVER
- MAIL_PORT
- MAIL_USE_TLS
- MAIL_USE_SSL
- MAIL_USERNAME
- MAIL_PASSWORD
- MAIL_DEFAULT_SENDER
- ENQUIRY_NOTIFICATION_EMAIL

If SMTP is not configured, enquiries are still stored and the app logs the delivery issue without exposing a false success message.

## Running tests

pytest -q

## Production startup

export FLASK_APP=wsgi.py
flask run --host 0.0.0.0 --port 8000

## Deployment notes

- Use a production database such as PostgreSQL.
- Set `APP_ENV=production` and `SECRET_KEY` securely.
- Set `CANONICAL_ORIGIN` to the live domain.
- Store mail credentials and secrets outside source control.
- Use HTTPS with secure cookies in production.

## Security notes

- Administrative routes are protected by login.
- Passwords are hashed using Werkzeug.
- CSRF protection is enabled on forms.
- Sensitive credentials remain in environment variables rather than source code.
- Published content is separated from draft content.

## Known gaps

- Contact details such as the office address and Instagram handle require final verification before publication by the company.
- The website is structured for production deployment but still needs live SMTP credentials and a final domain configuration before full production email delivery and search indexing are fully activated.
