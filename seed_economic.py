from main import app
from models.user_model import db, EconomicIndicator, RegionalSalaryData
from datetime import datetime, timedelta
import random

def seed_economic_data():
    with app.app_context():
        print(">>> Seeding Economic Data...")
        
        # 1. Economic Indicators (Last 6 months)
        start_date = datetime.now() - timedelta(days=180)
        indicators = []
        for i in range(7):
            date = start_date + timedelta(days=i*30)
            indicators.append(EconomicIndicator(
                date=date.date(),
                inflation_rate=random.uniform(2.5, 5.0),
                bi_rate=random.uniform(5.5, 6.5),
                usd_idr=random.uniform(15500, 16300),
                source="BI.go.id / Mock"
            ))
        
        db.session.add_all(indicators)
        
        # 2. Regional Salary Data (Central Java)
        cities = [
            ('Semarang', 3060348),
            ('Demak', 2733000),
            ('Kendal', 2520000),
            ('Salatiga', 2378000),
            ('Magelang', 2310000),
            ('Surakarta', 2263000)
        ]
        
        salary_data = []
        for city, umr in cities:
            salary_data.append(RegionalSalaryData(
                province='Jawa Tengah',
                city=city,
                umr=umr,
                year=2024
            ))
        
        db.session.add_all(salary_data)
        db.session.commit()
        print(">>> Economic Data Seeded Successfully!")

if __name__ == '__main__':
    seed_economic_data()
