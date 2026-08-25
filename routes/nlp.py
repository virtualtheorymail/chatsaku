import re

from datetime import datetime

# ============================================================
# DETEKSI USER NLP
# ============================================================

def deteksi_user_nlp(message, nlp):

    if not message:
        return None

    text = message.strip().lower()

    print("========================================")
    print("👤 CEK USER NLP")
    print("MESSAGE :", message)
    print("TEXT    :", text)
    print("========================================")

    # ========================================================
    # LIST USER
    # ========================================================

    if text in [
        "user",
        "users",
        "list user",
        "daftar user",
        "lihat user",
        "lihat pengguna",
        "daftar pengguna",
        "list pengguna",
        "semua user",
        "semua pengguna",
        "cek user",
        "cek pengguna",
        "tampilkan user",
        "tampilkan pengguna"
    ]:

        print("👤 USER TERDETEKSI")
        print("ACTION : list")

        return {
            "action": "list"
        }

    # ========================================================
    # TAMBAH USER
    # ========================================================

    pola_tambah = [
        "adduser",
        "tambah user",
        "tambah pengguna",
        "buat user",
        "buat pengguna",
        "daftarkan user",
        "daftarkan pengguna"
    ]

    for pola in pola_tambah:

        if text.startswith(pola):

            data = text[len(pola):].strip()

            parts = data.split()

            # Contoh:
            #
            # tambah user 628123456789 Bambang PREMIUM 30
            #
            # nomor = 628123456789
            # nama = Bambang
            # paket = PREMIUM
            # durasi = 30

            if len(parts) < 4:

                return {
                    "action": "add",
                    "error": "format"
                }

            nomor = parts[0]

            # =================================================
            # CARI PAKET
            # =================================================

            paket_index = None

            for i, part in enumerate(parts):

                if part.upper() in [
                    "STARTER",
                    "PRO",
                    "PREMIUM"
                ]:

                    paket_index = i
                    break

            if paket_index is None:

                return {
                    "action": "add",
                    "error": "paket"
                }

            # =================================================
            # NAMA
            # =================================================

            nama = " ".join(
                parts[1:paket_index]
            )

            if not nama:

                return {
                    "action": "add",
                    "error": "nama"
                }

            # =================================================
            # PAKET
            # =================================================

            paket = parts[
                paket_index
            ].upper()

            # =================================================
            # DURASI
            # =================================================

            if paket_index + 1 >= len(parts):

                return {
                    "action": "add",
                    "error": "durasi"
                }

            durasi = parts[
                paket_index + 1
            ]

            return {
                "action": "add",
                "nomor": nomor,
                "nama": nama,
                "paket": paket,
                "durasi": durasi
            }

    return None

# ============================================================
# DETEKSI BAYAR HUTANG NLP
# ============================================================

def deteksi_bayarhutang_nlp(
    message,
    data=None
):

    if not message:
        return None

    text = str(message).strip()

    if not text:
        return None

    text_lower = re.sub(
        r'\s+',
        ' ',
        text.lower()
    ).strip()

    if data is None:
        data = {}

    print("========================================")
    print("💰 CEK BAYAR HUTANG NLP")
    print("MESSAGE :", message)
    print("========================================")

    # ========================================================
    # LIST
    # ========================================================

    pola_list = [
        r'^bayarhutang$',
        r'^bayar\s+hutang$',
        r'^list\s+bayar\s+hutang$',
        r'^daftar\s+bayar\s+hutang$',
        r'^lihat\s+bayar\s+hutang$'
    ]

    for pola in pola_list:

        if re.search(
            pola,
            text_lower,
            re.IGNORECASE
        ):

            return {
                "intent": "bayarhutang",
                "action": "list",
                "nama": None,
                "nominal": None,
                "keterangan": None
            }

    # ========================================================
    # BAYAR
    # ========================================================

    pola_bayar = [
        r'^bayarhutang\s+(.+)$',
        r'^bayar\s+hutang\s+(.+)$',
        r'^bayarkan\s+hutang\s+(.+)$',
        r'^saya\s+bayar\s+hutang\s+(.+)$',
        r'^aku\s+bayar\s+hutang\s+(.+)$',
        r'^kami\s+bayar\s+hutang\s+(.+)$',
        r'^sudah\s+bayar\s+hutang\s+(.+)$',
        r'^telah\s+bayar\s+hutang\s+(.+)$',
        r'^lunasi\s+hutang\s+(.+)$',
        r'^lunas\s+hutang\s+(.+)$'
    ]

    match_bayar = None

    for pola in pola_bayar:

        match_bayar = re.search(
            pola,
            text_lower,
            re.IGNORECASE
        )

        if match_bayar:
            break

    if not match_bayar:
        return None

    # ========================================================
    # ISI
    #
    # bayar hutang ucup 1000
    #
    # isi = ucup 1000
    # ========================================================

    isi = match_bayar.group(1).strip()

    print("ISI :", isi)

    # ========================================================
    # NOMINAL
    #
    # PRIORITAS:
    # Ambil nominal PALING AKHIR
    # ========================================================

    nominal = None

    pola_nominal_akhir = re.search(
        r'(?:rp\s*)?'
        r'(\d+(?:[.,]\d+)?)'
        r'\s*(juta|jt|ribu|rb|miliar|milyar)?'
        r'\s*$',
        isi,
        re.IGNORECASE
    )

    if pola_nominal_akhir:

        angka_text = pola_nominal_akhir.group(1)
        satuan = pola_nominal_akhir.group(2)

        try:

            angka_text = angka_text.replace(
                ",",
                "."
            )

            angka_float = float(
                angka_text
            )

            if satuan:

                satuan = satuan.lower()

                if satuan in ["ribu", "rb"]:

                    nominal = int(
                        angka_float * 1000
                    )

                elif satuan in ["juta", "jt"]:

                    nominal = int(
                        angka_float * 1000000
                    )

                elif satuan in ["miliar", "milyar"]:

                    nominal = int(
                        angka_float * 1000000000
                    )

                else:

                    nominal = int(
                        angka_float
                    )

            else:

                nominal = int(
                    angka_float
                )

        except Exception as e:

            print(
                "❌ ERROR PARSE NOMINAL:",
                repr(e)
            )

            nominal = None

    # ========================================================
    # FALLBACK NOMINAL
    # ========================================================

    if nominal is None:

        try:

            nominal = parse_nominal_finance(
                isi
            )

        except Exception:

            try:

                nominal = normalize_nominal(
                    isi
                )

            except Exception:

                nominal = None

    # ========================================================
    # NAMA
    # ========================================================

    nama = isi

    # Hapus nominal dari belakang

    nama = re.sub(
        r'\s+(?:rp\s*)?'
        r'\d+(?:[.,]\d+)?'
        r'\s*(?:juta|jt|ribu|rb|miliar|milyar)?'
        r'\s*$',
        '',
        nama,
        flags=re.IGNORECASE
    ).strip()

    # Hapus kata hutang

    nama = re.sub(
        r'^hutang\s+',
        '',
        nama,
        flags=re.IGNORECASE
    ).strip()

    # Hapus ke / kepada

    nama = re.sub(
        r'^(ke|kepada)\s+',
        '',
        nama,
        flags=re.IGNORECASE
    ).strip()

    nama = re.sub(
        r'\s+',
        ' ',
        nama
    ).strip()

    # ========================================================
    # VALIDASI
    # ========================================================

    if not nama:

        return {
            "intent": "bayarhutang",
            "action": "pay",
            "nama": None,
            "nominal": nominal,
            "keterangan": None,
            "error": "nama"
        }

    # ========================================================
    # HASIL
    # ========================================================

    result = {
        "intent": "bayarhutang",
        "action": "pay",
        "nama": nama,
        "nominal": nominal,
        "keterangan": None
    }

    print("========================================")
    print("💰 BAYAR HUTANG TERDETEKSI")
    print("INTENT  :", result["intent"])
    print("ACTION  :", result["action"])
    print("NAMA    :", result["nama"])
    print("NOMINAL :", result["nominal"])
    print("========================================")

    return result
