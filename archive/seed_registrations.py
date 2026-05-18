
from main import app
from models.user_model import db, MemberRegistration, MobileUser
from datetime import datetime, date
import random

def seed_dummy_registrations():
    with app.app_context():
        print("Cleaning up existing dummy registrations (optional)...")
        # Optional: MemberRegistration.query.filter(MemberRegistration.full_name.like('Dummy %')).delete()
        
        dummy_data = [
            {
                "full_name": "Dummy Budi Santoso",
                "nik": "3201011234560001",
                "address": "Jl. Merdeka No. 10, Jakarta Pusat",
                "phone": "081234567890",
                "birth_date": date(1990, 5, 15),
                "gender": "LAKI LAKI",
                "status": "pending",
                "approval_status": "PENDING"
            },
            {
                "full_name": "Dummy Siti Aminah",
                "nik": "3201011234560002",
                "address": "Apartemen Green Bay, Pluit, Jakarta Utara",
                "phone": "081987654321",
                "birth_date": date(1995, 8, 22),
                "gender": "PEREMPUAN",
                "status": "pending",
                "approval_status": "PENDING"
            },
            {
                "full_name": "Dummy Ahmad Hidayat",
                "nik": "3201011234560003",
                "address": "Komp. Duta Kranji Blok A1 No. 5, Bekasi",
                "phone": "085611223344",
                "birth_date": date(1988, 12, 10),
                "gender": "LAKI LAKI",
                "status": "pending",
                "approval_status": "PENDING"
            },
            {
                "full_name": "Dummy Rina Kartika",
                "nik": "3201011234560004",
                "address": "Griya Asri Blok C2 No. 12, Depok",
                "phone": "087755667788",
                "birth_date": date(1992, 3, 30),
                "gender": "PEREMPUAN",
                "status": "pending",
                "approval_status": "PENDING"
            },
            {
                "full_name": "Dummy Joko Susilo",
                "nik": "3201011234560005",
                "address": "Perumahan Harapan Baru No. 45, Tangerang",
                "phone": "081399001122",
                "birth_date": date(1985, 7, 5),
                "gender": "LAKI LAKI",
                "status": "pending",
                "approval_status": "PENDING"
            }
        ]

        print(f"Seeding {len(dummy_data)} registration records...")
        
        for item in dummy_data:
            # Create a mobile user for each registration
            email_dummy = item['full_name'].lower().replace(' ', '.') + "@example.com"
            mobile_user = MobileUser.query.filter_by(email=email_dummy).first()
            if not mobile_user:
                mobile_user = MobileUser(
                    full_name=item['full_name'],
                    email=email_dummy,
                    status="AKTIF"
                )
                db.session.add(mobile_user)
                db.session.flush() # Get ID
            
            reg = MemberRegistration(
                mobile_user_id=mobile_user.id,
                nik=item['nik'],
                full_name=item['full_name'],
                address=item['address'],
                phone=item['phone'],
                birth_date=item['birth_date'],
                gender=item['gender'],
                status=item['status'],
                approval_status=item['approval_status'],
                registration_code=f"REG-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}"
            )
            db.session.add(reg)
        
        db.session.commit()
        print("Seeding completed successfully!")

if __name__ == "__main__":
    seed_dummy_registrations()
