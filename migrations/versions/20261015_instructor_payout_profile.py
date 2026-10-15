"""add encrypted instructor payout profile fields"""

from alembic import op
import sqlalchemy as sa


revision = "20261015_instructor_payout_profile"
down_revision = "20261015_instructor_finance"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns("instructors")}
    with op.batch_alter_table("instructors") as batch_op:
        columns = [
            sa.Column("payout_bank_name", sa.String(length=120), nullable=True),
            sa.Column("payout_account_name", sa.String(length=160), nullable=True),
            sa.Column("payout_account_number_encrypted", sa.Text(), nullable=True),
            sa.Column("payout_bank_code", sa.String(length=30), nullable=True),
        ]
        for column in columns:
            if column.name not in existing:
                batch_op.add_column(column)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns("instructors")}
    with op.batch_alter_table("instructors") as batch_op:
        for column_name in ("payout_bank_code", "payout_account_number_encrypted", "payout_account_name", "payout_bank_name"):
            if column_name in existing:
                batch_op.drop_column(column_name)