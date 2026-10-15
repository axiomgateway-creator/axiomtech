"""add manual course receipt review fields"""

from alembic import op
import sqlalchemy as sa

revision = "20261014_manual_course_receipts"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("academy_orders") as batch_op:
        batch_op.add_column(sa.Column("receipt_path", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("receipt_uploaded_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("receipt_reviewed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("receipt_review_note", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("reviewed_by_admin_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_academy_orders_reviewed_by_admin", "admin_users", ["reviewed_by_admin_id"], ["id"])


def downgrade():
    with op.batch_alter_table("academy_orders") as batch_op:
        batch_op.drop_constraint("fk_academy_orders_reviewed_by_admin", type_="foreignkey")
        batch_op.drop_column("reviewed_by_admin_id")
        batch_op.drop_column("receipt_review_note")
        batch_op.drop_column("receipt_reviewed_at")
        batch_op.drop_column("receipt_uploaded_at")
        batch_op.drop_column("receipt_path")
