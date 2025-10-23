from flask import Blueprint, render_template
from models import Conference, ConferenceRole,Track, User,UserRole
from datetime import date
from extensions import db

conference_bp = Blueprint("conference", __name__)


@conference_bp.route("/explore_conferences")
def explore_conferences():
    """
    Public route to display all conferences, categorized by status,
    extracting filter data (University/Department) directly from the Conference model.
    """
    today = date.today()

    # 1. Fetch all Conferences (No joins needed for filter data)
    all_conferences = Conference.query.order_by(Conference.start_date).all()

    # --- 2. Extract unique filter names DIRECTLY from the Conference objects ---
    unique_universities = set()
    unique_departments = set()

    categorized_conferences = {
        "upcoming": [],
        "ongoing": [],
        "past": []
    }

    for conf in all_conferences:
        status = conf.status

        # Extract names from the NEW Conference columns
        if conf.hosting_university:
            unique_universities.add(conf.hosting_university)
        if conf.hosting_department:
            unique_departments.add(conf.hosting_department)

        if status == "upcoming":
            categorized_conferences["upcoming"].append(conf)
        elif status == "ongoing":
            categorized_conferences["ongoing"].append(conf)
        else:
            categorized_conferences["past"].append(conf)

    # 3. Convert sets to sorted lists for Jinja dropdowns
    university_names = sorted(list(unique_universities))
    department_names = sorted(list(unique_departments))

    return render_template(
        "conference/explore_conferences.html",
        conferences=categorized_conferences,
        # Pass the refined filter lists
        university_names=university_names,
        department_names=department_names
    )


@conference_bp.route("/conference/<int:conf_id>")
def explore_more(conf_id):
    """
    Show detailed information about a specific conference, including tracks and fees.
    """
    # 1. Fetch the Conference object
    # Eagerly load the main organizer role and user for the template display
    conf = Conference.query.options(
        db.joinedload(Conference.roles).joinedload(ConferenceRole.user)
    ).get_or_404(conf_id)

    # 2. Fetch all Tracks related to this conference
    tracks = Track.query.filter_by(conference_id=conf_id).order_by(Track.name).all()

    # 3. Handle Organizer Name (The template uses conference.main_organizer)
    # The 'main_organizer' property on your Conference model should handle finding the approved organizer.
    # If it is slow, you could calculate it here.

    return render_template(
        "conference/explore_more.html",
        conference=conf,  # Now includes the organizer data
        tracks=tracks     # <--- CRITICAL: Pass the tracks list to the template
    )