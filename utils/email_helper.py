import os
import requests

def send_email_api(to_email, subject, text_content, html_content=None):
    """
    Mengirim email menggunakan HTTP API dari Brevo (Sendinblue).
    Ini lebih aman digunakan di lingkungan Cloud/Hugging Face yang memblokir port SMTP.
    """
    api_key = os.getenv("BREVO_API_KEY")
    sender_email = os.getenv("MAIL_USERNAME", "dianabackup00000@gmail.com")
    sender_name = "Koperasi Simpanku"

    if not api_key:
        print("ERROR: BREVO_API_KEY belum dikonfigurasi di file .env")
        return False

    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json"
    }

    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": text_content
    }
    
    if html_content:
        payload["htmlContent"] = html_content

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code in [201, 200, 202]:
            print(f"✅ Email berhasil dikirim ke {to_email} via Brevo API.")
            return True
        else:
            print(f"❌ Gagal mengirim email ke {to_email}. Error: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Terjadi kesalahan saat request API ke Brevo: {str(e)}")
        return False
