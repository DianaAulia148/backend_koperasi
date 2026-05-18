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

@api_bp.route('/ocr', methods=['POST'])
def process_ocr():
    # Cek apakah ada file yang dikirim
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    # Simpan file
    file_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(file_path)

    # --- BAGIAN OCR ---
    mock_ocr_data = {
        "nama": "BUDI SANTOSO",
        "nik": "3275012345678901",
        "ttl": "Jakarta, 01-01-1990",
        "jenis_kelamin": "Laki-laki",
        "agama": "Islam",
        "alamat": "Jl. Contoh No. 123, Jakarta"
    }

    return jsonify(mock_ocr_data), 200

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

