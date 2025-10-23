from flask import Blueprint, render_template, redirect, flash, session, url_for,current_app, send_file, abort, request
from models import Conference, User, ConferenceRole, UserRole, Track, Session,ReviewRecommendation,SessionPaper,Paper, Review, PaperStatus, Registration, PaymentStatus# Ensure all models are imported
from extensions import db
from routes.auth_routes import send_rejection_email
from routes.publish_schedule_pdf import generate_pdf_from_html
from functools import wraps
from datetime import datetime
from werkzeug.utils import secure_filename
import os

organizer_bp = Blueprint("organizer", __name__)

# --- DECORATOR for Organizers ---
def organizer_required(f):

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access this page.", "error")
            return redirect(url_for("auth.login"))

        # Get the conference ID from the URL
        conference_id = kwargs.get("conf_id")
        if not conference_id:
            # Handle cases where conf_id might be missing (shouldn't happen with current setup)
            abort(400)

            # Check if the user has an approved organizer role for this conference
        is_organizer = ConferenceRole.query.filter_by(
            user_id=session["user_id"],
            conference_id=conference_id,
            role=UserRole.organizer,
            status=1  # Must be an APPROVED organizer
        ).first()

        if not is_organizer:
            flash("You do not have organizer privileges for this conference.", "error")
            return redirect(url_for("auth.dashboard"))

        return f(*args, **kwargs)

    return decorated_function

# --- ORGANIZER ROUTES ---

@organizer_bp.route("/dashboard/<int:conf_id>")
@organizer_required
def dashboard(conf_id):

    conference = Conference.query.get_or_404(conf_id)

    pending_reviewers_count = ConferenceRole.query.filter_by(
        conference_id=conf_id,
        role=UserRole.reviewer,
        status=0  # 0 = Pending
    ).count()

    tracks_count = Track.query.filter_by(conference_id=conf_id).count()

    # Simple count of all users with an approved role (status=1)
    approved_users_count = db.session.query(ConferenceRole.user_id).filter_by(
        conference_id=conf_id,
        status=1
    ).distinct().count()
    papers_submitted_count = Paper.query.filter_by(
        conference_id=conf_id,
        # Optionally, filter by status if you only want papers still in the pipeline
        # status=PaperStatus.submitted
    ).count()

    return render_template(
        "organiser/dashboard_organizer.html",
        conference=conference,
        pending_reviewers_count=pending_reviewers_count,
        tracks_count=tracks_count,
        approved_users_count=approved_users_count,
        papers_submitted_count = papers_submitted_count
    )


# --- 1. USER MANAGEMENT ROUTES ---

@organizer_bp.route("/participants/<int:conf_id>/<role_filter>")
@organizer_required
def view_participants(conf_id, role_filter):
    """
    Unified route to view Participants, Authors, or Approved Reviewers
    based on the 'role_filter' URL parameter.
    """
    conference = Conference.query.get_or_404(conf_id)

    # Validate and set the role to filter
    try:
        if role_filter == "all":
            # For "all", we fetch approved users with any participant-type role
            target_roles = [UserRole.participant, UserRole.author, UserRole.reviewer]
            filter_label = "All Approved Participants"
        else:
            target_role = UserRole(role_filter)
            target_roles = [target_role]
            filter_label = f"Approved {target_role.value.title()}s"
    except ValueError:
        flash("Invalid role filter.", "error")
        return redirect(url_for("organizer.dashboard", conf_id=conf_id))

    # Fetch users with the approved role(s)
    approved_roles = ConferenceRole.query.options(db.joinedload(ConferenceRole.user)).filter(
        ConferenceRole.conference_id == conf_id,
        ConferenceRole.status == 1,  # Only approved roles
        ConferenceRole.role.in_(target_roles)
    ).all()

    # Group by User ID to prevent duplicates if a user has multiple roles (e.g., author and participant)
    user_map = {}
    for role_item in approved_roles:
        if role_item.user_id not in user_map:
            user_map[role_item.user_id] = role_item.user

    users = list(user_map.values())

    return render_template(
        "organiser/view_participants.html",  # A unified template handles all views
        conference=conference,
        users=users,
        role_filter=role_filter,
        filter_label=filter_label
    )


@organizer_bp.route("/manage_reviewers/<int:conf_id>")
@organizer_required
def manage_reviewers(conf_id):
    """View and manage PENDING REVIEWER requests for this conference."""
    conference = Conference.query.get_or_404(conf_id)

    pending_reviewer_roles = ConferenceRole.query.options(db.joinedload(ConferenceRole.user)).filter_by(
        conference_id=conf_id,
        role=UserRole.reviewer,
        status=0  # 0 = Pending
    ).all()

    all_tracks = Track.query.filter_by(conference_id=conf_id).all()

    # Create a dict: { '1': 'AI & Machine Learning', '2': 'HCI', ... }
    track_lookup = {str(t.track_id): t.name for t in all_tracks}

    return render_template(
        "organiser/manage_reviewers.html",
        conference=conference,
        roles=pending_reviewer_roles,
        track_lookup = track_lookup
    )


@organizer_bp.route("/reviewer_action/<int:conf_id>/<int:role_id>/<action>", methods=["POST"])
@organizer_required
def reviewer_action(conf_id, role_id, action):
    """Approve or reject a reviewer's role."""

    role_to_action = ConferenceRole.query.filter_by(
        id=role_id,
        conference_id=conf_id,
        role=UserRole.reviewer,
        status=0 # Must be a pending role
    ).first_or_404()

    if role_to_action.user_id == session["user_id"]:
        flash("You cannot approve or reject your own reviewer request.", "error")
        return redirect(url_for("organizer.manage_reviewers", conf_id=conf_id))

    # --- CRITICAL FIX: Access user name NOW before any database operations ---
    # This triggers the lazy load while the object is still attached to the session.
    user_name = role_to_action.user.name
    # -----------------------------------------------------------------------

    if action == "approve":
        role_to_action.status = 1
        db.session.commit()
        flash(f"Reviewer '{user_name}' approved.", "success") # Use the pre-loaded name

    elif action == "reject":
        # The crash occurred here because db.session.delete() or db.session.commit() detaches the object.
        db.session.delete(role_to_action)
        db.session.commit()
        flash(f"Reviewer '{user_name}' rejected (role removed).", "success") # Use the pre-loaded name

    else:
        flash("Invalid action.", "error")

    return redirect(url_for("organizer.manage_reviewers", conf_id=conf_id))

# --- 2. TRACKS & SESSIONS ROUTES ---

@organizer_bp.route("/tracks_sessions/<int:conf_id>")
@organizer_required
def tracks_sessions(conf_id):
    """Main view for managing Tracks and Sessions."""
    conference = Conference.query.get_or_404(conf_id)

    # Fetch all tracks for the conference, eagerly loading sessions
    tracks = Track.query.options(db.joinedload(Track.sessions)).filter_by(
        conference_id=conf_id
    ).order_by(Track.track_id).all()

    # We also need approved session chairs (reviewers or authors often) for the dropdown
    potential_chairs = ConferenceRole.query.options(db.joinedload(ConferenceRole.user)).filter(
        ConferenceRole.conference_id == conf_id,
        ConferenceRole.status == 1,
        ConferenceRole.role.in_([UserRole.reviewer, UserRole.author, UserRole.organizer])
    ).all()

    return render_template(
        "organiser/tracks_sessions.html",
        conference=conference,
        tracks=tracks,
        potential_chairs=potential_chairs
    )


@organizer_bp.route("/add_track/<int:conf_id>", methods=["POST"])
@organizer_required
def add_track(conf_id):
    """Handles adding a new track."""
    track_name = request.form.get("name")
    track_description = request.form.get("description")

    if track_name:
        new_track = Track(
            conference_id=conf_id,
            name=track_name,
            description=track_description
        )
        db.session.add(new_track)
        db.session.commit()
        flash(f"Track '{track_name}' successfully added.", "success")
    else:
        flash("Track name is required.", "error")

    return redirect(url_for("organizer.tracks_sessions", conf_id=conf_id))


@organizer_bp.route("/edit_track/<int:conf_id>/<int:track_id>", methods=["POST"])
@organizer_required
def edit_track(conf_id, track_id):
    """Handles updating an existing track."""
    track = Track.query.filter_by(
        track_id=track_id,
        conference_id=conf_id
    ).first_or_404()

    track_name = request.form.get("name")
    track_description = request.form.get("description")

    if track_name:
        track.name = track_name
        track.description = track_description
        db.session.commit()
        flash(f"Track '{track_name}' updated successfully.", "success")
    else:
        flash("Track name cannot be empty.", "error")

    return redirect(url_for("organizer.tracks_sessions", conf_id=conf_id))


@organizer_bp.route("/delete_track/<int:conf_id>/<int:track_id>", methods=["POST"])
@organizer_required
def delete_track(conf_id, track_id):
    """Handles deleting a track."""
    track = Track.query.filter_by(
        track_id=track_id,
        conference_id=conf_id
    ).first_or_404()

    track_name = track.name
    db.session.delete(track)
    db.session.commit()
    flash(f"Track '{track_name}' deleted. Related sessions/papers might need review.", "warning")

    return redirect(url_for("organizer.tracks_sessions", conf_id=conf_id))


@organizer_bp.route("/add_session/<int:conf_id>", methods=["POST"])
@organizer_required
def add_session(conf_id):
    """Handles adding a new session."""
    session_name = request.form.get("name")
    schedule_time_str = request.form.get("schedule_time")  # Expecting "YYYY-MM-DDTHH:MM" from datetime-local input
    session_location = request.form.get("location")
    track_id = request.form.get("track_id")  # Can be empty/None if general session
    session_chair_role_id = request.form.get("session_chair_role_id")

    if not session_name or not schedule_time_str:
        flash("Session name and time are required.", "error")
        return redirect(url_for("organizer.tracks_sessions", conf_id=conf_id))

    try:
        schedule_time = datetime.strptime(schedule_time_str, "%Y-%m-%dT%H:%M")
    except ValueError:
        flash("Invalid date and time format. Please use the required input format.", "error")
        return redirect(url_for("organizer.tracks_sessions", conf_id=conf_id))

    new_session = Session(
        conference_id=conf_id,
        track_id=track_id if track_id else None,
        name=session_name,
        schedule_time=schedule_time,
        location=session_location,
        session_chair_role_id=session_chair_role_id if session_chair_role_id else None
    )
    db.session.add(new_session)
    db.session.commit()
    flash(f"Session '{session_name}' successfully added.", "success")

    return redirect(url_for("organizer.tracks_sessions", conf_id=conf_id))


@organizer_bp.route("/delete_session/<int:conf_id>/<int:session_id>", methods=["POST"])
@organizer_required
def delete_session(conf_id, session_id):
    """Handles deleting a session."""
    session_to_delete = Session.query.filter_by(
        session_id=session_id,
        conference_id=conf_id
    ).first_or_404()

    session_name = session_to_delete.name
    db.session.delete(session_to_delete)
    db.session.commit()
    flash(f"Session '{session_name}' deleted. Related papers were unassigned.", "warning")

    return redirect(url_for("organizer.tracks_sessions", conf_id=conf_id))


# --- CONFERENCE DETAILS MANAGEMENT ROUTE (Placeholder) ---

@organizer_bp.route("/edit_details/<int:conf_id>", methods=["GET", "POST"])
@organizer_required
def edit_details(conf_id):
    """Allows the Organizer to complete/edit general conference details."""
    conference = Conference.query.get_or_404(conf_id)

    if request.method == "POST":
        # 1. Fetch form data
        description = request.form.get("description")
        location = request.form.get("location")
        start_date_str = request.form.get("start_date")
        end_date_str = request.form.get("end_date")
        author_fee = request.form.get("author_fee")
        participant_fee = request.form.get("participant_fee")

        # 2. Validation and Type Conversion
        if not description or not location:
            flash("Description and Location are required fields.", "error")
            return redirect(url_for("organizer.edit_details", conf_id=conf_id))

        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            author_fee = float(author_fee)
            participant_fee = float(participant_fee)

            if start_date > end_date:
                flash("Start date cannot be after the end date.", "error")
                return redirect(url_for("organizer.edit_details", conf_id=conf_id))

        except (ValueError, TypeError) as e:
            flash(f"Invalid format for date or fees: {e}", "error")
            return redirect(url_for("organizer.edit_details", conf_id=conf_id))

        # 3. Update the Conference model
        conference.description = description
        conference.location = location
        conference.start_date = start_date
        conference.end_date = end_date
        conference.author_fee = author_fee
        conference.participant_fee = participant_fee

        db.session.commit()
        flash("Conference details updated successfully!", "success")
        return redirect(url_for("organizer.dashboard", conf_id=conf_id))

    # GET request: Render the form
    return render_template(
        "organiser/edit_details.html",
        conference=conference
    )

@organizer_bp.route("/edit_session/<int:conf_id>/<int:session_id>", methods=["POST"])
@organizer_required
def edit_session(conf_id, session_id):
    """Handles updating an existing session."""

    # 1. Fetch the session and verify it belongs to the conference
    session_to_edit = Session.query.filter_by(
        session_id=session_id,
        conference_id=conf_id
    ).first_or_404()

    # 2. Extract and validate form data
    session_name = request.form.get("name")
    schedule_time_str = request.form.get("schedule_time")
    session_location = request.form.get("location")
    track_id = request.form.get("track_id")  # Note: Can be changed or left as is
    session_chair_role_id = request.form.get("session_chair_role_id")

    if not session_name or not schedule_time_str:
        flash("Session name and time are required for updates.", "error")
        return redirect(url_for("organizer.tracks_sessions", conf_id=conf_id))

    try:
        schedule_time = datetime.strptime(schedule_time_str, "%Y-%m-%dT%H:%M")
    except ValueError:
        flash("Invalid date and time format.", "error")
        return redirect(url_for("organizer.tracks_sessions", conf_id=conf_id))

    # 3. Update the session object
    session_to_edit.name = session_name
    session_to_edit.schedule_time = schedule_time
    session_to_edit.location = session_location

    # Handle optional fields (can be set to NULL if form sends empty string/None)
    session_to_edit.track_id = track_id if track_id else None
    session_to_edit.session_chair_role_id = session_chair_role_id if session_chair_role_id else None

    # 4. Commit changes
    db.session.commit()
    flash(f"Session '{session_name}' updated successfully.", "success")

    return redirect(url_for("organizer.tracks_sessions", conf_id=conf_id))


@organizer_bp.route("/remove_approved_reviewer/<int:conf_id>/<int:user_id>", methods=["POST"])
@organizer_required
def remove_approved_reviewer(conf_id, user_id):
    """Deletes an APPROVED reviewer role from the conference."""

    role_to_delete = ConferenceRole.query.filter_by(
        user_id=user_id,
        conference_id=conf_id,
        role=UserRole.reviewer,
        status=1  # Must be approved!
    ).first()

    if not role_to_delete:
        flash("Error: Approved reviewer role not found.", "error")
        return redirect(url_for('organizer.view_participants', conf_id=conf_id, role_filter='reviewer'))

    user_name = role_to_delete.user.name

    try:
        # Now delete the object
        db.session.delete(role_to_delete)
        db.session.commit()

        # Now the flash message uses the name we already stored
        flash(f"Approved reviewer role for {user_name} has been removed.", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Database error during deletion: {e}", "error")

    return redirect(url_for('organizer.view_participants', conf_id=conf_id, role_filter='reviewer'))


@organizer_bp.route("/papers/<int:conf_id>")
@organizer_required
def manage_papers(conf_id):
    """View all submitted papers for this conference with author/review details."""
    conference = Conference.query.get_or_404(conf_id)

    # Fetch all papers, joining on the author role, user details, and reviews
    papers = Paper.query.options(
        db.joinedload(Paper.author_role).joinedload(ConferenceRole.user),
        db.joinedload(Paper.track),
        db.joinedload(Paper.reviews)  # Essential for counting assignments
    ).filter_by(conference_id=conf_id).all()

    return render_template(
        "organiser/manage_papers.html",
        conference=conference,
        papers=papers,
        # PaperStatus=PaperStatus # Pass the Enum for status display if needed
    )


@organizer_bp.route("/download_paper/<int:conf_id>/<int:paper_id>")
@organizer_required
def download_paper(conf_id, paper_id):
    """Allows Organizer to download the paper file."""
    paper = Paper.query.get_or_404(paper_id)

    # SECURITY CHECK: Ensure the paper belongs to the conference
    if paper.conference_id != conf_id:
        abort(403)  # Forbidden

    # Construct the file path
    file_path = os.path.join(current_app.root_path, 'uploads', 'blind_papers', paper.blind_paper_file)

    if not os.path.exists(file_path):
        flash("File not found on server.", "error")
        return redirect(url_for('organizer.manage_papers', conf_id=conf_id))

    # Return the file for download
    return send_file(
        file_path,
        as_attachment=True,
        download_name=f"{paper.paper_id}_blind_{paper.title}.pdf"
    )



@organizer_bp.route("/assign_reviewers_view/<int:conf_id>/<int:paper_id>")
@organizer_required
def assign_reviewers_view(conf_id, paper_id):
    """View to select and assign reviewers to a specific paper, prioritizing matching tracks."""

    conference = Conference.query.get_or_404(conf_id)
    paper = Paper.query.get_or_404(paper_id)

    # CRITICAL: Identify the target track ID
    target_track_id = str(paper.track_id) if paper.track_id else None

    # 1. Fetch all APPROVED reviewers
    all_approved_reviewers = ConferenceRole.query.options(db.joinedload(ConferenceRole.user)).filter(
        ConferenceRole.conference_id == conf_id,
        ConferenceRole.role == UserRole.reviewer,
        ConferenceRole.status == 1
    ).all()

    current_assignments = [review.reviewer_role_id for review in paper.reviews]

    # 2. Categorize reviewers by match status
    matching_reviewers = []
    other_reviewers = []

    for role in all_approved_reviewers:
        # Check if the reviewer's expertise string contains the paper's track ID
        # Note: We must handle cases where role.expertise is NULL or empty
        expertise_list = role.expertise.split(',') if role.expertise else []

        # Use strip() to handle whitespace in stored expertise IDs (e.g., "1, 2, 3")
        is_match = target_track_id and (target_track_id in [eid.strip() for eid in expertise_list])

        # Add a custom attribute to the role object for template use
        role.has_track_match = is_match

        if is_match:
            matching_reviewers.append(role)
        else:
            other_reviewers.append(role)

    # 3. Create a final, ordered list: Matches first, then others.
    reviewers_list = matching_reviewers + other_reviewers

    # Fetch all tracks for the lookup (same as before)
    all_tracks = Track.query.filter_by(conference_id=conf_id).all()
    track_lookup = {str(t.track_id): t.name for t in all_tracks}

    return render_template(
        "organiser/assign_reviewers.html",
        conference=conference,
        paper=paper,
        reviewers=reviewers_list,  # <--- Use the prioritized list
        current_assignments=current_assignments,
        track_lookup=track_lookup,
        target_track_id=target_track_id
    )


@organizer_bp.route("/assign_reviewers_post/<int:conf_id>/<int:paper_id>", methods=["POST"])
@organizer_required
def assign_reviewers_post(conf_id, paper_id):
    """Handles the form submission (POST) to assign reviewers and update paper status."""

    paper = Paper.query.get_or_404(paper_id)

    reviewer_role_ids = request.form.getlist("reviewer_role_id")

    if not reviewer_role_ids:
        flash("Please select at least one reviewer to assign.", "warning")
        return redirect(url_for('organizer.assign_reviewers_view', conf_id=conf_id, paper_id=paper_id))

    successful_assignments = 0

    for role_id_str in reviewer_role_ids:
        role_id = int(role_id_str)

        # 1. Check if the assignment already exists
        existing_review = Review.query.filter_by(
            paper_id=paper_id,
            reviewer_role_id=role_id
        ).first()

        if existing_review:
            continue  # Skip if already assigned

        # 2. Create the new Review record (the assignment)
        new_review = Review(
            paper_id=paper_id,
            reviewer_role_id=role_id
        )
        db.session.add(new_review)
        successful_assignments += 1

    db.session.commit()

    if successful_assignments > 0:
        flash(f"Successfully assigned {successful_assignments} new reviewer(s) to paper: {paper.title}.", "success")

        # 3. Update paper status to 'under_review' if it was 'submitted'
        if paper.status == PaperStatus.submitted:
            paper.status = PaperStatus.under_review
            db.session.commit()

    else:
        flash("No new reviewers were assigned (they may have already been assigned).", "warning")

    # Redirect back to the main paper list
    return redirect(url_for('organizer.manage_papers', conf_id=conf_id))


@organizer_bp.route("/view_reviews/<int:conf_id>/<int:paper_id>")
@organizer_required
def view_reviews(conf_id, paper_id):
    """Displays all submitted reviews for a single paper to the Organizer."""

    paper = Paper.query.options(
        db.joinedload(Paper.reviews).joinedload(Review.reviewer_role).joinedload(ConferenceRole.user)
    ).get_or_404(paper_id)

    if paper.conference_id != conf_id:
        abort(403)

    is_decision_made = paper.status not in [PaperStatus.submitted, PaperStatus.under_review]

    # Check for unlock flag in URL
    edit_mode = request.args.get('edit', 'false') == 'true'

    # CRITICAL: Form is LOCKED if a decision has been made AND edit_mode is FALSE
    is_locked = is_decision_made and not edit_mode

    # Fetch all approved reviewers to compare against assigned list (optional)

    return render_template(
        "organiser/final_decision_form.html",
        conference_id=conf_id,
        paper=paper,
        submitted_reviews=[r for r in paper.reviews if r.recommendation] , # Filter for completed reviews
        recommendations = ReviewRecommendation,
        final_statuses=[PaperStatus.accepted, PaperStatus.rejected, PaperStatus.revision_required],
        # Explicitly list available decisions
        is_decision_made = is_decision_made,  # Pass status flag
        is_locked = is_locked  # Pass lock control
    )


@organizer_bp.route("/final_decision/<int:conf_id>/<int:paper_id>", methods=["POST"])
@organizer_required
def final_decision(conf_id, paper_id):
    """
    Processes the Organizer's final decision (Accept/Reject/Revision) for a paper.
    Handles data extraction before deletion to prevent DetachedInstanceError.
    """

    # Load paper and essential relationships (Author and User details)
    paper = Paper.query.options(
        db.joinedload(Paper.author_role).joinedload(ConferenceRole.user)
    ).get_or_404(paper_id)

    conference = Conference.query.get_or_404(conf_id)

    final_recommendation_str = request.form.get("final_recommendation")

    if not final_recommendation_str or final_recommendation_str.strip() == '':
        flash("Final decision selection is required.", "error")
        return redirect(url_for('organizer.view_reviews', conf_id=conf_id, paper_id=paper_id))

    # --- INPUT PROCESSING AND MAPPING ---
    input_key = final_recommendation_str.lower().strip()

    # Mapping: Radio Button Value -> Target PaperStatus Enum string
    status_map = {
        'accepted': 'accepted',
        'rejected': 'rejected',
        'revision_required': 'revision_required',
        # Handles robustness for generic input strings
        'accept': 'accepted',
        'reject': 'rejected'
    }

    # Use the map to get the correct string key for PaperStatus
    final_status_string = status_map.get(input_key)
    # ----------------------------------

    try:
        if not final_status_string:
            # This catches if the radio button value did not match any expected key
            raise ValueError(f"Received invalid decision key: '{input_key}'.")

        # Convert the string to the official PaperStatus Enum member
        final_status = PaperStatus[final_status_string]
        author_role = paper.author_role

        # --- CRITICAL FIX: Extract required data for email BEFORE potential deletion ---
        author_email = author_role.user.email
        author_name = author_role.user.name
        paper_title = paper.title
        # -----------------------------------------------------------------------------

        # 1. Update Paper Status
        paper.status = final_status
        flash_message = f"Final decision set to {final_status.name.title().replace('_', ' ')}. Author notified."

        # 2. HANDLE REJECTION (Send email, then delete record)
        if final_status == PaperStatus.rejected:

            # Call the imported email function using the pre-fetched variables
            email_sent_success = send_rejection_email(author_email, author_name, paper_title, conference)

            db.session.delete(author_role)  # Delete the record (cascades to paper if necessary)

            if email_sent_success:
                flash_message = f"Final decision set to REJECTED. Author role and paper deleted. Notification sent."
            else:
                flash_message = f"Final decision set to REJECTED. WARNING: Email notification failed."

        db.session.commit()  # Commit status update or deletion

        flash(flash_message, "success")

    except Exception as e:
        db.session.rollback()
        # Log the detailed error for troubleshooting
        print(f"FINAL DECISION CRASH: {e}")
        flash(f"Database error occurred during final decision commit: {e}", "error")

    # Redirect back to the main paper list
    return redirect(url_for('organizer.manage_papers', conf_id=conf_id))

@organizer_bp.route("/download_camera_ready/<int:conf_id>/<int:paper_id>")
@organizer_required
def download_camera_ready(conf_id, paper_id):
    """Allows Organizer to download the final, camera-ready paper file."""

    paper = Paper.query.get_or_404(paper_id)

    # Security Check: Ensure the file exists and is associated with the conference
    if paper.conference_id != conf_id or not paper.camera_ready_file:
        flash("Camera-ready file not available or unauthorized access.", "error")
        return redirect(url_for('organizer.manage_papers', conf_id=conf_id))

    # Construct the file path (assumes 'camera_ready' is the storage folder)
    file_path = os.path.join(current_app.root_path, 'uploads', 'camera_ready', paper.camera_ready_file)

    if not os.path.exists(file_path):
        flash("Final file not found on server.", "error")
        return redirect(url_for('organizer.manage_papers', conf_id=conf_id))

    # Return the file for download
    return send_file(
        file_path,
        as_attachment=True,
        download_name=f"{paper.paper_id}_FINAL_{paper.title}.pdf"  # Use the final title
    )


# In organizer_routes.py (Add this function)
@organizer_bp.route("/remove_assignment/<int:conf_id>/<int:review_id>", methods=["POST"])
@organizer_required
def remove_assignment(conf_id, review_id):
    """Deletes a specific Review assignment record."""

    review_to_delete = Review.query.get_or_404(review_id)

    # Optional security check: ensure the paper is not fully reviewed/decided
    if review_to_delete.paper.status not in [PaperStatus.submitted, PaperStatus.under_review,
                                             PaperStatus.revision_required]:
        flash("Cannot remove assignment; paper decision is finalized.", "error")
        return redirect(url_for('organizer.manage_papers', conf_id=conf_id))

    try:
        db.session.delete(review_to_delete)
        db.session.commit()
        flash("Reviewer assignment removed successfully.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Database error: Could not remove assignment. {e}", "error")

    # Redirect back to the assignment view
    return redirect(url_for('organizer.assign_reviewers_view', conf_id=conf_id, paper_id=review_to_delete.paper_id))


@organizer_bp.route("/generate_pdf_preview/<int:conf_id>")
@organizer_required
def generate_pdf_preview(conf_id):
    """
    Generates the dynamic schedule PDF for the Organizer's review/download."""

    conference = Conference.query.get_or_404(conf_id)

    # 1. Fetch sessions with all necessary joins (similar to view_schedule_html)
    sessions = (
        Session.query
        .options(
            # Load Track and Session Chair details
            db.joinedload(Session.track),
            db.joinedload(Session.session_chair_role).joinedload(ConferenceRole.user),

            # CRITICAL: Load SessionPaper assignments
            db.joinedload(Session.papers_in_session)
            # Load the Paper record from the assignment
            .joinedload(SessionPaper.paper)
            # Load the Paper's Author Role
            .joinedload(Paper.author_role)
            # Load the Registration record linked to the Author Role (for payment status)
            .joinedload(ConferenceRole.registration_link)

        )
        .filter_by(conference_id=conf_id)
        .order_by(Session.schedule_time)
        .all()
    )
    if not sessions:
        flash("Cannot generate PDF: No sessions are defined.", "warning")
        return redirect(url_for('organizer.upload_schedule', conf_id=conf_id))

    sessions_by_date = {}
    for session in sessions:
        if session.schedule_time:  # make sure not None
            date_key = session.schedule_time.date()
            sessions_by_date.setdefault(date_key, []).append(session)

    # 2. Render HTML (Uses the private template intended for PDF conversion)
    html_content = render_template(
        "organiser/schedule_pdf.html",
        conference=conference,
        all_sessions=sessions,
        sessions_by_date=sessions_by_date
    )

    # 3. Generate PDF using the robust helper function
    try:
        pdf_data = generate_pdf_from_html(html_content)

        filename = f"{conference.title.replace(' ', '_')}_Draft_Schedule.pdf"

        # Return file for download
        return send_file(
            pdf_data,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        print(f"ORGANIZER PDF GENERATION ERROR: {e}")
        flash(f"Error generating PDF preview. Check for data integrity issues.", "error")
        return redirect(url_for('organizer.upload_schedule', conf_id=conf_id))


@organizer_bp.route("/manage_session_papers/<int:conf_id>", methods=["GET"])
@organizer_required
def manage_session_papers(conf_id):
    """
    Displays all sessions and a pool of accepted, paid papers for assignment.
    Implements Python-side date processing to stabilize Jinja groupby.
    """
    conference = Conference.query.get_or_404(conf_id)

    # 1. Fetch Sessions (eagerly load existing papers and track details)
    sessions = Session.query.options(
        db.joinedload(Session.track),
        db.joinedload(Session.papers_in_session).joinedload(SessionPaper.paper)
    ).filter_by(conference_id=conf_id).order_by(Session.schedule_time).all()

    # --- CRITICAL FIX 1: Add a stable date string attribute for Jinja grouping ---
    for session in sessions:
        if session.schedule_time:
            # Create a simple YYYY-MM-DD string key
            session.date_key = session.schedule_time.strftime('%Y-%m-%d')
        else:
            session.date_key = '9999-12-31'  # Sorts undated sessions to the end
    # -----------------------------------------------------------------------------

    # 2. Fetch the pool of AVAILABLE papers (Accepted and Paid)
    accepted_papers_pool = Paper.query.options(
        db.joinedload(Paper.author_role).joinedload(ConferenceRole.registration_link)
    ).filter(
        Paper.conference_id == conf_id,
        Paper.status == PaperStatus.accepted,
        # Ensure payment status is complete for final slot assignment
        Paper.author_role.has(
            ConferenceRole.registration_link.has(
                Registration.payment_status == PaymentStatus.completed
            )
        )
    ).all()

    # Filter out papers already assigned to ANY session
    assigned_paper_ids = {sp.paper_id for session in sessions for sp in session.papers_in_session}

    available_papers = [
        p for p in accepted_papers_pool if p.paper_id not in assigned_paper_ids
    ]

    return render_template(
        "organiser/manage_session_papers.html",
        conference=conference,
        sessions=sessions,
        available_papers=available_papers
    )
# In organizer_routes.py (Add this POST route)

@organizer_bp.route("/assign_session_post/<int:conf_id>", methods=["POST"])
@organizer_required
def assign_session_post(conf_id):
    """Handles creating a new SessionPaper record."""

    session_id = request.form.get("session_id")
    paper_id = request.form.get("paper_id")

    if not session_id or not paper_id:
        flash("Invalid session or paper selection.", "error")
        return redirect(url_for('organizer.manage_session_papers', conf_id=conf_id))

    # Fetch role of the author/presenter (required by SessionPaper)
    paper = Paper.query.get(paper_id)
    presenter_role_id = paper.author_role_id

    # Check if assignment already exists for this paper
    if SessionPaper.query.filter_by(paper_id=paper_id).first():
        flash("This paper is already assigned to a session.", "error")
        return redirect(url_for('organizer.manage_session_papers', conf_id=conf_id))

    # Create the new assignment
    new_assignment = SessionPaper(
        session_id=int(session_id),
        paper_id=int(paper_id),
        presenter_role_id=presenter_role_id,
        presentation_time=None  # Set this later if needed, or leave null
    )

    db.session.add(new_assignment)
    db.session.commit()

    flash(f"Paper ID {paper_id} assigned to Session {session_id} successfully!", "success")
    return redirect(url_for('organizer.manage_session_papers', conf_id=conf_id))


@organizer_bp.route("/upload_schedule/<int:conf_id>", methods=["GET", "POST"])
@organizer_required
def upload_schedule(conf_id):
    """Handles the Organizer uploading the final schedule PDF."""
    conference = Conference.query.get_or_404(conf_id)

    if request.method == "POST":
        schedule_file = request.files.get("schedule_file")

        if not schedule_file or schedule_file.filename == '':
            flash("No file selected for upload.", "error")
            return redirect(url_for('organizer.upload_schedule', conf_id=conf_id))

        if schedule_file.filename.split('.')[-1].lower() != 'pdf':
            flash("Invalid file format. Please upload a PDF file.", "error")
            return redirect(url_for('organizer.upload_schedule', conf_id=conf_id))

        # 1. Define File Upload Location
        UPLOAD_FOLDER = os.path.join(current_app.root_path, 'uploads', 'schedules')
        if not os.path.exists(UPLOAD_FOLDER):
            os.makedirs(UPLOAD_FOLDER)

        # 2. Secure Filename and Save
        filename = secure_filename(schedule_file.filename)
        unique_filename = f"schedule_{conf_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"

        try:
            save_path = os.path.join(UPLOAD_FOLDER, unique_filename)
            schedule_file.save(save_path)
        except Exception as e:
            flash(f"Error saving file: {e}", "error")
            return redirect(url_for('organizer.upload_schedule', conf_id=conf_id))

        # 3. Update Conference Record (Storing the file reference)
        conference.final_schedule_file = unique_filename
        db.session.commit()

        flash("Final schedule PDF uploaded successfully and is now live!", "success")
        return redirect(url_for('organizer.dashboard', conf_id=conf_id))

    # GET request: Render the upload form
    return render_template(
        "organiser/upload_schedule.html",
        conference=conference
    )