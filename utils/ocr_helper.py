import easyocr
import cv2
import numpy as np
import re
import os
from datetime import date
import logging

# Set up logging for OCR
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cache reader instance globally so it doesn't load model on every request
_reader = None

def get_ocr_reader():
    global _reader
    if _reader is None:
        logger.info("Memuat model EasyOCR (hanya sekali saat pertama dipanggil)...")
        _reader = easyocr.Reader(['en', 'id'])
    return _reader

def preprocess_ktp(img_path):
    img = cv2.imread(img_path)
    if img is None:
        raise ValueError("Gambar tidak dapat dibaca oleh OpenCV.")
        
    img_resized = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(img_resized, cv2.COLOR_BGR2GRAY)
    denoised = cv2.fastNlMeansDenoising(gray, h=10)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(denoised)
    _, thresh = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # Simpan hasil preprocessing ke lokasi sementara jika diperlukan easyocr (bisa juga dilewatkan sebagai numpy array ke easyocr)
    temp_path = img_path + "_preprocessed.jpg"
    cv2.imwrite(temp_path, thresh)
    return temp_path

def parse_ktp(results):
    # Simpan teks beserta confidence score
    text_conf = [(text, prob) for (_, text, prob) in results]
    raw_text  = ' '.join([t for t, _ in text_conf])
    raw_upper = raw_text.upper()

    ktp_data  = {}
    conf_data = {}

    def get_conf_for(keyword):
        scores = [prob for text, prob in text_conf if keyword.lower() in text.lower()]
        return round(sum(scores) / len(scores) * 100, 1) if scores else 0.0

    # NIK
    nik = re.search(r'\b(\d{16})\b', raw_text)
    ktp_data['nik'] = nik.group(1) if nik else None

    # NAMA
    nama = None
    m1 = re.search(r'(?:^|\s)Nama\s*[:\-]?\s*([A-Z][A-Z\s]{2,})', raw_text, re.IGNORECASE)
    if m1:
        nama = m1.group(1).strip()
    if not nama:
        for i, (text, prob) in enumerate(text_conf):
            if re.match(r'^Nama$', text.strip(), re.IGNORECASE):
                for j in range(i+1, min(i+4, len(text_conf))):
                    candidate = text_conf[j][0].strip()
                    if re.match(r'^[A-Z][A-Z\s]{2,}$', candidate):
                        nama = candidate
                        break
                break
    ktp_data['nama'] = nama

    # Tempat Lahir
    tempat = re.search(
        r'(?:Tempat|Temp[a-z]+)\s*[/\s]*(?:Tgl\.?|Tanggal)?\s*(?:Lahir)?\s*[:\-]?\s*([A-Z][A-Z\s,]+?)(?:\d{2}-|\s{2,}|$)',
        raw_text, re.IGNORECASE)
    ktp_data['tempat_lahir'] = tempat.group(1).strip().rstrip(',') if tempat else None

    # Tanggal Lahir
    tgl = re.search(r'(\d{2}-\d{2}-\d{4})', raw_text)
    ktp_data['ttl'] = tgl.group(1) if tgl else None

    # Jenis Kelamin
    if 'PEREMPUAN' in raw_upper:
        ktp_data['jenis_kelamin'] = 'PEREMPUAN'
    elif 'LAKI' in raw_upper:
        ktp_data['jenis_kelamin'] = 'LAKI-LAKI'
    else:
        ktp_data['jenis_kelamin'] = None

    # Gol Darah
    gol = re.search(r'(?:Gol\.?\s*Darah|Darah)\s*[:\-]?\s*([ABO]{1,2}[+-]?)', raw_text, re.IGNORECASE)
    ktp_data['gol_darah'] = gol.group(1).strip() if gol else None

    # Alamat
    alamat = re.search(r'Alamat\s*[:\-]?\s*([A-Z0-9][^\n]+?)(?:RT|RW|Kel|$)', raw_text, re.IGNORECASE)
    alamat_str = alamat.group(1).strip() if alamat else None
    
    rtrw = re.search(r'(\d{3})[/\\](\d{3})', raw_text)
    rtrw_str = f"RT/RW {rtrw.group(1)}/{rtrw.group(2)}" if rtrw else ""
    
    keldesa = re.search(r'(?:Kel|Desa)\s*[/\\]?\s*(?:Desa|Kel)?\s*[:\-]?\s*([A-Z][A-Z\s]+?)(?:\s{2,}|Kec|$)', raw_text, re.IGNORECASE)
    kel_str = f"Kel. {keldesa.group(1).strip()}" if keldesa else ""
    
    kec = re.search(r'Kecamatan\s*[:\-]?\s*([A-Z][A-Z\s]+?)(?:\s{2,}|Agama|$)', raw_text, re.IGNORECASE)
    kec_str = f"Kec. {kec.group(1).strip()}" if kec else ""
    
    # Gabung alamat (optional sesuai format yang diminta)
    parts = [p for p in [alamat_str, rtrw_str, kel_str, kec_str] if p]
    ktp_data['alamat'] = ", ".join(parts) if parts else None

    # Agama
    agama_list = ['ISLAM', 'KRISTEN', 'KATOLIK', 'HINDU', 'BUDDHA', 'KONGHUCU']
    found_agama = next((a for a in agama_list if a in raw_upper), None)
    ktp_data['agama'] = found_agama

    # Status Kawin
    if 'BELUM KAWIN' in raw_upper:
        ktp_data['status_perkawinan'] = 'BELUM KAWIN'
    elif 'KAWIN' in raw_upper:
        ktp_data['status_perkawinan'] = 'KAWIN'
    elif 'CERAI' in raw_upper:
        ktp_data['status_perkawinan'] = 'CERAI'
    else:
        ktp_data['status_perkawinan'] = None

    # Pekerjaan
    pekerjaan = re.search(r'Pekerjaan\s*[:\-]?\s*([A-Z][A-Z\s]+?)(?:\s{2,}|Kewarganegaraan|$)', raw_text, re.IGNORECASE)
    ktp_data['pekerjaan'] = pekerjaan.group(1).strip() if pekerjaan else None

    # Kewarganegaraan
    if 'WNI' in raw_upper:
        ktp_data['kewarganegaraan'] = 'WNI'
    elif 'WNA' in raw_upper:
        ktp_data['kewarganegaraan'] = 'WNA'
    else:
        ktp_data['kewarganegaraan'] = None

    return ktp_data

def process_ktp_image(file_path):
    temp_path = None
    try:
        # Preprocess
        temp_path = preprocess_ktp(file_path)
        
        # Load reader & extract text
        reader = get_ocr_reader()
        results = reader.readtext(temp_path)
        
        # Parse data
        ktp_data = parse_ktp(results)
        return ktp_data
    except Exception as e:
        logger.error(f"Gagal memproses KTP: {str(e)}")
        raise e
    finally:
        # Bersihkan file preprocessed jika ada
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
