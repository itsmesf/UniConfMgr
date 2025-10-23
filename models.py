
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta, timezone
from flask import current_app
from itsdangerous import URLSafeTimedSerializer as Serializer
from enum import Enum as PyEnum
from extensions import db
from datetime import date
TOKEN_EXPIRATION_SEC = 1800


# ---------- ENUM DEFINITIONS ----------
class UserRole(PyEnum):
    participant = "participant"
    author = "author"
    reviewer = "reviewer"
    organizer = "organizer"
    admin = "admin"


class PaperStatus(PyEnum):
    submitted = "submitted"
    under_review = "under_review"
    accepted = "accepted"
    rejected = "rejected"
    revision_required = "revision_required"


class PaymentStatus(PyEnum):
    pending = "pending"
    completed = "completed"
    failed = "failed"


class ReviewRecommendation(PyEnum):
    accept = "accept"
    reject = "reject"
    revision_required = "revision_required"


class CertificateType(PyEnum):
    author = "author"
    participant = "participant"
    reviewer = "reviewer"


class ConferenceStatus(PyEnum):
    upcoming = "upcoming"
    ongoing = "ongoing"
    completed = "completed"


# ---------- MODELS ----------
class User(db.Model):
    __tablename__ = "users"
    user_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(200), nullable=False)
    university_name = db.Column(db.String(200))
    department = db.Column(db.String(200))
    contact_no = db.Column(db.String(20))
    is_super_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    is_email_verified = db.Column(db.Boolean, default=False, nullable=False)

    conference_roles = db.relationship("ConferenceRole", back_populates="user", cascade="all, delete-orphan")

    def get_reset_token(self, expires_sec=1800):
        """Generates a secure, timed token for password reset."""
        s = Serializer(current_app.config['SECRET_KEY'])
        return s.dumps({'user_id': self.user_id})

    @staticmethod
    def verify_reset_token(token, expires_sec=1800):
        """Verifies the reset token and returns the user if valid."""
        s = Serializer(current_app.config['SECRET_KEY'])
        try:
            data = s.loads(token, max_age=expires_sec)
            user_id = data.get('user_id')
        except:
            return None
        return User.query.get(user_id)

    def get_verification_token(self, expires_sec=TOKEN_EXPIRATION_SEC):
        """Generates a secure, timed token for email verification."""
        s = Serializer(current_app.config['SECRET_KEY'])
        # Use user_id and creation time in the token payload
        return s.dumps({'user_id': self.user_id, 'created_at': datetime.now().timestamp()})

    @staticmethod
    def verify_email_token(token):
        """Verifies the token and returns the user if valid."""
        s = Serializer(current_app.config['SECRET_KEY'])
        try:
            data = s.loads(token)
            user_id = data.get('user_id')
        except:
            return None
        return User.query.get(user_id)

    def __repr__(self):
        return f"<User {self.name}>"


class ConferenceRole(db.Model):
    __tablename__ = "conference_roles"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.user_id"), nullable=False)
    conference_id = db.Column(db.Integer, db.ForeignKey("conferences.conference_id"), nullable=False)
    role = db.Column(db.Enum(UserRole), nullable=False, index=True)
    status = db.Column(db.Integer, nullable=False, default=0, index=True)
    expertise = db.Column(db.Text)

    user = db.relationship("User", back_populates="conference_roles")
    conference = db.relationship("Conference", back_populates="roles")

    paper = db.relationship("Paper", back_populates="author_role", uselist=False, cascade="all, delete-orphan")
    reviews_conducted = db.relationship("Review", back_populates="reviewer_role", cascade="all, delete-orphan")
    registration_link = db.relationship(
        "Registration",
        back_populates="role_link",  # Property name on the Registration model
        uselist=False,
        cascade="all, delete-orphan"
    )
    sessions_chaired = db.relationship("Session", back_populates="session_chair_role",
                                       foreign_keys='Session.session_chair_role_id')

    __table_args__ = (db.UniqueConstraint('user_id', 'conference_id', name='_user_conference_uc'),)

    def __repr__(self):
        return f"<ConferenceRole UserID: {self.user_id} as {self.role.value} in ConfID: {self.conference_id}>"


class Conference(db.Model):
    __tablename__ = "conferences"
    conference_id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False, index=True)
    hosting_university = db.Column(db.String(200), nullable=False, index=True)
    hosting_department = db.Column(db.String(200), nullable=False, index=True)
    final_schedule_file = db.Column(db.String(200), nullable=True)
    description = db.Column(db.Text)
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=False, index=True)
    location = db.Column(db.String(200))
    author_fee = db.Column(db.Numeric(10, 2), nullable=False)
    participant_fee = db.Column(db.Numeric(10, 2), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    created_by_admin_id = db.Column(db.Integer, db.ForeignKey("users.user_id"), nullable=False, index=True)
    @property

    def status(self):
        """Calculates the conference status dynamically based on current date."""
        today = date.today()
        if self.start_date > today:
            return "upcoming"
        elif self.end_date < today:
            return "completed"
        else:
            return "ongoing"

    @property
    def main_organizer(self):
        """A helper property to find the first approved organizer."""
        for role in self.roles:
            if role.role == UserRole.organizer and role.status == 1:
                return role.user  # Returns the full User object
        return None

    # UPDATED: Relationships now reflect the new structure
    roles = db.relationship("ConferenceRole", back_populates="conference", cascade="all, delete-orphan")
    tracks = db.relationship("Track", back_populates="conference", cascade="all, delete-orphan", lazy=True)
    sessions = db.relationship("Session", back_populates="conference", cascade="all, delete-orphan", lazy=True)
    created_by = db.relationship("User", foreign_keys=[created_by_admin_id])
    registrations = db.relationship("Registration", back_populates="conference", cascade="all, delete-orphan",
                                    lazy=True)

    def __repr__(self):
        return f"<Conference {self.title}>"


class Track(db.Model):
    __tablename__ = "tracks"
    track_id = db.Column(db.Integer, primary_key=True)
    conference_id = db.Column(db.Integer, db.ForeignKey("conferences.conference_id"), nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False, index=True)
    description = db.Column(db.Text)

    conference = db.relationship("Conference", back_populates="tracks")
    papers = db.relationship("Paper", back_populates="track", lazy=True)
    sessions = db.relationship("Session", back_populates="track", cascade="all, delete-orphan", lazy=True)

    def __repr__(self):
        return f"<Track {self.name}>"


class Session(db.Model):
    __tablename__ = "sessions"
    session_id = db.Column(db.Integer, primary_key=True)
    conference_id = db.Column(db.Integer, db.ForeignKey("conferences.conference_id"), nullable=False, index=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.track_id"), nullable=True)
    name = db.Column(db.String(150), nullable=False, index=True)
    schedule_time = db.Column(db.DateTime, index=True)
    location = db.Column(db.String(150))
    # UPDATED: Foreign key now points to ConferenceRole
    session_chair_role_id = db.Column(db.Integer, db.ForeignKey("conference_roles.id"), nullable=True, index=True)



    conference = db.relationship("Conference", back_populates="sessions")
    track = db.relationship("Track", back_populates="sessions")
    session_chair_role = db.relationship("ConferenceRole", back_populates="sessions_chaired",
                                         foreign_keys=[session_chair_role_id])
    papers_in_session = db.relationship("SessionPaper", back_populates="session", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Session {self.name}>"


class Paper(db.Model):
    __tablename__ = "papers"
    paper_id = db.Column(db.Integer, primary_key=True)
    # UPDATED: Foreign key now points to ConferenceRole
    author_role_id = db.Column(db.Integer, db.ForeignKey("conference_roles.id"), nullable=False, index=True)
    conference_id = db.Column(db.Integer, db.ForeignKey("conferences.conference_id"), nullable=False, index=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.track_id"), nullable=True)
    title = db.Column(db.String(250), nullable=False, index=True)
    abstract = db.Column(db.Text)
    keywords = db.Column(db.String(250))
    blind_paper_file = db.Column(db.String(200), nullable=False)
    camera_ready_file = db.Column(db.String(200))
    status = db.Column(db.Enum(PaperStatus), default=PaperStatus.submitted, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    author_role = db.relationship("ConferenceRole", back_populates="paper")
    conference = db.relationship("Conference")  # No back_populates needed as it's not a collection
    track = db.relationship("Track", back_populates="papers")
    reviews = db.relationship("Review", back_populates="paper", cascade="all, delete-orphan", lazy=True)
    session_assignments = db.relationship("SessionPaper", back_populates="paper", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Paper {self.title} ({self.status.value})>"


class Review(db.Model):
    __tablename__ = "reviews"
    review_id = db.Column(db.Integer, primary_key=True)
    paper_id = db.Column(db.Integer, db.ForeignKey("papers.paper_id"), nullable=False, index=True)
    # UPDATED: Foreign key now points to ConferenceRole
    reviewer_role_id = db.Column(db.Integer, db.ForeignKey("conference_roles.id"), nullable=False, index=True)
    comments_to_author = db.Column(db.Text)
    comments_to_organiser = db.Column(db.Text)
    score = db.Column(db.Integer, index=True)
    recommendation = db.Column(db.Enum(ReviewRecommendation))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    paper = db.relationship("Paper", back_populates="reviews")
    reviewer_role = db.relationship("ConferenceRole", back_populates="reviews_conducted")

    def __repr__(self):
        return f"<Review {self.review_id} - Score {self.score}>"


class Registration(db.Model):
    __tablename__ = "registrations"
    registration_id = db.Column(db.Integer, primary_key=True)
    # UPDATED: Foreign key now points to ConferenceRole
    role_id = db.Column(db.Integer, db.ForeignKey("conference_roles.id"), nullable=False, unique=True, index=True)
    conference_id = db.Column(db.Integer, db.ForeignKey("conferences.conference_id"), nullable=False, index=True)
    registration_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    fee_amount = db.Column(db.Numeric(10, 2), nullable=False)
    payment_status = db.Column(db.Enum(PaymentStatus), default=PaymentStatus.pending, nullable=False, index=True)

    # FINAL FIX: The property name is 'role_link', and it back-populates 'registration_link' on the parent.
    role_link = db.relationship("ConferenceRole", back_populates="registration_link")

    # NEW: Fix Conference relationship (This was also potentially causing conflicts)
    conference = db.relationship("Conference", back_populates="registrations")

    def __repr__(self):
        return f"<Registration RoleID {self.role_id} for ConfID {self.conference_id}>"


# REMOVED: OrganizerRole and ConferenceReviewer models are no longer needed.

class SessionPaper(db.Model):
    __tablename__ = "session_papers"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.session_id"), nullable=False, index=True)
    paper_id = db.Column(db.Integer, db.ForeignKey("papers.paper_id"), nullable=False, unique=True)
    # UPDATED: Foreign key can point to ConferenceRole for the presenter
    presenter_role_id = db.Column(db.Integer, db.ForeignKey("conference_roles.id"), nullable=False, index=True)
    presentation_time = db.Column(db.DateTime, index=True)

    session = db.relationship("Session", back_populates="papers_in_session")

    # CRITICAL FIX: Ensure the paper relationship allows the join back to AuthorRole
    paper = db.relationship("Paper", back_populates="session_assignments",
                            primaryjoin="SessionPaper.paper_id == Paper.paper_id",
                            foreign_keys="SessionPaper.paper_id",
                            uselist=False)  # Important for clarity

    presenter_role = db.relationship("ConferenceRole")


class Certificate(db.Model):
    __tablename__ = "certificates"
    certificate_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    # UPDATED: Should link to the specific role that earned the certificate
    role_id = db.Column(db.Integer, db.ForeignKey("conference_roles.id"), nullable=False, index=True)
    certificate_type = db.Column(db.Enum(CertificateType), nullable=False, index=True)
    file_path = db.Column(db.String(200))
    issued_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    conference_role = db.relationship("ConferenceRole")


class OTPVerification(db.Model):
    __tablename__ = "otp_verifications"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, index=True)
    otp_code = db.Column(db.String(6), nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc) + timedelta(minutes=10),
                           nullable=False)

    def __repr__(self):
        return f"<OTP {self.otp_code} for {self.email}>"