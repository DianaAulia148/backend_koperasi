from flask import Blueprint, render_template, request, redirect, url_for, session, send_file, jsonify
from models.user_model import db, User, MemberSavingBalance, SavingTransaction, PayrollBatch, WithdrawalRequest
from sqlalchemy import func, case
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
    
    # Get filter parameters
    period = request.args.get('period', '')
    category = request.args.get('category', '')
    withdrawals_only = request.args.get('withdrawals_only', '') in ['1', 'true', 'yes', 'on']

    # Monthly period filter
    if not period:
        period_dt = datetime.now().replace(day=1)
        period = period_dt.strftime('%Y-%m')
    else:
        try:
            period_dt = datetime.strptime(period, '%Y-%m')
        except:
            period_dt = datetime.now().replace(day=1)
            period = period_dt.strftime('%Y-%m')

    start_dt = period_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if period_dt.month == 12:
        next_month = period_dt.replace(year=period_dt.year + 1, month=1, day=1)
    else:
        next_month = period_dt.replace(month=period_dt.month + 1, day=1)
    end_dt = next_month - timedelta(seconds=1)

    start_date = start_dt.strftime('%Y-%m-%d')
    end_date = end_dt.strftime('%Y-%m-%d')

    # Summary Cards
    total_balance = db.session.query(func.sum(MemberSavingBalance.balance)).scalar() or 0

    base_tx_filters = [
        SavingTransaction.deleted_at.is_(None),
        SavingTransaction.transaction_status == 'SUCCESS',
        SavingTransaction.transaction_date >= start_dt,
        SavingTransaction.transaction_date <= end_dt
    ]

    if category and category != 'SEMUA':
        try:
            cat_id = int(category)
            base_tx_filters.append(SavingTransaction.saving_type_id == cat_id)
        except ValueError:
            cat_id = None

    filtered_tx_filters = list(base_tx_filters)
    if withdrawals_only:
        filtered_tx_filters.extend([
            SavingTransaction.transaction_type == 'CREDIT',
            SavingTransaction.transaction_source == 'WITHDRAWAL'
        ])

    debit_filters = list(filtered_tx_filters) + [SavingTransaction.transaction_type == 'DEBIT']
    credit_filters = list(filtered_tx_filters) + [SavingTransaction.transaction_type == 'CREDIT']

    payroll_batch_filters = [
        PayrollBatch.deleted_at.is_(None),
        PayrollBatch.uploaded_at >= start_dt,
        PayrollBatch.uploaded_at <= end_dt
    ]

    total_payroll = db.session.query(func.sum(PayrollBatch.total_amount)).filter(
        *payroll_batch_filters
    ).scalar() or 0
    total_withdrawal = db.session.query(func.sum(SavingTransaction.amount)).filter(
        *filtered_tx_filters,
        SavingTransaction.transaction_type == 'CREDIT',
        SavingTransaction.transaction_source == 'WITHDRAWAL'
    ).scalar() or 0
    total_pemasukan = db.session.query(func.sum(SavingTransaction.amount)).filter(
        *debit_filters
    ).scalar() or 0
    total_pengeluaran = db.session.query(func.sum(SavingTransaction.amount)).filter(
        *credit_filters
    ).scalar() or 0

    # Fetch all saving types for dynamic columns
    from models.user_model import SavingType, Member
    saving_types = SavingType.query.all()

    # Load member balances and monthly transactions
    search_query = request.args.get('search', '').strip()
    members_query = Member.query.filter(Member.deleted_at.is_(None))
    if search_query:
        members_query = members_query.filter(Member.full_name.ilike(f'%{search_query}%'))
    members = members_query.order_by(Member.full_name.asc()).all()
    member_ids = [m.id for m in members]

    balance_by_member = {}
    if member_ids:
        balances = MemberSavingBalance.query.filter(MemberSavingBalance.member_id.in_(member_ids)).all()
        for b in balances:
            balance_by_member.setdefault(b.member_id, {})[b.saving_type_id] = float(b.balance)

    tx_filters = list(base_tx_filters)
    if withdrawals_only:
        tx_filters.extend([
            SavingTransaction.transaction_type == 'CREDIT',
            SavingTransaction.transaction_source == 'WITHDRAWAL'
        ])

    monthly_tx = db.session.query(
        SavingTransaction.member_id,
        SavingTransaction.transaction_type,
        func.sum(SavingTransaction.amount)
    ).filter(*tx_filters).group_by(
        SavingTransaction.member_id,
        SavingTransaction.transaction_type
    ).all()

    monthly_by_member = {}
    for member_id, tx_type, amount in monthly_tx:
        monthly_by_member.setdefault(member_id, {'DEBIT': 0, 'CREDIT': 0})
        monthly_by_member[member_id][tx_type] = float(amount or 0)

    report_rows = []
    for m in members:
        balances = balance_by_member.get(m.id, {})
        report_rows.append({
            'member': m,
            'balances': balances,
            'total_balance': sum(balances.values()),
            'pemasukan': monthly_by_member.get(m.id, {}).get('DEBIT', 0),
            'pengeluaran': monthly_by_member.get(m.id, {}).get('CREDIT', 0)
        })

    total_transactions = db.session.query(func.count(SavingTransaction.id)).filter(*tx_filters).scalar() or 0

    full_type_totals = {str(st.id): 0 for st in saving_types}
    for row in report_rows:
        for st_id, amount in row['balances'].items():
            full_type_totals[str(st_id)] = full_type_totals.get(str(st_id), 0) + amount

    full_pemasukan = total_pemasukan
    full_pengeluaran = total_pengeluaran
    recent_tx = report_rows
    
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
                           full_pemasukan=float(full_pemasukan),
                           full_pengeluaran=float(full_pengeluaran),
                           full_type_totals=full_type_totals,
                           recent_tx=recent_tx,
                           start_date=start_date,
                           end_date=end_date,
                           period=period,
                           category=category,
                           withdrawals_only=withdrawals_only,
                           search_query=search_query,
                           saving_types=saving_types,
                           insights=insights,
                           active_menu='finance_reports',
                           page_title='Laporan Keuangan')
@report_bp.route('/export/transactions/pdf')
def export_transactions_pdf():
    """Generate a single‑page PDF summarising totals and recent transactions (max 20)."""
    total_balance = db.session.query(func.sum(MemberSavingBalance.balance)).scalar() or 0
    total_payroll = db.session.query(func.sum(PayrollBatch.total_amount)).scalar() or 0
    total_withdrawal = db.session.query(func.sum(SavingTransaction.amount)).filter(
        SavingTransaction.transaction_type == 'CREDIT',
        SavingTransaction.transaction_source == 'WITHDRAWAL',
        SavingTransaction.transaction_status == 'SUCCESS',
        SavingTransaction.deleted_at.is_(None)
    ).scalar() or 0
    total_transactions = db.session.query(func.count(SavingTransaction.id)).filter(
        SavingTransaction.deleted_at.is_(None)
    ).scalar() or 0
    recent_tx = SavingTransaction.query.filter(SavingTransaction.deleted_at.is_(None)).order_by(SavingTransaction.transaction_date.desc()).limit(20).all()

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
    recent_tx = SavingTransaction.query.filter(SavingTransaction.deleted_at.is_(None)).order_by(SavingTransaction.transaction_date.desc()).limit(1000).all()
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


@report_bp.route('/reports/finance/reset', methods=['POST'])
def reset_financial_data():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
        
    try:
        from models.user_model import SavingTransaction, PayrollBatchDetail, PayrollBatch, MemberSavingBalance, WithdrawalRequest
        
        # Hapus semua transaksi simpanan
        db.session.query(SavingTransaction).delete()
        # Hapus semua batch payroll
        db.session.query(PayrollBatchDetail).delete()
        db.session.query(PayrollBatch).delete()
        # Hapus/reset request penarikan
        db.session.query(WithdrawalRequest).delete()
        
        # Reset saldo anggota menjadi 0
        db.session.query(MemberSavingBalance).update({MemberSavingBalance.balance: 0.0})
        
        db.session.commit()
        return jsonify({'success': True, 'message': 'Database transaksi & saldo berhasil dibersihkan!'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

