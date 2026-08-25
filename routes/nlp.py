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
    # ACTION LIST
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

            print("💰 BAYAR HUTANG LIST TERDETEKSI")

            return {

                "intent": "bayarhutang",

                "action": "list",

                "nama": None,

                "nominal": None,

                "keterangan": None

            }

    # ========================================================
    # ACTION PAY
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

    for pola in pola_bayar:

        match = re.search(
            pola,
            text_lower,
            re.IGNORECASE
        )

        if not match:
            continue

        # ====================================================
        # ISI SETELAH PREFIX
        #
        # bayar hutang mia 4000
        #
        # menjadi:
        #
        # mia 4000
        # ====================================================

        isi = match.group(1).strip()

        print("ISI :", isi)

        # ====================================================
        # NOMINAL
        # ====================================================

        nominal = None

        try:

            nominal = parse_nominal_finance(
                isi
            )

        except Exception as e:

            print(
                "⚠️ parse_nominal_finance gagal:",
                repr(e)
            )

            try:

                nominal = normalize_nominal(
                    isi
                )

            except Exception as e2:

                print(
                    "⚠️ normalize_nominal gagal:",
                    repr(e2)
                )

                nominal = None

        # ====================================================
        # NAMA
        # ====================================================

        nama = isi

        # ----------------------------------------------------
        # Hapus nominal di belakang
        #
        # mia 4000
        # mia 4.000
        # mia 4 ribu
        # mia 4rb
        # mia 2 juta
        # ----------------------------------------------------

        nama = re.sub(
            r'\s+(?:rp\s*)?'
            r'\d+(?:[.,]\d+)?'
            r'\s*(?:ribu|rb|juta|jt|miliar|milyar)?'
            r'\s*$',
            '',
            nama,
            flags=re.IGNORECASE
        ).strip()

        # ----------------------------------------------------
        # Jika masih ada kata "hutang"
        #
        # hutang mia
        #
        # menjadi:
        #
        # mia
        # ----------------------------------------------------

        nama = re.sub(
            r'^hutang\s+',
            '',
            nama,
            flags=re.IGNORECASE
        ).strip()

        # ----------------------------------------------------
        # Hapus ke / kepada
        #
        # kepada mia
        # ke mia
        # ----------------------------------------------------

        nama = re.sub(
            r'^(ke|kepada)\s+',
            '',
            nama,
            flags=re.IGNORECASE
        ).strip()

        # ----------------------------------------------------
        # Bersihkan spasi
        # ----------------------------------------------------

        nama = re.sub(
            r'\s+',
            ' ',
            nama
        ).strip()

        # ====================================================
        # VALIDASI NAMA
        # ====================================================

        if not nama:

            print(
                "❌ NAMA BAYAR HUTANG TIDAK DITEMUKAN"
            )

            return {

                "intent": "bayarhutang",

                "action": "pay",

                "nama": None,

                "nominal": nominal,

                "keterangan": None,

                "error": "nama"

            }

        # ====================================================
        # RETURN
        # ====================================================

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

    # ========================================================
    # TIDAK TERDETEKSI
    # ========================================================

    return None
