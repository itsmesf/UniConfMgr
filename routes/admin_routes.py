from flask import Blueprint, render_template, request, redirect, flash, session, url_for, abort
from models import Conference, User, ConferenceRole, UserRole  # IMPORT UserRole and ConferenceRole
from extensions import db
from functools import wraps
from datetime import datetime
from sqlalchemy.orm import joinedload

admin_bp = Blueprint("admin", __name__)


# --- DECORATOR (UPDATED) ---
def admin_required(f):
    """Decorator to ensure only admins can access"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access this page.", "error")
            return redirect(url_for("auth.login"))

        user = User.query.get(session["user_id"])
        # UPDATED: Check the boolean flags on the User object
        if not user or not (user.is_admin or user.is_super_admin):
            flash("You do not have administrative privileges to access this page.", "error")
            return redirect(url_for("main.index"))
        return f(*args, **kwargs)
    return decorated_function


# --- CONFERENCE MANAGEMENT ---

@admin_bp.route("/dashboard_admin/add_conference", methods=["GET", "POST"])
@admin_required
# Assuming this route uses an @admin_required decorator (not shown here, but essential)
def add_conference():
    """Handles the creation of a new conference by the Admin."""

    admin_id = session.get('user_id')
    if not admin_id:
        flash("You must be logged in to perform this action.", "error")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        # 1. Fetch ALL data, including the new fields
        title = request.form.get("title")
        description = request.form.get("description")
        start_date_str = request.form.get("start_date")
        end_date_str = request.form.get("end_date")
        location = request.form.get("location")

        # --- CRITICAL NEW FIELDS ---
        hosting_university = request.form.get("hosting_university")
        hosting_department = request.form.get("hosting_department")
        # ---------------------------

        author_fee_str = request.form.get("author_fee")
        participant_fee_str = request.form.get("participant_fee")

        # 2. Basic Validation (Ensure critical fields and new fields are present)
        if not all([title, start_date_str, end_date_str, hosting_university, hosting_department]):
            flash("Missing required fields (Title, Dates, University, Department).", "error")
            return redirect(url_for("admin.add_conference"))

        try:
            # Convert dates and ensure logical order
            start_date_obj = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_date_obj = datetime.strptime(end_date_str, "%Y-%m-%d").date()

            if start_date_obj > end_date_obj:
                flash("Start date cannot be after the end date.", "error")
                return redirect(url_for("admin.add_conference"))

            # Convert fees (using safe float conversion, defaulting to 0)
            author_fee = float(author_fee_str) if author_fee_str else 0.00
            participant_fee = float(participant_fee_str) if participant_fee_str else 0.00

        except (ValueError, TypeError) as e:
            flash(f"Invalid format for date or fee: {e}", "error")
            return redirect(url_for("admin.add_conference"))

        # 3. Create Conference Object (Including new columns)
        new_conf = Conference(
            title=title,
            description=description,
            start_date=start_date_obj,
            end_date=end_date_obj,
            location=location,
            hosting_university=hosting_university,  # NEW
            hosting_department=hosting_department,  # NEW
            author_fee=author_fee,
            participant_fee=participant_fee,
            created_by_admin_id=admin_id
        )

        db.session.add(new_conf)
        db.session.commit()
        flash(f"Conference '{title}' added successfully!", "success")

        # Redirect to the conference list view
        return redirect(url_for("admin.view_conference"))

        # GET request: Render the form
    return render_template("admin/add_conference.html")


@admin_bp.route("/dashboard_admin/view_conference")
@admin_required
def view_conference():
    admin_id = session["user_id"]
    conferences = Conference.query.filter_by(created_by_admin_id=admin_id).all()
    return render_template("admin/view_conference.html", conferences=conferences)


@admin_bp.route("/dashboard_admin/delete_conference/<int:conf_id>", methods=["POST"])
@admin_required
def delete_conference(conf_id):
    conference = Conference.query.get(conf_id)
    if conference and conference.created_by_admin_id == session["user_id"]:
        db.session.delete(conference)
        db.session.commit()
        flash("Conference deleted successfully!", "success")
    else:
        flash("Conference not found or cannot be deleted.", "error")
    return redirect(url_for("admin.view_conference"))


# --- ORGANIZER MANAGEMENT (CRUCIAL ROUTE ADDED) ---

@admin_bp.route("/view_organisers/<int:conf_id>")
@admin_required
def view_organisers(conf_id):
    """View and manage PENDING organizer requests for a conference."""
    conference = Conference.query.get_or_404(conf_id)
    if conference.created_by_admin_id != session["user_id"]:
        flash("Access denied.", "error")
        return redirect(url_for("admin.view_conference"))

    # Fetch all pending organizer roles (status=0) for this conference
    pending_organizer_roles = ConferenceRole.query.filter_by(
        conference_id=conf_id,
        role=UserRole.organizer,
        status=0
    ).all()

    # Renders the template you already have (view_organisers.html)
    return render_template("admin/view_organisers.html",
                           conference=conference,
                           roles=pending_organizer_roles)


@admin_bp.route("/role_action/<int:role_id>/<action>", methods=["POST"])
@admin_required
def role_action(role_id, action):
    """Approve or reject a user's role for a conference."""
    role = ConferenceRole.query.get_or_404(role_id)

    # 1. Store the name before any database operations, in case we need it for the flash message.
    user_name = role.user.name
    conf_id = role.conference_id

    # Security check: ensure the admin owns the conference for this role
    conference = Conference.query.get(conf_id)
    if not conference or conference.created_by_admin_id != session["user_id"]:
        flash("Access denied.", "error")
        return redirect(url_for("admin.view_conference"))

    # Perform the action on the ConferenceRole record
    if action == "approve":
        role.status = 1  # 1 = Approved
        db.session.commit()
        flash(f"Role for '{user_name}' approved successfully.", "success")

    elif action == "reject":
        db.session.delete(role)
        db.session.commit()
        flash(f"Role for '{user_name}' revoked and removed.", "success")

    else:
        flash("Invalid action.", "error")

    # Redirects back to the conference's manage page, now correctly named
    return redirect(url_for("admin.view_organisers", conf_id=conf_id))


@admin_bp.route("/view_all_organizers")
@admin_required
def view_all_organizers():
    """Displays a list of all approved organizers across all conferences."""
    all_approved_organizer_roles = ConferenceRole.query.options(
        joinedload(ConferenceRole.user),
        joinedload(ConferenceRole.conference)
    ).filter(
        ConferenceRole.role == UserRole.organizer,
        ConferenceRole.status == 1
    ).order_by(ConferenceRole.conference_id).all()

    return render_template(
        "admin/view_all_organizers.html",
        organizer_roles=all_approved_organizer_roles
    )


@admin_bp.route("/manage_pending_participants")
@admin_required
def manage_pending_participants():
    """Displays a list of all participants with status=0 (pending/unapproved)."""

    # Fetch all ConferenceRole entries where role is Participant and status is 0
    pending_roles = ConferenceRole.query.options(db.joinedload(ConferenceRole.user)).filter_by(
        role=UserRole.participant,
        status=0
    ).all()

    return render_template(
        "admin/manage_pending_participants.html",
        pending_roles=pending_roles
    )


@admin_bp.route("/delete_pending_participant/<int:role_id>", methods=["POST"])
@admin_required
def delete_pending_participant(role_id):
    """Deletes a specific ConferenceRole entry if it's a participant and status is 0."""

    # Fetch the role and ensure it is the correct type and status before deletion
    role_to_delete = ConferenceRole.query.filter_by(
        id=role_id,
        role=UserRole.participant,
        status=0
    ).first()

    if not role_to_delete:
        flash("Error: The role was not found or is already approved.", "error")
        return redirect(url_for("admin.manage_pending_participants"))

    user_name = role_to_delete.user.name

    try:
        db.session.delete(role_to_delete)
        db.session.commit()
        flash(f"Successfully deleted pending participant role for {user_name}.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Database error during deletion: {e}", "error")

    return redirect(url_for("admin.manage_pending_participants"))