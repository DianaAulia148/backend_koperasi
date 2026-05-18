import os
import pymysql
from dotenv import load_dotenv

load_dotenv()

def fix_member_bank_columns():
    print(">>> Menghubungkan ke database...")
    conn = pymysql.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD', ''),
        database=os.getenv('DB_NAME')
    )
    
    cursor = conn.cursor()
    print(">>> Menambahkan kolom bank ke tabel members...")
    
    columns_to_add = {
        'bank_name': 'VARCHAR(100)',
        'bank_account_no': 'VARCHAR(100)',
        'bank_account_name': 'VARCHAR(100)'
    }
    
    for col, ctype in columns_to_add.items():
        try:
            cursor.execute(f"ALTER TABLE members ADD COLUMN {col} {ctype}")
            print(f"Sukses menambahkan {col} ke members")
        except Exception as e:
            if "Duplicate column name" in str(e):
                print(f"Kolom {col} sudah ada.")
            else:
                print(f"Error {col}: {e}")
                
    conn.commit()
    conn.close()
    print(">>> Sinkronisasi Database Anggota Selesai!")

if __name__ == "__main__":
    fix_member_bank_columns()
