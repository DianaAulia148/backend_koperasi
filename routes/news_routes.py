from flask import Blueprint, jsonify
from utils.bi_scraper import get_mongo_db

news_bp = Blueprint('news', __name__, url_prefix='/api/news')

@news_bp.route('/economy', methods=['GET'])
def get_economy_news():
    db = get_mongo_db()
    if db is None:
        return jsonify({"success": False, "message": "Database connection failed", "data": []}), 500
        
    col = db["news_articles"]
    
    # Cek jika kosong, trigger scrape manual sekali (mirip BI scraper)
    if col.count_documents({}) == 0:
        from utils.news_scraper import fetch_and_store_news
        fetch_and_store_news()
        
    cursor = col.find({}, {"_id": 0}).sort("pub_date_dt", -1).limit(10)
    articles = list(cursor)
    
    return jsonify({
        "success": True,
        "message": "Articles fetched successfully",
        "data": articles
    })
