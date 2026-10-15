"""add instructor portal tables and ownership fields"""

from alembic import op
import sqlalchemy as sa


revision = "20261015_instructor_portal"
down_revision = "20261014_manual_course_receipts"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _add_columns(table, columns, foreign_keys=()):
    inspector = _inspector()
    existing_columns = {column["name"] for column in inspector.get_columns(table)}
    existing_foreign_keys = inspector.get_foreign_keys(table)
    with op.batch_alter_table(table) as batch_op:
        for column in columns:
            if column.name not in existing_columns:
                batch_op.add_column(column)
        for name, referred_table, local_columns, remote_columns in foreign_keys:
            already_exists = any(
                foreign_key.get("referred_table") == referred_table
                and foreign_key.get("constrained_columns") == local_columns
                for foreign_key in existing_foreign_keys
            )
            if not already_exists:
                batch_op.create_foreign_key(name, referred_table, local_columns, remote_columns)


def _create_index_if_missing(name, table, columns, unique=False):
    if name not in {index["name"] for index in _inspector().get_indexes(table)}:
        op.create_index(name, table, columns, unique=unique)


def upgrade():
    if not _inspector().has_table("instructors"):
        op.create_table(
        "instructors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("full_name", sa.String(length=160), nullable=False),
        sa.Column("email", sa.String(length=160), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=60)),
        sa.Column("professional_title", sa.String(length=160)),
        sa.Column("biography", sa.Text()),
        sa.Column("teaching_experience", sa.Text()),
        sa.Column("qualifications", sa.Text()),
        sa.Column("subject_areas", sa.Text()),
        sa.Column("profile_photo", sa.String(length=255)),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("decision_reason", sa.Text()),
        sa.Column("terms_accepted_at", sa.DateTime()),
        sa.Column("last_login_at", sa.DateTime()),
        sa.Column("reviewed_by_admin_id", sa.Integer(), sa.ForeignKey("admin_users.id")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    _create_index_if_missing("ix_instructors_email", "instructors", ["email"], unique=True)
    _create_index_if_missing("ix_instructors_status", "instructors", ["status"])

    _add_columns("company_settings", [
        sa.Column("academy_commission_percent", sa.Float(), nullable=True),
        sa.Column("academy_minimum_payout_kobo", sa.Integer(), nullable=False, server_default="0"),
    ])

    _add_columns("courses", [
        sa.Column("instructor_id", sa.Integer(), nullable=True),
        sa.Column("review_status", sa.String(length=20), nullable=False, server_default="not_required"),
        sa.Column("target_audience", sa.Text(), nullable=True),
        sa.Column("requirements", sa.Text(), nullable=True),
        sa.Column("what_students_learn", sa.Text(), nullable=True),
    ], [("fk_courses_instructor_id", "instructors", ["instructor_id"], ["id"])])
    _create_index_if_missing("ix_courses_instructor_id", "courses", ["instructor_id"])
    _create_index_if_missing("ix_courses_review_status", "courses", ["review_status"])

    _add_columns("course_lessons", [
        sa.Column("module_title", sa.String(length=160), nullable=True),
        sa.Column("resource_path", sa.String(length=255), nullable=True),
        sa.Column("resource_filename", sa.String(length=255), nullable=True),
    ])

    _add_columns("academy_certificates", [
        sa.Column("certificate_type", sa.String(length=30), nullable=False, server_default="completion"),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
        sa.Column("issued_by_instructor_id", sa.Integer(), nullable=True),
    ], [("fk_academy_certificates_issued_by_instructor", "instructors", ["issued_by_instructor_id"], ["id"])])

    if not _inspector().has_table("instructor_notifications"):
        op.create_table(
        "instructor_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instructor_id", sa.Integer(), sa.ForeignKey("instructors.id"), nullable=False),
        sa.Column("event_key", sa.String(length=160), unique=True),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("target_url", sa.String(length=255)),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    _create_index_if_missing("ix_instructor_notifications_instructor_id", "instructor_notifications", ["instructor_id"])
    _create_index_if_missing("ix_instructor_notifications_is_read", "instructor_notifications", ["is_read"])

    if not _inspector().has_table("instructor_audit_logs"):
        op.create_table(
        "instructor_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instructor_id", sa.Integer(), sa.ForeignKey("instructors.id")),
        sa.Column("admin_id", sa.Integer(), sa.ForeignKey("admin_users.id")),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.Integer()),
        sa.Column("details", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    _create_index_if_missing("ix_instructor_audit_logs_instructor_id", "instructor_audit_logs", ["instructor_id"])

    if not _inspector().has_table("instructor_payout_requests"):
        op.create_table(
        "instructor_payout_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instructor_id", sa.Integer(), sa.ForeignKey("instructors.id"), nullable=False),
        sa.Column("amount_kobo", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("decision_note", sa.Text()),
        sa.Column("payment_reference", sa.String(length=120)),
        sa.Column("reviewed_by_admin_id", sa.Integer(), sa.ForeignKey("admin_users.id")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    _create_index_if_missing("ix_instructor_payout_requests_instructor_id", "instructor_payout_requests", ["instructor_id"])
    _create_index_if_missing("ix_instructor_payout_requests_status", "instructor_payout_requests", ["status"])

    if not _inspector().has_table("instructor_earnings"):
        op.create_table(
        "instructor_earnings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instructor_id", sa.Integer(), sa.ForeignKey("instructors.id"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("academy_orders.id"), nullable=False, unique=True),
        sa.Column("gross_kobo", sa.Integer(), nullable=False),
        sa.Column("gateway_fee_kobo", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("commission_kobo", sa.Integer(), nullable=False),
        sa.Column("instructor_share_kobo", sa.Integer(), nullable=False),
        sa.Column("payout_status", sa.String(length=20), nullable=False, server_default="available"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    _create_index_if_missing("ix_instructor_earnings_instructor_id", "instructor_earnings", ["instructor_id"])
    _create_index_if_missing("ix_instructor_earnings_payout_status", "instructor_earnings", ["payout_status"])



def downgrade():
    op.drop_table("instructor_earnings")
    op.drop_table("instructor_payout_requests")
    op.drop_index("ix_instructor_audit_logs_instructor_id", table_name="instructor_audit_logs")
    op.drop_table("instructor_audit_logs")
    op.drop_index("ix_instructor_notifications_is_read", table_name="instructor_notifications")
    op.drop_index("ix_instructor_notifications_instructor_id", table_name="instructor_notifications")
    op.drop_table("instructor_notifications")
    with op.batch_alter_table("academy_certificates") as batch_op:
        batch_op.drop_constraint("fk_academy_certificates_issued_by_instructor", type_="foreignkey")
        batch_op.drop_column("issued_by_instructor_id")
        batch_op.drop_column("revoked_reason")
        batch_op.drop_column("revoked_at")
        batch_op.drop_column("certificate_type")
    with op.batch_alter_table("course_lessons") as batch_op:
        batch_op.drop_column("resource_filename")
        batch_op.drop_column("resource_path")
        batch_op.drop_column("module_title")
    op.drop_index("ix_courses_review_status", table_name="courses")
    op.drop_index("ix_courses_instructor_id", table_name="courses")
    with op.batch_alter_table("courses") as batch_op:
        batch_op.drop_constraint("fk_courses_instructor_id", type_="foreignkey")
        batch_op.drop_column("what_students_learn")
        batch_op.drop_column("requirements")
        batch_op.drop_column("target_audience")
        batch_op.drop_column("review_status")
        batch_op.drop_column("instructor_id")
    with op.batch_alter_table("company_settings") as batch_op:
        batch_op.drop_column("academy_minimum_payout_kobo")
        batch_op.drop_column("academy_commission_percent")
    op.drop_index("ix_instructors_status", table_name="instructors")
    op.drop_index("ix_instructors_email", table_name="instructors")
    op.drop_table("instructors")