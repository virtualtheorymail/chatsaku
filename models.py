from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from zoneinfo import ZoneInfo
from sqlalchemy import func

db = SQLAlchemy()

JAKARTA = ZoneInfo("Asia/Jakarta")


def now_jakarta():
    return datetime.now(JAKARTA)

class User(db.Model):

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    nama = db.Column(db.String(100), nullable=False)

    nomor_wa = db.Column(
        db.String(30),
        unique=True,
        nullable=False,
        index=True
    )

    aktif = db.Column(
        db.Boolean,
        default=True
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=now_jakarta
    )
    mulai_langganan = db.Column(db.Date)

    akhir_langganan = db.Column(db.Date)

    paket = db.Column(db.String(30), default="STARTER")

class UserLogin(db.Model):

    __tablename__ = "user_login"

    id = db.Column(db.Integer, primary_key=True)

    nama = db.Column(db.String(100), nullable=False)

    email = db.Column(
        db.String(120),
        unique=True,
        nullable=False,
        index=True
    )

    nomor_whatsapp = db.Column(
        db.String(30),
        unique=True,
        nullable=False
    )

    password = db.Column(
        db.String(255),
        nullable=False
    )

class Transaksi(db.Model):

    __tablename__ = "transaksi"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    tanggal = db.Column(
        db.DateTime(timezone=True),
        default=now_jakarta,
        index=True
    )

    tipe = db.Column(
        db.String(20),
        index=True
    )

    nominal = db.Column(
        db.BigInteger,
        nullable=False
    )

    kategori = db.Column(
        db.String(50),
        index=True
    )

    subkategori = db.Column(
        db.String(100)
    )

    keterangan = db.Column(
        db.String(255)
    )

    nomor_wa = db.Column(
        db.String(30),
        index=True
    )

    __table_args__ = (
        db.Index(
            "idx_transaksi_user_tanggal",
            "nomor_wa",
            "tanggal"
        ),
    )

class Budget(db.Model):

    __tablename__ = "budget"

    id = db.Column(db.Integer, primary_key=True)

    nomor_wa = db.Column(db.String(30), nullable=False, index=True)

    kategori = db.Column(db.String(100), nullable=False)

    nominal = db.Column(db.Integer, nullable=False)

    periode = db.Column(db.String(7), nullable=False)   # contoh: 2026-06

    dibuat = db.Column(
        db.DateTime(timezone=True),
        default=now_jakarta
    )

    auto_repeat = db.Column(
        db.Boolean,
        default=True
    )

    __table_args__ = (
        db.UniqueConstraint(
            "nomor_wa",
            "kategori",
            "periode",
            name="uq_budget"
        ),
    )

class Reminder(db.Model):

    __tablename__ = "reminder"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    nomor_wa = db.Column(
        db.String(30),
        nullable=False,
        index=True
    )

    nama = db.Column(
        db.String(100),
        nullable=False
    )

    nominal = db.Column(
        db.Integer,
        default=0
    )

    tanggal = db.Column(
        db.Integer,
        nullable=False
    )

    aktif = db.Column(
        db.Boolean,
        default=True
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=now_jakarta
    )

class RequestDemo(db.Model):

    __tablename__ = "request_demo"

    id = db.Column(db.Integer, primary_key=True)

    nomor_wa = db.Column(db.String(30), nullable=False, unique=True)

    nama = db.Column(db.String(150))

    status = db.Column(db.String(20), default="BARU")

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=now_jakarta
    )

class TargetPembelian(db.Model):

    __tablename__ = "target_pembelian"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    nomor_wa = db.Column(
        db.String(30),
        nullable=False,
        index=True
    )

    nama = db.Column(
        db.String(150),
        nullable=False
    )

    target = db.Column(
        db.Integer,
        nullable=False
    )

    terkumpul = db.Column(
        db.Integer,
        default=0
    )

    deadline = db.Column(
        db.Date,
        nullable=False
    )

    aktif = db.Column(
        db.Boolean,
        default=True
    )

    created_at = db.Column(
        db.DateTime,
        default=now_jakarta
    )

class HutangPiutang(db.Model):

    __tablename__ = "hutang_piutang"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    nomor_wa = db.Column(
        db.String(30),
        nullable=False,
        index=True
    )

    tipe = db.Column(
        db.String(20),
        nullable=False
    )
    # HUTANG = kita punya kewajiban
    # PIUTANG = orang lain punya kewajiban ke kita


    nama = db.Column(
        db.String(100),
        nullable=False
    )


    nominal = db.Column(
        db.Integer,
        nullable=False
    )


    keterangan = db.Column(
        db.String(255)
    )


    status = db.Column(
        db.String(20),
        default="BELUM_LUNAS"
    )


    tanggal = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


    lunas_tanggal = db.Column(
        db.DateTime,
        nullable=True
    )

class PromoPaket(db.Model):

    __tablename__ = "promo_paket"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    nama = db.Column(
        db.String(100),
        nullable=False
    )

    paket = db.Column(
        db.String(20),
        nullable=False
    )  # FREE / BASIC / PRO

    harga_promo = db.Column(
        db.Integer,
        nullable=False
    )

    tanggal_mulai = db.Column(
        db.Date,
        nullable=False
    )

    tanggal_selesai = db.Column(
        db.Date,
        nullable=False
    )

    aktif = db.Column(
        db.Boolean,
        default=True
    )

    created_at = db.Column(
        db.DateTime,
        default=now_jakarta
    )

class MonthlySummary(db.Model):
    __tablename__ = "monthly_summary"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    nomor_wa = db.Column(
        db.String(30),
        nullable=False,
        index=True
    )

    # contoh : 2026-07
    periode = db.Column(
        db.String(7),
        nullable=False,
        index=True
    )

    # saldo akhir bulan sebelumnya
    saldo_awal = db.Column(
        db.BigInteger,
        default=0
    )

    # total pemasukan bulan ini
    total_masuk = db.Column(
        db.BigInteger,
        default=0
    )

    # total pengeluaran bulan ini
    total_keluar = db.Column(
        db.BigInteger,
        default=0
    )

    # pemasukan - pengeluaran
    saving = db.Column(
        db.BigInteger,
        default=0
    )

    # saldo akhir bulan
    saldo_akhir = db.Column(
        db.BigInteger,
        default=0
    )

    total_transaksi = db.Column(
        db.Integer,
        default=0
    )

    status = db.Column(
        db.String(20),
        default="CLOSED"
    )

    closed_at = db.Column(
        db.DateTime(timezone=True),
        default=now_jakarta
    )

    checksum = db.Column(
        db.String(64)
    )

    __table_args__ = (

        db.UniqueConstraint(
            "nomor_wa",
            "periode",
            name="uq_monthly_summary"
        ),

    )

class SystemLock(db.Model):

    __tablename__ = "system_lock"

    nama = db.Column(
        db.String(50),
        primary_key=True
    )

    locked = db.Column(
        db.Boolean,
        default=False
    )

    updated_at = db.Column(
        db.DateTime,
        default=now_jakarta
    )

class SharedAccess(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    owner = db.Column(db.String(20), nullable=False)

    member = db.Column(db.String(20), nullable=False)

    aktif = db.Column(db.Boolean, default=True)

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

def get_owner_number(nomor):

    share = SharedAccess.query.filter_by(
        member=nomor,
        aktif=True
    ).first()

    if share:
        return share.owner

    return nomor

def acquire_lock():

    lock = SystemLock.query.get(
        "MONTHLY_CLOSING"
    )

    if lock is None:

        lock = SystemLock(

            nama="MONTHLY_CLOSING",

            locked=False

        )

        db.session.add(lock)

        db.session.commit()

    if lock.locked:

        return False

    lock.locked = True

    lock.updated_at = now_jakarta()

    db.session.commit()

    return True

def release_lock():

    lock = SystemLock.query.get(
        "MONTHLY_CLOSING"
    )

    if lock:

        lock.locked = False

        lock.updated_at = now_jakarta()

        db.session.commit()

def get_last_summary(nomor_wa):

    return MonthlySummary.query.filter_by(
        nomor_wa=nomor_wa
    ).order_by(
        MonthlySummary.periode.desc()
    ).first()

# def get_saldo_awal_bulan(nomor_wa, periode):

#     summary = get_summary(
#         nomor_wa,
#         periode
#     )

#     if summary:
#         return summary.saldo_awal

#     last = get_last_summary(
#         nomor_wa
#     )

#     if last:
#         return last.saldo_akhir

#     return 0

def calculate_opening_balance(
    nomor_wa,
    periode
):

    tahun, bulan = map(
        int,
        periode.split("-")
    )

    if bulan == 1:

        prev = f"{tahun-1}-12"

    else:

        prev = f"{tahun}-{bulan-1:02d}"

    summary = MonthlySummary.query.filter_by(
        nomor_wa=nomor_wa,
        periode=prev
    ).first()

    if summary:
        return summary.saldo_akhir

    awal_bulan = datetime(
        tahun,
        bulan,
        1
    )

    total_masuk = db.session.query(

        func.coalesce(
            func.sum(
                Transaksi.nominal
            ),
            0

        )

    ).filter(

        Transaksi.nomor_wa == nomor_wa,

        Transaksi.tipe == "MASUK",

        Transaksi.tanggal < awal_bulan

    ).scalar()

    total_keluar = db.session.query(

        func.coalesce(
            func.sum(
                Transaksi.nominal
            ),
            0

        )

    ).filter(

        Transaksi.nomor_wa == nomor_wa,

        Transaksi.tipe == "KELUAR",

        Transaksi.tanggal < awal_bulan

    ).scalar()

    return total_masuk-total_keluar

def get_saldo_akhir(nomor_wa):

    last = get_last_summary(
        nomor_wa
    )

    if last:
        return last.saldo_akhir

    return 0

def is_viewer(nomor):

    share = SharedAccess.query.filter_by(
        member=nomor,
        aktif=True
    ).first()

    if share:
        return True

    return False

from datetime import datetime


class Payment(db.Model):

    __tablename__ = "payments"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    # Relasi ke akun website
    user_login_id = db.Column(
        db.Integer,
        db.ForeignKey("user_login.id"),
        nullable=False
    )

    order_id = db.Column(
        db.String(100),
        unique=True,
        nullable=False
    )

    paket = db.Column(
        db.String(50),
        nullable=False
    )

    harga_normal = db.Column(
        db.Integer,
        nullable=False
    )

    harga_bayar = db.Column(
        db.Integer,
        nullable=False
    )

    promo_id = db.Column(
        db.Integer,
        db.ForeignKey("promo_paket.id"),
        nullable=True
    )

    promo = db.relationship(
        "PromoPaket"
    )

    status = db.Column(
        db.String(30),
        default="PENDING"
    )

    midtrans_token = db.Column(db.String(255))

    midtrans_response = db.Column(db.Text)

    created_at = db.Column(
        db.DateTime,
        default=now_jakarta
    )

    paid_at = db.Column(db.DateTime)

    login_user = db.relationship(
        "UserLogin",
        backref="payments"
    )
