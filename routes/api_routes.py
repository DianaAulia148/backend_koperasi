from flask import Blueprint, request, jsonify, current_app
from models.user_model import db, MemberRegistration, MobileUser, Member, MemberSavingBalance, SavingTransaction, SavingType, WithdrawalRequest, ActivityLog, OTPVerification
from routes.auth_routes import mail
from flask_mail import Message
import random
from datetime import datetime, timedelta
import os
from threading import Thread
import jwt
import hashlib
from functools import wraps
import cloudinary
import cloudinary.uploader
import cv2
import easyocr
import re
from thefuzz import fuzz
import io
from google.cloud import vision
from google.oauth2 import service_account

# Configuration Cloudinary
cloudinary.config( 
    cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME'), 
    api_key = os.getenv('CLOUDINARY_API_KEY'), 
    api_secret = os.getenv('CLOUDINARY_API_SECRET'),
    secure = True
)

api_bp = Blueprint('api', __name__, url_prefix='/api')

def send_async_email(app, msg):
    with app.app_context():
        try:
            mail.send(msg)
        except Exception as e:
            print(f"Async email error: {e}")

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        # Cek header Authorization: Bearer <token>
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith('Bearer '):
                token = auth_header.split(" ")[1]
        
        if not token:
            return jsonify({'success': False, 'message': 'Token is missing!'}), 401
        
        try:
            data = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=["HS256"])
            current_user = MobileUser.query.filter_by(id=data['user_id']).first()
            if not current_user:
                return jsonify({'success': False, 'message': 'User not found!'}), 401
        except jwt.ExpiredSignatureError:
            return jsonify({'success': False, 'message': 'Token has expired!'}), 401
        except Exception as e:
            return jsonify({'success': False, 'message': 'Token is invalid!'}), 401
            
        return f(current_user, *args, **kwargs)
    
    return decorated

@api_bp.route('/register', methods=['POST'])
def mobile_register():
    try:
        data = request.form
        full_name = data.get('full_name')
        email = data.get('email')
        password = data.get('password')
        phone = data.get('phone')

        if not email or not password:
            return jsonify({'success': False, 'error': 'Email dan password wajib diisi.'}), 400

        # Check existing
        existing_user = MobileUser.query.filter_by(email=email).first()
        if existing_user:
            if existing_user.is_verified:
                return jsonify({'success': False, 'error': 'Email sudah terdaftar.'}), 400
            else:
                # Jika belum verifikasi, timpa datanya agar user bisa kirim ulang OTP dari halaman Register
                existing_user.full_name = full_name
                existing_user.password = hash_password(password)
                existing_user.phone = phone
                new_user = existing_user
        else:
            hashed_password = hash_password(password)
            new_user = MobileUser(
                full_name=full_name,
                email=email,
                password=hashed_password,
                phone=phone,
                is_verified=False # Wajib verifikasi
            )
            db.session.add(new_user)
        db.session.commit()

        # Generate & Send OTP
        otp_code = str(random.randint(100000, 999999))
        expires_at = datetime.utcnow() + timedelta(minutes=15)
        
        # Simpan OTP ke DB
        otp_entry = OTPVerification(
            email=email,
            otp_code=otp_code,
            purpose='registration',
            expires_at=expires_at
        )
        db.session.add(otp_entry)
        db.session.commit()

        # Kirim Email secara Asynchronous (Background) agar tidak lemot
        msg = Message("Kode Verifikasi Pendaftaran Koperasi",
                      sender=current_app.config['MAIL_USERNAME'],
                      recipients=[email])
        msg.body = f"Halo {full_name},\n\nKode verifikasi Anda adalah: {otp_code}\n\nKode ini berlaku selama 15 menit. Mohon jangan sebarkan kode ini kepada siapa pun."
        
        app = current_app._get_current_object()
        Thread(target=send_async_email, args=(app, msg)).start()

        # Log Activity
        ActivityLog.log(f"New Mobile Registration: {full_name} (Pending Verification)", user_id=None, table_name="mobile_users", reference_id=new_user.id)

        return jsonify({
            'success': True, 
            'message': 'Registrasi berhasil. Silakan cek email Anda untuk kode verifikasi.',
            'is_verified': False,
            'debug_otp': otp_code # DITAMBAHKAN SEMENTARA AGAR ANDA BISA MELIHATNYA DI FLUTTER
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@api_bp.route('/login', methods=['POST'])
def mobile_login():
    auth = request.form # Bisa dari JSON atau Form
    email = request.form.get('email')
    password = request.form.get('password')

    if not email or not password:
        return jsonify({'success': False, 'message': 'Email and Password are required!'}), 400

    hashed_password = hash_password(password)
    user = MobileUser.query.filter_by(email=email, password=hashed_password).first()

    if not user:
        return jsonify({'success': False, 'error': 'Email atau password salah.'}), 401

    # Check Verification Status
    if not user.is_verified:
        return jsonify({
            'success': False, 
            'error': 'Akun Anda belum diverifikasi. Silakan cek email untuk kode OTP.',
            'needs_verification': True,
            'email': user.email
        }), 403 # Forbidden until verified

    # Generate Token (berlaku 7 hari)
    token = jwt.encode({
        'user_id': user.id,
        'exp': datetime.utcnow() + timedelta(days=7)
    }, current_app.config['SECRET_KEY'], algorithm="HS256")

    # Log Activity
    ActivityLog.log(f"Mobile User Login: {user.full_name}", user_id=None, table_name="mobile_users", reference_id=user.id)

    return jsonify({
        'success': True,
        'token': token,
        'user': {
            'id': user.id,
            'full_name': user.full_name,
            'email': user.email,
            'is_verified': True
        }
    })

@api_bp.route('/verify-otp', methods=['POST'])
def verify_otp():
    try:
        # Dukung JSON (Flutter) dan Form-Data
        if request.is_json:
            data = request.get_json()
            email = data.get('email', '').strip()
            otp_code = data.get('otp_code', '').strip()
        else:
            email = request.form.get('email', '').strip()
            otp_code = request.form.get('otp_code', '').strip()

        if not email or not otp_code:
            return jsonify({'success': False, 'error': 'Email dan kode OTP wajib diisi.'}), 400

        # Cari OTP terbaru yang belum expired
        otp_entry = OTPVerification.query.filter_by(
            email=email, 
            otp_code=otp_code,
            purpose='registration'
        ).filter(OTPVerification.expires_at > datetime.utcnow()).order_by(OTPVerification.created_at.desc()).first()

        if not otp_entry:
            return jsonify({'success': False, 'error': 'Kode OTP salah atau sudah kadaluarsa.'}), 400

        # Verifikasi User
        user = MobileUser.query.filter_by(email=email).first()
        if user:
            user.is_verified = True
            db.session.commit()
            
            # Hapus OTP yang sudah terpakai
            db.session.delete(otp_entry)
            db.session.commit()

            # Log Activity
            ActivityLog.log(f"User Verified Account: {user.full_name}", user_id=None, table_name="mobile_users", reference_id=user.id)

            return jsonify({'success': True, 'message': 'Verifikasi berhasil. Silakan login.'})
        else:
            return jsonify({'success': False, 'error': 'User tidak ditemukan.'}), 404

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@api_bp.route('/resend-otp', methods=['POST'])
def resend_otp():
    try:
        if request.is_json:
            data = request.get_json()
            email = data.get('email', '').strip()
        else:
            email = request.form.get('email', '').strip()

        if not email:
            return jsonify({'success': False, 'error': 'Email wajib diisi.'}), 400

        user = MobileUser.query.filter_by(email=email).first()
        if not user:
            return jsonify({'success': False, 'error': 'Email tidak terdaftar.'}), 404

        # Generate & Send New OTP
        otp_code = str(random.randint(100000, 999999))
        expires_at = datetime.utcnow() + timedelta(minutes=15)
        
        otp_entry = OTPVerification(
            email=email,
            otp_code=otp_code,
            purpose='registration',
            expires_at=expires_at
        )
        db.session.add(otp_entry)
        db.session.commit()

        # Kirim Email secara Asynchronous
        msg = Message("Kode Verifikasi Baru - Koperasi",
                      sender=current_app.config['MAIL_USERNAME'],
                      recipients=[email])
        msg.body = f"Kode verifikasi baru Anda adalah: {otp_code}\n\nBerlaku selama 15 menit."
        
        app = current_app._get_current_object()
        Thread(target=send_async_email, args=(app, msg)).start()

        return jsonify({
            'success': True, 
            'message': 'Kode verifikasi baru telah dikirim ke email Anda.',
            'debug_otp': otp_code # DITAMBAHKAN SEMENTARA
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Folder untuk menyimpan hasil unggahan
UPLOAD_FOLDER = 'uploads'
REGISTRATION_FOLDER = os.path.join(UPLOAD_FOLDER, 'registrations')

for folder in [UPLOAD_FOLDER, REGISTRATION_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

import cv2
import re
import os
from datetime import date

# --- OCR Reader (WAJIB pakai 'en' DAN 'id') ---
reader = None
def get_ocr_reader():
    global reader
    if reader is None:
        import easyocr
        reader = easyocr.Reader(['en', 'id'], gpu=False)
    return reader


# --- Preprocessing Gambar KTP ---
def preprocess_ktp(img_path):
    img = cv2.imread(img_path)
    if img is None:
        raise ValueError("Gambar tidak terbaca.")
    
    # Adaptive Resize: Cek resolusi gambar sebelum membesarkan/mengecilkan.
    # Gambar dari Document Scanner Google sudah HD, jangan digandakan lagi!
    h, w = img.shape[:2]
    print(f">>> Resolusi gambar asli: {w}x{h} piksel")
    
    if w < 800:
        # Gambar terlalu kecil, perbesar 2x
        img_resized = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        print(f">>> Gambar kecil, diperbesar 2x -> {w*2}x{h*2}")
    elif w > 3500:
        # Gambar super raksasa, perkecil sedikit saja agar OCR tidak mati (memori habis)
        img_resized = cv2.resize(img, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        print(f">>> Gambar raksasa, diperkecil 0.5x -> {w//2}x{h//2}")
    else:
        # Resolusi wajar (800-3500px), JANGAN DIPERKECIL agar teks kecil tetap terbaca tajam!
        img_resized = img
        print(f">>> Resolusi dipertahankan agar teks kecil terbaca tajam.")
    
    gray = cv2.cvtColor(img_resized, cv2.COLOR_BGR2GRAY)
    
    # 1. Binarized (Thresh)
    denoised = cv2.fastNlMeansDenoising(gray, h=10)
    _, thresh = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # 2. Grayscale Enhanced (CLAHE)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    
    # Mengembalikan 4 versi gambar untuk strategi Multi-Pass
    return img_resized, gray, enhanced, thresh


# ============================================================
# VALIDASI STRUKTUR NIK (16 DIGIT KETAT)
# ============================================================
def validate_nik_structure(nik_str, jenis_kelamin=""):
    """
    Membedah dan memvalidasi NIK KTP Indonesia berdasarkan aturan Kemendagri.
    NIK = PPKKCC.TTBBUU.NNNN
      PP   = Kode Provinsi (11-94)
      KK   = Kode Kabupaten/Kota (01-99)
      CC   = Kode Kecamatan (01-99)
      TT   = Tanggal Lahir (01-31, perempuan +40 jadi 41-71)
      BB   = Bulan Lahir (01-12)
      UU   = Tahun Lahir (2 digit terakhir)
      NNNN = Nomor Urut Pendaftaran (0001-9999)
    
    Returns: (is_valid: bool, message: str, corrected_nik: str)
    """
    if not nik_str or not nik_str.isdigit():
        return False, "NIK harus berisi angka saja.", nik_str
    
    if len(nik_str) != 16:
        return False, f"NIK harus 16 digit, terdeteksi {len(nik_str)} digit.", nik_str
    
    provinsi = int(nik_str[0:2])
    kabupaten = int(nik_str[2:4])
    kecamatan = int(nik_str[4:6])
    tanggal = int(nik_str[6:8])
    bulan = int(nik_str[8:10])
    tahun = int(nik_str[10:12])
    urut = int(nik_str[12:16])
    
    # Validasi Kode Provinsi (11=Aceh s/d 94=Papua Barat Daya)
    VALID_PROVINSI = [
        11,12,13,14,15,16,17,18,19,21,  # Sumatera
        31,32,33,34,35,36,              # Jawa + Banten
        51,52,53,                        # Bali, NTB, NTT
        61,62,63,64,65,                  # Kalimantan
        71,72,73,74,75,76,              # Sulawesi
        81,82,                           # Maluku
        91,92,93,94                      # Papua
    ]
    if provinsi not in VALID_PROVINSI:
        return False, f"Kode Provinsi '{nik_str[0:2]}' tidak valid. NIK mungkin salah baca oleh OCR.", nik_str
    
    # Validasi Tanggal Lahir
    # Perempuan: tanggal + 40 (jadi 41-71)
    is_perempuan = False
    if jenis_kelamin.upper() in ['PEREMPUAN', 'P']:
        is_perempuan = True
    elif tanggal > 40 and tanggal <= 71:
        # Jika OCR gagal baca Jenis Kelamin, tapi tanggal > 40, kita simpulkan dia perempuan
        is_perempuan = True
    
    if is_perempuan:
        if tanggal < 41 or tanggal > 71:
            return False, f"Tanggal lahir '{nik_str[6:8]}' tidak valid untuk perempuan (harus 41-71).", nik_str
    else:
        if tanggal < 1 or tanggal > 31:
            return False, f"Tanggal lahir '{nik_str[6:8]}' tidak valid (harus 01-31).", nik_str
    
    # Validasi Bulan (01-12)
    if bulan < 1 or bulan > 12:
        return False, f"Bulan lahir '{nik_str[8:10]}' tidak valid (harus 01-12).", nik_str
    
    # Validasi Nomor Urut (tidak boleh 0000)
    if urut == 0:
        return False, "Nomor urut NIK tidak boleh 0000.", nik_str
    
    return True, "NIK valid.", nik_str


# ============================================================
# FUZZY MATCHING UNTUK DETEKSI DUPLIKAT NAMA & NIK
# ============================================================
def fuzzy_check_duplicate(nik, nama, threshold=85):
    """
    Memeriksa apakah NIK atau Nama sudah ada di database dengan Fuzzy Matching.
    
    - NIK: Dicek secara EXACT MATCH (persis 16 digit).
    - Nama: Dicek secara FUZZY (kemiripan >= threshold%).
    
    Returns: (is_duplicate: bool, reason: str)
    """
    is_duplicate = False
    reason = ""
    
    # --- 1. Cek NIK Exact Match di Member (Anggota Aktif) ---
    if nik:
        existing_member = Member.query.filter_by(nik=nik).first()
        if existing_member:
            return True, f"NIK ({nik}) sudah terdaftar sebagai anggota aktif: {existing_member.full_name} (ID: {existing_member.member_no})."
        
        # Cek di MemberRegistration (Pendaftaran Pending/Approved)
        existing_reg = MemberRegistration.query.filter_by(ocr_nik=nik).filter(
            MemberRegistration.status.in_(['pending', 'approved'])
        ).first()
        if existing_reg:
            return True, f"NIK ({nik}) sedang dalam proses pendaftaran (status: {existing_reg.status})."
    
    # --- 2. Fuzzy Match Nama di Member (Anggota Aktif) ---
    if nama:
        nama_upper = nama.upper().strip()
        all_members = Member.query.with_entities(Member.full_name, Member.member_no).all()
        for member_name, member_no in all_members:
            if member_name:
                score = fuzz.token_sort_ratio(nama_upper, member_name.upper().strip())
                if score >= threshold:
                    return True, f"Nama '{nama}' sangat mirip ({score}%) dengan anggota aktif: '{member_name}' (ID: {member_no})."
        
        # Fuzzy Match Nama di MemberRegistration (Pendaftaran Pending)
        all_regs = MemberRegistration.query.filter(
            MemberRegistration.status.in_(['pending', 'approved'])
        ).with_entities(MemberRegistration.ocr_name, MemberRegistration.id).all()
        for reg_name, reg_id in all_regs:
            if reg_name:
                score = fuzz.token_sort_ratio(nama_upper, reg_name.upper().strip())
                if score >= threshold:
                    return True, f"Nama '{nama}' sangat mirip ({score}%) dengan pendaftaran #{reg_id}: '{reg_name}'."
    
    return False, ""


# --- Parser KTP Lengkap (dari Colab yang sudah berhasil) ---
def parse_ktp_to_flask_format(results):
    text_conf = [(text, prob) for (_, text, prob) in results]
    raw_text  = ' '.join([t for t, _ in text_conf])
    raw_upper = raw_text.upper()

    ktp_data  = {}

    # Koreksi NIK (Lebih Kebal Kesalahan OCR)
    cleaned_for_nik = raw_text.upper().replace(" ", "")
    replacements = {
        'O': '0', 'I': '1', 'L': '1', 'S': '5', 'B': '8', 
        'Z': '2', 'G': '6', 'T': '7', 'A': '4', 'U': '0', 'D': '0'
    }
    for char, replacement in replacements.items():
        cleaned_for_nik = cleaned_for_nik.replace(char, replacement)
    
    nik = re.search(r'(\d{16})', cleaned_for_nik)
    if not nik:
        # Fallback jika ada digit hilang / kelebihan (15-17 digit)
        nik = re.search(r'(\d{15,17})', cleaned_for_nik)
        
    ktp_data['nik'] = nik.group(1) if nik else ""

    # ============================================================
    # KOREKSI KODE PROVINSI BERBASIS TEKS KTP (ANTI SALAH BACA)
    # Angka 3 sering terbaca 2, 5, 6, 7, atau 8 oleh OCR.
    # Jika Provinsi terbaca di gambar, kita koreksi 2 digit pertama NIK.
    # ============================================================
    raw_nik = ktp_data.get('nik', '')
    if raw_nik and len(raw_nik) >= 2:
        # Peta koreksi: {kode_provinsi_benar: (keyword_di_KTP, daftar_kemungkinan_salah_baca)}
        PROVINSI_KOREKSI = {
            '33': (['JAWA TENGAH', 'JATENG', 'KOTA TEGAL', 'KAB TEGAL', 'KOTA SEMARANG', 'KAB SEMARANG', 'KOTA SOLO', 'KUDUS', 'BREBES', 'PEKALONGAN'],
                   ['22', '23', '25', '27', '28', '32', '35', '37', '38', '53', '55', '57', '58', '73', '77']),
            '32': (['JAWA BARAT', 'JABAR', 'KOTA BANDUNG', 'KAB BANDUNG', 'KOTA BOGOR', 'BEKASI', 'DEPOK', 'SUKABUMI'],
                   ['22', '23', '52', '72', '37', '57']),
            '35': (['JAWA TIMUR', 'JATIM', 'KOTA SURABAYA', 'KOTA MALANG', 'KAB MALANG'],
                   ['25', '55', '75', '85']),
            '36': (['BANTEN', 'KOTA TANGERANG', 'KAB TANGERANG', 'SERANG', 'CILEGON'],
                   ['26', '56', '76', '86']),
            '31': (['DKI JAKARTA', 'JAKARTA', 'JAKARTA PUSAT', 'JAKARTA SELATAN'],
                   ['21', '51', '71', '81']),
            '34': (['YOGYAKARTA', 'DIY', 'SLEMAN', 'BANTUL', 'GUNUNG KIDUL'],
                   ['24', '54', '74', '84']),
            '11': (['ACEH', 'NAD'], ['21', '51']),
            '12': (['SUMATERA UTARA', 'SUMUT', 'MEDAN'], ['22', '52']),
            '13': (['SUMATERA BARAT', 'SUMBAR', 'PADANG'], ['23', '53']),
        }
        for kode_benar, (keywords, wrong_codes) in PROVINSI_KOREKSI.items():
            # Cek apakah salah satu keyword provinsi ada di teks gambar
            if any(kw in raw_upper for kw in keywords):
                if raw_nik[0:2] in wrong_codes:
                    ktp_data['nik'] = kode_benar + raw_nik[2:]
                    print(f">>> Koreksi Provinsi: NIK {raw_nik[:2]}... -> {kode_benar}... (Provinsi: {kode_benar})")
                break  # Berhenti setelah menemukan provinsi yang cocok

    # Ekstraksi Nama — dengan Stop-Word Trimming agar tidak tumpah ke field berikutnya
    NAMA_STOP_WORDS = [
        'tempat', 'tgl', 'tanggal', 'lahir', 'jenis', 'kelamin', 'gol',
        'darah', 'agama', 'alamat', 'rt', 'rw', 'kecamatan', 'status',
        'pekerjaan', 'kewarganegaraan', 'berlaku', 'provinsi', 'kabupaten',
        'kel', 'desa', 'kota', 'penduduk'
    ]

    def trim_nama(raw_nama):
        result = raw_nama.strip()
        
        # Cegah Nama tumpah ke field Tempat/Tgl Lahir (contoh: "Diana Tempaltgl" atau "Tenpauqlahir")
        bleed_match = re.search(r'(?i)(?:temp[a-z]*|tenp[a-z]*)\s*[/\\]?\s*(?:tgl|tangg|lahir|fgae)', result)
        if bleed_match:
            result = result[:bleed_match.start()].strip()
            
        cut_pos = len(result)
        for sw in NAMA_STOP_WORDS:
            match = re.search(r'(?i)\b' + sw + r'\b', result)
            if match and match.start() < cut_pos:
                cut_pos = match.start()
        return result[:cut_pos].strip()

    nama = ""
    BLACKLIST_NAMA = [
        'PEREMPUAN', 'LAKI-LAKI', 'LAKI', 'ISLAM', 'KRISTEN', 'KATOLIK',
        'HINDU', 'BUDDHA', 'KONGHUCU', 'PROVINSI', 'KABUPATEN', 'KOTA',
        'NIK', 'ALAMAT', 'PEKERJAAN', 'KEWARGANEGARAAN', 'WNI', 'WNA',
        'HINGGA', 'BERLAKU', 'SEUMUR', 'HIDUP', 'GOL', 'DARAH', 'STATUS',
        'PERKAWINAN', 'AGAMA', 'TEMPAT', 'TGL', 'LAHIR', 'GOLONGAN'
    ]

    # Strategy 1: cari keyword 'Nama' di raw_text lalu trim stop-word
    m1 = re.search(r'(?:^|\s)(?:Nama|NAMA)\s*[:\-]?\s*([A-Za-z][A-Za-z\s\'\.]{2,})', raw_text, re.IGNORECASE)
    if m1:
        nama = trim_nama(m1.group(1))

    # Strategy 2: cari per-blok OCR
    if not nama:
        for i, (text, prob) in enumerate(text_conf):
            if re.search(r'\bNama\b', text, re.IGNORECASE):
                # Cek apakah nama ada di blok yang SAMA (mis: "Nama DIANA AULIA")
                inline = re.sub(r'(?i)nama\s*[:\-]?\s*', '', text).strip()
                inline_clean = trim_nama(inline)
                if len(inline_clean) >= 3 and inline_clean.upper() not in BLACKLIST_NAMA:
                    nama = inline_clean
                    break
                # Jika tidak, ambil dari blok berikutnya
                for j in range(i + 1, min(i + 4, len(text_conf))):
                    candidate = trim_nama(text_conf[j][0].strip())
                    if (re.match(r'^[A-Za-z\s\'\.]{3,}$', candidate)
                            and not any(bw in candidate.upper() for bw in BLACKLIST_NAMA)
                            and len(candidate) >= 3):
                        nama = candidate
                        break
                break

    # Strategy 3: NIK-Relative Positioning (Paling Akurat & Tahan Banting)
    # Di KTP, Nama SELALU berada tepat di bawah NIK. Jika OCR gagal membaca kata "Nama",
    # kita ambil 1-2 baris teks yang berada tepat setelah NIK ditemukan.
    if not nama and ktp_data.get('nik'):
        nik_value = ktp_data['nik']
        nik_idx = -1
        # Cari di blok mana NIK berada
        for i, (text, prob) in enumerate(text_conf):
            if nik_value in text.replace(" ", "") or (len(nik_value) >= 10 and nik_value[:10] in text.replace(" ", "")):
                nik_idx = i
                break
        
        if nik_idx != -1:
            # Cek 1-3 blok setelah NIK
            for i in range(nik_idx + 1, min(nik_idx + 4, len(text_conf))):
                candidate = text_conf[i][0]
                # Bersihkan jika ada sisa kata "Nama:" yang terpotong
                candidate_clean = re.sub(r'(?i)^(?:Nama|NAMA|Nena|Mame|Nane|Narna|Namo|Nami)\s*[:\-]?\s*', '', candidate).strip()
                candidate_clean = trim_nama(candidate_clean)
                
                # Nama harus dominan huruf dan minimal 3 karakter
                if len(candidate_clean) >= 3 and re.match(r'^[A-Za-z\s\'\.]{3,}$', candidate_clean):
                    if not any(bw in candidate_clean.upper() for bw in BLACKLIST_NAMA) and not any(sw in candidate_clean.lower() for sw in ['rt', 'rw', 'kec', 'kel', 'desa', 'kab']):
                        nama = candidate_clean
                        break

    ktp_data['nama'] = nama.title() if nama else ""

    tempat = re.search(r'(?:Tempat|Temp[a-z]+)\s*[/\s]*(?:Tgl\.?|Tanggal)?\s*(?:Lahir)?\s*[:\-]?\s*([A-Z][A-Z\s,]+?)(?:\d{2}-|\s{2,}|$)', raw_text, re.IGNORECASE)
    tempat_str = tempat.group(1).strip().rstrip(',') if tempat else ""
    # Bersihkan sisa-sisa typo dari label yang ikut terbaca
    tempat_str = re.sub(r'(?i)^(?:tempat|tgl|lql|lahir|tanggal|tempal|tenpauq|tgi)\s*[:\-]?\s*', '', tempat_str).strip()

    tgl = re.search(r'(\d{2}-\d{2}-\d{4})', raw_text)
    tgl_str = tgl.group(1) if tgl else ""

    if tempat_str and tgl_str:
        ktp_data['ttl'] = f"{tempat_str}, {tgl_str}"
    elif tempat_str:
        ktp_data['ttl'] = tempat_str
    elif tgl_str:
        ktp_data['ttl'] = tgl_str
    else:
        ktp_data['ttl'] = ""

    # Regex untuk toleransi Typo Jenis Kelamin
    if re.search(r'(?i)(PEREMPUAN|PERENPUAN|PEREMPIIAN|PREMPUAN|REMPUAN|PEMPUAN)', raw_text):
        ktp_data['jenis_kelamin'] = 'Perempuan'
    elif re.search(r'(?i)\b(LAKI|LAK1|L4KI)\b', raw_text):
        ktp_data['jenis_kelamin'] = 'Laki-laki'
    else:
        ktp_data['jenis_kelamin'] = ""

    agama_map = {
        'Islam': ['ISLAM', '1SLAM', 'ISLAN', 'LSLAM', 'SLA M', 'SLAM', 'ISL M'],
        'Kristen': ['KRISTEN', 'KR1STEN'],
        'Katolik': ['KATOLIK', 'KATHOLIK'],
        'Hindu': ['HINDU'],
        'Buddha': ['BUDDHA', 'BUDHA'],
        'Konghucu': ['KONGHUCU']
    }
    
    found_agama = ""
    # Cari di teks utuh
    for agama_name, aliases in agama_map.items():
        if any(alias in raw_upper for alias in aliases):
            found_agama = agama_name
            break
            
    # Jika gagal, cari per blok kata
    if not found_agama:
        for text, _ in text_conf:
            t_up = text.upper()
            for agama_name, aliases in agama_map.items():
                if any(alias in t_up for alias in aliases):
                    found_agama = agama_name
                    break
            if found_agama: break

    ktp_data['agama'] = found_agama

    alamat = re.search(r'Alamat\s*[:\-]?\s*([A-Za-z0-9][^\n]+?)(?:RT|RW|Kel|Desa|Kec|$)', raw_text, re.IGNORECASE)
    alamat_str = alamat.group(1).strip() if alamat else ""
    if not alamat_str:
        # Fallback Alamat
        alamat_fb = re.search(r'([A-Za-z0-9\s\.\,\-]+?)\s+(?:RT|RW)\s*[:\-]?\s*\d{1,3}', raw_text, re.IGNORECASE)
        if alamat_fb:
            words = alamat_fb.group(1).split()
            alamat_str = ' '.join(words[-3:]) if len(words) >= 3 else ' '.join(words)

    rtrw = re.search(r'(\d{3})[/\\](\d{3})', raw_text)
    rtrw_str = f"{rtrw.group(1)}/{rtrw.group(2)}" if rtrw else ""

    keldesa = re.search(r'(?:Kel|Desa)\s*[/\\]?\s*(?:Desa|Kel)?\s*[:\-]?\s*([A-Za-z][A-Za-z\s]+?)(?:\s{2,}|Kec|$)', raw_text, re.IGNORECASE)
    kel_str = keldesa.group(1).strip() if keldesa else ""

    kec = re.search(r'Kecamatan\s*[:\-]?\s*([A-Za-z][A-Za-z\s]+?)(?:\s{2,}|Agama|$)', raw_text, re.IGNORECASE)
    kec_str = kec.group(1).strip() if kec else ""

    bagian_alamat = []
    if alamat_str: bagian_alamat.append(alamat_str)
    if rtrw_str: bagian_alamat.append('RT/RW ' + rtrw_str)
    if kel_str: bagian_alamat.append('Kel. ' + kel_str)
    if kec_str: bagian_alamat.append('Kec. ' + kec_str)
    ktp_data['alamat'] = ', '.join(bagian_alamat)

    return ktp_data

@api_bp.route('/ocr', methods=['POST'])
def process_ocr():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    file_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(file_path)

    try:
        results = []
        best_method = ""
        
        # ============================================================
        # SMART TOGGLE: CEK APAKAH USER MENGGUNAKAN GOOGLE CLOUD VISION
        # ============================================================
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        gcp_key_path = os.path.join(base_dir, 'gcp_key.json')
        
        if os.path.exists(gcp_key_path):
            print(f">>> [SMART TOGGLE] Ditemukan {gcp_key_path}! Menggunakan Google Cloud Vision API...")
            try:
                # Setup Kredensial
                credentials = service_account.Credentials.from_service_account_file(gcp_key_path)
                client = vision.ImageAnnotatorClient(credentials=credentials)
                
                # Baca Gambar
                with io.open(file_path, 'rb') as image_file:
                    content = image_file.read()
                image = vision.Image(content=content)
                
                # Minta Google membaca Teks
                response = client.text_detection(image=image)
                texts = response.text_annotations
                
                if response.error.message:
                    raise Exception(f"{response.error.message}")
                    
                if texts:
                    # Teks[0] adalah paragraf utuh, Teks[1:] adalah kata per kata.
                    # Kita ubah formatnya agar cocok dengan parser kita yang sudah super canggih: [(None, kata, 1.0)]
                    results_raw = [(None, t.description, 1.0) for t in texts[1:]]
                    results = results_raw
                    best_method = "Google Cloud Vision API (Akurasi Tinggi)"
                    
                    parsed_raw = parse_ktp_to_flask_format(results_raw)
                    mean_confidence = 0.99 # Google sangat akurat
                else:
                    raise Exception("GCP Vision gagal membaca teks apa pun.")
            except Exception as e:
                print(f"!!! Error Google Vision: {e}")
                print("!!! Jatuh kembali (Fallback) ke EasyOCR lokal...")
                os.rename(gcp_key_path, gcp_key_path + ".error") # Matikan sementara
                # Fallback akan ditangkap oleh else di bawah (secara manual, namun lebih aman menggunakan try/except yang luas)
        
        # ============================================================
        # FALLBACK: MENGGUNAKAN EASYOCR LOKAL (OFFLINE)
        # ============================================================
        if not results:
            print(">>> [SMART TOGGLE] Menggunakan EasyOCR Lokal...")
            raw_rgb, gray, enhanced, thresh = preprocess_ktp(file_path)
            ocr_reader = get_ocr_reader()

            # --- TAHAP 1: BACA GAMBAR ASLI (COLOR RGB) ---
            results_raw = ocr_reader.readtext(raw_rgb, detail=1, paragraph=False)
            parsed_raw = parse_ktp_to_flask_format(results_raw)
            nik_raw_valid, _, _ = validate_nik_structure(parsed_raw.get('nik', ''), parsed_raw.get('jenis_kelamin', ''))
            
            # Efisiensi: Jika NIK VALID secara struktur DAN NAMA terbaca, stop proses!
            if nik_raw_valid and parsed_raw.get('nama'):
                results = results_raw
                best_method = "Raw RGB Color (Tahap 1)"
            else:
                # --- TAHAP 2: BACA GRAYSCALE ENHANCED ---
                results_enhanced = ocr_reader.readtext(enhanced, detail=1, paragraph=False)
                parsed_enhanced = parse_ktp_to_flask_format(results_enhanced)
                nik_enhanced_valid, _, _ = validate_nik_structure(parsed_enhanced.get('nik', ''), parsed_enhanced.get('jenis_kelamin', ''))
                
                if nik_enhanced_valid and parsed_enhanced.get('nama'):
                    results = results_enhanced
                    best_method = "Grayscale Enhanced (Tahap 2)"
                else:
                    # --- TAHAP 3: BACA BINARIZATION (TERAKHIR) ---
                    results_thresh = ocr_reader.readtext(thresh, detail=1, paragraph=False)
                    parsed_thresh = parse_ktp_to_flask_format(results_thresh)
                    nik_thresh_valid, _, _ = validate_nik_structure(parsed_thresh.get('nik', ''), parsed_thresh.get('jenis_kelamin', ''))
                    
                    # Bandingkan Akurasi (Confidence) jika tidak ada yang sempurna
                    conf_raw = sum([p for (_, _, p) in results_raw if p > 0]) / max(len(results_raw), 1) if results_raw else 0
                    conf_enhanced = sum([p for (_, _, p) in results_enhanced if p > 0]) / max(len(results_enhanced), 1) if results_enhanced else 0
                    conf_thresh = sum([p for (_, _, p) in results_thresh if p > 0]) / max(len(results_thresh), 1) if results_thresh else 0
                    
                    # Pilih yang memiliki kombinasi data terbaik berdasarkan Validitas NIK
                    if nik_raw_valid:
                        results = results_raw
                        best_method = "Raw RGB Color (Fallback NIK Valid)"
                    elif nik_enhanced_valid:
                        results = results_enhanced
                        best_method = "Grayscale Enhanced (Fallback NIK Valid)"
                    elif nik_thresh_valid:
                        results = results_thresh
                        best_method = "Binarization (Fallback NIK Valid)"
                    elif conf_enhanced > conf_thresh and conf_enhanced > conf_raw:
                        results = results_enhanced
                        best_method = "Grayscale Enhanced (Fallback Confidence)"
                    elif conf_raw > conf_thresh:
                        results = results_raw
                        best_method = "Raw RGB Color (Fallback Confidence)"
                    else:
                        results = results_thresh
                        best_method = "Binarization (Tahap 3)"

            # Hitung Rata-rata Skor
            confidences = [prob for (_, _, prob) in results if prob > 0.0]
            mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        print(f">>> OCR Method: {best_method} | Confidence: {mean_confidence*100:.1f}%")
            
        parsed_data = parse_ktp_to_flask_format(results)

        # ============================================================
        # PENGGABUNGAN DATA (MERGE) DARI TAHAP LAIN JIKA ADA YANG KOSONG ATAU SALAH
        # ============================================================
        current_nik_valid, _, _ = validate_nik_structure(parsed_data.get('nik', ''), parsed_data.get('jenis_kelamin', ''))
        
        # Prioritaskan untuk menimpa NIK jika NIK saat ini invalid tapi tahap lain punya NIK valid!
        if not current_nik_valid:
            if 'parsed_raw' in locals() and validate_nik_structure(parsed_raw.get('nik', ''), parsed_raw.get('jenis_kelamin', ''))[0]:
                parsed_data['nik'] = parsed_raw['nik']
                current_nik_valid = True
            elif 'parsed_enhanced' in locals() and validate_nik_structure(parsed_enhanced.get('nik', ''), parsed_enhanced.get('jenis_kelamin', ''))[0]:
                parsed_data['nik'] = parsed_enhanced['nik']
                current_nik_valid = True
            elif 'parsed_thresh' in locals() and validate_nik_structure(parsed_thresh.get('nik', ''), parsed_thresh.get('jenis_kelamin', ''))[0]:
                parsed_data['nik'] = parsed_thresh['nik']
                current_nik_valid = True

        if 'parsed_enhanced' in locals():
            if not parsed_data.get('nama') and parsed_enhanced.get('nama'): parsed_data['nama'] = parsed_enhanced['nama']
            for key in ['ttl', 'jenis_kelamin', 'agama', 'alamat']:
                if not parsed_data.get(key) and parsed_enhanced.get(key): parsed_data[key] = parsed_enhanced[key]
                
        if 'parsed_thresh' in locals():
            if not parsed_data.get('nama') and parsed_thresh.get('nama'): parsed_data['nama'] = parsed_thresh['nama']
            for key in ['ttl', 'jenis_kelamin', 'agama', 'alamat']:
                if not parsed_data.get(key) and parsed_thresh.get(key): parsed_data[key] = parsed_thresh[key]
        
        if 'parsed_raw' in locals():
            if not parsed_data.get('nama') and parsed_raw.get('nama'): parsed_data['nama'] = parsed_raw['nama']
            for key in ['ttl', 'jenis_kelamin', 'agama', 'alamat']:
                if not parsed_data.get(key) and parsed_raw.get(key): parsed_data[key] = parsed_raw[key]

        # ============================================================
        # VALIDASI STRUKTUR NIK (KRITIS!)
        # ============================================================
        nik = parsed_data.get('nik', '').strip()
        nama = parsed_data.get('nama', '').strip()
        jk = parsed_data.get('jenis_kelamin', '').strip()
        
        nik_valid = False
        nik_message = ""
        if nik:
            nik_valid, nik_message, nik = validate_nik_structure(nik, jk)
            parsed_data['nik'] = nik  # Update jika ada koreksi
        
        parsed_data['nik_valid'] = nik_valid
        parsed_data['nik_validation_message'] = nik_message

        # ============================================================
        # FUZZY MATCHING DUPLIKAT (NIK + NAMA)
        # ============================================================
        is_duplicate, duplicate_reason = fuzzy_check_duplicate(nik if nik_valid else "", nama, threshold=85)
        
        parsed_data['is_duplicate'] = is_duplicate
        parsed_data['duplicate_reason'] = duplicate_reason
        parsed_data['ocr_confidence'] = mean_confidence

        # ============================================================
        # LOG DI BACKEND CONSOLE
        # ============================================================
        print("\n" + "="*60)
        print("           LAPORAN SCAN OCR KTP (VALIDASI KETAT)")
        print("="*60)
        print(f"File           : {file.filename}")
        print(f"Metode Terbaik : {best_method} (conf: {mean_confidence*100:.1f}%)")
        print(f"-" * 60)
        print(f"NIK            : {nik if nik else 'TIDAK TERDETEKSI'}")
        print(f"NIK Valid      : {'✓ YA' if nik_valid else '✗ TIDAK'} — {nik_message}")
        print(f"Nama           : {nama if nama else 'TIDAK TERDETEKSI'}")
        print(f"TTL            : {parsed_data.get('ttl')}")
        print(f"JK             : {jk}")
        print(f"Agama          : {parsed_data.get('agama')}")
        print(f"Alamat         : {parsed_data.get('alamat')}")
        print(f"-" * 60)
        print(f"Duplikat       : {'⚠ YA (DITOLAK)' if is_duplicate else '✓ TIDAK (AMAN)'}")
        if is_duplicate:
            print(f"Alasan         : {duplicate_reason}")
        print("="*60 + "\n")
        
        # Clean up files
        if os.path.exists(file_path):
            os.remove(file_path)

        return jsonify(parsed_data), 200
    except Exception as e:
        print(f"OCR Error: {str(e)}")
        # Clean up files on error
        if os.path.exists(file_path):
            os.remove(file_path)
        return jsonify({'error': str(e)}), 500

@api_bp.route('/member/register', methods=['POST'])
@token_required
def register_member(current_user):
    try:
        # 1. Ambil Data Form (Gunakan ID dari token demi keamanan)
        user_id = current_user.id
        if not user_id:
            return jsonify({'success': False, 'error': 'User ID is required'}), 400

        # Cek apakah sudah ada pendaftaran
        existing = MemberRegistration.query.filter_by(mobile_user_id=user_id).filter(
            MemberRegistration.status.in_(['pending', 'approved'])
        ).first()
        if existing:
            return jsonify({'success': False, 'error': f'Anda sudah memiliki pendaftaran dengan status: {existing.status}'}), 400

        # ============================================================
        # VALIDASI FINAL: STRUKTUR NIK + FUZZY DUPLIKAT
        # ============================================================
        submitted_nik = request.form.get('nik', '').strip()
        submitted_nama = request.form.get('nama', '').strip()
        submitted_jk = request.form.get('jenis_kelamin', '').strip()
        
        # Validasi Struktur NIK
        if submitted_nik:
            nik_valid, nik_msg, _ = validate_nik_structure(submitted_nik, submitted_jk)
            if not nik_valid:
                return jsonify({'success': False, 'error': f'Pendaftaran Ditolak: {nik_msg} Silakan scan ulang KTP Anda.'}), 400
        
        # Fuzzy Matching Duplikat (NIK exact + Nama fuzzy 85%)
        is_dup, dup_reason = fuzzy_check_duplicate(submitted_nik, submitted_nama, threshold=85)
        if is_dup:
            return jsonify({'success': False, 'error': f'Pendaftaran Ditolak: {dup_reason}'}), 400

        # 2. Handle File Uploads (Upload ke Cloudinary)
        file_paths = {}
        file_fields = {
            'ktp': 'ktp', 
            'kartu_karyawan': 'kartu_anggota', 
            'pas_foto': 'pas_foto',
            'tanda_tangan': 'tanda_tangan'
        }

        for key, form_field in file_fields.items():
            if form_field in request.files:
                file = request.files[form_field]
                if file and file.filename != '':
                    # Upload langsung ke Cloudinary
                    try:
                        print(f">>> DEBUG: Uploading {key} to Cloudinary...")
                        upload_result = cloudinary.uploader.upload(
                            file,
                            folder="registrations",
                            public_id=f"reg_{user_id}_{key}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                        )
                        file_paths[f'path_{key}'] = upload_result.get('secure_url')
                        print(f">>> DEBUG: Success! URL: {file_paths[f'path_{key}']}")
                    except Exception as upload_error:
                        print(f">>> ERROR Cloudinary Upload ({key}): {str(upload_error)}")
                        # Jangan hentikan proses jika satu upload gagal, atau bisa return error jika kritis
                        return jsonify({'success': False, 'error': f'Gagal mengunggah {key}: {str(upload_error)}'}), 500

        # 3. Simpan ke Database (Gunakan awalan ocr_ sesuai model)
        new_reg = MemberRegistration(
            mobile_user_id=user_id,
            ocr_nik=request.form.get('nik'), # Gunakan ocr_nik
            ocr_name=request.form.get('nama'), # Flutter kirim 'nama'
            ocr_address=request.form.get('alamat'), # Flutter kirim 'alamat'
            phone=request.form.get('phone'),
            ocr_gender=request.form.get('jenis_kelamin'),
            ocr_birth_date=request.form.get('ttl'),
            status='pending',
            **file_paths
        )

        db.session.add(new_reg)
        db.session.commit()

        # Log Activity
        ActivityLog.log(f"Member Registration Submitted: {request.form.get('nama')}", user_id=None, table_name="member_registration", reference_id=new_reg.id)

        return jsonify({'success': True, 'message': 'Pendaftaran berhasil dikirim.'})

    except Exception as e:
        print(f"Error: {str(e)}") # Print ke console flask untuk debug
        return jsonify({'success': False, 'error': str(e)}), 500

@api_bp.route('/member/status/<int:user_id>', methods=['GET'])
def get_member_status(user_id):
    try:
        # 1. Ambil data MobileUser untuk full_name default
        m_user = MobileUser.query.get(user_id)
        if not m_user:
            return jsonify({'success': False, 'message': 'User not found'}), 404
            
        full_name = m_user.full_name

        # 2. Cek apakah user sudah jadi Member resmi di tabel 'members'
        member = Member.query.filter_by(mobile_user_id=user_id).first()
        if member:
            return jsonify({
                "status": "approved", # Sesuai permintaan (approved/aktif)
                "full_name": member.full_name or full_name,
                "registration_details": {
                    "rejection_reason": ""
                }
            })

        # 3. Jika belum jadi member, cek riwayat pendaftaran di 'member_registration'
        reg = MemberRegistration.query.filter_by(mobile_user_id=user_id).order_by(MemberRegistration.created_at.desc()).first()
        
        if not reg:
            return jsonify({
                "status": "not_started",
                "full_name": full_name,
                "registration_details": {
                    "rejection_reason": ""
                }
            })
        
        # 4. Ambil status yang paling akurat (mendukung kolom approval_status enterprise)
        # Standardize to lowercase as requested by user logic
        db_status = reg.approval_status.lower() if reg.approval_status and reg.approval_status != 'PENDING' else reg.status.lower()
        
        # Mapping status ke format Flutter (case-insensitive handling)
        final_status = db_status
        if db_status in ['aktif', 'approved']:
            final_status = "approved"
        elif db_status in ['pending', 'menunggu']:
            final_status = "pending"
        elif db_status in ['rejected', 'ditolak']:
            final_status = "rejected"

        return jsonify({
            "status": final_status,
            "full_name": reg.ocr_name or full_name,
            "registration_details": {
                "rejection_reason": reg.rejection_reason or ""
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@api_bp.route('/member/financial_details', methods=['GET'])
@token_required
def get_member_financial_details(current_user):
    member = Member.query.filter_by(mobile_user_id=current_user.id).first()
    if not member:
        return jsonify({'error': 'Member not found'}), 404
        
    balances = MemberSavingBalance.query.filter_by(member_id=member.id).all()
    transactions = SavingTransaction.query.filter_by(member_id=member.id).order_by(SavingTransaction.transaction_date.desc()).limit(10).all()
    
    balance_data = []
    total_balance = 0
    for b in balances:
        balance_data.append({
            'saving_type_id': b.saving_type_id,
            'balance': float(b.balance),
            'updated_at': b.updated_at.strftime('%Y-%m-%d %H:%M') if b.updated_at else '-'
        })
        total_balance += float(b.balance)
        
    tx_data = []
    for tx in transactions:
        st_name = SavingType.query.get(tx.saving_type_id).name if tx.saving_type_id else '-'
        tx_data.append({
            'id': tx.id,
            'type': tx.transaction_type,
            'saving_type': st_name,
            'saving_type_id': tx.saving_type_id,
            'amount': float(tx.amount),
            'date': tx.transaction_date.strftime('%Y-%m-%d %H:%M') if tx.transaction_date else '-',
            'status': tx.transaction_status,
            'description': tx.description
        })
        
    # Analytics Calculations
    all_transactions = SavingTransaction.query.filter_by(member_id=member.id, transaction_status='SUCCESS').all()
    
    total_payroll = sum([float(t.amount) for t in all_transactions if t.transaction_source == 'PAYROLL' and t.transaction_type == 'DEPOSIT'])
    total_withdrawal = sum([float(t.amount) for t in all_transactions if t.transaction_type in ['WITHDRAWAL', 'CREDIT'] or (t.transaction_type == 'DEBIT' and t.transaction_source != 'PAYROLL')])
    shu_estimation = total_balance * 0.05 # Proyeksi kas kasar 5%

    # Payroll History (Last 5)
    payroll_txs = SavingTransaction.query.filter_by(member_id=member.id, transaction_source='PAYROLL').order_by(SavingTransaction.transaction_date.desc()).limit(5).all()
    payroll_history = []
    for ptx in payroll_txs:
        payroll_history.append({
            'date': ptx.transaction_date.strftime('%Y-%m'),
            'amount': float(ptx.amount),
            'status': ptx.transaction_status
        })
        
    # Dummy Monthly Growth for Chart (6 months)
    import datetime
    from dateutil.relativedelta import relativedelta
    monthly_growth = {'labels': [], 'data': []}
    current_val = total_balance
    today = datetime.datetime.now()
    
    for i in range(5, -1, -1):
        month_date = today - relativedelta(months=i)
        monthly_growth['labels'].append(month_date.strftime('%b %Y'))
        
        if i == 0:
            monthly_growth['data'].append(current_val)
        else:
            # Mundur: kurangi nilai secara random (simulate growth)
            import random
            reduction = current_val * (random.uniform(0.02, 0.10))
            current_val = max(0, current_val - reduction)
            monthly_growth['data'].append(current_val)

    # Sort dummy data so it makes sense (oldest to newest)
    # The loop above generated data from [now-5, now-4, ..., now]. It's already chronological.
    
    return jsonify({
        'member': {
            'id': member.id,
            'member_no': member.member_no,
            'name': member.full_name,
            'phone': member.phone,
            'email': member.email,
            'address': member.address,
            'status': member.status,
            'birth_date': member.birth_date.strftime('%Y-%m-%d') if member.birth_date else '-',
            'gender': member.gender,
            'jabatan': member.jabatan,
            'pas_foto': member.pas_foto
        },
        'total_balance': total_balance,
        'balances': balance_data,
        'recent_transactions': tx_data,
        'analytics': {
            'total_payroll': total_payroll,
            'total_withdrawal': total_withdrawal,
            'shu_estimation': shu_estimation,
            'monthly_growth': monthly_growth,
            'payroll_history': payroll_history
        }
    })

@api_bp.route('/member/withdraw', methods=['POST'])
@token_required
def request_withdrawal(current_user):
    try:
        user_id = current_user.id
        amount = request.form.get('amount')
        bank_name = request.form.get('bank_name')
        account_number = request.form.get('account_number')
        account_holder = request.form.get('account_holder')
        reason = request.form.get('reason', '')
        saving_type_id = request.form.get('saving_type_id') # New field from Flutter

        if not all([user_id, amount, bank_name, account_number, account_holder]):
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400

        member = Member.query.filter_by(mobile_user_id=user_id).first()
        if not member:
            return jsonify({'success': False, 'error': 'Member not found'}), 404

        # Check balance (optional but recommended)
        # For now, just save the request as pending
        
        new_request = WithdrawalRequest(
            member_id=member.id,
            amount=amount,
            bank_name=bank_name,
            account_number=account_number,
            account_holder=account_holder,
            processing_notes=f"Saving Type ID: {saving_type_id}. Reason: {reason}",
            approval_status='PENDING'
        )

        db.session.add(new_request)
        db.session.commit()

        return jsonify({'success': True, 'message': 'Permohonan penarikan berhasil dikirim.'})

    except Exception as e:
        print(f"Withdrawal Error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

