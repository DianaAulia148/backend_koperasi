from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, send_file
from datetime import datetime
import pandas as pd
import io

economic_bp = Blueprint('economic', __name__, url_prefix='/economic')

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
                           active_menu='economic_overview',
                           latest_inflasi=latest_inflasi,
                           latest_birate=latest_birate,
                           latest_jisdor=latest_jisdor,
                           latest_pangan=latest_pangan,
                           all_inflasi=inflasi_data,
                           all_birate=birate_data,
                           all_jisdor=jisdor_data,
                           page_title='Economic Overview')

@economic_bp.route('/inflation')
def inflation():
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    from utils.bi_scraper import fetch_inflasi
    data = fetch_inflasi(start_date, end_date)
    return render_template('economic/inflation.html',
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
            
    else:
        return "Invalid indicator", 400
        
    df = pd.DataFrame(df_list)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Data')
    output.seek(0)
    
    return send_file(output, download_name=filename, as_attachment=True, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
