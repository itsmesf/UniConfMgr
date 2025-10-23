from flask import Blueprint, render_template, redirect, flash, session, url_for, abort, request, send_file, current_app
from models import ConferenceRole, UserRole, Conference,Track,Review,Paper,ReviewRecommendation# Import necessary models
from functools import wraps
from datetime import datetime
from extensions import db
import os
from flask import current_app
reviewer_bp = Blueprint("reviewer", __name__) # Define the Blueprint

# --- DECORATOR for Approved Reviewers ---
def reviewer_required(f):
    """Decorator to ensure user is a logged-in, APPROVED reviewer."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access this page.", "error")
            return redirect(url_for("auth.login"))

        conference_id = kwargs.get("conf_id")
        if not conference_id:
            abort(400)

        # Check if the user has an approved reviewer role for this conference
        is_approved_reviewer = ConferenceRole.query.filter_by(
            user_id=session["user_id"],
            conference_id=conference_id,
            role=UserRole.reviewer,
            status=1 # Must be an APPROVED reviewer
        ).first()

        if not is_approved_reviewer:
            flash("You do not have approved reviewer privileges for this conference.", "error")
            return redirect(url_for("auth.dashboard"))

        return f(*args, **kwargs)
    return decorated_function

# --- REVIEWER ROUTES GO HERE ---

@reviewer_bp.route("/dashboard/reviewer/<int:conf_id>")
@reviewer_required
def dashboard(conf_id):
    """The main dashboard for an approved reviewer, showing assigned papers."""

    # 1. Fetch conference object (CRITICAL FIX for UndefinedError)
    conference = Conference.query.get_or_404(conf_id)

    # 2. Get the reviewer's ConferenceRole ID
    reviewer_role = ConferenceRole.query.filter_by(
        user_id=session["user_id"],
        conference_id=conf_id,
        role=UserRole.reviewer,
        status=1
    ).first()

    if not reviewer_role:
        # Should be caught by the decorator, but good practice to handle.
        flash("Reviewer role not found for this conference.", "error")
        return redirect(url_for("auth.dashboard"))

    # 3. Fetch all Review records linked to this reviewer's role ID
    # Eagerly load the Paper, Author, and Track for template display efficiency
    assigned_reviews = Review.query.options(
        db.joinedload(Review.paper)
        .joinedload(Paper.author_role)
        .joinedload(ConferenceRole.user),
        db.joinedload(Review.paper).joinedload(Paper.track)
    ).filter_by(
        reviewer_role_id=reviewer_role.id
    ).all()

    # 4. Render the template, passing all required objects
    return render_template(
        "reviewer/dashboard_reviewer.html",
        conference=conference,  # <--- FIX: Passing the conference object
        assigned_reviews=assigned_reviews,
        reviewer_role=reviewer_role
    )

@reviewer_bp.route("/apply_registration/<int:conf_id>", methods=["GET", "POST"])
def apply_registration(conf_id):
    """
    Displays the form for a user to select expertise and officially apply as a reviewer.
    This route is accessible to logged-in users who do NOT yet have an approved reviewer role.
    """
    if "user_id" not in session:
        flash("Please log in to apply for the reviewer role.", "error")
        return redirect(url_for("auth.login"))

    # Fetch conference and current user's role status
    conference = Conference.query.get_or_404(conf_id)
    user_id = session['user_id']

    # Check if user is already an approved reviewer (redirect them if so)
    existing_role = ConferenceRole.query.filter_by(
        user_id=user_id,
        conference_id=conf_id,
        role=UserRole.reviewer
    ).first()

    if existing_role and existing_role.status == 1:
        flash("You are already an approved reviewer.", "info")
        return redirect(url_for('reviewer.dashboard', conf_id=conf_id))

    # Fetch available Tracks for the form
    tracks = Track.query.filter_by(conference_id=conf_id).order_by(Track.name).all()

    if request.method == 'POST':
        # --- SUBMISSION LOGIC ---
        selected_track_ids = request.form.getlist("expertise_tracks")
        expertise_notes = request.form.get("expertise_notes")

        if not selected_track_ids:
            flash("Please select at least one track that matches your expertise.", "error")
            return redirect(url_for('reviewer.apply_registration', conf_id=conf_id))

        # Store expertise as a comma-separated string of Track IDs
        expertise_string = ",".join(selected_track_ids)

        # Create or update the ConferenceRole record
        if not existing_role:
            existing_role = ConferenceRole(
                user_id=user_id,
                conference_id=conf_id,
                role=UserRole.reviewer
            )

        existing_role.expertise = expertise_string
        existing_role.status = 0  # Status: Pending Approval by Organizer
        db.session.add(existing_role)
        db.session.commit()

        flash("Reviewer application submitted successfully! Awaiting organizer approval.", "success")
        return redirect(url_for('auth.dashboard'))  # Redirect to user's general hub

    # GET request: Render the form
    return render_template(
        "reviewer/reviewer_register.html",  # <--- New template path
        conference=conference,
        tracks=tracks
    )

@reviewer_bp.route("/review_form/<int:conf_id>/<int:review_id>", methods=["GET", "POST"])
@reviewer_required
def view_review_form(conf_id, review_id):
    """
    Displays the review form (GET) or processes the review submission (POST).
    """
    # 1. Fetch the Review assignment and associated Paper
    review_assignment = Review.query.options(
        db.joinedload(Review.paper).joinedload(Paper.track),
        db.joinedload(Review.reviewer_role)
    ).get_or_404(review_id)

    # 2. Get the Reviewer's specific ConferenceRole ID
    reviewer_role = ConferenceRole.query.filter_by(
        user_id=session["user_id"],
        conference_id=conf_id,
        status=1
    ).first_or_404()

    # 3. CRITICAL AUTHORIZATION CHECK: Ensure this assignment belongs to the logged-in user
    if review_assignment.reviewer_role_id != reviewer_role.id:
        flash("You are not authorized to access this review assignment.", "error")
        return redirect(url_for('reviewer.dashboard', conf_id=conf_id))

    # --- HANDLE POST SUBMISSION (Used for both initial submission and updates) ---
    if request.method == "POST":
        comments_to_author = request.form.get("comments_to_author")
        comments_to_organiser = request.form.get("comments_to_organiser")
        score = request.form.get("score")
        recommendation_str = request.form.get("recommendation")

        if not comments_to_author or not score or not recommendation_str:
            flash("Please fill in all required fields (comments, score, and recommendation).", "error")
            return redirect(url_for('reviewer.view_review_form', conf_id=conf_id, review_id=review_id))

        try:
            review_assignment.comments_to_author = comments_to_author
            review_assignment.comments_to_organiser = comments_to_organiser
            review_assignment.score = int(score)
            review_assignment.recommendation = ReviewRecommendation[recommendation_str]
            review_assignment.created_at = datetime.now()

            db.session.commit()
            flash("Review successfully submitted/updated! Thank you.", "success")
            return redirect(url_for('reviewer.dashboard', conf_id=conf_id))

        except (ValueError, KeyError) as e:
            flash(f"Submission Error: Invalid score or recommendation value. {e}", "error")
            db.session.rollback()
            return redirect(url_for('reviewer.view_review_form', conf_id=conf_id, review_id=review_id))

    # --- HANDLE GET REQUEST ---
    edit_mode = request.args.get('edit', 'false') == 'true'

    is_completed = bool(review_assignment.recommendation)
    is_locked = is_completed and not edit_mode

    return render_template(
        "reviewer/review_form.html",
        conference_id=conf_id,
        review_assignment=review_assignment,
        recommendations=ReviewRecommendation,
        is_completed=is_completed,
        is_locked = is_locked
    )
@reviewer_bp.route("/download_paper/reviewer/<int:conf_id>/<int:paper_id>")
@reviewer_required
def download_paper(conf_id, paper_id):  # <-- Accept paper_id
    """Allows an approved reviewer to download the blind paper file."""

    paper = Paper.query.get_or_404(paper_id)

    # CRITICAL SECURITY CHECK: Ensure the paper is assigned to the logged-in reviewer.
    # We must check that a Review record exists for this paper and user.
    reviewer_role = ConferenceRole.query.filter_by(
        user_id=session["user_id"], conference_id=conf_id
    ).first()

    # Verify that an active assignment exists for this paper and reviewer
    assignment_exists = Review.query.filter_by(
        paper_id=paper_id,
        reviewer_role_id=reviewer_role.id
    ).first()

    if not assignment_exists:
        # If not assigned, they shouldn't download it.
        flash("You are not assigned to review this paper.", "error")
        # Since we don't have review_id, redirect to the dashboard
        return redirect(url_for('reviewer.dashboard', conf_id=conf_id))

        # Security checks passed, proceed with file path construction...

    file_path = os.path.join(current_app.root_path, 'uploads', 'blind_papers', paper.blind_paper_file)

    if not os.path.exists(file_path):
        flash("File not found on server. Contact the organizer.", "error")
        # Redirect to the dashboard, as we don't know the review_id here
        return redirect(url_for('reviewer.dashboard', conf_id=conf_id))

    return send_file(
        file_path,
        as_attachment=True,
        download_name=f"blind_paper_{paper.paper_id}_{paper.track.name[:10]}.pdf"
    )