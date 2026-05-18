from models.user_model import db, ActivityLog
from flask import Flask
from config import Config

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

with app.app_context():
    logs = ActivityLog.query.order_by(ActivityLog.created_at.desc()).limit(10).all()
    if not logs:
        print("Table 'activity_logs' is empty.")
    else:
        print("--- Recent Activity Logs ---")
        for log in logs:
            print(f"[{log.created_at}] UserID: {log.user_id}, Action: {log.activity}, IP: {log.ip_address}")
