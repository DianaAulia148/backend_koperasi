import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from utils.bi_scraper import get_mongo_db, _scrape_bi_food_prices, _scrape_inflasi, _scrape_bi_rate, _scrape_jisdor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = BackgroundScheduler()

def _update_scrape_metadata(db, source_name, status, duration_seconds=0):
    """Update scrape metadata in MongoDB for 'Last Update' display on dashboard."""
    try:
        col = db["scrape_metadata"]
        col.update_one(
            {"source": source_name},
            {"$set": {
                "source": source_name,
                "last_scraped_at": datetime.now(),
                "status": status,
                "duration_seconds": round(duration_seconds, 2),
                "scheduler_type": "APScheduler (BackgroundScheduler)",
                "schedule_config": "Daily 00:05 WIB + Hourly Interval"
            }},
            upsert=True
        )
    except Exception as e:
        logger.error(f"[Scheduler] Failed to update scrape metadata for {source_name}: {e}")

def run_daily_scraping_job():
    """Wrapper function to perform scraping on all Bank Indonesia data."""
    logger.info("Executing scheduled scraping job for Bank Indonesia data...")
    db = get_mongo_db()
    if db is None:
        logger.error("[Scheduler] Unable to establish MongoDB connection. Skipping job.")
        return
    
    job_start = datetime.now()
    
    # 1. Harga Pangan
    try:
        t0 = datetime.now()
        col_food = db["harga_pangan"]
        _scrape_bi_food_prices(col_food)
        duration = (datetime.now() - t0).total_seconds()
        _update_scrape_metadata(db, "harga_pangan", "SUCCESS", duration)
        logger.info(f"[Scheduler] Harga pangan scraped successfully in {duration:.1f}s.")
    except Exception as e:
        _update_scrape_metadata(db, "harga_pangan", f"FAILED: {str(e)[:100]}")
        logger.error(f"[Scheduler] Failed to scrape food prices: {e}")

    # 2. Inflasi
    try:
        t0 = datetime.now()
        col_inflasi = db["inflasi"]
        _scrape_inflasi(col_inflasi)
        duration = (datetime.now() - t0).total_seconds()
        _update_scrape_metadata(db, "inflasi", "SUCCESS", duration)
        logger.info(f"[Scheduler] Data inflasi scraped successfully in {duration:.1f}s.")
    except Exception as e:
        _update_scrape_metadata(db, "inflasi", f"FAILED: {str(e)[:100]}")
        logger.error(f"[Scheduler] Failed to scrape inflation: {e}")

    # 3. BI Rate
    try:
        t0 = datetime.now()
        col_bi_rate = db["bi_rate"]
        _scrape_bi_rate(col_bi_rate)
        duration = (datetime.now() - t0).total_seconds()
        _update_scrape_metadata(db, "bi_rate", "SUCCESS", duration)
        logger.info(f"[Scheduler] BI Rate scraped successfully in {duration:.1f}s.")
    except Exception as e:
        _update_scrape_metadata(db, "bi_rate", f"FAILED: {str(e)[:100]}")
        logger.error(f"[Scheduler] Failed to scrape BI Rate: {e}")

    # 4. JISDOR
    try:
        t0 = datetime.now()
        col_jisdor = db["jisdor"]
        _scrape_jisdor(col_jisdor)
        duration = (datetime.now() - t0).total_seconds()
        _update_scrape_metadata(db, "jisdor", "SUCCESS", duration)
        logger.info(f"[Scheduler] Kurs JISDOR scraped successfully in {duration:.1f}s.")
    except Exception as e:
        _update_scrape_metadata(db, "jisdor", f"FAILED: {str(e)[:100]}")
        logger.error(f"[Scheduler] Failed to scrape JISDOR: {e}")
    
    total_duration = (datetime.now() - job_start).total_seconds()
    _update_scrape_metadata(db, "_pipeline_summary", "SUCCESS", total_duration)
    logger.info(f"[Scheduler] All scheduled scraping tasks completed in {total_duration:.1f}s!")

def init_scheduler(app=None):
    """Initializes and starts the background scheduler."""
    if not scheduler.running:
        # Schedule the scraping job daily at 00:05 AM (WIB)
        scheduler.add_job(
            func=run_daily_scraping_job,
            trigger="cron",
            hour=0,
            minute=5,
            id="daily_bi_scraping_job",
            replace_existing=True
        )
        
        # Also schedule a shorter interval check/fallback (e.g. every 1 hour) to ensure 
        # that data updates frequently, satisfying the 'hourly' and 'highly active' criteria
        scheduler.add_job(
            func=run_daily_scraping_job,
            trigger="interval",
            hours=1,
            id="hourly_bi_scraping_check",
            replace_existing=True
        )
        
        # Schedule News Scraper every 3 hours
        from utils.news_scraper import fetch_and_store_news
        scheduler.add_job(
            func=fetch_and_store_news,
            trigger="interval",
            hours=3,
            id="hourly_news_scraping_check",
            replace_existing=True
        )
        
        # Start scheduler
        scheduler.start()
        logger.info("[Scheduler] Background scheduler initialized and started successfully.")
