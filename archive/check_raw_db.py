
import os
import pymysql
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

load_dotenv()

conn = pymysql.connect(
    host=os.getenv('DB_HOST', 'localhost'), 
    user=os.getenv('DB_USER', 'root'), 
    password=os.getenv('DB_PASSWORD', ''),
    database=os.getenv('DB_NAME')
)

cursor = conn.cursor(pymysql.cursors.DictCursor)
cursor.execute("SELECT id, full_name, status, approval_status, deleted_at FROM member_registration")
rows = cursor.fetchall()

print(f"Total rows in DB: {len(rows)}")
for row in rows:
    print(row)

conn.close()
