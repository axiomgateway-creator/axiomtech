from __future__ import annotations

from datetime import datetime, timezone

from flask import current_app
from flask_login import UserMixin
from sqlalchemy import UniqueConstraint
from werkzeug.security import check_password_hash, generate_password_hash

from . import db


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class AdminUser(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "admin_users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(50), default="admin", nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    last_login = db.Column(db.DateTime)

    def get_id(self):
        return f"admin:{self.id}"

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Student(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(60))
    profile_image = db.Column(db.String(255))
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    verification_token = db.Column(db.String(255))
    verification_expires_at = db.Column(db.DateTime)
    last_login_at = db.Column(db.DateTime)
    is_active_account = db.Column(db.Boolean, default=True, nullable=False)

    enrolments = db.relationship("CourseEnrollment", back_populates="student", cascade="all, delete-orphan")
    orders = db.relationship("AcademyOrder", back_populates="student", cascade="all, delete-orphan")
    certificates = db.relationship("AcademyCertificate", back_populates="student", cascade="all, delete-orphan")
    quiz_attempts = db.relationship("QuizAttempt", back_populates="student", cascade="all, delete-orphan")

    def get_id(self):
        return f"student:{self.id}"

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):
        return bool(self.is_active_account)


class CompanySettings(TimestampMixin, db.Model):
    __tablename__ = "company_settings"

    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(200), default="Axiom Gateway Consult", nullable=False)
    tagline = db.Column(db.String(200), default="Connecting People, Technology and Possibilities.", nullable=False)
    contact_email = db.Column(db.String(200), default="axiomgateway@gmail.com", nullable=False)
    telephone = db.Column(db.String(50), default="+2348081948464", nullable=False)
    office_address = db.Column(db.Text, default="No 13 Chu", nullable=False)
    instagram_url = db.Column(db.String(255), default="https://instagram.com/axiomgatway")
    whatsapp_url = db.Column(db.String(255), default="https://whatsapp.com/dl/")
    logo_url = db.Column(db.String(255), default="/static/images/logo.svg")
    favicon_url = db.Column(db.String(255), default="/static/images/favicon.svg")
    footer_text = db.Column(db.Text, default="Technology, digital skills and business consulting.")
    enquiry_notification_email = db.Column(db.String(200), default="axiomgateway@gmail.com")
    meta_description = db.Column(db.Text)
    canonical_origin = db.Column(db.String(255), default="http://localhost:5000")

    @staticmethod
    def get_settings():
        settings = CompanySettings.query.order_by(CompanySettings.id.desc()).first()
        if settings:
            return settings
        default = CompanySettings()
        db.session.add(default)
        db.session.commit()
        return default


class Service(TimestampMixin, db.Model):
    __tablename__ = "services"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(120), unique=True, nullable=False, index=True)
    short_description = db.Column(db.Text, nullable=False)
    full_description = db.Column(db.Text, nullable=False)
    icon = db.Column(db.String(50), default="fa-briefcase")
    display_order = db.Column(db.Integer, default=0, nullable=False)
    published = db.Column(db.Boolean, default=True, nullable=False)

    enquiries = db.relationship("Enquiry", back_populates="service")


class ArticleCategory(TimestampMixin, db.Model):
    __tablename__ = "article_categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(120), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)

    articles = db.relationship("Article", back_populates="category")


class CourseCategory(TimestampMixin, db.Model):
    __tablename__ = "course_categories"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(120), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)
    courses = db.relationship("Course", back_populates="category")


class Course(TimestampMixin, db.Model):
    __tablename__ = "courses"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False, index=True)
    short_description = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=False)
    cover_image = db.Column(db.String(255))
    category_id = db.Column(db.Integer, db.ForeignKey("course_categories.id"), nullable=True)
    category = db.relationship("CourseCategory", back_populates="courses")
    instructor_name = db.Column(db.String(120), default="Axiom Gateway Consult")
    difficulty = db.Column(db.String(30), default="Beginner")
    duration_hours = db.Column(db.Integer, default=1)
    language = db.Column(db.String(60), default="English")
    price = db.Column(db.Float, default=0.0)
    currency = db.Column(db.String(10), default="NGN")
    is_free = db.Column(db.Boolean, default=False, nullable=False)
    status = db.Column(db.String(20), default="draft", nullable=False)
    is_featured = db.Column(db.Boolean, default=False, nullable=False)
    certificate_eligible = db.Column(db.Boolean, default=True, nullable=False)
    objectives = db.Column(db.Text)
    prerequisites = db.Column(db.Text)
    published_at = db.Column(db.DateTime)
    lessons = db.relationship("CourseLesson", back_populates="course", cascade="all, delete-orphan")
    enrolments = db.relationship("CourseEnrollment", back_populates="course", cascade="all, delete-orphan")


class CourseLesson(TimestampMixin, db.Model):
    __tablename__ = "course_lessons"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), nullable=False)
    lesson_type = db.Column(db.String(40), default="text")
    content = db.Column(db.Text)
    external_video_url = db.Column(db.String(255))
    duration_minutes = db.Column(db.Integer, default=15)
    is_preview = db.Column(db.Boolean, default=False, nullable=False)
    order_index = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default="published", nullable=False)
    course = db.relationship("Course", back_populates="lessons")
    progress_entries = db.relationship("LessonProgress", back_populates="lesson", cascade="all, delete-orphan")

    __table_args__ = (db.UniqueConstraint("course_id", "slug", name="uq_course_lesson_slug"),)


class CourseEnrollment(TimestampMixin, db.Model):
    __tablename__ = "course_enrolments"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey("academy_orders.id"), nullable=True)
    status = db.Column(db.String(30), default="active", nullable=False)
    progress = db.Column(db.Float, default=0.0, nullable=False)
    last_lesson_id = db.Column(db.Integer, db.ForeignKey("course_lessons.id"), nullable=True)
    completed_at = db.Column(db.DateTime)
    source = db.Column(db.String(40), default="purchase")
    expiry_at = db.Column(db.DateTime)
    student = db.relationship("Student", back_populates="enrolments")
    course = db.relationship("Course", back_populates="enrolments")
    order = db.relationship("AcademyOrder", back_populates="enrolment")
    lesson_progress = db.relationship("LessonProgress", back_populates="enrolment", cascade="all, delete-orphan")

    __table_args__ = (db.UniqueConstraint("student_id", "course_id", name="uq_student_course_enrollment"),)


class LessonProgress(TimestampMixin, db.Model):
    __tablename__ = "lesson_progress"

    id = db.Column(db.Integer, primary_key=True)
    enrolment_id = db.Column(db.Integer, db.ForeignKey("course_enrolments.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    lesson_id = db.Column(db.Integer, db.ForeignKey("course_lessons.id"), nullable=False)
    completed = db.Column(db.Boolean, default=False, nullable=False)
    completed_at = db.Column(db.DateTime)
    enrolment = db.relationship("CourseEnrollment", back_populates="lesson_progress")
    lesson = db.relationship("CourseLesson", back_populates="progress_entries")

    __table_args__ = (db.UniqueConstraint("student_id", "lesson_id", name="uq_student_lesson_progress"),)


class Quiz(TimestampMixin, db.Model):
    __tablename__ = "quizzes"

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey("course_lessons.id"), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    instructions = db.Column(db.Text)
    pass_mark = db.Column(db.Float, default=70.0)
    attempt_limit = db.Column(db.Integer, default=3)
    status = db.Column(db.String(20), default="published", nullable=False)
    questions = db.relationship("QuizQuestion", back_populates="quiz", cascade="all, delete-orphan")
    attempts = db.relationship("QuizAttempt", back_populates="quiz", cascade="all, delete-orphan")


class QuizQuestion(TimestampMixin, db.Model):
    __tablename__ = "quiz_questions"

    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey("quizzes.id"), nullable=False)
    question_type = db.Column(db.String(40), default="multiple_choice", nullable=False)
    prompt = db.Column(db.Text, nullable=False)
    points = db.Column(db.Float, default=1.0)
    order_index = db.Column(db.Integer, default=0)
    quiz = db.relationship("Quiz", back_populates="questions")
    options = db.relationship("QuizOption", back_populates="question", cascade="all, delete-orphan")
    responses = db.relationship("QuizAnswer", back_populates="question", cascade="all, delete-orphan")


class QuizOption(TimestampMixin, db.Model):
    __tablename__ = "quiz_options"

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey("quiz_questions.id"), nullable=False)
    option_text = db.Column(db.Text, nullable=False)
    is_correct = db.Column(db.Boolean, default=False, nullable=False)
    question = db.relationship("QuizQuestion", back_populates="options")


class QuizAttempt(TimestampMixin, db.Model):
    __tablename__ = "quiz_attempts"

    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey("quizzes.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    submitted_at = db.Column(db.DateTime)
    score = db.Column(db.Float, default=0.0)
    passed = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default="in_progress", nullable=False)
    quiz = db.relationship("Quiz", back_populates="attempts")
    student = db.relationship("Student", back_populates="quiz_attempts")
    answers = db.relationship("QuizAnswer", back_populates="attempt", cascade="all, delete-orphan")


class QuizAnswer(TimestampMixin, db.Model):
    __tablename__ = "quiz_answers"

    id = db.Column(db.Integer, primary_key=True)
    attempt_id = db.Column(db.Integer, db.ForeignKey("quiz_attempts.id"), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey("quiz_questions.id"), nullable=False)
    selected_option_ids = db.Column(db.Text)
    free_text = db.Column(db.Text)
    attempt = db.relationship("QuizAttempt", back_populates="answers")
    question = db.relationship("QuizQuestion", back_populates="responses")


class AcademyProduct(TimestampMixin, db.Model):
    __tablename__ = "academy_products"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False, index=True)
    short_description = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=False)
    cover_image = db.Column(db.String(255))
    category = db.Column(db.String(120), default="Digital Resource")
    price = db.Column(db.Float, default=0.0)
    currency = db.Column(db.String(10), default="NGN")
    is_free = db.Column(db.Boolean, default=False, nullable=False)
    status = db.Column(db.String(20), default="draft", nullable=False)
    file_path = db.Column(db.String(255))
    published_at = db.Column(db.DateTime)
    orders = db.relationship("AcademyOrder", back_populates="product")


class AcademyOrder(TimestampMixin, db.Model):
    __tablename__ = "academy_orders"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    item_type = db.Column(db.String(40), nullable=False)
    item_id = db.Column(db.Integer, nullable=False)
    amount = db.Column(db.Float, default=0.0, nullable=False)
    currency = db.Column(db.String(10), default="NGN", nullable=False)
    status = db.Column(db.String(30), default="pending", nullable=False)
    reference = db.Column(db.String(80), unique=True, nullable=False, index=True)
    provider_reference = db.Column(db.String(120))
    receipt_path = db.Column(db.String(255))
    receipt_uploaded_at = db.Column(db.DateTime)
    receipt_reviewed_at = db.Column(db.DateTime)
    receipt_review_note = db.Column(db.Text)
    reviewed_by_admin_id = db.Column(db.Integer, db.ForeignKey("admin_users.id"), nullable=True)
    product_id = db.Column(db.Integer, db.ForeignKey("academy_products.id"), nullable=True)
    product = db.relationship("AcademyProduct", back_populates="orders")
    student = db.relationship("Student", back_populates="orders")
    reviewed_by = db.relationship("AdminUser", foreign_keys=[reviewed_by_admin_id])
    enrolment = db.relationship("CourseEnrollment", back_populates="order", uselist=False)
    payment_events = db.relationship("PaymentEvent", back_populates="order", cascade="all, delete-orphan")


class PaymentEvent(TimestampMixin, db.Model):
    __tablename__ = "payment_events"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("academy_orders.id"), nullable=False)
    provider = db.Column(db.String(60), default="paystack")
    event_type = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(30), default="received")
    payload = db.Column(db.Text)
    order = db.relationship("AcademyOrder", back_populates="payment_events")


class AcademyCertificate(TimestampMixin, db.Model):
    __tablename__ = "academy_certificates"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)
    certificate_number = db.Column(db.String(80), unique=True, nullable=False, index=True)
    verification_code = db.Column(db.String(80), unique=True, nullable=False, index=True)
    issue_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    status = db.Column(db.String(20), default="issued", nullable=False)
    student = db.relationship("Student", back_populates="certificates")
    course = db.relationship("Course")


class Article(TimestampMixin, db.Model):
    __tablename__ = "articles"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False, index=True)
    excerpt = db.Column(db.Text, nullable=False)
    body = db.Column(db.Text, nullable=False)
    cover_image = db.Column(db.String(255))
    category_id = db.Column(db.Integer, db.ForeignKey("article_categories.id"), nullable=True)
    author_name = db.Column(db.String(120), default="Axiom Gateway Consult")
    seo_title = db.Column(db.String(200))
    seo_description = db.Column(db.Text)
    status = db.Column(db.String(20), default="draft", nullable=False)
    published_at = db.Column(db.DateTime)
    category = db.relationship("ArticleCategory", back_populates="articles")


class Project(TimestampMixin, db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False, index=True)
    client_name = db.Column(db.String(200))
    category = db.Column(db.String(120), default="Consulting")
    summary = db.Column(db.Text, nullable=False)
    challenge = db.Column(db.Text)
    services_delivered = db.Column(db.Text)
    solution = db.Column(db.Text)
    outcomes = db.Column(db.Text)
    featured_image = db.Column(db.String(255))
    gallery = db.Column(db.Text)
    seo_title = db.Column(db.String(200))
    seo_description = db.Column(db.Text)
    status = db.Column(db.String(20), default="draft", nullable=False)
    published_at = db.Column(db.DateTime)
    is_featured = db.Column(db.Boolean, default=False)


class Enquiry(TimestampMixin, db.Model):
    __tablename__ = "enquiries"

    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(50), unique=True, index=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    organization = db.Column(db.String(160))
    email = db.Column(db.String(160), nullable=False, index=True)
    telephone = db.Column(db.String(60), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=True)
    enquiry_type = db.Column(db.String(40), default="General", nullable=False)
    description = db.Column(db.Text, nullable=False)
    preferred_contact = db.Column(db.String(30), default="Email")
    consent = db.Column(db.Boolean, default=False, nullable=False)
    status = db.Column(db.String(30), default="New", nullable=False)
    internal_notes = db.Column(db.Text)
    assigned_admin_id = db.Column(db.Integer, db.ForeignKey("admin_users.id"), nullable=True)
    assigned_admin = db.relationship("AdminUser", foreign_keys=[assigned_admin_id])
    service = db.relationship("Service", back_populates="enquiries")

    __table_args__ = (UniqueConstraint("reference", name="uq_enquiry_reference"),)

    @staticmethod
    def next_reference():
        latest = Enquiry.query.order_by(Enquiry.id.desc()).first()
        if not latest:
            return "AXIOM-1001"
        number = int(latest.reference.split("-")[-1]) + 1
        return f"AXIOM-{number}"
