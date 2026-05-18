import os
import pymysql
from dotenv import load_dotenv

load_dotenv()

from flask import Flask
from config import Config
from models.user_model import db

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

def upgrade_existing_tables():
    conn = pymysql.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD', ''),
        database=os.getenv('DB_NAME')
    )
    
    cursor = conn.cursor()
    print(">>> Memulai proses ALTER table untuk menambahkan kolom baru...")
    
    # 1. Update members
    columns_members = {
        'nip': 'VARCHAR(50) UNIQUE',
        'nik': 'VARCHAR(20) UNIQUE',
        'photo_profile': 'VARCHAR(255)',
        'signature_path': 'VARCHAR(255)',
        'deleted_at': 'DATETIME'
    }
    for col, ctype in columns_members.items():
        try:
            cursor.execute(f"ALTER TABLE members ADD COLUMN {col} {ctype}")
            print(f"Sukses menambahkan {col} ke members")
        except Exception as e:
            if "Duplicate column name" not in str(e):
                print(f"Error {col}: {e}")

    # 2. Update member_registration
    columns_registration = {
        'registration_code': 'VARCHAR(50) UNIQUE',
        'document_type': 'VARCHAR(50)',
        'ocr_name': 'VARCHAR(100)',
        'ocr_nik': 'VARCHAR(20)',
        'ocr_nip': 'VARCHAR(50)',
        'ocr_address': 'TEXT',
        'ocr_raw_text': 'TEXT',
        'ocr_confidence': 'FLOAT',
        'duplicate_check_status': 'VARCHAR(20) DEFAULT "PENDING"',
        'duplicate_reference_id': 'INT',
        'verification_status': 'VARCHAR(20) DEFAULT "PENDING"',
        'approval_status': 'VARCHAR(20) DEFAULT "PENDING"',
        'approved_by': 'INT',
        'approved_at': 'DATETIME',
        'updated_at': 'DATETIME',
        'deleted_at': 'DATETIME',
        'ocr_engine': 'VARCHAR(50)',
        'ocr_processed_at': 'DATETIME',
        'ocr_retry_count': 'INT DEFAULT 0',
        'fraud_score': 'FLOAT DEFAULT 0',
        'suspicious_reason': 'TEXT',
        'blacklist_match': 'BOOLEAN DEFAULT FALSE'
    }
    for col, ctype in columns_registration.items():
        try:
            cursor.execute(f"ALTER TABLE member_registration ADD COLUMN {col} {ctype}")
            print(f"Sukses menambahkan {col} ke member_registration")
        except Exception as e:
            if "Duplicate column name" not in str(e):
                print(f"Error {col}: {e}")
                
    # 3. Update withdrawal_requests
    columns_withdrawals = {
        'saving_transaction_id': 'INT'
    }
    for col, ctype in columns_withdrawals.items():
        try:
            cursor.execute(f"ALTER TABLE withdrawal_requests ADD COLUMN {col} {ctype}")
            print(f"Sukses menambahkan {col} ke withdrawal_requests")
        except Exception as e:
            if "Duplicate column name" not in str(e):
                print(f"Error {col}: {e}")
                
    conn.commit()
    conn.close()
    print(">>> Selesai ALTER tabel lama.")

if __name__ == "__main__":
    with app.app_context():
        print(">>> Sinkronisasi pembuatan tabel baru via SQLAlchemy (db.create_all())...")
        db.create_all()
        print(">>> Tabel Enterprise baru BERHASIL terbuat.")
        
    try:
        upgrade_existing_tables()
    except Exception as e:
        print("Gagal menjalankan alter table:", e)
    
    print("================================")
    print("Database siap digunakan dengan struktur V4 Final!")
