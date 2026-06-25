import os
from dotenv import load_dotenv

load_dotenv()

# Mengizinkan OAuth HTTP untuk local development
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")
    BASE_API_URL = "http://192.168.18.143:5000"

    # Database configuration: use MySQL if all required env vars are set, otherwise fallback to SQLite for local development
    DB_USER = os.getenv('DB_USER')
    DB_PASSWORD = os.getenv('DB_PASSWORD')
    DB_HOST = os.getenv('DB_HOST')
    DB_NAME = os.getenv('DB_NAME')
    if DB_USER and DB_PASSWORD and DB_HOST and DB_NAME:
        SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"
    else:
        # SQLite database file located in the project root
        SQLALCHEMY_DATABASE_URI = 'sqlite:///app.db'

    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_ID_MOBILE = os.getenv("GOOGLE_CLIENT_ID_MOBILE")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

    # Mail Settings
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_USERNAME")