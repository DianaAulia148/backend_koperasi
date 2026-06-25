from flask import Blueprint, render_template, request, redirect, url_for, session, send_file
from models.user_model import db, User, MemberSavingBalance, SavingTransaction, PayrollBatch, WithdrawalRequest
from sqlalchemy import func
from datetime import datetime, timedelta
import io
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

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
    
    # Actual Insights Calculation
    insights = []
    
    today = datetime.now()
    first_day_this_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # Calculate previous month's first day
    if today.month == 1:
        first_day_last_month = today.replace(year=today.year-1, month=12, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        first_day_last_month = today.replace(month=today.month-1, day=1, hour=0, minute=0, second=0, microsecond=0)
        
    # 1. Payroll Distribution Comparison
    payroll_this_month = db.session.query(func.sum(PayrollBatch.total_amount)).filter(
        PayrollBatch.uploaded_at >= first_day_this_month
    ).scalar() or 0
    payroll_last_month = db.session.query(func.sum(PayrollBatch.total_amount)).filter(
        PayrollBatch.uploaded_at >= first_day_last_month,
        PayrollBatch.uploaded_at < first_day_this_month
    ).scalar() or 0
    
    if payroll_last_month > 0:
        payroll_diff = ((payroll_this_month - payroll_last_month) / payroll_last_month) * 100
        direction = "meningkat" if payroll_diff > 0 else "menurun"
        insights.append(f"Distribusi payroll {direction} {abs(payroll_diff):.1f}% bulan ini dibandingkan bulan lalu.")
    elif payroll_this_month > 0:
        insights.append(f"Distribusi payroll bulan ini tercatat sebesar Rp {payroll_this_month:,.0f}.")
        
    # 2. Saving Type Contribution
    if total_balance > 0:
        st_wajib = saving_types[0] if saving_types else None
        if st_wajib:
            wajib_total = db.session.query(func.sum(MemberSavingBalance.balance)).filter_by(
                saving_type_id=st_wajib.id
            ).scalar() or 0
            wajib_pct = (wajib_total / total_balance) * 100
            insights.append(f"Simpanan {st_wajib.name} memberikan kontribusi {wajib_pct:.1f}% dari total saldo.")
            
    if not insights:
        insights.append("Belum cukup data transaksi untuk menghasilkan ringkasan (insights).")
    
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
@report_bp.route('/export/transactions/pdf')
def export_transactions_pdf():
    """Generate a single‑page PDF summarising totals and recent transactions (max 20)."""
    total_balance = db.session.query(func.sum(MemberSavingBalance.balance)).scalar() or 0
    total_payroll = db.session.query(func.sum(PayrollBatch.total_amount)).scalar() or 0
    total_withdrawal = db.session.query(func.sum(WithdrawalRequest.amount)).filter(WithdrawalRequest.approval_status == 'APPROVED').scalar() or 0
    total_transactions = db.session.query(func.count(SavingTransaction.id)).scalar() or 0
    recent_tx = SavingTransaction.query.order_by(SavingTransaction.transaction_date.desc()).limit(20).all()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []
    elements.append(Paragraph('Laporan Ringkas Transaksi', styles['Title']))
    elements.append(Spacer(1, 12))
    data = [
        ['Total Saldo', f"Rp {total_balance:,.0f}"],
        ['Total Payroll', f"Rp {total_payroll:,.0f}"],
        ['Total Penarikan', f"Rp {total_withdrawal:,.0f}"],
        ['Total Transaksi', f"{total_transactions}"]
    ]
    t = Table(data, colWidths=[150, 250])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('TEXTCOLOR', (0,0), (-1,0), colors.black),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 24))
    tx_data = [['Tanggal', 'Anggota', 'Jenis Simpanan', 'Tipe', 'Jumlah']]
    for tx in recent_tx:
        tx_data.append([
            tx.transaction_date.strftime('%Y-%m-%d'),
            getattr(tx, 'member_name', ''),
            getattr(tx, 'saving_type_name', ''),
            tx.transaction_type,
            f"Rp {tx.amount:,.0f}"
        ])
    tx_table = Table(tx_data, colWidths=[80, 100, 100, 60, 80])
    tx_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
    ]))
    elements.append(Paragraph('Transaksi Terbaru (max 20)', styles['Heading2']))
    elements.append(tx_table)
    doc.build(elements)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name='transaksi_ringkas.pdf', mimetype='application/pdf')

@report_bp.route('/export/transactions/excel')
def export_transactions_excel():
    """Export recent transactions to an Excel file (up to 1000 rows)."""
    recent_tx = SavingTransaction.query.order_by(SavingTransaction.transaction_date.desc()).limit(1000).all()
    rows = []
    for tx in recent_tx:
        rows.append({
            'Tanggal': tx.transaction_date,
            'Anggota': getattr(tx, 'member_name', ''),
            'Saving Type ID': tx.saving_type_id,
            'Tipe': tx.transaction_type,
            'Jumlah': tx.amount,
            'Status': tx.transaction_status,
        })
    df = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Transaksi')
    output.seek(0)
    return send_file(output, as_attachment=True, download_name='transaksi.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
