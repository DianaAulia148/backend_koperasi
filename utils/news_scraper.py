import feedparser
import logging
import requests
from datetime import datetime
from utils.bi_scraper import get_mongo_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RSS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# ─────────────────────────────────────────────────────────────────────────────
# KATA KUNCI WAJIB — artikel HARUS mengandung minimal satu kata kunci ini
# Fokus: data ekonomi Indonesia (rupiah, inflasi, BI rate, harga pangan, dll.)
# ─────────────────────────────────────────────────────────────────────────────
REQUIRED_KEYWORDS = [
    # Nilai Tukar & Kurs
    'rupiah', 'kurs', 'jisdor', 'dolar', 'usd/idr', 'idr',
    # Bank Indonesia & Kebijakan Moneter
    'bi rate', 'bi-rate', 'bank indonesia', 'suku bunga', 'kebijakan moneter',
    'repo rate', 'rrr', 'giro wajib',
    # Inflasi & Harga
    'inflasi', 'deflasi', 'harga pangan', 'harga bahan pokok', 'bahan pangan',
    'harga sembako', 'harga beras', 'harga minyak goreng', 'harga cabai',
    'harga telur', 'harga ayam', 'pangan', 'pasokan pangan',
    # Data Ekonomi Makro Indonesia
    'ekonomi indonesia', 'pertumbuhan ekonomi', 'pdb indonesia', 'gdp indonesia',
    'apbn', 'defisit anggaran', 'utang negara',
    'cadangan devisa', 'neraca perdagangan', 'ekspor impor', 'surplus neraca',
    'bps indonesia', 'statistik nasional',
    # Pasar Modal & Investasi Indonesia
    'ihsg', 'bursa efek indonesia', 'bei', 'pasar saham indonesia',
    # BUMN & Fiskal Nasional
    'pertamina', 'pln', 'bumn', 'subsidi bbm', 'subsidi energi', 'harga bbm',
]

# ─────────────────────────────────────────────────────────────────────────────
# KATA KUNCI PEMBLOKIR — artikel dengan kata kunci ini akan DIBUANG
# ─────────────────────────────────────────────────────────────────────────────
BLOCK_KEYWORDS = [
    'bola', 'piala', 'gol', 'final', 'liga', 'pertandingan',
    'sepak bola', 'basket', 'tenis', 'badminton', 'voli',
    'seleb', 'artis', 'selebgram', 'viral', 'drakor', 'drama',
    'film', 'musik', 'konser', 'fashion', 'resep', 'kuliner',
    'nuklir meledak', 'perang', 'militer', 'senjata',
    'crypto mining', 'bitcoin scam', 'hoaks',
]

# ─────────────────────────────────────────────────────────────────────────────
# SUMBER RSS — kanal Market & Umum CNBC Indonesia
# ─────────────────────────────────────────────────────────────────────────────
RSS_SOURCES = [
    {
        "url": "https://www.cnbcindonesia.com/market/rss",
        "source": "CNBC Indonesia - Market",
    },
    {
        "url": "https://www.cnbcindonesia.com/rss",
        "source": "CNBC Indonesia",
    },
]


def _extract_thumbnail(entry):
    """Ekstrak URL thumbnail dari berbagai format RSS."""
    if hasattr(entry, 'enclosures') and entry.enclosures:
        href = entry.enclosures[0].get('href', '')
        if href:
            return href
    if hasattr(entry, 'media_content') and entry.media_content:
        url = entry.media_content[0].get('url', '')
        if url:
            return url
    if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
        url = entry.media_thumbnail[0].get('url', '')
        if url:
            return url
    return ""


def _is_economy_related(title: str, description: str) -> bool:
    """
    Artikel lolos HANYA jika:
    1. Mengandung minimal satu REQUIRED_KEYWORD
    2. Tidak mengandung satu pun BLOCK_KEYWORD
    """
    text = (title + " " + description).lower()
    if any(bk in text for bk in BLOCK_KEYWORDS):
        return False
    return any(rk in text for rk in REQUIRED_KEYWORDS)


def fetch_and_store_news():
    db = get_mongo_db()
    if db is None:
        logger.error("[NewsScraper] MongoDB connection failed.")
        return

    col = db["news_articles"]
    inserted_count = 0
    skipped_count = 0

    for source_info in RSS_SOURCES:
        rss_url = source_info["url"]
        source_name = source_info["source"]

        logger.info(f"[NewsScraper] Fetching: {rss_url}")
        try:
            r = requests.get(rss_url, headers=RSS_HEADERS, timeout=15)
            feed = feedparser.parse(r.text)
        except Exception as e:
            logger.error(f"[NewsScraper] Failed to fetch {rss_url}: {e}")
            continue

        if not feed.entries:
            logger.warning(f"[NewsScraper] No entries found in {rss_url}")
            continue

        for entry in feed.entries:
            link = entry.get("link", "")
            if not link:
                continue

            title = entry.get("title", "")
            description = entry.get("summary", "")

            # Filter ketat: hanya berita ekonomi Indonesia yang relevan
            if not _is_economy_related(title, description):
                skipped_count += 1
                continue

            # Skip jika sudah ada di database
            if col.find_one({"link": link}):
                continue

            pub_date_str = entry.get("published", "")
            thumbnail_url = _extract_thumbnail(entry)

            try:
                from email.utils import parsedate_to_datetime
                pub_date_dt = parsedate_to_datetime(pub_date_str) if pub_date_str else datetime.now()
            except Exception:
                pub_date_dt = datetime.now()

            col.insert_one({
                "title": title,
                "link": link,
                "description": description,
                "pub_date_str": pub_date_str,
                "pub_date_dt": pub_date_dt,
                "thumbnail_url": thumbnail_url,
                "source": source_name,
                "created_at": datetime.now()
            })
            inserted_count += 1

    logger.info(
        f"[NewsScraper] Done. Inserted: {inserted_count}, "
        f"Skipped (non-economy): {skipped_count}"
    )

    # Simpan maks 100 artikel, hapus yang paling lama
    total = col.count_documents({})
    if total > 100:
        excess = total - 100
        oldest = list(col.find().sort("pub_date_dt", 1).limit(excess))
        ids = [a["_id"] for a in oldest]
        if ids:
            col.delete_many({"_id": {"$in": ids}})
            logger.info(f"[NewsScraper] Cleaned up {len(ids)} old articles.")
