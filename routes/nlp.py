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
