import os
import sys
from datetime import datetime, date
import random

# Add project root to sys.path
sys.path.append(os.getcwd())

from main import app
from models.user_model import db, Member, User
import hashlib

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def seed():
    with app.app_context():
        # Drop and recreate tables to ensure new schema is applied
        db.drop_all()
        db.create_all()
        print("Recreated tables with new schema.")

        # Create Admin
        admin = User(
            full_name="Admin Utama",
            employee_id="ADM-001",
            email="admin@example.com",
            password=hash_password("admin123456789"), # Min 12 chars as per signup logic
            role="admin"
        )
        db.session.add(admin)

        names = [
            ("Rahardian Anwar", "rahardian@mail.com"),
            ("Siti Aminah", "siti.amin@monolith.org"),
            ("Bambang Permadi", "bambang.p@outlook.com"),
            ("Eko Prasetyo", "eko.p@google.com"),
            ("Dewi Lestari", "dewi.l@gmail.com"),
            ("Fahri Hamzah", "fahri.h@yahoo.com"),
            ("Gita Gutawa", "gita.g@music.id"),
            ("Hadi Tjahjanto", "hadi.t@mil.id"),
            ("Indah Permata", "indah.p@shop.com"),
            ("Joko Widodo", "joko@gov.id")
        ]

        genders = ["LAKI LAKI", "PEREMPUAN"]
        jabatans = ["Manager", "Supervisor", "Staff", "Analyst", "Developer"]
        membership_types = ["ANGGOTA", "CALON ANGGOTA"]
        statuses = ["AKTIF", "TIDAK AKTIF"]

        members_to_add = []
        for i, (name, email) in enumerate(names):
            gender = genders[0] if i % 2 == 0 else genders[1]
            m_no = f"MB-{2024 if i % 2 == 0 else 2023}-{8891 + i:04d}"
            
            member = Member(
                member_no=m_no,
                full_name=name,
                jabatan=random.choice(jabatans),
                birth_date=date(1980 + random.randint(0, 20), random.randint(1, 12), random.randint(1, 28)),
                gender=gender,
                phone=f"0812{random.randint(10000000, 99999999)}",
                email=email,
                address=f"Jl. Merdeka No. {i+1}, Jakarta Selatan",
                membership_type=random.choice(membership_types),
                loan_limit=random.choice([0, 5000000, 10000000, 25000000, 50000000]),
                status=random.choice(statuses),
                date_joined=datetime.now()
            )
            members_to_add.append(member)

        # Add more dummy records to reach 1284 as in the image
        for i in range(10, 1284):
            m_no = f"MB-2024-{1000 + i:04d}"
            member = Member(
                member_no=m_no,
                full_name=f"Member Dummy {i}",
                jabatan="Staff",
                birth_date=date(1990, 1, 1),
                gender="LAKI LAKI",
                phone="08000000000",
                email=f"dummy{i}@example.com",
                address="-",
                membership_type="ANGGOTA",
                loan_limit=0,
                status="AKTIF",
                date_joined=datetime.now()
            )
            members_to_add.append(member)

        db.session.add_all(members_to_add)
        db.session.commit()
        print(f"Successfully seeded {len(members_to_add)} members.")

if __name__ == "__main__":
    seed()
