import os
from main import app
from models.user_model import db, Member, Transaction
import random
from datetime import datetime

with app.app_context():
    db.create_all()
    
    # Check if empty, then seed
    if Member.query.count() == 0:
        members = [
            Member(name="Bambang N.", initials="BN", status="Pending", ocr_score=98),
            Member(name="Ani Setiani", initials="AS", status="Pending", ocr_score=84),
            Member(name="Siti Rahma", initials="SR", status="Verified", ocr_score=99),
            Member(name="Agus Salim", initials="AS", status="Verified", ocr_score=100),
            Member(name="Dian Sastro", initials="DS", status="Verified", ocr_score=95),
            Member(name="Rafi Ahmad", initials="RA", status="Verified", ocr_score=90),
            Member(name="Luna Maya", initials="LM", status="Verified", ocr_score=88),
            Member(name="Gita Gutawa", initials="GG", status="Pending", ocr_score=75)
        ]
        db.session.add_all(members)
        
        # Adding around dummy 1200 records count to simulate 1.2K members (We can just insert a few and let the query count them, or simply add 1200 empty members)
        # Actually, let's just insert 8 and manually spoof the count if needed, or I'll just insert 1200 dummy rows
        dummy_members = [Member(name=f"Member {i}", initials="M", status="Verified") for i in range(1276)]
        db.session.bulk_save_objects(dummy_members)

        txs = [
            Transaction(tx_id="#TX-9021", name="Samsul H.", tx_type="SETOR", amount=2500000.0, status="Selesai"),
            Transaction(tx_id="#TX-9018", name="Indah P.", tx_type="TARIK", amount=5000000.0, status="Pending"),
            Transaction(tx_id="#TX-9017", name="Budi R.", tx_type="SETOR", amount=1420000000.0, status="Selesai"),
            Transaction(tx_id="#TX-9016", name="Siti R.", tx_type="SETOR", amount=2780000000.0, status="Selesai"),
            Transaction(tx_id="#TX-9015", name="Agus S.", tx_type="TARIK", amount=842000000.0, status="Selesai")
        ]
        db.session.add_all(txs)
        
        db.session.commit()
        print("Database seeded with Members and Transactions.")
    else:
        print("Database already has records, skipping seed.")
