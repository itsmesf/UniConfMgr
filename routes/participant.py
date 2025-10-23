from flask import Blueprint, flash, redirect, url_for, render_template, session
from sqlalchemy.orm import joinedload
from datetime import datetime
from models import Conference, ConferenceRole, UserRole, Certificate, CertificateType, Registration, PaymentStatus
from extensions import db
from .auth_routes import login_required  # Assumes login_required is in auth_routes.py

# --- DEFINE BLUEPRINT ---
participant_bp = Blueprint("participant", __name__)  # Endpoint name will be 'participant.function_name'


# --- PARTICIPANT DASHBOARD ROUTE ---

@participant_bp.route("/dashboard/participant/<int:conf_id>")
@login_required
def participant_dashboard(conf_id):
    """
    Displays the participant's dashboard for a specific conference.
    Only allows access if the user is an APPROVED participant.
    """
    user_id = session["user_id"]

    # 1. Verify User is an APPROVED Participant for this conference
    participant_role = ConferenceRole.query.filter_by(
        user_id=user_id,
        conference_id=conf_id,
        role=UserRole.participant,
        status=1  # Must be approved (paid)
    ).first()

    if not participant_role:
        flash("Access denied. You are not a confirmed participant for this event.", "error")
        # Redirect to the main user dashboard if access is denied
        return redirect(url_for("auth.dashboard"))

    conference = Conference.query.get_or_404(conf_id)

    # 2. Check for Certificate existence (for display purposes)
    certificate = Certificate.query.filter_by(
        role_id=participant_role.id,
        certificate_type=CertificateType.participant
    ).first()

    # 3. Check Payment Status (for display purposes)
    registration_record = Registration.query.filter_by(
        role_id=participant_role.id
    ).first()

    # Calculate is_paid status safely
    is_paid_status = (registration_record.payment_status == PaymentStatus.completed) if registration_record else False

    return render_template(
        "participant/dashboard_participant.html",  # <-- CORRECTED TEMPLATE PATH
        conference=conference,
        role=participant_role,
        certificate=certificate,
        is_paid=is_paid_status
    )