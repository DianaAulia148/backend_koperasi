import os
import pymysql
from dotenv import load_dotenv

load_dotenv()

from flask import Flask, redirect, url_for
from config import Config
from models.user_model import db
from routes.auth_routes import auth_bp, oauth, mail
from routes.api_routes import api_bp
from routes.onboarding_routes import onboarding_bp
from routes.finance_routes import finance_bp
from routes.report_routes import report_bp
from routes.analytics_routes import analytics_bp
from routes.economic_routes import economic_bp
from flask_mail import Mail

app = Flask(__name__)
app.config.from_object(Config)

# Register Blueprint & DB
db.init_app(app)
oauth.init_app(app)
mail.init_app(app)
app.register_blueprint(auth_bp)
app.register_blueprint(api_bp)
app.register_blueprint(onboarding_bp)
app.register_blueprint(finance_bp)
app.register_blueprint(report_bp)
app.register_blueprint(analytics_bp)
app.register_blueprint(economic_bp)

@app.route("/")
def index():
    return redirect(url_for('auth.login'))

def init_db():
    try:
        # Create DB if not exists
        conn = pymysql.connect(
            host=os.getenv('DB_HOST', 'localhost'), 
            user=os.getenv('DB_USER', 'root'), 
            password=os.getenv('DB_PASSWORD', ''),
            connect_timeout=5  # Maksimal menunggu 5 detik
        )
        conn.cursor().execute(f"CREATE DATABASE IF NOT EXISTS {os.getenv('DB_NAME')}")
        conn.close()
    except Exception as e:
        print(f"Failed to create database: {e}")

if __name__ == "__main__":
    print(">>> Menghubungkan ke Database...")
    init_db()
    with app.app_context():
        print(">>> Sinkronisasi Tabel Database...")
        db.create_all()
    print(f">>> Aplikasi SIAP di http://192.168.110.95:5000")
    app.run(host='0.0.0.0', port=5000, debug=True)