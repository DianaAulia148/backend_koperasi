from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from models.user_model import db, EconomicIndicator, RegionalSalaryData
from datetime import datetime

economic_bp = Blueprint('economic', __name__, url_prefix='/economic')

@economic_bp.before_request
def check_auth():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

@economic_bp.route('/overview')
def overview():
    latest_indicators = EconomicIndicator.query.order_by(EconomicIndicator.date.desc()).first()
    all_indicators = EconomicIndicator.query.order_by(EconomicIndicator.date.desc()).all()
    umr_data = RegionalSalaryData.query.filter_by(province='Jawa Tengah').order_by(RegionalSalaryData.umr.desc()).all()
    return render_template('economic/overview.html', 
                           active_menu='economic_overview',
                           latest=latest_indicators,
                           all_data=all_indicators,
                           umr_list=umr_data,
                           page_title='Economic Overview')

@economic_bp.route('/inflation')
def inflation():
    data = EconomicIndicator.query.filter(EconomicIndicator.inflation_rate != None).order_by(EconomicIndicator.date.desc()).all()
    return render_template('economic/indicator_detail.html',
                           active_menu='economic_inflation',
                           data=data,
                           page_title='Inflasi Nasional')

@economic_bp.route('/bi-rate')
def bi_rate():
    data = EconomicIndicator.query.filter(EconomicIndicator.bi_rate != None).order_by(EconomicIndicator.date.desc()).all()
    return render_template('economic/indicator_detail.html',
                           active_menu='economic_bi_rate',
                           data=data,
                           page_title='BI Rate Monitoring')

@economic_bp.route('/jisdor')
def jisdor():
    data = EconomicIndicator.query.filter(EconomicIndicator.usd_idr != None).order_by(EconomicIndicator.date.desc()).all()
    return render_template('economic/indicator_detail.html',
                           active_menu='economic_jisdor',
                           data=data,
                           page_title='Kurs JISDOR (USD/IDR)')

@economic_bp.route('/umr')
def umr_data():
    data = RegionalSalaryData.query.filter_by(province='Jawa Tengah').order_by(RegionalSalaryData.umr.desc()).all()
    return render_template('economic/umr.html',
                           active_menu='economic_umr',
                           data=data,
                           page_title='Data UMR Regional')
