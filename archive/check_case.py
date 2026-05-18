
from main import app
from models.user_model import db, MemberRegistration
from sqlalchemy import func

with app.app_context():
    all_regs = MemberRegistration.query.all()
    print(f"Total registrations: {len(all_regs)}")
    
    pending_count = MemberRegistration.query.filter_by(status='pending').count()
    Pending_count = MemberRegistration.query.filter_by(status='Pending').count()
    
    print(f"Status 'pending' (lowercase) count: {pending_count}")
    print(f"Status 'Pending' (Capitalized) count: {Pending_count}")
    
    for r in all_regs:
        print(f"ID: {r.id}, Name: {r.full_name}, Status: '{r.status}'")
