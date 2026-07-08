from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from models.user_model import db, SavingTransaction, MemberSavingBalance, SavingType, Member, PayrollBatch, PayrollBatchDetail, EconomicIndicator
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, extract, case, distinct
import logging
import calendar

logger = logging.getLogger(__name__)

analytics_bp = Blueprint('analytics', __name__, url_prefix='/analytics')

@analytics_bp.before_request
def check_auth():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

# ─────────────────────────────────────────────────────────────────────
#  HELPER: Get scrape metadata for "Last Update" display
def _get_internal_last_update():
    try:
        from models.user_model import SavingTransaction
        from datetime import datetime, timedelta
        last_tx = SavingTransaction.query.order_by(SavingTransaction.created_at.desc()).first()
        if last_tx and last_tx.created_at:
            # created_at is UTC, convert to WIB (+7)
            local_time = last_tx.created_at + timedelta(hours=7)
            return local_time.strftime("%d %b %Y, %H:%M WIB")
        return (datetime.utcnow() + timedelta(hours=7)).strftime("%d %b %Y, %H:%M WIB")
    except:
        return "Live Data"

def _get_last_update():
    """Get the last scraping timestamp for 'Last Update' badge on dashboard."""
    try:
        from utils.bi_scraper import get_scrape_metadata
        meta = get_scrape_metadata()
        summary = meta.get("_pipeline_summary", {})
        last_dt = summary.get("last_scraped_at")
        if last_dt:
            return last_dt.strftime("%d %b %Y, %H:%M WIB")
        return "Belum tersedia"
    except:
        return "Belum tersedia"

# ─────────────────────────────────────────────────────────────────────
#  API: Members list for name dropdown
# ─────────────────────────────────────────────────────────────────────
@analytics_bp.route('/members-list', endpoint='members_list')
def members_list():
    """Return list of active members {id, full_name} for dropdown."""
    members = Member.query.filter(
        Member.deleted_at == None,
        Member.status == 'AKTIF'
    ).order_by(Member.full_name).all()
    return jsonify([{'id': m.id, 'full_name': m.full_name} for m in members])

def _parse_date_filter(default_months=6):
    """Parse start_date and end_date from request parameters with fallback."""
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    import logging
    logging.info(f"[DEBUG_FILTER] Received start_date_str='{start_date_str}', end_date_str='{end_date_str}'")
    
    end_date = datetime.now()
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        except ValueError:
            logging.info(f"[DEBUG_FILTER] Failed to parse end_date_str: {end_date_str}")
            
    start_date = end_date - timedelta(days=30 * default_months)
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0)
        except ValueError:
            logging.info(f"[DEBUG_FILTER] Failed to parse start_date_str: {start_date_str}")
            
    logging.info(f"[DEBUG_FILTER] Parsed start_date={start_date}, end_date={end_date}")
    return start_date, end_date

def _generate_monthly_bins(start_date, end_date):
    """Generate list of (month, year) tuples between start_date and end_date."""
    months = []
    current = start_date.replace(day=1)
    end_month_start = end_date.replace(day=1)
    
    # Safety limit to avoid infinite loops or memory exhaust
    limit = 24
    while current <= end_month_start and limit > 0:
        months.append((current.month, current.year))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
        limit -= 1
    return months

# ─────────────────────────────────────────────────────────────────────
#  HELPER: Month names in Indonesian
# ─────────────────────────────────────────────────────────────────────
MONTH_NAMES_ID = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']


# ═════════════════════════════════════════════════════════════════════
#  1. SAVING TREND — 100% Real Data
# ═════════════════════════════════════════════════════════════════════
@analytics_bp.route('/saving-trend')
def saving_trend():
    start_date, end_date = _parse_date_filter(default_months=6)
    
    # ── Header Cards: ALL REAL ──
    total_balance = db.session.query(func.sum(MemberSavingBalance.balance)).scalar() or 0
    
    # Filter total transactions by date range
    tx_query = SavingTransaction.query.filter(SavingTransaction.deleted_at.is_(None))
    if start_date:
        tx_query = tx_query.filter(SavingTransaction.transaction_date >= start_date)
    if end_date:
        tx_query = tx_query.filter(SavingTransaction.transaction_date <= end_date)
    total_tx = tx_query.count()
    
    active_members = Member.query.filter_by(status='AKTIF').filter(Member.deleted_at.is_(None)).count()
    
    # Growth %: Real calculation (last completed month vs the month before last)
    # This prevents the "-100% growth" display at the beginning of the month when payroll is not yet processed.
    now = datetime.now()
    last_month_start = (now.replace(day=1) - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_end = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(seconds=1)
    
    prev_month_start = (last_month_start - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_month_end = last_month_start - timedelta(seconds=1)
    
    last_month_deposits = db.session.query(func.sum(SavingTransaction.amount)).filter(
        SavingTransaction.transaction_type == 'DEBIT',
        SavingTransaction.transaction_date >= last_month_start,
        SavingTransaction.transaction_date <= last_month_end,
        SavingTransaction.deleted_at.is_(None)
    ).scalar() or 0
    
    prev_month_deposits = db.session.query(func.sum(SavingTransaction.amount)).filter(
        SavingTransaction.transaction_type == 'DEBIT',
        SavingTransaction.transaction_date >= prev_month_start,
        SavingTransaction.transaction_date <= prev_month_end,
        SavingTransaction.deleted_at.is_(None)
    ).scalar() or 0
    
    if prev_month_deposits > 0:
        growth_pct = round(((float(last_month_deposits) - float(prev_month_deposits)) / float(prev_month_deposits)) * 100, 1)
    else:
        growth_pct = 0.0
    
    growth_direction = 'up' if growth_pct >= 0 else 'down'
    
    # ── Chart Data: Daily jika range ≤ 180 hari dan di-filter, Monthly jika lebih atau tidak di-filter ──
    date_range_days = (end_date - start_date).days
    is_filtered = bool(request.args.get('start_date') or request.args.get('end_date'))
    use_daily = is_filtered and (date_range_days <= 180)

    months = []
    deposit_data = []
    withdrawal_data = []

    if use_daily:
        # Per hari
        current_day = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        while current_day.date() <= end_date.date():
            day_end = current_day.replace(hour=23, minute=59, second=59)
            months.append(f"{current_day.day} {MONTH_NAMES_ID[current_day.month - 1]}")

            dep = db.session.query(func.sum(SavingTransaction.amount)).filter(
                SavingTransaction.transaction_type == 'DEBIT',
                SavingTransaction.transaction_date >= current_day,
                SavingTransaction.transaction_date <= day_end,
                SavingTransaction.deleted_at.is_(None)
            ).scalar() or 0
            deposit_data.append(round(float(dep) / 1000, 0))

            wd = db.session.query(func.sum(SavingTransaction.amount)).filter(
                SavingTransaction.transaction_type == 'CREDIT',
                SavingTransaction.transaction_date >= current_day,
                SavingTransaction.transaction_date <= day_end,
                SavingTransaction.deleted_at.is_(None)
            ).scalar() or 0
            withdrawal_data.append(round(float(wd) / 1000, 0))

            current_day += timedelta(days=1)
    else:
        # Per bulan
        bins = _generate_monthly_bins(start_date, end_date)
        for m, y in bins:
            if not is_filtered:
                months.append(MONTH_NAMES_ID[m - 1])
            else:
                months.append(f"{MONTH_NAMES_ID[m - 1]} {y}")
            _, last_day = calendar.monthrange(y, m)
            bin_start = max(start_date, datetime(y, m, 1, 0, 0, 0))
            bin_end = min(end_date, datetime(y, m, last_day, 23, 59, 59))

            dep = db.session.query(func.sum(SavingTransaction.amount)).filter(
                SavingTransaction.transaction_type == 'DEBIT',
                SavingTransaction.transaction_date >= bin_start,
                SavingTransaction.transaction_date <= bin_end,
                SavingTransaction.deleted_at.is_(None)
            ).scalar() or 0
            deposit_data.append(round(float(dep) / 1000, 0))

            wd = db.session.query(func.sum(SavingTransaction.amount)).filter(
                SavingTransaction.transaction_type == 'CREDIT',
                SavingTransaction.transaction_date >= bin_start,
                SavingTransaction.transaction_date <= bin_end,
                SavingTransaction.deleted_at.is_(None)
            ).scalar() or 0
            withdrawal_data.append(round(float(wd) / 1000, 0))
    
    # ── Distribution: Real from MemberSavingBalance + SavingType ──
    dist_query = db.session.query(
        SavingType.name,
        func.sum(MemberSavingBalance.balance)
    ).join(SavingType, MemberSavingBalance.saving_type_id == SavingType.id)\
     .group_by(SavingType.name).all()
    
    total_dist = sum([float(d[1] or 0) for d in dist_query]) if dist_query else 1
    distribution = []
    for name, balance in dist_query:
        pct = round((float(balance or 0) / total_dist) * 100, 1) if total_dist > 0 else 0
        distribution.append({'name': name, 'value': pct})
    
    if not distribution:
        distribution = [{'name': 'Belum ada data', 'value': 100}]
    
    # ── Dynamic Insights ──
    dominant_type = max(distribution, key=lambda x: x['value']) if distribution else {'name': 'N/A', 'value': 0}
    
    insights = []
    if growth_pct > 0:
        insights.append(f"Simpanan bulan lalu meningkat <strong>{abs(growth_pct)}%</strong> dibanding bulan sebelumnya.")
    elif growth_pct < 0:
        insights.append(f"Simpanan bulan lalu menurun <strong>{abs(growth_pct)}%</strong> dibanding bulan sebelumnya. Perlu perhatian khusus.")
    else:
        insights.append("Pertumbuhan simpanan stabil dibanding bulan sebelumnya.")
    
    insights.append(f"<strong>{dominant_type['name']}</strong> mendominasi dengan kontribusi <strong>{dominant_type['value']}%</strong> dari total saldo anggota.")
    
    last_updated = _get_internal_last_update()
    
    return render_template('analytics/saving_trend.html', 
                           active_menu='analytics_saving',
                           total_balance=total_balance,
                           total_tx=total_tx,
                           active_members=active_members,
                           growth_pct=abs(growth_pct),
                           growth_direction=growth_direction,
                           months=months,
                           deposit_data=deposit_data,
                           withdrawal_data=withdrawal_data,
                           distribution=distribution,
                           insights=insights,
                           last_updated=last_updated,
                           use_daily=use_daily,
                           start_date=start_date.strftime('%Y-%m-%d'),
                           end_date=end_date.strftime('%Y-%m-%d'),
                           page_title='Trend Simpanan')

# ═════════════════════════════════════════════════════════════════════
#  2. ECONOMIC ANALYSIS — Health Score + Real Charts
# ═════════════════════════════════════════════════════════════════════
# Helper to compute radar scores per member or overall
def _compute_radar_scores(member_id=None, start_date=None, end_date=None):
    """Calculate the five dimension scores.
    If member_id is provided, scores are computed only for that member.
    """
    # ── Dimension 1: Stabilitas Simpanan (30%) ──
    balance_this_month = db.session.query(func.sum(MemberSavingBalance.balance))
    if member_id is not None:
        balance_this_month = balance_this_month.filter(MemberSavingBalance.member_id == member_id)
    balance_this_month = balance_this_month.scalar() or 0
    
    deposits_query = db.session.query(func.sum(SavingTransaction.amount)).filter(
        SavingTransaction.transaction_type == 'DEBIT',
        SavingTransaction.transaction_status == 'SUCCESS',
        SavingTransaction.deleted_at.is_(None)
    )
    if member_id is not None:
        deposits_query = deposits_query.filter(SavingTransaction.member_id == member_id)
    if start_date: deposits_query = deposits_query.filter(SavingTransaction.transaction_date >= start_date)
    if end_date: deposits_query = deposits_query.filter(SavingTransaction.transaction_date <= end_date)
    deposits_this_period = deposits_query.scalar() or 0
    
    # Normalize: target Rp 500.000 per anggota per bulan
    if member_id is not None:
        active_members = 1
    else:
        active_members = Member.query.filter(Member.deleted_at == None).count() or 1
        
    n_months = max(1, int((end_date - start_date).days / 30)) if (start_date and end_date) else 6
    deposit_target = active_members * 500_000 * n_months
    stability_score = min(round((float(deposits_this_period) / deposit_target) * 100, 0), 100) if deposits_this_period else 50
    
    # ── Dimension 2: Frekuensi Penarikan (20%) ──
    tx_query = SavingTransaction.query.filter(SavingTransaction.deleted_at.is_(None))
    if member_id is not None: tx_query = tx_query.filter(SavingTransaction.member_id == member_id)
    if start_date: tx_query = tx_query.filter(SavingTransaction.transaction_date >= start_date)
    if end_date: tx_query = tx_query.filter(SavingTransaction.transaction_date <= end_date)
    total_tx_count = tx_query.count() or 1
    
    withdrawal_query = SavingTransaction.query.filter(
        SavingTransaction.transaction_type == 'CREDIT',
        SavingTransaction.transaction_source == 'WITHDRAWAL',
        SavingTransaction.deleted_at.is_(None)
    )
    if member_id is not None: withdrawal_query = withdrawal_query.filter(SavingTransaction.member_id == member_id)
    if start_date: withdrawal_query = withdrawal_query.filter(SavingTransaction.transaction_date >= start_date)
    if end_date: withdrawal_query = withdrawal_query.filter(SavingTransaction.transaction_date <= end_date)
    withdrawal_count = withdrawal_query.count()
    
    withdrawal_ratio = withdrawal_count / total_tx_count if total_tx_count > 0 else 0
    withdrawal_score = round(max(0, (1 - withdrawal_ratio) * 100), 0)
    
    # ── Dimension 3: Kondisi Ekonomi Makro (20%) ──
    economic_score = 50
    food_price_score = 50
    try:
        from utils.bi_scraper import fetch_inflasi, fetch_bi_rate, fetch_latest_food_prices
        inflasi_data = fetch_inflasi(start_date=start_date, end_date=end_date) or []
        birate_data = fetch_bi_rate(start_date=start_date, end_date=end_date) or []
        pangan_data = fetch_latest_food_prices(start_date=start_date, end_date=end_date) or []

        latest_inflasi = float(inflasi_data[0].get('inflasi_persen', 0)) if inflasi_data else None
        latest_bi_rate = float(birate_data[0].get('bi_rate_persen', 0)) if birate_data else None

        inflation_score = 50
        birate_score = 50
        if latest_inflasi is not None:
            if latest_inflasi < 3.0:
                inflation_score = 100
            elif latest_inflasi < 4.0:
                inflation_score = 85
            elif latest_inflasi < 5.0:
                inflation_score = 70
            elif latest_inflasi < 6.0:
                inflation_score = 55
            else:
                inflation_score = 35
        if latest_bi_rate is not None:
            if latest_bi_rate < 4.5:
                birate_score = 100
            elif latest_bi_rate < 5.0:
                birate_score = 85
            elif latest_bi_rate < 5.75:
                birate_score = 70
            elif latest_bi_rate < 6.5:
                birate_score = 55
            else:
                birate_score = 35

        food_price_by_date = {}
        for item in pangan_data:
            dt = item.get('tanggal_dt')
            harga = item.get('harga_rp')
            if dt is None or harga is None:
                continue
            food_price_by_date.setdefault(dt, []).append(float(harga))

        food_price_dates = sorted(food_price_by_date.keys())
        latest_food_price_avg = None
        food_price_change_pct = None
        if food_price_dates:
            latest_date = food_price_dates[-1]
            latest_food_price_avg = sum(food_price_by_date[latest_date]) / len(food_price_by_date[latest_date])
            if len(food_price_dates) > 1:
                earliest_date = food_price_dates[0]
                earliest_price_avg = sum(food_price_by_date[earliest_date]) / len(food_price_by_date[earliest_date])
                if earliest_price_avg > 0:
                    food_price_change_pct = ((latest_food_price_avg - earliest_price_avg) / earliest_price_avg) * 100

        if food_price_change_pct is not None:
            if food_price_change_pct < 2.0:
                food_price_score = 100
            elif food_price_change_pct < 4.0:
                food_price_score = 85
            elif food_price_change_pct < 6.0:
                food_price_score = 70
            elif food_price_change_pct < 8.0:
                food_price_score = 55
            else:
                food_price_score = 35
        else:
            food_price_score = 50

        economic_score = round((inflation_score * 0.45) + (birate_score * 0.35) + (food_price_score * 0.20), 0)
    except Exception:
        economic_score = 50
        food_price_score = 50

    # ── Dimension 4: Aktivitas Transaksi (15%) ──
    tx_target = (active_members * 5 * n_months)
    activity_score = min(round((total_tx_count / tx_target) * 100, 0), 100) if total_tx_count else 50
    
    # ── Dimension 5: Risiko Penarikan (10%) ──
    total_withdrawals_amount = db.session.query(func.sum(SavingTransaction.amount)).filter(
        SavingTransaction.transaction_type == 'CREDIT',
        SavingTransaction.transaction_source == 'WITHDRAWAL',
        SavingTransaction.transaction_status == 'SUCCESS',
        SavingTransaction.deleted_at.is_(None)
    )
    if member_id is not None:
        total_withdrawals_amount = total_withdrawals_amount.filter(SavingTransaction.member_id == member_id)
    if start_date: total_withdrawals_amount = total_withdrawals_amount.filter(SavingTransaction.transaction_date >= start_date)
    if end_date: total_withdrawals_amount = total_withdrawals_amount.filter(SavingTransaction.transaction_date <= end_date)
    total_withdrawals_val = total_withdrawals_amount.scalar() or 0
    
    total_balance = float(balance_this_month) if float(balance_this_month) > 0 else 1
    risk_ratio = float(total_withdrawals_val) / total_balance
    risk_score = round(max(0, min((1 - risk_ratio) * 100, 100)), 0)

    success_batches = 0
    total_batches = 0

    return {
        'labels': ['Stabilitas Simpanan', 'Frekuensi Penarikan', 'Kondisi Ekonomi Makro', 'Aktivitas Transaksi', 'Tekanan Harga Pangan', 'Risiko Penarikan'],
        'values': [int(stability_score), int(withdrawal_score), int(economic_score), int(activity_score), int(food_price_score), int(risk_score)],
        'raw_metrics': {
            'withdrawal_count': withdrawal_count,
            'total_tx_count': total_tx_count,
            'success_batches': success_batches,
            'total_batches': total_batches
        }
    }

@analytics_bp.route('/member-radar')
def member_radar():
    """Return radar data for a specific member or the average (overall) scores.
    Query param `member_id` optional. If omitted, returns the overall average scores.
    """
    member_id = request.args.get('member_id', type=int)
    start_date, end_date = _parse_date_filter(default_months=6)
    data = _compute_radar_scores(member_id, start_date, end_date)
    return jsonify(data)

@analytics_bp.route('/economic-analysis')
def economic_analysis():
    start_date, end_date = _parse_date_filter(default_months=6)
    member_id = request.args.get('member_id', type=int)
    selected_member_name = 'Semua Anggota'
    if member_id is not None:
        member = Member.query.get(member_id)
        selected_member_name = member.full_name if member else 'Anggota Tidak Ditemukan'
    
    # ── Dimension Scores (Unified for both Radar API and HTML Template) ──
    radar_data = _compute_radar_scores(member_id, start_date, end_date)
    radar_labels = radar_data['labels']
    radar_values = radar_data['values']
    
    stability_score = radar_values[0]
    withdrawal_score = radar_values[1]
    economic_score = radar_values[2]
    activity_score = radar_values[3]
    food_price_score = radar_values[4]
    risk_score = radar_values[5]
    
    raw_metrics = radar_data.get('raw_metrics', {})
    withdrawal_count = raw_metrics.get('withdrawal_count', 0)
    total_tx_count = raw_metrics.get('total_tx_count', 0)
    success_batches = raw_metrics.get('success_batches', 0)
    total_batches = raw_metrics.get('total_batches', 0)

    # ── Real savings totals like finance/savings ──
    deposit_query = db.session.query(func.sum(SavingTransaction.amount)).filter(
        SavingTransaction.transaction_type == 'DEBIT',
        SavingTransaction.transaction_status == 'SUCCESS',
        SavingTransaction.deleted_at.is_(None)
    )
    withdrawal_query = db.session.query(func.sum(SavingTransaction.amount)).filter(
        SavingTransaction.transaction_type == 'CREDIT',
        SavingTransaction.transaction_source == 'WITHDRAWAL',
        SavingTransaction.transaction_status == 'SUCCESS',
        SavingTransaction.deleted_at.is_(None)
    )
    if member_id is not None:
        deposit_query = deposit_query.filter(SavingTransaction.member_id == member_id)
        withdrawal_query = withdrawal_query.filter(SavingTransaction.member_id == member_id)
    if start_date:
        deposit_query = deposit_query.filter(SavingTransaction.transaction_date >= start_date)
        withdrawal_query = withdrawal_query.filter(SavingTransaction.transaction_date >= start_date)
    if end_date:
        deposit_query = deposit_query.filter(SavingTransaction.transaction_date <= end_date)
        withdrawal_query = withdrawal_query.filter(SavingTransaction.transaction_date <= end_date)

    total_balance_query = db.session.query(func.sum(MemberSavingBalance.balance))
    if member_id is not None:
        total_balance_query = total_balance_query.filter(MemberSavingBalance.member_id == member_id)
    total_balance = float(total_balance_query.scalar() or 0)

    total_deposits = float(deposit_query.scalar() or 0)
    total_withdrawals = float(withdrawal_query.scalar() or 0)
    net_flow = total_deposits - total_withdrawals

    trend_months = []
    deposit_values = []
    withdrawal_values = []
    bins = _generate_monthly_bins(start_date, end_date)
    is_filtered_savings = bool(request.args.get('start_date') or request.args.get('end_date'))
    for m, y in bins:
        if not is_filtered_savings:
            trend_months.append(MONTH_NAMES_ID[m - 1])
        else:
            trend_months.append(f"{MONTH_NAMES_ID[m - 1]} {y}")

        _, last_day = calendar.monthrange(y, m)
        bin_start = max(start_date, datetime(y, m, 1, 0, 0, 0))
        bin_end = min(end_date, datetime(y, m, last_day, 23, 59, 59))

        deposit_month_query = db.session.query(func.sum(SavingTransaction.amount)).filter(
            SavingTransaction.transaction_type == 'DEBIT',
            SavingTransaction.transaction_status == 'SUCCESS',
            SavingTransaction.deleted_at.is_(None),
            SavingTransaction.transaction_date >= bin_start,
            SavingTransaction.transaction_date <= bin_end
        )
        withdrawal_month_query = db.session.query(func.sum(SavingTransaction.amount)).filter(
            SavingTransaction.transaction_type == 'CREDIT',
            SavingTransaction.transaction_source == 'WITHDRAWAL',
            SavingTransaction.transaction_status == 'SUCCESS',
            SavingTransaction.deleted_at.is_(None),
            SavingTransaction.transaction_date >= bin_start,
            SavingTransaction.transaction_date <= bin_end
        )
        if member_id is not None:
            deposit_month_query = deposit_month_query.filter(SavingTransaction.member_id == member_id)
            withdrawal_month_query = withdrawal_month_query.filter(SavingTransaction.member_id == member_id)

        deposit_values.append(round(float(deposit_month_query.scalar() or 0) / 1000, 0))
        withdrawal_values.append(round(float(withdrawal_month_query.scalar() or 0) / 1000, 0))

    # ── Weighted Economic Health Score ──
    health_score = round(
        stability_score * 0.28 +
        withdrawal_score * 0.18 +
        economic_score * 0.20 +
        activity_score * 0.14 +
        food_price_score * 0.10 +
        risk_score * 0.10
    )
    health_score = max(0, min(health_score, 100))
    
    if health_score > 80:
        health_status = 'Sangat Baik'
    elif health_score > 60:
        health_status = 'Stabil'
    elif health_score > 40:
        health_status = 'Waspada'
    else:
        health_status = 'Risiko Tinggi'
    
    # ── Economic Indicator Summary (BI / Makro) ──
    from utils.bi_scraper import fetch_inflasi, fetch_bi_rate, fetch_jisdor, fetch_latest_food_prices

    inflasi_data = fetch_inflasi(start_date=start_date, end_date=end_date) or []
    birate_data = fetch_bi_rate(start_date=start_date, end_date=end_date) or []
    jurisdor_data = fetch_jisdor(start_date=start_date, end_date=end_date) or []
    pangan_data = fetch_latest_food_prices(start_date=start_date, end_date=end_date) or []
    use_scraped_data = bool(inflasi_data or birate_data or jurisdor_data or pangan_data)

    # Food price summary from scraped data
    food_price_by_date = {}
    for item in pangan_data:
        dt = item.get('tanggal_dt')
        harga = item.get('harga_rp')
        if dt is None or harga is None:
            continue
        food_price_by_date.setdefault(dt, []).append(float(harga))

    food_price_dates = sorted(food_price_by_date.keys())
    latest_food_price_avg = None
    food_price_change_pct = None
    if food_price_dates:
        latest_date = food_price_dates[-1]
        latest_food_price_avg = sum(food_price_by_date[latest_date]) / len(food_price_by_date[latest_date])
        if len(food_price_dates) > 1:
            earliest_date = food_price_dates[0]
            earliest_price_avg = sum(food_price_by_date[earliest_date]) / len(food_price_by_date[earliest_date])
            if earliest_price_avg > 0:
                food_price_change_pct = ((latest_food_price_avg - earliest_price_avg) / earliest_price_avg) * 100

    if food_price_change_pct is not None:
        if food_price_change_pct < 2.0:
            food_price_score = 100
        elif food_price_change_pct < 4.0:
            food_price_score = 85
        elif food_price_change_pct < 6.0:
            food_price_score = 70
        elif food_price_change_pct < 8.0:
            food_price_score = 55
        else:
            food_price_score = 35
    else:
        food_price_score = 50

    economic_rows_map = {}
    def add_economic_row(date_obj, label, value, source):
        if not date_obj:
            return
        key = date_obj.strftime('%d %b %Y')
        if key not in economic_rows_map:
            economic_rows_map[key] = {
                'date_obj': date_obj,
                'date': key,
                'inflation_rate': None,
                'bi_rate': None,
                'usd_idr': None,
                'source': source
            }
        economic_rows_map[key][label] = value
        if source:
            economic_rows_map[key]['source'] = source

    for item in inflasi_data:
        dt = item.get('tanggal_dt')
        if dt:
            add_economic_row(dt, 'inflation_rate', None if item.get('inflasi_persen') is None else round(float(item.get('inflasi_persen', 0)), 4), item.get('sumber') or 'Bank Indonesia')
            economic_rows_map[dt.strftime('%d %b %Y')]['inflation_rate'] = round(float(item.get('inflasi_persen', 0)), 4)

    for item in birate_data:
        dt = item.get('tanggal_dt')
        if dt:
            add_economic_row(dt, 'bi_rate', None if item.get('bi_rate_persen') is None else round(float(item.get('bi_rate_persen', 0)), 4), item.get('sumber') or 'Bank Indonesia')
            economic_rows_map[dt.strftime('%d %b %Y')]['bi_rate'] = round(float(item.get('bi_rate_persen', 0)), 4)

    for item in jurisdor_data:
        dt = item.get('tanggal_dt')
        if dt:
            add_economic_row(dt, 'usd_idr', None if item.get('kurs_jisdor') is None else round(float(item.get('kurs_jisdor', 0)), 2), item.get('sumber') or 'Bank Indonesia')
            economic_rows_map[dt.strftime('%d %b %Y')]['usd_idr'] = round(float(item.get('kurs_jisdor', 0)), 2)

    if use_scraped_data:
        economic_rows = sorted(economic_rows_map.values(), key=lambda r: r['date_obj'], reverse=True)
        latest_inflation = None
        latest_bi_rate = None
        latest_usd_idr = None
        for row in economic_rows:
            if latest_inflation is None and row.get('inflation_rate') is not None:
                latest_inflation = row.get('inflation_rate')
            if latest_bi_rate is None and row.get('bi_rate') is not None:
                latest_bi_rate = row.get('bi_rate')
            if latest_usd_idr is None and row.get('usd_idr') is not None:
                latest_usd_idr = row.get('usd_idr')
            if latest_inflation is not None and latest_bi_rate is not None and latest_usd_idr is not None:
                break
        economic_summary = {
            'latest_inflation': latest_inflation,
            'latest_bi_rate': latest_bi_rate,
            'latest_usd_idr': latest_usd_idr,
            'latest_food_price': latest_food_price_avg,
            'food_price_change_pct': round(food_price_change_pct, 2) if food_price_change_pct is not None else None,
            'avg_inflation': round(sum([row['inflation_rate'] or 0 for row in economic_rows]) / len([r for r in economic_rows if r['inflation_rate'] is not None]), 2) if any(r['inflation_rate'] is not None for r in economic_rows) else None,
            'avg_bi_rate': round(sum([row['bi_rate'] or 0 for row in economic_rows]) / len([r for r in economic_rows if r['bi_rate'] is not None]), 2) if any(r['bi_rate'] is not None for r in economic_rows) else None,
            'avg_usd_idr': round(sum([row['usd_idr'] or 0 for row in economic_rows]) / len([r for r in economic_rows if r['usd_idr'] is not None]), 2) if any(r['usd_idr'] is not None for r in economic_rows) else None,
            'count': len(economic_rows),
            'period': f"{start_date.strftime('%d %b %Y')} - {end_date.strftime('%d %b %Y')}",
            'source': 'Bank Indonesia (Scraping)'
        }
    else:
        economic_indicator_query = EconomicIndicator.query.filter(
            EconomicIndicator.date >= start_date.date(),
            EconomicIndicator.date <= end_date.date()
        ).order_by(EconomicIndicator.date.desc())
        economic_indicators = economic_indicator_query.all()
        latest_indicator = economic_indicators[0] if economic_indicators else None
        economic_rows = [
            {
                'date': indicator.date.strftime('%d %b %Y'),
                'inflation_rate': indicator.inflation_rate,
                'bi_rate': indicator.bi_rate,
                'usd_idr': indicator.usd_idr,
                'source': indicator.source
            }
            for indicator in economic_indicators
        ]
        economic_summary = {
            'latest_inflation': round(float(latest_indicator.inflation_rate), 2) if latest_indicator and latest_indicator.inflation_rate is not None else None,
            'latest_bi_rate': round(float(latest_indicator.bi_rate), 2) if latest_indicator and latest_indicator.bi_rate is not None else None,
            'latest_usd_idr': round(float(latest_indicator.usd_idr), 2) if latest_indicator and latest_indicator.usd_idr is not None else None,
            'latest_food_price': None,
            'food_price_change_pct': None,
            'avg_inflation': round(sum([i.inflation_rate or 0 for i in economic_indicators]) / len(economic_indicators), 2) if economic_indicators else None,
            'avg_bi_rate': round(sum([i.bi_rate or 0 for i in economic_indicators]) / len(economic_indicators), 2) if economic_indicators else None,
            'avg_usd_idr': round(sum([i.usd_idr or 0 for i in economic_indicators]) / len(economic_indicators), 2) if economic_indicators else None,
            'count': len(economic_indicators),
            'period': f"{start_date.strftime('%d %b %Y')} - {end_date.strftime('%d %b %Y')}",
            'source': 'Seed / Mock Data'
        }

    # ── Dynamic Recommendations ──
    recommendations = []
    
    # Get inflation data for context
    latest_inflasi = 0
    try:
        from utils.bi_scraper import fetch_inflasi
        inflasi_data = fetch_inflasi()
        if inflasi_data:
            latest_inflasi = float(inflasi_data[0].get('inflasi_persen', 0))
    except:
        pass
    
    if withdrawal_score < 60:
        recommendations.append({
            'tag': 'Waspada', 'tag_class': 'warning',
            'text': f'Frekuensi penarikan tinggi ({withdrawal_count} dari {total_tx_count} transaksi). Perlu monitoring likuiditas lebih ketat.'
        })
    else:
        recommendations.append({
            'tag': 'Optimal', 'tag_class': 'success',
            'text': f'Frekuensi penarikan terkendali ({withdrawal_count} dari {total_tx_count} transaksi). Likuiditas koperasi dalam kondisi baik.'
        })
    
    if latest_inflasi > 4.0:
        recommendations.append({
            'tag': 'Perhatian', 'tag_class': 'warning',
            'text': f'Inflasi nasional saat ini <strong>{latest_inflasi}%</strong>. Inflasi tinggi berpotensi meningkatkan penarikan anggota.'
        })
    elif latest_inflasi > 0:
        recommendations.append({
            'tag': 'Stabil', 'tag_class': 'success',
            'text': f'Inflasi nasional <strong>{latest_inflasi}%</strong> dalam level terkendali. Simpanan anggota cenderung stabil.'
        })
    
    if economic_score >= 80:
        recommendations.append({
            'tag': 'Optimal', 'tag_class': 'success',
            'text': 'Kondisi ekonomi makro mendukung aktivitas simpanan dan penarikan. Indikator BI stabil.'
        })
    
    last_updated = _get_last_update()
    
    return render_template('analytics/economic_analysis.html',
                           active_menu='analytics_economic',
                           health_score=health_score,
                           health_status=health_status,
                           radar_labels=radar_labels,
                           radar_values=radar_values,
                           selected_member_name=selected_member_name,
                           total_balance=total_balance,
                           total_deposits=total_deposits,
                           total_withdrawals=total_withdrawals,
                           net_flow=net_flow,
                           trend_months=trend_months,
                           deposit_values=deposit_values,
                           withdrawal_values=withdrawal_values,
                           economic_summary=economic_summary,
                           economic_rows=economic_rows,
                           recommendations=recommendations,
                           last_updated=last_updated,
                           start_date=start_date.strftime('%Y-%m-%d'),
                           end_date=end_date.strftime('%Y-%m-%d'),
                           page_title='Analisis Ekonomi')

# ═════════════════════════════════════════════════════════════════════
#  3. PAYROLL ANALYTICS — 100% Real Data
# ═════════════════════════════════════════════════════════════════════
@analytics_bp.route('/payroll')
def payroll_analytics():
    start_date, end_date = _parse_date_filter(default_months=6)
    
    # Filter batches listed in the table by the date range
    batches_query = PayrollBatch.query.filter(PayrollBatch.deleted_at.is_(None))
    if start_date:
        batches_query = batches_query.filter(PayrollBatch.uploaded_at >= start_date)
    if end_date:
        batches_query = batches_query.filter(PayrollBatch.uploaded_at <= end_date)
    batches = batches_query.order_by(PayrollBatch.uploaded_at.desc()).all()
    
    total_payroll = sum([float(b.total_amount or 0) for b in batches]) if batches else 0
    
    # Real: unique members who received payroll in this period
    member_query = db.session.query(func.count(distinct(PayrollBatchDetail.member_id)))\
        .join(PayrollBatch, PayrollBatchDetail.payroll_batch_id == PayrollBatch.id)\
        .filter(PayrollBatch.deleted_at.is_(None))
    if start_date:
        member_query = member_query.filter(PayrollBatch.uploaded_at >= start_date)
    if end_date:
        member_query = member_query.filter(PayrollBatch.uploaded_at <= end_date)
    total_members_payroll = member_query.scalar() or 0
    
    # Real: accuracy rate from batch success ratio in this period
    total_batches = len(batches)
    success_batches = sum(1 for b in batches if b.distribution_status == 'SUCCESS')
    failed_batches = sum(1 for b in batches if b.distribution_status == 'FAILED')
    accuracy_rate = round((success_batches / total_batches) * 100, 1) if total_batches > 0 else 0
    
    # Real: Payroll trend chart (dynamically aggregation based on Date range)
    bins = _generate_monthly_bins(start_date, end_date)
    payroll_months = []
    payroll_trend = []
    payroll_trend_raw = []  # in original Rp, for analysis
    payroll_member_counts = []  # members per month, for analysis
    
    is_filtered_payroll = bool(request.args.get('start_date') or request.args.get('end_date'))
    for m, y in bins:
        if not is_filtered_payroll:
            payroll_months.append(MONTH_NAMES_ID[m - 1])
        else:
            payroll_months.append(f"{MONTH_NAMES_ID[m - 1]} {y}")
        
        # Bounded dates for this specific month bin
        _, last_day = calendar.monthrange(y, m)
        bin_start = max(start_date, datetime(y, m, 1, 0, 0, 0))
        bin_end = min(end_date, datetime(y, m, last_day, 23, 59, 59))
        
        monthly_total = db.session.query(func.sum(PayrollBatch.total_amount)).filter(
            PayrollBatch.period_month == m,
            PayrollBatch.period_year == y,
            PayrollBatch.uploaded_at >= bin_start,
            PayrollBatch.uploaded_at <= bin_end,
            PayrollBatch.deleted_at.is_(None)
        ).scalar() or 0
        payroll_trend.append(round(float(monthly_total) / 1000, 0))  # Ribu Rp
        payroll_trend_raw.append(float(monthly_total))

        monthly_members = db.session.query(func.count(distinct(PayrollBatchDetail.member_id)))\
            .join(PayrollBatch, PayrollBatchDetail.payroll_batch_id == PayrollBatch.id)\
            .filter(
                PayrollBatch.period_month == m,
                PayrollBatch.period_year == y,
                PayrollBatch.uploaded_at >= bin_start,
                PayrollBatch.uploaded_at <= bin_end,
                PayrollBatch.deleted_at.is_(None)
            ).scalar() or 0
        payroll_member_counts.append(monthly_members)

    # ── Intelligent Payroll Analysis ──
    payroll_insights = []
    payroll_warnings = []
    payroll_tips = []

    # 1. Month-over-month trend analysis
    non_zero_trend = [(payroll_months[i], payroll_trend_raw[i], payroll_member_counts[i])
                      for i in range(len(payroll_trend_raw)) if payroll_trend_raw[i] > 0]

    if len(non_zero_trend) >= 2:
        prev_label, prev_val, prev_members = non_zero_trend[-2]
        curr_label, curr_val, curr_members = non_zero_trend[-1]

        if prev_val > 0:
            delta_pct = round(((curr_val - prev_val) / prev_val) * 100, 1)
            member_delta = curr_members - prev_members

            if delta_pct > 5:
                payroll_insights.append({
                    'icon': 'trending_up',
                    'color': '#10b981',
                    'title': f'Payroll Naik {delta_pct}% ({prev_label} → {curr_label})',
                    'detail': (
                        f'Total distribusi payroll meningkat dari <strong>Rp {prev_val:,.0f}</strong> menjadi <strong>Rp {curr_val:,.0f}</strong>. '
                        + (f'Jumlah anggota penerima bertambah <strong>{member_delta} orang</strong>, kemungkinan karena ada anggota baru bergabung.' if member_delta > 0
                           else f'Jumlah anggota penerima tetap <strong>{curr_members} orang</strong>, peningkatan nominal disebabkan oleh kenaikan nominal simpanan per anggota.')
                    )
                })
            elif delta_pct < -5:
                payroll_warnings.append({
                    'icon': 'trending_down',
                    'color': '#ef4444',
                    'title': f'Payroll Turun {abs(delta_pct)}% ({prev_label} → {curr_label})',
                    'detail': (
                        f'Total distribusi payroll menurun dari <strong>Rp {prev_val:,.0f}</strong> menjadi <strong>Rp {curr_val:,.0f}</strong>. '
                        + (f'Jumlah anggota penerima berkurang <strong>{abs(member_delta)} orang</strong>. Kemungkinan penyebab: anggota tidak aktif, pengunduran diri, atau tidak diikutsertakan dalam batch bulan ini.'
                           if member_delta < 0
                           else 'Jumlah anggota penerima tetap, namun nominal berkurang. Kemungkinan ada penyesuaian nominal potongan atau anggota memilih nominal lebih kecil.')
                    )
                })
            else:
                payroll_insights.append({
                    'icon': 'horizontal_rule',
                    'color': '#f59e0b',
                    'title': f'Payroll Stabil ({prev_label} → {curr_label})',
                    'detail': f'Distribusi payroll relatif konsisten dengan perubahan <strong>{delta_pct:+.1f}%</strong>. Tidak ada fluktuasi signifikan.'
                })

    # 2. Member count anomaly across months
    non_zero_members = [c for c in payroll_member_counts if c > 0]
    if len(non_zero_members) >= 2:
        max_members = max(non_zero_members)
        min_members = min(non_zero_members)
        if max_members > 0 and (max_members - min_members) / max_members > 0.10:
            payroll_warnings.append({
                'icon': 'group_remove',
                'color': '#f59e0b',
                'title': 'Fluktuasi Jumlah Anggota Penerima Payroll',
                'detail': (
                    f'Jumlah anggota penerima bervariasi antara <strong>{min_members}</strong> hingga <strong>{max_members} orang</strong> per bulan (selisih &gt;10%). '
                    'Ini bisa mengindikasikan anggota yang tidak aktif, data payroll yang tidak lengkap untuk bulan tertentu, atau anggota yang baru bergabung / mengundurkan diri.'
                )
            })

    # 3. Failed batches warning
    if failed_batches > 0:
        payroll_warnings.append({
            'icon': 'error_outline',
            'color': '#ef4444',
            'title': f'{failed_batches} Batch Gagal Didistribusikan',
            'detail': (
                f'Terdapat <strong>{failed_batches} batch</strong> dengan status FAILED dalam periode ini. '
                'Distribusi yang gagal berarti simpanan anggota pada batch tersebut belum tercatat. '
                'Segera cek log batch dan lakukan re-distribusi atau koreksi manual.'
            )
        })

    # 4. Zero-month gap warning
    zero_months = [payroll_months[i] for i in range(len(payroll_trend_raw)) if payroll_trend_raw[i] == 0]
    if zero_months:
        payroll_warnings.append({
            'icon': 'calendar_today',
            'color': '#f59e0b',
            'title': f'Tidak Ada Payroll di {len(zero_months)} Bulan',
            'detail': (
                f'Tidak ditemukan data payroll pada: <strong>{", ".join(zero_months)}</strong>. '
                'Kemungkinan penyebab: batch belum diupload, periode libur/cuti besar, atau data belum diproses.'
            )
        })

    # 5. Accuracy rate evaluation
    if accuracy_rate == 100:
        payroll_tips.append({
            'icon': 'verified',
            'color': '#10b981',
            'title': 'Tingkat Keberhasilan Distribusi: Sempurna',
            'detail': 'Seluruh batch payroll dalam periode ini berhasil didistribusikan 100%. Sistem berjalan optimal.'
        })
    elif accuracy_rate >= 80:
        payroll_tips.append({
            'icon': 'check_circle',
            'color': '#f59e0b',
            'title': f'Tingkat Keberhasilan: {accuracy_rate}%',
            'detail': f'Sebagian besar batch berhasil, namun ada {failed_batches} batch yang gagal. Periksa batch tersebut untuk memastikan data anggota sudah tercatat dengan benar.'
        })
    elif total_batches > 0:
        payroll_tips.append({
            'icon': 'warning',
            'color': '#ef4444',
            'title': f'Tingkat Keberhasilan Rendah: {accuracy_rate}%',
            'detail': 'Tingkat keberhasilan distribusi payroll di bawah 80%. Perlu evaluasi menyeluruh terhadap proses upload dan distribusi batch.'
        })

    # 6. General tip if no issues
    if not payroll_warnings and total_batches > 0:
        payroll_tips.append({
            'icon': 'thumb_up',
            'color': '#10b981',
            'title': 'Distribusi Payroll Berjalan Lancar',
            'detail': 'Tidak ada anomali signifikan yang terdeteksi. Pastikan untuk terus memonitor konsistensi jumlah anggota dan nominal setiap bulannya.'
        })

    last_updated = _get_internal_last_update()
    
    return render_template('analytics/payroll_analytics.html',
                           active_menu='analytics_payroll',
                           batches=batches,
                           total_payroll=total_payroll,
                           total_members_payroll=total_members_payroll,
                           accuracy_rate=accuracy_rate,
                           payroll_months=payroll_months,
                           payroll_trend=payroll_trend,
                           payroll_insights=payroll_insights,
                           payroll_warnings=payroll_warnings,
                           payroll_tips=payroll_tips,
                           last_updated=last_updated,
                           start_date=start_date.strftime('%Y-%m-%d'),
                           end_date=end_date.strftime('%Y-%m-%d'),
                           page_title='Payroll Analytics')

# ═════════════════════════════════════════════════════════════════════
#  4. FINANCIAL INSIGHT — 100% Real Data
# ═════════════════════════════════════════════════════════════════════
@analytics_bp.route('/financial-insight')
def financial_insight():
    start_date, end_date = _parse_date_filter(default_months=6)
    
    # Top Savers: REAL
    top_savers = db.session.query(Member.full_name, func.sum(MemberSavingBalance.balance).label('total'))\
        .join(MemberSavingBalance)\
        .filter(Member.deleted_at.is_(None))\
        .group_by(Member.id, Member.full_name)\
        .order_by(func.sum(MemberSavingBalance.balance).desc())\
        .limit(5).all()
    
    # Top 5 Inactive Savers: REAL
    top_inactive_savers = db.session.query(Member.full_name, func.sum(MemberSavingBalance.balance).label('total'))\
        .join(MemberSavingBalance)\
        .filter(
            Member.deleted_at.is_(None),
            MemberSavingBalance.status == 'INACTIVE'
        )\
        .group_by(Member.id, Member.full_name)\
        .order_by(func.sum(MemberSavingBalance.balance).desc())\
        .limit(5).all()
    
    # Average balance per member
    avg_balance = db.session.query(func.avg(MemberSavingBalance.balance)).scalar() or 0
    
    # Peak withdrawal week analysis (filtered by date range)
    week_withdrawals = {}
    withdrawal_query = SavingTransaction.query.filter(
        SavingTransaction.transaction_type == 'CREDIT',
        SavingTransaction.transaction_source == 'WITHDRAWAL',
        SavingTransaction.deleted_at.is_(None)
    )
    if start_date:
        withdrawal_query = withdrawal_query.filter(SavingTransaction.transaction_date >= start_date)
    if end_date:
        withdrawal_query = withdrawal_query.filter(SavingTransaction.transaction_date <= end_date)
    withdrawal_txs = withdrawal_query.all()
    
    for tx in withdrawal_txs:
        if tx.transaction_date:
            week_num = min((tx.transaction_date.day - 1) // 7 + 1, 4)
            week_withdrawals[week_num] = week_withdrawals.get(week_num, 0) + 1
    
    peak_week = max(week_withdrawals, key=lambda k: week_withdrawals[k]) if week_withdrawals else 4
    peak_week_count = week_withdrawals.get(peak_week, 0)
    
    # Dynamic Recommendations
    recommendations = []
    
    total_inactive = sum([float(s[1] or 0) for s in top_inactive_savers]) if top_inactive_savers else 0
    if total_inactive > 0:
        formatted_inactive = f"Rp {total_inactive:,.0f}".replace(',', '.')
        recommendations.append({
            'icon': 'pause_circle',
            'title': 'Reaktivasi Simpanan Non-Aktif',
            'text': f'Terdapat simpanan non-aktif dari 5 anggota teratas bernilai total <strong>{formatted_inactive}</strong>. Disarankan untuk menghubungi anggota guna program reaktivasi saldo.'
        })
    else:
        recommendations.append({
            'icon': 'check_circle',
            'title': 'Status Simpanan Anggota',
            'text': 'Semua simpanan anggota terdeteksi aktif. Koperasi berjalan dalam kapasitas operasional penuh yang optimal.'
        })
    
    recommendations.append({
        'icon': 'alarm_on',
        'title': 'Peak Withdrawal Time',
        'text': f'Data menunjukkan penarikan tunai memuncak pada <strong>minggu ke-{peak_week}</strong> setiap bulan ({peak_week_count} transaksi). Pastikan cadangan kas memadai.'
    })
    
    return render_template('analytics/financial_insight.html',
                           active_menu='analytics_finance',
                           last_updated=_get_internal_last_update(),
                           top_savers=top_savers,
                           top_inactive_savers=top_inactive_savers,
                           avg_balance=float(avg_balance),
                           recommendations=recommendations,
                           start_date=start_date.strftime('%Y-%m-%d'),
                           end_date=end_date.strftime('%Y-%m-%d'),
                           page_title='Financial Insight')

# ═════════════════════════════════════════════════════════════════════
#  5. ECONOMIC CORRELATION — Enhanced with BI Rate
# ═════════════════════════════════════════════════════════════════════
@analytics_bp.route('/economic-correlation')
def economic_correlation():
    from utils.bi_scraper import fetch_inflasi, fetch_bi_rate, fetch_jisdor, fetch_latest_food_prices
    from sqlalchemy import func, extract
    
    start_date, end_date = _parse_date_filter(default_months=6)
    selected_indicator = request.args.get('indicator', 'inflasi')
    if selected_indicator not in ['inflasi', 'bi_rate', 'jisdor', 'food_prices']:
        selected_indicator = 'inflasi'
    
    # Ambil data dari 4 indikator ekonomi makro
    inflasi_data = fetch_inflasi(start_date=start_date, end_date=end_date)
    birate_data = fetch_bi_rate(start_date=start_date, end_date=end_date)
    jisdor_data = fetch_jisdor(start_date=start_date, end_date=end_date)
    pangan_data = fetch_latest_food_prices(start_date=start_date, end_date=end_date)
    
    # Map Inflasi
    inflasi_map = {}
    for item in inflasi_data:
        dt = item.get('tanggal_dt')
        if dt: inflasi_map[f"{dt.month}-{dt.year}"] = float(item.get('inflasi_persen', 0))
            
    # Map BI Rate
    birate_map = {}
    for item in birate_data:
        dt = item.get('tanggal_dt')
        if dt: birate_map[f"{dt.month}-{dt.year}"] = float(item.get('bi_rate_persen', 0))
            
    # Map JISDOR (rata-rata bulanan)
    jisdor_month_vals = {}
    for item in jisdor_data:
        dt = item.get('tanggal_dt')
        kurs = item.get('kurs_jisdor')
        if dt and kurs: jisdor_month_vals.setdefault(f"{dt.month}-{dt.year}", []).append(float(kurs))
    jisdor_map = {}
    for key, vals in jisdor_month_vals.items():
        if vals: jisdor_map[key] = round(sum(vals) / len(vals), 0)
            
    # Map Harga Pangan (rata-rata bulanan level 1)
    food_month_vals = {}
    for item in pangan_data:
        dt = item.get('tanggal_dt')
        price = item.get('harga_rp')
        if dt and price: food_month_vals.setdefault(f"{dt.month}-{dt.year}", []).append(float(price))
    food_map = {}
    for key, vals in food_month_vals.items():
        if vals: food_map[key] = round(sum(vals) / len(vals), 0)
            
    # Bins bulanan dinamis
    bins = _generate_monthly_bins(start_date, end_date)
    chart_months = []
    inflation_values = []
    birate_values = []
    jisdor_values = []
    food_values = []
    withdrawal_values = []
    deposit_values = []
    net_flow_values = []
    withdrawal_ratio_values = []
    
    # Get last known value helper to fallback if month doesn't exist
    last_known_inf = 0.0
    last_known_bi = 0.0
    last_known_jisdor = 15000.0
    last_known_food = 40000.0
    
    # Seasonal configuration mapping (tahun-bulan -> nama event musiman)
    seasonal_config = {
        "2025-12": "Natal & Tahun Baru",
        "2026-03": "Lebaran / Idul Fitri",
        "2026-06": "Tahun Ajaran Baru",
        "2026-07": "Tahun Ajaran Baru"
    }
    
    active_seasonal_markers = []
    
    for m, y in bins:
        chart_months.append(f"{MONTH_NAMES_ID[m - 1]} {y}")
        key = f"{m}-{y}"
        
        # Check seasonal config
        cfg_key = f"{y}-{m:02d}"
        if cfg_key in seasonal_config:
            active_seasonal_markers.append({
                'month_idx': len(chart_months) - 1,
                'event': seasonal_config[cfg_key]
            })
        
        # Get values with carry-forward fallback
        inf_val = inflasi_map.get(key, last_known_inf)
        if key in inflasi_map: last_known_inf = inf_val
        inflation_values.append(inf_val)
        
        bi_val = birate_map.get(key, last_known_bi)
        if key in birate_map: last_known_bi = bi_val
        birate_values.append(bi_val)
        
        jisdor_val = jisdor_map.get(key, last_known_jisdor)
        if key in jisdor_map: last_known_jisdor = jisdor_val
        jisdor_values.append(jisdor_val)
        
        food_val = food_map.get(key, last_known_food)
        if key in food_map: last_known_food = food_val
        food_values.append(food_val)
        
        # Ambil data transaksi bulanan
        _, last_day = calendar.monthrange(y, m)
        bin_start = max(start_date, datetime(y, m, 1, 0, 0, 0))
        bin_end = min(end_date, datetime(y, m, last_day, 23, 59, 59))
        
        withdrawal_total = db.session.query(func.sum(SavingTransaction.amount)).filter(
            SavingTransaction.transaction_type == 'CREDIT',
            SavingTransaction.transaction_source == 'WITHDRAWAL',
            SavingTransaction.transaction_date >= bin_start,
            SavingTransaction.transaction_date <= bin_end,
            SavingTransaction.deleted_at.is_(None)
        ).scalar() or 0
        
        deposit_total = db.session.query(func.sum(SavingTransaction.amount)).filter(
            SavingTransaction.transaction_type == 'DEBIT',
            SavingTransaction.transaction_status == 'SUCCESS',
            SavingTransaction.transaction_date >= bin_start,
            SavingTransaction.transaction_date <= bin_end,
            SavingTransaction.deleted_at.is_(None)
        ).scalar() or 0
        
        wd_thousand = round(float(withdrawal_total) / 1000, 0)
        dep_thousand = round(float(deposit_total) / 1000, 0)
        net_thousand = dep_thousand - wd_thousand
        
        withdrawal_values.append(wd_thousand)
        deposit_values.append(dep_thousand)
        net_flow_values.append(net_thousand)
        
        # Safe division for Withdrawal Ratio (None if deposit = 0)
        if dep_thousand > 0:
            ratio_val = round((wd_thousand / dep_thousand) * 100, 1)
        else:
            ratio_val = None
        withdrawal_ratio_values.append(ratio_val)

    # ── Detect Partial Month ──
    now = datetime.now()
    is_current_month_partial = False
    current_month_label = ""
    if bins:
        last_m, last_y = bins[-1]
        if last_m == now.month and last_y == now.year:
            # check if month is still running
            is_current_month_partial = True
            current_month_label = f"{MONTH_NAMES_ID[last_m - 1]} {last_y}"

    # ── Data Quality Meta ──
    paired_count = len([x for x in inflation_values if x is not None])
    data_quality_info = {
        'total_months': len(bins),
        'date_range': f"{start_date.strftime('%B %Y')} - {end_date.strftime('%B %Y')}",
        'is_partial': is_current_month_partial,
        'partial_month_label': current_month_label if is_current_month_partial else None,
        'paired_count': paired_count
    }

    # ── Pearson Correlation Helpers ──
    def get_lagged_pairs(x, y, lag):
        if len(x) <= lag:
            return [], []
        return x[:len(x) - lag], y[lag:]

    def pearson_correlation(x, y):
        # Filter out None values
        pairs = [(x[i], y[i]) for i in range(len(x)) if x[i] is not None and y[i] is not None]
        n = len(pairs)
        if n < 3:
            return None, n
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        num = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
        den_x = sum((xs[i] - mean_x) ** 2 for i in range(n))
        den_y = sum((ys[i] - mean_y) ** 2 for i in range(n))
        if den_x == 0 or den_y == 0:
            return 0.0, n
        r = num / ((den_x * den_y) ** 0.5)
        return round(r, 2), n

    def interpret_r(r):
        if r is None:
            return "N/A"
        abs_r = abs(r)
        if abs_r >= 0.7:
            strength = "Kuat"
        elif abs_r >= 0.3:
            strength = "Sedang"
        elif abs_r >= 0.1:
            strength = "Lemah"
        else:
            strength = "Sangat Lemah"
        
        direction = "Positif" if r >= 0 else "Negatif"
        if strength == "Sangat Lemah":
            return "Tidak terdapat korelasi berarti"
        return f"{direction} {strength}"

    # ── Dynamic Lag Limits ──
    num_obs = len(bins)
    if num_obs < 12:
        max_lag_limit = 1
    elif num_obs < 24:
        max_lag_limit = 2
    else:
        max_lag_limit = 3
    active_lags = list(range(max_lag_limit + 1))

    # ── Set Active Economic Values ──
    if selected_indicator == 'inflasi':
        active_eco_values = inflation_values
        active_eco_label = 'Inflasi (%)'
        active_eco_unit = '%'
        var_eco_name = 'Inflasi'
    elif selected_indicator == 'bi_rate':
        active_eco_values = birate_values
        active_eco_label = 'BI Rate (%)'
        active_eco_unit = '%'
        var_eco_name = 'BI Rate'
    elif selected_indicator == 'jisdor':
        active_eco_values = jisdor_values
        active_eco_label = 'Kurs JISDOR (USD/IDR)'
        active_eco_unit = ' Rp'
        var_eco_name = 'Kurs JISDOR'
    else: # food_prices
        active_eco_values = food_values
        active_eco_label = 'Harga Pangan (Rupiah)'
        active_eco_unit = ' Rp'
        var_eco_name = 'Harga Pangan'

    # ── Build Lag Correlation Table ──
    pairs_to_correlate = [
        (f'{active_eco_label} vs Net Flow', active_eco_values, net_flow_values, 'Net Flow'),
        (f'{active_eco_label} vs Nominal Simpanan', active_eco_values, deposit_values, 'Simpanan'),
        (f'{active_eco_label} vs Nominal Penarikan', active_eco_values, withdrawal_values, 'Penarikan'),
    ]

    lag_correlation_table = []
    for label, x_vals, y_vals, var_y in pairs_to_correlate:
        row = {'metric': label}
        for lag in active_lags:
            x_paired, y_paired = get_lagged_pairs(x_vals, y_vals, lag)
            r_val, n_val = pearson_correlation(x_paired, y_paired)
            row[f'lag{lag}_r'] = r_val
            row[f'lag{lag}_n'] = n_val
            row[f'lag{lag}_desc'] = interpret_r(r_val)
        lag_correlation_table.append(row)

    # ── Average Withdrawal Ratio for KPI Card ──
    valid_ratios = [r for r in withdrawal_ratio_values if r is not None]
    avg_withdrawal_ratio = round(sum(valid_ratios) / len(valid_ratios), 1) if valid_ratios else None

    # ── Build Exploratory Correlation Insights ──
    correlation_insights = []

    def make_insight(label, x_vals, y_vals, title, var_names, severity="ok"):
        best_lag = 0
        best_r = 0.0
        best_n = 0
        best_weak = True
        
        for lag in active_lags:
            x_p, y_p = get_lagged_pairs(x_vals, y_vals, lag)
            r_val, n_val = pearson_correlation(x_p, y_p)
            if r_val is not None:
                if abs(r_val) >= 0.3:
                    best_weak = False
                if abs(r_val) > abs(best_r):
                    best_r = r_val
                    best_lag = lag
                    best_n = n_val
                    
        if best_weak:
            return {
                'title': title,
                'severity': 'ok',
                'icon': 'info',
                'result': 'Hubungan Sangat Lemah',
                'r': best_r,
                'lag': best_lag,
                'n': best_n,
                'interpretation': f'Belum ditemukan hubungan linier yang kuat antara {var_names[0]} dengan {var_names[1]} pada seluruh lag yang diamati.',
                'note': 'Hasil ini menunjukkan bahwa fluktuasi jangka pendek tidak berjalan beriringan pada periode ini.'
            }
        
        dir_str = "Positif" if best_r > 0 else "Negatif"
        str_str = "Kuat" if abs(best_r) >= 0.7 else "Sedang"
        
        if var_names[1] == 'Penarikan':
            interpretation = f"Terdapat indikasi bahwa peningkatan {var_names[0]} diikuti peningkatan penarikan sekitar {best_lag} bulan setelahnya." if best_r > 0 else f"Terdapat indikasi bahwa peningkatan {var_names[0]} diikuti penurunan penarikan sekitar {best_lag} bulan setelahnya."
        elif var_names[1] == 'Net Flow':
            interpretation = f"Terdapat indikasi bahwa peningkatan {var_names[0]} diikuti peningkatan Net Flow simpanan sekitar {best_lag} bulan setelahnya." if best_r > 0 else f"Terdapat indikasi bahwa peningkatan {var_names[0]} diikuti penurunan Net Flow simpanan sekitar {best_lag} bulan setelahnya."
        elif var_names[1] == 'Simpanan':
            interpretation = f"Terdapat indikasi bahwa peningkatan {var_names[0]} diikuti peningkatan Simpanan (setoran) sekitar {best_lag} bulan setelahnya." if best_r > 0 else f"Terdapat indikasi bahwa peningkatan {var_names[0]} diikuti penurunan Simpanan (setoran) sekitar {best_lag} bulan setelahnya."
        else:
            interpretation = f"Terdapat indikasi hubungan {dir_str.lower()} yang {str_str.lower()} antara {var_names[0]} dengan {var_names[1]} dengan tenggang waktu {best_lag} bulan."
            
        return {
            'title': title,
            'severity': severity if (best_r < 0 and var_names[1] == 'Net Flow') or (best_r > 0 and var_names[1] == 'Penarikan') else 'ok',
            'icon': 'trending_up' if best_r > 0 else 'trending_down',
            'result': f"Korelasi {dir_str} {str_str}",
            'r': best_r,
            'lag': best_lag,
            'n': best_n,
            'interpretation': interpretation,
            'note': 'Belum dapat disimpulkan sebagai hubungan sebab-akibat.'
        }

    correlation_insights.append(make_insight(f'{active_eco_label} vs Net Flow', active_eco_values, net_flow_values, f'Analisis {var_eco_name} ↔ Net Flow', [var_eco_name, 'Net Flow'], severity='warning'))
    correlation_insights.append(make_insight(f'{active_eco_label} vs Nominal Simpanan', active_eco_values, deposit_values, f'Analisis {var_eco_name} ↔ Simpanan', [var_eco_name, 'Simpanan'], severity='ok'))
    correlation_insights.append(make_insight(f'{active_eco_label} vs Nominal Penarikan', active_eco_values, withdrawal_values, f'Analisis {var_eco_name} ↔ Penarikan', [var_eco_name, 'Penarikan'], severity='warning'))

    last_updated = _get_last_update()

    return render_template('analytics/economic_correlation.html',
                           active_menu='analytics_correlation',
                           months=chart_months,
                           active_eco_values=active_eco_values,
                           active_eco_label=active_eco_label,
                           active_eco_unit=active_eco_unit,
                           selected_indicator=selected_indicator,
                           withdrawal_values=withdrawal_values,
                           deposit_values=deposit_values,
                           net_flow_values=net_flow_values,
                           withdrawal_ratio_values=withdrawal_ratio_values,
                           avg_withdrawal_ratio=avg_withdrawal_ratio,
                           lag_correlation_table=lag_correlation_table,
                           correlation_insights=correlation_insights,
                           data_quality_info=data_quality_info,
                           active_seasonal_markers=active_seasonal_markers,
                           active_lags=active_lags,
                           last_updated=last_updated,
                           start_date=start_date.strftime('%Y-%m-%d'),
                           end_date=end_date.strftime('%Y-%m-%d'),
                           page_title='Economic Correlation')
