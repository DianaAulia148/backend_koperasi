from dotenv import load_dotenv
load_dotenv()
import os

db_user = os.getenv('DB_USER')
db_password = os.getenv('DB_PASSWORD')
db_host = os.getenv('DB_HOST')
db_name = os.getenv('DB_NAME')

print('DB_USER:', db_user)
print('DB_PASSWORD:', repr(db_password))
print('DB_HOST:', db_host)
print('DB_NAME:', db_name)

if db_user and db_host and db_name:
    uri = f'mysql+pymysql://{db_user}:{db_password}@{db_host}/{db_name}'
else:
    uri = 'sqlite:///app.db'

print('URI yang akan digunakan Flask:', uri)

from sqlalchemy import create_engine, text
engine = create_engine(uri)
try:
    with engine.connect() as con:
        result = con.execute(text('SELECT COUNT(*) FROM mobile_users'))
        count = result.scalar()
        print('Jumlah mobile_users (via SQLAlchemy):', count)
        
        result2 = con.execute(text("SELECT email, password FROM mobile_users WHERE email='olar4865@gmail.com'"))
        row = result2.fetchone()
        if row:
            print('User ditemukan:', row[0])
            
            import hashlib
            hashed_input = hashlib.sha256('1234567890'.encode()).hexdigest()
            print('Hash di DB:    ', row[1])
            print('Hash dari input:', hashed_input)
            print('Cocok?', row[1] == hashed_input)
        else:
            print('USER TIDAK DITEMUKAN DI DATABASE!')
except Exception as e:
    print('ERROR koneksi SQLAlchemy:', e)
