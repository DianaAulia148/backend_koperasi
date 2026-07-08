from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, send_file
from datetime import datetime
import pandas as pd
import io

economic_bp = Blueprint('economic', __name__, url_prefix='/economic')

def _get_last_update():
    try:
        from utils.bi_scraper import get_scrape_metadata
        from datetime import datetime
        meta = get_scrape_metadata()
        last_dt = meta.get("_pipeline_summary", {}).get("last_scraped_at")
        
        # Cek apakah data belum ditarik hari ini (kadaluarsa)
        if not last_dt or last_dt.date() < datetime.now().date():
            # Trigger scraper di background agar halaman tetap loading cepat
            from utils.scheduler import run_daily_scraping_job
            import threading
            threading.Thread(target=run_daily_scraping_job, daemon=True).start()
            
            # Langsung kembalikan waktu sekarang (seolah-olah baru ditarik)
            return datetime.now().strftime("%d %b %Y, %H:%M WIB")
            
        if last_dt:
            return last_dt.strftime("%d %b %Y, %H:%M WIB")
    except Exception as e:
        pass
    return "Belum tersedia"

@economic_bp.before_request
def check_auth():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

@economic_bp.route('/overview')
def overview():
    from utils.bi_scraper import fetch_inflasi, fetch_bi_rate, fetch_jisdor, fetch_latest_food_prices
    
    inflasi_data = fetch_inflasi()
    birate_data = fetch_bi_rate()
    jisdor_data = fetch_jisdor()
    pangan_data = fetch_latest_food_prices()
    
    latest_inflasi = inflasi_data[0] if inflasi_data else None
    latest_birate  = birate_data[0]  if birate_data  else None
    latest_jisdor  = jisdor_data[0]  if jisdor_data  else None
    latest_pangan  = pangan_data[0]  if pangan_data  else None
    
    return render_template('economic/overview.html', 
                           last_updated=_get_last_update(),
                           active_menu='economic_overview',
                           latest_inflasi=latest_inflasi,
                           latest_birate=latest_birate,
                           latest_jisdor=latest_jisdor,
                           latest_pangan=latest_pangan,
                           all_inflasi=inflasi_data,
                           all_birate=birate_data,
                           all_jisdor=jisdor_data,
                           all_pangan=pangan_data,
                           page_title='Economic Overview')

@economic_bp.route('/inflation')
def inflation():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    from utils.bi_scraper import fetch_inflasi
    data = fetch_inflasi(start_date, end_date)
    return render_template('economic/inflation.html',
                           last_updated=_get_last_update(),
                           active_menu='economic_inflation',
                           data=data,
                           start_date=start_date,
                           end_date=end_date,
                           page_title='Inflasi Nasional')

@economic_bp.route('/bi-rate')
def bi_rate():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    from utils.bi_scraper import fetch_bi_rate
    data = fetch_bi_rate(start_date, end_date)
    return render_template('economic/bi_rate.html',
                           last_updated=_get_last_update(),
                           active_menu='economic_bi_rate',
                           data=data,
                           start_date=start_date,
                           end_date=end_date,
                           page_title='BI Rate Monitoring')

@economic_bp.route('/jisdor')
def jisdor():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    from utils.bi_scraper import fetch_jisdor
    data = fetch_jisdor(start_date, end_date)
    return render_template('economic/jisdor.html',
                           last_updated=_get_last_update(),
                           active_menu='economic_jisdor',
                           data=data,
                           start_date=start_date,
                           end_date=end_date,
                           page_title='Kurs JISDOR (USD/IDR)')

@economic_bp.route('/food-prices')
def food_prices():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    from utils.bi_scraper import fetch_latest_food_prices
    data = fetch_latest_food_prices(start_date, end_date)
    return render_template('economic/food_prices.html',
                           last_updated=_get_last_update(),
                           active_menu='economic_food_prices',
                           data=data,
                           start_date=start_date,
                           end_date=end_date,
                           page_title='Harga Bahan Pangan (BI)')

@economic_bp.route('/export/<indicator>')
def export_excel(indicator):
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    from utils.bi_scraper import fetch_inflasi, fetch_bi_rate, fetch_jisdor, fetch_latest_food_prices
    
    df_list = []
    filename = f"Export_{indicator}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    
    if indicator == 'inflasi':
        data = fetch_inflasi(start_date, end_date)
        for i, row in enumerate(data, 1):
            df_list.append({"NO": i, "Periode": row.get('periode_str'), "Inflasi (%)": row.get('inflasi_persen'), "Sumber": row.get('sumber')})
    
    elif indicator == 'bi_rate':
        data = fetch_bi_rate(start_date, end_date)
        for i, row in enumerate(data, 1):
            df_list.append({"NO": i, "Tanggal": row.get('tanggal_str'), "BI Rate (%)": row.get('bi_rate_persen'), "Sumber": row.get('sumber')})
            
    elif indicator == 'jisdor':
        data = fetch_jisdor(start_date, end_date)
        for i, row in enumerate(data, 1):
            df_list.append({"NO": i, "Tanggal": row.get('tanggal_str'), "Kurs (IDR/USD)": row.get('kurs_jisdor'), "Sumber": row.get('sumber')})
            
    elif indicator == 'food_prices':
        data = fetch_latest_food_prices(start_date, end_date)
        for i, row in enumerate(data, 1):
            df_list.append({"NO": i, "Tanggal": row.get('tanggal_str'), "Komoditas": row.get('komoditas'), "Harga (Rp)": row.get('harga_rp'), "Sumber": row.get('sumber')})
            
    elif indicator == 'correlation':
        from models.user_model import db, SavingTransaction
        from sqlalchemy import func
        import calendar
        from datetime import timedelta
        
        end_dt = datetime.now()
        if end_date:
            try: end_dt = datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            except ValueError: pass
        start_dt = end_dt - timedelta(days=30 * 6)
        if start_date:
            try: start_dt = datetime.strptime(start_date, '%Y-%m-%d').replace(hour=0, minute=0, second=0)
            except ValueError: pass
            
        inflasi_data_exp = fetch_inflasi(start_date=start_dt, end_date=end_dt)
        birate_data_exp = fetch_bi_rate(start_date=start_dt, end_date=end_dt)
        
        inflasi_map_exp = {}
        for item in inflasi_data_exp:
            dt = item.get('tanggal_dt')
            if dt: inflasi_map_exp[f"{dt.month}-{dt.year}"] = float(item.get('inflasi_persen', 0))
        birate_map_exp = {}
        for item in birate_data_exp:
            dt = item.get('tanggal_dt')
            if dt: birate_map_exp[f"{dt.month}-{dt.year}"] = float(item.get('bi_rate_persen', 0))
                
        months_list = []
        current_dt = start_dt.replace(day=1)
        end_month_start = end_dt.replace(day=1)
        limit = 24
        while current_dt <= end_month_start and limit > 0:
            months_list.append((current_dt.month, current_dt.year))
            if current_dt.month == 12: current_dt = current_dt.replace(year=current_dt.year + 1, month=1)
            else: current_dt = current_dt.replace(month=current_dt.month + 1)
            limit -= 1
            
        MN = ['Jan','Feb','Mar','Apr','Mei','Jun','Jul','Agu','Sep','Okt','Nov','Des']
        lki, lkb = 0.0, 0.0
        for i, (m, y) in enumerate(months_list, 1):
            key = f"{m}-{y}"
            iv = inflasi_map_exp.get(key, lki)
            if key in inflasi_map_exp: lki = iv
            bv = birate_map_exp.get(key, lkb)
            if key in birate_map_exp: lkb = bv
            _, ld = calendar.monthrange(y, m)
            bs = max(start_dt, datetime(y, m, 1, 0, 0, 0))
            be = min(end_dt, datetime(y, m, ld, 23, 59, 59))
            wt = db.session.query(func.sum(SavingTransaction.amount)).filter(
                SavingTransaction.transaction_type == 'CREDIT', SavingTransaction.transaction_source == 'WITHDRAWAL',
                SavingTransaction.transaction_date >= bs, SavingTransaction.transaction_date <= be,
                SavingTransaction.deleted_at.is_(None)).scalar() or 0
            dt_total = db.session.query(func.sum(SavingTransaction.amount)).filter(
                SavingTransaction.transaction_type == 'DEBIT', SavingTransaction.transaction_status == 'SUCCESS',
                SavingTransaction.transaction_date >= bs, SavingTransaction.transaction_date <= be,
                SavingTransaction.deleted_at.is_(None)).scalar() or 0
            wd_val, dep_val = float(wt), float(dt_total)
            nf = dep_val - wd_val
            ratio = round((wd_val / dep_val) * 100, 2) if dep_val > 0 else None
            df_list.append({"NO": i, "Periode": f"{MN[m-1]} {y}", "Inflasi (%)": iv, "BI Rate (%)": bv,
                "Simpanan (Rp)": dep_val, "Penarikan (Rp)": wd_val, "Net Flow (Rp)": nf,
                "Withdrawal Ratio (%)": ratio if ratio is not None else "-"})

    else:
        return "Invalid indicator", 400
        
    df = pd.DataFrame(df_list)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Data')
    output.seek(0)
    
    return send_file(output, download_name=filename, as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
