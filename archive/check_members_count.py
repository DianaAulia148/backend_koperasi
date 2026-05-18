from main import app
from models.user_model import Member
with app.app_context():
    print(f"Jumlah Anggota di DB: {Member.query.count()}")
