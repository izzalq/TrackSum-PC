"# TrackSum-PC" 
blakutik blakutak
# TrackSum-PC

Aplikasi desktop TrackSum untuk mencari rute dan estimasi tarif transportasi umum di Bandung, dibangun dengan antarmuka Python/Kivy dan mesin pencarian rute native C++.

## Prasyarat

- Python 3.10 atau lebih baru
- Kompiler C++ (`g++`)
- **Khusus Windows:** Pastikan MinGW-w64 sudah terpasang dan `g++` terdaftar di `PATH`

## Cara Menjalankan

1. **Kompilasi engine C++:**

   Windows:
   ```bat
   core_engine\build.bat
   ```

   Linux:
   ```sh
   g++ -std=c++17 -O2 -fPIC -shared core_engine/pareto_dijkstra.cpp core_engine/bridge.cpp -o core_engine/libtracksum_engine.so
   ```

2. **Install library Python yang dibutuhkan:**
   ```bat
   python -m pip install -r requirements.txt
   ```

3. **Jalankan aplikasi:**
   ```bat
   python app\main.py
   ```

Untuk pengujian cepat lewat ID simpul, kamu bisa memakai daftar titik yang ada di `data/bandung_routes.json` (contohnya `alun_alun` dan `ledeng`), atau langsung pilih lokasi lewat peta dan kolom pencarian.

## Struktur Data Multimoda

Setiap segmen (`edge`) di dalam `routes` mendukung empat jenis moda (`mode`), yaitu `angkot`, `damri`, `kereta`, dan `jalan_kaki`, lengkap dengan pengaturan `fare_model`, `minutes`, serta `fare_rupiah`.

- **Bus & Angkot:** Bisa ditambahkan `headway_minutes` untuk menghitung estimasi waktu tunggu armada.
- **Kereta Lokal:** Menggunakan `departure_minutes` dan `reverse_departure_minutes` yang dihitung dalam satuan menit setelah tengah malam (00:00).
- **Aturan Tarif & Transit:** Tarif flat hanya dihitung sekali saat penumpang pertama kali naik ke suatu trayek dan tidak ditagih ulang selama masih melanjutkan perjalanan di `route_id` yang sama. Sementara itu, segmen `jalan_kaki` dipakai untuk menyambungkan titik transit antarmoda atau stasiun tanpa menambah biaya.

> **Catatan:** Data trayek, tarif, jadwal keberangkatan, warna armada, serta beberapa titik koordinat stasiun yang ada saat ini masih berupa data simulasi (demo) dan belum mengacu pada data resmi. Jalur rel kereta dan akurasi lekukan jalan >= 90% juga masih dalam tahap penyempurnaan.

## Layanan Lokasi (`location_service.py`)

Modul `app/location_service.py` menggabungkan pencarian halte dari database lokal dengan pencarian tempat online lewat Nominatim (dibatasi di area Bandung Raya), sekaligus menangani *reverse geocoding* saat pengguna menggeser pin di peta.

Agar tetap aman dari pemblokiran server Nominatim, setiap permintaan pencarian online diberi jeda minimal 1 detik dan menyertakan identitas `User-Agent` aplikasi. Untuk fitur "Lokasi Saat Ini", aplikasi akan mencoba membaca GPS perangkat lewat Plyer terlebih dahulu; jika tidak tersedia (misalnya di PC/laptop), sistem otomatis beralih ke IP geolocation yang hasilnya bersifat perkiraan—dan data ini hanya dikirim keluar saat fitur tersebut benar-benar diklik pengguna.
