from models.user_model import db, MobileUser, MemberRegistration
from flask import Flask
from config import Config

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

with app.app_context():
    # Create a new test user
    test_user = MobileUser(
        full_name="User Ditolak",
        email="rejected@example.com",
        status="AKTIF"
    )
    db.session.add(test_user)
    db.session.commit()
    
    # Create a rejected registration for this user
    reg = MemberRegistration(
        mobile_user_id=test_user.id,
        ocr_name="User Ditolak",
        status="rejected",
        rejection_reason="Dokumen KTP tidak terbaca jelas.",
        approval_status="REJECTED"
    )
    db.session.add(reg)
    db.session.commit()
    
    print(f"Created rejected test user with ID: {test_user.id}")
