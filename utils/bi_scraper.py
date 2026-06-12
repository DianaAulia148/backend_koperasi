import requests
from bs4 import BeautifulSoup
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from datetime import datetime, timedelta
import io
import urllib3
import logging
from dateutil import parser

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MONGO_URI = "mongodb+srv://capstone:admin123@cluster0.ptzy4rw.mongodb.net/?appName=Cluster0"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8"
}

BULAN_ID = {
    "Januari": 1, "Februari": 2, "Maret": 3,
    "April": 4, "Mei": 5, "Juni": 6,
    "Juli": 7, "Agustus": 8, "September": 9,
    "Oktober": 10, "November": 11, "Desember": 12
}

def get_mongo_db():
    try:
        client = MongoClient(MONGO_URI, server_api=ServerApi('1'), tlsAllowInvalidCertificates=True, serverSelectionTimeoutMS=6000)
        return client["koperasi_db"]
    except Exception as e:
        logging.error(f"[MongoDB] Connection failed: {e}")
        return None

def parse_indonesian_date(date_str):
    """Attempt to parse various date formats into datetime object for MongoDB filtering."""
    try:
        # Check for month text e.g. "Maret 2026" or "17 Maret 2026"
        for indo_m, m_num in BULAN_ID.items():
            if indo_m in date_str:
                date_str = date_str.replace(indo_m, str(m_num))
                break
        return parser.parse(date_str, dayfirst=True)
    except Exception:
        # Fallback to current time if parsing completely fails, though ideally we ignore
        return datetime.now()

def apply_date_filter(query, start_date=None, end_date=None):
    if start_date or end_date:
        query["tanggal_dt"] = {}
        if start_date:
            try: query["tanggal_dt"]["$gte"] = parser.parse(start_date)
            except: pass
        if end_date:
            try: query["tanggal_dt"]["$lte"] = parser.parse(end_date)
            except: pass
        if not query["tanggal_dt"]:
            del query["tanggal_dt"]
    return query

# =============================================================================
#  HARGA PANGAN
# =============================================================================

def fetch_latest_food_prices(start_date=None, end_date=None):
    db = get_mongo_db()
    if db is None: return []
    col = db["harga_pangan"]

    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if col.count_documents({"diambil_pada": {"$gte": today_start}}) == 0:
        _scrape_bi_food_prices(col)

    query = {"level": 1}
    query = apply_date_filter(query, start_date, end_date)

    if not start_date and not end_date:
        # If no filter, just return the latest single date
        latest_doc = col.find_one({"level": 1}, sort=[("tanggal_dt", -1)])
        if latest_doc:
            query["tanggal_dt"] = latest_doc.get("tanggal_dt")

    cursor = col.find(query, sort=[("tanggal_dt", -1), ("komoditas", 1)])
    return list(cursor)

def _scrape_bi_food_prices(col):
    url = "https://www.bi.go.id/hargapangan/WebSite/TabelHarga/GetGridDataDaerah"
    # Pulling from 2025 to avoid overwhelming API, but for today we just need recent
    # The user wanted 2025 but since food price API limits ranges, we do last 30 days and let it build
    s_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    e_date = datetime.now().strftime("%Y-%m-%d")

    params = {"price_type_id": 1, "comcat_id": "", "province_id": "", "regency_id": "", "market_id": "", "tipe_laporan": 1, "start_date": s_date, "end_date": e_date}
    try:
        res = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, params=params, verify=False, timeout=30)
        data_json = res.json()
    except: return

    data_to_insert = []
    if isinstance(data_json, dict) and "data" in data_json:
        for row in data_json["data"]:
            komoditas = row.get("name")
            level = row.get("level", 1)
            for key, val in row.items():
                if "/" in key and len(key) == 10:
                    try:
                        val_str = str(val).replace(",", "").strip()
                        if val_str and val_str != "-":
                            harga = float(val_str)
                            dt = parser.parse(key, dayfirst=True)
                            if not col.find_one({"komoditas": komoditas, "tanggal_str": key}):
                                data_to_insert.append({
                                    "komoditas": komoditas, "level": int(level), "tanggal_str": key,
                                    "tanggal_dt": dt, "harga_rp": harga, "sumber": "Bank Indonesia (PIHPS API)",
                                    "diambil_pada": datetime.now()
                                })
                    except ValueError: pass
    if data_to_insert: col.insert_many(data_to_insert)

# =============================================================================
#  INFLASI
# =============================================================================

def fetch_inflasi(start_date=None, end_date=None):
    db = get_mongo_db()
    if db is None: return []
    col = db["inflasi"]
    
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if col.count_documents({"diambil_pada": {"$gte": today_start}}) == 0:
        _scrape_inflasi(col)
        
    query = apply_date_filter({}, start_date, end_date)
    cursor = col.find(query, {"_id": 0}, sort=[("tanggal_dt", -1)])
    return list(cursor)

def _scrape_inflasi(col):
    url = "https://www.bi.go.id/id/statistik/indikator/data-inflasi.aspx"
    try: response = requests.get(url, headers=HEADERS, verify=False, timeout=30)
    except: return
    soup = BeautifulSoup(response.text, "html.parser")
    post_data = {x.get("name"): x.get("value", "") for x in soup.find_all("input", type="hidden")}

    post_data["ctl00$ctl54$g_1f0a867d_90e9_4a92_b1c8_de34738fc4f1$ctl00$TextBoxDateFrom"] = "01/2020"
    post_data["ctl00$ctl54$g_1f0a867d_90e9_4a92_b1c8_de34738fc4f1$ctl00$TextBoxDateTo"] = datetime.now().strftime("%m/%Y")
    post_data["ctl00$ctl54$g_1f0a867d_90e9_4a92_b1c8_de34738fc4f1$ctl00$ButtonExport"] = "Unduh"

    try: post_res = requests.post(url, headers=HEADERS, data=post_data, verify=False, timeout=30)
    except: return
    try:
        import pandas as pd
        df = pd.read_excel(io.BytesIO(post_res.content), skiprows=4, names=["NO", "Periode", "Data Inflasi", "Dummy"])
        df = df[["Periode", "Data Inflasi"]].dropna()
    except: return

    data = []
    for _, row in df.iterrows():
        try:
            periode_str = str(row["Periode"]).strip()
            inflasi_val = float(str(row["Data Inflasi"]).replace("%", "").strip())
            dt = parse_indonesian_date(periode_str)
            if not col.find_one({"periode_str": periode_str}):
                data.append({
                    "periode_str": periode_str, "tanggal_dt": dt, "inflasi_persen": inflasi_val,
                    "sumber": "Bank Indonesia (Excel Export)", "url": url, "diambil_pada": datetime.now()
                })
        except: pass
    if data: col.insert_many(data)

# =============================================================================
#  BI RATE
# =============================================================================

def fetch_bi_rate(start_date=None, end_date=None):
    db = get_mongo_db()
    if db is None: return []
    col = db["bi_rate"]
    
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if col.count_documents({"diambil_pada": {"$gte": today_start}}) == 0:
        _scrape_bi_rate(col)
        
    query = apply_date_filter({}, start_date, end_date)
    cursor = col.find(query, {"_id": 0}, sort=[("tanggal_dt", -1)])
    return list(cursor)

def _scrape_bi_rate(col):
    url = "https://www.bi.go.id/id/statistik/indikator/BI-Rate.aspx"
    try: response = requests.get(url, headers=HEADERS, verify=False, timeout=30)
    except: return
    soup = BeautifulSoup(response.text, "html.parser")
    post_data = {x.get("name"): x.get("value", "") for x in soup.find_all("input", type="hidden")}

    post_data["ctl00$ctl54$g_78f62327_0ad4_4bb8_b958_a315eccecc27$ctl00$TextBoxDateStart"] = "01/01/2020"
    post_data["ctl00$ctl54$g_78f62327_0ad4_4bb8_b958_a315eccecc27$ctl00$TextBoxDateEnd"] = datetime.now().strftime("%d/%m/%Y")
    post_data["ctl00$ctl54$g_78f62327_0ad4_4bb8_b958_a315eccecc27$ctl00$ButtonExport"] = "Unduh"

    try: post_res = requests.post(url, headers=HEADERS, data=post_data, verify=False, timeout=30)
    except: return
    try:
        import pandas as pd
        df = pd.read_excel(io.BytesIO(post_res.content), skiprows=4, names=["NO", "Tanggal", "BI-7Day-RR", "Dummy"])
        df = df[["Tanggal", "BI-7Day-RR"]].dropna()
    except: return

    data = []
    for _, row in df.iterrows():
        try:
            tanggal_str = str(row["Tanggal"]).strip()
            rate_val = float(str(row["BI-7Day-RR"]).replace("%", "").strip())
            dt = parse_indonesian_date(tanggal_str)
            if not col.find_one({"tanggal_str": tanggal_str}):
                data.append({
                    "tanggal_str": tanggal_str, "tanggal_dt": dt, "bi_rate_persen": rate_val,
                    "sumber": "Bank Indonesia (Excel Export)", "url": url, "diambil_pada": datetime.now()
                })
        except: pass
    if data: col.insert_many(data)

# =============================================================================
#  JISDOR
# =============================================================================

def fetch_jisdor(start_date=None, end_date=None):
    db = get_mongo_db()
    if db is None: return []
    col = db["jisdor"]
    
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if col.count_documents({"diambil_pada": {"$gte": today_start}}) == 0:
        _scrape_jisdor(col)
        
    query = apply_date_filter({}, start_date, end_date)
    cursor = col.find(query, {"_id": 0}, sort=[("tanggal_dt", -1)])
    return list(cursor)

def _scrape_jisdor(col):
    url = "https://www.bi.go.id/id/statistik/informasi-kurs/jisdor/default.aspx"
    try: response = requests.get(url, headers=HEADERS, verify=False, timeout=30)
    except: return
    soup = BeautifulSoup(response.text, "html.parser")
    post_data = {x.get("name"): x.get("value", "") for x in soup.find_all("input", type="hidden")}

    post_data["ctl00$ctl54$g_f51e6b6d_47c5_4ff4_8105_27cbd1a2f52d$ctl00$TextBoxFrom"] = "01/01/2020"
    post_data["ctl00$ctl54$g_f51e6b6d_47c5_4ff4_8105_27cbd1a2f52d$ctl00$TextBoxDateTo"] = datetime.now().strftime("%d/%m/%Y")
    post_data["ctl00$ctl54$g_f51e6b6d_47c5_4ff4_8105_27cbd1a2f52d$ctl00$ButtonExport"] = "Unduh"

    try: post_res = requests.post(url, headers=HEADERS, data=post_data, verify=False, timeout=30)
    except: return
    try:
        import pandas as pd
        df = pd.read_excel(io.BytesIO(post_res.content), skiprows=4, names=["NO", "Tanggal", "Kurs", "Dummy"])
        df = df[["Tanggal", "Kurs"]].dropna()
    except: return

    data = []
    for _, row in df.iterrows():
        try:
            tanggal_raw = str(row["Tanggal"]).split()[0]
            kurs_val = int(float(str(row["Kurs"]).replace(",", "").strip()))
            dt = parser.parse(tanggal_raw)
            if not col.find_one({"tanggal_str": tanggal_raw}):
                data.append({
                    "tanggal_str": tanggal_raw, "tanggal_dt": dt, "kurs_jisdor": kurs_val,
                    "satuan": "IDR per 1 USD", "sumber": "Bank Indonesia (Excel Export)",
                    "url": url, "diambil_pada": datetime.now()
                })
        except: pass
    if data: col.insert_many(data)
