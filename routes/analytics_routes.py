from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from models.user_model import db, SavingTransaction, MemberSavingBalance, SavingType, Member, PayrollBatch, EconomicIndicator
from datetime import datetime, timedelta
from sqlalchemy import func

analytics_bp = Blueprint('analytics', __name__, url_prefix='/analytics')

@analytics_bp.before_request
def check_auth():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

@analytics_bp.route('/saving-trend')
def saving_trend():
    # Header Cards Data
    total_balance = db.session.query(func.sum(MemberSavingBalance.balance)).scalar() or 0
    total_tx = SavingTransaction.query.count()
    active_members = Member.query.filter_by(status='AKTIF').count()
    
    # Growth calculation (Mock for now, compare this month vs last month)
    growth_pct = 12.5 # Mock
    
    # Chart Data: Monthly Aggregation
    # In real world: query SavingTransaction grouped by month
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun']
    trend_data = [450, 520, 480, 610, 750, 890] # In millions
    
    # Distribution Data (Donut Chart)
    distribution = [
        {'name': 'Simpanan Wajib', 'value': 45},
        {'name': 'Simpanan Pokok', 'value': 25},
        {'name': 'Simpanan Sukarela', 'value': 20},
        {'name': 'Lainnya', 'value': 10}
    ]
    
    return render_template('analytics/saving_trend.html', 
                           active_menu='analytics_saving',
                           total_balance=total_balance,
                           total_tx=total_tx,
                           active_members=active_members,
                           growth_pct=growth_pct,
                           months=months,
                           trend_data=trend_data,
                           distribution=distribution,
                           page_title='Trend Simpanan')

@analytics_bp.route('/economic-analysis')
def economic_analysis():
    # Financial Health Score
    health_score = 85
    health_status = 'Stabil' # Stabil, Aman, Waspada, Risiko Tinggi
    
    # Radar Chart Data
    radar_labels = ['Stabilitas Simpanan', 'Frekuensi Penarikan', 'Konsistensi Payroll', 'Aktivitas Finansial', 'Risiko Finansial']
    radar_values = [90, 70, 85, 80, 20]
    
    return render_template('analytics/economic_analysis.html',
                           active_menu='analytics_economic',
                           health_score=health_score,
                           health_status=health_status,
                           radar_labels=radar_labels,
                           radar_values=radar_values,
                           page_title='Analisis Ekonomi')

@analytics_bp.route('/payroll')
def payroll_analytics():
    # Summary
    batches = PayrollBatch.query.order_by(PayrollBatch.uploaded_at.desc()).all()
    total_payroll = sum([b.total_amount for b in batches]) if batches else 0
    
    return render_template('analytics/payroll_analytics.html',
                           active_menu='analytics_payroll',
                           batches=batches,
                           total_payroll=total_payroll,
                           page_title='Payroll Analytics')

@analytics_bp.route('/financial-insight')
def financial_insight():
    # Top Analytics
    top_savers = db.session.query(Member.full_name, MemberSavingBalance.balance)\
        .join(MemberSavingBalance)\
        .order_by(MemberSavingBalance.balance.desc())\
        .limit(5).all()
        
    return render_template('analytics/financial_insight.html',
                           active_menu='analytics_insight',
                           top_savers=top_savers,
                           page_title='Financial Insight')

@analytics_bp.route('/economic-correlation')
def economic_correlation():
    from utils.bi_scraper import fetch_inflasi
    from sqlalchemy import func, extract
    
    # Ambil 6 bulan terakhir dari data inflasi scraping BI
    inflasi_data = fetch_inflasi()
    
    months = []
    inflation_values = []
    withdrawal_values = []
    
    # Data inflasi dibalik karena dari scraper terbaru di atas, kita butuh chronological untuk chart
    for item in reversed(inflasi_data[:6]):
        try:
            m_str = item.get('periode_str', '')
            if not m_str: continue
            
            # Extract month name for label (e.g. "April 2026" -> "Apr")
            m_label = m_str[:3]
            months.append(m_label)
            
            inflasi_val = float(item.get('inflasi_persen', 0))
            inflation_values.append(inflasi_val)
            
            # Dapatkan Withdrawal total untuk bulan yang sama dari DB Koperasi
            # Karena periode_str formatnya "Bulan Tahun", kita harus mapping ke angka bulan
            # Tapi untuk simplicity, kita hitung mundur 6 bulan dari sekarang
        except:
            pass

    # Fallback jika scraping gagal
    if not months:
        months = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun']
        inflation_values = [3.2, 3.5, 4.1, 4.8, 4.2, 3.8]

    # Ambil real withdrawal data 6 bulan terakhir
    now = datetime.utcnow()
    withdrawal_values = []
    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']
    
    chart_months = []
    for i in range(5, -1, -1):
        target_date = now - timedelta(days=30 * i)
        m = target_date.month
        y = target_date.year
        chart_months.append(month_names[m - 1])
        
        withdrawal_total = db.session.query(func.sum(SavingTransaction.amount)).filter(
            SavingTransaction.transaction_type == 'CREDIT',
            SavingTransaction.transaction_source == 'WITHDRAWAL',
            extract('month', SavingTransaction.transaction_date) == m,
            extract('year', SavingTransaction.transaction_date) == y
        ).scalar() or 0
        withdrawal_values.append(float(withdrawal_total) / 1000000) # Dalam Juta Rp

    # Insight Dinamis
    latest_inflation = inflation_values[-1] if inflation_values else 0
    insight_1 = f"Inflasi saat ini <strong>{latest_inflation}%</strong>."
    if latest_inflation > 4.0:
        insight_1 += " Inflasi tinggi memicu kenaikan penarikan."
    else:
        insight_1 += " Inflasi stabil, penarikan normal."

    return render_template('analytics/economic_correlation.html',
                           active_menu='analytics_correlation',
                           months=chart_months,
                           inflation_values=inflation_values[-6:] if len(inflation_values) >= 6 else inflation_values,
                           withdrawal_values=withdrawal_values,
                           insight_1=insight_1,
                           page_title='Economic Correlation')
