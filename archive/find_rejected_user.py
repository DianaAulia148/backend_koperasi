from models.user_model import db, MobileUser, MemberRegistration, Member
from flask import Flask
from config import Config

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

with app.app_context():
    # Find users who are NOT in members table
    member_uids = [m.mobile_user_id for m in Member.query.all() if m.mobile_user_id is not None]
    
    # Find registrations with status 'rejected' for users not in members
    rejected_regs = MemberRegistration.query.filter(
        MemberRegistration.status == 'rejected',
        ~MemberRegistration.mobile_user_id.in_(member_uids)
    ).all()
    
    print("--- Users with only Rejected Registrations ---")
    for r in rejected_regs:
        print(f"MobileUserID: {r.mobile_user_id}, Name: {r.ocr_name}, Rejection: {r.rejection_reason}")
