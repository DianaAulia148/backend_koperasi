import os
print(">>> Mulai inisialisasi...")
os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'
import pymysql
print(">>> pymysql diimpor...")
from dotenv import load_dotenv

load_dotenv()

print(">>> Mulai mengimpor Flask dan library lainnya (ini mungkin memakan waktu)...")
from flask import Flask, redirect, url_for
from flask_cors import CORS
from config import Config
from models.user_model import db
from routes.auth_routes import auth_bp, oauth, mail
from routes.api_routes import api_bp
from routes.onboarding_routes import onboarding_bp
from routes.finance_routes import finance_bp
from routes.report_routes import report_bp
from routes.analytics_routes import analytics_bp
from routes.economic_routes import economic_bp
from routes.news_routes import news_bp
from flask_mail import Mail

app = Flask(__name__)
app.config.from_object(Config)

# Fix for reverse proxy (Hugging Face / Ngrok) to ensure HTTPS is recognized
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Aktifkan CORS agar Flutter (HP) bisa mengakses API dari laptop
CORS(app, resources={r"/*": {"origins": "*"}})  # type: ignore

# Register Blueprint & DB
db.init_app(app)
oauth.init_app(app)
mail.init_app(app)
app.register_blueprint(auth_bp)
app.register_blueprint(api_bp)
app.register_blueprint(onboarding_bp, url_prefix='/onboarding')
app.register_blueprint(finance_bp)
app.register_blueprint(report_bp)
app.register_blueprint(analytics_bp)
app.register_blueprint(economic_bp)
app.register_blueprint(news_bp)

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
            port=int(os.getenv('DB_PORT', 3306)),
            connect_timeout=5  # Maksimal menunggu 5 detik
        )
        conn.cursor().execute(f"CREATE DATABASE IF NOT EXISTS {os.getenv('DB_NAME')}")
        conn.close()
    except Exception as e:
        print(f"Failed to create database: {e}")

if __name__ == "__main__":
    print(">>> Menghubungkan ke Database...")
    init_db()
    print(">>> Sinkronisasi Tabel Database...")
    try:
        with app.app_context():
            db.create_all()
    except Exception as e:
        print(f"Warning during table creation: {e}")

    # Pra-load model OCR & scheduler hanya di proses utama (mencegah berjalan ganda saat reload)
    is_main_process = (not app.config.get('DEBUG', False)) or (os.environ.get('WERKZEUG_RUN_MAIN') == 'true')
    
    if is_main_process:
        import threading
        from utils.ocr_helper import warm_up_models
        # Matikan warmup otomatis agar memori server gratis HF tidak jebol saat startup
        # warmup_thread = threading.Thread(target=warm_up_models, daemon=True)
        # warmup_thread.start()

        # Inisialisasi scheduler otomatis pengambilan data ekonomi (UAS Big Data Kriteria)
        try:
            from utils.scheduler import init_scheduler
            init_scheduler(app)
            print(">>> Scheduler Otomatis (Daily/Hourly Scraper) AKTIF!")
        except Exception as e:
            print(f"Warning: Gagal mengaktifkan background scheduler: {e}")

    print(">>> Aplikasi SIAP dijalankan pada port 7860!")
    app.run(host='0.0.0.0', port=7860, debug=False, threaded=True, use_reloader=False)