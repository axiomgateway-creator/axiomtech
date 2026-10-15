import re
import hashlib
import hmac
import io
import json

import pytest

from app import create_app
from app import db
from app.models import (
    AcademyOrder,
    AcademyProduct,
    AcademyCertificate,
    AdminUser,
    Article,
    Course,
    CourseEnrollment,
    CourseLesson,
    Quiz,
    QuizOption,
    QuizQuestion,
    Student,
)


@pytest.fixture
def client():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.test_client() as client:
        yield client


def test_homepage_loads(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Axiom Gateway Consult" in response.data.lower() or b"Empowering People" in response.data


def test_admin_requires_login(client):
    response = client.get("/admin")
    assert response.status_code == 302


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
        course = Course.query.filter_by(slug="digital-skills-for-modern-professionals").first()
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
        course = Course.query.filter_by(slug="digital-skills-for-modern-professionals").first()
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
        course = Course.query.filter_by(slug="digital-skills-for-modern-professionals").first()
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

        course_page = client.get("/academy/courses/digital-skills-for-modern-professionals")
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
        course = Course.query.filter_by(slug="digital-skills-for-modern-professionals").first()
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
        course = Course.query.filter_by(slug="digital-skills-for-modern-professionals").first()
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

    with app.test_client() as client:
        register_student(client)
        with app.app_context():
            student = Student.query.filter_by(email="learner@example.com").first()
            course = Course.query.filter_by(slug="digital-skills-for-modern-professionals").first()
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
