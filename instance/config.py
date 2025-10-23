# config.py
import os
from dotenv import load_dotenv

load_dotenv()

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:

    SECRET_KEY = str(os.environ.get('SECRET_KEY'))

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        "sqlite:///" + os.path.join(basedir, "conference.db")
    ).replace("postgres://", "postgresql://", 1)

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # 3. Flask-Mail settings (Load securely)
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
