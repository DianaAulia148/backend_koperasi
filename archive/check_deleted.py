
from main import app
from models.user_model import db, MemberRegistration

with app.app_context():
    all_regs = MemberRegistration.query.all()
    print(f"Total registrations: {len(all_regs)}")
    for r in all_regs:
        print(f"ID: {r.id}, Name: {r.full_name}, Status: '{r.status}', Deleted At: {r.deleted_at}")
