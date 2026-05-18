from main import app
from models.user_model import Member
with app.app_context():
    member = Member.query.filter((Member.full_name.like('%BUDI%')) | (Member.email.like('%kholil%'))).first()
    if member:
        print(f"FOUND: ID={member.id}, Name={member.full_name}, Email={member.email}, DB={app.config['SQLALCHEMY_DATABASE_URI']}")
    else:
        print("NOT FOUND in currently connected database.")
