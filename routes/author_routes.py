from flask import Blueprint, render_template, redirect, flash, session, url_for, abort, request, current_app
from models import ConferenceRole, UserRole, Conference, Track, Paper, PaymentStatus, PaperStatus, Review,Registration # Added PaperStatus
from extensions import db
from functools import wraps
from datetime import datetime
from werkzeug.utils import secure_filename
from .auth_routes import login_required
import os  # Necessary for file paths

author_bp = Blueprint("author", __name__)


# --- DECORATOR for Approved Authors ---
# (This remains correct for protecting the Dashboard)
def author_required(f):
    """Decorator to ensure user is a logged-in, APPROVED author."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access this page.", "error")
            return redirect(url_for("auth.login"))

        conference_id = kwargs.get("conf_id")
        if not conference_id:
            abort(400)

        is_approved_author = ConferenceRole.query.filter_by(
            user_id=session["user_id"],
            conference_id=conference_id,
            role=UserRole.author,
            status=1  # Must be APPROVED
        ).first()

        if not is_approved_author:
            flash("You do not have approved author privileges for this conference.", "error")
            return redirect(url_for("auth.dashboard"))

        return f(*args, **kwargs)

    return decorated_function


# --- AUTHOR ROUTES GO HERE ---
@author_bp.route("/dashboard/author/<int:conf_id>")
@author_required
def dashboard(conf_id):
    """The main hub showing submission status and actions."""
    user_id = session['user_id']

    # 1. Fetch the Conference object (CRITICAL FIX)
    conference = Conference.query.get_or_404(conf_id)

    # 2. Fetch the Author Role
    author_role = ConferenceRole.query.filter_by(
        user_id=user_id,
        conference_id=conf_id,
        role=UserRole.author,
    ).first_or_404()  # Should exist due to @author_required

    # 3. Fetch the associated Paper (if any)
    paper = Paper.query.options(
        db.joinedload(Paper.track)
    ).filter_by(
        author_role_id=author_role.id
    ).first()

    # 4. Render the template
    return render_template(
        "author/dashboard_author.html",
        conference=conference,  # <--- PASS THE CONFERENCE OBJECT
        author_role=author_role,
        paper=paper
    )


@author_bp.route("/submit_paper/<int:conf_id>", methods=["GET", "POST"])
@login_required  # Only requires user to be logged in
def submit_paper(conf_id):
    """
    Handles the merged submission process: Abstract, Track, and Blind File Upload
    all in one step. Sets Author status directly to APPROVED (status=1).
    """
    user_id = session['user_id']
    conference = Conference.query.get_or_404(conf_id)

    # 1. Check if user is already an author and has submitted a paper (prevents duplicates)
    existing_role = ConferenceRole.query.filter_by(
        user_id=user_id, conference_id=conf_id, role=UserRole.author
    ).first()

    if existing_role and Paper.query.filter_by(author_role_id=existing_role.id).first():
        flash("You have already submitted a paper. Manage its status via your dashboard.", "info")
        return redirect(url_for('author.dashboard', conf_id=conf_id))

    # Fetch available Tracks for the GET request form
    tracks = Track.query.filter_by(conference_id=conf_id).order_by(Track.name).all()

    if request.method == 'POST':
        # --- 2. POST PROCESSING (Submission and File Handling) ---
        title = request.form.get("title")
        abstract = request.form.get("abstract")
        keywords = request.form.get("keywords")
        track_id = request.form.get("track_id")
        blind_copy_file = request.files.get("blind_copy")

        # Validation: All fields + file are required
        if not all([title, abstract, keywords, track_id, blind_copy_file and blind_copy_file.filename]):
            flash("Please ensure all fields and the blind copy PDF file are provided.", "error")
            return redirect(url_for('author.submit_paper', conf_id=conf_id))

        # 3. Handle File Upload
        UPLOAD_FOLDER = os.path.join(current_app.root_path, 'uploads', 'blind_papers')
        if not os.path.exists(UPLOAD_FOLDER):
            os.makedirs(UPLOAD_FOLDER)

        filename = secure_filename(blind_copy_file.filename)
        # Create a unique filename
        unique_filename = f"paper_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"

        try:
            # Save the file
            save_path = os.path.join(UPLOAD_FOLDER, unique_filename)
            blind_copy_file.save(save_path)
        except Exception as e:
            flash(f"Error saving file: {e}", "error")
            return redirect(url_for('author.submit_paper', conf_id=conf_id))

        # 4. Create/Update Author Role (CRITICAL: SET STATUS = 1)
        if not existing_role:
            author_role = ConferenceRole(
                user_id=user_id,
                conference_id=conf_id,
                role=UserRole.author,
                status=1  # DIRECTLY APPROVED for dashboard access
            )
            db.session.add(author_role)
        else:
            author_role = existing_role
            author_role.status = 1

            # 5. Create the Paper Record
        new_paper = Paper(
            author_role_id=author_role.id,
            conference_id=conf_id,
            track_id=int(track_id),
            title=title,
            abstract=abstract,
            keywords=keywords,
            blind_paper_file=unique_filename,
            status=PaperStatus.submitted
        )
        db.session.add(new_paper)
        db.session.commit()

        # 6. Correct Redirection
        flash("Paper submitted successfully! You now have full access to your Author Dashboard.", "success")
        return redirect(url_for('author.dashboard', conf_id=conf_id))

    # 7. GET request: Render the form
    return render_template(
        "author/submission_form.html",  # Template file name
        conference=conference,
        tracks=tracks
    )


# In author_routes.py (Add this route)

@author_required
@author_bp.route("/view_submission/<int:conf_id>")
def view_submission(conf_id):
    """
    Displays the detailed status, decision, and communication options for the author's submitted paper.
    """
    user_id = session['user_id']
    conference = Conference.query.get_or_404(conf_id)


    # 1. Fetch the Author Role
    author_role = ConferenceRole.query.filter_by(
        user_id=user_id,
        conference_id=conf_id,
        role=UserRole.author,
    ).first_or_404()

    # 2. Fetch the associated Paper
    paper = Paper.query.options(
        db.joinedload(Paper.track),
        db.joinedload(Paper.reviews)  # Load the reviews relationship
        .joinedload(Review.reviewer_role)  # Load the reviewer's role info
        .joinedload(ConferenceRole.user)  # Load the user's name
    ).filter_by(
        author_role_id=author_role.id
    ).first_or_404()

    author_role = paper.author_role
    is_author_registered = Registration.query.filter_by(role_id=author_role.id,
                                                        payment_status=PaymentStatus.completed).first() is not None

    # NOTE: You will implement a dedicated template later.
    return render_template(
        "author/view_submission.html",
        conference=conference,
        paper=paper,
        is_author_registered = is_author_registered
    )


@author_bp.route("/upload_camera_ready/<int:conf_id>/<int:paper_id>", methods=["POST"])
@author_required
def upload_camera_ready(conf_id, paper_id):
    """Handles the POST submission of the final camera-ready copy."""

    paper = Paper.query.get_or_404(paper_id)
    camera_ready_file = request.files.get("camera_ready_file")

    # 1. Security and Status Check
    # Ensure paper is accepted/revision_required before uploading camera-ready copy
    if paper.conference_id != conf_id or paper.status not in [PaperStatus.accepted, PaperStatus.revision_required]:
        flash("File upload denied. Paper status does not allow camera-ready submission.", "error")
        return redirect(url_for('author.view_submission', conf_id=conf_id))

    if not camera_ready_file or camera_ready_file.filename == '':
        flash("Camera-ready file is required.", "error")
        return redirect(url_for('author.view_submission', conf_id=conf_id, paper_id=paper_id))

    # 2. Handle File Upload
    UPLOAD_FOLDER = os.path.join(current_app.root_path, 'uploads', 'camera_ready')
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

    user_id = session['user_id']
    filename = secure_filename(camera_ready_file.filename)
    unique_filename = f"camera_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"

    try:
        # Save the file
        save_path = os.path.join(UPLOAD_FOLDER, unique_filename)
        camera_ready_file.save(save_path)
    except Exception as e:
        flash(f"Error saving file: {e}", "error")
        return redirect(url_for('author.view_submission', conf_id=conf_id, paper_id=paper_id))

    # 3. Update Paper Record
    paper.camera_ready_file = unique_filename

    # Update status to accepted if it was revision required
    if paper.status == PaperStatus.revision_required:
        paper.status = PaperStatus.accepted

    db.session.commit()

    flash("Camera-ready copy successfully uploaded!", "success")
    return redirect(url_for('author.view_submission', conf_id=conf_id, paper_id=paper_id))


@author_bp.route("/process_payment/<int:conf_id>/<int:paper_id>", methods=["POST"])
@author_required
def process_author_payment(conf_id, paper_id):
    """
    Handles the POST request for author fee payment, confirms registration,
    and flashes the crucial Paper ID.
    """

    paper = Paper.query.get_or_404(paper_id)

    # NOTE: Conference object must be fetched to access fee amount
    conference = Conference.query.get_or_404(conf_id)

    # 1. Validation: Ensure paper is accepted and authorized
    if paper.conference_id != conf_id or paper.status != PaperStatus.accepted:
        flash("Payment rejected: Paper must be officially accepted for author registration.", "error")
        return redirect(url_for('author.view_submission', conf_id=conf_id, paper_id=paper_id))

    # 2. Check for existing registration record
    author_role = paper.author_role
    if Registration.query.filter_by(role_id=author_role.id).first():
        flash("Author registration already finalized.", "warning")
        return redirect(url_for('author.view_submission', conf_id=conf_id, paper_id=paper_id))

    # 3. Simulate Successful Payment (Setting status to COMPLETED)

    new_registration = Registration(
        role_link=author_role,
        conference_id=conf_id,
        fee_amount=conference.author_fee,  # Use the conference fee defined by the organizer
        payment_status=PaymentStatus.completed
    )
    db.session.add(new_registration)
    db.session.commit()

    # --- CRITICAL ACTION: Include Paper ID in the success message ---
    flash(
        f"Author registration and payment confirmed! Paper ID **{paper.paper_id}** ({paper.title}) is secured in the program. You are officially registered.",
        "success")
    # -------------------------------------------------------------

    return redirect(url_for('author.view_submission', conf_id=conf_id, paper_id=paper_id))


@author_bp.route("/upload_revised_blind_copy/<int:conf_id>/<int:paper_id>", methods=["POST"])
@author_required
def upload_revised_blind_copy(conf_id, paper_id):
    """
    Handles the POST submission of a revised blind copy when the status is 'revision_required'.
    This overwrites the original blind file.
    """
    paper = Paper.query.get_or_404(paper_id)
    revised_file = request.files.get("revised_blind_file")

    # 1. Security and Status Check
    if paper.conference_id != conf_id or paper.status != PaperStatus.revision_required:
        flash("File upload denied. Only allowed for papers marked 'Revision Required'.", "error")
        return redirect(url_for('author.view_submission', conf_id=conf_id, paper_id=paper_id))

    if not revised_file or revised_file.filename == '':
        flash("Revised blind copy file is required.", "error")
        return redirect(url_for('author.view_submission', conf_id=conf_id, paper_id=paper_id))

    # 2. Handle File Upload (Save to the original blind_papers folder)
    UPLOAD_FOLDER = os.path.join(current_app.root_path, 'uploads', 'blind_papers')
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

    user_id = session['user_id']
    filename = secure_filename(revised_file.filename)

    # Generate a unique filename, preserving the blind nature
    unique_filename = f"revised_blind_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"

    try:
        # Save the new file, overwriting the reference in the paper table
        save_path = os.path.join(UPLOAD_FOLDER, unique_filename)
        revised_file.save(save_path)
    except Exception as e:
        flash(f"Error saving file: {e}", "error")
        return redirect(url_for('author.view_submission', conf_id=conf_id, paper_id=paper_id))

    # 3. Update Paper Record
    # CRITICAL: Overwrite the old blind file name and set status to signal re-review readiness
    paper.blind_paper_file = unique_filename
    paper.status = PaperStatus.under_review  # Signal that it's back for review/organizer check

    db.session.commit()

    flash("Revised blind copy submitted successfully! Status set to Under Review.", "success")
    return redirect(url_for('author.view_submission', conf_id=conf_id, paper_id=paper_id))