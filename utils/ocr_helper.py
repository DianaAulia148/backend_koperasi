import cv2
import numpy as np
import re
import os
import logging
from ultralytics import YOLO

# Set up logging for OCR
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global instances
_paddle_ocr = None
_yolo_model = None

def get_paddle_ocr():
    global _paddle_ocr
    if _paddle_ocr is None:
        logger.info("Memuat model PaddleOCR...")
        # Matikan OneDNN/MKLDNN untuk mencegah C++ backend error di Windows
        os.environ['FLAGS_use_mkldnn'] = '0'
        # Import lazy to avoid slowing down startup if not used
        from paddleocr import PaddleOCR
        _paddle_ocr = PaddleOCR(use_angle_cls=True, lang='id', enable_mkldnn=False)
    return _paddle_ocr

def get_yolo_model():
    global _yolo_model
    if _yolo_model is None:
        yolo_path = os.path.join('runs', 'detect', 'ktp_model', 'weights', 'best.pt')
        if os.path.exists(yolo_path):
            logger.info("Memuat model YOLOv8 untuk deteksi KTP...")
            _yolo_model = YOLO(yolo_path)
        else:
            logger.info("Model YOLOv8 belum dilatih/tidak ditemukan. Menggunakan fallback ke seluruh gambar.")
            _yolo_model = "NOT_TRAINED"
    return _yolo_model

def preprocess_ktp(img_path):
    img = cv2.imread(img_path)
    if img is None:
        raise ValueError("Gambar tidak dapat dibaca oleh OpenCV.")
        
    yolo = get_yolo_model()
    if yolo != "NOT_TRAINED":
        # Gunakan YOLO untuk mendeteksi dan crop KTP
        results = yolo(img)
        # Jika ada deteksi
        if len(results) > 0 and len(results[0].boxes) > 0:
            box = results[0].boxes[0] # Ambil deteksi pertama dengan confidence tertinggi
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            img = img[y1:y2, x1:x2]
            logger.info("KTP berhasil di-crop menggunakan YOLOv8.")

    # Image enhancement
    img_resized = cv2.resize(img, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    
    # PaddleOCR bekerja dengan baik pada gambar RGB yang sudah jelas,
    # tetapi bisa juga dibantu dengan sedikit penajaman
    kernel = np.array([[0, -1, 0],
                       [-1, 5,-1],
                       [0, -1, 0]])
    sharpened = cv2.filter2D(img_resized, -1, kernel)

    temp_path = img_path + "_preprocessed.jpg"
    cv2.imwrite(temp_path, sharpened)
    return temp_path

def parse_ktp(results_paddle):
    # PaddleOCR output format:
    # [[[[x,y],[x,y],[x,y],[x,y]], ("text", confidence)], ...]
    
    # Ambil teks dan probabilitasnya
    text_conf = []
    if results_paddle and len(results_paddle) > 0 and results_paddle[0] is not None:
        for line in results_paddle[0]:
            try:
                # Format standar: line = [box, ('text', confidence)]
                if len(line) >= 2:
                    val = line[1]
                    if isinstance(val, (tuple, list)) and len(val) >= 2:
                        text_conf.append((str(val[0]), float(val[1])))
                    elif isinstance(val, str):
                        text_conf.append((val, 1.0))
            except Exception as e:
                logger.error(f"Error parsing line {line}: {e}")
                continue
                
    raw_text  = ' '.join([t for t, _ in text_conf])
    raw_upper = raw_text.upper()

    ktp_data  = {}

    # NIK
    nik = re.search(r'\b(\d{16})\b', raw_text)
    ktp_data['nik'] = nik.group(1) if nik else None

    # NAMA
    nama = None
    m1 = re.search(r'(?:^|\s)Nama\s*[:\-]?\s*([A-Z][A-Za-z\s]{2,})', raw_text, re.IGNORECASE)
    if m1:
        nama = m1.group(1).strip()
    if not nama:
        for i, (text, prob) in enumerate(text_conf):
            if re.match(r'^Nama$', text.strip(), re.IGNORECASE) or 'NAMA' in text.upper():
                for j in range(i+1, min(i+4, len(text_conf))):
                    candidate = text_conf[j][0].strip()
                    if re.match(r'^[A-Z][A-Za-z\s]{2,}$', candidate) and 'TEMPAT' not in candidate.upper() and 'LAHIR' not in candidate.upper():
                        nama = candidate
                        break
                break
    ktp_data['nama'] = nama

    # Tempat Lahir
    tempat = re.search(
        r'(?:Tempat|Temp[a-z]+)\s*[/\s]*(?:Tgl\.?|Tanggal)?\s*(?:Lahir)?\s*[:\-]?\s*([A-Za-z][A-Za-z\s,]+?)(?:\d{2}-|\s{2,}|$)',
        raw_text, re.IGNORECASE)
    ktp_data['tempat_lahir'] = tempat.group(1).strip().rstrip(',') if tempat else None

    # Tanggal Lahir
    tgl = re.search(r'(\d{2}-\d{2}-\d{4})', raw_text)
    ktp_data['ttl'] = tgl.group(1) if tgl else None

    # Jika ttl gabungan diminta
    if ktp_data.get('tempat_lahir') and ktp_data.get('ttl'):
        ktp_data['ttl_full'] = f"{ktp_data['tempat_lahir']}, {ktp_data['ttl']}"
    elif ktp_data.get('ttl'):
        ktp_data['ttl_full'] = ktp_data['ttl']

    # Jenis Kelamin
    if re.search(r'(?i)(PEREMPUAN|PERENPUAN)', raw_upper):
        ktp_data['jenis_kelamin'] = 'Perempuan'
    elif re.search(r'(?i)(LAKI|LAK1)', raw_upper):
        ktp_data['jenis_kelamin'] = 'Laki-laki'
    else:
        ktp_data['jenis_kelamin'] = None

    # Alamat
    alamat = re.search(r'Alamat\s*[:\-]?\s*([A-Za-z0-9][^\n]+?)(?:RT|RW|Kel|$)', raw_text, re.IGNORECASE)
    alamat_str = alamat.group(1).strip() if alamat else None
    
    rtrw = re.search(r'(\d{3})[/\\](\d{3})', raw_text)
    rtrw_str = f"RT/RW {rtrw.group(1)}/{rtrw.group(2)}" if rtrw else ""
    
    keldesa = re.search(r'(?:Kel|Desa)\s*[/\\]?\s*(?:Desa|Kel)?\s*[:\-]?\s*([A-Za-z][A-Za-z\s]+?)(?:\s{2,}|Kec|$)', raw_text, re.IGNORECASE)
    kel_str = f"Kel. {keldesa.group(1).strip()}" if keldesa else ""
    
    kec = re.search(r'Kecamatan\s*[:\-]?\s*([A-Za-z][A-Za-z\s]+?)(?:\s{2,}|Agama|$)', raw_text, re.IGNORECASE)
    kec_str = f"Kec. {kec.group(1).strip()}" if kec else ""
    
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
    pekerjaan = re.search(r'Pekerjaan\s*[:\-]?\s*([A-Za-z][A-Za-z\s]+?)(?:\s{2,}|Kewarganegaraan|$)', raw_text, re.IGNORECASE)
    ktp_data['pekerjaan'] = pekerjaan.group(1).strip() if pekerjaan else None

    ktp_data['ttl'] = ktp_data.get('ttl_full', ktp_data.get('ttl'))
    return ktp_data

def process_ktp_image(file_path):
    temp_path = None
    try:
        # Preprocess dengan YOLO crop (jika sudah di-train) + Penajaman
        temp_path = preprocess_ktp(file_path)
        
        # Ekstrak Teks Menggunakan PaddleOCR
        ocr = get_paddle_ocr()
        results = ocr.ocr(temp_path)
        
        # Parse data
        ktp_data = parse_ktp(results)
        return ktp_data
    except Exception as e:
        logger.error(f"Gagal memproses KTP: {str(e)}")
        raise e
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

def parse_ktp_to_flask_format(results_paddle):
    # Fungsi wrapper agar kompatibel dengan existing api_routes.py
    ktp_data = parse_ktp(results_paddle)
    return {
        'nik': ktp_data.get('nik', ''),
        'nama': ktp_data.get('nama', ''),
        'ttl': ktp_data.get('ttl_full', ''),
        'jenis_kelamin': ktp_data.get('jenis_kelamin', ''),
        'agama': ktp_data.get('agama', ''),
        'alamat': ktp_data.get('alamat', '')
    }
