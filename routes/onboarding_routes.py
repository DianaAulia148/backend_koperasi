from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, current_app
from models.user_model import db, User, MemberRegistration, Member, MobileUser, MemberDocument, OcrLog, RegistrationTimeline, ActivityLog
from datetime import datetime
from sqlalchemy import func
import random

onboarding_bp = Blueprint('onboarding', __name__)

@onboarding_bp.route('/registration')
def registration():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    current_user = User.query.get(session['user_id'])
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('search', '').strip()
    status_filter = request.args.get('status', '')
    duplicate_filter = request.args.get('duplicate', '')
    
    # Base query for master queue
    query = MemberRegistration.query
    
    # Apply filters
    if search_query:
        query = query.filter(
            (MemberRegistration.ocr_name.ilike(f'%{search_query}%')) |
            (MemberRegistration.ocr_nik.ilike(f'%{search_query}%')) |
            (MemberRegistration.registration_code.ilike(f'%{search_query}%'))
        )
    if status_filter:
        query = query.filter_by(approval_status=status_filter)
    if duplicate_filter:
        if duplicate_filter == 'CLEAN':
            query = query.filter_by(duplicate_check_status='CLEAN')
        else:
            query = query.filter(MemberRegistration.duplicate_check_status != 'CLEAN')
            
    # Filter: Data Pending Review (User Logic)
    review_needed = request.args.get('review_needed', '0')
    if review_needed == '1':
        query = query.filter(
            MemberRegistration.approval_status == 'PENDING',
            (
                (MemberRegistration.ocr_confidence < 0.75) |
                (MemberRegistration.duplicate_check_status != 'CLEAN') |
                (MemberRegistration.verification_status != 'VERIFIED')
            )
        )
    
    # Pagination
    pagination = query.order_by(MemberRegistration.created_at.desc()).paginate(page=page, per_page=15, error_out=False)
    registrations = pagination.items
    
    # Analytics Cards Data
    pending_count = MemberRegistration.query.filter_by(approval_status='PENDING').count()
    low_confidence_count = MemberRegistration.query.filter(
        MemberRegistration.approval_status == 'PENDING',
        MemberRegistration.ocr_confidence < 0.75
    ).count()
    duplicate_count = MemberRegistration.query.filter(
        MemberRegistration.approval_status == 'PENDING',
        MemberRegistration.duplicate_check_status != 'CLEAN'
    ).count()
    approved_today_count = MemberRegistration.query.filter(
        MemberRegistration.approval_status == 'APPROVED',
        func.date(MemberRegistration.approved_at) == datetime.now().date()
    ).count()

    return render_template('onboarding/registration.html',
                           current_user=current_user,
                           registrations=registrations,
                           pagination=pagination,
                           search_query=search_query,
                           status_filter=status_filter,
                           duplicate_filter=duplicate_filter,
                           pending_count=pending_count,
                           low_confidence_count=low_confidence_count,
                           duplicate_count=duplicate_count,
                           approved_today_count=approved_today_count,
                           active_menu='registration',
                           page_title='Antrean Pendaftaran')

@onboarding_bp.route('/registration/<int:reg_id>', methods=['GET', 'POST'])
def registration_detail(reg_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
        
    current_user = User.query.get(session['user_id'])
    reg = MemberRegistration.query.get_or_404(reg_id)
    
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'update':
            # Perform manual update
            fields_to_check = {
                'ocr_nik': 'NIK',
                'ocr_name': 'Nama',
                'ocr_nip': 'NIP',
                'ocr_jabatan': 'Jabatan',
                'ocr_gender': 'Gender',
                'ocr_birth_date': 'Tanggal Lahir',
                'ocr_address': 'Alamat'
            }
            
            changes_made = []
            for field, label in fields_to_check.items():
                old_val = getattr(reg, field)
                new_val = request.form.get(field, '').strip()
                if old_val != new_val:
                    setattr(reg, field, new_val)
                    # Log OCR Field Change
                    log = OcrLog(
                        registration_id=reg.id,
                        field_name=label,
                        value_before=old_val,
                        value_after=new_val,
                        confidence_before=reg.ocr_confidence,
                        confidence_after=1.0,
                        reviewer_id=current_user.id
                    )
                    db.session.add(log)
                    changes_made.append(f"{label} changed to '{new_val}'")
            
            if changes_made:
                # Re-evaluate duplicate check when NIK is changed manually
                new_nik = request.form.get('ocr_nik', '').strip()
                existing_member = None
                if new_nik:
                    existing_member = Member.query.filter_by(nik=new_nik).first()
                
                if existing_member:
                    reg.duplicate_check_status = 'DUPLICATED'
                    reg.duplicate_reference_id = existing_member.id
                else:
                    reg.duplicate_check_status = 'CLEAN'
                    reg.duplicate_reference_id = None
                
                # Update verification status to VERIFIED on manual save
                reg.verification_status = 'VERIFIED'
                
                # Log activity log
                ActivityLog.log(
                    activity=f"Manual Edit Details for Reg ID {reg.id}: {', '.join(changes_made)}",
                    user_id=current_user.id,
                    table_name="member_registration",
                    reference_id=reg.id
                )
                
                # Add a timeline event
                timeline_event = RegistrationTimeline(
                    registration_id=reg.id,
                    status='MANUAL_REVIEW',
                    notes=f"Data diedit manual oleh Pengurus: {', '.join(changes_made)}",
                    created_by=current_user.id
                )
                db.session.add(timeline_event)
                db.session.commit()
                flash("Data pendaftaran berhasil diperbarui secara manual.", "success")
            else:
                flash("Tidak ada perubahan data yang disimpan.", "info")
                
            return redirect(url_for('onboarding.registration_detail', reg_id=reg.id))

    documents = MemberDocument.query.filter_by(member_registration_id=reg.id).all()
    doc_dict = {doc.document_type: doc.file_path for doc in documents}
    
    timeline = RegistrationTimeline.query.filter_by(registration_id=reg.id).order_by(RegistrationTimeline.created_at.desc()).all()
    ocr_logs = OcrLog.query.filter_by(registration_id=reg.id).order_by(OcrLog.created_at.desc()).all()
    
    # Get duplicates if any
    duplicates = []
    if reg.duplicate_check_status != 'CLEAN' and reg.duplicate_reference_id:
        existing_member = Member.query.get(reg.duplicate_reference_id)
        if existing_member:
            duplicates.append(existing_member)
            
    # Get Activity Logs
    activity_logs = ActivityLog.query.filter_by(table_name='member_registration', reference_id=reg.id).order_by(ActivityLog.created_at.desc()).all()
            
    return render_template('onboarding/registration_detail.html',
                           current_user=current_user,
                           reg=reg,
                           doc_dict=doc_dict,
                           timeline=timeline,
                           ocr_logs=ocr_logs,
                           activity_logs=activity_logs,
                           duplicates=duplicates,
                           active_menu='registration',
                           page_title='Detail Antrean Pendaftaran')

@onboarding_bp.route('/registration/retry_ocr/<int:reg_id>', methods=['POST'])
def retry_ocr(reg_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
        
    current_user = User.query.get(session['user_id'])
    reg = MemberRegistration.query.get_or_404(reg_id)
    
    # Simulate OCR Re-Scan and improvement of confidence
    reg.ocr_retry_count = (reg.ocr_retry_count or 0) + 1
    reg.ocr_confidence = round(random.uniform(0.76, 0.95), 2)
    reg.verification_status = 'PARTIAL'
    
    # Log timeline event
    timeline_event = RegistrationTimeline(
        registration_id=reg.id,
        status='OCR_PROCESSED',
        notes=f"OCR Scan diulang (Scan #{reg.ocr_retry_count}). Confidence score: {round(reg.ocr_confidence*100, 1)}%",
        created_by=current_user.id
    )
    db.session.add(timeline_event)
    
    # Log activity log
    ActivityLog.log(
        activity=f"Retried OCR Scan for Reg ID {reg.id} (Scan #{reg.ocr_retry_count})",
        user_id=current_user.id,
        table_name="member_registration",
        reference_id=reg.id
    )
    
    db.session.commit()
    flash("Proses OCR Scan berhasil diulang.", "success")
    return redirect(url_for('onboarding.registration_detail', reg_id=reg.id))

@onboarding_bp.route('/registration/approve/<int:reg_id>', methods=['POST'])
def approve_registration(reg_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
        
    reg = MemberRegistration.query.get_or_404(reg_id)
    reg.approval_status = 'APPROVED'
    reg.status = 'approved' # Legacy field
    reg.approved_by = session['user_id']
    reg.approved_at = datetime.utcnow()
    
    # Create actual Member
    # Check if mobile_user exists
    mobile_user = MobileUser.query.get(reg.mobile_user_id)
    email = mobile_user.email if mobile_user else None
    
    # Generate Member Number (Simple example)
    member_no = f"M-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    new_member = Member(
        member_no=member_no,
        nik=reg.ocr_nik,
        nip=reg.ocr_nip,
        full_name=reg.ocr_name,
        jabatan=reg.ocr_jabatan,
        gender=reg.ocr_gender,
        phone=reg.phone,
        email=email,
        address=reg.ocr_address,
        mobile_user_id=reg.mobile_user_id,
        status="AKTIF",
        pas_foto=reg.path_pas_foto,
        signature_path=reg.path_tanda_tangan
    )
    db.session.add(new_member)
    db.session.flush() # Get new_member ID
    
    # Initialize basic saving balances for the new member
    from models.user_model import SavingType, MemberSavingBalance
    saving_types = SavingType.query.all()
    for st in saving_types:
        balance = MemberSavingBalance(
            member_id=new_member.id,
            saving_type_id=st.id,
            balance=0
        )
        db.session.add(balance)

    # Update mobile user status
    if mobile_user:
        mobile_user.status = 'AKTIF'
        
    # Log Timeline
    timeline = RegistrationTimeline(
        registration_id=reg.id,
        status='APPROVED',
        notes=f'Pendaftaran disetujui. Member No: {member_no}',
        created_by=session.get('user_id')
    )
    db.session.add(timeline)
    
    ActivityLog.log(f"Approved Member Registration: {reg.ocr_name}", user_id=session['user_id'], table_name="member_registration", reference_id=reg.id)
    db.session.commit()
    
    flash("Pendaftaran berhasil disetujui. Anggota baru telah ditambahkan.", "success")
    return redirect(url_for('onboarding.registration_detail', reg_id=reg.id))

@onboarding_bp.route('/registration/reject/<int:reg_id>', methods=['POST'])
def reject_registration(reg_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
        
    reason = request.form.get('rejection_reason', 'Dokumen tidak valid')
    reg = MemberRegistration.query.get_or_404(reg_id)
    reg.approval_status = 'REJECTED'
    reg.status = 'rejected' # Legacy
    reg.rejection_reason = reason
    reg.approved_by = session['user_id']
    reg.approved_at = datetime.utcnow()
    
    # Log Timeline
    timeline = RegistrationTimeline(
        registration_id=reg.id,
        status='REJECTED',
        notes=f'Pendaftaran ditolak. Alasan: {reason}',
        created_by=session['user_id']
    )
    db.session.add(timeline)
    
    ActivityLog.log(f"Rejected Member Registration: {reg.ocr_name}", user_id=session['user_id'], table_name="member_registration", reference_id=reg.id)
    db.session.commit()
    
    flash(f"Pendaftaran ditolak: {reason}", "warning")
    return redirect(url_for('onboarding.registration_detail', reg_id=reg.id))
