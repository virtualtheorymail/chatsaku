import re
from datetime import datetime


# =========================================================
# CHATSAKU NLP ROUTER
# =========================================================

def normalize_text(text):
    if not text:
        return ""

    text = text.lower().strip()

    replacements = {
        "gak": "tidak",
        "nggak": "tidak",
        "ga": "tidak",
        "ngga": "tidak",
        "dong": "",
        "ya": "",
        "nih": "",
        "sih": "",
        "deh": "",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"\s+", " ", text)

    return text.strip()


# =========================================================
# DETEKSI NOMINAL
# =========================================================

def extract_amount(text):

    text = text.lower()

    # 50 ribu
    match = re.search(
        r'(\d+(?:[.,]\d+)?)\s*(ribu|rb|juta|jt|milyar|miliar)',
        text
    )

    if match:

        angka = float(
            match.group(1)
            .replace(",", ".")
        )

        satuan = match.group(2)

        if satuan in ["ribu", "rb"]:
            angka *= 1000

        elif satuan in ["juta", "jt"]:
            angka *= 1000000

        elif satuan in ["milyar", "miliar"]:
            angka *= 1000000000

        return int(angka)

    # 500000
    match = re.search(
        r'(?<!\d)(\d{4,})(?!\d)',
        text
    )

    if match:
        return int(match.group(1).replace(".", ""))

    return None


# =========================================================
# DETEKSI INTENT
# =========================================================

def detect_intent(message):

    text = normalize_text(message)

    # =====================================================
    # SALDO
    # =====================================================

    saldo_keywords = [
        "saldo",
        "cek saldo",
        "berapa saldo",
        "saldo saya",
        "saldo aku",
        "uang saya berapa",
        "uangku berapa",
        "sisa uang",
        "uang yang tersedia",
        "uang sekarang berapa",
        "sisa uang saya"
    ]

    if any(x in text for x in saldo_keywords):
        return "saldo"


    # =====================================================
    # HARI INI
    # =====================================================

    hari_ini_keywords = [
        "hari ini",
        "hariini",
        "transaksi hari ini",
        "pengeluaran hari ini",
        "pemasukan hari ini",
        "rekap hari ini",
        "laporan hari ini",
        "hari ini habis berapa",
        "hari ini keluar berapa"
    ]

    if any(x in text for x in hari_ini_keywords):
        return "hari_ini"


    # =====================================================
    # DASHBOARD
    # =====================================================

    dashboard_keywords = [
        "dashboard",
        "dasbor",
        "lihat dashboard",
        "buka dashboard",
        "tampilkan dashboard"
    ]

    if any(x in text for x in dashboard_keywords):
        return "dashboard"


    # =====================================================
    # INSIGHT
    # =====================================================

    insight_keywords = [
        "insight",
        "analisa keuangan",
        "analisis keuangan",
        "analisa keuangan saya",
        "kondisi keuangan",
        "keuangan saya bagaimana",
        "saya boros tidak",
        "saya boros atau tidak",
        "evaluasi keuangan"
    ]

    if any(x in text for x in insight_keywords):
        return "insight"


    # =====================================================
    # BUDGET
    # =====================================================

    budget_keywords = [
        "budget",
        "anggaran",
        "atur budget",
        "buat budget",
        "cek budget",
        "budget saya",
        "anggaran saya"
    ]

    if any(x in text for x in budget_keywords):
        return "budget"


    # =====================================================
    # REMINDER
    # =====================================================

    reminder_keywords = [
        "reminder",
        "pengingat",
        "ingatkan saya",
        "ingatkan aku",
        "buat pengingat",
        "buat reminder",
        "ingatkan"
    ]

    if any(x in text for x in reminder_keywords):
        return "reminder"


    # =====================================================
    # HAPUS REMINDER
    # =====================================================

    hapus_reminder_keywords = [
        "hapus reminder",
        "hapus pengingat",
        "batalkan reminder",
        "hapus semua reminder",
        "hapus pengingat saya"
    ]

    if any(x in text for x in hapus_reminder_keywords):
        return "hapusreminder"


    # =====================================================
    # HUTANG
    # =====================================================

    hutang_keywords = [
        "hutang saya",
        "utang saya",
        "berapa hutang saya",
        "berapa utang saya",
        "cek hutang",
        "cek utang",
        "daftar hutang",
        "daftar utang"
    ]

    if any(x in text for x in hutang_keywords):
        return "hutang"


    # =====================================================
    # PIUTANG
    # =====================================================

    piutang_keywords = [
        "piutang",
        "orang yang hutang",
        "orang yang utang",
        "uang saya yang dipinjam",
        "uang yang belum dikembalikan",
        "siapa yang masih hutang",
        "siapa yang masih utang"
    ]

    if any(x in text for x in piutang_keywords):
        return "piutang"


    # =====================================================
    # BAYAR HUTANG
    # =====================================================

    if (
        "bayar hutang" in text
        or "bayar utang" in text
        or "sudah bayar hutang" in text
        or "sudah bayar utang" in text
    ):
        return "bayarhutang"


    # =====================================================
    # BAYAR PIUTANG
    # =====================================================

    if (
        "bayar piutang" in text
        or "piutang sudah dibayar" in text
        or "sudah dibayar" in text
    ):
        return "bayarpiutang"


    # =====================================================
    # TARGET
    # =====================================================

    target_keywords = [
        "target",
        "target tabungan",
        "target saya",
        "cek target",
        "lihat target",
        "target pembelian"
    ]

    if any(x in text for x in target_keywords):
        return "target"


    # =====================================================
    # TABUNGAN
    # =====================================================

    tabungan_keywords = [
        "tabungan",
        "menabung",
        "saya menabung",
        "cek tabungan",
        "tabungan saya"
    ]

    if any(x in text for x in tabungan_keywords):
        return "tabung"


    # =====================================================
    # HELP / MENU
    # =====================================================

    help_keywords = [
        "menu",
        "fitur",
        "help",
        "bantuan",
        "bisa apa",
        "apa yang bisa",
        "cara menggunakan",
        "cara pakai chatsaku"
    ]

    if any(x in text for x in help_keywords):
        return "help"


    # =====================================================
    # TRANSAKSI MASUK
    # =====================================================

    masuk_keywords = [
        "pemasukan",
        "uang masuk",
        "uang masuk",
        "dapat uang",
        "terima uang",
        "menerima uang",
        "gajian",
        "gaji masuk",
        "dapat transfer",
        "transfer masuk"
    ]

    if any(x in text for x in masuk_keywords):
        return "masuk"


    # =====================================================
    # TRANSAKSI KELUAR
    # =====================================================

    keluar_keywords = [
        "pengeluaran",
        "uang keluar",
        "belanja",
        "beli ",
        "bayar ",
        "makan ",
        "jajan ",
        "parkir ",
        "bensin ",
        "transportasi ",
        "keluar "
    ]

    if any(x in text for x in keluar_keywords):
        return "keluar"


    # =====================================================
    # DEFAULT
    # =====================================================

    return None


# =========================================================
# EXTRACT ENTITY TRANSAKSI
# =========================================================

def extract_transaction(message, intent):

    text = normalize_text(message)

    nominal = extract_amount(text)

    data = {
        "intent": intent,
        "nominal": nominal,
        "keterangan": message.strip()
    }

    return data


# =========================================================
# MAIN NLP
# =========================================================

def parse_message(message):

    intent = detect_intent(message)

    result = {
        "intent": intent,
        "nominal": None,
        "keterangan": message.strip()
    }

    if intent in ["masuk", "keluar"]:

        result.update(
            extract_transaction(
                message,
                intent
            )
        )

    return result
