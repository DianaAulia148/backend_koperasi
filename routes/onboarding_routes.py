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
    
    # Base query for master queue (hide APPROVED as they go to Members table)
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
    else:
        # Default: only show PENDING in the main queue
        query = query.filter(MemberRegistration.approval_status == 'PENDING')

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
    rejected_count = MemberRegistration.query.filter_by(approval_status='REJECTED').count()
    approved_count = MemberRegistration.query.filter_by(approval_status='APPROVED').count()

    return render_template('onboarding/registration.html',
                           current_user=current_user,
                           registrations=registrations,
                           pagination=pagination,
                           search_query=search_query,
                           status_filter=status_filter,
                           duplicate_filter=duplicate_filter,
                           pending_count=pending_count,
                           rejected_count=rejected_count,
                           approved_count=approved_count,
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
                    member_registration_id=reg.id,
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
    
    # Fallback to legacy paths stored in MemberRegistration from mobile API
    if 'KTP' not in doc_dict and reg.path_ktp:
        doc_dict['KTP'] = reg.path_ktp
    if 'KARTU_KARYAWAN' not in doc_dict and reg.path_kartu_karyawan:
        doc_dict['KARTU_KARYAWAN'] = reg.path_kartu_karyawan
    if 'PAS_FOTO' not in doc_dict and reg.path_pas_foto:
        doc_dict['PAS_FOTO'] = reg.path_pas_foto
    if 'TANDA_TANGAN' not in doc_dict and reg.path_tanda_tangan:
        doc_dict['TANDA_TANGAN'] = reg.path_tanda_tangan
    
    timeline = RegistrationTimeline.query.filter_by(member_registration_id=reg.id).order_by(RegistrationTimeline.created_at.desc()).all()
    ocr_logs = []
    
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
        member_registration_id=reg.id,
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
    
    from routes.auth_routes import parse_ocr_date
    birth_date_val = parse_ocr_date(reg.ocr_birth_date)
    
    # Check for duplicate NIK or NIP to prevent IntegrityError (500)
    if reg.ocr_nik:
        existing_nik = Member.query.filter_by(nik=reg.ocr_nik).first()
        if existing_nik:
            flash(f"Gagal menyetujui: NIK {reg.ocr_nik} sudah terdaftar pada anggota lain.", "error")
            return redirect(request.referrer or url_for('onboarding.registration'))
            
    if reg.ocr_nip:
        existing_nip = Member.query.filter_by(nip=reg.ocr_nip).first()
        if existing_nip:
            flash(f"Gagal menyetujui: NIP {reg.ocr_nip} sudah terdaftar pada anggota lain.", "error")
            return redirect(request.referrer or url_for('onboarding.registration'))
    
    new_member = Member(
        member_no=member_no,
        nik=reg.ocr_nik,
        nip=reg.ocr_nip,
        full_name=reg.ocr_name or (mobile_user.full_name if mobile_user else "Unknown"),
        jabatan=reg.ocr_jabatan,
        birth_date=birth_date_val,
        gender=reg.ocr_gender,
        phone=reg.phone,
        email=email,
        address=reg.ocr_address,
        mobile_user_id=reg.mobile_user_id,
        status="AKTIF",
        pas_foto=reg.path_pas_foto,
        signature_path=reg.path_tanda_tangan,
        bank_name=reg.bank_name,
        bank_account_number=reg.bank_account_number
    )
    db.session.add(new_member)
    db.session.flush() # Get new_member ID
    
    # Initialize basic saving balances for the new member
    from models.user_model import SavingType, MemberSavingBalance, DepositRequest
    saving_types = SavingType.query.all()
    for st in saving_types:
        balance = MemberSavingBalance(
            member_id=new_member.id,
            saving_type_id=st.id,
            balance=0
        )
        db.session.add(balance)
        
        # Buat tagihan setoran otomatis (PENDING) jika tipe simpanan sama dengan form registrasi
        if getattr(reg, 'savings_amount', None) and getattr(reg, 'savings_amount') > 0 and st.name == getattr(reg, 'savings_type', ''):
            initial_deposit = DepositRequest(
                member_id=new_member.id,
                saving_type_id=st.id,
                amount=reg.savings_amount,
                source_bank=getattr(reg, 'bank_name', None),
                source_account_no=getattr(reg, 'bank_account_number', None),
                source_account_name=getattr(reg, 'ocr_name', None),
                approval_status='PENDING'
            )
            db.session.add(initial_deposit)

    # Update mobile user status
    if mobile_user:
        mobile_user.status = 'AKTIF'
        
    # Log Timeline
    timeline = RegistrationTimeline(
        member_registration_id=reg.id,
        status='APPROVED',
        notes=f'Pendaftaran disetujui. Member No: {member_no}',
        created_by=session.get('user_id')
    )
    db.session.add(timeline)
    
    member_name_log = reg.ocr_name or (mobile_user.full_name if mobile_user else "Unknown")
    ActivityLog.log(f"Approved Member Registration: {member_name_log}", user_id=session['user_id'], table_name="member_registration", reference_id=reg.id)
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
        member_registration_id=reg.id,
        status='REJECTED',
        notes=f'Pendaftaran ditolak. Alasan: {reason}',
        created_by=session['user_id']
    )
    db.session.add(timeline)
    
    mobile_user = MobileUser.query.get(reg.mobile_user_id) if reg.mobile_user_id else None
    member_name_log = reg.ocr_name or (mobile_user.full_name if mobile_user else "Unknown")
    ActivityLog.log(f"Rejected Member Registration: {member_name_log}", user_id=session['user_id'], table_name="member_registration", reference_id=reg.id)
    db.session.commit()
    
    flash(f"Pendaftaran ditolak: {reason}", "warning")
    return redirect(url_for('onboarding.registration_detail', reg_id=reg.id))

from models.user_model import ResignationRequest

@onboarding_bp.route('/resignations')
def resignations():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    
    current_user = User.query.get(session['user_id'])
    status_filter = request.args.get('status', 'PENDING')
    
    query = ResignationRequest.query
    if status_filter:
        query = query.filter_by(status=status_filter)
        
    requests = query.order_by(ResignationRequest.created_at.desc()).all()
    
    return render_template('onboarding/resignations.html',
                           current_user=current_user,
                           requests=requests,
                           status_filter=status_filter,
                           active_menu='resignations',
                           page_title='Pengajuan Keluar Anggota')

@onboarding_bp.route('/resignations/<int:req_id>/approve', methods=['POST'])
def approve_resignation(req_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
        
    req = ResignationRequest.query.get_or_404(req_id)
    if req.status != 'PENDING':
        return jsonify({'success': False, 'message': 'Hanya pengajuan PENDING yang dapat disetujui'}), 400
        
    transfer_proof = request.files.get('transfer_proof')
    if not transfer_proof:
        return jsonify({'success': False, 'message': 'Bukti transfer sisa simpanan wajib diunggah'}), 400
        
    # Save proof (simplified)
    import os
    proof_path = os.path.join('uploads', f'proof_{req_id}_{transfer_proof.filename}')
    transfer_proof.save(proof_path)
    
    req.status = 'APPROVED'
    req.transfer_proof = proof_path
    req.approved_by = session['user_id']
    req.approved_at = datetime.utcnow()
    
    # Generate Form Mengundurkan Diri DOCX
    import os
    import docx
    try:
        template_path = os.path.join('templates', 'docs', 'Form-Mengundurkan-Diri-Template.docx')
        doc = docx.Document(template_path)
        
        replacements = {
            'N a m a\t:': f'N a m a\t: {req.member.full_name if req.member else ""}',
            'N IPY\t:': f'N IPY\t: {req.nipy}',
            'No. Anggota Koperasi\t:': f'No. Anggota Koperasi\t: {req.member.member_no if req.member else ""}',
            'Jabatan / Departemen\t:': f'Jabatan / Departemen\t: {req.jabatan}',
            'Lokasi Kerja / Site\t:': f'Lokasi Kerja / Site\t: {req.lokasi_kerja}',
            'mulai bulan  .......................': f'mulai bulan {req.effective_month}',
            'Bank :\n\t........': f'Bank : {req.bank_name}',
            'Nomor Rekening :': f'Nomor Rekening : {req.bank_account_number}',
            'Atas nama\t:': f'Atas nama\t: {req.bank_account_name}',
        }
        
        # simple replacement logic
        for p in doc.paragraphs:
            for key, val in replacements.items():
                if key in p.text:
                    p.text = p.text.replace(key, val)
                    
        # generate filename
        member_no = req.member.member_no if req.member else str(req.id)
        out_filename = f'Form_Resign_{member_no}.docx'
        out_path = os.path.join('uploads', out_filename)
        doc.save(out_path)
        req.document_url = f'/api/membership/resign/document/{out_filename}'
    except Exception as e:
        print("Error generating docx:", str(e))
        pass # If fails, just continue
        
    db.session.commit()
    
    # Activity Log
    ActivityLog.log(f"Resignation approved for {req.member.full_name if req.member else 'Unknown'}", user_id=session['user_id'], table_name="resignation_requests", reference_id=req.id)
    
    if req.member:
        from models.user_model import Notification
        notif = Notification(
            member_id=req.member.id,
            title="Pengajuan Keluar Anggota Disetujui",
            message="Pengajuan pengunduran diri Anda telah disetujui oleh pengurus. Silakan cek status keanggotaan Anda.",
            notification_type="SYSTEM",
            is_read=False
        )
        db.session.add(notif)
        db.session.commit()
    

    return jsonify({'success': True, 'message': 'Pengajuan berhasil disetujui.'})

@onboarding_bp.route('/resignations/<int:req_id>/reject', methods=['POST'])
def reject_resignation(req_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
        
    req = ResignationRequest.query.get_or_404(req_id)
    if req.status != 'PENDING':
        return jsonify({'success': False, 'message': 'Hanya pengajuan PENDING yang dapat ditolak'}), 400
    data = request.get_json(silent=True) or request.form
    reason = data.get('reason', 'Tidak ada alasan yang diberikan.')
        
    req.status = 'REJECTED'
    req.approved_by = session['user_id']
    req.approved_at = datetime.utcnow()
    # If the model has rejection_reason we could save it, otherwise just in log.
    
    db.session.commit()
    
    # Notify user via Notification if mobile_user_id can be found
    if req.member:
        mobile_user_id = None
        from models.user_model import MemberRegistration
        reg = MemberRegistration.query.filter_by(ocr_nik=req.member.nik).first()
        if not reg:
            reg = MemberRegistration.query.filter_by(ocr_nip=req.member.nip).first()
        if reg:
            mobile_user_id = reg.mobile_user_id
            
        if req.member:
            from models.user_model import Notification
            notif = Notification(
                member_id=req.member.id,
                title="Pengajuan Pengunduran Diri Ditolak",
                message=f"Pengajuan pengunduran diri Anda telah ditolak. Alasan: {reason}",
                notification_type="SYSTEM",
                is_read=False
            )
            db.session.add(notif)
            db.session.commit()
    
    ActivityLog.log(f"Resignation rejected for {req.member.full_name if req.member else 'Unknown'}", user_id=session['user_id'], table_name="resignation_requests", reference_id=req.id)
    
    return jsonify({'success': True, 'message': 'Pengajuan berhasil ditolak.'})
