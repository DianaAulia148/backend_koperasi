from models.user_model import db, ActivityLog
from flask import Flask
from config import Config

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

with app.app_context():
    # Mock request context for remote_addr
    with app.test_request_context(environ_base={'REMOTE_ADDR': '127.0.0.1'}):
        ActivityLog.log("Test Log from Script", user_id=1)
        print("Logged successfully from script.")
