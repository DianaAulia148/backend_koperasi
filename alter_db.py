import sqlite3

def upgrade_db():
    conn = sqlite3.connect('d:/SEMESTER 6/CAPSTONE PROJEK/backend_koperasi/instance/app.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute("ALTER TABLE member_registration ADD COLUMN bank_name VARCHAR(100);")
        print("Added bank_name to member_registration")
    except sqlite3.OperationalError as e:
        print(f"member_registration.bank_name: {e}")

    try:
        cursor.execute("ALTER TABLE member_registration ADD COLUMN bank_account_number VARCHAR(100);")
        print("Added bank_account_number to member_registration")
    except sqlite3.OperationalError as e:
        print(f"member_registration.bank_account_number: {e}")

    try:
        cursor.execute("ALTER TABLE members ADD COLUMN bank_name VARCHAR(100);")
        print("Added bank_name to members")
    except sqlite3.OperationalError as e:
        print(f"members.bank_name: {e}")

    try:
        cursor.execute("ALTER TABLE members ADD COLUMN bank_account_number VARCHAR(100);")
        print("Added bank_account_number to members")
    except sqlite3.OperationalError as e:
        print(f"members.bank_account_number: {e}")

    conn.commit()
    conn.close()

if __name__ == '__main__':
    upgrade_db()
