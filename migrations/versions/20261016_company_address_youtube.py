"""complete company address and add YouTube channel setting"""

from alembic import op
import sqlalchemy as sa


revision = "20261016_company_address_youtube"
down_revision = "20261015_default_services"
branch_labels = None
depends_on = None


COMPANY_ADDRESS = "No 5 Adetokunbo Ademola Street Mitama, Abuja"
YOUTUBE_URL = "https://www.youtube.com/channel/UCVWSZcwBZB8tu7f76OtVKqA"


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "youtube_url" not in {column["name"] for column in inspector.get_columns("company_settings")}:
        op.add_column("company_settings", sa.Column("youtube_url", sa.String(length=255), nullable=True))

    settings = sa.table(
        "company_settings",
        sa.column("office_address", sa.Text()),
        sa.column("youtube_url", sa.String(length=255)),
    )
    op.get_bind().execute(
        settings.update().values(
            office_address=COMPANY_ADDRESS,
            youtube_url=YOUTUBE_URL,
        )
    )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "youtube_url" in {column["name"] for column in inspector.get_columns("company_settings")}:
        op.drop_column("company_settings", "youtube_url")
