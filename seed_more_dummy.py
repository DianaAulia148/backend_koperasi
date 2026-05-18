import os
import random
from datetime import datetime, timedelta
from config import Config
from models.user_model import db, Member, SavingType, SavingTransaction
from main import app

def generate_more_dummy_data():
    with app.app_context():
        print(">>> Memulai injeksi 50 data dummy tambahan untuk bulan ini...")
        
        member = Member.query.first()
        saving_type_wajib = SavingType.query.filter_by(code='SW').first()
        
        if not member or not saving_type_wajib:
            print("Member atau SavingType belum ada.")
            return
            
        categories_pemasukan = ['Gaji Bulanan', 'Penjualan Aplikasi', 'Bonus Kinerja', 'Pencairan Dana']
        categories_pengeluaran = ['Keperluan Kantor', 'Keluarga', 'Beli Alat Kantor', 'Pembayaran Project', 'Lainnya']
        
        # Start from 1st of current month
        today = datetime.now()
        start_date = today.replace(day=1)
        
        for i in range(50):
            # Random date within this month up to today
            days_range = (today - start_date).days
            if days_range <= 0:
                days_range = 1
            random_days = random.randint(0, days_range)
            tx_date = start_date + timedelta(days=random_days, hours=random.randint(8, 17), minutes=random.randint(0, 59))
            
            # 60% Pemasukan, 40% Pengeluaran
            is_credit = random.random() < 0.6
            
            amount = float(random.randint(10, 500) * 10000) # 100k - 5m
            
            if is_credit:
                cat = random.choice(categories_pemasukan)
            else:
                cat = random.choice(categories_pengeluaran)
                
            tx = SavingTransaction(
                member_id=member.id,
                saving_type_id=saving_type_wajib.id,
                transaction_type='CREDIT' if is_credit else 'DEBIT',
                amount=amount,
                balance_before=0,
                balance_after=amount,
                transaction_source=cat,
                reference_number=f"TRX-EXTRA-{i}-{int(datetime.now().timestamp())}",
                transaction_date=tx_date,
                description=f"Topup Saldo {i}",
                transaction_status='SUCCESS'
            )
            db.session.add(tx)
            
        db.session.commit()
        print(">>> 50 Data dummy tambahan berhasil di-generate!")

if __name__ == '__main__':
    generate_more_dummy_data()
