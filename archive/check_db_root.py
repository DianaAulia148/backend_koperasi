
from main import app
from models.user_model import db, MemberRegistration

with app.app_context():
    all_regs = MemberRegistration.query.all()
    print(f"Total registrations in DB: {len(all_regs)}")
    for r in all_regs:
        print(f"ID: {r.id}, Name: {r.full_name}, Status: {r.status}, Approval Status: {r.approval_status}")
