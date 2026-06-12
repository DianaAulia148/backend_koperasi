import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
}

url = "https://www.bi.go.id/hargapangan/WebSite/TabelHarga/GetGridDataDaerah"

# Let's try province 13, 14, 15
for p_id in [10, 11, 12, 13, 14, 15, 16, 17]:
    params = {
        "price_type_id": 1,
        "comcat_id": "",
        "province_id": str(p_id),
        "regency_id": "",
        "market_id": "",
        "tipe_laporan": 1,
        "start_date": "2026-06-01",
        "end_date": "2026-06-05"
    }
    try:
        res = requests.get(url, headers=HEADERS, params=params, verify=False)
        data = res.json()
        if "data" in data and len(data["data"]) > 0:
            print(f"Province {p_id} returned data. First item: {data['data'][0].get('name')}")
    except Exception as e:
        print(f"Failed for {p_id}")

