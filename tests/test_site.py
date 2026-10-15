import re
import hashlib
import hmac
import io
import json

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app import db
from app.models import (
    AcademyOrder,
    AcademyProduct,
    AcademyCertificate,
    AdminUser,
    Article,
    CompanySettings,
    Course,
    CourseCategory,
    CourseEnrollment,
    CourseLesson,
    Instructor,
    InstructorEarning,
    InstructorPayoutAllocation,
    InstructorPayoutRequest,
    InstructorReversal,
    PaymentEvent,
    InstructorEarning,
    Quiz,
    QuizOption,
    QuizQuestion,
    Service,
    Student,
)
from app.routes import record_instructor_earning


def add_test_courses(app):
    with app.app_context():
        category = CourseCategory(name="Test Courses", slug="test-courses")
        db.session.add(category)
        web_development = Course(
            title="Web Development",
            slug="web-development",
            short_description="Build practical website design and development skills.",
            description="<p>Learn the foundations of modern web development.</p>",
            category=category,
            price=25000,
            currency="NGN",
            status="published",
        )
        digital_marketing = Course(
            title="Digital Marketing",
            slug="digital-marketing",
            short_description="Plan and deliver effective digital marketing campaigns.",
            description="<p>Learn the foundations of digital marketing.</p>",
            category=category,
            price=25000,
            currency="NGN",
            status="published",
        )
        db.session.add_all([web_development, digital_marketing])
        db.session.flush()
        for order_index, title in enumerate(["Introduction", "Core concepts", "Practical application"], start=1):
            db.session.add(
                CourseLesson(
                    course_id=web_development.id,
                    title=title,
                    slug=f"web-development-{title.lower().replace(' ', '-')}",
                    lesson_type="text",
                    content=f"<p>Lesson content for {title}.</p>",
                    order_index=order_index,
                    status="published",
                )
            )
        db.session.commit()


@pytest.fixture
def client():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    add_test_courses(app)
    with app.test_client() as client:
        yield client


def test_app_startup_does_not_seed_content():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        assert Course.query.count() == 0
        assert CourseCategory.query.count() == 0


def test_password_hashing_works_without_hashlib_scrypt(monkeypatch):
    instructor = Instructor(
        full_name="Hash Test Instructor",
        email="hash-test@example.com",
        professional_title="Trainer",
        biography="Experienced instructor.",
        subject_areas="Training",
    )
    instructor.set_password("StrongPass123")
    assert instructor.password_hash.startswith("pbkdf2:sha256:")
    assert instructor.check_password("StrongPass123")
    assert not instructor.check_password("WrongPass123")
    pbkdf2_hash = instructor.password_hash

    legacy_scrypt_hash = generate_password_hash(
        "LegacyPass123",
        method="scrypt:1024:8:1",
    )
    monkeypatch.delattr(hashlib, "scrypt")
    instructor.password_hash = pbkdf2_hash
    assert instructor.check_password("StrongPass123")

    instructor.password_hash = legacy_scrypt_hash
    assert instructor.check_password("LegacyPass123")
    assert not instructor.check_password("WrongPass123")


def test_instructor_application_approval_course_review_and_ownership():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    instructor_client = app.test_client()
    application = instructor_client.post("/academy/instructor/register", data={
        "full_name": "Amina Instructor",
        "email": "amina@example.com",
        "phone": "08000000000",
        "professional_title": "Web developer",
        "biography": "Experienced developer and educator with a long history of practical teaching.",
        "teaching_experience": "Delivered professional workshops.",
        "qualifications": "BSc Computer Science",
        "subject_areas": "Web development, design systems",
        "password": "StrongPass123",
        "confirm_password": "StrongPass123",
        "terms_accepted": "y",
    })
    assert application.status_code == 302
    assert b"awaiting review" in instructor_client.get("/academy/instructor/dashboard").data.lower()
    assert instructor_client.get("/academy/instructor/courses").status_code == 403

    with app.app_context():
        admin = AdminUser(name="Review Admin", email="review-admin@example.com", role="admin", active=True)
        admin.set_password("StrongAdmin123")
        db.session.add(admin)
        db.session.commit()
        instructor = Instructor.query.filter_by(email="amina@example.com").first()
        instructor_id = instructor.id

    admin_client = app.test_client()
    assert admin_client.post("/admin/login", data={"email": "review-admin@example.com", "password": "StrongAdmin123"}).status_code == 302
    assert admin_client.get("/admin/instructors").status_code == 200
    decision = admin_client.post(f"/admin/instructors/{instructor_id}/decision", data={"decision": "approved", "reason": "Credentials reviewed"})
    assert decision.status_code == 302
    assert instructor_client.get("/academy/instructor/courses").status_code == 200
    for portal_path in [
        "/academy/instructor/dashboard",
        "/academy/instructor/students",
        "/academy/instructor/earnings",
        "/academy/instructor/analytics",
        "/academy/instructor/notifications",
        "/academy/instructor/profile",
    ]:
        assert instructor_client.get(portal_path).status_code == 200, portal_path

    course_response = instructor_client.post("/academy/instructor/courses/new", data={
        "title": "Practical Web Systems",
        "slug": "practical-web-systems",
        "short_description": "Build a practical web application.",
        "description": "A complete course description for a practical web application course.",
        "difficulty": "Beginner",
        "duration_hours": "12",
        "language": "English",
        "price": "12000",
        "action": "save",
    })
    assert course_response.status_code == 302
    with app.app_context():
        course = Course.query.filter_by(slug="practical-web-systems").first()
        assert course.instructor_id == instructor_id
        assert course.status == "draft"
        assert course.review_status == "draft"
        course_id = course.id
        second = Instructor(
            full_name="Other Instructor",
            email="other@example.com",
            professional_title="Consultant",
            biography="A qualified instructor with extensive professional teaching experience.",
            subject_areas="Consulting",
            status="approved",
        )
        second.set_password("StrongPass123")
        db.session.add(second)
        db.session.commit()

    lesson_response = instructor_client.post(f"/academy/instructor/courses/{course_id}/lessons", data={
        "title": "First module",
        "content": "Course foundations and learning objectives.",
        "lesson_type": "text",
        "duration_minutes": "20",
        "order_index": "1",
    })
    assert lesson_response.status_code == 302
    with app.app_context():
        lesson = CourseLesson.query.filter_by(course_id=course_id).one()
        lesson_id = lesson.id
    edit_lesson_response = instructor_client.post(
        f"/academy/instructor/courses/{course_id}/lessons/{lesson_id}/edit",
        data={
            "title": "First module revised",
            "slug": "first-module-revised",
            "module_title": "Getting started",
            "content": "<p>Updated course foundations.</p>",
            "lesson_type": "text",
            "duration_minutes": "25",
            "order_index": "2",
            "is_preview": "on",
        },
    )
    assert edit_lesson_response.status_code == 302
    quiz_response = instructor_client.post(
        f"/academy/instructor/courses/{course_id}/quizzes",
        data={
            "title": "Foundations check",
            "instructions": "Choose the correct answer.",
            "pass_mark": "70",
            "attempt_limit": "2",
            "prompt_1": "Which is a web standard?",
            "option_1_a": "HTML",
            "option_1_b": "A random value",
            "correct_1": "a",
        },
    )
    assert quiz_response.status_code == 302
    with app.app_context():
        quiz = Quiz.query.filter_by(course_id=course_id).one()
        assert quiz.status == "draft"
        assert CourseLesson.query.get(lesson_id).title == "First module revised"
    course_response = instructor_client.post(f"/academy/instructor/courses/{course_id}/edit", data={
        "title": "Practical Web Systems",
        "slug": "practical-web-systems",
        "short_description": "Build a practical web application.",
        "description": "A complete course description for a practical web application course.",
        "difficulty": "Beginner",
        "duration_hours": "12",
        "language": "English",
        "price": "12000",
        "action": "submit",
    })
    assert course_response.status_code == 302
    with app.app_context():
        course = db.session.get(Course, course_id)
        assert course.review_status == "submitted"

    assert admin_client.get("/admin/instructors").status_code == 200
    assert admin_client.post(f"/admin/instructor-courses/{course_id}/decision", data={"decision": "approved"}).status_code == 302
    assert instructor_client.get("/academy/courses/practical-web-systems").status_code == 200
    with app.app_context():
        assert CourseLesson.query.filter_by(id=lesson_id).first().status == "published"
        assert Quiz.query.filter_by(course_id=course_id).one().status == "published"

    other_client = app.test_client()
    assert other_client.post("/academy/instructor/login", data={"email": "other@example.com", "password": "StrongPass123"}).status_code == 302
    assert other_client.get(f"/academy/instructor/courses/{course_id}/edit").status_code == 404


def test_free_instructor_course_enrollment_creates_no_order():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        instructor = Instructor(
            full_name="Free Course Instructor",
            email="free-instructor@example.com",
            professional_title="Educator",
            biography="An experienced instructor with practical course delivery experience.",
            subject_areas="Professional development",
            status="approved",
        )
        instructor.set_password("StrongPass123")
        db.session.add(instructor)
        db.session.flush()
        course = Course(
            title="Open Learning",
            slug="open-learning",
            short_description="A free learning course.",
            description="Free course details.",
            instructor_id=instructor.id,
            instructor_name=instructor.full_name,
            is_free=True,
            price=0,
            status="published",
        )
        db.session.add(course)
        db.session.commit()
        course_id = course.id

    client = app.test_client()
    register_student(client, email="free-student@example.com")
    response = client.post(f"/student/checkout/{course_id}")
    assert response.status_code == 302
    assert response.location.endswith("/student/courses/open-learning")
    with app.app_context():
        student = Student.query.filter_by(email="free-student@example.com").first()
        enrollment = CourseEnrollment.query.filter_by(student_id=student.id, course_id=course_id).first()
        assert enrollment.status == "active"
        assert enrollment.source == "free"
        assert AcademyOrder.query.filter_by(student_id=student.id, item_id=course_id, item_type="course").count() == 0


def test_admission_certificate_pdf_and_revocation_verification():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        instructor = Instructor(
            full_name="Certificate Instructor",
            email="certificate-instructor@example.com",
            professional_title="Trainer",
            biography="An experienced instructor with practical teaching experience.",
            subject_areas="Training",
            status="approved",
        )
        instructor.set_password("StrongPass123")
        student = Student(full_name="Certificate Student", email="certificate-student@example.com")
        student.set_password("StrongPass123")
        db.session.add_all([instructor, student])
        db.session.flush()
        course = Course(
            title="Verified Learning",
            slug="verified-learning",
            short_description="Course summary.",
            description="Course details.",
            instructor_id=instructor.id,
            instructor_name=instructor.full_name,
            status="published",
        )
        db.session.add(course)
        db.session.flush()
        enrollment = CourseEnrollment(student_id=student.id, course_id=course.id, status="active")
        db.session.add(enrollment)
        db.session.commit()
        enrollment_id = enrollment.id
        instructor_email = instructor.email

    client = app.test_client()
    assert client.post("/academy/instructor/login", data={"email": instructor_email, "password": "StrongPass123"}).status_code == 302
    pdf_response = client.post(f"/academy/instructor/students/{enrollment_id}/admission-certificate", follow_redirects=True)
    assert pdf_response.status_code == 200
    assert pdf_response.mimetype == "application/pdf"
    assert pdf_response.data.startswith(b"%PDF")
    with app.app_context():
        certificate = AcademyCertificate.query.filter_by(certificate_type="admission").first()
        certificate_id = certificate.id
        verification_code = certificate.verification_code
    valid_response = client.post("/academy/certificates/verify", data={"code": verification_code})
    assert b"Certificate is valid" in valid_response.data
    certificates_page = client.get("/academy/instructor/certificates")
    assert certificates_page.status_code == 200
    assert b"Admission" in certificates_page.data
    assert b"Revocation reason" in certificates_page.data
    revoke_response = client.post(f"/academy/instructor/certificates/{certificate_id}/revoke", data={"reason": "Admission record corrected"})
    assert revoke_response.status_code == 302
    revoked_response = client.post("/academy/certificates/verify", data={"code": verification_code})
    assert b"Certificate has been revoked" in revoked_response.data


def test_instructor_earnings_are_idempotent_and_use_kobo():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        instructor = Instructor(
            full_name="Earnings Instructor",
            email="earnings-instructor@example.com",
            professional_title="Trainer",
            biography="An experienced instructor with practical teaching experience.",
            subject_areas="Training",
            status="approved",
        )
        instructor.set_password("StrongPass123")
        student = Student(full_name="Paying Student", email="paying-student@example.com")
        student.set_password("StrongPass123")
        settings = CompanySettings(academy_commission_percent=10)
        db.session.add_all([instructor, student, settings])
        db.session.flush()
        course = Course(title="Paid Course", slug="paid-course", short_description="Paid summary", description="Paid course details", instructor_id=instructor.id)
        db.session.add(course)
        db.session.flush()
        order = AcademyOrder(student_id=student.id, item_type="course", item_id=course.id, amount=125.50, currency="NGN", status="paid", reference="AXM-EARNINGS-1")
        db.session.add(order)
        db.session.flush()
        record_instructor_earning(order, course, {"fees": 125})
        record_instructor_earning(order, course, {"fees": 125})
        db.session.commit()
        earning = InstructorEarning.query.filter_by(order_id=order.id).one()
        assert earning.gross_kobo == 12550
        assert earning.gateway_fee_kobo == 125
        assert earning.commission_kobo == 1255
        assert earning.instructor_share_kobo == 11170
        assert InstructorEarning.query.count() == 1


def test_instructor_lesson_material_is_private_and_html_is_sanitized(tmp_path):
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    app.config["UPLOAD_FOLDER"] = str(tmp_path / "private-academy")
    with app.app_context():
        instructor = Instructor(
            full_name="Materials Instructor",
            email="materials-instructor@example.com",
            professional_title="Trainer",
            biography="An experienced instructor with practical teaching experience.",
            subject_areas="Training",
            status="approved",
        )
        instructor.set_password("StrongPass123")
        enrolled_student = Student(full_name="Enrolled Learner", email="enrolled-materials@example.com")
        enrolled_student.set_password("StrongPass123")
        other_student = Student(full_name="Other Learner", email="other-materials@example.com")
        other_student.set_password("StrongPass123")
        db.session.add_all([instructor, enrolled_student, other_student])
        db.session.flush()
        course = Course(title="Private Materials", slug="private-materials", short_description="Summary", description="Description", instructor_id=instructor.id, status="published")
        db.session.add(course)
        db.session.flush()
        enrollment = CourseEnrollment(student_id=enrolled_student.id, course_id=course.id, status="active")
        db.session.add(enrollment)
        db.session.commit()
        instructor_email = instructor.email
        enrolled_email = enrolled_student.email
        other_email = other_student.email
        course_id = course.id

    instructor_client = app.test_client()
    assert instructor_client.post("/academy/instructor/login", data={"email": instructor_email, "password": "StrongPass123"}).status_code == 302
    response = instructor_client.post(
        f"/academy/instructor/courses/{course_id}/lessons",
        data={
            "title": "Reference notes",
            "content": "<script>alert(1)</script><p>Safe notes</p>",
            "lesson_type": "text",
            "duration_minutes": "10",
            "resource": (io.BytesIO(b"%PDF-1.7\nprivate note bytes"), "notes.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    with app.app_context():
        lesson = CourseLesson.query.filter_by(course_id=course_id).one()
        assert "<script>" not in lesson.content
        lesson.status = "published"
        db.session.commit()
        lesson_id = lesson.id
        stored_path = tmp_path / "private-academy" / lesson.resource_path
        assert stored_path.is_file()
        assert "static" not in lesson.resource_path

    instructor_download = instructor_client.get(f"/academy/instructor/courses/{course_id}/materials/{lesson_id}")
    assert instructor_download.status_code == 200
    assert instructor_download.data.startswith(b"%PDF")
    enrolled_client = app.test_client()
    assert enrolled_client.post("/student/login", data={"email": enrolled_email, "password": "StrongPass123"}, follow_redirects=True).status_code == 200
    student_download = enrolled_client.get(f"/academy/instructor/courses/{course_id}/materials/{lesson_id}")
    assert student_download.status_code == 200
    other_client = app.test_client()
    assert other_client.post("/student/login", data={"email": other_email, "password": "StrongPass123"}, follow_redirects=True).status_code == 200
    assert other_client.get(f"/academy/instructor/courses/{course_id}/materials/{lesson_id}").status_code == 404


def test_paid_course_uses_paystack_and_preserves_order_amount(monkeypatch):
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "PAYSTACK_SECRET_KEY": "test-key"})
    with app.app_context():
        course = Course(title="Paystack Course", slug="paystack-course", short_description="Summary", description="Description", price=12500, currency="NGN", status="published")
        db.session.add(course)
        db.session.commit()
        course_id = course.id

    monkeypatch.setattr("app.routes.initialize_paystack_payment", lambda _order: "https://paystack.test/authorize")
    client = app.test_client()
    register_student(client, email="paystack-student@example.com")
    response = client.post(f"/student/checkout/{course_id}")
    assert response.status_code == 302
    assert response.location == "https://paystack.test/authorize"
    with app.app_context():
        order = AcademyOrder.query.filter_by(student_id=Student.query.filter_by(email="paystack-student@example.com").first().id, item_type="course", item_id=course_id).one()
        assert order.amount == 12500
        course = db.session.get(Course, course_id)
        course.price = 18000
        db.session.commit()
        assert db.session.get(AcademyOrder, order.id).amount == 12500


def test_payout_rejection_releases_only_allocated_earnings():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    app.config["SECRET_KEY"] = "unique-test-key-for-payout-encryption"
    with app.app_context():
        first = Instructor(full_name="First Payout Instructor", email="first-payout@example.com", professional_title="Trainer", biography="An experienced instructor with practical teaching experience.", subject_areas="Teaching", status="approved")
        first.set_password("StrongPass123")
        other = Instructor(full_name="Other Payout Instructor", email="other-payout@example.com", professional_title="Trainer", biography="An experienced instructor with practical teaching experience.", subject_areas="Teaching", status="approved")
        other.set_password("StrongPass123")
        admin = AdminUser(name="Payout Admin", email="payout-admin@example.com", role="admin", active=True)
        admin.set_password("StrongAdmin123")
        student = Student(full_name="Payout Learner", email="payout-learner@example.com")
        student.set_password("StrongPass123")
        db.session.add_all([first, other, admin, student])
        db.session.flush()
        first_course = Course(title="First Payout Course", slug="first-payout-course", short_description="Summary", description="Details", instructor_id=first.id)
        other_course = Course(title="Other Payout Course", slug="other-payout-course", short_description="Summary", description="Details", instructor_id=other.id)
        db.session.add_all([first_course, other_course])
        db.session.flush()
        first_order = AcademyOrder(student_id=student.id, item_type="course", item_id=first_course.id, amount=50, currency="NGN", status="paid", reference="AXM-PAYOUT-FIRST")
        other_order = AcademyOrder(student_id=student.id, item_type="course", item_id=other_course.id, amount=25, currency="NGN", status="paid", reference="AXM-PAYOUT-OTHER")
        db.session.add_all([first_order, other_order])
        db.session.flush()
        first_earning = InstructorEarning(instructor_id=first.id, order_id=first_order.id, gross_kobo=5000, commission_kobo=0, instructor_share_kobo=5000, payout_status="requested")
        other_earning = InstructorEarning(instructor_id=other.id, order_id=other_order.id, gross_kobo=2500, commission_kobo=0, instructor_share_kobo=2500, payout_status="requested")
        db.session.add_all([first_earning, other_earning])
        db.session.flush()
        payout = InstructorPayoutRequest(instructor_id=first.id, amount_kobo=5000, status="pending")
        db.session.add(payout)
        db.session.flush()
        db.session.add(InstructorPayoutAllocation(payout_request_id=payout.id, earning_id=first_earning.id, amount_kobo=5000))
        payout_id = payout.id
        first_earning_id, other_earning_id = first_earning.id, other_earning.id
        db.session.commit()

    admin_client = app.test_client()
    assert admin_client.post("/admin/login", data={"email": "payout-admin@example.com", "password": "StrongAdmin123"}).status_code == 302
    response = admin_client.post(f"/admin/instructor-payouts/{payout_id}/decision", data={"decision": "rejected", "note": "Please confirm account details"})
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(InstructorEarning, first_earning_id).payout_status == "available"
        assert db.session.get(InstructorEarning, other_earning_id).payout_status == "requested"

    instructor_client = app.test_client()
    assert instructor_client.post("/academy/instructor/login", data={"email": "first-payout@example.com", "password": "StrongPass123"}).status_code == 302
    profile_response = instructor_client.post("/academy/instructor/payout-profile", data={
        "bank_name": "Test Bank",
        "account_name": "First Payout Instructor",
        "account_number": "0123456789",
        "bank_code": "001",
    })
    assert profile_response.status_code == 302
    with app.app_context():
        saved_instructor = Instructor.query.filter_by(email="first-payout@example.com").first()
        assert saved_instructor.payout_account_number_encrypted != "0123456789"
    retry_response = instructor_client.post("/academy/instructor/earnings", data={"amount": "50.00"})
    assert retry_response.status_code == 302
    with app.app_context():
        assert InstructorPayoutRequest.query.filter_by(instructor_id=Instructor.query.filter_by(email="first-payout@example.com").first().id).count() == 2
        assert InstructorPayoutAllocation.query.count() == 1
    admin_page = admin_client.get("/admin/instructors")
    assert b"0123456789" in admin_page.data


def test_verified_instructor_order_reversal_is_idempotent():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        instructor = Instructor(full_name="Refund Instructor", email="refund-instructor@example.com", professional_title="Trainer", biography="An experienced instructor with practical teaching experience.", subject_areas="Teaching", status="approved")
        instructor.set_password("StrongPass123")
        student = Student(full_name="Refund Learner", email="refund-student@example.com")
        student.set_password("StrongPass123")
        admin = AdminUser(name="Refund Admin", email="refund-admin@example.com", role="admin", active=True)
        admin.set_password("StrongAdmin123")
        db.session.add_all([instructor, student, admin, CompanySettings(academy_commission_percent=10)])
        db.session.flush()
        course = Course(title="Refund Course", slug="refund-course", short_description="Summary", description="Details", instructor_id=instructor.id)
        db.session.add(course)
        db.session.flush()
        order = AcademyOrder(student_id=student.id, item_type="course", item_id=course.id, amount=100, currency="NGN", status="paid", reference="AXM-REFUND-1")
        db.session.add(order)
        db.session.flush()
        db.session.add(PaymentEvent(order_id=order.id, provider="paystack", event_type="charge.success", status="verified", payload="{}"))
        record_instructor_earning(order, course)
        order_id = order.id
        db.session.commit()

    admin_client = app.test_client()
    assert admin_client.post("/admin/login", data={"email": "refund-admin@example.com", "password": "StrongAdmin123"}).status_code == 302
    review_page = admin_client.get("/admin/instructors")
    assert b"Verified course orders" in review_page.data
    response = admin_client.post(f"/admin/instructor-orders/{order_id}/reverse", data={"reason": "Customer refund approved"})
    assert response.status_code == 302
    with app.app_context():
        assert db.session.get(AcademyOrder, order_id).status == "refunded"
        assert InstructorReversal.query.filter_by(order_id=order_id).count() == 1
        earning = InstructorEarning.query.filter_by(order_id=order_id).one()
        assert earning.payout_status == "reversed"
        assert earning.instructor_share_kobo == 9000


def test_homepage_loads(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Axiom Gateway Consult" in response.data.lower() or b"Empowering People" in response.data


def test_homepage_uses_distinct_images_for_services(client):
    services = [
        ("Digital Solutions", "digital-solutions-it", "image4.png"),
        ("People Development", "human-resource-organizational-development", "image6.png"),
        ("Business Consulting", "business-management-consulting", "image7.png"),
        ("Digital Marketing", "digital-marketing-creative", "image5.png"),
        ("Data Analytics", "data-analytics-business-intelligence", "image.png"),
    ]
    with client.application.app_context():
        db.session.add_all(
            Service(name=name, slug=slug, short_description="Service overview", full_description="Service details")
            for name, slug, _image in services
        )
        db.session.commit()

    response = client.get("/")
    assert response.status_code == 200
    for name, _slug, image in services:
        assert f'src="/static/images/{image}" alt="{name}"'.encode() in response.data


def test_services_page_shows_service_items_and_distinct_images(client):
    services = [
        ("Digital Solutions and IT Services", "digital-solutions-it", "image4.png"),
        ("Human Resource and Organizational Development", "human-resource-organizational-development", "image6.png"),
        ("Business and Management Consulting", "business-management-consulting", "image7.png"),
        ("Digital Marketing and Creative Services", "digital-marketing-creative", "image5.png"),
        ("Data Analytics and Business Intelligence", "data-analytics-business-intelligence", "image.png"),
    ]
    with client.application.app_context():
        db.session.add_all(
            Service(name=name, slug=slug, short_description="Service overview", full_description="Service details")
            for name, slug, _image in services
        )
        db.session.commit()

    response = client.get("/services")
    assert response.status_code == 200
    for name, _slug, image in services:
        assert f'src="/static/images/{image}" alt="{name}"'.encode() in response.data
        assert f"<h2 class=\"text-2xl font-bold text-slate-900 mb-3\">{name}</h2>".encode() in response.data
    assert b"A focused portfolio of solutions for private organizations" in response.data
    assert b"Web design &amp; development" in response.data
    assert b"Web development" in response.data
    assert b"Business portals" in response.data
    assert b"Cloud hosting support" in response.data
    assert b"Training needs assessment" in response.data
    assert b"Workforce development" in response.data
    assert b"Team building" in response.data
    assert b"Business planning" in response.data
    assert b"Project advisory" in response.data
    assert b"Process improvement" in response.data
    assert b"Brand identity" in response.data
    assert b"SEO support" in response.data
    assert b"Creative content" in response.data
    assert b"Turn insights into action" in response.data
    assert b"Dashboard reporting" in response.data
    assert b"Performance analysis" in response.data
    assert b'href="/academy/instructor/login"' in response.data
    assert b'href="/academy/instructor/register"' in response.data


def test_instructor_login_and_account_creation_pages_render(client):
    login_response = client.get("/academy/instructor/login")
    register_response = client.get("/academy/instructor/register")

    assert login_response.status_code == 200
    assert b"Instructor sign in" in login_response.data
    assert b"Apply as an instructor" in login_response.data
    assert register_response.status_code == 200
    assert b"Apply to teach" in register_response.data
    assert b"Already applied?" in register_response.data


def test_admin_requires_login(client):
    response = client.get("/admin")
    assert response.status_code == 302


def test_first_admin_signup_requires_setup_key_and_is_one_time():
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "ADMIN_SETUP_KEY": "private-admin-bootstrap-key",
    })
    client = app.test_client()
    assert client.get("/admin/signup").status_code == 200

    invalid = client.post("/admin/signup", data={
        "name": "Site Administrator",
        "email": "owner@example.com",
        "setup_key": "incorrect-key",
        "password": "StrongAdminPass123",
        "confirm_password": "StrongAdminPass123",
    })
    assert invalid.status_code == 200
    with app.app_context():
        assert AdminUser.query.count() == 0

    created = client.post("/admin/signup", data={
        "name": "Site Administrator",
        "email": "Owner@Example.com",
        "setup_key": "private-admin-bootstrap-key",
        "password": "StrongAdminPass123",
        "confirm_password": "StrongAdminPass123",
    })
    assert created.status_code == 302
    assert created.headers["Location"].endswith("/admin")
    with app.app_context():
        admin = AdminUser.query.one()
        assert admin.email == "owner@example.com"
        assert admin.active
        assert admin.check_password("StrongAdminPass123")
    assert client.get("/admin/signup").status_code == 404


def test_contact_form_validates_email(client):
    response = client.post(
        "/contact",
        data={
            "full_name": "Test User",
            "email": "not-an-email",
            "telephone": "08000000000",
            "service": "digital-solutions-it",
            "enquiry_type": "General",
            "description": "Test description",
            "preferred_contact": "Email",
            "consent": "y",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"valid email" in response.data.lower() or b"invalid email" in response.data.lower()


def test_academy_homepage_loads(client):
    response = client.get("/academy")
    assert response.status_code == 200
    assert b"axiom academy" in response.data.lower()
    assert b"Learn Skills." in response.data
    assert b'name="q"' in response.data
    assert b'action="/academy/courses"' in response.data
    assert b"Training your team?" in response.data
    assert b"Verify a certificate" in response.data


def test_academy_homepage_links_real_published_content(client):
    with client.application.app_context():
        course = Course.query.filter_by(slug="web-development").first()
        category_id = course.category_id
        product = AcademyProduct(
            title="Homepage resource",
            slug="homepage-resource",
            short_description="A real published learning resource.",
            description="Resource details",
            cover_image=None,
            price=5000,
            currency="NGN",
            is_free=False,
            status="published",
        )
        db.session.add(product)
        db.session.commit()
        course_slug = course.slug

    response = client.get("/academy?q=digital")
    assert response.status_code == 200
    assert b'value="digital"' in response.data
    assert b"/academy/courses?category=" + str(category_id).encode() in response.data
    assert f"/academy/courses/{course_slug}".encode() in response.data
    assert b"/academy/products/homepage-resource" in response.data
    assert b"NGN 5000.00" in response.data
    assert b"static/uploads" not in response.data


def test_academy_homepage_handles_empty_published_collections(client):
    with client.application.app_context():
        Course.query.update({Course.status: "draft"})
        AcademyProduct.query.update({AcademyProduct.status: "draft"})
        db.session.commit()

    response = client.get("/academy")
    assert response.status_code == 200
    assert b"New courses are on the way" in response.data
    assert b"There are no recently published courses yet" in response.data
    assert b"Homepage resource" not in response.data
    assert b"Explore what you want to learn" not in response.data


def test_academy_public_pages_render(client):
    with client.application.app_context():
        course = Course.query.filter_by(slug="web-development").first()
        product = AcademyProduct(
            title="Public resource",
            slug="public-resource",
            short_description="Resource overview",
            description="Resource details",
            is_free=True,
            status="published",
        )
        article = Article(
            title="Published insight",
            slug="published-insight",
            excerpt="A published article excerpt for route coverage.",
            body="Published article body",
            status="published",
        )
        db.session.add_all([product, article])
        db.session.commit()
        course_slug = course.slug

    paths = [
        "/academy",
        "/academy/courses",
        "/academy/products",
        "/academy/certificates/verify",
        f"/academy/courses/{course_slug}",
        "/academy/products/public-resource",
        "/insights/published-insight",
    ]
    for path in paths:
        assert client.get(path).status_code == 200, path

    with client.application.app_context():
        db.session.add(Article(title="Draft insight", slug="draft-insight", excerpt="Draft article excerpt for route coverage.", body="Draft", status="draft"))
        db.session.commit()
    assert client.get("/insights/draft-insight").status_code == 404


def test_student_registration_and_dashboard(client):
    response = client.post(
        "/student/register",
        data={
            "full_name": "Student User",
            "email": "student@example.com",
            "password": "StrongPass123",
            "confirm_password": "StrongPass123",
            "phone": "08000000000",
            "consent": "y",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Welcome to Axiom Academy" in response.data.lower() or b"Student Dashboard" in response.data

    dashboard = client.get("/student/dashboard")
    assert dashboard.status_code == 200
    assert b"student dashboard" in dashboard.data.lower()
    assert b"student sidebar" in dashboard.data.lower()

    catalogue = client.get("/academy/courses")
    assert catalogue.status_code == 200
    assert b"student sidebar" not in catalogue.data.lower()
    assert b"Logout" in catalogue.data


def test_student_courses_orders_and_certificates_pages_are_account_scoped(client):
    register_student(client)
    with client.application.app_context():
        student = Student.query.filter_by(email="learner@example.com").first()
        course = Course.query.filter_by(slug="web-development").first()
        enrolment = CourseEnrollment(student_id=student.id, course_id=course.id, status="active", progress=40)
        order = AcademyOrder(
            student_id=student.id,
            item_type="course",
            item_id=course.id,
            amount=course.price,
            currency=course.currency,
            status="pending",
            reference="AXM-STUDENT-ORDER-1",
        )
        certificate = AcademyCertificate(
            student_id=student.id,
            course_id=course.id,
            certificate_number="AXM-CERT-STUDENT-1",
            verification_code="VERIFY-STUDENT-1",
        )
        db.session.add_all([enrolment, order, certificate])
        db.session.commit()
        course_title = course.title

    courses_page = client.get("/student/my-courses")
    assert courses_page.status_code == 200
    assert course_title.encode() in courses_page.data
    assert b"40%" in courses_page.data
    assert b"Continue learning" in courses_page.data
    assert b'aria-current="page"' in courses_page.data

    orders_page = client.get("/student/orders")
    assert orders_page.status_code == 200
    assert b"AXM-STUDENT-ORDER-1" in orders_page.data
    assert course_title.encode() in orders_page.data
    assert b"pending" in orders_page.data

    certificates_page = client.get("/student/certificates")
    assert certificates_page.status_code == 200
    assert b"AXM-CERT-STUDENT-1" in certificates_page.data
    assert b"VERIFY-STUDENT-1" in certificates_page.data
    assert course_title.encode() in certificates_page.data

    client.get("/student/logout")
    register_student(client, email="another-learner@example.com")
    assert b"AXM-STUDENT-ORDER-1" not in client.get("/student/orders").data
    assert b"AXM-CERT-STUDENT-1" not in client.get("/student/certificates").data
    assert course_title.encode() not in client.get("/student/my-courses").data

    client.get("/student/logout")
    for path in ("/student/my-courses", "/student/orders", "/student/certificates"):
        assert client.get(path).status_code == 302


def test_student_course_checkout_accepts_csrf_token():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    app.config["WTF_CSRF_ENABLED"] = True
    add_test_courses(app)

    with app.test_client() as client:
        registration_page = client.get("/student/register")
        registration_token = re.search(rb'<input[^>]*name="csrf_token"[^>]*value="([^"]+)"', registration_page.data)
        assert registration_token

        registration_response = client.post(
            "/student/register",
            data={
                "csrf_token": registration_token.group(1).decode(),
                "full_name": "CSRF Student",
                "email": "csrf-student@example.com",
                "password": "StrongPass123",
                "confirm_password": "StrongPass123",
                "phone": "08000000000",
                "consent": "y",
            },
        )
        assert registration_response.status_code == 302
        assert registration_response.location.endswith("/student/dashboard")

        course_page = client.get("/academy/courses/web-development")
        assert course_page.status_code == 200
        checkout_token = re.search(rb'<input[^>]*name="csrf_token"[^>]*value="([^"]+)"', course_page.data)
        assert checkout_token

        checkout_response = client.post(
            "/student/checkout/1",
            data={"csrf_token": checkout_token.group(1).decode()},
            follow_redirects=True,
        )
        assert checkout_response.status_code == 200
        assert b"submit your receipt" in checkout_response.data.lower()
        assert b"1030034612" in checkout_response.data
        with app.app_context():
            assert CourseEnrollment.query.count() == 0


def test_course_access_requires_submitted_receipt_and_admin_approval(client, tmp_path):
    client.application.config["UPLOAD_FOLDER"] = str(tmp_path / "private-uploads")
    register_student(client, email="receipt-learner@example.com")
    response = client.post("/student/checkout/1")
    assert response.status_code == 302
    assert "/student/orders/" in response.location
    receipt_page = client.get(response.location)
    assert b"UBA" in receipt_page.data
    assert b"1030034612" in receipt_page.data

    submission = client.post(
        response.location,
        data={"receipt": (io.BytesIO(b"payment receipt"), "payment-receipt.pdf")},
        content_type="multipart/form-data",
    )
    assert submission.status_code == 302
    with client.application.app_context():
        order = AcademyOrder.query.filter_by(item_type="course", status="receipt_submitted").one()
        assert order.receipt_path.startswith("receipts/")
        course = db.session.get(Course, order.item_id)
        assert CourseEnrollment.query.filter_by(student_id=order.student_id, course_id=course.id).first() is None
        admin = AdminUser(name="Receipt Admin", email="receipts-admin@example.com", role="admin", active=True)
        admin.set_password("StrongAdmin123")
        db.session.add(admin)
        db.session.commit()
        order_id = order.id
        course_slug = course.slug

    client.get("/student/logout")
    assert client.post("/admin/login", data={"email": "receipts-admin@example.com", "password": "StrongAdmin123"}).status_code == 302
    review = client.post(f"/admin/course-payments/{order_id}/review", data={"decision": "approve"})
    assert review.status_code == 302
    with client.application.app_context():
        assert AcademyOrder.query.get(order_id).status == "paid"
        assert CourseEnrollment.query.filter_by(course_id=1, status="active").count() == 1

    client.get("/admin/logout")
    assert client.post("/student/login", data={"email": "receipt-learner@example.com", "password": "StrongPass123"}).status_code == 302
    assert client.get(f"/student/courses/{course_slug}").status_code == 200


def register_student(client, email="learner@example.com"):
    response = client.post(
        "/student/register",
        data={
            "full_name": "Learning Student",
            "email": email,
            "password": "StrongPass123",
            "confirm_password": "StrongPass123",
            "phone": "08000000000",
            "consent": "y",
        },
    )
    assert response.status_code == 302


def test_lesson_progress_awards_certificate(client):
    register_student(client)
    app = client.application
    with app.app_context():
        course = Course.query.filter_by(slug="web-development").first()
        course_id = course.id
        student = Student.query.filter_by(email="learner@example.com").first()
        db.session.add(CourseEnrollment(student_id=student.id, course_id=course.id, status="active", progress=0.0, source="bank_transfer"))
        db.session.commit()

    with app.app_context():
        course = db.session.get(Course, course_id)
        lesson_ids = [lesson.id for lesson in CourseLesson.query.filter_by(course_id=course_id).order_by(CourseLesson.order_index).all()]
        slug = course.slug
    for lesson_id in lesson_ids:
        response = client.post(f"/student/courses/{slug}/lessons/{lesson_id}/complete")
        assert response.status_code == 302

    with app.app_context():
        enrollment = CourseEnrollment.query.filter_by(course_id=course_id).first()
        assert enrollment.progress == 100
        assert enrollment.completed_at is not None
        assert enrollment.student.certificates[0].course_id == course_id


def test_quiz_submission_is_scored_for_enrolled_student(client):
    register_student(client)
    app = client.application
    with app.app_context():
        course = Course.query.filter_by(slug="web-development").first()
        student = Student.query.filter_by(email="learner@example.com").first()
        course_id, student_id = course.id, student.id
        enrollment = CourseEnrollment(student_id=student_id, course_id=course_id, status="active", progress=0)
        quiz = Quiz(course_id=course_id, title="Knowledge check", pass_mark=70, attempt_limit=2, status="published")
        question = QuizQuestion(prompt="Choose the correct answer", points=1, order_index=1)
        question.options = [QuizOption(option_text="Correct", is_correct=True), QuizOption(option_text="Incorrect", is_correct=False)]
        quiz.questions.append(question)
        db.session.add_all([enrollment, quiz])
        db.session.commit()
        quiz_id = quiz.id
        correct_option_id = question.options[0].id

    response = client.post(f"/student/quizzes/{quiz_id}", data={f"question_1": str(correct_option_id)}, follow_redirects=True)
    assert response.status_code == 200
    assert b"Assessment passed" in response.data


def test_product_download_requires_paid_order(client, tmp_path):
    register_student(client)
    client.application.config["UPLOAD_FOLDER"] = str(tmp_path)
    asset = tmp_path / "course-guide.pdf"
    asset.write_bytes(b"private course guide")
    with client.application.app_context():
        product = AcademyProduct(
            title="Course guide",
            slug="course-guide",
            short_description="Downloadable guide",
            description="Guide",
            is_free=True,
            status="published",
            file_path=asset.name,
        )
        db.session.add(product)
        db.session.commit()
        product_id = product.id

    denied = client.get(f"/student/products/{product_id}/download")
    assert denied.status_code == 403
    purchased = client.post(f"/student/products/{product_id}/checkout")
    assert purchased.status_code == 302
    downloaded = client.get(f"/student/products/{product_id}/download")
    assert downloaded.status_code == 200
    assert downloaded.data == b"private course guide"


def test_student_cannot_open_admin_and_admin_course_screen_loads(client):
    register_student(client)
    assert client.get("/admin").status_code == 403
    client.get("/student/logout")

    with client.application.app_context():
        admin = AdminUser(name="Academy Admin", email="admin@example.com", role="admin", active=True)
        admin.set_password("StrongAdmin123")
        db.session.add(admin)
        db.session.commit()

    response = client.post("/admin/login", data={"email": "admin@example.com", "password": "StrongAdmin123"})
    assert response.status_code == 302
    courses = client.get("/admin/courses")
    assert courses.status_code == 200, courses.location
    assert b"Academy courses" in courses.data
    with client.application.app_context():
        course_id = Course.query.first().id
    assert client.get("/admin/courses/new").status_code == 200
    assert client.get(f"/admin/courses/{course_id}/lessons/new").status_code == 200
    assert client.get(f"/admin/courses/{course_id}/quizzes/new").status_code == 200
    assert client.get("/admin/products/new").status_code == 200


def test_admin_uploads_resources_to_private_storage(client, tmp_path):
    client.application.config["UPLOAD_FOLDER"] = str(tmp_path)
    with client.application.app_context():
        admin = AdminUser(name="Resource Admin", email="resource-admin@example.com", role="admin", active=True)
        admin.set_password("StrongAdmin123")
        db.session.add(admin)
        db.session.commit()

    login_response = client.post("/admin/login", data={"email": "resource-admin@example.com", "password": "StrongAdmin123"})
    assert login_response.status_code == 302
    response = client.post(
        "/admin/products/new",
        data={
            "title": "Private handbook",
            "short_description": "A downloadable handbook",
            "description": "Course companion resource",
            "price": "0",
            "currency": "NGN",
            "is_free": "on",
            "publish": "on",
            "resource_file": (io.BytesIO(b"private contents"), "handbook.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    with client.application.app_context():
        product = AcademyProduct.query.filter_by(slug="private-handbook").first()
        stored_file = tmp_path / product.file_path
        assert stored_file.is_file()
        assert product.file_path != "handbook.pdf"
        assert stored_file.read_bytes() == b"private contents"


def test_signed_paystack_webhook_grants_matching_course_order():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    app.config.update(WTF_CSRF_ENABLED=False, PAYSTACK_SECRET_KEY="test-paystack-secret")
    add_test_courses(app)

    with app.test_client() as client:
        register_student(client)
        with app.app_context():
            student = Student.query.filter_by(email="learner@example.com").first()
            course = Course.query.filter_by(slug="web-development").first()
            order = AcademyOrder(
                student_id=student.id,
                item_type="course",
                item_id=course.id,
                amount=course.price,
                currency=course.currency,
                status="pending",
                reference="AXM-WEBHOOK-TEST",
            )
            db.session.add(order)
            db.session.commit()
            course_id = course.id

        mismatch_payload = json.dumps({
            "event": "charge.success",
            "data": {"reference": "AXM-WEBHOOK-TEST", "amount": 1, "currency": "NGN", "status": "success"},
        }).encode()
        mismatch_signature = hmac.new(b"test-paystack-secret", mismatch_payload, hashlib.sha512).hexdigest()
        mismatch_response = client.post("/student/payment/webhook", data=mismatch_payload, content_type="application/json", headers={"x-paystack-signature": mismatch_signature})
        assert mismatch_response.status_code == 400
        with app.app_context():
            assert AcademyOrder.query.filter_by(reference="AXM-WEBHOOK-TEST").first().status == "pending"
            assert CourseEnrollment.query.filter_by(course_id=course_id).count() == 0

        payload = json.dumps({
            "event": "charge.success",
            "data": {"reference": "AXM-WEBHOOK-TEST", "amount": 2500000, "currency": "NGN", "status": "success"},
        }).encode()
        signature = hmac.new(b"test-paystack-secret", payload, hashlib.sha512).hexdigest()
        response = client.post("/student/payment/webhook", data=payload, content_type="application/json", headers={"x-paystack-signature": signature})
        assert response.status_code == 200

        with app.app_context():
            order = AcademyOrder.query.filter_by(reference="AXM-WEBHOOK-TEST").first()
            assert order.status == "paid"
            assert CourseEnrollment.query.filter_by(course_id=course_id, status="active").count() == 1
