# Reviu Artikel Ilmiah AI

Aplikasi web untuk mereviu dan merevisi artikel ilmiah `.docx` dengan bantuan AI (OpenAI Responses API).

**Setiap pengguna memakai OpenAI API key miliknya sendiri.** Pemilik aplikasi tidak menyediakan API key. Setelah login, pengguna wajib memasukkan API key; key hanya disimpan sementara di server-side session dan otomatis terhapus saat logout atau saat sesi berakhir.

## Fitur

- Sistem akun: registrasi dan login (password di-hash, database SQLite).
- Halaman API key per sesi: validasi ringan ke OpenAI sebelum diterima, tombol hapus key, tidak pernah ditampilkan kembali.
- Isolasi per pengguna: file unggahan dan hasil analisis dipisah per akun; pengguna tidak dapat mengakses hasil milik pengguna lain.
- Proteksi CSRF pada seluruh form POST, cookie HttpOnly + SameSite=Lax (+ Secure saat production), header `Cache-Control: no-store` di halaman sensitif.
- Upload artikel ilmiah dalam format `.docx`.
- Ekstraksi teks dari dokumen Word.
- Analisis menggunakan OpenAI Responses API; model dikonfigurasi melalui `OPENAI_MODEL`.
- Revisi bertahap untuk judul, abstrak, pendahuluan, metodologi, hasil dan pembahasan, serta kesimpulan.
- Setiap tahap memakai hasil revisi tahap sebelumnya agar naskah tetap koheren.
- Deteksi bagian metodologi dengan heading `Metode`, `Metodologi`, `Metode Penelitian`, `Research Method`, atau `Methodology`.
- Analisis hasil dan pembahasan dengan AI melalui tombol terpisah di halaman hasil.
- Deteksi bagian hasil dan pembahasan dengan heading `Hasil`, `Hasil Penelitian`, `Results`, `Pembahasan`, `Discussion`, atau `Hasil dan Pembahasan`.
- Pemeriksaan sitasi, kecocokan daftar pustaka, dan format APA 7 sebagai tahap akhir.
- Rekomendasi 10-15 referensi aktual dari OpenAlex dan Crossref, lengkap dengan DOI dan format APA 7.
- Pemilihan referensi tambahan melalui tombol `Tambahkan ke Daftar Pustaka`.
- Unduh laporan akhir dalam format PDF setelah seluruh tahap analisis selesai.
- Hapus hasil reviu dan file terkait melalui halaman hasil.
- Penandaan kutipan yang tidak dapat dicocokkan dengan daftar pustaka sebagai `perlu verifikasi`.
- Penyimpanan hasil analisis ke folder `output`.

## Struktur Proyek

```text
.
├── app.py
├── requirements.txt
├── render.yaml
├── .env.example
├── README.md
├── static/
│   └── styles.css
├── templates/
│   ├── login.html
│   ├── register.html
│   ├── api_key.html
│   ├── index.html
│   └── result.html
├── tests/
│   ├── conftest.py
│   └── test_app.py
├── instance/        (dibuat otomatis, berisi app.db — jangan di-commit)
├── flask_session/   (dibuat otomatis, session server-side — jangan di-commit)
├── uploads/<id_pengguna>/
└── output/<id_pengguna>/
```

## Cara Menjalankan Secara Lokal

1. Buat virtual environment.

```bash
python -m venv .venv
```

2. Aktifkan virtual environment.

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Command Prompt:

```cmd
.\.venv\Scripts\activate.bat
```

3. Instal dependensi.

```bash
pip install -r requirements.txt
```

4. Salin `.env.example` menjadi `.env` lalu sesuaikan nilainya. Jangan pernah memasukkan API key OpenAI ke `.env` atau ke repository.

```env
SECRET_KEY=ganti-dengan-nilai-acak-yang-panjang
FLASK_ENV=development
SESSION_TYPE=filesystem
SESSION_LIFETIME_MINUTES=120
OPENAI_MODEL=gpt-5.6
```

5. Jalankan aplikasi.

```bash
python app.py
```

6. Buka `http://127.0.0.1:5000`, daftar akun, login, lalu masukkan OpenAI API key milik Anda pada halaman API key.

## Menjalankan Test

```bash
pip install pytest
python -m pytest tests/ -q
```

Seluruh pemanggilan OpenAI dalam test menggunakan mock sehingga tidak menghabiskan saldo API.

## Environment Variable

| Variabel | Wajib | Keterangan |
| --- | --- | --- |
| `SECRET_KEY` | Ya (production) | Kunci penandatangan session cookie. Gunakan nilai acak panjang. |
| `FLASK_ENV` | Tidak | `development` untuk lokal, `production` (default) untuk deploy. Menentukan mode debug dan cookie `Secure`. |
| `SESSION_TYPE` | Tidak | `filesystem` (default) atau `redis`. |
| `REDIS_URL` | Jika `SESSION_TYPE=redis` | URL koneksi Redis untuk session production. |
| `SESSION_LIFETIME_MINUTES` | Tidak | Umur session (default 120 menit). Setelah kedaluwarsa, pengguna harus login dan memasukkan API key lagi. |
| `OPENAI_MODEL` | Tidak | Model OpenAI (default `gpt-5.6`). |
| `OPENAI_TIMEOUT_SECONDS` | Tidak | Batas waktu request ke OpenAI (default 300). |
| `SCHOLARLY_API_EMAIL` | Tidak | Email kontak untuk API Crossref/OpenAlex. |
| `DATABASE_PATH` | Tidak | Lokasi file SQLite akun pengguna (default `instance/app.db`). |

`OPENAI_API_KEY` **tidak dibutuhkan** — setiap pengguna memakai key miliknya sendiri per sesi.

## Deployment ke Render

1. Push repository ini ke GitHub (pastikan `.env`, `instance/`, `flask_session/`, `uploads/`, dan `output/` tidak ikut ter-commit; sudah diatur di `.gitignore`).
2. Di Render, buat **Web Service** baru dari repository, atau gunakan Blueprint (`render.yaml` sudah tersedia).
3. Konfigurasi:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app`
   - Health check path: `/healthz`
4. Environment variable minimal: `SECRET_KEY` (nilai acak), `FLASK_ENV=production`, `OPENAI_MODEL`.
5. **Session production:** disarankan `SESSION_TYPE=redis` + `REDIS_URL` (Render Key Value, atau layanan gratis seperti Upstash). Tanpa Redis, `SESSION_TYPE=filesystem` tetap aman (key tidak pernah berada di cookie) tetapi semua sesi hilang saat instance restart/deploy — pengguna cukup login dan memasukkan key lagi. Aplikasi **tidak pernah** kembali menyimpan key di cookie Flask.
6. Catatan Render free tier: filesystem bersifat ephemeral. Database akun (`instance/app.db`), file unggahan, dan hasil analisis ikut hilang saat redeploy. Untuk data akun yang persisten, pasang Render Disk atau ganti `DATABASE_PATH` ke disk persisten.

## Keamanan API Key Pengguna

- Key dikirim hanya lewat POST (form), tidak pernah lewat URL/query string.
- Key divalidasi dengan request ringan (`models.retrieve`/`models.list`) sebelum diterima — tanpa mengonsumsi token.
- Key disimpan hanya di server-side session (Flask-Session); cookie browser hanya berisi ID session yang ditandatangani, HttpOnly, SameSite=Lax, dan Secure saat production.
- Key tidak pernah ditulis ke log, database, file, localStorage, atau ditampilkan kembali di halaman/JSON/pesan error.
- Logout menghapus key dan seluruh session; halaman sensitif memakai `Cache-Control: no-store` sehingga tombol Back tidak menampilkan data sesi lama.

## Catatan Penting

- Aplikasi ini tidak melakukan analisis manual berbasis aturan Python. Python hanya membaca dokumen, mengirim teks ke AI, dan menampilkan hasil.
- AI diinstruksikan untuk tidak mengarang data penelitian, angka, lokasi, metode, temuan, atau kutipan.
- AI diinstruksikan untuk tidak membuat kutipan palsu.
- Jika kutipan tidak dapat diverifikasi dari daftar pustaka di artikel, hasil harus menampilkan `perlu verifikasi`.
- Hasil difokuskan pada teks revisi final yang ringkas dan siap digunakan penulis.

## Bagian Hasil

1. Evaluasi Judul
2. Rekomendasi Judul Baru
3. Evaluasi Abstrak
4. Abstrak Versi Perbaikan
5. Evaluasi Pendahuluan
6. Gap Penelitian
7. Cek Kutipan dan Daftar Pustaka
8. Rumusan Masalah
9. Pendahuluan Versi Revisi

## Modul Metodologi

Setelah analisis awal selesai, halaman hasil menampilkan tombol `Analisis Metodologi dengan AI`. Modul ini akan:

- mendeteksi dan menampilkan teks metodologi dari artikel;
- mengirim teks metodologi dan artikel lengkap ke AI;
- mengevaluasi kelengkapan jenis penelitian, pendekatan, desain, subjek, lokasi, waktu, populasi, sampel, teknik pengumpulan data, instrumen, prosedur, analisis data, validitas, reliabilitas, etika penelitian, dan kesesuaian metode dengan tujuan atau rumusan masalah;
- menampilkan kelemahan, komponen yang belum ada, saran perbaikan, catatan yang perlu dilengkapi penulis, dan metodologi versi revisi.

AI diinstruksikan untuk tidak mengarang sampel, lokasi, instrumen, hasil uji validitas, hasil uji reliabilitas, atau teknik analisis yang tidak tersedia dalam artikel.

## Modul Hasil dan Pembahasan

Setelah analisis awal selesai, halaman hasil menampilkan tombol `Analisis Hasil dan Pembahasan dengan AI`. Modul ini memakai hasil analisis sebelumnya untuk memeriksa keselarasan:

- judul penelitian;
- tujuan penelitian;
- rumusan masalah;
- gap penelitian;
- metodologi;
- hasil penelitian;
- pembahasan.

Output modul ini meliputi evaluasi hasil penelitian, evaluasi pembahasan, kesesuaian dengan rumusan masalah, metodologi, tujuan penelitian, inkonsistensi, saran perbaikan, hasil versi revisi, pembahasan versi revisi, dan catatan untuk penulis.

AI diinstruksikan untuk tidak mengarang data penelitian, angka statistik, hasil observasi, hasil wawancara, tabel, atau grafik. Jika data tidak tersedia, AI harus menulis `Bagian ini memerlukan data tambahan dari penulis dan tidak dapat direvisi secara penuh tanpa data asli.`

## Modul Referensi dan Sitasi

Halaman hasil menyediakan tombol `Analisis Referensi dan Sitasi`. Modul ini memeriksa semua sitasi dalam naskah, kecocokannya dengan daftar pustaka, referensi yang tidak pernah disitasi, referensi duplikat, kelengkapan referensi, usia referensi, kualitas sumber, dan kepatuhan terhadap APA 7th Edition.

Output modul ini meliputi ringkasan kualitas referensi, statistik jenis referensi, statistik usia referensi, sitasi bermasalah, referensi bermasalah, referensi tidak pernah disitasi, sitasi tanpa referensi, referensi duplikat, evaluasi kualitas referensi, evaluasi APA 7, daftar perbaikan, skor kualitas referensi, dan tingkat kesiapan referensi untuk publikasi.

AI diinstruksikan untuk tidak mengarang DOI, URL, atau data bibliografi. Jika keberadaan atau kredibilitas referensi tidak dapat dipastikan dari artikel, AI harus menulis `Referensi perlu diverifikasi pada sumber asli.`

