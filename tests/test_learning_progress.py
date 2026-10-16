from datetime import datetime, timezone

import pytest

from app import create_app, db
from app.models import (
    AcademyCertificate,
    Course,
    CourseEnrollment,
    CourseLesson,
    LessonProgress,
    Student,
)
from app.routes import recalculate_course_progress


@pytest.fixture
def learning_app():
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "MAIL_SERVER": None,
    })
    with app.app_context():
        student = Student(full_name="Progress Student", email="progress@example.com", password_hash="unused")
        course = Course(
            title="Progress Course",
            slug="progress-course",
            short_description="Course for progress tests.",
            description="Course for progress tests.",
            status="published",
        )
        db.session.add_all([student, course])
        db.session.flush()
        published = [
            CourseLesson(course_id=course.id, title=f"Lesson {index}", slug=f"lesson-{index}", status="published")
            for index in range(1, 3)
        ]
        draft = CourseLesson(course_id=course.id, title="Draft", slug="draft", status="draft")
        db.session.add_all([*published, draft])
        db.session.flush()
        enrollment = CourseEnrollment(student_id=student.id, course_id=course.id, status="active")
        db.session.add(enrollment)
        db.session.commit()
        yield app, student.id, course.id, [lesson.id for lesson in published], draft.id, enrollment.id


def student_client(app, student_id):
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = f"student:{student_id}"
        session["_fresh"] = True
    return client


def test_completion_uses_published_lessons_and_is_idempotent(learning_app):
    app, student_id, course_id, lesson_ids, _draft_id, enrollment_id = learning_app
    client = student_client(app, student_id)

    response = client.post(f"/student/courses/progress-course/lessons/{lesson_ids[0]}/complete")
    assert response.status_code == 302
    with app.app_context():
        enrollment = db.session.get(CourseEnrollment, enrollment_id)
        first_progress = LessonProgress.query.filter_by(enrolment_id=enrollment_id, lesson_id=lesson_ids[0]).one()
        first_completed_at = first_progress.completed_at
        assert enrollment.progress == 50.0
        assert enrollment.last_lesson_id == lesson_ids[0]
        assert enrollment.last_accessed_at is not None
        assert AcademyCertificate.query.filter_by(student_id=student_id, course_id=course_id).count() == 0

    client.post(f"/student/courses/progress-course/lessons/{lesson_ids[0]}/complete")
    with app.app_context():
        enrollment = db.session.get(CourseEnrollment, enrollment_id)
        progress_rows = LessonProgress.query.filter_by(enrolment_id=enrollment_id, lesson_id=lesson_ids[0]).all()
        assert len(progress_rows) == 1
        assert progress_rows[0].completed_at == first_completed_at
        assert enrollment.progress == 50.0

    response = client.post(f"/student/courses/progress-course/lessons/{lesson_ids[1]}/complete")
    assert response.status_code == 302
    with app.app_context():
        enrollment = db.session.get(CourseEnrollment, enrollment_id)
        certificate = AcademyCertificate.query.filter_by(student_id=student_id, course_id=course_id).one()
        assert enrollment.progress == 100.0
        assert enrollment.completed_at is not None
        assert certificate.status == "issued"
        assert certificate.certificate_type == "completion"


def test_progress_and_certificate_recalculate_when_published_lessons_change(learning_app):
    app, student_id, course_id, lesson_ids, _draft_id, enrollment_id = learning_app
    client = student_client(app, student_id)
    for lesson_id in lesson_ids:
        client.post(f"/student/courses/progress-course/lessons/{lesson_id}/complete")

    with app.app_context():
        enrollment = db.session.get(CourseEnrollment, enrollment_id)
        certificate = AcademyCertificate.query.filter_by(student_id=student_id, course_id=course_id).one()

        added_lesson = CourseLesson(
            course_id=course_id,
            title="New published lesson",
            slug="new-published-lesson",
            status="published",
        )
        db.session.add(added_lesson)
        db.session.flush()
        recalculate_course_progress(course_id)
        db.session.commit()

        assert enrollment.progress == pytest.approx(200 / 3)
        assert enrollment.completed_at is None
        assert certificate.status == "revoked"

        added_lesson.status = "draft"
        recalculate_course_progress(course_id)
        db.session.commit()
        assert enrollment.progress == 100.0
        assert certificate.status == "issued"
        assert certificate.revoked_at is None
        assert certificate.revoked_reason is None

        # Deleting a lesson also removes its progress and triggers the same recalculation.
        lesson = db.session.get(CourseLesson, lesson_ids[0])
        db.session.delete(lesson)
        db.session.flush()
        recalculate_course_progress(course_id)
        db.session.commit()
        assert enrollment.progress == 100.0
        assert LessonProgress.query.filter_by(lesson_id=lesson_ids[0]).count() == 0


def test_last_access_timestamp_is_stored_with_the_lesson_progress(learning_app):
    app, student_id, _course_id, lesson_ids, _draft_id, enrollment_id = learning_app
    client = student_client(app, student_id)
    before = datetime.now(timezone.utc)
    client.post(f"/student/courses/progress-course/lessons/{lesson_ids[0]}/complete")

    with app.app_context():
        enrollment = db.session.get(CourseEnrollment, enrollment_id)
        assert enrollment.last_lesson_id == lesson_ids[0]
        assert enrollment.last_accessed_at is not None
        assert enrollment.last_accessed_at.replace(tzinfo=timezone.utc) >= before
