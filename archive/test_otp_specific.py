import pymysql
import os
from dotenv import load_dotenv

load_dotenv()
conn = pymysql.connect(host=os.getenv('DB_HOST', 'localhost'), user=os.getenv('DB_USER', 'root'), password=os.getenv('DB_PASSWORD', ''), database=os.getenv('DB_NAME'))
cursor = conn.cursor()
cursor.execute("SELECT email, otp_code, created_at FROM otp_verifications WHERE email='kholilala99@gmail.com'")
print("OTP for kholilala99:", cursor.fetchall())
