import os
import random
from datetime import datetime, timedelta
from config import Config
from models.user_model import db, Member, SavingType, SavingTransaction
from main import app

def generate_multi_type_dummy_data():
    with app.app_context():
        print(">>> Memulai injeksi data dummy lintas simpanan (SP, SW, SS)...")
        
        member = Member.query.first()
        saving_types = SavingType.query.all()
        
        if not member or not saving_types:
            print("Member atau SavingType belum ada.")
            return
            
        categories_pemasukan = ['Gaji Bulanan', 'Penjualan Aplikasi', 'Bonus Kinerja', 'Pencairan Dana']
        categories_pengeluaran = ['Keperluan Kantor', 'Keluarga', 'Beli Alat Kantor', 'Pembayaran Project', 'Lainnya']
        
        today = datetime.now()
        start_date = today.replace(day=1)
        
        for i in range(30):
            # Random date within this month
            days_range = (today - start_date).days
            if days_range <= 0: days_range = 1
            random_days = random.randint(0, days_range)
            tx_date = start_date + timedelta(days=random_days, hours=random.randint(8, 17), minutes=random.randint(0, 59))
            
            # Randomly pick a saving type
            st = random.choice(saving_types)
            
            # 70% Pemasukan, 30% Pengeluaran
            is_credit = random.random() < 0.7
            amount = float(random.randint(10, 200) * 10000)
            
            cat = random.choice(categories_pemasukan if is_credit else categories_pengeluaran)
                
            tx = SavingTransaction(
                member_id=member.id,
                saving_type_id=st.id,
                transaction_type='CREDIT' if is_credit else 'DEBIT',
                amount=amount,
                balance_before=0,
                balance_after=amount,
                transaction_source=cat,
                reference_number=f"TRX-MULTI-{st.code}-{i}-{int(datetime.now().timestamp())}",
                transaction_date=tx_date,
                description=f"Simpanan {st.name}",
                transaction_status='SUCCESS'
            )
            db.session.add(tx)
            
        db.session.commit()
        print(">>> Data dummy lintas simpanan berhasil di-generate!")

if __name__ == '__main__':
    generate_multi_type_dummy_data()
