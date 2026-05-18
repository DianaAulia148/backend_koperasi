from flask import Blueprint, render_template, request, redirect, url_for, session
from models.user_model import db, User, MemberSavingBalance, SavingTransaction, PayrollBatch, WithdrawalRequest
from sqlalchemy import func
from datetime import datetime, timedelta

report_bp = Blueprint('report', __name__)

@report_bp.route('/reports/finance')
def finance_dashboard():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
        
    current_user = User.query.get(session['user_id'])
    
    # Summary Cards
    total_balance = db.session.query(func.sum(MemberSavingBalance.balance)).scalar() or 0
    total_payroll = db.session.query(func.sum(PayrollBatch.total_amount)).scalar() or 0
    total_withdrawal = db.session.query(func.sum(WithdrawalRequest.amount)).filter(WithdrawalRequest.approval_status == 'APPROVED').scalar() or 0
    total_transactions = db.session.query(func.count(SavingTransaction.id)).scalar() or 0
    
    # Get filter parameters
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    category = request.args.get('category', '')
    
    # Default to current month if no dates provided
    if not start_date and not end_date:
        today = datetime.now()
        start_date = today.replace(day=1).strftime('%Y-%m-%d')
        end_date = today.strftime('%Y-%m-%d')
    
    # Fetch all saving types for dynamic columns and filter
    from models.user_model import SavingType, Member
    saving_types = SavingType.query.all()
    
    # Base query for transactions
    tx_query = SavingTransaction.query.order_by(SavingTransaction.transaction_date.desc())
    
    from datetime import datetime as dt_class, time

    if start_date:
        try:
            start_dt = dt_class.strptime(start_date, '%Y-%m-%d')
            tx_query = tx_query.filter(SavingTransaction.transaction_date >= start_dt)
        except: pass
    if end_date:
        try:
            end_dt = dt_class.strptime(end_date, '%Y-%m-%d')
            end_dt = dt_class.combine(end_dt, time(23, 59, 59))
            tx_query = tx_query.filter(SavingTransaction.transaction_date <= end_dt)
        except: pass
            
    if category and category != 'SEMUA':
        try:
            cat_id = int(category)
            tx_query = tx_query.filter_by(saving_type_id=cat_id)
        except: pass
            
    # Use a join to fetch member names efficiently and increase limit
    recent_tx = tx_query.join(Member, SavingTransaction.member_id == Member.id)\
                        .with_entities(SavingTransaction, Member.full_name)\
                        .limit(1000).all()
    
    # Format the data for the template
    formatted_tx = []
    for tx, name in recent_tx:
        tx.member_name = name
        formatted_tx.append(tx)
    recent_tx = formatted_tx
    
    # Insights (Dummy AI Logic)
    insights = [
        "Distribusi payroll meningkat 12% bulan ini dibandingkan bulan lalu.",
        "Tren penarikan cukup stabil dalam 2 minggu terakhir.",
        "Simpanan Wajib merupakan penyumbang saldo terbesar (65%)."
    ]
    
    return render_template('reports/financial_reports.html',
                           current_user=current_user,
                           total_balance=total_balance,
                           total_payroll=total_payroll,
                           total_withdrawal=total_withdrawal,
                           total_transactions=total_transactions,
                           recent_tx=recent_tx,
                           start_date=start_date,
                           end_date=end_date,
                           category=category,
                           saving_types=saving_types,
                           insights=insights,
                           active_menu='finance_reports',
                           page_title='Laporan Keuangan')
