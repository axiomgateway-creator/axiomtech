"""add instructor payout allocations and reversals"""

from alembic import op
import sqlalchemy as sa


revision = "20261015_instructor_finance"
down_revision = "20261015_instructor_portal"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("instructor_payout_allocations"):
        op.create_table(
            "instructor_payout_allocations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("payout_request_id", sa.Integer(), sa.ForeignKey("instructor_payout_requests.id"), nullable=False),
            sa.Column("earning_id", sa.Integer(), sa.ForeignKey("instructor_earnings.id"), nullable=False, unique=True),
            sa.Column("amount_kobo", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if "ix_instructor_payout_allocations_payout_request_id" not in {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("instructor_payout_allocations")}:
        op.create_index("ix_instructor_payout_allocations_payout_request_id", "instructor_payout_allocations", ["payout_request_id"])

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("instructor_reversals"):
        op.create_table(
            "instructor_reversals",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("order_id", sa.Integer(), sa.ForeignKey("academy_orders.id"), nullable=False, unique=True),
            sa.Column("instructor_id", sa.Integer(), sa.ForeignKey("instructors.id"), nullable=False),
            sa.Column("gross_reversed_kobo", sa.Integer(), nullable=False),
            sa.Column("commission_reversed_kobo", sa.Integer(), nullable=False),
            sa.Column("instructor_share_reversed_kobo", sa.Integer(), nullable=False),
            sa.Column("reason", sa.Text()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if "ix_instructor_reversals_instructor_id" not in {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("instructor_reversals")}:
        op.create_index("ix_instructor_reversals_instructor_id", "instructor_reversals", ["instructor_id"])


def downgrade():
    op.drop_index("ix_instructor_reversals_instructor_id", table_name="instructor_reversals")
    op.drop_table("instructor_reversals")
    op.drop_index("ix_instructor_payout_allocations_payout_request_id", table_name="instructor_payout_allocations")
    op.drop_table("instructor_payout_allocations")