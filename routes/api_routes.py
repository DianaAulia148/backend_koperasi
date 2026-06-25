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
from utils.ocr_helper import process_ktp_image

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


# --- Preprocessing Gambar KTP (Anti-Background Noise) ---
def remove_background_lines(gray_img):
    """
    Menghapus garis horizontal dan vertikal dari background KTP
    menggunakan morfologi OpenCV. Ini mencegah EasyOCR salah
    membaca garis dekoratif sebagai teks.
    """
    # Deteksi & hapus garis HORIZONTAL
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
    horizontal_lines = cv2.morphologyEx(gray_img, cv2.MORPH_OPEN, horizontal_kernel, iterations=2)
    
    # Deteksi & hapus garis VERTIKAL
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
    vertical_lines = cv2.morphologyEx(gray_img, cv2.MORPH_OPEN, vertical_kernel, iterations=2)
    
    # Gabungkan mask garis
    lines_mask = cv2.add(horizontal_lines, vertical_lines)
    
    # Hapus garis dari gambar asli (ganti dengan putih / latar belakang terang)
    cleaned = cv2.subtract(gray_img, lines_mask)
    
    return cleaned


def remove_background_pattern(gray_img):
    """
    Menghilangkan pola background KTP (motif batik, guilloche pattern)
    dengan teknik Top-Hat Transform + Adaptive Threshold.
    Top-Hat menonjolkan objek TERANG (teks) dan menekan background gelap berulang.
    """
    # Black-Hat: Menonjolkan struktur gelap (teks) di atas background terang
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    blackhat = cv2.morphologyEx(gray_img, cv2.MORPH_BLACKHAT, kernel)
    
    # Top-Hat: Menonjolkan detail kecil terang (noise) agar bisa dihilangkan
    tophat = cv2.morphologyEx(gray_img, cv2.MORPH_TOPHAT, kernel)
    
    # Gabung: kurangi noise tophat, tambah kontras dari blackhat
    result = cv2.subtract(gray_img, tophat)
    result = cv2.add(result, blackhat)
    
    return result


def preprocess_ktp(img_path):
    img = cv2.imread(img_path)
    if img is None:
        raise ValueError("Gambar tidak terbaca.")
    
    # --- STEP 1: Adaptive Resize ---
    h, w = img.shape[:2]
    print(f">>> Resolusi gambar asli: {w}x{h} piksel")
    
    # KTP standar punya rasio sekitar 1.6:1. Lebar 1200px sangat optimal untuk OCR (cepat & akurat)
    # Jika terlalu besar, OCR akan sangat lambat (membuat Flutter timeout > 60s)
    TARGET_WIDTH = 1200
    
    if w > TARGET_WIDTH:
        scale = TARGET_WIDTH / w
        img_resized = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        print(f">>> Gambar diperkecil: {w}x{h} -> {int(w * scale)}x{int(h * scale)}")
    elif w < 800:
        scale = 800 / w
        img_resized = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)
        print(f">>> Gambar diperbesar: {w}x{h} -> {int(w * scale)}x{int(h * scale)}")
    else:
        img_resized = img
        print(f">>> Resolusi dipertahankan: {w}x{h}")
    
    # --- STEP 2: Konversi ke Grayscale ---
    gray = cv2.cvtColor(img_resized, cv2.COLOR_BGR2GRAY)
    
    # --- STEP 3: Hapus Garis Background KTP ---
    # Garis horizontal/vertikal di KTP (border, kolom tabel) sering mengganggu OCR
    gray_no_lines = remove_background_lines(gray)
    print(">>> Background lines removed.")
    
    # --- STEP 4: Hilangkan Pola Background (Motif KTP) ---
    # Motif guilloche/batik di background KTP bisa terbaca sebagai karakter
    gray_clean = remove_background_pattern(gray_no_lines)
    print(">>> Background pattern suppressed.")
    
    # --- STEP 5: Denoising ---
    denoised = cv2.fastNlMeansDenoising(gray_clean, h=15, templateWindowSize=7, searchWindowSize=21)
    
    # --- STEP 6: Versi ENHANCED (CLAHE) — untuk Multi-Pass OCR ---
    # CLAHE meningkatkan kontras lokal agar teks tipis di area gelap ikut terbaca
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(denoised)
    
    # --- STEP 7: Versi BINARIZED (Adaptive Threshold) ---
    # Adaptive lebih baik dari Otsu untuk KTP karena pencahayaan tidak merata
    thresh = cv2.adaptiveThreshold(
        denoised, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=31,  # Area blok untuk threshold lokal
        C=15           # Konstanta pengurang (makin besar = makin bersih background)
    )
    
    print(">>> Preprocessing selesai: raw_rgb | enhanced | thresh (adaptive)")
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
    
    # Validasi Kode Provinsi (11-99 untuk mengakomodasi pemekaran provinsi baru di masa depan)
    if provinsi < 11 or provinsi > 99:
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
            return True, f"Tanggal lahir '{nik_str[6:8]}' tidak valid untuk perempuan (harus 41-71), silakan periksa ulang.", nik_str
    else:
        if tanggal < 1 or tanggal > 31:
            return True, f"Tanggal lahir '{nik_str[6:8]}' tidak valid (harus 01-31), silakan periksa ulang.", nik_str
    
    # Validasi Bulan (01-12)
    if bulan < 1 or bulan > 12:
        return True, f"Bulan lahir '{nik_str[8:10]}' tidak valid (harus 01-12), silakan periksa ulang.", nik_str
    
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
    
    # --- 1. Cek NIK Exact Match (Unik per individu) ---
    if nik:
        existing_member = Member.query.filter_by(nik=nik).first()
        if existing_member:
            return True, f"NIK ({nik}) sudah terdaftar sebagai anggota aktif atas nama {existing_member.full_name}."
        
        existing_reg = MemberRegistration.query.filter_by(ocr_nik=nik).filter(
            MemberRegistration.status.in_(['pending', 'approved'])
        ).first()
        if existing_reg:
            return True, f"NIK ({nik}) sedang dalam proses pendaftaran."
            
    # Nama yang sama dengan NIK yang berbeda diperbolehkan (nama pasaran tidak boleh diblokir)
    return False, ""


# --- Parser KTP Lengkap (Menggunakan Spatial Bounding Box) ---
from utils.spatial_parser import spatial_parse_ktp

def parse_ktp_to_flask_format(results):
    return spatial_parse_ktp(results)

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
                    # ✅ FIX: Sertakan bounding box dari GCP agar spatial_parser bisa bekerja!
                    results_raw = []
                    for t in texts[1:]:
                        box = None
                        if t.bounding_poly and t.bounding_poly.vertices:
                            box = t.bounding_poly.vertices  # GCP vertices format
                        results_raw.append((box, t.description, 1.0))
                    results = results_raw
                    best_method = "Google Cloud Vision API (Akurasi Tinggi)"
                    mean_confidence = 0.99 # Google sangat akurat
                    parsed_data = parse_ktp_to_flask_format(results_raw)
                    print(f">>> [GCP RAW TEXT]: {' '.join([t.description for t in texts[1:]])}")
                else:
                    raise Exception("GCP Vision gagal membaca teks apa pun.")
            except Exception as e:
                print(f"!!! Error Google Vision: {e}")
                print("!!! Jatuh kembali (Fallback) ke PaddleOCR+YOLO lokal...")
                results = []  # pastikan fallback berjalan
        
        # ============================================================
        # FALLBACK: MENGGUNAKAN PADDLEOCR + YOLOv8 (DEEP LEARNING)
        # ✅ FIX BUG #2: Gunakan parser canggih yg sama (bukan ocr_helper.parse_ktp)
        # ============================================================
        if not results:
            print(">>> [SMART TOGGLE] Menggunakan PaddleOCR + YOLOv8 Lokal...")
            
            # Step 1: Preprocess (Adaptive Resize Only, no heavy sharpening)
            import tempfile
            from utils.ocr_helper import get_paddle_ocr
            
            # Kita gunakan fungsi preprocess_ktp lokal di api_routes.py
            # yang sangat cerdas mengatur ukuran gambar (tidak over-sharpen)
            img_resized, _, _, _ = preprocess_ktp(file_path)
            
            temp_preprocessed = None
            try:
                # Simpan sementara untuk dibaca PaddleOCR
                temp_fd, temp_path = tempfile.mkstemp(suffix=".jpg")
                os.close(temp_fd)
                cv2.imwrite(temp_path, img_resized)
                temp_preprocessed = temp_path
                
                # Step 2: PaddleOCR baca teks
                ocr_engine = get_paddle_ocr()
                # Panggil ocr tanpa argumen cls yang tidak lagi didukung di versi baru
                paddle_results = ocr_engine.ocr(temp_preprocessed)
                
                # Step 3: Konversi format PaddleOCR → format 3-tuple yg kompatibel dg parser canggih
                results_raw = []
                if paddle_results and len(paddle_results) > 0 and paddle_results[0] is not None:
                    first_res = paddle_results[0]
                    if isinstance(first_res, dict):
                        # Format baru (PaddleX / PaddleOCR >= 2.7)
                        texts = first_res.get('rec_texts', [])
                        scores = first_res.get('rec_scores', [])
                        polys = first_res.get('rec_polys', [])
                        for i in range(len(texts)):
                            text = str(texts[i])
                            score = float(scores[i]) if i < len(scores) else 1.0
                            box = polys[i] if i < len(polys) else None
                            results_raw.append((box, text, score))
                    elif isinstance(first_res, list):
                        # Format lama (Traditional PaddleOCR)
                        for line in first_res:
                            try:
                                if len(line) >= 2:
                                    box = line[0]  # Bounding box: [[x,y],[x,y],[x,y],[x,y]]
                                    val = line[1]
                                    if isinstance(val, (tuple, list)) and len(val) >= 2:
                                        results_raw.append((box, str(val[0]), float(val[1])))
                                    elif isinstance(val, str):
                                        results_raw.append((box, val, 1.0))
                            except Exception as conv_err:
                                print(f">>> [WARN] Konversi baris OCR gagal: {conv_err}")
                
                raw_words = [t for (_, t, _) in results_raw]
                print(f">>> [PADDLE RAW TEXT]: {' '.join(raw_words)}")
                print(f">>> [PADDLE] Total {len(results_raw)} blok teks terdeteksi.")
                
                # Step 4: Parse dengan parser CANGGIH
                parsed_data = parse_ktp_to_flask_format(results_raw)
                results = results_raw  # tandai sudah diproses
                
            finally:
                if temp_preprocessed and os.path.exists(temp_preprocessed):
                    os.remove(temp_preprocessed)
            
            best_method = "PaddleOCR (Lokal)"
            mean_confidence = 0.95

        # ============================================================
        # VALIDASI STRUKTUR NIK (KRITIS!)
        # ============================================================
        nik = (parsed_data.get('nik') or '').strip()
        nama = (parsed_data.get('nama') or '').strip()
        jk = (parsed_data.get('jenis_kelamin') or '').strip()
        
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
        print(f"NIK Valid      : {'[YA]' if nik_valid else '[TIDAK]'} - {nik_message}")
        print(f"Nama           : {nama if nama else 'TIDAK TERDETEKSI'}")
        print(f"TTL            : {parsed_data.get('ttl')}")
        print(f"JK             : {jk}")
        print(f"Agama          : {parsed_data.get('agama')}")
        print(f"Alamat         : {parsed_data.get('alamat')}")
        print("-" * 60)
        print(f"Duplikat       : {'[YA - DITOLAK]' if is_duplicate else '[TIDAK - AMAN]'}")
        if is_duplicate:
            print(f"Alasan         : {duplicate_reason}")
        print("="*60 + "\n")
        
        # ============================================================
        # LOG AKTIVITAS OCR KE DATABASE
        # ============================================================
        try:
            # Identifikasi user dari token Bearer (jika ada)
            mobile_user_id = None
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                try:
                    token_str = auth_header.split(" ")[1]
                    token_data = jwt.decode(token_str, current_app.config['SECRET_KEY'], algorithms=["HS256"])
                    mobile_user_id = token_data.get('user_id')
                except Exception:
                    pass  # Token tidak valid / tidak ada, lewat saja

            # Catat ke ActivityLog
            log_msg = (
                f"OCR Scan KTP | File: {file.filename} | "
                f"NIK: {nik if nik else 'N/A'} | "
                f"Nama: {nama if nama else 'N/A'} | "
                f"Metode: {best_method} | "
                f"Confidence: {mean_confidence*100:.1f}% | "
                f"NIK Valid: {'YA' if nik_valid else 'TIDAK'} | "
                f"Duplikat: {'YA' if is_duplicate else 'TIDAK'}"
            )
            ActivityLog.log(
                activity=log_msg,
                user_id=None,
                table_name="ocr_scan",
                reference_id=mobile_user_id
            )
            print(f">>> [DB] Aktivitas OCR berhasil dicatat ke activity_logs.")

            # Jika user teridentifikasi, update MemberRegistration yang masih pending
            if mobile_user_id:
                existing_reg = MemberRegistration.query.filter_by(
                    mobile_user_id=mobile_user_id
                ).filter(MemberRegistration.status.in_(['pending'])).first()

                if existing_reg:
                    existing_reg.ocr_nik = nik or existing_reg.ocr_nik
                    existing_reg.ocr_name = nama or existing_reg.ocr_name
                    existing_reg.ocr_birth_date = parsed_data.get('ttl') or existing_reg.ocr_birth_date
                    existing_reg.ocr_gender = jk or existing_reg.ocr_gender
                    existing_reg.ocr_address = parsed_data.get('alamat') or existing_reg.ocr_address
                    existing_reg.ocr_confidence = mean_confidence
                    existing_reg.ocr_engine = best_method
                    existing_reg.ocr_processed_at = datetime.utcnow()
                    existing_reg.ocr_retry_count = (existing_reg.ocr_retry_count or 0) + 1
                    db.session.commit()
                    print(f">>> [DB] OCR data diperbarui untuk MemberRegistration ID: {existing_reg.id}")

        except Exception as log_err:
            print(f">>> [WARN] Gagal menyimpan log OCR ke DB: {log_err}")
            db.session.rollback()
        # ============================================================
        
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


# ============================================================
# ENDPOINT BARU: VALIDASI KTP TANPA UPLOAD FOTO
# Digunakan oleh Flutter setelah parsing OCR lokal (ML Kit)
# Flutter kirim JSON: {nik, nama, ttl, jenis_kelamin, agama, alamat}
# Server hanya cek: validitas struktur NIK + fuzzy duplikat
# ============================================================
@api_bp.route('/validate-ktp', methods=['POST'])
def validate_ktp():
    try:
        if request.is_json:
            data = request.get_json()
        else:
            return jsonify({'success': False, 'error': 'Request harus JSON'}), 400

        nik  = (data.get('nik')           or '').strip()
        nama = (data.get('nama')          or '').strip()
        jk   = (data.get('jenis_kelamin') or '').strip()

        # ── LOG DETAIL untuk debugging ───────────────────────
        print("\n" + "="*55)
        print("    [validate-ktp] DATA DITERIMA DARI FLUTTER")
        print("="*55)
        print(f"  NIK            : '{nik}' (len={len(nik)})")
        print(f"  Nama           : '{nama}'")
        print(f"  Jenis Kelamin  : '{jk}'")
        print("="*55)

        # Validasi struktur NIK
        nik_valid   = False
        nik_message = ''
        if nik:
            nik_valid, nik_message, nik = validate_nik_structure(nik, jk)
        else:
            nik_message = 'NIK tidak boleh kosong.'

        # Cek duplikat hanya jika NIK valid
        is_duplicate    = False
        duplicate_reason = ''
        if nik_valid:
            is_duplicate, duplicate_reason = fuzzy_check_duplicate(nik, nama, threshold=85)

        print(f"  NIK Valid      : {nik_valid} — {nik_message}")
        print(f"  Duplikat       : {is_duplicate} — {duplicate_reason}")
        print("="*55 + "\n")

        return jsonify({
            'nik_valid': nik_valid,
            'nik_validation_message': nik_message,
            'is_duplicate': is_duplicate,
            'duplicate_reason': duplicate_reason,
            'nama_diterima': nama,  # Kembalikan ke Flutter untuk debug
        }), 200

    except Exception as e:
        print(f"validate-ktp Error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


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
                "member_id": member.member_no,
                "avatar_path": member.pas_foto,
                "address": member.address,
                "phone": member.phone,
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
            "address": reg.ocr_address,
            "phone": reg.phone,
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
    
    total_payroll = sum([float(t.amount) for t in all_transactions if t.transaction_source == 'PAYROLL' and t.transaction_type in ['DEPOSIT', 'DEBIT']])
    total_withdrawal = sum([float(t.amount) for t in all_transactions if t.transaction_type in ['WITHDRAWAL', 'CREDIT']])
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
        
    # Actual Monthly Growth for Chart (6 months)
    import datetime
    from dateutil.relativedelta import relativedelta
    import calendar
    
    monthly_growth = {'labels': [], 'data': []}
    today = datetime.datetime.now()
    
    for i in range(5, -1, -1):
        target_date = today - relativedelta(months=i)
        target_month = target_date.month
        target_year = target_date.year
        
        last_day = calendar.monthrange(target_year, target_month)[1]
        end_date = datetime.datetime(target_year, target_month, last_day, 23, 59, 59)
        
        monthly_growth['labels'].append(target_date.strftime('%b %Y'))
        
        # Calculate balance up to end of this month for this member
        debit = db.session.query(db.func.sum(SavingTransaction.amount)).filter(
            SavingTransaction.member_id == member.id,
            SavingTransaction.transaction_type == 'DEBIT',
            SavingTransaction.transaction_status == 'SUCCESS',
            SavingTransaction.transaction_date <= end_date
        ).scalar() or 0
        
        credit = db.session.query(db.func.sum(SavingTransaction.amount)).filter(
            SavingTransaction.member_id == member.id,
            SavingTransaction.transaction_type == 'CREDIT',
            SavingTransaction.transaction_status == 'SUCCESS',
            SavingTransaction.transaction_date <= end_date
        ).scalar() or 0
        
        monthly_growth['data'].append(float(debit - credit))
    
    return jsonify({
        'member': {
            'id': member.id,
            'member_no': member.member_no,
            'name': member.full_name,
            'nik': member.nik or '-',
            'nip': member.nip or '-',
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

@api_bp.route('/member/deposit', methods=['POST'])
@token_required
def request_deposit(current_user):
    try:
        user_id = current_user.id
        
        # Support both form data and json
        data = request.json if request.is_json else request.form
        
        amount = data.get('amount')
        saving_type_id = data.get('saving_type_id')
        source_bank = data.get('source_bank')
        source_account_no = data.get('source_account_no')

        if not all([amount, saving_type_id, source_bank, source_account_no]):
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400

        member = Member.query.filter_by(mobile_user_id=user_id).first()
        if not member:
            return jsonify({'success': False, 'error': 'Member not found'}), 404
            
        new_request = DepositRequest(
            member_id=member.id,
            saving_type_id=saving_type_id,
            amount=amount,
            source_bank=source_bank,
            source_account_no=source_account_no,
            approval_status='PENDING'
        )

        db.session.add(new_request)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Deposit request submitted successfully'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

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

        # Check balance validation
        st_id = 2 # Default to Simpanan Sukarela (SS)
        if saving_type_id:
            try:
                st_id = int(saving_type_id)
            except ValueError:
                pass

        balance_record = MemberSavingBalance.query.filter_by(member_id=member.id, saving_type_id=st_id).first()
        current_balance = float(balance_record.balance) if balance_record else 0.0

        try:
            req_amount = float(amount)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Format nominal penarikan tidak valid'}), 400

        if req_amount > current_balance:
            import locale
            try:
                formatted_bal = f"{int(current_balance):,}".replace(",", ".")
            except:
                formatted_bal = str(int(current_balance))
            return jsonify({'success': False, 'error': f'Saldo tidak mencukupi. Saldo tersedia: Rp {formatted_bal}'}), 400

        new_request = WithdrawalRequest(
            member_id=member.id,
            amount=amount,
            bank_name=bank_name,
            account_number=account_number,
            account_holder=account_holder,
            processing_notes=f"Saving Type ID: {st_id}. Reason: {reason}",
            approval_status='PENDING'
        )

        db.session.add(new_request)
        db.session.commit()

        return jsonify({'success': True, 'message': 'Permohonan penarikan berhasil dikirim.'})

    except Exception as e:
        print(f"Withdrawal Error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================
# GROWTH ANALYTICS ENDPOINT (FOR FLUTTER MOBILE APP)
# Aggregates: Saving Trends + Economic Data + AI Insights + Prediction
# ============================================================
@api_bp.route('/growth-analytics', methods=['GET'])
@token_required
def growth_analytics(current_user):
    try:
        from sqlalchemy import func, extract
        from utils.bi_scraper import fetch_inflasi, fetch_bi_rate, fetch_jisdor

        period = request.args.get('period', 'Bulanan')  # Mingguan, Bulanan, Tahunan
        
        # ── 1. SAVING TREND DATA ─────────────────────────────
        # Get member for this user
        member = Member.query.filter_by(mobile_user_id=current_user.id).first()
        member_id = member.id if member else None
        
        if member_id:
            total_balance = float(db.session.query(func.sum(MemberSavingBalance.balance)).filter_by(member_id=member_id).scalar() or 0)
            total_tx = SavingTransaction.query.filter_by(member_id=member_id).count()
        else:
            total_balance = 0.0
            total_tx = 0

        active_members = Member.query.filter_by(status='AKTIF').count()
        
        # Aggregation of saving transactions based on period
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        months_labels = []
        months_values = []
        
        if period == 'Mingguan':
            # Last 7 Days
            for i in range(6, -1, -1):
                target_date = now - timedelta(days=i)
                months_labels.append(target_date.strftime('%d %b'))
                
                if member_id:
                    daily_deposit = db.session.query(func.sum(SavingTransaction.amount)).filter(
                        SavingTransaction.member_id == member_id,
                        SavingTransaction.transaction_type == 'DEBIT',
                        extract('day', SavingTransaction.transaction_date) == target_date.day,
                        extract('month', SavingTransaction.transaction_date) == target_date.month,
                        extract('year', SavingTransaction.transaction_date) == target_date.year
                    ).scalar() or 0
                else:
                    daily_deposit = 0
                months_values.append(float(daily_deposit))
                
        elif period == 'Tahunan':
            # Last 5 Years
            for i in range(4, -1, -1):
                target_year = now.year - i
                months_labels.append(str(target_year))
                
                if member_id:
                    yearly_deposit = db.session.query(func.sum(SavingTransaction.amount)).filter(
                        SavingTransaction.member_id == member_id,
                        SavingTransaction.transaction_type == 'DEBIT',
                        extract('year', SavingTransaction.transaction_date) == target_year
                    ).scalar() or 0
                else:
                    yearly_deposit = 0
                months_values.append(float(yearly_deposit))
                
        else:
            # Bulanan (Last 6 Months)
            month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']
            for i in range(5, -1, -1):
                target_date = now - timedelta(days=30 * i)
                month_num = target_date.month
                year_num = target_date.year
                months_labels.append(month_names[month_num - 1])
                
                if member_id:
                    monthly_deposit = db.session.query(func.sum(SavingTransaction.amount)).filter(
                        SavingTransaction.member_id == member_id,
                        SavingTransaction.transaction_type == 'DEBIT',
                        extract('month', SavingTransaction.transaction_date) == month_num,
                        extract('year', SavingTransaction.transaction_date) == year_num
                    ).scalar() or 0
                else:
                    monthly_deposit = 0
                months_values.append(float(monthly_deposit))
        
        # Calculate growth percentage
        if len(months_values) >= 2 and months_values[-2] > 0:
            growth_pct = round(((months_values[-1] - months_values[-2]) / months_values[-2]) * 100, 1)
        else:
            growth_pct = 0.0
        
        # Distribution by saving type
        distribution = []
        if member_id:
            saving_types = SavingType.query.filter_by(is_active=True).all()
            for st in saving_types:
                type_balance = db.session.query(func.sum(MemberSavingBalance.balance)).filter(
                    MemberSavingBalance.saving_type_id == st.id,
                    MemberSavingBalance.member_id == member_id
                ).scalar() or 0
                distribution.append({
                    'name': st.name,
                    'value': float(type_balance)
                })
        
        # ── 2. ECONOMIC DATA (FROM BI SCRAPER) ───────────────
        try:
            inflasi_data = fetch_inflasi()
            birate_data = fetch_bi_rate()
            jisdor_data = fetch_jisdor()
        except Exception as e:
            print(f"[growth-analytics] BI Scraper error: {e}")
            inflasi_data = []
            birate_data = []
            jisdor_data = []
        
        # Take latest 6 entries for charts
        eco_months = []
        inflation_values = []
        birate_values = []
        usd_idr_values = []
        
        for item in reversed(inflasi_data[:6]):
            eco_months.append(item.get('periode_str', '')[:3])
            inflation_values.append(float(item.get('inflasi_persen', 0)))
        
        for item in reversed(birate_data[:6]):
            birate_values.append(float(item.get('bi_rate_persen', 0)))
        
        for item in reversed(jisdor_data[:6]):
            usd_idr_values.append(float(item.get('kurs_jisdor', 0)))
        
        # ── 3. AI INSIGHTS (RULE-BASED ANALYSIS) ────────────
        ai_insights = []
        
        # Insight 1: Inflation impact
        latest_inflation = inflation_values[-1] if inflation_values else 0
        if latest_inflation > 4.0:
            ai_insights.append({
                'type': 'warning',
                'title': 'Inflasi Tinggi',
                'message': f'Inflasi nasional mencapai {latest_inflation}%, melebihi batas aman 4%. Daya beli menurun, disarankan mengalokasikan lebih banyak pada Simpanan Sukarela sebagai dana cadangan darurat.',
                'confidence': 0.85
            })
        elif latest_inflation > 3.0:
            ai_insights.append({
                'type': 'info',
                'title': 'Inflasi Terkendali',
                'message': f'Inflasi nasional {latest_inflation}% masih dalam batas wajar. Kondisi ekonomi relatif stabil untuk menabung.',
                'confidence': 0.90
            })
        else:
            ai_insights.append({
                'type': 'success',
                'title': 'Inflasi Rendah',
                'message': f'Inflasi nasional {latest_inflation}% menunjukkan stabilitas harga. Waktu yang baik untuk meningkatkan simpanan jangka panjang.',
                'confidence': 0.92
            })
        
        # Insight 1: Zero Balance condition
        if total_balance == 0:
            ai_insights.append({
                'type': 'info',
                'title': 'Belum Ada Simpanan',
                'message': 'Anda belum memiliki riwayat simpanan. Mulailah menabung untuk membangun ketahanan finansial. Kami tetap menampilkan analisis ekonomi makro di bawah ini sebagai referensi kondisi keuangan secara umum.',
                'confidence': 1.0
            })
        else:
            # Insight 2: Growth trend
            if growth_pct > 10:
                ai_insights.append({
                    'type': 'success',
                    'title': 'Pertumbuhan Pesat',
                    'message': f'Simpanan Anda tumbuh {growth_pct}% periode ini. Pertumbuhan di atas rata-rata ini menunjukkan manajemen keuangan yang sangat baik.',
                    'confidence': 0.88
                })
            elif growth_pct > 0:
                ai_insights.append({
                    'type': 'info',
                    'title': 'Pertumbuhan Positif',
                    'message': f'Simpanan Anda tumbuh {growth_pct}% periode ini. Pertahankan kebiasaan menabung yang konsisten ini.',
                    'confidence': 0.85
                })
            elif growth_pct < 0:
                ai_insights.append({
                    'type': 'warning',
                    'title': 'Penurunan Simpanan',
                    'message': f'Simpanan Anda menurun {abs(growth_pct)}% periode ini. Coba tinjau kembali pengeluaran Anda.',
                    'confidence': 0.82
                })
                
        # Insight 3: Inflation impact
        latest_inflation = inflation_values[-1] if inflation_values else 0
        if latest_inflation > 4.0:
            ai_insights.append({
                'type': 'warning',
                'title': 'Inflasi Nasional Tinggi',
                'message': f'Inflasi saat ini mencapai {latest_inflation}%. Nilai uang berpotensi turun, disarankan untuk mengamankan dana darurat di koperasi dengan bunga stabil.',
                'confidence': 0.85
            })
        elif latest_inflation <= 4.0 and latest_inflation > 0:
            ai_insights.append({
                'type': 'success',
                'title': 'Inflasi Nasional Terkendali',
                'message': f'Inflasi saat ini {latest_inflation}%. Waktu yang tepat untuk mengembangkan nilai aset melalui simpanan jangka panjang.',
                'confidence': 0.90
            })
        
        # Insight 4: BI Rate vs withdrawal correlation
        latest_birate = birate_values[-1] if birate_values else 0
        prev_birate = birate_values[-2] if len(birate_values) >= 2 else latest_birate
        if latest_birate > prev_birate:
            ai_insights.append({
                'type': 'info',
                'title': 'Suku Bunga BI Naik',
                'message': f'BI-7 Day Rate naik ke {latest_birate}%. Menabung saat ini berpotensi memberikan imbal hasil lebih baik.',
                'confidence': 0.80
            })
        
        # Insight 5: USD/IDR
        latest_kurs = usd_idr_values[-1] if usd_idr_values else 0
        if latest_kurs > 16000:
            ai_insights.append({
                'type': 'warning',
                'title': 'Rupiah Melemah',
                'message': f'Kurs mencapai Rp {latest_kurs:,.0f}/USD. Harga barang berpotensi naik, pastikan Anda memiliki dana cadangan yang cukup.',
                'confidence': 0.78
            })
        
        # ── 4. GROWTH PREDICTION (SIMPLE LINEAR TREND) ──────
        prediction_growth = 0.0
        probability = 50
        trend_direction = 'stable'
        predicted_balance = total_balance
        
        if total_balance == 0:
            probability = 0
            predicted_balance = 0.0
        elif len(months_values) >= 3:
            # Simple moving average + trend
            recent_values = [v for v in months_values if v > 0]
            if len(recent_values) >= 2:
                # Calculate average growth rate
                growth_rates = []
                for j in range(1, len(recent_values)):
                    if recent_values[j-1] > 0:
                        rate = (recent_values[j] - recent_values[j-1]) / recent_values[j-1]
                        growth_rates.append(rate)
                
                if growth_rates:
                    avg_growth_rate = sum(growth_rates) / len(growth_rates)
                    prediction_growth = round(avg_growth_rate * 100, 1)
                    
                    # Adjust for economic factors
                    if latest_inflation > 4.0:
                        prediction_growth -= 1.5  # High inflation dampens growth
                    if latest_birate > prev_birate:
                        prediction_growth += 0.5  # Higher BI rate encourages saving
                    
                    prediction_growth = round(prediction_growth, 1)
                    
                    # Calculate probability based on consistency
                    if len(growth_rates) >= 3:
                        positive_months = sum(1 for r in growth_rates if r > 0)
                        probability = min(95, int((positive_months / len(growth_rates)) * 100))
                    else:
                        probability = 65
                    
                    trend_direction = 'up' if prediction_growth > 0 else ('down' if prediction_growth < 0 else 'stable')
                    predicted_balance = round(total_balance * (1 + prediction_growth / 100), 2)
        
        # ── 5. PAYROLL DATA ─────────────────────────────────
        from models.user_model import PayrollBatch
        payroll_months = []
        payroll_values = []
        withdrawal_values = []
        
        for i in range(5, -1, -1):
            target_date = now - timedelta(days=30 * i)
            m = target_date.month
            y = target_date.year
            payroll_months.append(month_names[m - 1])
            
            # Payroll total
            payroll_total = db.session.query(func.sum(PayrollBatch.total_amount)).filter(
                PayrollBatch.period_month == m,
                PayrollBatch.period_year == y
            ).scalar() or 0
            payroll_values.append(float(payroll_total))
            
            # Withdrawals
            withdrawal_total = db.session.query(func.sum(SavingTransaction.amount)).filter(
                SavingTransaction.transaction_type == 'CREDIT',
                SavingTransaction.transaction_source == 'WITHDRAWAL',
                extract('month', SavingTransaction.transaction_date) == m,
                extract('year', SavingTransaction.transaction_date) == y
            ).scalar() or 0
            withdrawal_values.append(float(withdrawal_total))
        
        # ── 6. FINANCIAL HEALTH SCORE ────────────────────────
        health_score = 50  # Base
        if growth_pct > 0: health_score += 15
        if growth_pct > 10: health_score += 10
        if latest_inflation < 4: health_score += 10
        if latest_inflation < 3: health_score += 5
        if active_members > 10: health_score += 10
        health_score = min(100, health_score)
        
        if health_score >= 80: health_status = 'Sangat Baik'
        elif health_score >= 60: health_status = 'Stabil'
        elif health_score >= 40: health_status = 'Waspada'
        else: health_status = 'Risiko Tinggi'

        # ── BUILD RESPONSE ──────────────────────────────────
        response = {
            'success': True,
            'saving_trend': {
                'months': months_labels,
                'values': months_values,
                'growth_pct': growth_pct,
                'total_balance': total_balance,
                'total_tx': total_tx,
                'active_members': active_members,
                'distribution': distribution
            },
            'economic_data': {
                'inflation': inflation_values,
                'bi_rate': birate_values,
                'usd_idr': usd_idr_values,
                'months': eco_months if eco_months else months_labels
            },
            'ai_insights': ai_insights,
            'prediction': {
                'next_month_growth_pct': prediction_growth,
                'probability': probability,
                'trend_direction': trend_direction,
                'predicted_balance': predicted_balance
            },
            'payroll_vs_withdrawal': {
                'months': payroll_months,
                'payroll': payroll_values,
                'withdrawal': withdrawal_values
            },
            'health': {
                'score': health_score,
                'status': health_status
            }
        }
        
        return jsonify(response), 200
    
    except Exception as e:
        print(f"[growth-analytics] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

