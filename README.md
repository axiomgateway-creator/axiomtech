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

## Administrator bootstrap

Create an initial admin account with the CLI command:

export FLASK_APP=wsgi.py
flask create-admin

This command prompts for name, email, and password and stores a hashed password in the database.

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
