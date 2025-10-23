from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash
from extensions import db
from models import User, Conference, ConferenceRole, UserRole, Registration, PaymentStatus, PaperStatus, Paper
from .auth_routes import login_required

roles_bp = Blueprint("roles", __name__)


@roles_bp.route("/apply/<int:conference_id>/<role_name>", methods=["GET", "POST"])
@login_required
def apply_for_role(conference_id, role_name):
    """
    Handles role application: redirects Author/Reviewer/Participant to forms on GET,
    and processes immediate role creation for Organizer.
    """
    conference = Conference.query.get_or_404(conference_id)
    user = User.query.get(session['user_id'])

    try:
        requested_role = UserRole[role_name]
    except KeyError:
        flash("Invalid role specified.", "error")
        return redirect(url_for("conference.explore_conferences"))

    # 1. CHECK FOR EXISTING ROLE
    existing_role = ConferenceRole.query.filter_by(
        user_id=user.user_id, conference_id=conference_id).first()
    if existing_role:
        flash(f"You already have a role for this conference.", "warning")
        return redirect(url_for("auth.dashboard"))  # Redirect to user hub (assuming explore_more is too specific)

    # --- HANDLE POST REQUEST (Generic POST is primarily for simple roles) ---
    if request.method == "POST":
        # NOTE: This block is currently set up for generic role creation if a simple form posts back here.

        # 1. Author and Reviewer POSTs are handled by their own Blueprints.
        if requested_role in [UserRole.reviewer, UserRole.author]:
            flash(f"Application error: Complex {role_name.title()} forms should post to their dedicated routes.",
                  "error")
            return redirect(url_for("conference.explore_more", conf_id=conference_id))

        # 2. General POST logic (for participant, if they used a form posting back here)
        # This will be replaced by the dedicated 'register_participant' POST route logic later.

        flash("Generic role submission successful (POST).", "success")
        return redirect(url_for("conference.explore_more", conf_id=conference_id))

    # --- HANDLE GET REQUEST (DISPLAYING THE FORM / REDIRECTION) ---

    if requested_role == UserRole.reviewer:
        # Reviewer: Redirect to expertise form
        return redirect(url_for('reviewer.apply_registration', conf_id=conference_id))

    # --- HANDLE Participant and Organizer ---

    if requested_role == UserRole.participant:
        # Participant: Render the dedicated registration page (for payment/final steps)
        # This is where your current logic sends the user, which is correct for form display.
        return render_template(
            'participant/participant_register.html',
            conference=conference,
            role_name=role_name
        )

    if requested_role == UserRole.organizer:
        # Organizer: Immediate creation (no form needed)

        new_role_request = ConferenceRole(
            user_id=user.user_id,
            conference_id=conference.conference_id,
            role=requested_role,
            status=0
        )
        db.session.add(new_role_request)
        db.session.commit()

        flash(f"Your application as a(n) {role_name.title()} has been submitted! Please await approval.", "success")
        return redirect(url_for("conference.explore_more", conf_id=conference_id))

    elif requested_role == UserRole.author:
        # AUTHOR: Immediate creation with status=1 to grant dashboard access instantly.
        # This aligns with the new requirement that the Author dashboard must be available immediately.

        new_role_request = ConferenceRole(
            user_id=user.user_id,
            conference_id=conference.conference_id,
            role=requested_role,
            status=1  # CRITICAL FIX: Set status to 1 for immediate dashboard access
        )
        db.session.add(new_role_request)
        db.session.commit()

        flash(f"You are now registered as an Author! You can now submit your paper from your dashboard.", "success")

        # Redirect to the protected Author Dashboard
        return redirect(url_for("author.dashboard", conf_id=conference_id))

    # Fallback return (should be unreachable)
    flash("Application failed.", "error")
    return redirect(url_for("conference.explore_more", conf_id=conference_id))

@roles_bp.route("/register_participant/<int:conference_id>", methods=["POST"])
@login_required
def register_participant(conference_id):
    conference = Conference.query.get_or_404(conference_id)
    user_id = session['user_id']
    fee_amount_value = float(conference.participant_fee)

    # 1. CREATE USER ROLE
    new_role = ConferenceRole(
        user_id=user_id,
        conference_id=conference_id,
        role=UserRole.participant,
        status=1
    )
    db.session.add(new_role)  # Add to session first

    # 2. CREATE REGISTRATION (Passing the new_role OBJECT)
    new_registration = Registration(
        # FIX: Pass the object 'new_role' instead of an ID.
        # SQLAlchemy will fetch the ID automatically during commit.
        role_link=new_role,
        conference_id=conference_id,
        fee_amount=fee_amount_value,
        payment_status=PaymentStatus.completed
    )
    db.session.add(new_registration)
    db.session.commit()  # This commit now succeeds.

    flash("Registration and payment successful! You are now a confirmed participant.", "success")
    return redirect(url_for("auth.dashboard"))


@roles_bp.route("/register_as_participant_after_rejection/<int:conf_id>", methods=["GET"])
@login_required
def register_as_participant_after_rejection(conf_id):
    """Deletes the rejected Author role and redirects the user to the Participant registration form."""
    user_id = session['user_id']
    conference = Conference.query.get_or_404(conf_id)

    # 1. Find the REJECTED Author Role
    author_role = ConferenceRole.query.filter_by(
        user_id=user_id,
        conference_id=conf_id,
        role=UserRole.author
    ).first()

    # 2. Delete the Rejected Author Role (ensures cascade deletes the Paper and Registration if they exist)
    if author_role:
        # Check if their paper was actually rejected to proceed with deletion
        # This requires fetching the associated paper to confirm status
        paper = Paper.query.filter_by(author_role_id=author_role.id).first()

        if paper and paper.status == PaperStatus.rejected:
            # Delete the role; cascades should handle the paper automatically
            db.session.delete(author_role)
            db.session.commit()
            flash("Rejected Author status cleared. Proceeding to participant registration.", "info")
        else:
            # If the paper status is still submitted/accepted, deny deletion
            flash("Cannot switch roles; your paper status is still pending or accepted.", "error")
            return redirect(url_for('author.dashboard', conf_id=conf_id))

    # 3. Redirect to the Participant Registration Form
    # This assumes the Participant registration needs a form (for payment/info)
    return redirect(url_for('participant.participant_registration', conf_id=conf_id))