from . import db
from .models import AdminUser, ArticleCategory, CompanySettings, Course, CourseCategory, CourseLesson, Service


SERVICE_SEEDS = [
    {
        "name": "Digital Solutions and IT Services",
        "slug": "digital-solutions-it",
        "short_description": "Technology systems, websites, portals, and digital modernization for organizations.",
        "full_description": "We design and implement digital tools that improve productivity, streamline workflows, and support organizational growth.",
        "icon": "fa-computer",
        "display_order": 1,
    },
    {
        "name": "Human Resource and Organizational Development",
        "slug": "human-resource-organizational-development",
        "short_description": "Capacity development, workforce strategies, and people-focused organizational improvement.",
        "full_description": "We help organizations strengthen people systems, align talent and performance, and build sustainable growth capabilities.",
        "icon": "fa-users",
        "display_order": 2,
    },
    {
        "name": "Business and Management Consulting",
        "slug": "business-management-consulting",
        "short_description": "Strategic direction, planning, optimization, and advisory support for operations and growth.",
        "full_description": "Our consulting approach combines business analysis, operational insight, and practical recommendations to support better decisions.",
        "icon": "fa-chart-line",
        "display_order": 3,
    },
    {
        "name": "Digital Marketing and Creative Services",
        "slug": "digital-marketing-creative",
        "short_description": "Brand communication, content strategy, marketing support, and creative digital execution.",
        "full_description": "We connect organizations with their audiences through digital marketing, creative communication, and brand enablement.",
        "icon": "fa-pen-ruler",
        "display_order": 4,
    },
    {
        "name": "Data Analytics and Business Intelligence",
        "slug": "data-analytics-business-intelligence",
        "short_description": "Insight generation, reporting, dashboards, and data-driven decision support.",
        "full_description": "We convert business data into clear, measurable insight that helps teams plan, monitor, and improve performance.",
        "icon": "fa-database",
        "display_order": 5,
    },
]


ARTICLE_CATEGORY_SEEDS = [
    ("Technology and Digital Transformation", "technology-and-digital-transformation"),
    ("Business Development and Entrepreneurship", "business-development-and-entrepreneurship"),
    ("Data Analytics and Business Intelligence", "data-analytics-and-business-intelligence"),
    ("Human Resource Development", "human-resource-development"),
    ("Digital Marketing", "digital-marketing"),
    ("Project Management and Organizational Performance", "project-management-and-organizational-performance"),
]


def seed_initial_data():
    if CompanySettings.query.count() == 0:
        db.session.add(CompanySettings())

    for service_data in SERVICE_SEEDS:
        if not Service.query.filter_by(slug=service_data["slug"]).first():
            service = Service(
                name=service_data["name"],
                slug=service_data["slug"],
                short_description=service_data["short_description"],
                full_description=service_data["full_description"],
                icon=service_data["icon"],
                display_order=service_data["display_order"],
                published=True,
            )
            db.session.add(service)

    for name, slug in ARTICLE_CATEGORY_SEEDS:
        if not ArticleCategory.query.filter_by(slug=slug).first():
            db.session.add(ArticleCategory(name=name, slug=slug, description=name))

    academy_categories = [
        ("Digital Skills", "digital-skills", "Practical digital capability for modern teams and professionals."),
        ("Business and Leadership", "business-and-leadership", "Tools for strategy, management, and operational excellence."),
        ("Data and Analytics", "data-and-analytics", "Analysis, reporting, and evidence-based decision making."),
    ]
    for name, slug, description in academy_categories:
        if not CourseCategory.query.filter_by(slug=slug).first():
            db.session.add(CourseCategory(name=name, slug=slug, description=description))

    db.session.flush()

    academy_courses = [
        {
            "title": "Digital Skills for Modern Professionals",
            "slug": "digital-skills-for-modern-professionals",
            "short_description": "Build practical digital literacy, productivity, and operational confidence.",
            "description": "<p>Learn the core digital skills needed to stay productive, communicate clearly, and work with modern systems in a professional environment.</p>",
            "category_slug": "digital-skills",
            "difficulty": "Beginner",
            "duration_hours": 6,
            "price": 25000,
            "currency": "NGN",
            "is_free": False,
            "is_featured": True,
            "certificate_eligible": True,
            "instructor_name": "Axiom Academy",
            "objectives": "Understand digital workplace tools\nImprove online collaboration\nApply practical digital workflows",
        },
        {
            "title": "Executive Leadership Essentials",
            "slug": "executive-leadership-essentials",
            "short_description": "Strengthen strategic leadership, communication, and decision-making skills.",
            "description": "<p>Build the leadership habits and strategic thinking needed for managers, founders, and teams driving transformation.</p>",
            "category_slug": "business-and-leadership",
            "difficulty": "Intermediate",
            "duration_hours": 8,
            "price": 40000,
            "currency": "NGN",
            "is_free": False,
            "is_featured": True,
            "certificate_eligible": True,
            "instructor_name": "Axiom Academy",
            "objectives": "Lead with clarity\nImprove team communication\nDrive strategic execution",
        },
    ]
    for course_data in academy_courses:
        if not Course.query.filter_by(slug=course_data["slug"]).first():
            category = CourseCategory.query.filter_by(slug=course_data["category_slug"]).first()
            course = Course(
                title=course_data["title"],
                slug=course_data["slug"],
                short_description=course_data["short_description"],
                description=course_data["description"],
                category=category,
                instructor_name=course_data["instructor_name"],
                difficulty=course_data["difficulty"],
                duration_hours=course_data["duration_hours"],
                price=float(course_data["price"]),
                currency=course_data["currency"],
                is_free=course_data["is_free"],
                is_featured=course_data["is_featured"],
                certificate_eligible=course_data["certificate_eligible"],
                objectives=course_data["objectives"],
                status="published",
                published_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            )
            db.session.add(course)
            db.session.flush()
            for order_index, lesson_name in enumerate(["Introduction", "Core concepts", "Practical application"], start=1):
                db.session.add(
                    CourseLesson(
                        course_id=course.id,
                        title=lesson_name,
                        slug=f"{course.slug}-{lesson_name.lower().replace(' ', '-')}",
                        lesson_type="text",
                        content=f"<p>Lesson content for {lesson_name}.</p>",
                        order_index=order_index,
                        status="published",
                    )
                )

    db.session.commit()
