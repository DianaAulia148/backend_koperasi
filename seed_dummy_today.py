import os
import random
from datetime import datetime
from config import Config
from models.user_model import db, Member, SavingType, SavingTransaction
from main import app

def generate_specific_dummy_data():
    with app.app_context():
        print(">>> Memulai injeksi data spesifik untuk 7-8 Mei 2026...")
        
        member = Member.query.first()
        saving_type_wajib = SavingType.query.filter_by(code='SW').first()
        
        if not member or not saving_type_wajib:
            print("Member atau SavingType belum ada. Harap jalankan seed_dummy.py dulu.")
            return

        dates_to_seed = [
            datetime(2026, 5, 7, 10, 30),
            datetime(2026, 5, 7, 14, 15),
            datetime(2026, 5, 8, 9, 0),
            datetime(2026, 5, 8, 16, 45)
        ]
        
        categories = ['Keperluan Kantor', 'Pembuatan Aplikasi', 'Gaji Bulanan', 'Beli Alat Kantor']
        
        for i, dt in enumerate(dates_to_seed):
            is_credit = random.choice([True, False])
            amount = float(random.randint(50, 500) * 10000) # 500k - 5m
            
            tx = SavingTransaction(
                member_id=member.id,
                saving_type_id=saving_type_wajib.id,
                transaction_type='CREDIT' if is_credit else 'DEBIT',
                amount=amount,
                balance_before=0,
                balance_after=amount,
                transaction_source=categories[i],
                reference_number=f"TRX-SPECIFIC-{i}-{int(datetime.now().timestamp())}",
                transaction_date=dt,
                description=f"Transaksi Dummy {dt.strftime('%d %b')}",
                transaction_status='SUCCESS'
            )
            db.session.add(tx)
            
        db.session.commit()
        print(">>> Data spesifik berhasil di-generate!")

if __name__ == '__main__':
    generate_specific_dummy_data()
