# 📱 DOKUMENTASI API KOPERASI MOBILE

Selamat datang di Dokumentasi Resmi API Koperasi Mobile (Co-op Mobile API). Dokumentasi ini dirancang khusus untuk membantu para pengembang (terutama tim mobile Flutter) dalam mengintegrasikan aplikasi klien dengan server Flask backend Koperasi.

Semua endpoint API di bawah prefix `/api` memiliki performa tinggi, fitur validasi otomatis, sistem proteksi idempotensi keuangan, proteksi JWT, dan logger aktivitas terintegrasi.

---

## 🚀 PANDUAN CEPAT (QUICK START)

### 🔗 Informasi Server (Base URL)
* **Development (Local Host):** `http://127.0.0.1:5000`
* **Staging / Local Network IP:** `http://192.168.110.95:5000`
* **Production URL:** `https://api.coop-koperasi.co.id` (Contoh Produksi)

### 🔒 Protokol Keamanan (Otentikasi)
Sebagian besar API dilindungi dengan protokol **JSON Web Token (JWT)** berbasis standard industri.
Untuk mengakses endpoint terproteksi, Anda wajib melampirkan token JWT yang valid ke dalam header HTTP:
```http
Authorization: Bearer <your_jwt_token_here>
```

> [!IMPORTANT]
> Token JWT memiliki masa kadaluarsa **7 hari** setelah pembuatan. Aplikasi mobile disarankan untuk menyimpan token ini di dalam secure storage lokal (seperti `flutter_secure_storage`) dan melakukan redirect otomatis ke halaman Login jika server mengembalikan kode status `401 Unauthorized` (Token Expired/Invalid).

---

## 🛠️ VARIABEL LINGKUNGAN (POSTMAN ENVIRONMENT)

Untuk kenyamanan saat testing menggunakan koleksi Postman, gunakan variabel-variabel berikut di dalam **Postman Environment** Anda:

| Nama Variabel | Jenis | Deskripsi | Contoh Nilai |
| :--- | :--- | :--- | :--- |
| `base_url` | String | URL dasar server backend Flask | `http://127.0.0.1:5000` |
| `token` | Secret | JWT Token otentikasi (Otomatis terisi saat login) | `eyJhbGciOiJIUzI1NiIs...` |
| `user_id` | Integer | ID unik user aktif (untuk cek status pendaftaran) | `1` |

---

## 📂 DAFTAR ENDPOINT & SPESIFIKASI DETAIL

### 📦 1. Kategori: Autentikasi & Registrasi Akun

#### 🔵 POST `/api/register`
* **Deskripsi:** Mendaftarkan akun pengguna aplikasi mobile baru.
* **Autentikasi:** Terbuka untuk Umum (Public)
* **Content-Type:** `application/x-www-form-urlencoded` atau `multipart/form-data`

##### Parameter Request Body (Form-Data)
| Parameter | Tipe | Validasi | Deskripsi |
| :--- | :--- | :--- | :--- |
| `full_name` | String | Opsional | Nama lengkap calon pengguna. |
| `email` | String | **Wajib (Unik)** | Email aktif untuk menerima OTP. |
| `password` | String | **Wajib** | Kata sandi akun (Min. 12 karakter). |
| `phone` | String | Opsional | Nomor telepon aktif. |

##### Contoh Respons (200 OK - Pendaftaran Berhasil)
```json
{
  "success": true,
  "message": "Registrasi berhasil. Silakan cek email Anda untuk kode verifikasi.",
  "is_verified": false,
  "debug_otp": "654321"
}
```

##### Contoh Respons (400 Bad Request - Email Sudah Terdaftar)
```json
{
  "success": false,
  "error": "Email sudah terdaftar."
}
```

---

#### 🔵 POST `/api/verify-otp`
* **Deskripsi:** Memverifikasi pendaftaran akun menggunakan kode OTP yang dikirim ke email.
* **Autentikasi:** Terbuka untuk Umum (Public)
* **Content-Type:** `application/json` atau `application/x-www-form-urlencoded`

##### Parameter Request Body (JSON)
```json
{
  "email": "budi.santoso@gmail.com",
  "otp_code": "654321"
}
```

##### Contoh Respons (200 OK - Verifikasi Berhasil)
```json
{
  "success": true,
  "message": "Verifikasi berhasil. Silakan login."
}
```

##### Contoh Respons (400 Bad Request - OTP Gagal)
```json
{
  "success": false,
  "error": "Kode OTP salah atau sudah kadaluarsa."
}
```

---

#### 🔵 POST `/api/resend-otp`
* **Deskripsi:** Mengirim ulang kode verifikasi OTP baru ke email yang belum terverifikasi.
* **Autentikasi:** Terbuka untuk Umum (Public)
* **Content-Type:** `application/json` atau `application/x-www-form-urlencoded`

##### Parameter Request Body (JSON)
```json
{
  "email": "budi.santoso@gmail.com"
}
```

##### Contoh Respons (200 OK - OTP Baru Terkirim)
```json
{
  "success": true,
  "message": "Kode verifikasi baru telah dikirim ke email Anda.",
  "debug_otp": "987654"
}
```

---

#### 🔵 POST `/api/login`
* **Deskripsi:** Autentikasi akun mobile dan memperoleh JWT Token.
* **Autentikasi:** Terbuka untuk Umum (Public)
* **Content-Type:** `application/x-www-form-urlencoded` atau `application/json`

> [!TIP]
> **Postman Automation Tool:** Di dalam koleksi Postman yang kami sediakan, request **Login Akun** memiliki *Test Script* bawaan yang otomatis mengambil `token` dari respons JSON dan meng-update variabel environment `{{token}}`.

##### Parameter Request Body (Form-Data / JSON)
| Parameter | Tipe | Validasi | Deskripsi |
| :--- | :--- | :--- | :--- |
| `email` | String | **Wajib** | Alamat email terdaftar. |
| `password` | String | **Wajib** | Kata sandi akun. |

##### Contoh Respons (200 OK - Login Berhasil)
```json
{
  "success": true,
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoxLCJleHAiOjE3MTU5OTAwMDB9.EXAMPLE_SIGNATURE_KEY",
  "user": {
    "id": 1,
    "full_name": "Budi Santoso",
    "email": "budi.santoso@gmail.com",
    "is_verified": true
  }
}
```

##### Contoh Respons (403 Forbidden - Belum Verifikasi OTP)
```json
{
  "success": false,
  "error": "Akun Anda belum diverifikasi. Silakan cek email untuk kode OTP.",
  "needs_verification": true,
  "email": "budi.santoso@gmail.com"
}
```

##### Contoh Respons (401 Unauthorized - Kredensial Salah)
```json
{
  "success": false,
  "error": "Email atau password salah."
}
```

---

### 📦 2. Kategori: Pendaftaran Anggota (KYC)

#### 🔵 POST `/api/ocr`
* **Deskripsi:** Mengunggah gambar KTP fisik untuk diekstraksi datanya secara otomatis menggunakan modul OCR AI.
* **Autentikasi:** Terbuka untuk Umum (Public)
* **Content-Type:** `multipart/form-data`

##### Berkas Unggahan (Multipart Files)
* `file`: File foto KTP fisik (Format JPEG/PNG, biner).

##### Contoh Respons (200 OK - OCR Sukses)
```json
{
  "nama": "BUDI SANTOSO",
  "nik": "3275012345678901",
  "ttl": "Jakarta, 01-01-1990",
  "jenis_kelamin": "Laki-laki",
  "agama": "Islam",
  "alamat": "Jl. Contoh No. 123, RT 001/RW 002, Kel. Bekasi Jaya, Kec. Bekasi Timur, Kota Bekasi"
}
```

---

#### 🔵 POST `/api/member/register`
* **Deskripsi:** Mengirim berkas formulir fisik dan berkas unggahan digital untuk mendaftar sebagai anggota resmi koperasi.
* **Autentikasi:** **Wajib JWT Token (`Bearer {{token}}`)**
* **Content-Type:** `multipart/form-data`

##### Parameter Request Body (Multipart Form-Data)
| Parameter | Tipe | Validasi | Deskripsi |
| :--- | :--- | :--- | :--- |
| `nik` | String | **Wajib** | NIK KTP Calon Anggota. |
| `nama` | String | **Wajib** | Nama Lengkap (Sesuai KTP). |
| `alamat` | String | **Wajib** | Alamat Lengkap Domisili. |
| `phone` | String | **Wajib** | Nomor Telepon Aktif. |
| `jenis_kelamin` | String | **Wajib** | `Laki-laki` atau `Perempuan`. |
| `ttl` | String | **Wajib** | Tempat, Tanggal Lahir (Format: `Kota, DD-MM-YYYY`). |
| `ktp` | File (Biner) | **Wajib** | Foto KTP Asli. |
| `kartu_anggota` | File (Biner) | **Wajib** | Foto Kartu Karyawan / Kartu Anggota. |
| `pas_foto` | File (Biner) | **Wajib** | Pas Foto Resmi 3x4 (Latar Merah/Biru). |
| `tanda_tangan` | File (Biner) | **Wajib** | Foto Tanda Tangan Digital. |

##### Contoh Respons (200 OK - Sukses)
```json
{
  "success": true,
  "message": "Pendaftaran berhasil dikirim."
}
```

##### Contoh Respons (400 Bad Request - Pendaftaran Ganda)
```json
{
  "success": false,
  "error": "Anda sudah memiliki pendaftaran dengan status: pending"
}
```

---

#### 🔵 GET `/api/member/status/<user_id>`
* **Deskripsi:** Mengecek status kemajuan pendaftaran anggota dari pengguna mobile berdasarkan `user_id`.
* **Autentikasi:** Terbuka untuk Umum (Public)
* **Request Path Parameters:**
  - `user_id`: ID pengguna mobile (integer).

##### Jenis Status Pendaftaran yang Dikembalikan (`status`):
* `not_started` : Belum pernah mengajukan pendaftaran anggota.
* `pending` : Berkas pendaftaran sedang direview oleh Admin.
* `approved` : Berkas disetujui, akun berganti menjadi Anggota Resmi Aktif.
* `rejected` : Pendaftaran ditolak (Alasan disertakan di `rejection_reason`).

##### Contoh Respons (200 OK - Approved/Aktif)
```json
{
  "status": "approved",
  "full_name": "Budi Santoso",
  "registration_details": {
    "rejection_reason": ""
  }
}
```

##### Contoh Respons (200 OK - Rejected/Ditolak)
```json
{
  "status": "rejected",
  "full_name": "Budi Santoso",
  "registration_details": {
    "rejection_reason": "Gambar KTP buram dan data tanda tangan tidak sesuai. Silakan upload ulang."
  }
}
```

---

### 📦 3. Kategori: Layanan Keuangan & Transaksi

#### 🔵 GET `/api/member/financial_details`
* **Deskripsi:** Mengambil detail profil keuangan anggota, total saldo koperasi, rincian per-jenis simpanan, mutasi transaksi terbaru, data grafik pertumbuhan, dan data payroll.
* **Autentikasi:** **Wajib JWT Token (`Bearer {{token}}`)**
* **Content-Type:** None (GET request)

##### Rincian Jenis Simpanan (Saving Type ID):
* `1` : Simpanan Pokok
* `2` : Simpanan Wajib (Payroll)
* `3` : Simpanan Sukarela (Bebas)

##### Contoh Respons (200 OK - Sukses Mengambil Data)
```json
{
  "member": {
    "id": 1,
    "member_no": "M-20260518123045",
    "name": "Budi Santoso",
    "phone": "08123456789",
    "email": "budi.santoso@gmail.com",
    "address": "Jl. Contoh No. 123, RT 001/RW 002, Jakarta",
    "status": "AKTIF",
    "birth_date": "1990-01-01",
    "gender": "Laki-laki",
    "jabatan": "IT Senior Specialist",
    "pas_foto": "https://res.cloudinary.com/demo/image/upload/v15789/reg_1_pas_foto.jpg"
  },
  "total_balance": 5250000.0,
  "balances": [
    {
      "saving_type_id": 1,
      "balance": 1000000.0,
      "updated_at": "2026-05-18 10:00"
    },
    {
      "saving_type_id": 2,
      "balance": 4000000.0,
      "updated_at": "2026-05-18 10:00"
    },
    {
      "saving_type_id": 3,
      "balance": 250000.0,
      "updated_at": "2026-05-18 10:00"
    }
  ],
  "recent_transactions": [
    {
      "id": 102,
      "type": "DEPOSIT",
      "saving_type": "Simpanan Wajib",
      "saving_type_id": 2,
      "amount": 250000.0,
      "date": "2026-05-01 08:30",
      "status": "SUCCESS",
      "description": "Potong Payroll Bulanan Mei 2026"
    },
    {
      "id": 98,
      "type": "WITHDRAWAL",
      "saving_type": "Simpanan Sukarela",
      "saving_type_id": 3,
      "amount": 500000.0,
      "date": "2026-04-15 14:00",
      "status": "SUCCESS",
      "description": "Penarikan Dana Sukarela via Mobile App"
    }
  ],
  "analytics": {
    "total_payroll": 4000000.0,
    "total_withdrawal": 500000.0,
    "shu_estimation": 262500.0,
    "monthly_growth": {
      "labels": ["Des 2025", "Jan 2026", "Feb 2026", "Mar 2026", "Apr 2026", "Mei 2026"],
      "data": [4250000.0, 4450000.0, 4650000.0, 4800000.0, 5000000.0, 5250000.0]
    },
    "payroll_history": [
      {"date": "2026-05", "amount": 250000.0, "status": "SUCCESS"},
      {"date": "2026-04", "amount": 250000.0, "status": "SUCCESS"},
      {"date": "2026-03", "amount": 250000.0, "status": "SUCCESS"}
    ]
  }
}
```

---

#### 🔵 POST `/api/member/withdraw`
* **Deskripsi:** Mengajukan permohonan penarikan saldo simpanan anggota ke rekening bank pribadi.
* **Autentikasi:** **Wajib JWT Token (`Bearer {{token}}`)**
* **Content-Type:** `application/x-www-form-urlencoded` atau `multipart/form-data`

##### Parameter Request Body (Form-Data)
| Parameter | Tipe | Validasi | Deskripsi |
| :--- | :--- | :--- | :--- |
| `amount` | Numeric | **Wajib** | Nominal dana yang ingin ditarik. |
| `bank_name` | String | **Wajib** | Nama Bank tujuan transfer (misal: `Bank Mandiri`, `BCA`). |
| `account_number` | String | **Wajib** | Nomor Rekening tujuan transfer. |
| `account_holder` | String | **Wajib** | Nama Pemilik Rekening (Wajib sesuai KTP/Anggota). |
| `saving_type_id` | Integer | **Wajib** | ID asal jenis simpanan (disarankan `3` untuk Sukarela). |
| `reason` | String | Opsional | Alasan penarikan dana. |

##### Contoh Respons (200 OK - Permohonan Terkirim)
```json
{
  "success": true,
  "message": "Permohonan penarikan berhasil dikirim."
}
```

##### Contoh Respons (404 Not Found - Member Tidak Ditemukan)
```json
{
  "success": false,
  "error": "Member not found"
}
```

---

## 📱 CONTOH INTEGRASI KODE FLUTTER (DART)

Berikut adalah contoh snippet implementasi integration client menggunakan package HTTP atau Dio di Flutter:

### 1. Otentikasi & Penyimpanan Token Otomatis
```dart
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class ApiService {
  final String baseUrl = "http://192.168.110.95:5000/api";
  final storage = const FlutterSecureStorage();

  Future<bool> login(String email, String password) async {
    final response = await http.post(
      Uri.parse("$baseUrl/login"),
      body: {
        "email": email,
        "password": password,
      },
    );

    if (response.statusCode == 200) {
      final data = json.decode(response.body);
      if (data['success'] == true) {
        // Simpan token JWT secara aman
        await storage.write(key: "jwt_token", value: data['token']);
        await storage.write(key: "user_id", value: data['user']['id'].toString());
        return true;
      }
    }
    return false;
  }
}
```

### 2. Mengakses Endpoint Terproteksi (Bearer Token)
```dart
Future<Map<String, dynamic>?> getFinancialDetails() async {
  final token = await storage.read(key: "jwt_token");
  
  final response = await http.get(
    Uri.parse("$baseUrl/member/financial_details"),
    headers: {
      "Authorization": "Bearer $token",
      "Accept": "application/json",
    },
  );

  if (response.statusCode == 200) {
    return json.decode(response.body);
  } else if (response.statusCode == 401) {
    // Redirect ke halaman login karena token expired
    print("Token Expired atau Tidak Valid!");
  }
  return null;
}
```

---

## 📌 PEMBARUAN & PEMELIHARAAN (API VERSIONING)
Dokumentasi ini mencerminkan status API **V5 (Enterprise Edition)**.
Harap perbarui dokumentasi ini secara berkala setiap kali terjadi perubahan skema respons basis data atau penambahan parameter di berkas `routes/api_routes.py`.

---
*Dokumentasi Koperasi Mobile API - Diperbarui pada 2026-05-18*
