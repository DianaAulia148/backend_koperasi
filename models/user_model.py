from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

# -------------------------------------------------------------------
# ENTERPRISE BASE MIXIN (Soft Delete & Audit)
# -------------------------------------------------------------------
class SoftDeleteMixin:
    """Reusable abstraction for Soft Deletes"""
    deleted_at = db.Column(db.DateTime, nullable=True)

    def soft_delete(self):
        self.deleted_at = datetime.utcnow()
        db.session.add(self)
        db.session.commit()
        
    def restore(self):
        self.deleted_at = None
        db.session.add(self)
        db.session.commit()

    @classmethod
    def active(cls):
        """Active query helper: Example -> Model.active().all()"""
        return cls.query.filter(cls.deleted_at.is_(None))

# -------------------------------------------------------------------
# LEGACY & MODIFIED MASTER TABLES
# -------------------------------------------------------------------

class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100))
    employee_id = db.Column(db.String(50))
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(255))
    role = db.Column(db.String(50)) # Admin / Teller
    jabatan = db.Column(db.String(50)) # Ketua, Wakil, Sekretaris, Bendahara, Pengawas, Pegawai
    status = db.Column(db.String(50), default="AKTIF") # AKTIF / TIDAK AKTIF
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class MobileUser(db.Model):
    __tablename__ = "mobile_users"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True, nullable=True) # Ensure unique for login
    phone = db.Column(db.String(20), unique=True, nullable=True)
    password = db.Column(db.String(255))
    google_id = db.Column(db.String(100))
    status = db.Column(db.String(50), default="AKTIF")
    is_verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class MemberRegistration(SoftDeleteMixin, db.Model):
    __tablename__ = "member_registration"
    id = db.Column(db.Integer, primary_key=True)
    mobile_user_id = db.Column(db.Integer, db.ForeignKey('mobile_users.id'))
    phone = db.Column(db.String(20))
    status = db.Column(db.String(20), default="pending") # Legacy status
    rejection_reason = db.Column(db.Text) 
    
    # [DEPRECATED] Legacy Paths untuk file upload (dipertahankan agar tidak break sistem lama)
    path_ktp = db.Column(db.String(255))
    path_kartu_karyawan = db.Column(db.String(255))
    path_pas_foto = db.Column(db.String(255))
    path_tanda_tangan = db.Column(db.String(255))

    # --- ENTERPRISE ENHANCEMENTS (V4) ---
    registration_code = db.Column(db.String(50), unique=True)
    document_type = db.Column(db.String(50)) # e.g. KTP, PASSPORT
    
    # OCR Data
    ocr_name = db.Column(db.String(100))
    ocr_nik = db.Column(db.String(20))
    ocr_nip = db.Column(db.String(50))
    ocr_jabatan = db.Column(db.String(100))
    ocr_birth_date = db.Column(db.String(50))
    ocr_gender = db.Column(db.String(20))
    ocr_address = db.Column(db.Text)
    ocr_raw_text = db.Column(db.Text)
    ocr_confidence = db.Column(db.Float) # Float instead of Decimal
    ocr_engine = db.Column(db.String(50))
    ocr_processed_at = db.Column(db.DateTime, nullable=True)
    ocr_retry_count = db.Column(db.Integer, default=0)
    
    # Fraud Detection
    fraud_score = db.Column(db.Float, default=0.0)
    suspicious_reason = db.Column(db.Text)
    blacklist_match = db.Column(db.Boolean, default=False)
    
    # Status & Audit
    duplicate_check_status = db.Column(db.String(20), default="PENDING") # CLEAN, SUSPICIOUS, DUPLICATED
    duplicate_reference_id = db.Column(db.Integer, nullable=True) # Refers to members.id if duplicated
    verification_status = db.Column(db.String(20), default="PENDING") # PENDING, PARTIAL, VERIFIED
    approval_status = db.Column(db.String(20), default="PENDING") # PENDING, APPROVED, REJECTED
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # deleted_at from SoftDeleteMixin
    
    mobile_user = db.relationship('MobileUser', backref=db.backref('registrations', lazy=True))
    approver = db.relationship('User', foreign_keys=[approved_by], backref='audit_registrations')
    documents = db.relationship('MemberDocument', backref='registration', lazy=True)

class OcrLog(db.Model):
    __tablename__ = "ocr_logs"
    id = db.Column(db.Integer, primary_key=True)
    registration_id = db.Column(db.Integer, db.ForeignKey('member_registration.id'), nullable=False)
    field_name = db.Column(db.String(100))
    value_before = db.Column(db.Text)
    value_after = db.Column(db.Text)
    confidence_before = db.Column(db.Float)
    confidence_after = db.Column(db.Float)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    retry_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class RegistrationTimeline(db.Model):
    __tablename__ = "registration_timeline"
    id = db.Column(db.Integer, primary_key=True)
    registration_id = db.Column(db.Integer, db.ForeignKey('member_registration.id'), nullable=False)
    status = db.Column(db.String(50)) # e.g. UPLOADED, OCR_PROCESSED, DUPLICATE_CHECKED, MANUAL_REVIEW, APPROVED, REJECTED
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True) # ID Pengurus yang melakukan aksi
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Member(SoftDeleteMixin, db.Model):
    __tablename__ = "members"
    id = db.Column(db.Integer, primary_key=True)
    member_no = db.Column(db.String(50), unique=True, nullable=False)
    nip = db.Column(db.String(50), unique=True, nullable=True) # Added for payroll matching
    nik = db.Column(db.String(20), unique=True, nullable=True) # Added for KYC duplicate protection
    full_name = db.Column(db.String(100), nullable=False)
    jabatan = db.Column(db.String(100))
    birth_date = db.Column(db.Date)
    gender = db.Column(db.String(20)) # LAKI LAKI / PEREMPUAN
    phone = db.Column(db.String(20))
    email = db.Column(db.String(100))
    address = db.Column(db.Text)
    loan_limit = db.Column(db.Float, default=0)
    status = db.Column(db.String(50), default="AKTIF") # AKTIF / TIDAK AKTIF
    
    # E-KYC Visuals
    photo_profile = db.Column(db.String(255))
    pas_foto = db.Column(db.String(255)) # Pas Foto 3x4
    signature_path = db.Column(db.String(255))
    # Disbursement Details (For Withdrawals)
    bank_name = db.Column(db.String(100))
    bank_account_no = db.Column(db.String(100))
    bank_account_name = db.Column(db.String(100))

    date_joined = db.Column(db.DateTime, default=datetime.utcnow)
    mobile_user_id = db.Column(db.Integer, db.ForeignKey('mobile_users.id')) 
    # deleted_at from SoftDeleteMixin

# LEGACY Transaction Table (NOT MERGED)
class Transaction(db.Model):
    __tablename__ = "transactions"
    id = db.Column(db.Integer, primary_key=True)
    tx_id = db.Column(db.String(20))
    name = db.Column(db.String(100))
    tx_type = db.Column(db.String(20))
    amount = db.Column(db.Float)
    status = db.Column(db.String(50), default="Selesai")
    date = db.Column(db.DateTime, default=datetime.utcnow)

# -------------------------------------------------------------------
# ENTERPRISE LEDGER & PAYROLL SYSTEM (V4)
# -------------------------------------------------------------------

class MemberDocument(db.Model):
    __tablename__ = "member_documents"
    id = db.Column(db.Integer, primary_key=True)
    member_registration_id = db.Column(db.Integer, db.ForeignKey('member_registration.id'), nullable=False)
    document_type = db.Column(db.String(50)) # KTP, KK, KARTU_KARYAWAN, PAS_FOTO, TANDA_TANGAN
    file_path = db.Column(db.String(255), nullable=False)
    file_name = db.Column(db.String(255))
    file_size = db.Column(db.Integer)
    is_verified = db.Column(db.Boolean, default=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    verified_at = db.Column(db.DateTime, nullable=True)

class SavingType(db.Model):
    __tablename__ = "saving_types"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True)
    name = db.Column(db.String(100))
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)

class MemberSavingBalance(db.Model):
    __tablename__ = "member_saving_balances"
    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False)
    saving_type_id = db.Column(db.Integer, db.ForeignKey('saving_types.id'), nullable=False)
    balance = db.Column(db.Numeric(15, 2), default=0.00)
    
    # Optimistic Locking setup for financial transaction safety
    version_number = db.Column(db.Integer, nullable=False, default=1)
    
    last_transaction_at = db.Column(db.DateTime, nullable=True)
    last_updated_by = db.Column(db.String(50), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __mapper_args__ = {
        'version_id_col': version_number
    }

class SavingTransaction(SoftDeleteMixin, db.Model):
    __tablename__ = "saving_transactions"
    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False)
    payroll_batch_detail_id = db.Column(db.Integer, db.ForeignKey('payroll_batch_details.id'), nullable=True)
    saving_type_id = db.Column(db.Integer, db.ForeignKey('saving_types.id'), nullable=False)
    
    transaction_type = db.Column(db.String(20)) # DEBIT, CREDIT
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    balance_before = db.Column(db.Numeric(15, 2), nullable=False)
    balance_after = db.Column(db.Numeric(15, 2), nullable=False)
    transaction_source = db.Column(db.String(50)) # PAYROLL, WITHDRAWAL, MANUAL, ADJUSTMENT, OCR_VALIDATION
    reference_number = db.Column(db.String(100), unique=True, nullable=False)
    transaction_date = db.Column(db.DateTime, default=datetime.utcnow)
    description = db.Column(db.Text)
    
    transaction_status = db.Column(db.String(20), default="SUCCESS") # PENDING, SUCCESS, FAILED, REVERSED
    processed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    processed_at = db.Column(db.DateTime, default=datetime.utcnow)
    reversal_reference_id = db.Column(db.String(100), nullable=True)
    
    # New Fields for Detailed Ledger
    source_bank = db.Column(db.String(100), nullable=True)
    source_account = db.Column(db.String(100), nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    member = db.relationship('Member', backref=db.backref('saving_transactions', lazy=True))
    saving_type = db.relationship('SavingType', backref='transactions')
    # deleted_at from SoftDeleteMixin

class PayrollBatch(SoftDeleteMixin, db.Model):
    __tablename__ = "payroll_batches"
    id = db.Column(db.Integer, primary_key=True)
    batch_code = db.Column(db.String(50), unique=True, nullable=False)
    period_month = db.Column(db.Integer)
    period_year = db.Column(db.Integer)
    uploaded_file = db.Column(db.String(255))
    total_members = db.Column(db.Integer, default=0)
    total_amount = db.Column(db.Numeric(15, 2), default=0.00)
    transfer_amount = db.Column(db.Numeric(15, 2), default=0.00)
    validation_status = db.Column(db.String(20), default="PENDING") # PENDING, PROCESSING, SUCCESS, FAILED
    distribution_status = db.Column(db.String(20), default="PENDING") # PENDING, PROCESSING, SUCCESS, FAILED
    
    # Financial Idempotency Protection System
    distribution_lock = db.Column(db.Boolean, default=False)
    distribution_hash = db.Column(db.String(128), unique=True, nullable=True)
    distribution_started_at = db.Column(db.DateTime, nullable=True)
    distribution_completed_at = db.Column(db.DateTime, nullable=True)
    
    # Monitoring
    success_count = db.Column(db.Integer, default=0)
    failed_count = db.Column(db.Integer, default=0)
    processing_notes = db.Column(db.Text)
    
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime, nullable=True)
    # deleted_at from SoftDeleteMixin
    
    uploader = db.relationship('User', foreign_keys=[uploaded_by], backref='payroll_batches')
    details = db.relationship('PayrollBatchDetail', backref='batch', lazy='dynamic')

class PayrollBatchDetail(db.Model):
    __tablename__ = "payroll_batch_details"
    id = db.Column(db.Integer, primary_key=True)
    payroll_batch_id = db.Column(db.Integer, db.ForeignKey('payroll_batches.id'), nullable=False)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False)
    saving_type_id = db.Column(db.Integer, db.ForeignKey('saving_types.id'), nullable=False)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    distribution_status = db.Column(db.String(20), default="PENDING") # PENDING, SUCCESS, FAILED
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class OcrTransferResult(db.Model):
    __tablename__ = "ocr_transfer_results"
    id = db.Column(db.Integer, primary_key=True)
    payroll_batch_id = db.Column(db.Integer, db.ForeignKey('payroll_batches.id'), nullable=False, unique=True)
    image_path = db.Column(db.String(255))
    bank_name = db.Column(db.String(100))
    transfer_amount = db.Column(db.Numeric(15, 2))
    transfer_date = db.Column(db.Date)
    reference_number = db.Column(db.String(100))
    ocr_raw_text = db.Column(db.Text)
    ocr_confidence = db.Column(db.Float)
    
    ocr_status = db.Column(db.String(20), default="PENDING") # PENDING, PROCESSING, SUCCESS, FAILED, MANUAL_REVIEW
    validation_status = db.Column(db.String(20), default="PENDING")
    manual_review_required = db.Column(db.Boolean, default=False)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class WithdrawalRequest(SoftDeleteMixin, db.Model):
    __tablename__ = "withdrawal_requests"
    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    bank_name = db.Column(db.String(100))
    account_number = db.Column(db.String(50))
    account_holder = db.Column(db.String(100))
    request_date = db.Column(db.Date, default=datetime.utcnow)
    approval_status = db.Column(db.String(20), default="PENDING") # PENDING, APPROVED, REJECTED
    rejection_reason = db.Column(db.Text)
    
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    
    processed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    processing_notes = db.Column(db.Text)
    transfer_reference_number = db.Column(db.String(100), nullable=True)
    transfer_proof = db.Column(db.String(255))
    saving_transaction_id = db.Column(db.Integer, db.ForeignKey('saving_transactions.id'), nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    member = db.relationship('Member', backref=db.backref('withdrawal_requests', lazy=True))
    # deleted_at from SoftDeleteMixin

class DepositRequest(SoftDeleteMixin, db.Model):
    __tablename__ = "deposit_requests"
    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False)
    saving_type_id = db.Column(db.Integer, db.ForeignKey('saving_types.id'), nullable=False)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    
    # Proof of transfer
    proof_image = db.Column(db.String(255))
    source_bank = db.Column(db.String(100))
    source_account_no = db.Column(db.String(50))
    source_account_name = db.Column(db.String(100))
    
    approval_status = db.Column(db.String(20), default="PENDING") # PENDING, APPROVED, REJECTED
    rejection_reason = db.Column(db.Text)
    
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    member = db.relationship('Member', backref=db.backref('deposit_requests', lazy=True))
    saving_type = db.relationship('SavingType')
    # deleted_at from SoftDeleteMixin

class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=False)
    title = db.Column(db.String(255))
    message = db.Column(db.Text)
    notification_type = db.Column(db.String(50))
    notification_channel = db.Column(db.String(20), default="PUSH") # PUSH, EMAIL, WHATSAPP, SMS
    notification_status = db.Column(db.String(20), default="PENDING") # PENDING, SENT, READ, FAILED
    
    is_read = db.Column(db.Boolean, default=False)
    sent_at = db.Column(db.DateTime, nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)
    failed_reason = db.Column(db.Text)
    retry_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ActivityLog(db.Model):
    __tablename__ = "activity_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    activity = db.Column(db.String(255))
    table_name = db.Column(db.String(100))
    reference_id = db.Column(db.Integer)
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @staticmethod
    def log(activity, user_id=None, table_name=None, reference_id=None):
        from flask import request
        try:
            new_log = ActivityLog(
                user_id=user_id,
                activity=activity,
                table_name=table_name,
                reference_id=reference_id,
                ip_address=request.remote_addr
            )
            db.session.add(new_log)
            db.session.commit()
        except Exception as e:
            print(f"Error logging activity: {e}")
            db.session.rollback()

class OTPVerification(db.Model):
    __tablename__ = "otp_verifications"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), nullable=False)
    otp_code = db.Column(db.String(6), nullable=False)
    purpose = db.Column(db.String(50)) # registration / forgot_password
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)

# -------------------------------------------------------------------
# ENTERPRISE ANALYTICS & ECONOMIC DATA (V5)
# -------------------------------------------------------------------

class EconomicIndicator(db.Model):
    __tablename__ = "economic_indicators"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    inflation_rate = db.Column(db.Float)
    bi_rate = db.Column(db.Float)
    usd_idr = db.Column(db.Float)
    source = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class RegionalSalaryData(db.Model):
    __tablename__ = "regional_salary_data"
    id = db.Column(db.Integer, primary_key=True)
    province = db.Column(db.String(100))
    city = db.Column(db.String(100))
    umr = db.Column(db.Numeric(15, 2))
    year = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class EconomicAnalysisLog(db.Model):
    __tablename__ = "economic_analysis_logs"
    id = db.Column(db.Integer, primary_key=True)
    analysis_type = db.Column(db.String(100)) # e.g. TREND_SIMPANAN, KORELASI_EKONOMI
    result_summary = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)