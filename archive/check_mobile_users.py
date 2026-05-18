from models.user_model import db, MobileUser, MemberRegistration, Member
from flask import Flask
from config import Config

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

with app.app_context():
    print("--- Mobile Users ---")
    users = MobileUser.query.all()
    for u in users:
        print(f"ID: {u.id}, Name: {u.full_name}, Email: {u.email}")
    
    print("\n--- Registrations (ID vs MobileUserID) ---")
    regs = MemberRegistration.query.all()
    for r in regs:
        print(f"RegID: {r.id}, MobileUserID: {r.mobile_user_id}, Name: {r.ocr_name}")
