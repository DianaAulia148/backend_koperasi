import sys
sys.path.insert(0, '.')

from utils.bi_scraper import get_mongo_db
from utils.news_scraper import fetch_and_store_news

# 1. Hapus semua artikel lama yang tidak relevan
db = get_mongo_db()
col = db["news_articles"]
deleted = col.delete_many({})
print(f"Deleted {deleted.deleted_count} old articles from MongoDB.")

# 2. Jalankan scraper baru dengan filter ketat
print("\nRunning scraper with strict economy filter...")
fetch_and_store_news()

# 3. Tampilkan hasil
count = col.count_documents({})
print(f"\nTotal economy articles in DB: {count}")
articles = list(col.find({}, {'_id': 0, 'title': 1, 'thumbnail_url': 1}).sort('pub_date_dt', -1).limit(10))
for i, a in enumerate(articles, 1):
    title = a.get('title', '')[:75]
    thumb = 'YES' if a.get('thumbnail_url') else 'NO'
    print(f"  {i:2}. [{thumb}] {title}")
