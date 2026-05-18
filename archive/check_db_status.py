from models.user_model import db, Member, MemberRegistration
from flask import Flask
import os
from config import Config

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

with app.app_context():
    print("--- Members Status ---")
    members = Member.query.all()
    for m in members:
        print(f"ID: {m.id}, Name: {m.full_name}, Status: {m.status}, MobileUserID: {m.mobile_user_id}")
    
    print("\n--- Member Registrations Status ---")
    regs = MemberRegistration.query.all()
    for r in regs:
        print(f"ID: {r.id}, Name: {r.ocr_name}, Status: {r.status}, ApprovalStatus: {r.approval_status}, Rejection: {r.rejection_reason}")
