import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    APP_ENV = os.getenv("APP_ENV", "development")
    AUTO_CREATE_DB = os.getenv("AUTO_CREATE_DB", "false").lower() == "true"
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    ADMIN_SETUP_KEY = os.getenv("ADMIN_SETUP_KEY")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///{base}".format(base=str(BASE_DIR / "instance" / "axiom.db")))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {}
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", str(BASE_DIR / "instance" / "uploads"))
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    CANONICAL_ORIGIN = os.getenv("CANONICAL_ORIGIN", "http://localhost:5000")
    MAIL_SERVER = os.getenv("MAIL_SERVER")
    MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "true").lower() == "true"
    MAIL_USE_SSL = os.getenv("MAIL_USE_SSL", "false").lower() == "true"
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_DEFAULT_SENDER", "noreply@axiomgateway.com")
    ENQUIRY_NOTIFICATION_EMAIL = os.getenv("ENQUIRY_NOTIFICATION_EMAIL", "axiomgateway@gmail.com")
    PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
    PAYSTACK_CALLBACK_URL = os.getenv("PAYSTACK_CALLBACK_URL")

    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True

    if APP_ENV == "production":
        SESSION_COOKIE_SECURE = True
    else:
        SESSION_COOKIE_SECURE = False
