from flask import Flask, render_template
from instance.config import Config
from routes.auth_routes import auth_bp
from routes.admin_routes import admin_bp
from routes.profile import profile_bp
from routes.conference_routes import conference_bp
from routes.roles import roles_bp
from routes.participant import participant_bp
from routes.organizer_routes import organizer_bp
from routes.reviewer_routes import reviewer_bp
from routes.author_routes import author_bp
from routes.publish_schedule_pdf import schedule_bp
from extensions import db, mail
from datetime import datetime,date
from flask_migrate import Migrate


app = Flask(__name__, instance_relative_config=True)
app.config.from_object(Config)

@app.context_processor
def inject_now():
    return {'now': datetime.now}

# Initialize extensions
db.init_app(app)
mail.init_app(app)
migrate = Migrate(app, db)

# Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(conference_bp)
app.register_blueprint(profile_bp)
app.register_blueprint(roles_bp)
app.register_blueprint(participant_bp)
app.register_blueprint(organizer_bp)
app.register_blueprint(schedule_bp)
app.register_blueprint(reviewer_bp)
app.register_blueprint(author_bp, url_prefix='/author')

@app.route("/")
def home():
    return render_template("index.html")

with app.app_context():
    db.create_all()

def is_submitted_test(value):
    """Checks if a review recommendation is submitted (i.e., not None)."""
    return value is not None

def format_datetime_filter(value, format_string):
    """Formats a datetime or date object using strftime."""
    # Ensure value is treated as a datetime object
    if isinstance(value, datetime):
        return value.strftime(format_string)
    if isinstance(value, date):
        return value.strftime(format_string)
    return value # Return original value if it's not a date/datetime

app.jinja_env.tests['is_submitted'] = is_submitted_test
app.jinja_env.filters['strftime'] = format_datetime_filter

if __name__ == "__main__":
    app.run(debug=True)
