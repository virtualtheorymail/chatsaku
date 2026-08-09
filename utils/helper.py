from flask import Flask, request, jsonify, render_template, send_file, redirect
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta, time as dt_time
import time
from models import db, Transaksi, Budget, Reminder, User, MonthlySummary
from sqlalchemy import func
import requests
import os
import pandas as pd
import io
from zoneinfo import ZoneInfo
from itsdangerous import URLSafeTimedSerializer
from itsdangerous import BadSignature
from itsdangerous import SignatureExpired

JAKARTA = ZoneInfo("Asia/Jakarta")

SECRET_KEY = os.getenv("SECRET_KEY")

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY belum diset.")

serializer = URLSafeTimedSerializer(SECRET_KEY)

BASE_URL = os.getenv(
    "BASE_URL",
    "https://web-production-9a550.up.railway.app"
)


KATEGORI = {

    "makanan": [

        "bakso","mie","mie ayam","ayam","ayam geprek","ayam bakar",
        "ayam goreng","ayam penyet","pizza","burger","kebab",
        "martabak","sate","nasi","warteg","padang","seafood",
        "pempek","siomay","batagor","snack","cemilan","roti",
        "donat","croissant","sosis","bakpao","dimsum","pecel",
        "gado gado","soto","rawon","sop","iga","bebek","lele",
        "pecel lele","lalapan","bakmi","kwetiau","capcay",
        "rice bowl","steak","ramen","sushi","takoyaki",
        "okonomiyaki","kfc","mcd","mcdonald","hokben",
        "a&w","solaria","cfc","sabana","burger king",
        "dominos","pizza hut","wingstop","marugame",
        "yoshinoya","shihlin","mixue","warung","resto",
        "restoran","catering","prasmanan","sarapan",
        "makan siang","makan malam"

    ],

    "minuman": [

        "kopi","es kopi","americano","latte","cappuccino",
        "espresso","mocha","teh","es teh","teh tarik",
        "jus","boba","chatime","xing fu tang","starbucks",
        "janji jiwa","kopi kenangan","tomoro","fore",
        "excelso","point coffee","good day","air","galon",
        "aqua","le minerale","club","susu","yakult",
        "vit","pocari","isotonik","redbull","sprite",
        "fanta","coca cola","cola","pepsi","orange juice",
        "alpukat","mangga","kelapa","es jeruk","es campur"

    ],

    "transport": [

        "grab","grabcar","grabfood","grabexpress",
        "gojek","gocar","goride","gopay","gobox",
        "maxim","indrive","bensin","pertalite",
        "pertamax","dexlite","solar","parkir",
        "tol","kereta","kai","whoosh","lrt","mrt",
        "bus","damri","angkot","ojek","taksi",
        "bluebird","transjakarta","kapal","pesawat",
        "citilink","lion","batik air","garuda"

    ],

    "belanja": [

        "indomaret","alfamart","alfamidi","superindo",
        "hypermart","lottemart","transmart","hari hari",
        "yogya","ramayana","ace","ikea","mr diy",
        "sayur","buah","beras","telur","daging",
        "ikan","ayam","minyak","gula","garam",
        "tepung","mie instan","sabun","shampoo",
        "pasta gigi","tissue","popok","detergen",
        "sembako","belanja","grosir","pasar"

    ],

    "tagihan": [

        "pln","listrik","token","air","pam",
        "wifi","internet","indihome","biznet",
        "myrepublic","iconnet","oxygen",
        "pulsa","paket data","telkomsel",
        "indosat","tri","xl","axis","smartfren",
        "bpjs","pdam","tv kabel","first media",
        "icloud","google one","hosting","domain"

    ],

    "hiburan": [

        "netflix","spotify","youtube premium",
        "disney","viu","wetv","iqiyi","bioskop",
        "xxi","cgv","cinepolis","steam","game",
        "playstation","ps","xbox","nintendo",
        "valorant","mobile legends","ml","pubg",
        "free fire","ff","genshin","honkai",
        "roblox","minecraft","dota","csgo"

    ],

    "kesehatan": [

        "dokter","obat","apotek","kimia farma",
        "k24","century","vitamin","rumah sakit",
        "rs","lab","laboratorium","klinik",
        "medical checkup","tes darah",
        "bpjs kesehatan","vaksin","fisioterapi",
        "dokter gigi","tambal","cabut gigi",
        "optik","kacamata"

    ],

    "pendidikan": [

        "sekolah","kampus","universitas",
        "kuliah","ukt","spp","les","kursus",
        "sertifikasi","udemy","coursera",
        "dicoding","buku","ebook","modul",
        "alat tulis","pensil","pulpen","print",
        "fotocopy","skripsi","wisuda"

    ],

    "investasi": [

        "saham","stockbit","ajaib","bibit",
        "reksadana","obligasi","sbn",
        "emas","antam","pegadaian",
        "crypto","bitcoin","ethereum",
        "bnb","solana","dogecoin",
        "deposito","p2p","peer to peer"

    ],

    "gaji": [

        "gaji","salary","honor","honorarium",
        "bonus","thr","insentif","komisi",
        "fee","upah","lembur","tunjangan"

    ],

    "usaha": [

        "penjualan","jualan","omset","cash",
        "transfer masuk","pelanggan","customer",
        "invoice","project","freelance",
        "jasa","order","pesanan"

    ],

    "keluarga": [

        "istri","suami","anak","orang tua",
        "ayah","ibu","adik","kakak",
        "uang jajan","nafkah"

    ],

    "donasi": [

        "sedekah","zakat","infak","donasi",
        "masjid","gereja","yayasan",
        "bantuan","amal"

    ],

    "fashion": [

        "baju","celana","sepatu","sendal",
        "tas","jaket","kaos","kemeja",
        "hijab","topi","jam tangan",
        "aksesoris"

    ],

    "perawatan": [

        "barber","potong rambut","salon",
        "spa","facial","skincare",
        "makeup","kosmetik","parfum",
        "sabun muka"

    ],

    "rumah": [

        "kontrakan","kos","sewa rumah",
        "cicilan rumah","kpr","furniture",
        "meja","kursi","lemari","kasur",
        "kipas","ac","kulkas","tv",
        "kompor","tabung gas","elpiji"

    ],

    "kendaraan": [

        "service","servis","oli",
        "ban","aki","bengkel",
        "motor","mobil","stnk",
        "pajak kendaraan","cuci mobil",
        "cuci motor"

    ],

    "lainnya": []
}

FEATURES = {

    "STARTER": {

        # Pencatatan dasar
        "transaksi",

        # Dashboard Ringkas
        "dashboard",

        # Cek saldo
        "saldo",

        # Saldo hari ini
        "saldo_hari_ini",

        # Riwayat transaksi
        "riwayat",

        # Bantuan
        "help"

    },

    "PRO": {

        # Semua fitur Starter
        "transaksi",
        "dashboard",
        "saldo",
        "saldo_hari_ini",
        "riwayat",
        "help",

        # Budgeting
        "budget",

        # Export
        "excel",

        # Statistik dasar
        "statistik",

        #Target tabungan
        "target",
        "tabung",
        "hapustarget"

    },

    "PREMIUM": {

        # Semua fitur Pro
        "transaksi",
        "dashboard",
        "saldo",
        "saldo_hari_ini",
        "riwayat",
        "help",
        "budget",
        "reminder",
        "hapusreminder",
        "excel",
        "statistik",
        "target",
        "tabung",
        "hapustarget",

        # AI
        "ai",

        # Multi User
        "share",

        # Hutang Piutang
        "hutang",
        "piutang",

        # Export PDF
        "pdf",

        # Laporan otomatis
        "laporan_harian",

        # Insight lanjutan (opsional jika nanti dibuat)
        "forecast",
        "cashflow"

    }

}

def has_feature(sender, feature):

    user = User.query.filter_by(
        nomor_wa=sender,
        aktif=True
    ).first()


    if not user:
        return False


    # cek masa aktif paket
    if user.paket != "STARTER":

        if user.akhir_langganan:

            if user.akhir_langganan < now_jakarta().date():

                return False



    paket = (user.paket or "STARTER").upper()


    return feature in FEATURES.get(
        paket,
        set()
    )

def now_jakarta():
    return datetime.now(JAKARTA)

def periode_sekarang():
    return now_jakarta().strftime("%Y-%m")

def sekarang():
    return datetime.now(ZoneInfo("Asia/Jakarta"))

def cari_kategori(keterangan):

    teks = keterangan.lower()

    for kategori, daftar in KATEGORI.items():

        for sub in daftar:

            if sub in teks:

                return kategori, sub

    return "lainnya", "lainnya"

def generate_dashboard_link(nomor_wa):

    token = serializer.dumps(nomor_wa)

    return f"{BASE_URL}/dashboard/{token}"

def verify_token(token):

    try:

        nomor = serializer.loads(
            token,
            max_age=60 * 30  # 30 menit
        )

        return nomor

    except (BadSignature, SignatureExpired):

        return None

# =========================
# VALIDASI FORMAT PENOMORAN
# =========================
def normalize_wa(nomor):

    if not nomor:
        return None

    nomor = str(nomor).strip()

    nomor = nomor.replace("@s.whatsapp.net", "")
    nomor = nomor.replace("+", "")
    nomor = nomor.replace(" ", "")
    nomor = nomor.replace("-", "")

    if nomor.startswith("08"):
        nomor = "62" + nomor[1:]

    elif nomor.startswith("8"):
        nomor = "62" + nomor

    elif not nomor.startswith("62"):
        return None

    # Panjang nomor Indonesia umumnya 11-15 digit
    if len(nomor) < 11 or len(nomor) > 15:
        return None

    return nomor

import re

def normalize_nominal(nominal):

    if nominal is None:
        return None

    nominal = str(nominal).strip().lower()

    nominal = nominal.replace("rp", "")

    # Jika ada koma, buang bagian desimal
    if "," in nominal:
        nominal = nominal.split(",")[0]

    # Sisakan angka saja
    nominal = re.sub(r"[^0-9]", "", nominal)

    if not nominal:
        return None

    return int(nominal)


# =========================
# VALIDASI USER
# =========================
def user_terdaftar(nomor):

    nomor = normalize_wa(nomor)

    return User.query.filter(
        User.nomor_wa == nomor,
        User.aktif.is_(True)
    ).first()

def transaksi_user(sender):
    return Transaksi.query.filter(
        Transaksi.nomor_wa == sender
    )


# =========================
# FONNTE SEND MESSAGE
# =========================
# FONTE_TOKEN = os.getenv("FONTE_TOKEN")

# def kirim_wa(nomor, pesan):
#     try:

#         response = requests.post(
#             "https://api.fonnte.com/send",
#             headers={
#                 "Authorization": FONTE_TOKEN
#             },
#             data={
#                 "target": nomor,
#                 "message": pesan,
#                 "delay": 2
#             },
#             timeout=30
#         )

#         print("=" * 60)
#         print("FONNTE SEND")
#         print("TO     :", nomor)
#         print("STATUS :", response.status_code)
#         print("BODY   :", response.text)
#         print("=" * 60)

#     except Exception as e:
#         print("ERROR FONNTE :", str(e))

# ==========================================
# BABLAST CONFIG
# ==========================================
BABLAST_API_KEY = os.getenv("BABLAST_API_KEY")

import requests

session = requests.Session()


def kirim_wa(nomor, pesan):

    try:

        response = session.post(

            "https://api.bablast.id/send",

            headers={

                "Authorization": f"Bearer {BABLAST_API_KEY}",

                "Content-Type": "application/json"

            },

            json={

                "phone": nomor,

                "message": pesan

            },

            timeout=30

        )

        print("=" * 60)
        print("BABLAST SEND")
        print("TO      :", nomor)
        print("STATUS  :", response.status_code)

        try:
            print("BODY    :", response.json())
        except:
            print("BODY    :", response.text)

        print("=" * 60)

        if response.status_code != 200:
            return False

        result = response.json()

        # Sesuaikan jika struktur response Bablast berbeda
        if result.get("success") is True:
            return True

        return False

    except Exception as e:

        print("=" * 60)
        print("BABLAST ERROR")
        print(str(e))
        print("=" * 60)

        return False

def hitung_saldo(nomor_wa):

    total_masuk = db.session.query(
        db.func.coalesce(db.func.sum(Transaksi.nominal), 0)
    ).filter(
        Transaksi.nomor_wa == nomor_wa,
        Transaksi.tipe == "MASUK"
    ).scalar()

    total_keluar = db.session.query(
        db.func.coalesce(db.func.sum(Transaksi.nominal), 0)
    ).filter(
        Transaksi.nomor_wa == nomor_wa,
        Transaksi.tipe == "KELUAR"
    ).scalar()

    return total_masuk - total_keluar



def progress_bar(persen):

    penuh = int(persen / 10)

    return "🟩" * penuh + "⬜" * (10 - penuh)

def ai_insight(sender):

    bulan = periode_sekarang()

    data = transaksi_user(sender).filter(
        Transaksi.tipe == "KELUAR"
    ).all()

    if not data:
        return "Belum ada data untuk dianalisis."

    total = sum(x.nominal for x in data)

    kategori = {}

    for trx in data:

        kategori.setdefault(trx.kategori, 0)

        kategori[trx.kategori] += trx.nominal

    kategori_terbesar = max(
        kategori,
        key=kategori.get
    )

    nominal = kategori[kategori_terbesar]

    persen = nominal / total * 100

    insight = []

    insight.append(
        f"📊 Pengeluaran terbesar berada pada kategori *{kategori_terbesar.title()}* ({persen:.1f}%)."
    )

    if persen > 50:

        insight.append(
            f"⚠️ Lebih dari setengah pengeluaran berasal dari {kategori_terbesar}."
        )

    elif persen > 30:

        insight.append(
            f"💡 Pengeluaran {kategori_terbesar} mulai mendominasi bulan ini."
        )

    else:

        insight.append(
            "✅ Pengeluaran masih cukup seimbang antar kategori."
        )

    return "\n".join(insight)

def get_harga_paket(nama_paket):
    """
    Mengembalikan informasi harga paket beserta promo yang sedang aktif.
    """

    from models import PromoPaket

    hari_ini = sekarang().date()

    # =========================
    # HARGA NORMAL
    # =========================

    harga_normal = {
        "STARTER": 19000,
        "PRO": 49000,
        "PREMIUM": 75000
    }

    paket = nama_paket.upper()

    harga = harga_normal.get(paket, 0)

    # =========================
    # CEK PROMO
    # =========================

    promo = PromoPaket.query.filter(
        PromoPaket.aktif == True,
        PromoPaket.paket == paket,
        PromoPaket.tanggal_mulai <= hari_ini,
        PromoPaket.tanggal_selesai >= hari_ini
    ).first()

    if promo:

        return {

            "promo": True,

            "nama_promo": promo.nama,

            "paket": paket,

            "harga_normal": harga,

            "harga": promo.harga_promo,

            "hemat": harga - promo.harga_promo,

            "tanggal_mulai": promo.tanggal_mulai,

            "tanggal_selesai": promo.tanggal_selesai

        }

    return {

        "promo": False,

        "nama_promo": None,

        "paket": paket,

        "harga_normal": harga,

        "harga": harga,

        "hemat": 0,

        "tanggal_mulai": None,

        "tanggal_selesai": None

    }


def get_missing_periods(nomor_wa):

    last = (
        MonthlySummary.query
        .filter_by(nomor_wa=nomor_wa)
        .order_by(MonthlySummary.periode.desc())
        .first()
    )

    if last is None:
        return []

    tahun, bulan = map(int, last.periode.split("-"))

    sekarang = now_jakarta()

    hasil = []

    while True:

        bulan += 1

        if bulan == 13:
            bulan = 1
            tahun += 1

        if (
            tahun == sekarang.year
            and bulan == sekarang.month
        ):
            break

        hasil.append(
            f"{tahun}-{bulan:02d}"
        )

    return hasil

def verify_monthly_summary(nomor_wa):
    """
    Memastikan seluruh Monthly Summary selalu lengkap.

    Jika ada bulan yang belum pernah di-closing,
    maka otomatis dibuat snapshot hingga bulan terakhir
    sebelum bulan berjalan.

    Seluruh proses dijalankan dalam satu transaksi database.
    """

    missing = get_missing_periods(nomor_wa)

    if not missing:
        return

    user = User.query.filter_by(
        nomor_wa=nomor_wa
    ).first()

    if user is None:
        return

    print("=" * 60)
    print("AUTO VERIFY MONTHLY SUMMARY")
    print("Nomor WA :", nomor_wa)
    print("Missing  :", missing)
    print("=" * 60)

    try:

        for periode in missing:

            print(f"Closing {periode}")

            closing_user(
                user,
                periode
            )

        # copy budget, summary, dll baru disimpan sekali
        db.session.commit()

        print("=" * 60)
        print("VERIFY SUCCESS")
        print("=" * 60)

    except Exception as e:

        db.session.rollback()

        import traceback
        traceback.print_exc()

        print("=" * 60)
        print("VERIFY FAILED")
        print(str(e))
        print("=" * 60)

        raise
