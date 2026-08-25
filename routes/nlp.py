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


# ============================================================
# DETEKSI ADMIN USER NLP
# ============================================================

def deteksi_admin_user_nlp(
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
    print("👤 CEK ADMIN USER NLP")
    print("MESSAGE :", message)
    print("========================================")

    # ========================================================
    # DELETE USER
    # ========================================================

    pola_delete = [

        r'^deluser\s+(.+)$',

        r'^hapus\s+user\s+(.+)$',

        r'^hapus\s+pengguna\s+(.+)$',

        r'^hapuskan\s+user\s+(.+)$',

        r'^hapuskan\s+pengguna\s+(.+)$',

        r'^hapus\s+akun\s+(.+)$',

        r'^hapuskan\s+akun\s+(.+)$'

    ]

    for pola in pola_delete:

        match = re.search(
            pola,
            text_lower,
            re.IGNORECASE
        )

        if not match:
            continue

        nomor = match.group(1).strip()

        # ----------------------------------------------------
        # Ambil nomor WA
        # ----------------------------------------------------

        match_nomor = re.search(
            r'(?:\+?62|0)\d{8,15}',
            nomor
        )

        if match_nomor:

            nomor = match_nomor.group(0)

        else:

            nomor = None

        return {

            "intent": "deluser",

            "action": "delete",

            "nomor": nomor,

            "nama": None,

            "paket": None,

            "error": (
                None
                if nomor
                else "nomor"
            )

        }

    # ========================================================
    # GANTI PAKET
    # ========================================================

    pola_paket = [

        r'^paket\s+(.+)$',

        r'^ganti\s+paket\s+(.+)$',

        r'^ubah\s+paket\s+(.+)$',

        r'^ubah\s+paket\s+user\s+(.+)$',

        r'^ganti\s+paket\s+user\s+(.+)$'

    ]

    for pola in pola_paket:

        match = re.search(
            pola,
            text_lower,
            re.IGNORECASE
        )

        if not match:
            continue

        isi = match.group(1).strip()

        parts = isi.split()

        nomor = None
        paket = None

        # ----------------------------------------------------
        # Cari nomor
        # ----------------------------------------------------

        for part in parts:

            if re.fullmatch(
                r'(?:\+?62|0)\d{8,15}',
                part
            ):

                nomor = part

                break

        # ----------------------------------------------------
        # Cari paket
        # ----------------------------------------------------

        for part in parts:

            if part.upper() in FEATURES:

                paket = part.upper()

                break

        error = None

        if not nomor:

            error = "nomor"

        elif not paket:

            error = "paket"

        return {

            "intent": "paket",

            "action": "package",

            "nomor": nomor,

            "nama": None,

            "paket": paket,

            "error": error

        }

    # ========================================================
    # AKTIFKAN USER
    # ========================================================

    pola_aktif = [

        r'^aktif\s+(.+)$',

        r'^aktifkan\s+(.+)$',

        r'^aktifkan\s+user\s+(.+)$',

        r'^aktifkan\s+pengguna\s+(.+)$',

        r'^nyalakan\s+user\s+(.+)$'

    ]

    for pola in pola_aktif:

        match = re.search(
            pola,
            text_lower,
            re.IGNORECASE
        )

        if not match:
            continue

        isi = match.group(1).strip()

        match_nomor = re.search(
            r'(?:\+?62|0)\d{8,15}',
            isi
        )

        nomor = (
            match_nomor.group(0)
            if match_nomor
            else None
        )

        return {

            "intent": "aktif",

            "action": "activate",

            "nomor": nomor,

            "nama": None,

            "paket": None,

            "error": (
                None
                if nomor
                else "nomor"
            )

        }

    # ========================================================
    # NONAKTIFKAN USER
    # ========================================================

    pola_nonaktif = [

        r'^nonaktif\s+(.+)$',

        r'^nonaktifkan\s+(.+)$',

        r'^nonaktifkan\s+user\s+(.+)$',

        r'^nonaktifkan\s+pengguna\s+(.+)$',

        r'^matikan\s+user\s+(.+)$',

        r'^blokir\s+user\s+(.+)$',

        r'^blokir\s+pengguna\s+(.+)$'

    ]

    for pola in pola_nonaktif:

        match = re.search(
            pola,
            text_lower,
            re.IGNORECASE
        )

        if not match:
            continue

        isi = match.group(1).strip()

        match_nomor = re.search(
            r'(?:\+?62|0)\d{8,15}',
            isi
        )

        nomor = (
            match_nomor.group(0)
            if match_nomor
            else None
        )

        return {

            "intent": "nonaktif",

            "action": "deactivate",

            "nomor": nomor,

            "nama": None,

            "paket": None,

            "error": (
                None
                if nomor
                else "nomor"
            )

        }

    return None


# ============================================================
# DETEKSI PAKET USER NLP
# ============================================================

def deteksi_paket_nlp(message, nlp=None):

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

    print("========================================")
    print("📦 CEK PAKET NLP")
    print("MESSAGE :", message)
    print("========================================")

    # ========================================================
    # LIST / INFO PAKET
    # ========================================================

    pola_list = [
        r'^paket$',
        r'^list paket$',
        r'^daftar paket$',
        r'^lihat paket$',
        r'^cek paket$',
        r'^paket apa saja$',
        r'^ada paket apa saja$',
        r'^pilihan paket$',
        r'^lihat semua paket$'
    ]

    for pola in pola_list:

        if re.fullmatch(
            pola,
            text_lower,
            re.IGNORECASE
        ):

            print("📦 PAKET LIST TERDETEKSI")

            return {
                "intent": "paket",
                "action": "list",
                "nomor": None,
                "paket": None
            }

    # ========================================================
    # GANTI PAKET
    #
    # Contoh:
    #
    # paket 628123456789 PREMIUM
    # ganti paket 628123456789 PREMIUM
    # ubah paket 628123456789 PRO
    # ubah paket user 628123456789 PRO
    # ========================================================

    pola_ganti = [

        r'^paket\s+(\d+)\s+(\w+)$',

        r'^ganti\s+paket\s+(\d+)\s+(\w+)$',

        r'^ubah\s+paket\s+(\d+)\s+(\w+)$',

        r'^ubah\s+paket\s+user\s+(\d+)\s+(\w+)$',

        r'^ganti\s+paket\s+user\s+(\d+)\s+(\w+)$',

        r'^set\s+paket\s+(\d+)\s+(\w+)$'
    ]

    for pola in pola_ganti:

        match = re.fullmatch(
            pola,
            text_lower,
            re.IGNORECASE
        )

        if not match:
            continue

        nomor = match.group(1)

        paket = match.group(2).upper()

        print("📦 GANTI PAKET TERDETEKSI")
        print("NOMOR :", nomor)
        print("PAKET :", paket)

        # ====================================================
        # VALIDASI PAKET
        # ====================================================

        if paket not in FEATURES:

            return {
                "intent": "paket",
                "action": "update",
                "nomor": nomor,
                "paket": paket,
                "error": "paket"
            }

        return {
            "intent": "paket",
            "action": "update",
            "nomor": nomor,
            "paket": paket,
            "error": None
        }

    # ========================================================
    # FALLBACK DARI NLP UTAMA
    # ========================================================

    if nlp and nlp.get("intent") == "paket":

        return {
            "intent": "paket",
            "action": nlp.get("action"),
            "nomor": nlp.get("nomor"),
            "paket": nlp.get("paket"),
            "error": nlp.get("error")
        }

    return None
