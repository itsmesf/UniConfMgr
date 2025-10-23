
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
# ADD these imports for password hashing and checking
from werkzeug.security import generate_password_hash, check_password_hash
from models import User
from extensions import db
from .auth_routes import login_required

profile_bp = Blueprint("profile", __name__)


@profile_bp.route("/profile", methods=["GET", "POST"])
@login_required
def view_profile():
    """Handles viewing and updating the user's profile information."""
    user = User.query.get_or_404(session["user_id"])

    if request.method == "POST":
        # This part remains the same - it only handles general info
        user.name = request.form.get("name")
        user.university_name = request.form.get("university_name")
        user.department = request.form.get("department")
        user.contact_no = request.form.get("contact_no")

        db.session.commit()
        flash("Your profile has been updated successfully!", "success")
        return redirect(url_for("profile.view_profile"))

    return render_template("view_profile.html", user=user)


# --- NEW: Route for changing the password ---
@profile_bp.route("/profile/change-password", methods=["POST"])
@login_required
def change_password():
    """Handles the password change logic."""
    user = User.query.get_or_404(session["user_id"])

    current_password = request.form.get("current_password")
    new_password = request.form.get("new_password")
    confirm_password = request.form.get("confirm_password")

    # 1. Verify the current password
    if not check_password_hash(user.password_hash, current_password):
        flash("Your current password is incorrect. Please try again.", "error")
        return redirect(url_for("profile.view_profile"))

    # 2. Check if the new password is not empty
    if not new_password:
        flash("New password cannot be empty.", "error")
        return redirect(url_for("profile.view_profile"))

    # 3. Check if the new passwords match
    if new_password != confirm_password:
        flash("The new passwords do not match. Please try again.", "error")
        return redirect(url_for("profile.view_profile"))

    # 4. Hash the new password and update the user
    user.password_hash = generate_password_hash(new_password)
    db.session.commit()

    flash("Your password has been changed successfully!", "success")
    return redirect(url_for("profile.view_profile"))