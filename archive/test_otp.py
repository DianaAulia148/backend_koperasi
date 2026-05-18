import requests
import time
import pymysql
import os
from dotenv import load_dotenv

load_dotenv()

email = 'loverseblak@gmail.com'
r1 = requests.post('http://127.0.0.1:5000/api/resend-otp', data={'email': email})
print('Resend status:', r1.status_code)

time.sleep(1) # wait for db

conn = pymysql.connect(host=os.getenv('DB_HOST', 'localhost'), user=os.getenv('DB_USER', 'root'), password=os.getenv('DB_PASSWORD', ''), database=os.getenv('DB_NAME'))
cursor = conn.cursor()
cursor.execute("SELECT otp_code, created_at, expires_at FROM otp_verifications WHERE email=%s ORDER BY id DESC LIMIT 1", (email,))
otp_row = cursor.fetchone()
print('OTP Record:', otp_row)

if otp_row:
    r2 = requests.post('http://127.0.0.1:5000/api/verify-otp', data={'email': email, 'otp_code': otp_row[0]})
    print('Verify status:', r2.status_code)
    print('Verify response:', r2.text)
