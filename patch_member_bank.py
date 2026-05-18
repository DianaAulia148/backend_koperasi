from main import app
from models.user_model import db, Member

with app.app_context():
    members = Member.query.all()
    for m in members:
        if not m.bank_name:
            m.bank_name = 'BCA'
            m.bank_account_no = '8800' + m.member_no[-6:] if m.member_no else '8800123456'
            m.bank_account_name = m.full_name
    db.session.commit()
    print(f"Updated {len(members)} members with dummy bank info.")
