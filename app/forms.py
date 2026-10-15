from flask_wtf import FlaskForm
from wtforms import BooleanField, FloatField, HiddenField, IntegerField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, NumberRange, Optional, ValidationError


class ContactForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(min=2, max=120)])
    organization = StringField("Organization", validators=[Optional(), Length(max=160)])
    email = StringField("Email address", validators=[DataRequired(), Email()])
    telephone = StringField("Telephone number", validators=[DataRequired(), Length(min=7, max=60)])
    service = SelectField("Service of interest", coerce=str, validators=[DataRequired()])
    enquiry_type = SelectField(
        "Enquiry type",
        choices=[
            ("General", "General"),
            ("Service Request", "Service Request"),
            ("Partnership", "Partnership"),
            ("Project Proposal", "Project Proposal"),
            ("Training", "Training"),
            ("Other", "Other"),
        ],
        validators=[DataRequired()],
    )
    description = TextAreaField("Description of enquiry", validators=[DataRequired(), Length(min=10, max=2000)])
    preferred_contact = SelectField(
        "Preferred contact method",
        choices=[("Email", "Email"), ("Phone", "Phone"), ("WhatsApp", "WhatsApp")],
        validators=[DataRequired()],
    )
    consent = BooleanField("I agree to the privacy notice", validators=[DataRequired()])


class AdminLoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = StringField("Password", validators=[DataRequired()])


class AdminRegistrationForm(FlaskForm):
    name = StringField("Full name", validators=[DataRequired(), Length(min=2, max=120)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=120)])
    setup_key = StringField("Admin setup key", validators=[DataRequired(), Length(max=255)])
    password = StringField("Password", validators=[DataRequired(), Length(min=12, max=128)])
    confirm_password = StringField("Confirm password", validators=[DataRequired(), Length(min=12, max=128)])

    def validate_confirm_password(self, field):
        if field.data != self.password.data:
            raise ValidationError("Passwords do not match.")


class StudentRegistrationForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(min=2, max=160)])
    email = StringField("Email address", validators=[DataRequired(), Email()])
    password = StringField("Password", validators=[DataRequired(), Length(min=8)])
    confirm_password = StringField("Confirm password", validators=[DataRequired(), Length(min=8)])
    phone = StringField("Phone number", validators=[Optional(), Length(max=60)])
    consent = BooleanField("I agree to the privacy notice and terms", validators=[DataRequired()])

    def validate_confirm_password(self, field):
        if field.data != self.password.data:
            raise ValidationError("Passwords do not match.")


class StudentLoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email()])
    password = StringField("Password", validators=[DataRequired()])
    remember = BooleanField("Remember me")


class InstructorRegistrationForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(min=2, max=160)])
    email = StringField("Email address", validators=[DataRequired(), Email(), Length(max=160)])
    phone = StringField("Phone number", validators=[Optional(), Length(max=60)])
    professional_title = StringField("Professional title or expertise", validators=[DataRequired(), Length(max=160)])
    biography = TextAreaField("Biography", validators=[DataRequired(), Length(min=30, max=3000)])
    teaching_experience = TextAreaField("Teaching experience", validators=[Optional(), Length(max=3000)])
    qualifications = TextAreaField("Qualifications and certifications", validators=[Optional(), Length(max=3000)])
    subject_areas = TextAreaField("Courses or subject areas", validators=[DataRequired(), Length(min=3, max=2000)])
    password = StringField("Password", validators=[DataRequired(), Length(min=8, max=128)])
    confirm_password = StringField("Confirm password", validators=[DataRequired(), Length(min=8, max=128)])
    terms_accepted = BooleanField("I agree to the instructor terms", validators=[DataRequired()])

    def validate_confirm_password(self, field):
        if field.data != self.password.data:
            raise ValidationError("Passwords do not match.")


class InstructorLoginForm(FlaskForm):
    email = StringField("Email address", validators=[DataRequired(), Email()])
    password = StringField("Password", validators=[DataRequired()])
    remember = BooleanField("Remember me")


class CourseForm(FlaskForm):
    title = StringField("Course title", validators=[DataRequired(), Length(min=3, max=200)])
    slug = StringField("URL slug", validators=[DataRequired(), Length(min=3, max=200)])
    short_description = TextAreaField("Short description", validators=[DataRequired(), Length(max=2000)])
    description = TextAreaField("Description", validators=[DataRequired()])
    category_id = SelectField("Category", coerce=int, validators=[Optional()])
    instructor_name = StringField("Instructor", validators=[Optional(), Length(max=120)])
    difficulty = SelectField("Difficulty", choices=[("Beginner", "Beginner"), ("Intermediate", "Intermediate"), ("Advanced", "Advanced")])
    duration_hours = IntegerField("Duration in hours", validators=[DataRequired()])
    language = StringField("Language", validators=[DataRequired(), Length(max=60)])
    price = StringField("Price", validators=[DataRequired()])
    currency = SelectField("Currency", choices=[("NGN", "NGN"), ("USD", "USD")])
    is_free = BooleanField("Free course")
    status = SelectField("Status", choices=[("draft", "Draft"), ("published", "Published")])
    is_featured = BooleanField("Featured course")
    certificate_eligible = BooleanField("Certificate eligible")
    objectives = TextAreaField("Learning objectives", validators=[Optional()])
    prerequisites = TextAreaField("Prerequisites", validators=[Optional()])

    def validate_price(self, field):
        try:
            value = float(field.data)
        except (TypeError, ValueError):
            raise ValidationError("Enter a valid course price.")
        if value < 0:
            raise ValidationError("Course price cannot be negative.")


class ArticleForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(min=3, max=200)])
    slug = StringField("Slug", validators=[DataRequired(), Length(min=3, max=200)])
    excerpt = TextAreaField("Excerpt", validators=[DataRequired(), Length(min=20, max=500)])
    body = TextAreaField("Body", validators=[DataRequired()])
    category_id = SelectField("Category", coerce=int, validators=[Optional()])
    author_name = StringField("Author", validators=[Optional(), Length(max=120)])
    seo_title = StringField("SEO title", validators=[Optional(), Length(max=200)])
    seo_description = TextAreaField("SEO description", validators=[Optional(), Length(max=300)])
    status = SelectField("Status", choices=[("draft", "Draft"), ("published", "Published")])
    cover_image = StringField("Cover image")


class ProjectForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(min=3, max=200)])
    slug = StringField("Slug", validators=[DataRequired(), Length(min=3, max=200)])
    client_name = StringField("Client name", validators=[Optional(), Length(max=200)])
    category = StringField("Category", validators=[Optional(), Length(max=120)])
    summary = TextAreaField("Summary", validators=[DataRequired(), Length(min=20, max=2000)])
    challenge = TextAreaField("Challenge", validators=[Optional()])
    services_delivered = TextAreaField("Services delivered", validators=[Optional()])
    solution = TextAreaField("Solution", validators=[Optional()])
    outcomes = TextAreaField("Outcomes", validators=[Optional()])
    featured_image = StringField("Featured image")
    gallery = TextAreaField("Gallery images")
    seo_title = StringField("SEO title", validators=[Optional(), Length(max=200)])
    seo_description = TextAreaField("SEO description", validators=[Optional(), Length(max=300)])
    status = SelectField("Status", choices=[("draft", "Draft"), ("published", "Published")])
    is_featured = HiddenField()


class CompanySettingsForm(FlaskForm):
    company_name = StringField("Company name", validators=[DataRequired(), Length(max=200)])
    tagline = StringField("Tagline", validators=[DataRequired(), Length(max=200)])
    contact_email = StringField("Email", validators=[DataRequired(), Email()])
    telephone = StringField("Telephone", validators=[DataRequired(), Length(max=50)])
    office_address = TextAreaField("Office address", validators=[DataRequired()])
    instagram_url = StringField("Instagram URL", validators=[Optional()])
    whatsapp_url = StringField("WhatsApp URL", validators=[Optional()])
    logo_url = StringField("Logo URL", validators=[Optional()])
    favicon_url = StringField("Favicon URL", validators=[Optional()])
    footer_text = TextAreaField("Footer text", validators=[Optional()])
    enquiry_notification_email = StringField("Enquiry recipient", validators=[DataRequired(), Email()])
    meta_description = TextAreaField("Meta description", validators=[Optional(), Length(max=300)])
    canonical_origin = StringField("Canonical origin", validators=[Optional()])
    academy_commission_percent = FloatField("Academy commission percentage", validators=[Optional(), NumberRange(min=0, max=100)])
    academy_minimum_payout_kobo = IntegerField("Minimum payout (kobo)", validators=[Optional(), NumberRange(min=0)])
