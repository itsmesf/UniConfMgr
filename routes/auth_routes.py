from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from werkzeug.security import check_password_hash, generate_password_hash
from models import User,ConferenceRole,Conference # UserRole enum is no longer needed here for auth logic
from extensions import db
from functools import wraps
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Email, Mail
import os
TOKEN_EXPIRATION_SEC = 1800


auth_bp = Blueprint("auth", __name__)


# --- DECORATORS (UPDATED) ---

def login_required(f):
    """Decorator to ensure the user is logged in."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access this page.", "error")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    """Decorator to ensure the user is an admin or super admin."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access this page.", "error")
            return redirect(url_for("auth.login"))

        # Check admin status from the session for efficiency
        if not session.get("is_admin") and not session.get("is_super_admin"):
            flash("You do not have administrative privileges for this page.", "error")
            return redirect(url_for("auth.dashboard"))  # Redirect to their main dashboard
        return f(*args, **kwargs)

    return decorated_function


def super_admin_required(f):
    """Decorator to ensure the user is a super admin."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access this page.", "error")
            return redirect(url_for("auth.login"))

        if not session.get("is_super_admin"):
            flash("You do not have permission to access this page.", "error")
            return redirect(url_for("auth.dashboard"))
        return f(*args, **kwargs)

    return decorated_function


# --- SUPER ADMIN ROUTES (UPDATED) ---

@auth_bp.route("/dashboard_super_admin/add_admin", methods=["GET", "POST"])
@super_admin_required
def add_admin():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")

        if User.query.filter_by(email=email).first():
            flash("Email is already registered.", "error")
            return redirect(url_for("auth.add_admin"))

        hashed_password = generate_password_hash(password)

        new_admin = User(
            name=name,
            email=email,
            password_hash=hashed_password,
            is_admin=True,
            is_email_verified=True
        )
        db.session.add(new_admin)
        db.session.commit()

        # --- SEND THE WELCOME EMAIL ---
        try:
            # 1. Prepare the email content and recipient

            # Get the HTML content from the Jinja template
            html_content = render_template(
                'emails/new_admin_welcome.html',
                name=name,
                email=email,
                password=password
            )

            # NOTE: The sender email must be verified in your SendGrid account!
            sender_email = current_app.config['MAIL_USERNAME']  # This should be the verified SendGrid address

            # 2. Build the SendGrid Message object
            message = Mail(
                from_email=Email(sender_email, "Conference Manager"),  # Correct way
                to_emails=email,
                subject='Your Admin Account has been Created!',
                html_content=html_content
            )

            # 3. Send the message using the API key
            sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            response = sg.send(message)

            # Optional: Log success based on API response code (202 is accepted)
            if response.status_code == 202:
                flash("Admin created successfully and a welcome email has been sent!", "success")
            else:
                # SendGrid accepted the request but returned an unexpected status code
                flash(f"Admin created, but SendGrid returned status {response.status_code}. Email may not have sent.",
                      "warning")

        except Exception as e:
            # This catches API connection errors, authentication errors, etc.
            print(f"SendGrid Error: {e}")
            flash(f"Admin created, but failed to send email. Error: {e}", "warning")

        return redirect(url_for("auth.view_admins"))

    return render_template("superAdmin/add_admin.html")


@auth_bp.route("/dashboard_super_admin/view_admins")
@super_admin_required
def view_admins():
    # UPDATED: Query using the 'is_admin' flag.
    admins = User.query.filter_by(is_admin=True, is_super_admin=False).all()
    return render_template("superAdmin/view_admins.html", admins=admins)


@auth_bp.route("/dashboard_super_admin/admins/delete/<int:user_id>", methods=["POST"])
@super_admin_required
def delete_admin(user_id):
    admin_to_delete = User.query.get_or_404(user_id)
    # UPDATED: Check using the 'is_admin' flag.
    if admin_to_delete.is_admin and not admin_to_delete.is_super_admin:
        db.session.delete(admin_to_delete)
        db.session.commit()
        flash("Admin deleted successfully!", "success")
    else:
        flash("User is not an admin or cannot be deleted.", "error")
    return redirect(url_for("auth.view_admins"))


# --- GENERAL AUTH ROUTES (UPDATED) ---

@auth_bp.route("/")
def index():
    return render_template("index.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        user = User.query.filter_by(email=email).first()

        # 1. Check for Invalid Credentials
        if not user or not check_password_hash(user.password_hash, password):
            flash("Invalid email or password.", "error")
            return redirect(url_for("auth.login"))

        # 2. CRITICAL FIX: Check Email Verification Status
        if not user.is_email_verified:
            # Note: You should create an 'auth.resend_verification' route
            # to handle resending the token.
            flash("Please verify your email address before logging in.", "warning")
            return redirect(url_for('auth.login'))
            # Alternatively: return redirect(url_for('auth.resend_verification'))

        # 3. Successful Login: Set Session Variables
        session["user_id"] = user.user_id
        session["user_name"] = user.name
        session["is_super_admin"] = user.is_super_admin
        session["is_admin"] = user.is_admin

        flash(f"Welcome back, {user.name}!", "success")
        return redirect(url_for("auth.dashboard"))

    return render_template("login.html")

@auth_bp.route("/logout")
@login_required
def logout():
    session.clear()
    flash("You have been successfully logged out.", "info")
    return redirect(url_for("auth.login"))


# --- DASHBOARD ROUTER (UPDATED) ---

@auth_bp.route("/dashboard")

@login_required
def dashboard():
    user_name = session.get("user_name")

    # Handle super admin
    if session.get("is_super_admin"):
        return render_template("superAdmin/dashboard_super_admin.html", user_name=user_name)

    # Handle regular admin
    if session.get("is_admin"):
        return render_template("admin/dashboard_admin.html", user_name=user_name)

    # For all other users, fetch their specific roles for the hub dashboard
    user_roles = ConferenceRole.query.filter_by(user_id=session['user_id']).all()
    return render_template("dashboard.html", user_name=user_name, roles=user_roles)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Handles new user registration and sends an email verification link."""
    if request.method == "POST":
        # 1. Get user details from the form
        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")

        university = request.form.get("university_name")
        department = request.form.get("department")
        contact_no = request.form.get("contact_no")

        # 2. Check if a user with that email already exists
        if User.query.filter_by(email=email).first():
            flash("An account with this email address already exists. Please log in.", "warning")
            return redirect(url_for("auth.login"))

        # 3. Hash the password
        hashed_password = generate_password_hash(password)

        # 4. Create a new User object
        new_user = User(
            name=name,
            email=email,
            password_hash=hashed_password,
            university_name=university,
            department=department,
            contact_no=contact_no,
            # CRITICAL FIX: Set verification status to FALSE initially
            is_email_verified=False
        )

        # 5. Add to the database and save changes (Crucial: need user_id for token)
        db.session.add(new_user)
        db.session.commit()

        # 6. CRITICAL: Send the email verification link
        # Note: We rely on the User object being committed to get the user.user_id
        email_sent = send_verification_email(new_user)

        # 7. Flash success message and redirect
        if email_sent:
            flash("Registration successful! Please check your email to verify your address and activate your account.",
                  "info")
        else:
            # Provide an error message if mail fails (useful for local debugging)
            flash("Registration successful, but the verification email failed to send. Please contact support.",
                  "warning")

        return redirect(url_for("auth.login"))

    # For a GET request, just show the registration page
    return render_template("register.html")



@auth_bp.route("/reset_password", methods=['GET', 'POST'])
def reset_password_request():
    """Route for users to request a password reset link."""
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()

        if user:
            try:
                # 1. Generate Token and HTML Content
                token = user.get_reset_token()

                html_content = render_template(
                    'emails/reset_password.html',
                    user=user,
                    token=token
                )

                # NOTE: The sender must be the email address verified with SendGrid
                sender_email = current_app.config['MAIL_USERNAME']

                # 2. Build the SendGrid Message object
                message = Mail(
                    from_email=(sender_email,"ConfMgr"),
                    to_emails=user.email,
                    subject='Password Reset Request',
                    html_content=html_content
                )

                # 3. Send the message using the API key
                sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
                response = sg.send(message)

                # Check if SendGrid accepted the request (Status 202 is success)
                if response.status_code == 202:
                    flash('An email has been sent with instructions to reset your password.', 'info')
                else:
                    # Log the non-202 status for debugging, but treat as an application issue
                    print(f"SendGrid API Error: Unexpected status code {response.status_code}")
                    flash('Failed to send email. Please try again or check logs.', 'warning')

                return redirect(url_for('auth.login'))

            except Exception as e:
                # This catches errors like invalid API key, network issues, etc.
                print(f"SendGrid Integration Error: {e}")
                flash('An unexpected error occurred while processing your request.', 'danger')
                return redirect(url_for('auth.login'))
        else:
            flash('No account found with that email address.', 'warning')

    return render_template('auth/reset_request.html')


@auth_bp.route("/reset_password/<token>", methods=['GET', 'POST'])
def reset_token(token):
    """Route to handle the actual password reset using the token."""
    user = User.verify_reset_token(token)
    if user is None:
        flash('That is an invalid or expired token.', 'warning')
        return redirect(url_for('auth.reset_password_request'))

    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('auth/reset_password.html', token=token)

        user.password_hash = generate_password_hash(password)
        db.session.commit()
        flash('Your password has been updated! You are now able to log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', token=token)


@auth_bp.route("/verify_email/<token>")
def verify_email(token):
    user = User.verify_email_token(token)  # You must implement this static method on the User model

    if user:
        user.is_email_verified = True
        db.session.commit()
        flash("Email verified! You can now log in.", "success")
        return redirect(url_for('auth.login'))
    else:
        flash("Verification link is invalid or expired.", "error")
        return redirect(url_for('auth.register'))


def send_verification_email(user):
    """Generates a token and sends the verification email to the user via SendGrid API."""

    token = user.get_verification_token()
    sender_email = current_app.config['MAIL_USERNAME']  # Verified SendGrid Sender

    # Construct the verification link
    verify_url = url_for('auth.verify_email', token=token, _external=True)

    # Compose the plain text body (SendGrid prefers plain text or HTML content)
    body_content = f"""
Dear {user.name},

Thank you for registering with UniConfMgr - The Academic Nexus.
Please click the following link to verify your email address and activate your account:

{verify_url}

This link will expire in 30 minutes.

If you did not register for this service, please ignore this email.

The UniConfMgr Team
"""
    # 1. Build the SendGrid Message object
    message = Mail(
        from_email=(sender_email,"UniConfMgr"),
        to_emails=user.email,
        subject='Verify Your Email Address for UniConfMgr',
        plain_text_content=body_content  # Using plain_text_content
    )

    # 2. Send the message using the API key
    try:
        sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
        response = sg.send(message)

        # Check for successful API acceptance (HTTP Status 202)
        if 200 <= response.status_code < 300:
            return True
        else:
            print(f"SENDGRID API FAILED: Status {response.status_code}")
            return False

    except Exception as e:
        print(f"SENDGRID API ERROR: {e}")
        return False




def send_rejection_email(author_email: str, author_name: str, paper_title: str, conference: Conference):
    """
    Generates and sends a rejection notification using the SendGrid API.
    """

    if not author_email:
        print(f"REJECTION MAIL FAILED: Author email not found for paper '{paper_title}'.")
        return False

    # 1. Compose the plain text message body
    body_content = f"""
Dear {author_name},

The final decision on your paper, "{paper_title}", submitted to the {conference.title}, has been concluded.

Regrettably, your paper was not accepted for presentation at the conference. We thank you for your submission and encourage you to submit to future events.

You may still register to attend the conference as a participant via the public site.

The UniConfMgr Team
"""
    sender_email = current_app.config['MAIL_USERNAME']  # Verified SendGrid Sender

    # 2. Build the SendGrid Message object
    message = Mail(
        from_email=(sender_email,"UniConfMgr"),
        to_emails=author_email,
        subject=f'Decision on Paper: Regrettably Rejected - {conference.title}',
        plain_text_content=body_content
    )

    # 3. Send the message within the application context
    try:
        with current_app.app_context():
            sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))

            response = sg.send(message)

            # Check for successful API acceptance
            if 200 <= response.status_code < 300:
                return True
            else:
                print(f"SENDGRID API FAILED: Status {response.status_code}")
                return False

    except Exception as e:
        # Log the specific API error
        print(f"REJECTION MAIL FAILED (API Error): {e}")
        return False