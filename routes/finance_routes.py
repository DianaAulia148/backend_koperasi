from flask import Blueprint, render_template, request, redirect, url_for, session
from models.user_model import db, User, MemberSavingBalance, SavingTransaction, PayrollBatch, WithdrawalRequest, DepositRequest

finance_bp = Blueprint('finance', __name__)

@finance_bp.route('/finance/payroll')
def payroll():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    current_user = User.query.get(session['user_id'])
    return render_template('payroll.html', current_user=current_user, active_menu='payroll', page_title='Payroll Automation')

@finance_bp.route('/finance/savings')
def savings():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    current_user = User.query.get(session['user_id'])
    
    # Standard Ledger Data
    total_transactions = SavingTransaction.query.count()
    total_balance = db.session.query(db.func.sum(MemberSavingBalance.balance)).scalar() or 0
    total_withdrawal = db.session.query(db.func.sum(WithdrawalRequest.amount)).filter_by(approval_status='APPROVED').scalar() or 0
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

@finance_bp.route('/finance/withdrawals')
def withdrawals():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    current_user = User.query.get(session['user_id'])
    
    # Simple list for placeholder
    reqs = WithdrawalRequest.query.order_by(WithdrawalRequest.request_date.desc()).all()
    stats = {
        'pending': WithdrawalRequest.query.filter_by(approval_status='PENDING').count(),
        'approved_today': WithdrawalRequest.query.filter_by(approval_status='APPROVED').count(), # Simplified
        'completed': WithdrawalRequest.query.filter_by(approval_status='COMPLETED').count(),
        'rejected': WithdrawalRequest.query.filter_by(approval_status='REJECTED').count()
    }
    return render_template('withdrawal.html', current_user=current_user, withdrawals=reqs, stats=stats, active_menu='withdrawals', page_title='Penarikan Simpanan')
