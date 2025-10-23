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

    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
