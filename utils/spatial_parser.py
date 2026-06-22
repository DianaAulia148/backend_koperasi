import re
import difflib

def _fuzzy_clean_prefix(text, expected_labels):
    """Membersihkan typo awalan label secara hybrid (Fuzzy + Hardcoded)."""
    text = re.sub(r'^[:\-\.\s\/]+', '', text).strip()
    
    HARDCODED_TYPOS = {
        'ALAMAT': ['AMAL', 'MAL', 'ALA', 'ALM', 'ALMT', 'ALARNAT', 'ARNAT', 'RNAT'],
        'NAMA': ['NA', 'MA', 'AMA', 'NAM', 'NMA', 'VAMA', 'NANA', 'MAMA', 'VNA', 'NHA'],
        'TEMPAT': ['MPAT', 'PAT', 'TEMP', 'EMPAT', 'AT'],
        'KECAMATAN': ['ECAMATAN', 'CAMATAN', 'KEC', 'ECAM'],
        'KELURAHAN': ['EL', 'ESA', 'DESA', 'KEL', 'KELDESA', 'ELDESA'],
        'JENIS': ['NIS', 'ENIS', 'JNS', 'IS'],
        'KELAMIN': ['ELAMIN', 'LAMIN'],
        'TANGGAL': ['TGL', 'TANGGA'],
        'LAHIR': ['LAHI', 'AHIR', 'LHR']
    }
    
    changed = True
    while changed and text:
        changed = False
        tokens = re.split(r'[\s/:\-]+', text, maxsplit=1)
        if not tokens: break
        
        raw_first = tokens[0]
        first_word = re.sub(r'[^A-Z]', '', raw_first.upper())
        if not first_word: 
            text = tokens[1] if len(tokens) > 1 else ''
            text = re.sub(r'^[:\-\.\s\/]+', '', text).strip()
            changed = True
            continue
            
        for label in expected_labels:
            matched = False
            for label_part in label.upper().split():
                clean_label = re.sub(r'[^A-Z]', '', label_part)
                if not clean_label: continue
                
                # Aturan perlindungan kata pendek (TGL vs TEGAL)
                if len(clean_label) <= 3:
                    if first_word == clean_label:
                        matched = True
                        break
                    continue
                
                ratio = difflib.SequenceMatcher(None, first_word, clean_label).ratio()
                
                if (ratio >= 0.70 and len(first_word) >= 3) or \
                   (first_word in clean_label and len(first_word) >= 3 and clean_label != first_word):
                    matched = True
                    break
            
            if not matched:
                for real_label, typos in HARDCODED_TYPOS.items():
                    if real_label in label.upper() and first_word in typos:
                        matched = True
                        break
                        
            if matched:
                match_idx = text.upper().find(raw_first.upper())
                if match_idx != -1:
                    text = text[match_idx + len(raw_first):]
                    text = re.sub(r'^[:\-\.\s\/]+', '', text).strip()
                    changed = True
                    break
                    
    return text


# ============================================================================
# STABLE KTP PARSER — Row-Order Based
# ============================================================================
# Prinsip: SEMUA KTP Indonesia punya layout & urutan field IDENTIK.
# Urutan field setelah header:
#   NIK -> Nama -> Tempat/Tgl Lahir -> Jenis Kelamin -> Alamat ->
#   RT/RW -> Kel/Desa -> Kecamatan -> Agama -> Status Perkawinan ->
#   Pekerjaan -> Kewarganegaraan -> Berlaku Hingga
#
# Strategi:
#   1. Kelompokkan teks OCR ke BARIS berdasarkan overlap Y
#   2. Identifikasi tiap baris via label keyword
#   3. Jika label tidak terbaca, gunakan URUTAN POSISI dari baris NIK
#   4. Ekstrak nilai dari sisi kanan label
# ============================================================================

KTP_LABEL_WORDS = {
    'NIK', 'NAMA', 'TEMPAT', 'TGL', 'LAHIR', 'TANGGAL',
    'JENIS', 'KELAMIN', 'GOL', 'DARAH', 'ALAMAT', 'RT', 'RW',
    'KEL', 'DESA', 'KECAMATAN', 'KEC', 'AGAMA', 'STATUS',
    'PERKAWINAN', 'PEKERJAAN', 'KEWARGANEGARAAN', 'BERLAKU',
    'HINGGA', 'SEUMUR', 'HIDUP', 'PROVINSI', 'KABUPATEN',
    'KOTA', 'REPUBLIK', 'INDONESIA', 'KARTU', 'TANDA',
    'PENDUDUK', 'WNI', 'WNA',
}

# Urutan field KTP standar (setelah header provinsi/kota)
KTP_FIELD_ORDER = [
    'nik', 'nama', 'ttl', 'jk',
    'alamat', 'rtrw', 'keldesa', 'kecamatan',
    'agama', 'status', 'pekerjaan', 'warga', 'berlaku',
]

# Regex pattern untuk identifikasi label pada setiap baris
FIELD_PATTERNS = [
    ('nik',       r'\d{12,}'),
    ('nama',      r'\bNAMA\b|\bNAM[^A-Z]'),
    ('ttl',       r'TEMPAT|TGL|LAHIR|T\.TGL|TTL'),
    ('jk',        r'JENIS|KELAMIN|JNS'),
    ('alamat',    r'\bALAMAT\b|\bALMT\b'),
    ('rtrw',      r'\bRT\b.*\bRW\b|\bRT\s*/\s*RW'),
    ('keldesa',   r'\bKEL\b[^A-Z]|\bDESA\b|\bKEL/DESA\b|\bEL/DESA\b'),
    ('kecamatan', r'KECAMATAN|\bKEC\b[^A-Z]|\bECAMATAN\b|\bCAMATAN\b'),
    ('agama',     r'\bAGAMA\b'),
    ('status',    r'STATUS|PERKAWINAN'),
    ('pekerjaan', r'PEKERJAAN'),
    ('warga',     r'KEWARGANEGARAAN|WARGANEG'),
    ('berlaku',   r'BERLAKU|HINGGA|SEUMUR'),
]


def _is_label_text(text):
    """Cek apakah teks hanyalah label KTP (bukan nilai data)."""
    words = re.sub(r'[:\-\.\/]+', ' ', text.upper()).split()
    words = [w for w in words if len(w) > 1]
    if not words:
        return True
    label_count = sum(1 for w in words if w in KTP_LABEL_WORDS)
    return (label_count / len(words)) > 0.6


def _group_rows(blocks):
    """Kelompokkan blok ke dalam baris berdasarkan overlap Y ≥ 35%."""
    if not blocks:
        return []

    sorted_blocks = sorted(blocks, key=lambda b: (b['y_center'], b['min_x']))
    rows = []
    assigned = [False] * len(sorted_blocks)

    for i in range(len(sorted_blocks)):
        if assigned[i]:
            continue
        row = [sorted_blocks[i]]
        assigned[i] = True
        row_min_y = sorted_blocks[i]['min_y']
        row_max_y = sorted_blocks[i]['max_y']

        for j in range(i + 1, len(sorted_blocks)):
            if assigned[j]:
                continue
            b = sorted_blocks[j]
            overlap = min(row_max_y, b['max_y']) - max(row_min_y, b['min_y'])
            min_h = min(row_max_y - row_min_y, b['height'])
            if min_h > 0 and (overlap / min_h) >= 0.35:
                row.append(b)
                assigned[j] = True
                row_min_y = min(row_min_y, b['min_y'])
                row_max_y = max(row_max_y, b['max_y'])

        row.sort(key=lambda b: b['min_x'])
        rows.append(row)

    return rows


def _extract_value(row, label_patterns):
    """
    Ekstrak bagian NILAI dari sebuah baris.
    Label di sisi kiri, nilai di sisi kanan.
    """
    if not row:
        return ""

    # Cari tepi kanan blok-blok label
    label_max_x = 0
    for b in row:
        for pat in label_patterns:
            if re.search(pat, b['text']):
                label_max_x = max(label_max_x, b['max_x'])
                break

    if label_max_x > 0:
        value_blocks = [
            b for b in row
            if b['min_x'] >= label_max_x * 0.92
            and b['raw'] not in [':', '-', '.', ';']
            and not _is_label_text(b['text'])
        ]
        if value_blocks:
            val = ' '.join([b['raw'] for b in value_blocks])
            return re.sub(r'^[\s:\-\.;]+', '', val).strip()

    # Fallback: buang kata-kata label, ambil sisanya
    all_raw = [b['raw'] for b in row if b['raw'] not in [':', '-', '.', ';']]
    full = ' '.join(all_raw)
    for pat in label_patterns:
        full = re.sub(pat, '', full, flags=re.IGNORECASE)
    return re.sub(r'^[\s:\-\.;]+', '', full).strip()


def _extract_nik(raw_upper):
    """Ekstrak NIK 16 digit dengan koreksi karakter OCR."""
    cleaned = raw_upper.replace(" ", "")
    for old, new in [('O','0'),('I','1'),('L','1'),('S','5'),
                     ('B','8'),('Z','2'),('G','6'),('T','7'),
                     ('A','4'),('U','0'),('D','0')]:
        cleaned = cleaned.replace(old, new)
    m = re.search(r'(\d{16})', cleaned)
    if not m:
        m = re.search(r'(\d{15,17})', cleaned)
    return m.group(1) if m else ""


def _correct_nik_province(nik, raw_upper):
    """Auto-koreksi kode provinsi NIK berdasarkan teks KTP."""
    if not nik or len(nik) < 2:
        return nik
    PROV = {
        '33': (['JAWA TENGAH','JATENG','TEGAL','SEMARANG','SOLO','KUDUS','BREBES','PEKALONGAN'],
               ['22','23','25','27','28','32','35','37','38','53','55','57','58','73','77']),
        '32': (['JAWA BARAT','JABAR','BANDUNG','BOGOR','BEKASI','DEPOK','SUKABUMI'],
               ['22','23','52','72','37','57']),
        '35': (['JAWA TIMUR','JATIM','SURABAYA','MALANG'], ['25','55','75','85']),
        '36': (['BANTEN','TANGERANG','SERANG','CILEGON'], ['26','56','76','86']),
        '31': (['DKI JAKARTA','JAKARTA'], ['21','51','71','81']),
    }
    for kode, (keywords, wrong) in PROV.items():
        if any(kw in raw_upper for kw in keywords) and nik[0:2] in wrong:
            return kode + nik[2:]
    return nik


# ============================================================================
# MAIN PARSER
# ============================================================================
def spatial_parse_ktp(results):
    """
    Parser KTP stabil berbasis Row-Order.
    Menerima list of (box, text, confidence) dari PaddleOCR atau GCP Vision.
    """
    ktp_data = {
        'nik': '', 'nama': '', 'ttl': '',
        'jenis_kelamin': '', 'agama': '', 'alamat': '',
    }

    # ── TAHAP 1: Ekstrak blok teks + koordinat ──────────────────────
    blocks = []
    all_texts = []

    for box, text, conf in results:
        text_str = str(text).strip()
        all_texts.append(text_str)

        if box is None:
            continue
        try:
            if hasattr(box, '__len__') and len(box) == 0:
                continue
        except TypeError:
            pass

        try:
            box_list = list(box)
            if len(box_list) < 4:
                continue
            if hasattr(box_list[0], 'x'):  # GCP Vision
                xs = [v.x for v in box_list]
                ys = [v.y for v in box_list]
            else:  # PaddleOCR [[x,y],...]
                xs = [float(p[0]) for p in box_list]
                ys = [float(p[1]) for p in box_list]
            blocks.append({
                'raw': text_str, 'text': text_str.upper(),
                'min_x': min(xs), 'max_x': max(xs),
                'min_y': min(ys), 'max_y': max(ys),
                'y_center': (min(ys)+max(ys))/2,
                'height': max(ys)-min(ys),
            })
        except Exception as e:
            print(f">>> [WARN] Skip block: {e}")

    raw_text = ' '.join(all_texts)
    raw_upper = raw_text.upper()

    print(f">>> [STABLE] {len(blocks)} blocks, {len(all_texts)} texts total.")

    if not blocks:
        print(">>> [STABLE] No bbox -> regex fallback.")
        return _regex_fallback_parse(raw_text, raw_upper,
                                      [(t, 1.0) for t in all_texts])

    # ── TAHAP 2: Kelompokkan ke baris ───────────────────────────────
    rows = _group_rows(blocks)
    row_texts = [' '.join([b['text'] for b in r]) for r in rows]

    for idx, rt in enumerate(row_texts):
        print(f">>>   Row {idx:2d}: {rt}")

    # ── TAHAP 3: Identifikasi field per baris ───────────────────────
    row_field = {}  # row_idx -> field_name
    used_fields = set()

    for idx, rt in enumerate(row_texts):
        for field, pattern in FIELD_PATTERNS:
            if field in used_fields and field not in ('rtrw','keldesa','kecamatan'):
                continue
            if re.search(pattern, rt):
                row_field[idx] = field
                used_fields.add(field)
                break

    # Positional fallback: gunakan urutan baris NIK sebagai anchor
    nik_idx = next((i for i, f in row_field.items() if f == 'nik'), None)
    if nik_idx is not None:
        expected = nik_idx
        for field in KTP_FIELD_ORDER:
            if expected >= len(rows):
                break
            if expected not in row_field:
                row_field[expected] = field
            expected += 1

    # Debug
    print(">>> [STABLE] Field map:")
    for idx in sorted(row_field.keys()):
        if idx < len(row_texts):
            print(f">>>   Row {idx:2d} -> {row_field[idx]:12s} : {row_texts[idx][:60]}")

    # Helper: ambil row(s) untuk sebuah field
    def get_rows(field_name):
        return [idx for idx, f in row_field.items() if f == field_name]

    # ── TAHAP 4: Ekstrak setiap field ───────────────────────────────

    # ---- NIK ----
    ktp_data['nik'] = _extract_nik(raw_upper)
    ktp_data['nik'] = _correct_nik_province(ktp_data['nik'], raw_upper)

    # ---- NAMA ----
    nama_rows = get_rows('nama')
    nama = ''
    if nama_rows:
        nama = _extract_value(rows[nama_rows[0]], [r'\bNAMA\b', r'\bNAM\b', r'\b[VNM]AMA\b', r'\bAMA\b', r'\bMA\b'])
    
    nama = _fuzzy_clean_prefix(nama, ['NAMA'])
    nama = re.sub(r'(?i)\s*\b(TEMPAT|TGL|LAHIR|AGAMA|KELAMIN|JENIS|ALAMAT|GOL|DARAH|STATUS|PEKERJAAN)\b.*', '', nama).strip()
    nama = re.sub(r"[^A-Za-z\s\.'-]", '', nama).strip()
    # Fallback: regex dari raw_text
    if not nama:
        m = re.search(r'(?:NAMA|NAM)\s*[:\-]?\s*([A-Z][A-Z\s\.]{2,})', raw_upper)
        if m:
            nama = m.group(1).strip()
            nama = re.sub(r'(?i)\b(TEMPAT|TGL|LAHIR|AGAMA|KELAMIN|JENIS|ALAMAT)\b.*', '', nama).strip()
    ktp_data['nama'] = nama.title() if nama else ""

    # ---- TEMPAT / TGL LAHIR ----
    ttl_rows = get_rows('ttl')
    tempat = ''
    tanggal = ''
    if ttl_rows:
        val = _extract_value(rows[ttl_rows[0]],
                             [r'TEMPAT', r'TGL', r'LAHIR', r'TANGGAL', r'T\.TGL', r'TTL', r'MPAT', r'TGLLAHIR'])
        val = _fuzzy_clean_prefix(val, ['TEMPAT TANGGAL LAHIR'])
        
        # Pisahkan tempat (huruf) dan tanggal (angka)
        # Format umum: "TEGAL, 01-06-1998" atau "TEGAL 01-06-1998"
        m_tgl = re.search(r'(\d{2})[/\-](\d{2})[/\-](\d{4})', val)
        if m_tgl:
            tanggal = f"{m_tgl.group(1)}-{m_tgl.group(2)}-{m_tgl.group(3)}"
            # Tempat = bagian sebelum tanggal
            before = val[:m_tgl.start()]
            before = re.sub(r'[,\s:\-\.]+$', '', before).strip()
            before = re.sub(r'(?i)\b(LAHIR|TGL|TANGGAL)\b', '', before).strip()
            if len(before) >= 2 and re.match(r'^[A-Za-z]', before):
                tempat = before
        else:
            # Tidak ada tanggal di baris ini, mungkin hanya tempat
            kota_only = re.sub(r'(?i)\b(LAHIR|TGL|TANGGAL)\b', '', val).strip()
            kota_only = re.sub(r'[:\-\.]+', '', kota_only).strip()
            if len(kota_only) >= 2 and re.match(r'^[A-Za-z]', kota_only):
                tempat = kota_only

    # Fallback tanggal: cari DD-MM-YYYY atau DD/MM/YYYY di seluruh teks
    if not tanggal:
        for m in re.finditer(r'(\d{2})[/\-](\d{2})[/\-](\d{4})', raw_text):
            thn = int(m.group(3))
            if 1920 <= thn <= 2015:
                tanggal = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                break

    if tempat and tanggal:
        ktp_data['ttl'] = f"{tempat.title()}, {tanggal}"
    elif tanggal:
        ktp_data['ttl'] = tanggal
    else:
        ktp_data['ttl'] = ''

    # ---- JENIS KELAMIN ----
    if re.search(r'(?i)(PEREMPUAN|PERENPUAN|PEREMPIIAN|PREMPUAN)', raw_text):
        ktp_data['jenis_kelamin'] = 'Perempuan'
    elif re.search(r'(?i)\b(LAKI|LAK1|L4KI)\b', raw_text):
        ktp_data['jenis_kelamin'] = 'Laki-laki'

    # ---- AGAMA ----
    agama_map = {
        'Islam': ['ISLAM','ISLAN','ISLAH'],
        'Kristen': ['KRISTEN','KRISTAN'],
        'Katolik': ['KATOLIK'],
        'Hindu': ['HINDU'],
        'Buddha': ['BUDDHA','BUDHA'],
        'Konghucu': ['KONGHUCU','KHONGHUCU'],
    }
    for agama_name, aliases in agama_map.items():
        if any(a in raw_upper for a in aliases):
            ktp_data['agama'] = agama_name
            break

    # ---- ALAMAT (multi-baris: alamat + RT/RW + kel/desa + kecamatan) ----
    alamat_parts = []

    # Alamat utama
    alamat_rows = get_rows('alamat')
    if alamat_rows:
        al = _extract_value(rows[alamat_rows[0]], [r'\bALAMAT\b', r'\bALMT\b', r'\bAMAL\b', r'\bMAL\b', r'\bALARNAT\b'])
        al = _fuzzy_clean_prefix(al, ['ALAMAT'])
        if al:
            alamat_parts.append(al)
    else:
        # Fallback jika alamat tercampur di baris lain (misal di baris JK)
        m = re.search(r'(?:ALAMAT|ALARNAT|ALMT|AMAL|MAL)\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9\s\.\/]+?)(?:\s+(?:RT|RW|KEL|DESA|KEC|AGAMA|PEREMPUAN|LAKI))', raw_text, re.IGNORECASE)
        if m:
            al = m.group(1).strip()
            al = _fuzzy_clean_prefix(al, ['ALAMAT'])
            if al:
                alamat_parts.insert(0, al)

    # RT/RW
    rtrw_match = re.search(
        r'(?:RT|RFIRW|RTIRW)[/\\]?(?:RT|RW|RFIRW|RTIRW)?\s*[:\-]?\s*(\d{1,3})[/\\](\d{1,3})',
        raw_text, re.IGNORECASE)
    if rtrw_match:
        alamat_parts.append(f"RT/RW {rtrw_match.group(1).zfill(3)}/{rtrw_match.group(2).zfill(3)}")

    # Kel/Desa
    kel_rows = get_rows('keldesa')
    if kel_rows:
        kel = _extract_value(rows[kel_rows[0]], [r'\bKEL\b', r'\bDESA\b'])
        kel = _fuzzy_clean_prefix(kel, ['KELURAHAN DESA'])
        if kel:
            alamat_parts.append(f"Kel. {' '.join(kel.split()[:3])}")
    elif not kel_rows:
        m = re.search(r'(?:Kel|Desa|El/Desa)\s*[/\\]?\s*(?:Desa|Kel)?\s*[:\-]?\s*([A-Za-z][A-Za-z\s]+?)(?:\s{2,}|Kec|$)',
                       raw_text, re.IGNORECASE)
        if m:
            alamat_parts.append(f"Kel. {m.group(1).strip()}")

    # Kecamatan
    kec_rows = get_rows('kecamatan')
    if kec_rows:
        kec = _extract_value(rows[kec_rows[0]], [r'KECAMATAN', r'\bKEC\b', r'ECAMATAN', r'CAMATAN'])
        kec = _fuzzy_clean_prefix(kec, ['KECAMATAN'])
        if kec:
            alamat_parts.append(f"Kec. {kec}")
    elif not kec_rows:
        m = re.search(r'(?:Kecamatan|Ecamatan|Camatan|Kec\.?)\s*[:\-]?\s*([A-Za-z][A-Za-z\s]+?)(?:\s{2,}|Agama|Status|$)',
                       raw_text, re.IGNORECASE)
        if m:
            alamat_parts.append(f"Kec. {m.group(1).strip()}")

    ktp_data['alamat'] = ', '.join(alamat_parts)

    # ── Debug log ───────────────────────────────────────────────────
    print(f">>> [RESULT] NIK={ktp_data['nik']}, Nama={ktp_data['nama']}, "
          f"TTL={ktp_data['ttl']}, JK={ktp_data['jenis_kelamin']}, "
          f"Agama={ktp_data['agama']}, Alamat={ktp_data['alamat']}")

    return ktp_data


# ============================================================================
# REGEX FALLBACK (ketika tidak ada bounding box)
# ============================================================================
def _regex_fallback_parse(raw_text, raw_upper, text_conf):
    """Full regex fallback ketika bounding box tidak tersedia."""
    ktp_data = {}

    # === NIK ===
    ktp_data['nik'] = _extract_nik(raw_upper)

    # === NAMA ===
    nama = ""
    # Cari dengan mentoleransi typo NAMA, VAMA, NMA, MA, dll (pastikan itu kata utuh dengan \b)
    m_nama = re.search(r'(?:^|\s)\b(NAMA|NAM|VAMA|NMA|AMA|MA|NA)\b\s*[:\-]?\s*([A-Z][A-Za-z\s\.]{2,})', raw_text, re.IGNORECASE)
    if m_nama:
        nama = m_nama.group(2).strip()
        nama = re.sub(r'(?i)\b(Tempat|Mpat|Pat|Tgl|Lahir|Jenis|Kelamin|Agama|Alamat|Status|Pekerjaan)\b.*', '', nama).strip()
    if not nama:
        for i, (text, _) in enumerate(text_conf):
            if re.match(r'(?i)^(NAMA|NAM|VAMA|NMA|AMA|MA|NA)$', text.strip()):
                for j in range(i+1, min(i+4, len(text_conf))):
                    candidate = text_conf[j][0].strip()
                    if candidate in [':', '-', '.']:
                        continue
                    if (re.match(r'^[A-Z][A-Za-z\s\.]{2,}$', candidate)
                            and not re.search(r'(?i)(TEMPAT|LAHIR|AGAMA|ALAMAT|KELAMIN)', candidate)):
                        nama = candidate
                        break
                break
    ktp_data['nama'] = nama.title() if nama else ""

    # === TEMPAT / TANGGAL LAHIR ===
    ttl = ""
    tempat = re.search(
        r'\b(Tempat|Temp[a-z]+|Mpat|Pat|At)\b\s*[/\s]*(?:Tgl\.?|Tanggal)?\s*(?:Lahir)?\s*[:\-]?\s*([A-Za-z][A-Za-z\s,]+?)(?:\d{2}-|\s{2,}|$)',
        raw_text, re.IGNORECASE)
    tgl = re.search(r'(\d{2}-\d{2}-\d{4})', raw_text)
    if tempat and tgl:
        ttl = f"{tempat.group(2).strip().rstrip(',')}, {tgl.group(1)}"
    elif tgl:
        ttl = tgl.group(1)
    ktp_data['ttl'] = ttl

    # === JENIS KELAMIN ===
    if re.search(r'(?i)(PEREMPUAN|PERENPUAN|PEREMPIIAN)', raw_text):
        ktp_data['jenis_kelamin'] = 'Perempuan'
    elif re.search(r'(?i)\b(LAKI|LAK1|L4KI)\b', raw_text):
        ktp_data['jenis_kelamin'] = 'Laki-laki'
    else:
        ktp_data['jenis_kelamin'] = ""

    # === AGAMA ===
    agama_list = ['ISLAM','KRISTEN','KATOLIK','HINDU','BUDDHA','KONGHUCU']
    ktp_data['agama'] = next((a.capitalize() for a in agama_list if a in raw_upper), "")

    # === ALAMAT ===
    alamat_parts = []
    # Mentoleransi typo ALAMAT, ALARNAT, AMAL, MAL, dll
    alamat = re.search(r'\b(ALAMAT|ALARNAT|ALMT|AMAL|MAL)\b\s*[:\-]?\s*([A-Za-z0-9][^\n]+?)(?:RT|RW|Kel|Desa|Kec|$)', raw_text, re.IGNORECASE)
    if alamat:
        al = alamat.group(2).strip()
        al = _fuzzy_clean_prefix(al, ['ALAMAT'])
        if al:
            alamat_parts.append(al)
    rtrw = re.search(r'(\d{3})[/\\](\d{3})', raw_text)
    if rtrw:
        alamat_parts.append(f"RT/RW {rtrw.group(1)}/{rtrw.group(2)}")
    keldesa = re.search(r'\b(Kel|Desa|El/Desa|El/desa)\b\s*[/\\]?\s*(?:Desa|Kel)?\s*[:\-]?\s*([A-Za-z][A-Za-z\s]+?)(?:\s{2,}|Kec|Ecamatan|Camatan|$)', raw_text, re.IGNORECASE)
    if keldesa:
        kel = keldesa.group(2).strip()
        kel = _fuzzy_clean_prefix(kel, ['KELURAHAN DESA'])
        if kel:
            alamat_parts.append(f"Kel. {kel}")
    kec = re.search(r'\b(Kecamatan|Ecamatan|Camatan|Kec\.?)\b\s*[:\-]?\s*([A-Za-z][A-Za-z\s]+?)(?:\s{2,}|Agama|Islam|Kristen|Status|Erkawinan|$)', raw_text, re.IGNORECASE)
    if kec:
        kc = kec.group(2).strip()
        kc = _fuzzy_clean_prefix(kc, ['KECAMATAN'])
        if kc:
            alamat_parts.append(f"Kec. {kc}")
    ktp_data['alamat'] = ', '.join(alamat_parts) if alamat_parts else ""

    print(f">>> [FALLBACK] NIK={ktp_data.get('nik')}, Nama={ktp_data.get('nama')}, "
          f"TTL={ktp_data.get('ttl')}, JK={ktp_data.get('jenis_kelamin')}, Agama={ktp_data.get('agama')}, Alamat={ktp_data.get('alamat')}")
    return ktp_data
