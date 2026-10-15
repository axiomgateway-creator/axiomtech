from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from flask import Flask, render_template
from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

from .config import Config


db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
student_login_manager = LoginManager()
csrf = CSRFProtect()
mail = Mail()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
)


def load_user(user_id):
    from .models import AdminUser, Instructor, Student

    if not user_id:
        return None
    prefix, _, suffix = str(user_id).partition(":")
    if prefix == "student" and suffix.isdigit():
        return db.session.get(Student, int(suffix))
    if prefix == "admin" and suffix.isdigit():
        return db.session.get(AdminUser, int(suffix))
    if prefix == "instructor" and suffix.isdigit():
        return db.session.get(Instructor, int(suffix))
    if user_id.isdigit():
        return db.session.get(AdminUser, int(user_id))
    return None


def student_load_user(user_id):
    return load_user(user_id)


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    if app.config.get("TESTING"):
        app.config["WTF_CSRF_ENABLED"] = False

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.user_loader(load_user)
    login_manager.login_view = "admin.admin_login"
    student_login_manager.init_app(app)
    student_login_manager.user_loader(student_load_user)
    student_login_manager.login_view = "student.student_login"
    csrf.init_app(app)
    mail.init_app(app)
    limiter.init_app(app)

    from .routes import admin_bp, instructor_bp, public_bp, student_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(student_bp, url_prefix="/student")
    app.register_blueprint(instructor_bp)

    @app.context_processor
    def inject_context():
        from .models import CompanySettings, Service

        settings = CompanySettings.get_settings()
        services = Service.query.filter_by(published=True).order_by(Service.display_order.asc()).all()
        return {"company_settings": settings, "services": services}

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("public/404.html"), 404

    if app.config.get("TESTING") or app.config.get("AUTO_CREATE_DB", False):
        with app.app_context():
            db.create_all()

    return app
