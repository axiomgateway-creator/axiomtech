from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import secrets
from io import BytesIO
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from werkzeug.utils import secure_filename

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import or_
from werkzeug.security import generate_password_hash

from . import csrf, db, limiter, mail
from .forms import AdminLoginForm, AdminRegistrationForm, ArticleForm, CompanySettingsForm, ContactForm, CourseForm, InstructorLoginForm, InstructorRegistrationForm, ProjectForm, StudentLoginForm, StudentRegistrationForm
from .models import (
    AcademyCertificate,
    AcademyOrder,
    AcademyProduct,
    AdminUser,
    Article,
    ArticleCategory,
    CompanySettings,
    Course,
    CourseCategory,
    CourseEnrollment,
    CourseLesson,
    LessonProgress,
    Enquiry,
    Instructor,
    InstructorAuditLog,
    InstructorEarning,
    InstructorNotification,
    InstructorPayoutAllocation,
    InstructorPayoutRequest,
    InstructorReversal,
    PaymentEvent,
    Quiz,
    QuizAttempt,
    QuizAnswer,
    QuizOption,
    QuizQuestion,
    Project,
    Service,
    Student,
)
from . import student_login_manager

public_bp = Blueprint("public", __name__)
admin_bp = Blueprint("admin", __name__)
student_bp = Blueprint("student", __name__)
instructor_bp = Blueprint("instructor", __name__, url_prefix="/academy/instructor")


def create_instructor_notification(instructor, category, message, target_url=None, event_key=None):
    if event_key and InstructorNotification.query.filter_by(event_key=event_key).first():
        return None
    notification = InstructorNotification(
        instructor=instructor,
        category=category,
        message=message,
        target_url=target_url,
        event_key=event_key,
    )
    db.session.add(notification)
    return notification


def write_instructor_audit(action, target_type, target_id=None, instructor_id=None, admin_id=None, details=None):
    db.session.add(InstructorAuditLog(
        instructor_id=instructor_id,
        admin_id=admin_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
    ))


def save_public_image(upload, subdirectory):
    filename = secure_filename(upload.filename or "")
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in {"jpg", "jpeg", "png", "webp"}:
        return None, "Choose a JPG, PNG, or WebP image."
    image_data = upload.stream.read(5 * 1024 * 1024 + 1)
    if len(image_data) > 5 * 1024 * 1024:
        return None, "Images must be 5 MB or smaller."
    try:
        from PIL import Image

        image = Image.open(BytesIO(image_data))
        image.verify()
    except Exception:
        return None, "The selected file is not a valid image."
    directory = Path(current_app.static_folder) / "uploads" / subdirectory
    directory.mkdir(parents=True, exist_ok=True)
    stored_name = f"{secrets.token_hex(16)}.{extension}"
    (directory / stored_name).write_bytes(image_data)
    return f"/static/uploads/{subdirectory}/{stored_name}", None


def sanitize_instructor_html(value):
    import bleach

    return bleach.clean(
        value or "",
        tags={"p", "br", "strong", "b", "em", "i", "ul", "ol", "li", "blockquote", "h2", "h3", "a"},
        attributes={"a": ["href", "title"]},
        protocols={"http", "https", "mailto"},
        strip=True,
    )


def valid_resource_signature(extension, content):
    signatures = {
        "pdf": content.startswith(b"%PDF-"),
        "jpg": content.startswith(b"\xff\xd8\xff"),
        "jpeg": content.startswith(b"\xff\xd8\xff"),
        "png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "doc": content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
        "ppt": content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
        "docx": content.startswith(b"PK\x03\x04"),
        "pptx": content.startswith(b"PK\x03\x04"),
    }
    return signatures.get(extension, False)


def payout_account_cipher():
    import base64
    import hashlib
    from cryptography.fernet import Fernet

    secret = current_app.config.get("SECRET_KEY")
    if not secret or secret == "dev-secret-key":
        raise RuntimeError("Set a unique SECRET_KEY before storing payout account details.")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def mask_payout_account(encrypted_value):
    if not encrypted_value:
        return None
    value = payout_account_cipher().decrypt(encrypted_value.encode("ascii")).decode("utf-8")
    return f"******{value[-4:]}"
def decrypt_payout_account(encrypted_value):
    if not encrypted_value:
        return ""
    return payout_account_cipher().decrypt(encrypted_value.encode("ascii")).decode("utf-8")


@instructor_bp.before_request
def require_instructor():
    public_endpoints = {"instructor.register", "instructor.login"}
    if request.endpoint in public_endpoints:
        if current_user.is_authenticated and not isinstance(current_user, Instructor):
            abort(403)
        return None
    if not current_user.is_authenticated:
        return redirect(url_for("instructor.login", next=request.url))
    if request.endpoint == "instructor.lesson_material" and isinstance(current_user, Student):
        return None
    if not isinstance(current_user, Instructor):
        abort(403)
    if current_user.status != "approved" and request.endpoint not in {"instructor.dashboard", "instructor.logout", "instructor.profile"}:
        abort(403)


@admin_bp.before_request
def restrict_admin_area():
    if request.endpoint in {"admin.admin_login", "admin.admin_signup"}:
        return None
    if not isinstance(current_user, AdminUser):
        if not current_user.is_authenticated:
            return redirect(url_for("admin.admin_login", next=request.url))
        abort(403)


def generate_reference():
    return Enquiry.next_reference()


def get_service_choices():
    return [(service.slug, service.name) for service in Service.query.filter_by(published=True).order_by(Service.display_order.asc()).all()]


def slugify(value):
    value = (value or "").strip().lower()
    return "".join(ch if ch.isalnum() else "-" for ch in value).replace("--", "-")


def send_mail(subject, recipients, body, html_body=None):
    if not current_app.config.get("MAIL_SERVER"):
        current_app.logger.warning("Email not configured: %s", subject)
        return False

    try:
        from flask_mail import Message

        msg = Message(subject, sender=current_app.config.get("MAIL_DEFAULT_SENDER"), recipients=recipients)
        msg.body = body
        if html_body:
            msg.html = html_body
        mail.send(msg)
        return True
    except Exception as exc:  # pragma: no cover - actual SMTP availability varies
        current_app.logger.exception("SMTP delivery failure: %s", exc)
        return False


def notify_admin_of_enquiry(enquiry):
    settings = CompanySettings.get_settings()
    recipient = settings.enquiry_notification_email or current_app.config.get("ENQUIRY_NOTIFICATION_EMAIL")
    if not recipient:
        return False
    body = (
        f"New enquiry from {enquiry.full_name} ({enquiry.email})\n"
        f"Reference: {enquiry.reference}\n"
        f"Service: {enquiry.service.name if enquiry.service else enquiry.enquiry_type}\n"
        f"Type: {enquiry.enquiry_type}\n"
        f"Phone: {enquiry.telephone}\n"
        f"Preferred contact: {enquiry.preferred_contact}\n\n"
        f"Description:\n{enquiry.description}"
    )
    return send_mail("New Axiom enquiry received", [recipient], body)


def send_confirmation_email(enquiry):
    if not enquiry.email:
        return False
    body = (
        "Thank you for contacting Axiom Gateway Consult.\n\n"
        f"Your enquiry reference is {enquiry.reference}.\n"
        "We will review your request and respond using your preferred contact method.\n"
        "Warm regards,\nAxiom Gateway Consult"
    )
    return send_mail("Axiom Gateway Consult enquiry received", [enquiry.email], body)


def send_academy_notice(subject, recipients, body):
    recipients = [recipient for recipient in recipients if recipient]
    return send_mail(subject, recipients, body) if recipients else False


def get_admin_notification_recipient():
    settings = CompanySettings.get_settings()
    return settings.enquiry_notification_email or current_app.config.get("ENQUIRY_NOTIFICATION_EMAIL")


def get_private_academy_upload_root():
    upload_root = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    static_root = Path(current_app.static_folder).resolve()
    if upload_root == static_root or static_root in upload_root.parents:
        raise RuntimeError("Academy uploads must be stored outside Flask's static directory.")
    return upload_root


def get_receipt_file(order):
    """Return a receipt only when its stored name resolves inside private storage."""
    upload_root = get_private_academy_upload_root()
    stored_name = Path(order.receipt_path or "")
    receipt_path = (stored_name if stored_name.is_absolute() else upload_root / stored_name).resolve()
    try:
        receipt_path.relative_to(upload_root)
    except ValueError:
        abort(404)
    if not receipt_path.is_file():
        abort(404)
    return receipt_path


def initialize_paystack_payment(order):
    secret_key = current_app.config.get("PAYSTACK_SECRET_KEY")
    if not secret_key:
        return None
    student = order.student
    payload = {
        "email": student.email,
        "amount": int(round(order.amount * 100)),
        "currency": order.currency,
        "reference": order.reference,
        "callback_url": current_app.config.get("PAYSTACK_CALLBACK_URL") or url_for("student.payment_callback", _external=True),
        "metadata": {"order_reference": order.reference, "student_id": student.id, "item_type": order.item_type},
    }
    request_object = Request(
        "https://api.paystack.co/transaction/initialize",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {secret_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request_object, timeout=15) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        current_app.logger.warning("Paystack initialization failed for order %s: %s", order.reference, exc)
        return None
    if not result.get("status") or not result.get("data", {}).get("authorization_url"):
        return None
    order.provider_reference = result["data"].get("reference")
    db.session.commit()
    return result["data"]["authorization_url"]


def verify_paystack_payment(reference):
    secret_key = current_app.config.get("PAYSTACK_SECRET_KEY")
    if not secret_key:
        return None
    request_object = Request(
        f"https://api.paystack.co/transaction/verify/{reference}",
        headers={"Authorization": f"Bearer {secret_key}"},
    )
    try:
        with urlopen(request_object, timeout=15) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        current_app.logger.warning("Paystack verification failed for reference %s: %s", reference, exc)
        return None
    if result.get("status") and result.get("data", {}).get("status") == "success":
        return result["data"]
    return None


def complete_paid_order(order, gateway_data):
    if order.status == "refunded":
        return False
    expected_amount = int(round(order.amount * 100))
    if gateway_data.get("reference") != order.reference or gateway_data.get("amount") != expected_amount or gateway_data.get("currency", "").upper() != order.currency.upper():
        current_app.logger.warning("Paystack amount/currency mismatch for order %s", order.reference)
        return False
    was_paid = order.status == "paid"
    order.status = "paid"
    order.provider_reference = gateway_data.get("reference") or order.provider_reference
    notification = None
    if order.item_type == "course":
        course = db.session.get(Course, order.item_id)
        if not course:
            return False
        enrolment = CourseEnrollment.query.filter_by(student_id=order.student_id, course_id=course.id).first()
        if enrolment:
            enrolment.order_id = order.id
            enrolment.status = "active"
            enrolment.source = "purchase"
        else:
            enrolment = CourseEnrollment(student_id=order.student_id, course_id=course.id, order_id=order.id, status="active", progress=0.0, source="purchase")
            db.session.add(enrolment)
        if course.instructor_id:
            record_instructor_earning(order, course, gateway_data)
            create_instructor_notification(
                course.instructor,
                "enrollment",
                f"A paid enrollment was confirmed for {course.title}.",
                url_for("instructor.students"),
                f"paid-enrollment-{order.id}",
            )
        notification = ("Axiom Academy course enrollment confirmed", order.student.email, f"Payment confirmed for {course.title}. Your course is ready in your student dashboard.")
    elif order.item_type == "product":
        product = db.session.get(AcademyProduct, order.item_id)
        if not product:
            return False
        notification = ("Axiom Academy resource purchase confirmed", order.student.email, f"Payment confirmed for {product.title}. Sign in to your dashboard to download your resource.")
    if not was_paid:
        db.session.add(PaymentEvent(
            order=order,
            provider="paystack",
            event_type="charge.success",
            status="verified",
            payload=json.dumps({"reference": gateway_data.get("reference"), "amount": gateway_data.get("amount"), "currency": gateway_data.get("currency")}),
        ))
    db.session.commit()
    if notification:
        send_academy_notice(notification[0], [notification[1]], notification[2])
    return True


def record_instructor_earning(order, course, gateway_data=None):
    if not course.instructor_id or InstructorEarning.query.filter_by(order_id=order.id).first():
        return None
    settings = CompanySettings.query.order_by(CompanySettings.id.desc()).first()
    commission_percent = settings.academy_commission_percent if settings else None
    if commission_percent is None or not 0 <= commission_percent <= 100:
        return None
    gross_kobo = int((Decimal(str(order.amount)) * 100).quantize(Decimal("1")))
    fees_kobo = max(0, int(gateway_data.get("fees") or 0)) if gateway_data else 0
    commission_kobo = int((Decimal(gross_kobo) * Decimal(str(commission_percent)) / 100).quantize(Decimal("1")))
    share_kobo = max(0, gross_kobo - fees_kobo - commission_kobo)
    earning = InstructorEarning(
        instructor_id=course.instructor_id,
        order_id=order.id,
        gross_kobo=gross_kobo,
        gateway_fee_kobo=fees_kobo,
        commission_kobo=commission_kobo,
        instructor_share_kobo=share_kobo,
    )
    db.session.add(earning)
    return earning


def reverse_instructor_earning(order, reason=None):
    earning = InstructorEarning.query.filter_by(order_id=order.id).first()
    if not earning or InstructorReversal.query.filter_by(order_id=order.id).first():
        return None
    if earning.payout_status != "available":
        return None
    reversal = InstructorReversal(
        order_id=order.id,
        instructor_id=earning.instructor_id,
        gross_reversed_kobo=earning.gross_kobo,
        commission_reversed_kobo=earning.commission_kobo,
        instructor_share_reversed_kobo=earning.instructor_share_kobo,
        reason=(reason or "Payment reversed")[:2000],
    )
    earning.payout_status = "reversed"
    db.session.add(reversal)
    create_instructor_notification(
        earning.instructor,
        "reversal",
        f"A payment for order {order.reference} was reversed.",
        url_for("instructor.earnings"),
        f"order-reversal-{order.id}",
    )
    write_instructor_audit("payment_reversed", "order", order.id, instructor_id=earning.instructor_id, details=reason)
    return reversal


def award_course_certificate(enrolment):
    course = enrolment.course
    total_lessons = CourseLesson.query.filter_by(course_id=course.id, status="published").count()
    completed_lessons = (
        LessonProgress.query.join(CourseLesson, LessonProgress.lesson_id == CourseLesson.id)
        .filter(
            LessonProgress.enrolment_id == enrolment.id,
            LessonProgress.completed.is_(True),
            CourseLesson.course_id == course.id,
            CourseLesson.status == "published",
        )
        .count()
    )
    if not course.certificate_eligible or not total_lessons or completed_lessons < total_lessons:
        return None
    certificate = AcademyCertificate.query.filter_by(student_id=enrolment.student_id, course_id=course.id, certificate_type="completion").first()
    if certificate:
        if certificate.status != "issued":
            certificate.status = "issued"
            certificate.revoked_at = None
            certificate.revoked_reason = None
        return certificate
    certificate = AcademyCertificate(
        student_id=enrolment.student_id,
        course_id=course.id,
        certificate_number=f"AXM-{course.id}-{secrets.token_hex(5).upper()}",
        verification_code=secrets.token_urlsafe(12),
            certificate_type="completion",
    )
    db.session.add(certificate)
    db.session.commit()
    send_academy_notice(
        "Your Axiom Academy certificate is ready",
        [enrolment.student.email],
        f"Congratulations on completing {course.title}. Certificate verification code: {certificate.verification_code}",
    )
    send_academy_notice(
        "Axiom Academy certificate issued",
        [get_admin_notification_recipient()],
        f"{enrolment.student.full_name} completed {course.title}. Certificate: {certificate.certificate_number}.",
    )
    return certificate


def recalculate_course_progress(course_id):
    """Recompute enrollment progress against the course's currently published lessons."""
    total_lessons = CourseLesson.query.filter_by(course_id=course_id, status="published").count()
    enrolments = CourseEnrollment.query.filter_by(course_id=course_id).all()
    for enrolment in enrolments:
        completed_lessons = (
            LessonProgress.query.join(CourseLesson, LessonProgress.lesson_id == CourseLesson.id)
            .filter(
                LessonProgress.enrolment_id == enrolment.id,
                LessonProgress.completed.is_(True),
                CourseLesson.course_id == course_id,
                CourseLesson.status == "published",
            )
            .count()
        )
        is_complete = bool(total_lessons and completed_lessons >= total_lessons)
        enrolment.progress = (completed_lessons / total_lessons) * 100 if total_lessons else 0.0
        if is_complete:
            if enrolment.completed_at is None:
                enrolment.completed_at = datetime.now(timezone.utc)
            award_course_certificate(enrolment)
        else:
            enrolment.completed_at = None
            certificate = AcademyCertificate.query.filter_by(
                student_id=enrolment.student_id,
                course_id=course_id,
                certificate_type="completion",
                status="issued",
            ).first()
            if certificate:
                certificate.status = "revoked"
                certificate.revoked_at = datetime.now(timezone.utc)
                certificate.revoked_reason = "Course published lessons changed."


@public_bp.route("/")
def home():
    services = Service.query.filter_by(published=True).order_by(Service.display_order.asc()).all()
    recent_articles = Article.query.filter_by(status="published").order_by(Article.published_at.desc().nullslast()).limit(3).all()
    projects = Project.query.filter_by(status="published").order_by(Project.published_at.desc().nullslast()).limit(3).all()
    featured_courses = Course.query.filter_by(status="published").order_by(
        Course.is_featured.desc(),
        Course.published_at.desc().nullslast(),
    ).limit(2).all()
    return render_template(
        "public/home.html",
        services=services,
        recent_articles=recent_articles,
        projects=projects,
        featured_courses=featured_courses,
    )


@public_bp.route("/academy")
def academy_home():
    categories = CourseCategory.query.join(Course).filter(Course.status == "published").distinct().order_by(CourseCategory.name.asc()).all()
    featured_courses = Course.query.filter_by(status="published").order_by(Course.is_featured.desc(), Course.published_at.desc().nullslast()).limit(3).all()
    recent_courses = Course.query.filter_by(status="published").order_by(Course.published_at.desc().nullslast()).limit(3).all()
    products = AcademyProduct.query.filter_by(status="published").order_by(AcademyProduct.published_at.desc().nullslast()).limit(3).all()
    search_query = request.args.get("q", "")
    return render_template("public/academy_home.html", categories=categories, featured_courses=featured_courses, recent_courses=recent_courses, products=products, search_query=search_query)


@public_bp.route("/academy/courses")
def academy_courses():
    page = request.args.get("page", 1, type=int)
    q = request.args.get("q", "")
    category = request.args.get("category", "")
    query = Course.query.filter_by(status="published")
    if q:
        query = query.filter(or_(Course.title.ilike(f"%{q}%"), Course.short_description.ilike(f"%{q}%"), Course.description.ilike(f"%{q}%")))
    if category:
        query = query.filter_by(category_id=category)
    courses = query.order_by(Course.published_at.desc().nullslast()).paginate(page=page, per_page=6, error_out=False)
    categories = CourseCategory.query.order_by(CourseCategory.name.asc()).all()
    return render_template("public/academy_courses.html", courses=courses, categories=categories, q=q, category=category)


@public_bp.route("/academy/courses/<slug>")
def academy_course_detail(slug):
    course = Course.query.filter_by(slug=slug, status="published").first_or_404()
    lessons = CourseLesson.query.filter_by(course_id=course.id, status="published").order_by(CourseLesson.order_index.asc(), CourseLesson.id.asc()).all()
    enrolled = False
    payment_order = None
    if current_user.is_authenticated and isinstance(current_user, Student):
        enrolled = CourseEnrollment.query.filter_by(student_id=current_user.id, course_id=course.id, status="active").first() is not None
        payment_order = AcademyOrder.query.filter_by(student_id=current_user.id, item_type="course", item_id=course.id).order_by(AcademyOrder.created_at.desc()).first()
    return render_template("public/course_detail.html", course=course, lessons=lessons, enrolled=enrolled, payment_order=payment_order)


@public_bp.route("/academy/products")
def academy_products():
    products = AcademyProduct.query.filter_by(status="published").order_by(AcademyProduct.published_at.desc().nullslast()).all()
    return render_template("public/academy_products.html", products=products)


@public_bp.route("/academy/products/<slug>")
def academy_product_detail(slug):
    product = AcademyProduct.query.filter_by(slug=slug, status="published").first_or_404()
    purchased = False
    if current_user.is_authenticated and isinstance(current_user, Student):
        purchased = AcademyOrder.query.filter_by(student_id=current_user.id, item_type="product", item_id=product.id, status="paid").first() is not None
    return render_template("public/product_detail.html", product=product, purchased=purchased)


@public_bp.route("/academy/certificates/verify", methods=["GET", "POST"])
def verify_certificate():
    cert = None
    result = None
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        cert = AcademyCertificate.query.filter(
            (AcademyCertificate.verification_code == code)
            | (AcademyCertificate.certificate_number == code)
        ).first()
        if cert and cert.status == "issued":
            result = "valid"
        elif cert and cert.status == "revoked":
            result = "revoked"
        else:
            result = "invalid"
    elif request.args.get("code"):
        code = request.args.get("code", "").strip()
        cert = AcademyCertificate.query.filter(
            (AcademyCertificate.verification_code == code)
            | (AcademyCertificate.certificate_number == code)
        ).first()
        if cert and cert.status == "issued":
            result = "valid"
        elif cert and cert.status == "revoked":
            result = "revoked"
        else:
            result = "invalid"
    return render_template("public/certificate_verify.html", cert=cert, result=result)


@public_bp.route("/about")
def about():
    return render_template("public/about.html")


@public_bp.route("/services")
def services():
    services_list = Service.query.filter_by(published=True).order_by(Service.display_order.asc()).all()
    return render_template("public/services.html", services=services_list)


@public_bp.route("/services/<slug>")
def service_detail(slug):
    service = Service.query.filter_by(slug=slug, published=True).first_or_404()
    return render_template("public/service_detail.html", service=service)


@public_bp.route("/who-we-serve")
def who_we_serve():
    return render_template("public/who_we_serve.html")


@public_bp.route("/projects")
def projects():
    page = request.args.get("page", 1, type=int)
    q = request.args.get("q", "")
    category = request.args.get("category", "")
    query = Project.query.filter_by(status="published")
    if q:
        query = query.filter(or_(Project.title.ilike(f"%{q}%"), Project.summary.ilike(f"%{q}%")))
    if category:
        query = query.filter(Project.category == category)
    projects_list = query.order_by(Project.published_at.desc().nullslast()).paginate(page=page, per_page=6, error_out=False)
    categories = [project.category for project in Project.query.filter_by(status="published").all() if project.category]
    categories = sorted(set(categories))
    return render_template("public/projects.html", projects=projects_list, categories=categories, q=q, category=category)


@public_bp.route("/projects/<slug>")
def project_detail(slug):
    project = Project.query.filter_by(slug=slug, status="published").first_or_404()
    return render_template("public/project_detail.html", project=project)


@public_bp.route("/insights")
def insights():
    page = request.args.get("page", 1, type=int)
    category_slug = request.args.get("category", "")
    q = request.args.get("q", "")
    query = Article.query.filter_by(status="published")
    if category_slug:
        category = ArticleCategory.query.filter_by(slug=category_slug).first()
        if category:
            query = query.filter_by(category_id=category.id)
    if q:
        query = query.filter(or_(Article.title.ilike(f"%{q}%"), Article.excerpt.ilike(f"%{q}%"), Article.body.ilike(f"%{q}%")))
    articles = query.order_by(Article.published_at.desc().nullslast()).paginate(page=page, per_page=6, error_out=False)
    categories = ArticleCategory.query.order_by(ArticleCategory.name.asc()).all()
    return render_template("public/insights.html", articles=articles, categories=categories, q=q, category_slug=category_slug)


@public_bp.route("/insights/<slug>")
def article_detail(slug):
    article = Article.query.filter_by(slug=slug, status="published").first_or_404()
    related = Article.query.filter(Article.id != article.id, Article.status == "published").order_by(Article.published_at.desc().nullslast()).limit(3).all()
    return render_template("public/article_detail.html", article=article, related=related)


@public_bp.route("/contact", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def contact():
    form = ContactForm()
    form.service.choices = get_service_choices()
    if request.method == "POST":
        if form.validate_on_submit():
            selected_service = Service.query.filter_by(slug=form.service.data, published=True).first()
            enquiry = Enquiry(
                reference=generate_reference(),
                full_name=form.full_name.data.strip(),
                organization=form.organization.data.strip() or None,
                email=form.email.data.strip(),
                telephone=form.telephone.data.strip(),
                service=selected_service,
                enquiry_type=form.enquiry_type.data,
                description=form.description.data.strip(),
                preferred_contact=form.preferred_contact.data,
                consent=bool(form.consent.data),
                status="New",
            )
            db.session.add(enquiry)
            db.session.commit()

            admin_success = notify_admin_of_enquiry(enquiry)
            visitor_success = send_confirmation_email(enquiry)

            flash(
                "Your enquiry has been submitted successfully. "
                + (f"Reference: {enquiry.reference}. " if enquiry.reference else "")
                + ("Our team will contact you shortly." if admin_success or visitor_success else "We have saved your enquiry and will follow up once email services are configured."),
                "success",
            )
            return redirect(url_for("public.contact"))
    return render_template("public/contact.html", form=form)


@student_bp.route("/register", methods=["GET", "POST"])
def student_register():
    if current_user.is_authenticated:
        return redirect(url_for("student.dashboard"))
    form = StudentRegistrationForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if Student.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
            return render_template("student/register.html", form=form)
        student = Student(full_name=form.full_name.data.strip(), email=email, phone=form.phone.data.strip() or None)
        student.set_password(form.password.data)
        student.is_verified = not current_app.config.get("MAIL_SERVER")
        db.session.add(student)
        db.session.commit()
        if student.is_verified:
            login_user(student, remember=True)
            flash("Registration successful. Welcome to Axiom Academy.", "success")
            return redirect(url_for("student.dashboard"))
        flash("Registration successful. Please verify your email to continue.", "success")
        return redirect(url_for("student.student_login"))
    return render_template("student/register.html", form=form)


@student_bp.route("/login", methods=["GET", "POST"])
def student_login():
    if current_user.is_authenticated:
        return redirect(url_for("student.dashboard"))
    form = StudentLoginForm()
    if form.validate_on_submit():
        student = Student.query.filter_by(email=form.email.data.strip().lower()).first()
        if student and student.check_password(form.password.data) and student.is_active_account:
            login_user(student, remember=form.remember.data)
            student.last_login_at = datetime.now(timezone.utc)
            db.session.commit()
            flash("Welcome back to Axiom Academy.", "success")
            return redirect(url_for("student.dashboard"))
        flash("Invalid login credentials.", "error")
    return render_template("student/login.html", form=form)


@student_bp.route("/logout")
@login_required
def student_logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("public.academy_home"))


@student_bp.route("/dashboard")
@login_required
def dashboard():
    if not isinstance(current_user, Student):
        flash("Please sign in to access the student dashboard.", "error")
        return redirect(url_for("student.student_login"))
    enrolments = CourseEnrollment.query.filter_by(student_id=current_user.id).order_by(CourseEnrollment.created_at.desc()).all()
    orders = AcademyOrder.query.filter_by(student_id=current_user.id).order_by(AcademyOrder.created_at.desc()).all()
    certificates = AcademyCertificate.query.filter_by(student_id=current_user.id).order_by(AcademyCertificate.issue_date.desc()).all()
    product_orders = AcademyOrder.query.filter_by(student_id=current_user.id, item_type="product", status="paid").order_by(AcademyOrder.created_at.desc()).all()
    active_courses = Course.query.filter(Course.id.in_([e.course_id for e in enrolments])).all()
    return render_template("student/dashboard.html", enrolments=enrolments, orders=orders, certificates=certificates, product_orders=product_orders, active_courses=active_courses)


@student_bp.route("/my-courses")
@login_required
def my_courses():
    if not isinstance(current_user, Student):
        abort(403)
    enrolments = CourseEnrollment.query.filter_by(student_id=current_user.id).order_by(CourseEnrollment.updated_at.desc()).all()
    return render_template("student/my_courses.html", enrolments=enrolments)


@student_bp.route("/orders")
@login_required
def student_orders():
    if not isinstance(current_user, Student):
        abort(403)
    orders = AcademyOrder.query.filter_by(student_id=current_user.id).order_by(AcademyOrder.created_at.desc()).all()
    course_ids = {order.item_id for order in orders if order.item_type == "course"}
    order_courses = {course.id: course for course in Course.query.filter(Course.id.in_(course_ids)).all()} if course_ids else {}
    return render_template("student/orders.html", orders=orders, order_courses=order_courses)


@student_bp.route("/certificates")
@login_required
def student_certificates():
    if not isinstance(current_user, Student):
        abort(403)
    certificates = AcademyCertificate.query.filter_by(
        student_id=current_user.id,
        status="issued",
    ).order_by(AcademyCertificate.issue_date.desc()).all()
    return render_template("student/certificates.html", certificates=certificates)


@student_bp.route("/certificates/<int:certificate_id>.pdf")
@login_required
def student_certificate_pdf(certificate_id):
    if not isinstance(current_user, Student):
        abort(403)
    certificate = AcademyCertificate.query.filter_by(
        id=certificate_id,
        student_id=current_user.id,
        status="issued",
    ).first_or_404()
    return certificate_pdf_response(certificate)


@student_bp.route("/courses/<slug>")
@login_required
def student_course_detail(slug):
    if not isinstance(current_user, Student):
        return redirect(url_for("student.student_login"))
    course = Course.query.filter_by(slug=slug, status="published").first_or_404()
    enrolment = CourseEnrollment.query.filter_by(student_id=current_user.id, course_id=course.id).first()
    if not enrolment or enrolment.status != "active":
        flash("You are not enrolled in this course.", "error")
        return redirect(url_for("public.academy_course_detail", slug=slug))
    lessons = CourseLesson.query.filter_by(course_id=course.id, status="published").order_by(CourseLesson.order_index.asc(), CourseLesson.id.asc()).all()
    requested_lesson_id = request.args.get("lesson_id", type=int)
    selected_lesson = next(
        (lesson for lesson in lessons if lesson.id == requested_lesson_id),
        None,
    )
    if selected_lesson is None:
        selected_lesson = next(
            (lesson for lesson in lessons if lesson.id == enrolment.last_lesson_id),
            None,
        )
    if selected_lesson is None:
        selected_lesson = next(
            (
                lesson
                for lesson in lessons
                if not any(
                    entry.lesson_id == lesson.id and entry.completed
                    for entry in enrolment.lesson_progress
                )
            ),
            lessons[0] if lessons else None,
        )
    if selected_lesson:
        accessed_at = datetime.now(timezone.utc)
        lesson_progress = LessonProgress.query.filter_by(
            enrolment_id=enrolment.id,
            lesson_id=selected_lesson.id,
        ).first()
        if not lesson_progress:
            lesson_progress = LessonProgress(
                enrolment_id=enrolment.id,
                student_id=current_user.id,
                lesson_id=selected_lesson.id,
            )
            db.session.add(lesson_progress)
        lesson_progress.updated_at = accessed_at
        enrolment.last_lesson_id = selected_lesson.id
        enrolment.updated_at = accessed_at
        db.session.commit()
    progress_by_lesson = {entry.lesson_id: entry for entry in enrolment.lesson_progress}
    quizzes = Quiz.query.filter_by(course_id=course.id, status="published").order_by(Quiz.id.asc()).all()
    return render_template(
        "student/course_detail.html",
        course=course,
        enrolment=enrolment,
        lessons=lessons,
        progress_by_lesson=progress_by_lesson,
        quizzes=quizzes,
        current_lesson_id=selected_lesson.id if selected_lesson else None,
    )


@student_bp.route("/courses/<slug>/lessons/<int:lesson_id>/complete", methods=["POST"])
@login_required
def complete_lesson(slug, lesson_id):
    if not isinstance(current_user, Student):
        abort(403)
    course = Course.query.filter_by(slug=slug, status="published").first_or_404()
    enrolment = CourseEnrollment.query.filter_by(student_id=current_user.id, course_id=course.id, status="active").first_or_404()
    lesson = CourseLesson.query.filter_by(id=lesson_id, course_id=course.id, status="published").first_or_404()
    progress = LessonProgress.query.filter_by(enrolment_id=enrolment.id, lesson_id=lesson.id).first()
    if not progress:
        progress = LessonProgress(enrolment_id=enrolment.id, student_id=current_user.id, lesson_id=lesson.id)
        db.session.add(progress)
    accessed_at = datetime.now(timezone.utc)
    if not progress.completed:
        progress.completed = True
        progress.completed_at = accessed_at
    progress.updated_at = accessed_at
    enrolment.last_lesson_id = lesson.id
    enrolment.updated_at = accessed_at
    recalculate_course_progress(course.id)
    db.session.commit()
    flash("Lesson progress saved.", "success")
    return redirect(url_for("student.student_course_detail", slug=slug))


@student_bp.route("/quizzes/<int:quiz_id>", methods=["GET", "POST"])
@login_required
def take_quiz(quiz_id):
    if not isinstance(current_user, Student):
        abort(403)
    quiz = Quiz.query.filter_by(id=quiz_id, status="published").first_or_404()
    course = db.session.get(Course, quiz.course_id) if quiz.course_id else None
    if not course and quiz.lesson_id:
        lesson = db.session.get(CourseLesson, quiz.lesson_id)
        course = lesson.course if lesson else None
    if not course:
        abort(404)
    enrolment = CourseEnrollment.query.filter_by(student_id=current_user.id, course_id=course.id, status="active").first_or_404()
    attempts_used = QuizAttempt.query.filter_by(quiz_id=quiz.id, student_id=current_user.id).count()
    if request.method == "POST":
        if quiz.attempt_limit and attempts_used >= quiz.attempt_limit:
            flash("You have used all attempts for this assessment.", "error")
            return redirect(url_for("student.student_course_detail", slug=course.slug))
        questions = QuizQuestion.query.filter_by(quiz_id=quiz.id).order_by(QuizQuestion.order_index.asc(), QuizQuestion.id.asc()).all()
        total_points = sum(max(0.0, question.points or 0.0) for question in questions)
        earned_points = 0.0
        attempt = QuizAttempt(quiz_id=quiz.id, student_id=current_user.id, status="submitted", submitted_at=datetime.now(timezone.utc))
        db.session.add(attempt)
        db.session.flush()
        for question in questions:
            selected_value = request.form.get(f"question_{question.id}", "")
            selected_option = next((option for option in question.options if str(option.id) == selected_value), None)
            if selected_option:
                correct_option = next((option for option in question.options if option.is_correct), None)
                if correct_option and selected_option.id == correct_option.id:
                    earned_points += max(0.0, question.points or 0.0)
            db.session.add(QuizAnswer(
                attempt_id=attempt.id,
                question_id=question.id,
                selected_option_ids=json.dumps([selected_option.id] if selected_option else []),
            ))
        attempt.score = (earned_points / total_points * 100) if total_points else 0.0
        attempt.passed = attempt.score >= (quiz.pass_mark or 0.0)
        db.session.commit()
        flash("Assessment submitted.", "success")
        return redirect(url_for("student.take_quiz", quiz_id=quiz.id, result=attempt.id))
    result_id = request.args.get("result", type=int)
    result = QuizAttempt.query.filter_by(id=result_id, quiz_id=quiz.id, student_id=current_user.id).first() if result_id else None
    questions = QuizQuestion.query.filter_by(quiz_id=quiz.id).order_by(QuizQuestion.order_index.asc(), QuizQuestion.id.asc()).all()
    return render_template("student/quiz.html", quiz=quiz, course=course, questions=questions, attempts_used=attempts_used, result=result)


@student_bp.route("/checkout/<int:course_id>", methods=["POST"])
@login_required
def checkout_course(course_id):
    if not isinstance(current_user, Student):
        flash("Student login required.", "error")
        return redirect(url_for("student.student_login"))
    course = Course.query.get_or_404(course_id)
    if course.status != "published":
        flash("This course is unavailable.", "error")
        return redirect(url_for("public.academy_courses"))
    existing_enrolment = CourseEnrollment.query.filter_by(student_id=current_user.id, course_id=course.id).first()
    if existing_enrolment and existing_enrolment.status == "active":
        flash("You are already enrolled in this course.", "error")
        return redirect(url_for("student.dashboard"))
    if course.is_free:
        enrolment = existing_enrolment or CourseEnrollment(
            student_id=current_user.id,
            course_id=course.id,
            status="active",
            progress=0.0,
            source="free",
        )
        enrolment.status = "active"
        enrolment.source = "free"
        db.session.add(enrolment)
        if course.instructor:
            create_instructor_notification(
                course.instructor,
                "enrollment",
                f"A student enrolled in your free course, {course.title}.",
                url_for("instructor.students"),
                f"free-enrollment-{current_user.id}-{course.id}",
            )
        db.session.commit()
        flash("You are enrolled. The course is ready in your dashboard.", "success")
        return redirect(url_for("student.student_course_detail", slug=course.slug))
    order = AcademyOrder.query.filter_by(student_id=current_user.id, item_type="course", item_id=course.id).filter(AcademyOrder.status.in_(["pending", "awaiting_receipt", "receipt_submitted", "rejected"])).order_by(AcademyOrder.created_at.desc()).first()
    if not order:
        order = AcademyOrder(
            student_id=current_user.id, item_type="course", item_id=course.id,
            amount=course.price, currency=course.currency,
            status="pending" if current_app.config.get("PAYSTACK_SECRET_KEY") else "awaiting_receipt",
            reference=f"AXM-{secrets.token_hex(12).upper()}",
        )
        db.session.add(order)
        db.session.commit()
    if current_app.config.get("PAYSTACK_SECRET_KEY") and order.status in {"pending", "awaiting_receipt"}:
        authorization_url = initialize_paystack_payment(order)
        if authorization_url:
            return redirect(authorization_url)
        order.status = "awaiting_receipt"
        db.session.commit()
    return redirect(url_for("student.submit_course_receipt", order_id=order.id))


@student_bp.route("/orders/<int:order_id>/receipt", methods=["GET", "POST"])
@login_required
def submit_course_receipt(order_id):
    if not isinstance(current_user, Student):
        abort(403)
    order = AcademyOrder.query.filter_by(id=order_id, student_id=current_user.id, item_type="course").first_or_404()
    if order.status == "paid":
        course = db.session.get(Course, order.item_id)
        return redirect(url_for("student.student_course_detail", slug=course.slug))
    course = db.session.get(Course, order.item_id)
    if not course:
        abort(404)
    if request.method == "POST":
        upload = request.files.get("receipt")
        filename = secure_filename(upload.filename or "") if upload else ""
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if not filename or extension not in {"jpg", "jpeg", "png", "pdf"}:
            flash("Upload a clear JPG, PNG, or PDF payment receipt.", "error")
            return redirect(url_for("student.submit_course_receipt", order_id=order.id))
        upload_root = get_private_academy_upload_root()
        upload_root.mkdir(parents=True, exist_ok=True)
        stored_name = f"receipts/{order.reference}_{secrets.token_hex(10)}.{extension}"
        receipt_path = upload_root / stored_name
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        upload.save(receipt_path)
        order.receipt_path = stored_name
        order.receipt_uploaded_at = datetime.now(timezone.utc)
        order.receipt_reviewed_at = None
        order.receipt_review_note = None
        order.reviewed_by_admin_id = None
        order.status = "receipt_submitted"
        db.session.commit()
        send_academy_notice("Course payment receipt submitted", [get_admin_notification_recipient()], f"Receipt submitted for {course.title}. Order: {order.reference}. Review it in the Axiom admin panel.")
        flash("Your receipt has been submitted. Course access opens after admin approval.", "success")
        return redirect(url_for("student.student_orders"))
    return render_template("student/receipt_submission.html", order=order, course=course)


@student_bp.route("/payment/callback")
@login_required
def payment_callback():
    if not isinstance(current_user, Student):
        abort(403)
    reference = request.args.get("reference", "").strip()
    order = AcademyOrder.query.filter_by(reference=reference, student_id=current_user.id).first_or_404()
    if order.status != "paid":
        gateway_data = verify_paystack_payment(reference)
        if not gateway_data or not complete_paid_order(order, gateway_data):
            flash("Payment is not confirmed yet. No course access has been granted.", "error")
            return redirect(url_for("student.dashboard"))
    flash("Payment confirmed. Your purchase is ready.", "success")
    if order.item_type == "course":
        course = db.session.get(Course, order.item_id)
        return redirect(url_for("student.student_course_detail", slug=course.slug))
    return redirect(url_for("student.dashboard"))


@student_bp.route("/payment/webhook", methods=["POST"])
@csrf.exempt
def payment_webhook():
    secret_key = current_app.config.get("PAYSTACK_SECRET_KEY")
    signature = request.headers.get("x-paystack-signature", "")
    expected_signature = hmac.new((secret_key or "").encode(), request.get_data(), hashlib.sha512).hexdigest()
    if not secret_key or not hmac.compare_digest(signature, expected_signature):
        abort(401)
    payload = request.get_json(silent=True) or {}
    if payload.get("event") != "charge.success":
        return "ignored", 200
    data = payload.get("data", {})
    reference = data.get("reference")
    order = AcademyOrder.query.filter_by(reference=reference).first()
    if not order:
        return "unknown order", 404
    if order.status != "paid" and not complete_paid_order(order, data):
        return "payment mismatch", 400
    return "ok", 200


@student_bp.route("/products/<int:product_id>/checkout", methods=["POST"])
@login_required
def checkout_product(product_id):
    if not isinstance(current_user, Student):
        abort(403)
    product = AcademyProduct.query.filter_by(id=product_id, status="published").first_or_404()
    if AcademyOrder.query.filter_by(student_id=current_user.id, item_type="product", item_id=product.id, status="paid").first():
        return redirect(url_for("student.download_product", product_id=product.id))
    order = AcademyOrder(
        student_id=current_user.id,
        item_type="product",
        item_id=product.id,
        product_id=product.id,
        amount=0.0 if product.is_free else product.price,
        currency=product.currency,
        status="paid" if product.is_free else "pending",
        reference=f"AXM-{secrets.token_hex(12).upper()}",
    )
    db.session.add(order)
    db.session.commit()
    if product.is_free:
        return redirect(url_for("student.download_product", product_id=product.id))
    authorization_url = initialize_paystack_payment(order)
    if not authorization_url:
        flash("Payment could not be started. Please try again later.", "error")
        return redirect(url_for("public.academy_product_detail", slug=product.slug))
    return redirect(authorization_url)


@student_bp.route("/products/<int:product_id>/download")
@login_required
def download_product(product_id):
    if not isinstance(current_user, Student):
        abort(403)
    product = AcademyProduct.query.filter_by(id=product_id, status="published").first_or_404()
    paid_order = AcademyOrder.query.filter_by(student_id=current_user.id, item_type="product", item_id=product.id, status="paid").first()
    if not paid_order:
        abort(403)
    upload_root = get_private_academy_upload_root()
    requested_path = Path(product.file_path or "")
    file_path = (requested_path if requested_path.is_absolute() else upload_root / requested_path).resolve()
    try:
        file_path.relative_to(upload_root)
    except ValueError:
        abort(404)
    if not file_path.is_file():
        abort(404)
    return send_file(file_path, as_attachment=True, download_name=file_path.name)


@public_bp.route("/privacy")
def privacy():
    return render_template("public/privacy.html")


@public_bp.route("/terms")
def terms():
    return render_template("public/terms.html")


@public_bp.route("/robots.txt")
def robots_txt():
    return "User-agent: *\nAllow: /\nDisallow: /admin\nSitemap: " + current_app.config.get("CANONICAL_ORIGIN", "http://localhost:5000") + "/sitemap.xml\n", 200, {"Content-Type": "text/plain"}


@public_bp.route("/sitemap.xml")
def sitemap_xml():
    origin = current_app.config.get("CANONICAL_ORIGIN", "http://localhost:5000")
    urls = [
        "",
        "/about",
        "/services",
        "/who-we-serve",
        "/projects",
        "/insights",
        "/contact",
        "/privacy",
        "/terms",
    ]
    for service in Service.query.filter_by(published=True).all():
        urls.append(f"/services/{service.slug}")
    for article in Article.query.filter_by(status="published").all():
        urls.append(f"/insights/{article.slug}")
    for project in Project.query.filter_by(status="published").all():
        urls.append(f"/projects/{project.slug}")
    body = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"
    for path in urls:
        body += f"<url><loc>{origin}{path}</loc></url>"
    body += "</urlset>"
    return body, 200, {"Content-Type": "application/xml"}


@instructor_bp.route("/register", methods=["GET", "POST"])
def register():
    form = InstructorRegistrationForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if (Instructor.query.filter_by(email=email).first()
                or Student.query.filter_by(email=email).first()
                or AdminUser.query.filter_by(email=email).first()):
            form.email.errors.append("An account with this email already exists.")
        else:
            photo_url = None
            photo_upload = request.files.get("profile_photo")
            if photo_upload and photo_upload.filename:
                photo_url, upload_error = save_public_image(photo_upload, "instructor-profiles")
                if upload_error:
                    flash(upload_error, "error")
                    return render_template("instructor/register.html", form=form)
            instructor = Instructor(
                full_name=form.full_name.data.strip(),
                email=email,
                phone=form.phone.data.strip() or None,
                professional_title=form.professional_title.data.strip(),
                biography=form.biography.data.strip(),
                teaching_experience=form.teaching_experience.data.strip() or None,
                qualifications=form.qualifications.data.strip() or None,
                subject_areas=form.subject_areas.data.strip(),
                profile_photo=photo_url,
                terms_accepted_at=datetime.now(timezone.utc),
            )
            instructor.set_password(form.password.data)
            db.session.add(instructor)
            db.session.flush()
            write_instructor_audit("application_submitted", "instructor", instructor.id, instructor_id=instructor.id)
            db.session.commit()
            send_academy_notice(
                "New Axiom Academy instructor application",
                [get_admin_notification_recipient()],
                f"Instructor application submitted by {instructor.full_name} ({instructor.email}). Review it in the admin instructor portal.",
            )
            login_user(instructor, remember=True)
            flash("Your instructor application is submitted and awaiting review.", "success")
            return redirect(url_for("instructor.dashboard"))
    return render_template("instructor/register.html", form=form)


@instructor_bp.route("/login", methods=["GET", "POST"])
def login():
    form = InstructorLoginForm()
    if form.validate_on_submit():
        instructor = Instructor.query.filter_by(email=form.email.data.strip().lower()).first()
        if instructor and instructor.check_password(form.password.data) and instructor.status not in {"rejected", "suspended"}:
            login_user(instructor, remember=form.remember.data)
            instructor.last_login_at = datetime.now(timezone.utc)
            db.session.commit()
            return redirect(url_for("instructor.dashboard"))
        flash("Invalid instructor login credentials.", "error")
    return render_template("instructor/login.html", form=form)


@instructor_bp.route("/logout")
@login_required
def logout():
    if not isinstance(current_user, Instructor):
        abort(403)
    logout_user()
    return redirect(url_for("public.academy_home"))


@instructor_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()[:160]
        email = request.form.get("email", "").strip().lower()[:160]
        if not full_name or not email:
            flash("Full name and email are required.", "error")
        elif (
            Instructor.query.filter(Instructor.email == email, Instructor.id != current_user.id).first()
            or Student.query.filter_by(email=email).first()
            or AdminUser.query.filter_by(email=email).first()
        ):
            flash("That email address is already assigned to another account.", "error")
        else:
            current_user.full_name = full_name
            current_user.email = email
            current_user.phone = request.form.get("phone", "").strip()[:60] or None
            current_user.professional_title = request.form.get("professional_title", "").strip()[:160]
            current_user.biography = request.form.get("biography", "").strip()[:3000]
            current_user.teaching_experience = request.form.get("teaching_experience", "").strip()[:3000] or None
            current_user.qualifications = request.form.get("qualifications", "").strip()[:3000] or None
            current_user.subject_areas = request.form.get("subject_areas", "").strip()[:2000]
            photo_upload = request.files.get("profile_photo")
            if photo_upload and photo_upload.filename:
                photo_url, upload_error = save_public_image(photo_upload, "instructor-profiles")
                if upload_error:
                    flash(upload_error, "error")
                    return render_template("instructor/profile.html", instructor=current_user)
                current_user.profile_photo = photo_url
            write_instructor_audit("profile_updated", "instructor", current_user.id, instructor_id=current_user.id)
            db.session.commit()
            flash("Profile updated.", "success")
            return redirect(url_for("instructor.profile"))
    return render_template("instructor/profile.html", instructor=current_user)


@instructor_bp.route("/dashboard")
@login_required
def dashboard():
    if not isinstance(current_user, Instructor):
        abort(403)
    if current_user.status != "approved":
        return render_template("instructor/pending.html", instructor=current_user)
    courses = Course.query.filter_by(instructor_id=current_user.id).all()
    course_ids = [course.id for course in courses]
    enrollments = CourseEnrollment.query.filter(CourseEnrollment.course_id.in_(course_ids)).all() if course_ids else []
    earnings = InstructorEarning.query.filter_by(instructor_id=current_user.id).all()
    reversals = InstructorReversal.query.filter_by(instructor_id=current_user.id).all()
    paid_orders = AcademyOrder.query.filter(
        AcademyOrder.item_type == "course",
        AcademyOrder.item_id.in_(course_ids),
        AcademyOrder.status == "paid",
    ).all() if course_ids else []
    recent_enrollments = sorted(enrollments, key=lambda item: item.created_at, reverse=True)[:8]
    recent_orders = AcademyOrder.query.filter(AcademyOrder.item_type == "course", AcademyOrder.item_id.in_(course_ids)).order_by(AcademyOrder.created_at.desc()).limit(8).all() if course_ids else []
    unread_count = InstructorNotification.query.filter_by(instructor_id=current_user.id, is_read=False).count()
    metrics = {
        "courses": len(courses),
        "published": sum(course.status == "published" for course in courses),
        "drafts": sum(course.status == "draft" for course in courses),
        "awaiting_review": sum(course.review_status == "submitted" for course in courses),
        "enrollments": len(enrollments),
        "new_students": len({item.student_id for item in enrollments if item.created_at and (datetime.now(timezone.utc).replace(tzinfo=None) - item.created_at.replace(tzinfo=None)).days < 30}),
        "gross_sales_kobo": sum(int((Decimal(str(order.amount)) * 100).quantize(Decimal("1"))) for order in paid_orders),
        "earnings_kobo": sum(item.instructor_share_kobo for item in earnings) - sum(item.instructor_share_reversed_kobo for item in reversals),
        "pending_payouts_kobo": sum(item.amount_kobo for item in InstructorPayoutRequest.query.filter(InstructorPayoutRequest.instructor_id == current_user.id, InstructorPayoutRequest.status.in_(["pending", "approved"])).all()),
        "completed_payouts_kobo": sum(item.amount_kobo for item in InstructorPayoutRequest.query.filter_by(instructor_id=current_user.id, status="paid").all()),
        "unread_notifications": unread_count,
    }
    notifications = InstructorNotification.query.filter_by(instructor_id=current_user.id).order_by(InstructorNotification.created_at.desc()).limit(5).all()
    return render_template("instructor/dashboard.html", metrics=metrics, courses=courses, recent_enrollments=recent_enrollments, recent_orders=recent_orders, notifications=notifications)


def instructor_owned_course(course_id):
    return Course.query.filter_by(id=course_id, instructor_id=current_user.id).first_or_404()


@instructor_bp.route("/courses")
@login_required
def courses():
    course_list = Course.query.filter_by(instructor_id=current_user.id).order_by(Course.updated_at.desc()).all()
    return render_template("instructor/courses.html", courses=course_list)


@instructor_bp.route("/courses/new", methods=["GET", "POST"])
@login_required
def course_new():
    categories = CourseCategory.query.order_by(CourseCategory.name.asc()).all()
    if request.method == "POST":
        title = request.form.get("title", "").strip()[:200]
        slug = slugify(request.form.get("slug", "") or title).strip("-")[:200]
        short_description = request.form.get("short_description", "").strip()
        description = request.form.get("description", "").strip()
        is_free = request.form.get("is_free") == "on"
        try:
            price = Decimal("0") if is_free else Decimal(request.form.get("price", ""))
            duration_hours = int(request.form.get("duration_hours", "1"))
        except (InvalidOperation, ValueError):
            price, duration_hours = Decimal("-1"), 0
        errors = []
        if len(title) < 3 or not slug or not short_description or not description:
            errors.append("Title, slug, short description, and course description are required.")
        if not price.is_finite() or price < 0 or (not is_free and price <= 0):
            errors.append("Paid courses require a positive price in NGN.")
        if duration_hours < 1 or duration_hours > 10000:
            errors.append("Duration must be a positive number of hours.")
        if Course.query.filter_by(slug=slug).first():
            errors.append("That course URL is already in use.")
        if errors:
            for error in errors:
                flash(error, "error")
            return render_template("instructor/course_form.html", course=None, categories=categories)
        category_id = request.form.get("category_id", type=int)
        category = db.session.get(CourseCategory, category_id) if category_id else None
        if category_id and not category:
            flash("Choose a valid course category.", "error")
            return render_template("instructor/course_form.html", course=None, categories=categories)
        cover_image = None
        cover_upload = request.files.get("cover_image")
        if cover_upload and cover_upload.filename:
            cover_image, upload_error = save_public_image(cover_upload, "course-covers")
            if upload_error:
                flash(upload_error, "error")
                return render_template("instructor/course_form.html", course=None, categories=categories)
        course = Course(
            title=title,
            slug=slug,
            short_description=short_description,
            description=sanitize_instructor_html(description),
            cover_image=cover_image,
            category=category,
            instructor_id=current_user.id,
            instructor_name=current_user.full_name,
            difficulty=request.form.get("difficulty") if request.form.get("difficulty") in {"Beginner", "Intermediate", "Advanced"} else "Beginner",
            duration_hours=duration_hours,
            language=request.form.get("language", "English").strip()[:60] or "English",
            price=float(price),
            currency="NGN",
            is_free=is_free,
            status="draft",
            review_status="draft",
            objectives=request.form.get("objectives", "").strip() or None,
            prerequisites=request.form.get("prerequisites", "").strip() or None,
            target_audience=request.form.get("target_audience", "").strip() or None,
            requirements=request.form.get("requirements", "").strip() or None,
            what_students_learn=request.form.get("what_students_learn", "").strip() or None,
        )
        db.session.add(course)
        db.session.flush()
        action = request.form.get("action")
        if action == "submit":
            if CourseLesson.query.filter_by(course_id=course.id).count() == 0:
                write_instructor_audit("course_created", "course", course.id, instructor_id=current_user.id)
                db.session.commit()
                flash("Add at least one lesson before submitting the course for review.", "error")
                return redirect(url_for("instructor.course_edit", course_id=course.id))
            course.review_status = "submitted"
            create_instructor_notification(current_user, "course", f"Course submitted for review: {course.title}", url_for("instructor.courses"), f"course-submitted-{course.id}")
        write_instructor_audit("course_created", "course", course.id, instructor_id=current_user.id)
        db.session.commit()
        if action == "submit":
            send_academy_notice("Axiom Academy course submitted for review", [get_admin_notification_recipient()], f"{current_user.full_name} submitted '{course.title}' for review.")
        flash("Course saved as a draft." if action != "submit" else "Course submitted for admin review.", "success")
        return redirect(url_for("instructor.courses"))
    return render_template("instructor/course_form.html", course=None, categories=categories)


@instructor_bp.route("/courses/<int:course_id>/edit", methods=["GET", "POST"])
@login_required
def course_edit(course_id):
    course = instructor_owned_course(course_id)
    categories = CourseCategory.query.order_by(CourseCategory.name.asc()).all()
    if request.method == "POST":
        title = request.form.get("title", "").strip()[:200]
        slug = slugify(request.form.get("slug", "") or title).strip("-")[:200]
        try:
            is_free = request.form.get("is_free") == "on"
            price = Decimal("0") if is_free else Decimal(request.form.get("price", ""))
            duration_hours = int(request.form.get("duration_hours", "1"))
        except (InvalidOperation, ValueError):
            flash("Enter a valid price and course duration.", "error")
            return render_template("instructor/course_form.html", course=course, categories=categories)
        duplicate = Course.query.filter(Course.slug == slug, Course.id != course.id).first()
        if duplicate or not title or not price.is_finite() or price < 0 or (not is_free and price <= 0) or duration_hours < 1:
            flash("Check the title, unique URL, positive paid price, and course duration.", "error")
            return render_template("instructor/course_form.html", course=course, categories=categories)
        category_id = request.form.get("category_id", type=int)
        category = db.session.get(CourseCategory, category_id) if category_id else None
        if category_id and not category:
            flash("Choose a valid course category.", "error")
            return render_template("instructor/course_form.html", course=course, categories=categories)
        cover_upload = request.files.get("cover_image")
        if cover_upload and cover_upload.filename:
            cover_image, upload_error = save_public_image(cover_upload, "course-covers")
            if upload_error:
                flash(upload_error, "error")
                return render_template("instructor/course_form.html", course=course, categories=categories)
            course.cover_image = cover_image
        course.title = title
        course.slug = slug
        course.short_description = request.form.get("short_description", "").strip()
        course.description = sanitize_instructor_html(request.form.get("description", "").strip())
        course.category = category
        course.instructor_name = current_user.full_name
        course.difficulty = request.form.get("difficulty") if request.form.get("difficulty") in {"Beginner", "Intermediate", "Advanced"} else "Beginner"
        course.duration_hours = duration_hours
        course.language = request.form.get("language", "English").strip()[:60] or "English"
        course.price = float(price)
        course.currency = "NGN"
        course.is_free = is_free
        course.objectives = request.form.get("objectives", "").strip() or None
        course.prerequisites = request.form.get("prerequisites", "").strip() or None
        course.target_audience = request.form.get("target_audience", "").strip() or None
        course.requirements = request.form.get("requirements", "").strip() or None
        course.what_students_learn = request.form.get("what_students_learn", "").strip() or None
        action = request.form.get("action")
        course.status = "draft"
        course.review_status = "draft"
        course.published_at = None
        if action == "submit":
            if not course.short_description or not course.description:
                flash("A short and full description are required before review.", "error")
                return render_template("instructor/course_form.html", course=course, categories=categories)
            if CourseLesson.query.filter_by(course_id=course.id).count() == 0:
                flash("Add at least one lesson before submitting the course for review.", "error")
                return render_template("instructor/course_form.html", course=course, categories=categories)
            course.status = "draft"
            course.review_status = "submitted"
            create_instructor_notification(current_user, "course", f"Course submitted for review: {course.title}", url_for("instructor.courses"), f"course-submitted-{course.id}-{int(datetime.now(timezone.utc).timestamp())}")
        write_instructor_audit("course_updated", "course", course.id, instructor_id=current_user.id)
        db.session.commit()
        if action == "submit":
            send_academy_notice("Axiom Academy course submitted for review", [get_admin_notification_recipient()], f"{current_user.full_name} submitted '{course.title}' for review.")
        flash("Course submitted for review." if action == "submit" else "Course draft updated.", "success")
        return redirect(url_for("instructor.courses"))
    return render_template("instructor/course_form.html", course=course, categories=categories)


@instructor_bp.route("/courses/<int:course_id>/preview")
@login_required
def course_preview(course_id):
    course = instructor_owned_course(course_id)
    lessons = CourseLesson.query.filter_by(course_id=course.id).order_by(CourseLesson.order_index.asc(), CourseLesson.id.asc()).all()
    return render_template("instructor/course_preview.html", course=course, lessons=lessons)


@instructor_bp.route("/courses/<int:course_id>/status", methods=["POST"])
@login_required
def course_status(course_id):
    course = instructor_owned_course(course_id)
    action = request.form.get("action")
    if action == "unpublish" and course.status == "published":
        course.status = "draft"
        course.review_status = "draft"
        write_instructor_audit("course_unpublished", "course", course.id, instructor_id=current_user.id)
    elif action == "archive":
        course.status = "archived"
        course.review_status = "archived"
        write_instructor_audit("course_archived", "course", course.id, instructor_id=current_user.id)
    else:
        abort(400)
    db.session.commit()
    flash("Course status updated.", "success")
    return redirect(url_for("instructor.courses"))


@instructor_bp.route("/courses/<int:course_id>/lessons", methods=["POST"])
@login_required
def lesson_create(course_id):
    course = instructor_owned_course(course_id)
    title = request.form.get("title", "").strip()[:200]
    content = request.form.get("content", "").strip()
    lesson_slug = slugify(request.form.get("slug", "") or title).strip("-")[:200]
    lesson_type = request.form.get("lesson_type", "text")
    try:
        duration_minutes = max(1, min(1440, int(request.form.get("duration_minutes", "15"))))
        order_index = max(0, int(request.form.get("order_index", "0")))
    except ValueError:
        flash("Lesson duration and order must be whole numbers.", "error")
        return redirect(url_for("instructor.course_edit", course_id=course.id))
    upload = request.files.get("resource")
    allowed = {"pdf", "ppt", "pptx", "doc", "docx", "jpg", "jpeg", "png"}
    resource_path = None
    resource_filename = None
    if upload and upload.filename:
        filename = secure_filename(upload.filename)
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if extension not in allowed:
            flash("Allowed lesson resources are PDF, PowerPoint, Word, JPG, or PNG files.", "error")
            return redirect(url_for("instructor.course_edit", course_id=course.id))
        resource_bytes = upload.stream.read(16 * 1024 * 1024 + 1)
        if len(resource_bytes) > 16 * 1024 * 1024 or not valid_resource_signature(extension, resource_bytes[:16]):
            flash("The resource file is too large or does not match its file type.", "error")
            return redirect(url_for("instructor.course_edit", course_id=course.id))
        root = get_private_academy_upload_root() / "instructor_materials" / str(current_user.id)
        root.mkdir(parents=True, exist_ok=True)
        stored = f"{secrets.token_hex(16)}.{extension}"
        (root / stored).write_bytes(resource_bytes)
        resource_path = f"instructor_materials/{current_user.id}/{stored}"
        resource_filename = filename
    if not title or not (content or request.form.get("external_video_url", "").strip() or resource_path):
        flash("Provide a lesson title and lesson content, video link, or resource file.", "error")
        return redirect(url_for("instructor.course_edit", course_id=course.id))
    if lesson_type not in {"text", "video"} or CourseLesson.query.filter_by(course_id=course.id, slug=lesson_slug).first():
        flash("Choose a valid lesson type and unique lesson URL.", "error")
        return redirect(url_for("instructor.course_edit", course_id=course.id))
    external_video_url = request.form.get("external_video_url", "").strip() or None
    if external_video_url:
        parsed_video_url = urlsplit(external_video_url)
        if parsed_video_url.scheme not in {"http", "https"} or not parsed_video_url.netloc:
            flash("Video links must use a valid HTTP or HTTPS URL.", "error")
            return redirect(url_for("instructor.course_edit", course_id=course.id))
    lesson = CourseLesson(
        course=course,
        title=title,
        slug=lesson_slug,
        lesson_type=lesson_type,
        content=sanitize_instructor_html(content) or None,
        external_video_url=external_video_url,
        module_title=request.form.get("module_title", "").strip()[:160] or None,
        resource_path=resource_path,
        resource_filename=resource_filename,
        duration_minutes=duration_minutes,
        order_index=order_index,
        is_preview=request.form.get("is_preview") == "on",
        status="draft",
    )
    db.session.add(lesson)
    course.status = "draft"
    course.review_status = "draft"
    course.published_at = None
    write_instructor_audit("lesson_created", "lesson", None, instructor_id=current_user.id, details=course.title)
    recalculate_course_progress(course.id)
    db.session.commit()
    flash("Lesson saved as a draft.", "success")
    return redirect(url_for("instructor.course_edit", course_id=course.id))


@instructor_bp.route("/courses/<int:course_id>/lessons/<int:lesson_id>/edit", methods=["POST"])
@login_required
def lesson_edit(course_id, lesson_id):
    course = instructor_owned_course(course_id)
    lesson = CourseLesson.query.filter_by(id=lesson_id, course_id=course.id).first_or_404()
    title = request.form.get("title", "").strip()[:200]
    slug = slugify(request.form.get("slug", "") or title).strip("-")[:200]
    try:
        lesson.order_index = max(0, int(request.form.get("order_index", lesson.order_index)))
        lesson.duration_minutes = max(1, min(1440, int(request.form.get("duration_minutes", lesson.duration_minutes))))
    except ValueError:
        flash("Lesson duration and order must be whole numbers.", "error")
        return redirect(url_for("instructor.course_edit", course_id=course.id))
    duplicate = CourseLesson.query.filter(CourseLesson.course_id == course.id, CourseLesson.slug == slug, CourseLesson.id != lesson.id).first()
    if not title or duplicate:
        flash("Lesson title is required and its URL must be unique in this course.", "error")
        return redirect(url_for("instructor.course_edit", course_id=course.id))
    lesson.title = title
    lesson.slug = slug
    lesson.module_title = request.form.get("module_title", "").strip()[:160] or None
    lesson.content = sanitize_instructor_html(request.form.get("content", "").strip()) or None
    lesson.is_preview = request.form.get("is_preview") == "on"
    lesson_status = request.form.get("status")
    if lesson_status in {"draft", "published"}:
        lesson.status = lesson_status
    video_url = request.form.get("external_video_url", "").strip() or None
    if video_url:
        parsed_video_url = urlsplit(video_url)
        if parsed_video_url.scheme not in {"http", "https"} or not parsed_video_url.netloc:
            flash("Video links must use a valid HTTP or HTTPS URL.", "error")
            return redirect(url_for("instructor.course_edit", course_id=course.id))
    lesson.external_video_url = video_url
    lesson.lesson_type = request.form.get("lesson_type") if request.form.get("lesson_type") in {"text", "video"} else "text"
    upload = request.files.get("resource")
    if upload and upload.filename:
        filename = secure_filename(upload.filename)
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if extension not in {"pdf", "ppt", "pptx", "doc", "docx", "jpg", "jpeg", "png"}:
            flash("Choose a supported course resource file.", "error")
            return redirect(url_for("instructor.course_edit", course_id=course.id))
        resource_bytes = upload.stream.read(16 * 1024 * 1024 + 1)
        if len(resource_bytes) > 16 * 1024 * 1024 or not valid_resource_signature(extension, resource_bytes[:16]):
            flash("The resource file is too large or does not match its file type.", "error")
            return redirect(url_for("instructor.course_edit", course_id=course.id))
        root = get_private_academy_upload_root() / "instructor_materials" / str(current_user.id)
        root.mkdir(parents=True, exist_ok=True)
        stored = f"{secrets.token_hex(16)}.{extension}"
        (root / stored).write_bytes(resource_bytes)
        lesson.resource_path = f"instructor_materials/{current_user.id}/{stored}"
        lesson.resource_filename = filename
        course.status = "draft"
        course.review_status = "draft"
        course.published_at = None
    write_instructor_audit("lesson_updated", "lesson", lesson.id, instructor_id=current_user.id)
    recalculate_course_progress(course.id)
    db.session.commit()
    flash("Lesson updated.", "success")
    return redirect(url_for("instructor.course_edit", course_id=course.id))


@instructor_bp.route("/courses/<int:course_id>/lessons/<int:lesson_id>/delete", methods=["POST"])
@login_required
def lesson_delete(course_id, lesson_id):
    course = instructor_owned_course(course_id)
    lesson = CourseLesson.query.filter_by(id=lesson_id, course_id=course.id).first_or_404()
    if Quiz.query.filter_by(lesson_id=lesson.id).count():
        flash("This lesson is referenced by an assessment and cannot be deleted.", "error")
        return redirect(url_for("instructor.course_edit", course_id=course.id))
    if lesson.resource_path:
        root = get_private_academy_upload_root().resolve()
        file_path = (root / lesson.resource_path).resolve()
        try:
            file_path.relative_to(root)
        except ValueError:
            abort(404)
        file_path.unlink(missing_ok=True)
    lesson_id_value = lesson.id
    CourseEnrollment.query.filter_by(course_id=course.id, last_lesson_id=lesson.id).update(
        {CourseEnrollment.last_lesson_id: None},
        synchronize_session=False,
    )
    db.session.delete(lesson)
    course.status = "draft"
    course.review_status = "draft"
    course.published_at = None
    write_instructor_audit("lesson_deleted", "lesson", lesson_id_value, instructor_id=current_user.id)
    db.session.flush()
    recalculate_course_progress(course.id)
    db.session.commit()
    flash("Lesson deleted.", "success")
    return redirect(url_for("instructor.course_edit", course_id=course.id))


@instructor_bp.route("/courses/<int:course_id>/quizzes", methods=["POST"])
@login_required
def quiz_create(course_id):
    course = instructor_owned_course(course_id)
    title = request.form.get("title", "").strip()[:200]
    if not title:
        flash("Assessment title is required.", "error")
        return redirect(url_for("instructor.course_edit", course_id=course.id))
    try:
        pass_mark = min(100.0, max(0.0, float(request.form.get("pass_mark", "70"))))
        attempt_limit = min(20, max(1, int(request.form.get("attempt_limit", "3"))))
    except ValueError:
        flash("Enter a valid pass mark and attempt limit.", "error")
        return redirect(url_for("instructor.course_edit", course_id=course.id))
    quiz = Quiz(course_id=course.id, title=title, instructions=request.form.get("instructions", "").strip() or None, pass_mark=pass_mark, attempt_limit=attempt_limit, status="draft")
    question_count = 0
    for index in range(1, 11):
        prompt = request.form.get(f"prompt_{index}", "").strip()
        if not prompt:
            continue
        options = [request.form.get(f"option_{index}_{letter}", "").strip() for letter in "abcd"]
        correct = request.form.get(f"correct_{index}", "")
        if sum(bool(option) for option in options) < 2 or correct not in {"a", "b", "c", "d"} or not options[ord(correct) - ord("a")]:
            flash(f"Question {index} requires two choices and one valid correct answer.", "error")
            return redirect(url_for("instructor.course_edit", course_id=course.id))
        question = QuizQuestion(prompt=prompt[:4000], points=1.0, order_index=index)
        quiz.questions.append(question)
        for option_index, option_text in enumerate(options):
            if option_text:
                question.options.append(QuizOption(option_text=option_text[:1000], is_correct=chr(ord("a") + option_index) == correct))
        question_count += 1
    if not question_count:
        flash("Add at least one assessment question.", "error")
        return redirect(url_for("instructor.course_edit", course_id=course.id))
    db.session.add(quiz)
    db.session.flush()
    write_instructor_audit("quiz_created", "quiz", quiz.id, instructor_id=current_user.id, details=course.title)
    db.session.commit()
    flash("Assessment saved as a draft. It will publish with the approved course.", "success")
    return redirect(url_for("instructor.course_edit", course_id=course.id))


@instructor_bp.route("/courses/<int:course_id>/materials/<int:lesson_id>")
@login_required
def lesson_material(course_id, lesson_id):
    course = Course.query.filter_by(id=course_id).first_or_404()
    lesson = CourseLesson.query.filter_by(id=lesson_id, course_id=course.id).first_or_404()
    instructor_access = isinstance(current_user, Instructor) and course.instructor_id == current_user.id and current_user.status == "approved"
    student_access = isinstance(current_user, Student) and lesson.status == "published" and CourseEnrollment.query.filter_by(student_id=current_user.id, course_id=course.id, status="active").first() is not None
    if not (instructor_access or student_access) or not lesson.resource_path:
        abort(404)
    root = get_private_academy_upload_root().resolve()
    path = (root / lesson.resource_path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        abort(404)
    if not path.is_file():
        abort(404)
    return send_file(path, as_attachment=True, download_name=lesson.resource_filename or path.name, mimetype=mimetypes.guess_type(path.name)[0])


@instructor_bp.route("/students")
@login_required
def students():
    course_ids = [course.id for course in Course.query.filter_by(instructor_id=current_user.id).all()]
    query = CourseEnrollment.query.filter(CourseEnrollment.course_id.in_(course_ids)) if course_ids else CourseEnrollment.query.filter(db.false())
    course_filter = request.args.get("course", type=int)
    status_filter = request.args.get("status", "").strip()
    search = request.args.get("q", "").strip()
    if course_filter in course_ids:
        query = query.filter_by(course_id=course_filter)
    if status_filter in {"active", "completed", "cancelled"}:
        if status_filter == "completed":
            query = query.filter(CourseEnrollment.completed_at.isnot(None))
        elif status_filter == "active":
            query = query.filter(CourseEnrollment.status == "active", CourseEnrollment.completed_at.is_(None))
        else:
            query = query.filter_by(status=status_filter)
    if search:
        query = query.join(Student).filter(or_(Student.full_name.ilike(f"%{search}%"), Student.email.ilike(f"%{search}%")))
    sort = request.args.get("sort", "date")
    ordering = CourseEnrollment.progress.asc() if sort == "progress_asc" else CourseEnrollment.progress.desc() if sort == "progress_desc" else CourseEnrollment.created_at.asc() if sort == "date_asc" else CourseEnrollment.created_at.desc()
    enrollments = query.order_by(ordering).paginate(page=request.args.get("page", 1, type=int), per_page=25, error_out=False)
    instructor_courses = Course.query.filter_by(instructor_id=current_user.id).order_by(Course.title.asc()).all()
    return render_template("instructor/students.html", enrollments=enrollments, courses=instructor_courses, course_filter=course_filter, status_filter=status_filter, search=search, sort=sort)


@instructor_bp.route("/students/<int:enrollment_id>")
@login_required
def student_detail(enrollment_id):
    enrollment = CourseEnrollment.query.join(Course).filter(
        CourseEnrollment.id == enrollment_id,
        Course.instructor_id == current_user.id,
    ).first_or_404()
    lesson_ids = [lesson.id for lesson in enrollment.course.lessons]
    quiz_query = Quiz.query.filter(Quiz.course_id == enrollment.course_id)
    if lesson_ids:
        quiz_query = quiz_query.union(Quiz.query.filter(Quiz.lesson_id.in_(lesson_ids)))
    quiz_ids = [quiz.id for quiz in quiz_query.all()]
    attempts = QuizAttempt.query.filter(
        QuizAttempt.student_id == enrollment.student_id,
        QuizAttempt.quiz_id.in_(quiz_ids),
    ).order_by(QuizAttempt.submitted_at.desc().nullslast()).all() if quiz_ids else []
    completed_lessons = LessonProgress.query.filter_by(enrolment_id=enrollment.id, completed=True).count()
    certificates = AcademyCertificate.query.filter_by(student_id=enrollment.student_id, course_id=enrollment.course_id).order_by(AcademyCertificate.issue_date.desc()).all()
    return render_template(
        "instructor/student_detail.html",
        enrollment=enrollment,
        completed_lessons=completed_lessons,
        total_lessons=len(lesson_ids),
        attempts=attempts,
        certificates=certificates,
    )


@instructor_bp.route("/students/<int:enrollment_id>/admission-certificate", methods=["POST"])
@login_required
def issue_admission_certificate(enrollment_id):
    enrollment = CourseEnrollment.query.join(Course).filter(
        CourseEnrollment.id == enrollment_id,
        Course.instructor_id == current_user.id,
        CourseEnrollment.status == "active",
    ).first_or_404()
    existing = AcademyCertificate.query.filter_by(
        student_id=enrollment.student_id,
        course_id=enrollment.course_id,
        certificate_type="admission",
        status="issued",
    ).first()
    if existing:
        return redirect(url_for("instructor.certificate_pdf", certificate_id=existing.id))
    certificate = AcademyCertificate(
        student_id=enrollment.student_id,
        course_id=enrollment.course_id,
        certificate_number=f"AXM-ADM-{secrets.token_hex(6).upper()}",
        verification_code=secrets.token_urlsafe(16),
        certificate_type="admission",
        status="issued",
        issued_by_instructor_id=current_user.id,
    )
    db.session.add(certificate)
    db.session.flush()
    write_instructor_audit("admission_certificate_issued", "certificate", certificate.id, instructor_id=current_user.id, details=f"Enrollment {enrollment.id}")
    create_instructor_notification(current_user, "certificate", f"Admission certificate issued for {enrollment.student.full_name}.", url_for("instructor.certificates"), f"admission-certificate-{certificate.id}")
    db.session.commit()
    send_academy_notice("Axiom Academy admission certificate", [enrollment.student.email], f"Your admission certificate for {enrollment.course.title} is available. Verification code: {certificate.verification_code}")
    flash("Admission certificate issued.", "success")
    return redirect(url_for("instructor.certificate_pdf", certificate_id=certificate.id))


@instructor_bp.route("/certificates")
@login_required
def certificates():
    course_ids = [course.id for course in Course.query.filter_by(instructor_id=current_user.id).all()]
    items = AcademyCertificate.query.filter(AcademyCertificate.course_id.in_(course_ids)).order_by(AcademyCertificate.issue_date.desc()).all() if course_ids else []
    return render_template("instructor/certificates.html", certificates=items)


@instructor_bp.route("/certificates/<int:certificate_id>.pdf")
@login_required
def certificate_pdf(certificate_id):
    certificate = AcademyCertificate.query.join(Course).filter(
        AcademyCertificate.id == certificate_id,
        Course.instructor_id == current_user.id,
        AcademyCertificate.status == "issued",
    ).first_or_404()
    return certificate_pdf_response(certificate)


def certificate_pdf_response(certificate):
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas

    output = BytesIO()
    page = canvas.Canvas(output, pagesize=landscape(letter))
    width, height = landscape(letter)
    page.setStrokeColorRGB(0.035, 0.161, 0.294)
    page.setLineWidth(3)
    page.rect(28, 28, width - 56, height - 56)
    page.setStrokeColorRGB(0.788, 0.635, 0.153)
    page.setLineWidth(1)
    page.rect(38, 38, width - 76, height - 76)
    page.setFillColorRGB(0.035, 0.161, 0.294)
    page.setFont("Helvetica-Bold", 15)
    page.drawCentredString(width / 2, height - 92, "AXIOM GATEWAY CONSULT ACADEMY")
    page.setFillColorRGB(0.788, 0.635, 0.153)
    page.setFont("Helvetica-Bold", 30)
    certificate_title = "ADMISSION CERTIFICATE" if certificate.certificate_type == "admission" else "COURSE COMPLETION CERTIFICATE"
    page.drawCentredString(width / 2, height - 155, certificate_title)
    page.setFillColorRGB(0.15, 0.18, 0.22)
    page.setFont("Helvetica", 14)
    page.drawCentredString(width / 2, height - 210, "This confirms that")
    page.setFont("Helvetica-Bold", 24)
    student_name = certificate.student.full_name
    name_font_size = 24
    while name_font_size > 14 and stringWidth(student_name, "Helvetica-Bold", name_font_size) > width - 120:
        name_font_size -= 1
    page.setFont("Helvetica-Bold", name_font_size)
    page.drawCentredString(width / 2, height - 250, student_name)
    page.setFont("Helvetica", 14)
    course_statement = (
        f"has been admitted to {certificate.course.title}"
        if certificate.certificate_type == "admission"
        else f"has successfully completed {certificate.course.title}"
    )
    course_font_size = 14
    while course_font_size > 10 and stringWidth(course_statement, "Helvetica", course_font_size) > width - 120:
        course_font_size -= 1
    page.setFont("Helvetica", course_font_size)
    page.drawCentredString(width / 2, height - 290, course_statement)
    if certificate.certificate_type == "admission":
        page.setFont("Helvetica", 14)
        page.drawCentredString(width / 2, height - 325, f"Instructor: {certificate.issued_by_instructor.full_name if certificate.issued_by_instructor else certificate.course.instructor_name}")
    page.drawCentredString(width / 2, height - 360, f"Issued: {certificate.issue_date.strftime('%d %B %Y')}")
    page.setFont("Helvetica", 10)
    page.drawCentredString(width / 2, 78, f"Certificate {certificate.certificate_number} · Verification code {certificate.verification_code}")
    verification_url = url_for("public.verify_certificate", code=certificate.verification_code, _external=True)
    page.drawCentredString(width / 2, 60, f"Verify at {verification_url}")
    from reportlab.graphics import renderPDF
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing

    qr = QrCodeWidget(verification_url)
    x1, y1, x2, y2 = qr.getBounds()
    qr_size = 54
    drawing = Drawing(qr_size, qr_size, transform=[qr_size / (x2 - x1), 0, 0, qr_size / (y2 - y1), -x1, -y1])
    drawing.add(qr)
    renderPDF.draw(drawing, page, width - 88, 42)
    page.save()
    output.seek(0)
    return send_file(output, mimetype="application/pdf", as_attachment=True, download_name=f"{certificate.certificate_number}.pdf")


@instructor_bp.route("/certificates/<int:certificate_id>/revoke", methods=["POST"])
@login_required
def revoke_certificate(certificate_id):
    certificate = AcademyCertificate.query.join(Course).filter(
        AcademyCertificate.id == certificate_id,
        Course.instructor_id == current_user.id,
        AcademyCertificate.status == "issued",
    ).first_or_404()
    reason = request.form.get("reason", "").strip()
    if len(reason) < 5:
        flash("Provide a reason of at least five characters.", "error")
        return redirect(url_for("instructor.certificates"))
    certificate.status = "revoked"
    certificate.revoked_at = datetime.now(timezone.utc)
    certificate.revoked_reason = reason[:1000]
    write_instructor_audit("certificate_revoked", "certificate", certificate.id, instructor_id=current_user.id, details=certificate.revoked_reason)
    db.session.commit()
    flash("Certificate revoked. Public verification will report it as revoked.", "success")
    return redirect(url_for("instructor.certificates"))


@instructor_bp.route("/earnings", methods=["GET", "POST"])
@login_required
def earnings():
    if request.method == "POST":
        try:
            amount_naira = Decimal(request.form.get("amount", ""))
            amount_kobo_decimal = amount_naira * 100
            amount_kobo = int(amount_kobo_decimal)
            if amount_kobo_decimal != amount_kobo or not amount_naira.is_finite():
                amount_kobo = 0
        except (InvalidOperation, ValueError):
            amount_kobo = 0
        available_entries = InstructorEarning.query.filter_by(instructor_id=current_user.id, payout_status="available").order_by(InstructorEarning.created_at.asc()).all()
        available = sum(item.instructor_share_kobo for item in available_entries)
        settings = CompanySettings.query.order_by(CompanySettings.id.desc()).first()
        minimum = settings.academy_minimum_payout_kobo if settings else 0
        active_request = InstructorPayoutRequest.query.filter(InstructorPayoutRequest.instructor_id == current_user.id, InstructorPayoutRequest.status.in_(["pending", "approved"])).first()
        profile_complete = all((current_user.payout_bank_name, current_user.payout_account_name, current_user.payout_bank_code, current_user.payout_account_number_encrypted))
        if not profile_complete:
            flash("Add your payout bank details before requesting a transfer.", "error")
        elif amount_kobo <= 0 or amount_kobo < minimum or amount_kobo != available or active_request:
            flash("Request the full available balance, meet the configured minimum, and resolve any existing request first.", "error")
        else:
            remaining = amount_kobo
            for earning in available_entries:
                allocated = min(remaining, earning.instructor_share_kobo)
                if allocated <= 0:
                    break
                earning.payout_status = "requested"
                remaining -= allocated
            payout = InstructorPayoutRequest(instructor_id=current_user.id, amount_kobo=amount_kobo, status="pending")
            db.session.add(payout)
            db.session.flush()
            remaining = amount_kobo
            for earning in available_entries:
                allocated = min(remaining, earning.instructor_share_kobo)
                if allocated <= 0:
                    break
                db.session.add(InstructorPayoutAllocation(payout_request_id=payout.id, earning_id=earning.id, amount_kobo=allocated))
                remaining -= allocated
            write_instructor_audit("payout_requested", "payout", None, instructor_id=current_user.id, details=str(amount_kobo))
            db.session.commit()
            flash("Payout request submitted for admin review.", "success")
            return redirect(url_for("instructor.earnings"))
    entries_query = InstructorEarning.query.filter_by(instructor_id=current_user.id)
    start_date = request.args.get("start", "").strip()
    end_date = request.args.get("end", "").strip()
    course_filter = request.args.get("course", type=int)
    payout_filter = request.args.get("status", "").strip()
    if start_date:
        try:
            entries_query = entries_query.filter(InstructorEarning.created_at >= datetime.fromisoformat(start_date))
        except ValueError:
            start_date = ""
    if end_date:
        try:
            entries_query = entries_query.filter(InstructorEarning.created_at < datetime.fromisoformat(end_date) + timedelta(days=1))
        except ValueError:
            end_date = ""
    if payout_filter in {"available", "requested", "paid", "reversed"}:
        entries_query = entries_query.filter_by(payout_status=payout_filter)
    if course_filter:
        entries_query = entries_query.join(AcademyOrder, InstructorEarning.order_id == AcademyOrder.id).filter(AcademyOrder.item_type == "course", AcademyOrder.item_id == course_filter)
    entries = entries_query.order_by(InstructorEarning.created_at.desc()).all()
    reversals = InstructorReversal.query.filter_by(instructor_id=current_user.id).order_by(InstructorReversal.created_at.desc()).all()
    requests_list = InstructorPayoutRequest.query.filter_by(instructor_id=current_user.id).order_by(InstructorPayoutRequest.created_at.desc()).all()
    course_ids = [course.id for course in Course.query.filter_by(instructor_id=current_user.id).all()]
    paid_orders = AcademyOrder.query.filter(
        AcademyOrder.item_type == "course",
        AcademyOrder.item_id.in_(course_ids),
        AcademyOrder.status == "paid",
    ).all() if course_ids else []
    totals = {
        "gross": sum(int((Decimal(str(order.amount)) * 100).quantize(Decimal("1"))) for order in paid_orders),
        "commission": sum(item.commission_kobo for item in entries) - sum(item.commission_reversed_kobo for item in reversals),
        "net": sum(item.instructor_share_kobo for item in entries) - sum(item.instructor_share_reversed_kobo for item in reversals),
        "available": sum(item.instructor_share_kobo for item in entries if item.payout_status == "available"),
        "pending": sum(item.amount_kobo for item in requests_list if item.status == "pending"),
        "paid": sum(item.amount_kobo for item in requests_list if item.status == "paid"),
    }
    course_map = {course.id: course for course in Course.query.filter(Course.id.in_(course_ids)).all()} if course_ids else {}
    return render_template(
        "instructor/earnings.html",
        entries=entries,
        payout_requests=requests_list,
        totals=totals,
        course_map=course_map,
        reversals=reversals,
        start_date=start_date,
        end_date=end_date,
        course_filter=course_filter,
        payout_filter=payout_filter,
        instructor_courses=Course.query.filter_by(instructor_id=current_user.id).order_by(Course.title.asc()).all(),
        payout_account_mask=mask_payout_account(current_user.payout_account_number_encrypted),
    )


@instructor_bp.route("/payout-profile", methods=["GET", "POST"])
@login_required
def payout_profile():
    if request.method == "POST":
        bank_name = request.form.get("bank_name", "").strip()[:120]
        account_name = request.form.get("account_name", "").strip()[:160]
        account_number = request.form.get("account_number", "").strip()
        bank_code = request.form.get("bank_code", "").strip()[:30]
        if not bank_name or not account_name or not bank_code:
            flash("Bank, account name, and bank code are required.", "error")
        elif account_number and (not account_number.isdigit() or not 8 <= len(account_number) <= 20):
            flash("Enter a valid account number.", "error")
        else:
            current_user.payout_bank_name = bank_name
            current_user.payout_account_name = account_name
            current_user.payout_bank_code = bank_code
            if account_number:
                current_user.payout_account_number_encrypted = payout_account_cipher().encrypt(account_number.encode("utf-8")).decode("ascii")
            write_instructor_audit("payout_profile_updated", "instructor", current_user.id, instructor_id=current_user.id)
            db.session.commit()
            flash("Payout profile saved. Account number is encrypted at rest.", "success")
            return redirect(url_for("instructor.payout_profile"))
    return render_template(
        "instructor/payout_profile.html",
        instructor=current_user,
        masked_account=mask_payout_account(current_user.payout_account_number_encrypted),
    )


@instructor_bp.route("/analytics")
@login_required
def analytics():
    courses = Course.query.filter_by(instructor_id=current_user.id).all()
    course_ids = [course.id for course in courses]
    course_filter = request.args.get("course", type=int)
    start_date = request.args.get("start", "").strip()
    end_date = request.args.get("end", "").strip()
    selected_course_ids = [course_filter] if course_filter in course_ids else course_ids
    enrollment_query = CourseEnrollment.query.filter(CourseEnrollment.course_id.in_(selected_course_ids)) if selected_course_ids else CourseEnrollment.query.filter(db.false())
    earning_query = InstructorEarning.query.filter_by(instructor_id=current_user.id)
    if selected_course_ids:
        earning_query = earning_query.join(AcademyOrder, InstructorEarning.order_id == AcademyOrder.id).filter(AcademyOrder.item_type == "course", AcademyOrder.item_id.in_(selected_course_ids))
    if start_date:
        try:
            date_start = datetime.fromisoformat(start_date)
            enrollment_query = enrollment_query.filter(CourseEnrollment.created_at >= date_start)
            earning_query = earning_query.filter(InstructorEarning.created_at >= date_start)
        except ValueError:
            start_date = ""
    if end_date:
        try:
            date_end = datetime.fromisoformat(end_date) + timedelta(days=1)
            enrollment_query = enrollment_query.filter(CourseEnrollment.created_at < date_end)
            earning_query = earning_query.filter(InstructorEarning.created_at < date_end)
        except ValueError:
            end_date = ""
    enrollments = enrollment_query.all()
    earnings_list = earning_query.all()
    reversals = InstructorReversal.query.filter_by(instructor_id=current_user.id).all()
    if selected_course_ids:
        reversals = [item for item in reversals if item.order.item_type == "course" and item.order.item_id in selected_course_ids]
    paid_orders_query = AcademyOrder.query.filter(
        AcademyOrder.item_type == "course",
        AcademyOrder.item_id.in_(selected_course_ids),
        AcademyOrder.status == "paid",
    ) if selected_course_ids else AcademyOrder.query.filter(db.false())
    if start_date:
        paid_orders_query = paid_orders_query.filter(AcademyOrder.created_at >= date_start)
    if end_date:
        paid_orders_query = paid_orders_query.filter(AcademyOrder.created_at < date_end)
    paid_orders = paid_orders_query.all()
    daily = {}
    for enrollment in enrollments:
        day = enrollment.created_at.date().isoformat()
        daily[day] = daily.get(day, 0) + 1
    return render_template("instructor/analytics.html", courses=courses, enrollments=enrollments, daily_enrollments=sorted(daily.items()), earnings=earnings_list, paid_orders=paid_orders, reversals=reversals, course_filter=course_filter, start_date=start_date, end_date=end_date)


@instructor_bp.route("/notifications")
@login_required
def notifications():
    items = InstructorNotification.query.filter_by(instructor_id=current_user.id).order_by(InstructorNotification.created_at.desc()).paginate(page=request.args.get("page", 1, type=int), per_page=25, error_out=False)
    return render_template("instructor/notifications.html", notifications=items)


@instructor_bp.route("/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def notification_read(notification_id):
    notification = InstructorNotification.query.filter_by(id=notification_id, instructor_id=current_user.id).first_or_404()
    notification.is_read = True
    db.session.commit()
    return redirect(notification.target_url or url_for("instructor.notifications"))


@instructor_bp.route("/notifications/read-all", methods=["POST"])
@login_required
def notifications_read_all():
    InstructorNotification.query.filter_by(instructor_id=current_user.id, is_read=False).update({InstructorNotification.is_read: True}, synchronize_session=False)
    db.session.commit()
    return redirect(url_for("instructor.notifications"))


@admin_bp.route("/instructors")
@login_required
def instructors_admin():
    instructors = Instructor.query.order_by(Instructor.created_at.desc()).all()
    orders_to_reverse = AcademyOrder.query.join(Course, (AcademyOrder.item_type == "course") & (AcademyOrder.item_id == Course.id)).join(InstructorEarning, InstructorEarning.order_id == AcademyOrder.id).filter(Course.instructor_id.isnot(None), AcademyOrder.status == "paid", InstructorEarning.payout_status == "available", AcademyOrder.payment_events.any(PaymentEvent.status == "verified")).order_by(AcademyOrder.created_at.desc()).limit(100).all()
    reverse_courses = {course.id: course for course in Course.query.filter(Course.id.in_([order.item_id for order in orders_to_reverse])).all()} if orders_to_reverse else {}
    payout_requests = InstructorPayoutRequest.query.filter(InstructorPayoutRequest.status.in_(["pending", "approved"])).order_by(InstructorPayoutRequest.created_at.asc()).all()
    payout_instructor_ids = {payout.instructor_id for payout in payout_requests}
    payout_instructors = Instructor.query.filter(Instructor.id.in_(payout_instructor_ids)).all() if payout_instructor_ids else []
    payout_profiles = {item.id: {"bank": item.payout_bank_name, "account_name": item.payout_account_name, "account_number": decrypt_payout_account(item.payout_account_number_encrypted), "bank_code": item.payout_bank_code} for item in payout_instructors}
    return render_template(
        "admin/instructors.html",
        instructors=instructors,
        courses_to_review=Course.query.filter_by(review_status="submitted").all(),
        payout_requests=payout_requests,
        orders_to_reverse=orders_to_reverse,
        reverse_courses=reverse_courses,
        payout_profiles=payout_profiles,
    )


@admin_bp.route("/instructors/<int:instructor_id>/decision", methods=["POST"])
@login_required
def instructor_decision(instructor_id):
    instructor = Instructor.query.get_or_404(instructor_id)
    decision = request.form.get("decision")
    if decision not in {"approved", "rejected", "suspended"}:
        abort(400)
    reason = request.form.get("reason", "").strip()[:2000] or None
    if instructor.status == decision and instructor.decision_reason == reason:
        return redirect(url_for("admin.instructors_admin"))
    instructor.status = decision
    instructor.decision_reason = reason
    instructor.reviewed_by_admin_id = current_user.id
    create_instructor_notification(instructor, "account", f"Your instructor account was {decision}.", url_for("instructor.dashboard"), f"instructor-decision-{instructor.id}-{int(datetime.now(timezone.utc).timestamp())}")
    write_instructor_audit(f"instructor_{decision}", "instructor", instructor.id, instructor_id=instructor.id, admin_id=current_user.id, details=instructor.decision_reason)
    db.session.commit()
    send_academy_notice(
        f"Axiom Academy instructor application {decision}",
        [instructor.email],
        f"Your instructor application was {decision}. {instructor.decision_reason or ''}".strip(),
    )
    flash(f"Instructor {decision}.", "success")
    return redirect(url_for("admin.instructors_admin"))


@admin_bp.route("/instructor-courses/<int:course_id>/decision", methods=["POST"])
@login_required
def instructor_course_decision(course_id):
    course = Course.query.filter(Course.id == course_id, Course.instructor_id.isnot(None)).first_or_404()
    decision = request.form.get("decision")
    if decision not in {"approved", "rejected"}:
        abort(400)
    if course.review_status == decision and ((decision == "approved" and course.status == "published") or (decision == "rejected" and course.status == "draft")):
        return redirect(url_for("admin.instructors_admin"))
    if decision == "approved" and (
        not course.instructor
        or course.instructor.status != "approved"
        or CourseLesson.query.filter_by(course_id=course.id).count() == 0
    ):
        flash("Approve the instructor and confirm the course has lessons before publishing.", "error")
        return redirect(url_for("admin.instructors_admin"))
    course.review_status = decision
    course.status = "published" if decision == "approved" else "draft"
    course.published_at = datetime.now(timezone.utc) if decision == "approved" else None
    if decision == "approved":
        CourseLesson.query.filter_by(course_id=course.id, status="draft").update({CourseLesson.status: "published"}, synchronize_session=False)
        Quiz.query.filter_by(course_id=course.id, status="draft").update({Quiz.status: "published"}, synchronize_session=False)
        recalculate_course_progress(course.id)
    if course.instructor:
        create_instructor_notification(course.instructor, "course", f"Your course '{course.title}' was {decision}.", url_for("instructor.course_edit", course_id=course.id), f"course-decision-{course.id}-{int(datetime.now(timezone.utc).timestamp())}")
    write_instructor_audit(f"course_{decision}", "course", course.id, instructor_id=course.instructor_id, admin_id=current_user.id)
    db.session.commit()
    send_academy_notice(
        f"Axiom Academy course {decision}",
        [course.instructor.email] if course.instructor else [],
        f"Your course '{course.title}' was {decision}.",
    )
    flash(f"Course {decision}.", "success")
    return redirect(url_for("admin.instructors_admin"))


@admin_bp.route("/instructor-payouts/<int:payout_id>/decision", methods=["POST"])
@login_required
def instructor_payout_decision(payout_id):
    payout = InstructorPayoutRequest.query.get_or_404(payout_id)
    decision = request.form.get("decision")
    allowed = (payout.status == "pending" and decision in {"approved", "rejected"}) or (payout.status == "approved" and decision == "paid")
    if not allowed:
        abort(400)
    payout.status = decision
    payout.decision_note = request.form.get("note", "").strip()[:2000] or None
    payout.payment_reference = request.form.get("payment_reference", "").strip()[:120] or None
    payout.reviewed_by_admin_id = current_user.id
    if decision == "rejected":
        for allocation in payout.allocations:
            if allocation.earning.payout_status == "requested":
                allocation.earning.payout_status = "available"
            db.session.delete(allocation)
    elif decision == "paid":
        if not payout.payment_reference:
            flash("A verified payment reference is required to mark a payout paid.", "error")
            return redirect(url_for("admin.instructors_admin"))
        if sum(allocation.amount_kobo for allocation in payout.allocations) != payout.amount_kobo:
            abort(409)
        for allocation in payout.allocations:
            allocation.earning.payout_status = "paid"
    create_instructor_notification(payout.instructor, "payout", f"Your payout request was marked {decision}.", url_for("instructor.earnings"), f"payout-decision-{payout.id}")
    write_instructor_audit(f"payout_{decision}", "payout", payout.id, instructor_id=payout.instructor_id, admin_id=current_user.id, details=payout.payment_reference or payout.decision_note)
    db.session.commit()
    send_academy_notice(
        f"Axiom Academy payout request {decision}",
        [payout.instructor.email],
        f"Your payout request of NGN {payout.amount_kobo / 100:.2f} was marked {decision}. {payout.decision_note or ''}".strip(),
    )
    flash(f"Payout request {decision}.", "success")
    return redirect(url_for("admin.instructors_admin"))


@admin_bp.route("/instructor-orders/<int:order_id>/reverse", methods=["POST"])
@login_required
def instructor_order_reverse(order_id):
    order = AcademyOrder.query.filter_by(id=order_id, item_type="course", status="paid").first_or_404()
    if not order.payment_events or not any(event.status == "verified" for event in order.payment_events):
        abort(409)
    reversal = reverse_instructor_earning(order, request.form.get("reason", "").strip())
    if not reversal:
        abort(409)
    order.status = "refunded"
    enrollment = CourseEnrollment.query.filter_by(student_id=order.student_id, course_id=order.item_id).first()
    if enrollment:
        enrollment.status = "cancelled"
    for certificate in AcademyCertificate.query.filter_by(student_id=order.student_id, course_id=order.item_id, status="issued").all():
        certificate.status = "revoked"
        certificate.revoked_at = datetime.now(timezone.utc)
        certificate.revoked_reason = "Course payment was refunded."
    write_instructor_audit("course_order_refunded", "order", order.id, admin_id=current_user.id, details=reversal.reason)
    db.session.commit()
    flash("Order marked refunded and instructor earnings reversed.", "success")
    return redirect(url_for("admin.course_payments"))


@admin_bp.route("/login", methods=["GET", "POST"])
def admin_login():
    form = AdminLoginForm()
    if form.validate_on_submit():
        user = AdminUser.query.filter_by(email=form.email.data.lower().strip()).first()
        if user and user.check_password(form.password.data) and user.active:
            login_user(user, remember=True)
            user.last_login = datetime.now(timezone.utc)
            db.session.commit()
            flash("Welcome back.", "success")
            return redirect(url_for("admin.dashboard"))
        flash("Invalid login credentials.", "error")
    return render_template(
        "admin/login.html",
        form=form,
        admin_signup_available=(
            bool(current_app.config.get("ADMIN_SETUP_KEY"))
            and AdminUser.query.count() == 0
        ),
    )


@admin_bp.route("/signup", methods=["GET", "POST"])
@limiter.limit("5 per hour")
def admin_signup():
    setup_key = current_app.config.get("ADMIN_SETUP_KEY")
    if not setup_key or AdminUser.query.count() > 0:
        abort(404)

    form = AdminRegistrationForm()
    if form.validate_on_submit():
        if not hmac.compare_digest(form.setup_key.data, setup_key):
            flash("Invalid admin setup key.", "error")
        elif AdminUser.query.filter_by(email=form.email.data.strip().lower()).first():
            flash("An account with that email already exists.", "error")
        else:
            user = AdminUser(
                name=form.name.data.strip(),
                email=form.email.data.strip().lower(),
                role="admin",
                active=True,
            )
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            login_user(user, remember=True)
            flash("Admin account created. Welcome to the dashboard.", "success")
            return redirect(url_for("admin.dashboard"))
    return render_template("admin/signup.html", form=form)


@admin_bp.route("/logout")
@login_required
def admin_logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("public.home"))


@admin_bp.route("")
@login_required
def dashboard():
    academy_counts = {
        "courses": Course.query.count(),
        "published_courses": Course.query.filter_by(status="published").count(),
        "students": Student.query.count(),
        "enrolments": CourseEnrollment.query.count(),
        "pending_orders": AcademyOrder.query.filter(AcademyOrder.status.in_(["awaiting_receipt", "receipt_submitted"])).count(),
        "submitted_receipts": AcademyOrder.query.filter_by(status="receipt_submitted", item_type="course").count(),
        "issued_certificates": AcademyCertificate.query.filter_by(status="issued").count(),
        "resources": AcademyProduct.query.count(),
    }
    enquiries = Enquiry.query.order_by(Enquiry.created_at.desc()).limit(5).all()
    recent_articles = Article.query.order_by(Article.created_at.desc()).limit(5).all()
    published_articles = Article.query.filter_by(status="published").count()
    draft_articles = Article.query.filter_by(status="draft").count()
    published_projects = Project.query.filter_by(status="published").count()
    total_enquiries = Enquiry.query.count()
    unread = Enquiry.query.filter_by(status="New").count()
    counts = {}
    for status in ["New", "In Progress", "Responded", "Converted", "Closed"]:
        counts[status] = Enquiry.query.filter_by(status=status).count()
    return render_template(
        "admin/dashboard.html",
        total_enquiries=total_enquiries,
        unread=unread,
        counts=counts,
        published_articles=published_articles,
        draft_articles=draft_articles,
        published_projects=published_projects,
        recent_enquiries=enquiries,
        recent_articles=recent_articles,
        academy_counts=academy_counts,
    )


@admin_bp.route("/course-payments")
@login_required
def course_payments():
    orders = AcademyOrder.query.filter_by(item_type="course").filter(AcademyOrder.status.in_(["receipt_submitted", "rejected", "awaiting_receipt"])).order_by(AcademyOrder.receipt_uploaded_at.desc().nullslast(), AcademyOrder.created_at.desc()).all()
    courses = {course.id: course for course in Course.query.filter(Course.id.in_([order.item_id for order in orders])).all()} if orders else {}
    return render_template("admin/course_payments.html", orders=orders, courses=courses)


@admin_bp.route("/course-payments/<int:order_id>/receipt")
@login_required
def course_payment_receipt(order_id):
    order = AcademyOrder.query.filter_by(id=order_id, item_type="course").first_or_404()
    return send_file(get_receipt_file(order), as_attachment=False, download_name=Path(order.receipt_path).name)


@admin_bp.route("/course-payments/<int:order_id>/review", methods=["POST"])
@login_required
def review_course_payment(order_id):
    order = AcademyOrder.query.filter_by(id=order_id, item_type="course", status="receipt_submitted").first_or_404()
    decision = request.form.get("decision")
    note = request.form.get("review_note", "").strip()[:1000] or None
    course = db.session.get(Course, order.item_id)
    if not course:
        abort(404)
    order.receipt_reviewed_at = datetime.now(timezone.utc)
    order.receipt_review_note = note
    order.reviewed_by_admin_id = current_user.id
    if decision == "approve":
        order.status = "paid"
        enrolment = CourseEnrollment.query.filter_by(student_id=order.student_id, course_id=course.id).first()
        if enrolment:
            enrolment.order_id = order.id
            enrolment.status = "active"
            enrolment.source = "bank_transfer"
        else:
            db.session.add(CourseEnrollment(student_id=order.student_id, course_id=course.id, order_id=order.id, status="active", progress=0.0, source="bank_transfer"))
        if course.instructor_id:
            record_instructor_earning(order, course)
            create_instructor_notification(
                course.instructor,
                "enrollment",
                f"A verified payment was approved for {course.title}.",
                url_for("instructor.students"),
                f"verified-receipt-{order.id}",
            )
        db.session.commit()
        send_academy_notice("Axiom Academy course access approved", [order.student.email], f"Your payment receipt for {course.title} has been approved. You can now access the course.")
        flash("Receipt approved and course access granted.", "success")
    elif decision == "reject":
        order.status = "rejected"
        db.session.commit()
        send_academy_notice("Axiom Academy receipt needs attention", [order.student.email], f"Your receipt for {course.title} was not approved. {note or 'Please submit a clearer or correct receipt from your student dashboard.'}")
        flash("Receipt marked for resubmission.", "success")
    else:
        flash("Choose approve or request a resubmission.", "error")
    return redirect(url_for("admin.course_payments"))


@admin_bp.route("/courses")
@login_required
def courses_admin():
    courses = Course.query.order_by(Course.updated_at.desc()).all()
    return render_template("admin/courses.html", courses=courses)


@admin_bp.route("/courses/new", methods=["GET", "POST"])
@login_required
def course_new():
    form = CourseForm()
    form.category_id.choices = [(0, "No category")] + [(category.id, category.name) for category in CourseCategory.query.order_by(CourseCategory.name.asc()).all()]
    if form.validate_on_submit():
        category = db.session.get(CourseCategory, form.category_id.data) if form.category_id.data else None
        course = Course(
            title=form.title.data.strip(),
            slug=(form.slug.data or slugify(form.title.data)).lower(),
            short_description=form.short_description.data.strip(),
            description=form.description.data.strip(),
            category=category,
            instructor_name=form.instructor_name.data.strip() or "Axiom Gateway Consult",
            difficulty=form.difficulty.data,
            duration_hours=max(1, form.duration_hours.data),
            language=form.language.data.strip(),
            price=float(form.price.data),
            currency=form.currency.data,
            is_free=form.is_free.data,
            status=form.status.data,
            is_featured=form.is_featured.data,
            certificate_eligible=form.certificate_eligible.data,
            objectives=form.objectives.data.strip() or None,
            prerequisites=form.prerequisites.data.strip() or None,
            published_at=datetime.now(timezone.utc) if form.status.data == "published" else None,
        )
        if Course.query.filter_by(slug=course.slug).first():
            form.slug.errors.append("That course URL is already in use.")
        else:
            db.session.add(course)
            db.session.commit()
            if course.status == "published":
                send_academy_notice("Axiom Academy course published", [get_admin_notification_recipient()], f"Course published: {course.title} ({url_for('public.academy_course_detail', slug=course.slug, _external=True)}).")
            flash("Course saved.", "success")
            return redirect(url_for("admin.courses_admin"))
    return render_template("admin/course_form.html", form=form)


@admin_bp.route("/courses/<int:course_id>/edit", methods=["GET", "POST"])
@login_required
def course_edit(course_id):
    course = Course.query.get_or_404(course_id)
    form = CourseForm(obj=course)
    form.category_id.choices = [(0, "No category")] + [(category.id, category.name) for category in CourseCategory.query.order_by(CourseCategory.name.asc()).all()]
    if request.method == "GET":
        form.category_id.data = course.category_id or 0
    if form.validate_on_submit():
        previous_status = course.status
        next_slug = (form.slug.data or slugify(form.title.data)).lower()
        duplicate = Course.query.filter(Course.slug == next_slug, Course.id != course.id).first()
        if duplicate:
            form.slug.errors.append("That course URL is already in use.")
        else:
            course.title = form.title.data.strip()
            course.slug = next_slug
            course.short_description = form.short_description.data.strip()
            course.description = form.description.data.strip()
            course.category_id = form.category_id.data or None
            course.instructor_name = form.instructor_name.data.strip() or "Axiom Gateway Consult"
            course.difficulty = form.difficulty.data
            course.duration_hours = max(1, form.duration_hours.data)
            course.language = form.language.data.strip()
            course.price = float(form.price.data)
            course.currency = form.currency.data
            course.is_free = form.is_free.data
            course.status = form.status.data
            course.is_featured = form.is_featured.data
            course.certificate_eligible = form.certificate_eligible.data
            course.objectives = form.objectives.data.strip() or None
            course.prerequisites = form.prerequisites.data.strip() or None
            course.published_at = datetime.now(timezone.utc) if course.status == "published" and not course.published_at else course.published_at
            if course.status == "draft":
                course.published_at = None
            db.session.commit()
            if previous_status != "published" and course.status == "published":
                send_academy_notice("Axiom Academy course published", [get_admin_notification_recipient()], f"Course published: {course.title} ({url_for('public.academy_course_detail', slug=course.slug, _external=True)}).")
            flash("Course updated.", "success")
            return redirect(url_for("admin.courses_admin"))
    return render_template("admin/course_form.html", form=form, course=course)


@admin_bp.route("/courses/<int:course_id>/quizzes/new", methods=["GET", "POST"])
@login_required
def quiz_new(course_id):
    course = Course.query.get_or_404(course_id)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("Assessment title is required.", "error")
            return redirect(url_for("admin.quiz_new", course_id=course.id))
        quiz = Quiz(
            course_id=course.id,
            title=title[:200],
            instructions=request.form.get("instructions", "").strip() or None,
            pass_mark=min(100.0, max(0.0, request.form.get("pass_mark", type=float, default=70.0))),
            attempt_limit=min(20, max(1, request.form.get("attempt_limit", type=int, default=3))),
            status="published" if request.form.get("publish") else "draft",
        )
        db.session.add(quiz)
        question_count = 0
        for index in range(1, 21):
            prompt = request.form.get(f"prompt_{index}", "").strip()
            if not prompt:
                continue
            options = [request.form.get(f"option_{index}_{letter}", "").strip() for letter in "abcd"]
            correct = request.form.get(f"correct_{index}", "")
            if sum(bool(option) for option in options) < 2 or correct not in {"a", "b", "c", "d"} or not options[ord(correct) - ord("a")]:
                db.session.rollback()
                flash(f"Question {index} needs at least two options and one valid correct answer.", "error")
                return redirect(url_for("admin.quiz_new", course_id=course.id))
            question = QuizQuestion(prompt=prompt, points=1.0, order_index=index)
            quiz.questions.append(question)
            for option_index, option_text in enumerate(options):
                if option_text:
                    question.options.append(QuizOption(option_text=option_text, is_correct=chr(ord("a") + option_index) == correct))
            question_count += 1
        if not question_count:
            db.session.rollback()
            flash("Add at least one assessment question.", "error")
            return redirect(url_for("admin.quiz_new", course_id=course.id))
        db.session.commit()
        flash("Assessment created.", "success")
        return redirect(url_for("admin.courses_admin"))
    return render_template("admin/quiz_form.html", course=course)


@admin_bp.route("/courses/<int:course_id>/lessons/new", methods=["GET", "POST"])
@login_required
def lesson_new(course_id):
    course = Course.query.get_or_404(course_id)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        try:
            duration_minutes = max(1, min(1440, int(request.form.get("duration_minutes", "15"))))
            order_index = max(0, int(request.form.get("order_index", "0")))
        except ValueError:
            flash("Lesson duration and order must be whole numbers.", "error")
            return redirect(url_for("admin.lesson_new", course_id=course.id))
        if not title or not content:
            flash("Lesson title and content are required.", "error")
            return redirect(url_for("admin.lesson_new", course_id=course.id))
        slug = slugify(request.form.get("slug", "") or title)
        if CourseLesson.query.filter_by(course_id=course.id, slug=slug).first():
            flash("A lesson with that URL already exists in this course.", "error")
            return redirect(url_for("admin.lesson_new", course_id=course.id))
        lesson = CourseLesson(
            course_id=course.id,
            title=title[:200],
            slug=slug,
            lesson_type=request.form.get("lesson_type", "text") if request.form.get("lesson_type") in {"text", "video"} else "text",
            content=content,
            external_video_url=request.form.get("external_video_url", "").strip() or None,
            duration_minutes=duration_minutes,
            is_preview=bool(request.form.get("is_preview")),
            order_index=order_index,
            status="published" if request.form.get("publish") else "draft",
        )
        db.session.add(lesson)
        db.session.flush()
        recalculate_course_progress(course.id)
        db.session.commit()
        if lesson.status == "published":
            send_academy_notice("Axiom Academy lesson published", [get_admin_notification_recipient()], f"Lesson published for {course.title}: {lesson.title}.")
        flash("Lesson saved.", "success")
        return redirect(url_for("admin.courses_admin"))
    return render_template("admin/lesson_form.html", course=course)


@admin_bp.route("/products")
@login_required
def products_admin():
    products = AcademyProduct.query.order_by(AcademyProduct.updated_at.desc()).all()
    return render_template("admin/products.html", products=products)


@admin_bp.route("/products/new", methods=["GET", "POST"])
@login_required
def product_new():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        slug = slugify(request.form.get("slug", "") or title)
        short_description = request.form.get("short_description", "").strip()
        description = request.form.get("description", "").strip()
        upload = request.files.get("resource_file")
        try:
            price = max(0.0, float(request.form.get("price", "0")))
        except ValueError:
            flash("Enter a valid resource price.", "error")
            return redirect(url_for("admin.product_new"))
        allowed_extensions = {"pdf", "docx", "xlsx", "pptx", "zip", "mp4", "webm"}
        filename = secure_filename(upload.filename or "") if upload else ""
        extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if not title or not short_description or not description or not upload or not filename:
            flash("Complete the resource details and choose a file to upload.", "error")
            return redirect(url_for("admin.product_new"))
        if extension not in allowed_extensions:
            flash("Allowed resource types: PDF, DOCX, XLSX, PPTX, ZIP, MP4, and WEBM.", "error")
            return redirect(url_for("admin.product_new"))
        if AcademyProduct.query.filter_by(slug=slug).first():
            flash("That product URL is already in use.", "error")
            return redirect(url_for("admin.product_new"))
        upload_root = get_private_academy_upload_root()
        upload_root.mkdir(parents=True, exist_ok=True)
        stored_name = f"{secrets.token_hex(16)}_{filename}"
        upload.save(upload_root / stored_name)
        status = "published" if request.form.get("publish") else "draft"
        product = AcademyProduct(
            title=title[:200],
            slug=slug,
            short_description=short_description,
            description=description,
            category=request.form.get("category", "Digital Resource").strip()[:120] or "Digital Resource",
            price=price,
            currency=request.form.get("currency", "NGN") if request.form.get("currency") in {"NGN", "USD"} else "NGN",
            is_free=bool(request.form.get("is_free")),
            status=status,
            file_path=stored_name,
            published_at=datetime.now(timezone.utc) if status == "published" else None,
        )
        db.session.add(product)
        db.session.commit()
        if product.status == "published":
            send_academy_notice("Axiom Academy resource published", [get_admin_notification_recipient()], f"Resource published: {product.title}.")
        flash("Resource uploaded and saved.", "success")
        return redirect(url_for("admin.products_admin"))
    return render_template("admin/product_form.html")


@admin_bp.route("/enquiries")
@login_required
def enquiries():
    query = request.args.get("q", "")
    status = request.args.get("status", "")
    service_slug = request.args.get("service", "")
    service_filter = Service.query.filter_by(slug=service_slug).first() if service_slug else None
    base_query = Enquiry.query
    if query:
        base_query = base_query.filter(or_(Enquiry.full_name.ilike(f"%{query}%"), Enquiry.email.ilike(f"%{query}%"), Enquiry.description.ilike(f"%{query}%")))
    if status:
        base_query = base_query.filter_by(status=status)
    if service_filter:
        base_query = base_query.filter_by(service_id=service_filter.id)
    items = base_query.order_by(Enquiry.created_at.desc()).all()
    services = Service.query.filter_by(published=True).all()
    return render_template("admin/enquiries.html", enquiries=items, services=services, status=status, q=query, service_slug=service_slug)


@admin_bp.route("/enquiries/<int:id>", methods=["GET", "POST"])
@login_required
def enquiry_detail(id):
    enquiry = Enquiry.query.get_or_404(id)
    if request.method == "POST":
        enquiry.status = request.form.get("status", enquiry.status)
        enquiry.internal_notes = request.form.get("internal_notes", enquiry.internal_notes)
        db.session.commit()
        flash("Enquiry updated.", "success")
        return redirect(url_for("admin.enquiry_detail", id=enquiry.id))
    return render_template("admin/enquiry_detail.html", enquiry=enquiry)


@admin_bp.route("/articles")
@login_required
def articles():
    items = Article.query.order_by(Article.created_at.desc()).all()
    return render_template("admin/articles.html", articles=items)


@admin_bp.route("/articles/new", methods=["GET", "POST"])
@login_required
def article_new():
    form = ArticleForm()
    categories = ArticleCategory.query.order_by(ArticleCategory.name.asc()).all()
    form.category_id.choices = [(category.id, category.name) for category in categories]
    if request.method == "POST" and form.validate_on_submit():
        category = ArticleCategory.query.get(form.category_id.data) if form.category_id.data else None
        article = Article(
            title=form.title.data.strip(),
            slug=(form.slug.data or slugify(form.title.data)).lower(),
            excerpt=form.excerpt.data.strip(),
            body=form.body.data.strip(),
            cover_image=form.cover_image.data.strip() or None,
            category=category,
            author_name=form.author_name.data.strip() or "Axiom Gateway Consult",
            seo_title=form.seo_title.data.strip() or form.title.data.strip(),
            seo_description=form.seo_description.data.strip(),
            status=form.status.data,
            published_at=datetime.now(timezone.utc) if form.status.data == "published" else None,
        )
        db.session.add(article)
        db.session.commit()
        flash("Article saved.", "success")
        return redirect(url_for("admin.articles"))
    return render_template("admin/article_form.html", form=form, categories=categories)


@admin_bp.route("/articles/<int:id>/edit", methods=["GET", "POST"])
@login_required
def article_edit(id):
    article = Article.query.get_or_404(id)
    form = ArticleForm(obj=article)
    form.category_id.choices = [(category.id, category.name) for category in ArticleCategory.query.order_by(ArticleCategory.name.asc()).all()]
    if request.method == "POST" and form.validate_on_submit():
        article.title = form.title.data.strip()
        article.slug = (form.slug.data or slugify(form.title.data)).lower()
        article.excerpt = form.excerpt.data.strip()
        article.body = form.body.data.strip()
        article.cover_image = form.cover_image.data.strip() or None
        article.category_id = form.category_id.data or None
        article.author_name = form.author_name.data.strip() or "Axiom Gateway Consult"
        article.seo_title = form.seo_title.data.strip() or article.title
        article.seo_description = form.seo_description.data.strip()
        article.status = form.status.data
        if form.status.data == "published" and article.published_at is None:
            article.published_at = datetime.now(timezone.utc)
        if form.status.data == "draft":
            article.published_at = None
        db.session.commit()
        flash("Article updated.", "success")
        return redirect(url_for("admin.articles"))
    return render_template("admin/article_form.html", form=form, article=article, categories=ArticleCategory.query.order_by(ArticleCategory.name.asc()).all())


@admin_bp.route("/categories", methods=["GET", "POST"])
@login_required
def categories():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            slug = slugify(name)
            if not ArticleCategory.query.filter_by(slug=slug).first():
                db.session.add(ArticleCategory(name=name, slug=slug, description=request.form.get("description", "")))
                db.session.commit()
                flash("Category added.", "success")
            else:
                flash("Category already exists.", "error")
    items = ArticleCategory.query.order_by(ArticleCategory.name.asc()).all()
    return render_template("admin/categories.html", categories=items)


@admin_bp.route("/projects")
@login_required
def projects_admin():
    items = Project.query.order_by(Project.created_at.desc()).all()
    return render_template("admin/projects.html", projects=items)


@admin_bp.route("/projects/new", methods=["GET", "POST"])
@login_required
def project_new():
    form = ProjectForm()
    if request.method == "POST" and form.validate_on_submit():
        project = Project(
            title=form.title.data.strip(),
            slug=(form.slug.data or slugify(form.title.data)).lower(),
            client_name=form.client_name.data.strip() or None,
            category=form.category.data.strip() or "Consulting",
            summary=form.summary.data.strip(),
            challenge=form.challenge.data.strip() or None,
            services_delivered=form.services_delivered.data.strip() or None,
            solution=form.solution.data.strip() or None,
            outcomes=form.outcomes.data.strip() or None,
            featured_image=form.featured_image.data.strip() or None,
            gallery=form.gallery.data.strip() or None,
            seo_title=form.seo_title.data.strip() or form.title.data.strip(),
            seo_description=form.seo_description.data.strip(),
            status=form.status.data,
            is_featured=bool(request.form.get("is_featured")),
            published_at=datetime.now(timezone.utc) if form.status.data == "published" else None,
        )
        db.session.add(project)
        db.session.commit()
        flash("Project created.", "success")
        return redirect(url_for("admin.projects_admin"))
    return render_template("admin/project_form.html", form=form)


@admin_bp.route("/projects/<int:id>/edit", methods=["GET", "POST"])
@login_required
def project_edit(id):
    project = Project.query.get_or_404(id)
    form = ProjectForm(obj=project)
    if request.method == "POST" and form.validate_on_submit():
        project.title = form.title.data.strip()
        project.slug = (form.slug.data or slugify(form.title.data)).lower()
        project.client_name = form.client_name.data.strip() or None
        project.category = form.category.data.strip() or "Consulting"
        project.summary = form.summary.data.strip()
        project.challenge = form.challenge.data.strip() or None
        project.services_delivered = form.services_delivered.data.strip() or None
        project.solution = form.solution.data.strip() or None
        project.outcomes = form.outcomes.data.strip() or None
        project.featured_image = form.featured_image.data.strip() or None
        project.gallery = form.gallery.data.strip() or None
        project.seo_title = form.seo_title.data.strip() or project.title
        project.seo_description = form.seo_description.data.strip()
        project.status = form.status.data
        project.is_featured = bool(request.form.get("is_featured"))
        if form.status.data == "published" and project.published_at is None:
            project.published_at = datetime.now(timezone.utc)
        if form.status.data == "draft":
            project.published_at = None
        db.session.commit()
        flash("Project updated.", "success")
        return redirect(url_for("admin.projects_admin"))
    return render_template("admin/project_form.html", form=form, project=project)


@admin_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    settings = CompanySettings.get_settings()
    form = CompanySettingsForm(obj=settings)
    if request.method == "POST" and form.validate_on_submit():
        form.populate_obj(settings)
        settings.canonical_origin = settings.canonical_origin or current_app.config.get("CANONICAL_ORIGIN")
        write_instructor_audit(
            "academy_financial_settings_updated",
            "company_settings",
            settings.id,
            admin_id=current_user.id,
            details=f"commission_percent={settings.academy_commission_percent};minimum_payout_kobo={settings.academy_minimum_payout_kobo}",
        )
        db.session.commit()
        flash("Company settings updated.", "success")
        return redirect(url_for("admin.settings"))
    return render_template("admin/settings.html", form=form, settings=settings)


@admin_bp.cli.command("create-admin")
def create_admin_command():
    import click

    name = click.prompt("Full name")
    email = click.prompt("Email")
    password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
    if AdminUser.query.filter_by(email=email.lower()).first():
        click.echo("Admin already exists.")
        return
    user = AdminUser(name=name, email=email.lower(), role="admin", active=True)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    click.echo(f"Admin created: {email}")


@public_bp.app_errorhandler(404)
def public_not_found(error):
    return render_template("public/404.html"), 404


@public_bp.app_errorhandler(500)
def public_server_error(error):
    return render_template("public/500.html"), 500


@student_bp.before_request
def student_require_login():
    if request.endpoint in {"student.student_login", "student.student_register", "student.payment_webhook"}:
        if request.endpoint != "student.payment_webhook" and current_user.is_authenticated and not isinstance(current_user, Student):
            abort(403)
        return None
    if request.endpoint and request.endpoint.startswith("student"):
        if not current_user.is_authenticated:
            return redirect(url_for("student.student_login"))
        if not isinstance(current_user, Student):
            abort(403)


@admin_bp.before_request
def require_login():
    if request.endpoint and request.endpoint.startswith("admin") and request.endpoint not in {"admin.admin_login", "admin.admin_signup"}:
        if not current_user.is_authenticated:
            return redirect(url_for("admin.admin_login"))
        if not isinstance(current_user, AdminUser):
            abort(403)
