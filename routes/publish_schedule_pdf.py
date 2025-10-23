from flask import Blueprint, render_template, redirect, flash, send_file, url_for
from datetime import datetime
from extensions import db
from models import Conference, Session, ConferenceRole, Track,SessionPaper,Session,Paper # All necessary imports
from xhtml2pdf import pisa
import io
import os
import tempfile

# Define the new Blueprint for public/general conference actions
schedule_bp = Blueprint("schedule", __name__)

def generate_pdf_from_html(html_content):
    pdf_output = io.BytesIO()
    cwd_backup = os.getcwd()

    try:
        temp_dir = tempfile.gettempdir()
        os.chdir(temp_dir)

        pisa_status = pisa.CreatePDF(
            html_content.encode("utf-8", "ignore"),
            dest=pdf_output
        )

        if pisa_status.err:
            raise Exception(f"PDF conversion failed (pisa code {pisa_status.err}).")

        pdf_output.seek(0)
        return pdf_output

    finally:
        os.chdir(cwd_backup)


# =================================================================
# --- PUBLIC SCHEDULE ROUTES ---
# =================================================================


@schedule_bp.route("/conference/<int:conf_id>/schedule_pdf")
def get_public_schedule_pdf(conf_id):
    """
    ROUTE 1: Generates the dynamic PDF schedule using xhtml2pdf (used for downloading a draft).
    """
    try:
        conference = Conference.query.get_or_404(conf_id)

        # 1. Fetch sessions with full data joins
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
            flash("Cannot generate PDF: No sessions are defined.", "info")
            return redirect(url_for("conference.explore_more", conf_id=conf_id))

        sessions_by_date = {}
        for session in sessions:
            if session.schedule_time:  # make sure not None
                date_key = session.schedule_time.date()
                sessions_by_date.setdefault(date_key, []).append(session)

        # 2. Render HTML
        html_content = render_template(
            "organiser/schedule_pdf.html", # Template designed for print layout
            conference=conference,
            all_sessions=sessions,
            sessions_by_date=sessions_by_date
        )

        # 3. Generate PDF
        pdf_data = generate_pdf_from_html(html_content)
        filename = f"{conference.title.replace(' ', '_')}_Program_Schedule.pdf"

        return send_file(
            pdf_data,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename
        )

    except Exception as e:
        print(f"PUBLIC PDF GENERATION ERROR: {e}")
        flash(f"Error generating PDF draft: {e}. Try again later.", "error")
        return redirect(url_for("conference.explore_more", conf_id=conf_id))


@schedule_bp.route("/conference/<int:conf_id>/schedule_view")
def view_schedule_html(conf_id):
    """
    ROUTE 2: Public route to view the dynamic program schedule in HTML format.
    """
    try:
        conference = Conference.query.get_or_404(conf_id)

        # Fetch sessions with all necessary joins
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
            flash("No sessions have been scheduled yet.", "info")
            return redirect(url_for("conference.explore_more", conf_id=conf_id))

        sessions_by_date = {}
        for session in sessions:
            if session.schedule_time:  # make sure not None
                date_key = session.schedule_time.date()
                sessions_by_date.setdefault(date_key, []).append(session)



        # Render the HTML template (NOTE: Template path might need adjustment)
        return render_template(
            "organiser/schedule_view.html",
            conference=conference,
            all_sessions=sessions,
            sessions_by_date = sessions_by_date
        )

    except Exception as e:
        print(f"HTML SCHEDULE VIEW ERROR: {e}")
        flash(f"Error fetching schedule: {e}.", "error")
        return redirect(url_for("conference.explore_more", conf_id=conf_id))