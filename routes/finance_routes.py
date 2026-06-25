from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from models.user_model import (db, User, MemberSavingBalance, SavingTransaction,
                                PayrollBatch, WithdrawalRequest, DepositRequest,
                                Member, SavingType, PayrollBatchDetail)
from datetime import datetime
from sqlalchemy import func
import secrets

finance_bp = Blueprint('finance', __name__)


# ─────────────────────────────────────────────────────────────────────────────
# PAYROLL HALAMAN UTAMA
# ─────────────────────────────────────────────────────────────────────────────
@finance_bp.route('/finance/payroll')
def payroll():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    current_user = User.query.get(session['user_id'])

    batches = PayrollBatch.query.order_by(PayrollBatch.uploaded_at.desc()).all()

    total_payroll_this_month = db.session.query(func.sum(PayrollBatch.total_amount)).filter(
        func.extract('month', PayrollBatch.uploaded_at) == datetime.now().month,
        func.extract('year', PayrollBatch.uploaded_at) == datetime.now().year
    ).scalar() or 0

    total_batches = PayrollBatch.query.count()
    successful_distributions = PayrollBatchDetail.query.filter_by(distribution_status='SUCCESS').count()
    active_members_count = Member.query.filter_by(status='AKTIF').count()

    stats = {
        'total_payroll': total_payroll_this_month,
        'total_batches': total_batches,
        'successful_distributions': successful_distributions,
        'active_members': active_members_count,
    }

    return render_template('payroll.html',
                           current_user=current_user,
                           active_menu='payroll',
                           page_title='Payroll Automation',
                           batches=batches,
                           stats=stats)


# ─────────────────────────────────────────────────────────────────────────────
# API: PROSES PAYROLL OTOMATIS
# ─────────────────────────────────────────────────────────────────────────────
@finance_bp.route('/finance/payroll/auto_process', methods=['POST'])
def auto_process_payroll():
    """
    Proses payroll otomatis: distribusi simpanan wajib ke semua anggota aktif.
    Body JSON (opsional): { "amount_per_member": 500000 }
    """
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    try:
        data = request.get_json(silent=True) or {}
        amount_per_member = int(data.get('amount_per_member', 500000))

        active_members = Member.query.filter_by(status='AKTIF').all()
        if not active_members:
            return jsonify({'success': False, 'error': 'Tidak ada anggota aktif.'}), 400

        st_wajib = SavingType.query.filter_by(code='SW').first()
        if not st_wajib:
            return jsonify({'success': False, 'error': 'Tipe simpanan Wajib (kode SW) tidak ditemukan.'}), 400

        # Cegah duplikat proses bulan yang sama
        existing = PayrollBatch.query.filter_by(
            period_month=datetime.now().month,
            period_year=datetime.now().year,
            distribution_status='SUCCESS'
        ).first()
        if existing:
            return jsonify({
                'success': False,
                'error': f'Payroll bulan ini sudah diproses (Batch: {existing.batch_code}).'
            }), 400

        total_amount = len(active_members) * amount_per_member
        batch_code = "PR-" + datetime.now().strftime("%Y%m") + "-" + secrets.token_hex(2).upper()

        new_batch = PayrollBatch(
            batch_code=batch_code,
            period_month=datetime.now().month,
            period_year=datetime.now().year,
            total_amount=total_amount,
            total_members=len(active_members),
            distribution_status='PROCESSING',
            validation_status='SUCCESS',
            uploaded_by=session['user_id'],
            uploaded_at=datetime.utcnow(),
        )
        db.session.add(new_batch)
        db.session.flush()

        success_count = 0
        failed_count = 0

        for member in active_members:
            try:
                # Cek/buat saldo simpanan wajib
                balance_record = MemberSavingBalance.query.filter_by(
                    member_id=member.id, saving_type_id=st_wajib.id
                ).first()
                if not balance_record:
                    balance_record = MemberSavingBalance(
                        member_id=member.id, saving_type_id=st_wajib.id, balance=0
                    )
                    db.session.add(balance_record)
                    db.session.flush()

                balance_before = float(balance_record.balance)
                balance_after = balance_before + amount_per_member

                # Update saldo
                balance_record.balance = balance_after
                balance_record.last_transaction_at = datetime.utcnow()

                # Buat detail payroll
                detail = PayrollBatchDetail(
                    payroll_batch_id=new_batch.id,
                    member_id=member.id,
                    saving_type_id=st_wajib.id,
                    amount=amount_per_member,
                    distribution_status='SUCCESS'
                )
                db.session.add(detail)
                db.session.flush()

                # Buat transaksi dengan semua kolom wajib
                trx = SavingTransaction(
                    member_id=member.id,
                    payroll_batch_detail_id=detail.id,
                    saving_type_id=st_wajib.id,
                    transaction_type='DEBIT',
                    amount=amount_per_member,
                    balance_before=balance_before,
                    balance_after=balance_after,
                    transaction_source='PAYROLL',
                    reference_number="TRX-PAY-" + secrets.token_hex(6).upper(),
                    transaction_date=datetime.utcnow(),
                    transaction_status='SUCCESS',
                    processed_by=session['user_id'],
                    processed_at=datetime.utcnow(),
                    description=f'Payroll Simpanan Wajib {datetime.now().strftime("%B %Y")} - {batch_code}'
                )
                db.session.add(trx)
                success_count += 1

            except Exception as member_err:
                failed_count += 1
                print(f"[PAYROLL] Gagal anggota {member.id}: {member_err}")

        # Update status final batch
        new_batch.distribution_status = 'SUCCESS' if failed_count == 0 else 'PARTIAL'
        new_batch.success_count = success_count
        new_batch.failed_count = failed_count
        new_batch.processed_at = datetime.utcnow()

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Payroll berhasil: {success_count} anggota. Gagal: {failed_count}.',
            'batch_code': batch_code,
            'total_members': len(active_members),
            'success_count': success_count,
            'failed_count': failed_count,
            'total_amount': success_count * amount_per_member
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# API: STATISTIK REAL-TIME (untuk di-polling frontend)
# ─────────────────────────────────────────────────────────────────────────────
@finance_bp.route('/finance/payroll/stats')
def payroll_stats():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    total_payroll_this_month = db.session.query(func.sum(PayrollBatch.total_amount)).filter(
        func.extract('month', PayrollBatch.uploaded_at) == datetime.now().month,
        func.extract('year', PayrollBatch.uploaded_at) == datetime.now().year
    ).scalar() or 0

    total_batches = PayrollBatch.query.count()
    successful_distributions = PayrollBatchDetail.query.filter_by(distribution_status='SUCCESS').count()
    failed_distributions = PayrollBatchDetail.query.filter_by(distribution_status='FAILED').count()
    active_members = Member.query.filter_by(status='AKTIF').count()
    latest_batch = PayrollBatch.query.order_by(PayrollBatch.uploaded_at.desc()).first()

    return jsonify({
        'success': True,
        'total_payroll_this_month': float(total_payroll_this_month),
        'total_batches': total_batches,
        'successful_distributions': successful_distributions,
        'failed_distributions': failed_distributions,
        'active_members': active_members,
        'latest_batch_code': latest_batch.batch_code if latest_batch else None,
        'latest_batch_status': latest_batch.distribution_status if latest_batch else None,
        'latest_success_count': latest_batch.success_count if latest_batch else 0,
        'latest_failed_count': latest_batch.failed_count if latest_batch else 0,
        'latest_total_members': latest_batch.total_members if latest_batch else 0,
    })


# ─────────────────────────────────────────────────────────────────────────────
# API: DETAIL BATCH (untuk modal)
# ─────────────────────────────────────────────────────────────────────────────
@finance_bp.route('/finance/payroll/batch/<batch_code>/detail')
def batch_detail_api(batch_code):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    batch = PayrollBatch.query.filter_by(batch_code=batch_code).first()
    if not batch:
        return jsonify({'success': False, 'error': 'Batch tidak ditemukan'}), 404

    details = PayrollBatchDetail.query.filter_by(payroll_batch_id=batch.id).all()
    result = []
    for d in details:
        member = Member.query.get(d.member_id)
        result.append({
            'member_no': member.member_no if member else '-',
            'member_name': member.full_name if member else 'Unknown',
            'amount': float(d.amount),
            'status': d.distribution_status,
        })

    success_count = sum(1 for d in details if d.distribution_status == 'SUCCESS')
    failed_count = sum(1 for d in details if d.distribution_status == 'FAILED')

    return jsonify({
        'success': True,
        'batch_code': batch.batch_code,
        'period': f"Bulan {batch.period_month} Tahun {batch.period_year}",
        'total_members': batch.total_members,
        'total_amount': float(batch.total_amount),
        'success_count': success_count,
        'failed_count': failed_count,
        'distribution_status': batch.distribution_status,
        'uploaded_at': batch.uploaded_at.strftime('%d %b %Y %H:%M') if batch.uploaded_at else '-',
        'details': result
    })


# ─────────────────────────────────────────────────────────────────────────────
# SIMPANAN (LEDGER)
# ─────────────────────────────────────────────────────────────────────────────
@finance_bp.route('/finance/savings')
def savings():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    current_user = User.query.get(session['user_id'])

    total_transactions = SavingTransaction.query.count()
    total_balance = db.session.query(func.sum(MemberSavingBalance.balance)).scalar() or 0
    total_withdrawal = db.session.query(func.sum(WithdrawalRequest.amount)).filter_by(approval_status='APPROVED').scalar() or 0
    pending_review = DepositRequest.query.filter_by(approval_status='PENDING').count()

    transactions = SavingTransaction.query.order_by(SavingTransaction.transaction_date.desc()).limit(100).all()
    pending_deposits = DepositRequest.query.filter_by(approval_status='PENDING').order_by(DepositRequest.created_at.desc()).all()

    return render_template('ledger.html',
                           current_user=current_user,
                           active_menu='savings',
                           page_title='Simpanan Anggota',
                           total_transactions=total_transactions,
                           total_balance=float(total_balance),
                           total_withdrawal=float(total_withdrawal),
                           pending_review=pending_review,
                           transactions=transactions,
                           pending_deposits=pending_deposits)

@finance_bp.route('/finance/deposit/<int:deposit_id>/approve', methods=['POST'])
def approve_deposit(deposit_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        deposit = DepositRequest.query.get(deposit_id)
        if not deposit or deposit.approval_status != 'PENDING':
            return jsonify({'success': False, 'error': 'Deposit tidak valid atau sudah diproses'}), 400
            
        amount = float(deposit.amount)
        
        balance_record = MemberSavingBalance.query.filter_by(
            member_id=deposit.member_id, saving_type_id=deposit.saving_type_id
        ).first()
        if not balance_record:
            balance_record = MemberSavingBalance(
                member_id=deposit.member_id, saving_type_id=deposit.saving_type_id, balance=0
            )
            db.session.add(balance_record)
            db.session.flush()

        balance_before = float(balance_record.balance)
        balance_after = balance_before + amount

        balance_record.balance = balance_after
        balance_record.last_transaction_at = datetime.utcnow()
        
        trx = SavingTransaction(
            member_id=deposit.member_id,
            saving_type_id=deposit.saving_type_id,
            transaction_type='DEBIT',
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            transaction_source='DEPOSIT',
            reference_number="TRX-DEP-" + secrets.token_hex(6).upper(),
            transaction_date=datetime.utcnow(),
            transaction_status='SUCCESS',
            processed_by=session['user_id'],
            processed_at=datetime.utcnow(),
            source_bank=deposit.source_bank,
            source_account=deposit.source_account_no,
            description=f'Setoran Simpanan Mandiri via Aplikasi'
        )
        db.session.add(trx)
        
        deposit.approval_status = 'APPROVED'
        deposit.approved_by = session['user_id']
        deposit.approved_at = datetime.utcnow()
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'Setoran berhasil disetujui.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@finance_bp.route('/finance/deposit/<int:deposit_id>/reject', methods=['POST'])
def reject_deposit(deposit_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    try:
        deposit = DepositRequest.query.get(deposit_id)
        if not deposit or deposit.approval_status != 'PENDING':
            return jsonify({'success': False, 'error': 'Deposit tidak valid atau sudah diproses'}), 400
            
        data = request.get_json() or {}
        reason = data.get('reason', 'Ditolak oleh Admin')
        
        deposit.approval_status = 'REJECTED'
        deposit.rejection_reason = reason
        deposit.approved_by = session['user_id']
        deposit.approved_at = datetime.utcnow()
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'Setoran berhasil ditolak.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# EXCEL PAYROLL UPLOAD & TEMPLATE
# ─────────────────────────────────────────────────────────────────────────────
import pandas as pd
import io
from flask import send_file

@finance_bp.route('/finance/payroll/download_template')
def download_payroll_template():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
        
    active_members = Member.query.filter_by(status='AKTIF').all()
    data = []
    for m in active_members:
        data.append({
            'member_no': m.member_no,
            'member_name': m.full_name,
            'saving_type_code': 'SW', # Default Wajib
            'amount': 500000          # Default 500k
        })
        
    df = pd.DataFrame(data)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Payroll_Template')
        
    output.seek(0)
    filename = f"Template_Payroll_{datetime.now().strftime('%Y%m%d')}.xlsx"
    
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

@finance_bp.route('/finance/payroll/upload_process', methods=['POST'])
def upload_process_payroll():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'Tidak ada file yang diunggah'}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'File kosong'}), 400
        
    try:
        df = pd.read_excel(file)
        
        # Validasi kolom
        required_cols = ['member_no', 'saving_type_code', 'amount']
        for col in required_cols:
            if col not in df.columns:
                return jsonify({'success': False, 'error': f'Kolom {col} tidak ditemukan di Excel.'}), 400
                
        # Cek apakah bulan ini sudah ada batch dari upload (opsional, bisa di skip jika boleh multiple batch)
        # Kita ijinkan multiple batch untuk Excel, karena bisa beda-beda anggota.
        
        total_amount = df['amount'].sum()
        total_members = len(df)
        batch_code = "PRX-" + datetime.now().strftime("%Y%m") + "-" + secrets.token_hex(2).upper()
        
        new_batch = PayrollBatch(
            batch_code=batch_code,
            period_month=datetime.now().month,
            period_year=datetime.now().year,
            total_amount=total_amount,
            total_members=total_members,
            distribution_status='PROCESSING',
            validation_status='SUCCESS',
            uploaded_by=session['user_id'],
            uploaded_at=datetime.utcnow(),
        )
        db.session.add(new_batch)
        db.session.flush()
        
        success_count = 0
        failed_count = 0
        
        # Pre-fetch saving types to optimize
        saving_types = {st.code: st.id for st in SavingType.query.all()}
        
        for index, row in df.iterrows():
            try:
                member_no = str(row['member_no']).strip()
                st_code = str(row['saving_type_code']).strip()
                amount = float(row['amount'])
                
                member = Member.query.filter_by(member_no=member_no).first()
                if not member:
                    raise Exception(f"Anggota {member_no} tidak ditemukan.")
                    
                if st_code not in saving_types:
                    raise Exception(f"Kode simpanan {st_code} tidak valid.")
                
                st_id = saving_types[st_code]
                
                balance_record = MemberSavingBalance.query.filter_by(
                    member_id=member.id, saving_type_id=st_id
                ).first()
                if not balance_record:
                    balance_record = MemberSavingBalance(
                        member_id=member.id, saving_type_id=st_id, balance=0
                    )
                    db.session.add(balance_record)
                    db.session.flush()

                balance_before = float(balance_record.balance)
                balance_after = balance_before + amount

                balance_record.balance = balance_after
                balance_record.last_transaction_at = datetime.utcnow()

                detail = PayrollBatchDetail(
                    payroll_batch_id=new_batch.id,
                    member_id=member.id,
                    saving_type_id=st_id,
                    amount=amount,
                    distribution_status='SUCCESS'
                )
                db.session.add(detail)
                db.session.flush()

                trx = SavingTransaction(
                    member_id=member.id,
                    payroll_batch_detail_id=detail.id,
                    saving_type_id=st_id,
                    transaction_type='DEBIT',
                    amount=amount,
                    balance_before=balance_before,
                    balance_after=balance_after,
                    transaction_source='PAYROLL',
                    reference_number="TRX-PAYX-" + secrets.token_hex(6).upper(),
                    transaction_date=datetime.utcnow(),
                    transaction_status='SUCCESS',
                    processed_by=session['user_id'],
                    processed_at=datetime.utcnow(),
                    description=f'Payroll Simpanan {st_code} via Excel - {batch_code}'
                )
                db.session.add(trx)
                success_count += 1
                
            except Exception as row_err:
                failed_count += 1
                print(f"[EXCEL PAYROLL] Baris {index+2} gagal: {row_err}")
                
                # Still create a failed detail log
                if 'member' in locals() and member:
                    detail = PayrollBatchDetail(
                        payroll_batch_id=new_batch.id,
                        member_id=member.id,
                        saving_type_id=saving_types.get(st_code, None),
                        amount=row.get('amount', 0),
                        distribution_status='FAILED'
                    )
                    db.session.add(detail)
        
        new_batch.distribution_status = 'SUCCESS' if failed_count == 0 else 'PARTIAL'
        new_batch.success_count = success_count
        new_batch.failed_count = failed_count
        new_batch.processed_at = datetime.utcnow()

        db.session.commit()
        return jsonify({
            'success': True,
            'message': f'Payroll Excel berhasil diproses. Sukses: {success_count}, Gagal: {failed_count}.',
            'batch_code': batch_code,
            'success_count': success_count,
            'failed_count': failed_count
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

# ─────────────────────────────────────────────────────────────────────────────
# PENARIKAN
# ─────────────────────────────────────────────────────────────────────────────
@finance_bp.route('/finance/withdrawals')
def withdrawals():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    current_user = User.query.get(session['user_id'])

    reqs = WithdrawalRequest.query.order_by(WithdrawalRequest.request_date.desc()).all()
    stats = {
        'pending': WithdrawalRequest.query.filter_by(approval_status='PENDING').count(),
        'approved_today': WithdrawalRequest.query.filter_by(approval_status='APPROVED').count(),
        'completed': WithdrawalRequest.query.filter_by(approval_status='COMPLETED').count(),
        'rejected': WithdrawalRequest.query.filter_by(approval_status='REJECTED').count()
    }
    return render_template('withdrawal.html', current_user=current_user, withdrawals=reqs, stats=stats,
                           active_menu='withdrawals', page_title='Penarikan Simpanan')
