import os
import random
from datetime import datetime, timedelta
from config import Config
from models.user_model import db, User, Member, SavingType, MemberSavingBalance, SavingTransaction, PayrollBatch, WithdrawalRequest
from main import app

def generate_dummy_data():
    with app.app_context():
        print(">>> Memulai proses injeksi data dummy keuangan...")
        
        # 1. Pastikan ada SavingType
        saving_type_wajib = SavingType.query.filter_by(code='SW').first()
        if not saving_type_wajib:
            saving_type_wajib = SavingType(code='SW', name='Simpanan Wajib', description='Simpanan Wajib Anggota')
            db.session.add(saving_type_wajib)
        
        saving_type_pokok = SavingType.query.filter_by(code='SP').first()
        if not saving_type_pokok:
            saving_type_pokok = SavingType(code='SP', name='Simpanan Pokok', description='Simpanan Pokok Anggota')
            db.session.add(saving_type_pokok)
            
        saving_type_sukarela = SavingType.query.filter_by(code='SS').first()
        if not saving_type_sukarela:
            saving_type_sukarela = SavingType(code='SS', name='Simpanan Sukarela', description='Simpanan Sukarela Anggota')
            db.session.add(saving_type_sukarela)

        db.session.commit()

        # 2. Pastikan ada Member
        member = Member.query.first()
        if not member:
            member = Member(
                member_no='M-DUMMY001',
                nik='1234567890123456',
                full_name='Dummy Member',
                status='AKTIF',
                bank_name='BCA',
                bank_account_no='8800123456',
                bank_account_name='Dummy Member'
            )
            db.session.add(member)
            db.session.commit()

        # 3. Buat beberapa SavingTransactions untuk 3 bulan terakhir
        categories = ['Keperluan Kantor', 'Keluarga', 'Lainnya', 'Penjualan Aplikasi', 'Pembuatan Aplikasi', 'Gaji Bulanan', 'Bonus Kinerja']
        
        start_date = datetime.now() - timedelta(days=90)
        
        print(">>> Membuat transaksi dummy...")
        for i in range(25):
            tx_date = start_date + timedelta(days=random.randint(1, 90))
            is_credit = random.choice([True, True, False]) # Lebih banyak pemasukan
            
            amount = float(random.randint(500, 5000) * 1000) # 500rb - 5jt
            
            tx = SavingTransaction(
                member_id=member.id,
                saving_type_id=saving_type_wajib.id,
                transaction_type='CREDIT' if is_credit else 'DEBIT',
                amount=amount,
                balance_before=0,
                balance_after=amount,
                transaction_source=random.choice(categories),
                reference_number=f"TRX-DUMMY-{i}-{int(datetime.now().timestamp())}",
                transaction_date=tx_date,
                description=f"Transaksi Dummy {i}",
                transaction_status='SUCCESS'
            )
            db.session.add(tx)
            
        # 4. Update Summary Statistics Dummy
        print(">>> Mengupdate saldo dan summary...")
        balance = MemberSavingBalance.query.filter_by(member_id=member.id).first()
        if not balance:
            balance = MemberSavingBalance(member_id=member.id, saving_type_id=saving_type_wajib.id, balance=150000000)
            db.session.add(balance)
            
        payroll = PayrollBatch.query.filter_by(batch_code='PB-DUMMY').first()
        if not payroll:
            payroll = PayrollBatch(batch_code='PB-DUMMY', total_amount=85000000, validation_status='SUCCESS', distribution_status='SUCCESS')
            db.session.add(payroll)
            
        withdraw = WithdrawalRequest.query.filter_by(member_id=member.id).first()
        if not withdraw:
            withdraw = WithdrawalRequest(member_id=member.id, amount=12000000, approval_status='APPROVED')
            db.session.add(withdraw)
            
        db.session.commit()
        print(">>> Data dummy berhasil di-generate!")

if __name__ == '__main__':
    generate_dummy_data()
