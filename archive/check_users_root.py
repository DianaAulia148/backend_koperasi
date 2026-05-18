from main import app
from models.user_model import User
import os

with app.app_context():
    try:
        users = User.query.all()
        if not users:
            print("No users found in database.")
        for u in users:
            print(f"Email: {u.email}, ID: {u.employee_id}")
    except Exception as e:
        print(f"Error: {e}")
