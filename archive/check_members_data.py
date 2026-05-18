from main import app
from models.user_model import Member
with app.app_context():
    members = Member.query.limit(5).all()
    for m in members:
        print(f"ID: {m.id}, Name: {m.full_name}, Created: {m.date_joined}")
