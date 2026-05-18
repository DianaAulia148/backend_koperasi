from models.user_model import db, MobileUser, MemberRegistration, Member
from flask import Flask
from config import Config

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

with app.app_context():
    print("--- Members in DB ---")
    members = Member.query.all()
    for m in members:
        print(f"MemberID: {m.id}, Name: {m.full_name}, MobileUserID: {m.mobile_user_id}, Status: {m.status}")
