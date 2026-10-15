"""add default published service listings"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "20261015_default_services"
down_revision = "20261015_instructor_payout_profile"
branch_labels = None
depends_on = None


SERVICES = (
    (
        "Digital Solutions and IT Services",
        "digital-solutions-it",
        "Technology systems, websites, portals, and digital modernization for organizations.",
        "Technology systems, websites, portals, and digital modernization for organizations.",
        "fa-laptop-code",
        1,
    ),
    (
        "Human Resource and Organizational Development",
        "human-resource-organizational-development",
        "Capacity development, workforce strategies, and people-focused organizational improvement.",
        "Capacity development, workforce strategies, and people-focused organizational improvement.",
        "fa-people-group",
        2,
    ),
    (
        "Business and Management Consulting",
        "business-management-consulting",
        "Strategic direction, planning, optimization, and advisory support for operations and growth.",
        "Strategic direction, planning, optimization, and advisory support for operations and growth.",
        "fa-chart-line",
        3,
    ),
    (
        "Digital Marketing and Creative Services",
        "digital-marketing-creative",
        "Brand communication, content strategy, marketing support, and creative digital execution.",
        "Brand communication, content strategy, marketing support, and creative digital execution.",
        "fa-bullhorn",
        4,
    ),
    (
        "Data Analytics and Business Intelligence",
        "data-analytics-business-intelligence",
        "Insight generation, reporting, dashboards, and data-driven decision support.",
        "Insight generation, reporting, dashboards, and data-driven decision support.",
        "fa-chart-pie",
        5,
    ),
)


def upgrade():
    connection = op.get_bind()
    services = sa.table(
        "services",
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("short_description", sa.Text()),
        sa.column("full_description", sa.Text()),
        sa.column("icon", sa.String()),
        sa.column("display_order", sa.Integer()),
        sa.column("published", sa.Boolean()),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    existing_slugs = set(
        connection.execute(sa.select(services.c.slug)).scalars()
    )
    now = datetime.now(timezone.utc)
    connection.execute(
        services.insert(),
        [
            {
                "name": name,
                "slug": slug,
                "short_description": short_description,
                "full_description": full_description,
                "icon": icon,
                "display_order": display_order,
                "published": True,
                "created_at": now,
                "updated_at": now,
            }
            for name, slug, short_description, full_description, icon, display_order in SERVICES
            if slug not in existing_slugs
        ],
    )


def downgrade():
    """Keep editable service content when reverting this data-only migration."""
    pass
