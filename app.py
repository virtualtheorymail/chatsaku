from flask import Flask, request, jsonify, render_template, send_file, redirect
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta, time as dt_time
import time
from models import db, Transaksi, Budget, Reminder, User, RequestDemo, HutangPiutang, TargetPembelian, PromoPaket, MonthlySummary, get_last_summary, get_saldo_akhir, UserLogin, Payment
from routes.webhook import webhook_bp
import requests
import os
import pandas as pd
import io
from zoneinfo import ZoneInfo
from itsdangerous import URLSafeTimedSerializer
from itsdangerous import BadSignature
from itsdangerous import SignatureExpired
from utils.helper import *
from config import bcrypt, jwt, cors, init_extensions

from sqlalchemy import func
from calendar import monthrange

from apscheduler.schedulers.background import BackgroundScheduler
from zoneinfo import ZoneInfo
import atexit
from flask_jwt_extended import jwt_required, get_jwt_identity
from auth import auth_bp
import json
from routes.nlp_router import parse_message

app = Flask(__name__)

app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(days=30)

init_extensions(app)

app.register_blueprint(auth_bp)

# def scheduler_loop():

#     print("Scheduler Started")

#     while True:

#         try:

#             print("Server  :", sekarang())
#             print("Jakarta :", now_jakarta())

#             schedule.run_pending()

#         except Exception:
#             import traceback
#             traceback.print_exc()

#         time.sleep(1)
# =========================
# CONFIG DB
# =========================
# app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///kas.db"
# ambil DATABASE_URL dari Railway
database_url = os.getenv("DATABASE_URL")

# FIX untuk Railway (postgres:// -> postgresql://)
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

# ❗ INI WAJIB ADA
app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

app.register_blueprint(webhook_bp)

ADMIN_NUMBER = os.getenv("ADMIN_NUMBER")

with app.app_context():
    db.create_all()

@app.route("/admin/users")
def admin_users():

    search = request.args.get("search", "")

    page = request.args.get(
        "page",
        1,
        type=int
    )

    page_request = request.args.get(
        "page_request",
        1,
        type=int
    )

    # =====================================
    # REGISTERED USER
    # =====================================

    query = User.query

    if search:

        query = query.filter(
            User.nomor_wa.contains(search)
        )

    users = query.order_by(
        User.created_at.desc()
    ).paginate(
        page=page,
        per_page=15
    )

    # =====================================
    # REQUEST DEMO
    # =====================================

    request_users = RequestDemo.query.order_by(
        RequestDemo.created_at.desc()
    ).paginate(
        page=page_request,
        per_page=15
    )

    return render_template(
        "admin_users.html",
        users=users,
        request_users=request_users,
        search=search
    )

from datetime import date, timedelta

@app.route("/admin/users/add", methods=["POST"])
def add_user():

    nama = request.form["nama"].strip()

    nomor = request.form["nomor"].strip()

    durasi = int(request.form.get("durasi", 30))

    if User.query.filter_by(
        nomor_wa=nomor
    ).first():

        return redirect("/admin/users")

    mulai = date.today()

    akhir = mulai + timedelta(days=durasi)

    user = User(
        nama=nama,
        nomor_wa=nomor,
        aktif=True,
        mulai_langganan=mulai,
        akhir_langganan=akhir
    )

    db.session.add(user)

    db.session.commit()

    return redirect("/admin/users")

from datetime import date, timedelta

@app.route("/admin/users/toggle/<int:id>")
def toggle_user(id):

    user = User.query.get_or_404(id)

    if user.aktif:

        user.aktif = False

    else:

        user.aktif = True

        user.mulai_langganan = date.today()

        user.akhir_langganan = date.today() + timedelta(days=30)

    db.session.commit()

    return redirect("/admin/users")

@app.route("/admin/users/delete/<int:id>")
def delete_user(id):

    user = User.query.get_or_404(id)

    nomor = user.nomor_wa

    # Hapus semua transaksi
    Transaksi.query.filter_by(
        nomor_wa=nomor
    ).delete()

    # Hapus semua budget
    Budget.query.filter_by(
        nomor_wa=nomor
    ).delete()

    # Hapus semua reminder
    Reminder.query.filter_by(
        nomor_wa=nomor
    ).delete()

    # Hapus request demo
    RequestDemo.query.filter_by(
        nomor_wa=nomor
    ).delete()

    # Hapus user
    db.session.delete(user)

    db.session.commit()

    return redirect("/admin/users")

@app.route("/dashboard/<token>")
def dashboard(token):

    nomor = verify_token(token)

    if not nomor:
        return render_template(
            "link_expired.html"
        )
    verify_monthly_summary(nomor)
    # =========================
    # PARAMETER
    # =========================

    page = request.args.get("page", 1, type=int)
    per_page = 10

    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    # =========================
    # QUERY DASAR
    # =========================

    query = Transaksi.query.filter(
        Transaksi.nomor_wa == nomor
    )

    # =========================
    # FILTER TANGGAL
    # =========================

    try:
        if start_date:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            query = query.filter(
                Transaksi.tanggal >= start
            )

        if end_date:
            # +1 hari agar seluruh transaksi pada tanggal tersebut ikut terambil
            end = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(
                Transaksi.tanggal < end
            )

    except ValueError:
        # Abaikan jika format tanggal tidak valid
        pass

    # =========================
    # PAGINATION
    # =========================

    data_paginated = query.order_by(
        Transaksi.tanggal.desc()
    ).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )

    # =========================
    # DATA UNTUK CHART & SUMMARY
    # =========================

    all_data = query.order_by(
        Transaksi.tanggal.desc()
    ).all()

    total_masuk = sum(
        x.nominal
        for x in all_data
        if x.tipe == "MASUK"
    )

    total_keluar = sum(
        x.nominal
        for x in all_data
        if x.tipe == "KELUAR"
    )

    saldo = total_masuk - total_keluar

    # ==========================================
    # SAVING
    # ==========================================

    saving = saldo

    saving_persen = 0

    if total_masuk > 0:
        saving_persen = round((saving / total_masuk) * 100, 1)

    # ==========================================
    # BUDGET BULAN INI
    # ==========================================

    periode = periode_sekarang()

    budget_list = Budget.query.filter_by(
        nomor_wa=nomor,
        periode=periode
    ).all()

    budget_data = []

    for b in budget_list:

        terpakai = db.session.query(
            db.func.coalesce(db.func.sum(Transaksi.nominal), 0)
        ).filter(
            Transaksi.nomor_wa == nomor,
            Transaksi.tipe == "KELUAR",
            Transaksi.kategori == b.kategori,
            db.func.to_char(
                Transaksi.tanggal,
                "YYYY-MM"
            ) == periode
        ).scalar()

        sisa = b.nominal - terpakai

        persen = 0

        if b.nominal > 0:
            persen = round((terpakai / b.nominal) * 100)

        budget_data.append({

            "kategori": b.kategori,
            "budget": b.nominal or 0,
            "terpakai": terpakai or 0,
            "sisa": sisa or 0,
            "persen": persen

        })

    # ==========================================
    # TARGET PEMBELIAN / TABUNGAN
    # ==========================================

    target_pembelian = TargetPembelian.query.filter(
        TargetPembelian.nomor_wa == nomor,
        TargetPembelian.aktif == True
    ).order_by(
        TargetPembelian.deadline.asc()
    ).first()

    target_data = None

    if target_pembelian:

        progress = 0

        if target_pembelian.target > 0:
            progress = round(
                (target_pembelian.terkumpul / target_pembelian.target) * 100,
                1
            )

        progress = min(progress, 100)

        sisa = max(
            target_pembelian.target - target_pembelian.terkumpul,
            0
        )

        sisa_hari = (
            target_pembelian.deadline - sekarang().date()
        ).days

        target_data = {

            "id": target_pembelian.id,

            "nama": target_pembelian.nama,

            "target": target_pembelian.target,

            "terkumpul": target_pembelian.terkumpul,

            "sisa": sisa,

            "progress": progress,

            "deadline": target_pembelian.deadline,

            "sisa_hari": sisa_hari,

            "selesai": progress >= 100

        }

    # ==========================================
    # REMINDER TAGIHAN
    # ==========================================

    reminders = Reminder.query.filter_by(
        nomor_wa=nomor,
        aktif=True
    ).order_by(
        Reminder.tanggal.asc()
    ).all()

    # ==========================================
    # AI FINANCE INSIGHT
    # ==========================================

    from utils.ai_insight import generate_ai_insight

    insight = generate_ai_insight(nomor)
    # ==========================
    # HUTANG PIUTANG SUMMARY
    # ==========================

    hutang_list = HutangPiutang.query.filter(
        HutangPiutang.nomor_wa == nomor,
        HutangPiutang.tipe == "HUTANG",
        HutangPiutang.status != "LUNAS"
    ).order_by(
        HutangPiutang.tanggal.desc()
    ).all()

    piutang_list = HutangPiutang.query.filter(
        HutangPiutang.nomor_wa == nomor,
        HutangPiutang.tipe == "PIUTANG",
        HutangPiutang.status != "LUNAS"
    ).order_by(
        HutangPiutang.tanggal.desc()
    ).all()

    total_hutang = sum(
        x.nominal for x in hutang_list
    )


    total_piutang = sum(
        x.nominal for x in piutang_list
    )


    net_balance = total_piutang - total_hutang


    # =====================================================
    # USER
    # =====================================================

    user = User.query.filter_by(nomor_wa=nomor).first()

    # =====================================================
    # PROFILE
    # =====================================================

    tanggal_daftar = (
        user.dibuat.strftime("%d %b %Y")
        if getattr(user, "dibuat", None)
        else "-"
    )

    # =====================================================
    # SUMMARY
    # =====================================================

    financial_score = 100

    if total_masuk > 0:

        rasio = total_keluar / total_masuk

        if rasio > .90:
            financial_score -= 35

        elif rasio > .75:
            financial_score -= 20

    for b in budget_data:

        if b["persen"] > 100:
            financial_score -= 10

    financial_score = max(financial_score, 0)

    if financial_score >= 80:
        financial_status = "Excellent"

    elif financial_score >= 60:
        financial_status = "Good"

    elif financial_score >= 40:
        financial_status = "Warning"

    else:
        financial_status = "Critical"


    closing_status = "Open"

    target_saving = 1000000
    saving_target_percent = 65

    streak = 27

    # =====================================================
    # AI
    # =====================================================

    ai_summary = (
        "Pengeluaran masih terkendali. "
        "Saving berada di atas target. "
        "Belum ada indikasi over budget."
    )

    ai_recommendation = [

        "Pertahankan saving minimal 20%.",

        "Kurangi pengeluaran hiburan.",

        "Lakukan closing pada akhir bulan."

    ]

    # =====================================================
    # ANALYTICS
    # =====================================================

    top_category = "Makanan"
    top_nominal = 1750000

    low_category = "Investasi"
    low_nominal = 250000

    prediksi_saldo = saldo

    budget_risk = "Rendah"

    budget_risk_desc = "Budget masih aman"

    # =====================================================
    # REMINDER
    # =====================================================

    reminder_count = 0
    reminder_today = 0
    reminder_week = 0
    reminder_month = 0
    reminder_overdue = 0

    reminder_count = len(reminders)

    reminder_today = 0
    reminder_week = 0
    reminder_month = 0
    reminder_overdue = 0

    reminder_list = []

    today = sekarang().date()

    for r in reminders:

        tanggal = date(today.year, today.month, r.tanggal)

        if tanggal < today:
            if today.month == 12:
                tanggal = date(today.year + 1, 1, r.tanggal)
            else:
                tanggal = date(today.year, today.month + 1, r.tanggal)

        selisih = (tanggal - today).days

        if selisih < 0:
            reminder_overdue += 1

        elif selisih == 0:
            reminder_today += 1

        elif selisih <= 7:
            reminder_week += 1

        reminder_month += 1

        if selisih < 0:
            status = f"Terlambat {abs(selisih)} hari"
            warna = "danger"
        elif selisih == 0:
            status = "Hari ini"
            warna = "warning"
        elif selisih == 1:
            status = "Besok"
            warna = "warning"
        else:
            status = f"{selisih} hari lagi"
            warna = "success"

        reminder_list.append({
            "hari": tanggal.strftime("%d"),
            "bulan": tanggal.strftime("%b").upper(),
            "judul": r.nama,
            "kategori": getattr(r, "kategori", "-"),
            "catatan": getattr(r, "catatan", ""),
            "nominal": r.nominal,
            "status": status,
            "status_color": warna
        })

    # =====================================================
    # BUDGET
    # =====================================================

    budget_list = budget_data

    saldo_awal = saldo

    # =====================================================
    # WEEKLY PRODUCTIVITY
    # =====================================================

    weekly_activity = [

        {"nama":"Sen","persen":80,"total":8},

        {"nama":"Sel","persen":60,"total":6},

        {"nama":"Rab","persen":100,"total":10},

        {"nama":"Kam","persen":70,"total":7},

        {"nama":"Jum","persen":55,"total":5},

        {"nama":"Sab","persen":35,"total":3},

        {"nama":"Min","persen":20,"total":2}

    ]

    # =====================================================
    # TRANSAKSI TERBARU
    # =====================================================

    transaksi_terbaru = []

    for trx in all_data[:10]:

        transaksi_terbaru.append({

            "jenis": trx.tipe.lower(),

            "keterangan": trx.keterangan,

            "kategori": trx.kategori,

            "tanggal": trx.tanggal.strftime("%d %b"),

            "jam": trx.tanggal.strftime("%H:%M"),

            "nominal": trx.nominal,

            "saldo": saldo

        })

    transaksi_hari_ini = 0
    masuk_hari_ini = 0
    keluar_hari_ini = 0
    saving_hari_ini = 0

    today = sekarang().date()

    trx_today = [

        x for x in all_data

        if x.tanggal.date() == today

    ]

    transaksi_hari_ini = len(trx_today)

    masuk_hari_ini = sum(

        x.nominal

        for x in trx_today

        if x.tipe == "MASUK"

    )

    keluar_hari_ini = sum(

        x.nominal

        for x in trx_today

        if x.tipe == "KELUAR"

    )

    saving_hari_ini = masuk_hari_ini - keluar_hari_ini

    # =====================================================
    # TREND CHART
    # =====================================================

    trend_label = []
    trend_value = []

    for trx in all_data:

        tanggal = trx.tanggal.strftime("%d %b")

        if tanggal not in trend_label:
            trend_label.append(tanggal)
            trend_value.append(trx.nominal)

        else:
            index = trend_label.index(tanggal)
            trend_value[index] += trx.nominal

    # =========================
    # RENDER
    # =========================

    return render_template(

        "index.html",

        user=user,

        saldo=saldo,
        periode=periode,

        tanggal_daftar=tanggal_daftar,

        financial_score=financial_score,
        financial_status=financial_status,

        ai_summary=ai_summary,
        ai_recommendation=ai_recommendation,

        top_category=top_category,
        top_nominal=top_nominal,
        low_category=low_category,
        low_nominal=low_nominal,

        prediksi_saldo=prediksi_saldo,

        budget_risk=budget_risk,
        budget_risk_desc=budget_risk_desc,

        reminder_count=reminder_count,
        reminder_today=reminder_today,
        reminder_week=reminder_week,
        reminder_month=reminder_month,
        reminder_overdue=reminder_overdue,
        reminder_list=reminder_list,

        budget_list=budget_list,

        saldo_awal=saldo_awal,

        closing_status=closing_status,

        target_saving=target_saving,
        saving_target_percent=saving_target_percent,

        streak=streak,

        transaksi_terbaru=transaksi_terbaru,
        transaksi_hari_ini=transaksi_hari_ini,
        masuk_hari_ini=masuk_hari_ini,
        keluar_hari_ini=keluar_hari_ini,
        saving_hari_ini=saving_hari_ini,

        weekly_activity=weekly_activity,
        saving=saving,
        saving_persen=saving_persen,

        total_masuk=total_masuk,
        total_keluar=total_keluar,

        insight=insight,

        budget_data=budget_data,

        hutang_list=hutang_list,
        piutang_list=piutang_list,

        total_hutang=total_hutang,
        total_piutang=total_piutang,
        net_balance=net_balance,

        target_data=target_data,

        data_paginated=data_paginated,

        trend_label=trend_label,
        trend_value=trend_value,
        now=date.today()

    )

@app.route("/expired")
def expired():

    return render_template(
        "link_expired.html"
    )

@app.route("/dashboard-data/<token>")
def dashboard_data(token):

    nomor = verify_token(token)

    if not nomor:
        return jsonify({"status": False}), 403

    transaksi = (
        Transaksi.query
        .filter_by(nomor_wa=nomor)
        .order_by(Transaksi.tanggal.desc())
        .limit(10)
        .all()
    )

    total_masuk = db.session.query(
        db.func.coalesce(db.func.sum(Transaksi.nominal),0)
    ).filter(
        Transaksi.nomor_wa==nomor,
        Transaksi.tipe=="MASUK"
    ).scalar()

    total_keluar = db.session.query(
        db.func.coalesce(db.func.sum(Transaksi.nominal),0)
    ).filter(
        Transaksi.nomor_wa==nomor,
        Transaksi.tipe=="KELUAR"
    ).scalar()

    saldo = total_masuk-total_keluar

    rows=[]

    for t in transaksi:

        rows.append({
            "id": t.id,
            "tanggal":t.tanggal.strftime("%d/%m/%Y %H:%M"),
            "tipe":t.tipe,
            "nominal":t.nominal,
            "kategori":t.kategori or "-",
            "keterangan":t.keterangan or "-"

        })

    return jsonify({

        "saldo":saldo,
        "masuk":total_masuk,
        "keluar":total_keluar,
        "rows":rows

    })

# =========================
# LOG REQUEST
# =========================
@app.before_request
def log_all():
    print("=" * 80)
    print("PATH :", request.path)
    print("METHOD :", request.method)
    print("CONTENT TYPE :", request.content_type)
    print("=" * 80)

@app.route("/")
def home():
    return render_template("home.html")

# =========================
# EXPORT EXCEL
# =========================
@app.route("/export-excel")
def export_excel():

    # =========================
    # VERIFIKASI TOKEN
    # =========================
    token = request.args.get("token")

    nomor = verify_token(token)

    if not nomor:
        return "Unauthorized", 403

    # =========================
    # FILTER TANGGAL
    # =========================
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")

    query = Transaksi.query.filter(
        Transaksi.nomor_wa == nomor
    )

    if start_date:
        query = query.filter(
            db.func.date(Transaksi.tanggal) >= start_date
        )

    if end_date:
        query = query.filter(
            db.func.date(Transaksi.tanggal) <= end_date
        )

    # =========================
    # AMBIL DATA
    # =========================
    data = query.order_by(
        Transaksi.tanggal.desc()
    ).all()

    rows = []

    for row in data:

        rows.append({
            "Tanggal": row.tanggal.strftime("%d-%m-%Y %H:%M"),
            "Tipe": row.tipe,
            "Nominal": row.nominal,
            "Keterangan": row.keterangan,
            "Nomor WA": row.nomor_wa
        })

    df = pd.DataFrame(rows)

    output = io.BytesIO()

    with pd.ExcelWriter(
        output,
        engine="openpyxl"
    ) as writer:

        df.to_excel(
            writer,
            index=False,
            sheet_name="Kas WhatsApp"
        )

        worksheet = writer.sheets["Kas WhatsApp"]

        for column in worksheet.columns:

            max_length = 0

            column_letter = column[0].column_letter

            for cell in column:

                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except Exception:
                    pass

            worksheet.column_dimensions[
                column_letter
            ].width = max_length + 3

    output.seek(0)

    filename = (
        f"Kas_WhatsApp_"
        f"{sekarang().strftime('%Y%m%d_%H%M%S')}.xlsx"
    )

    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@app.route("/fitur")
def fitur():

    commands = [

        {
            "icon": "💰",
            "title": "Pemasukan",
            "command": "masuk",
            "example": "masuk 500000 gaji",
            "desc": "Mencatat pemasukan secara otomatis."
        },

        {
            "icon": "💸",
            "title": "Pengeluaran",
            "command": "keluar",
            "example": "keluar 25000 makan",
            "desc": "Mencatat pengeluaran beserta kategori otomatis."
        },

        {
            "icon": "💳",
            "title": "Saldo",
            "command": "saldo",
            "example": "saldo",
            "desc": "Menampilkan saldo terkini, total pemasukan, pengeluaran, dan link dashboard."
        },

        {
            "icon": "📊",
            "title": "Ringkasan Hari Ini",
            "command": "hariini",
            "example": "hariini",
            "desc": "Melihat total transaksi hari ini."
        },

        {
            "icon": "🎯",
            "title": "Budget Bulanan",
            "command": "budget",
            "example": "budget makanan 1500000",
            "desc": "Membuat dan memonitor budget tiap kategori."
        },

        {
            "icon": "🤖",
            "title": "AI Insight",
            "command": "insight",
            "example": "insight",
            "desc": "AI menganalisis pola pengeluaran dan memberikan rekomendasi."
        },

        {
            "icon": "🔔",
            "title": "Reminder Tagihan",
            "command": "reminder",
            "example": "reminder listrik 20 500000",
            "desc": "Mengingatkan tagihan bulanan."
        },

        {
            "icon": "🗑️",
            "title": "Hapus Reminder",
            "command": "hapusreminder",
            "example": "hapusreminder listrik",
            "desc": "Menghapus reminder yang sudah tidak digunakan."
        }

    ]

    return render_template(
        "fitur.html",
        commands=commands
    )

# =====================================
# LAPORAN HARIAN FINANCE
# =====================================

def generate_laporan_harian(nomor_wa):

    hari_ini = date.today()

    awal = datetime.combine(
        hari_ini,
        dt_time.min
    )

    akhir = datetime.combine(
        hari_ini,
        dt_time.max
    )

    # =========================
    # TRANSAKSI HARI INI
    # =========================

    transaksi = Transaksi.query.filter(
        Transaksi.nomor_wa == nomor_wa,
        Transaksi.tanggal.between(
            awal,
            akhir
        )
    ).all()

    total_masuk = 0
    total_keluar = 0

    detail_masuk = ""
    detail_keluar = ""

    for t in transaksi:

        if t.tipe == "MASUK":

            total_masuk += t.nominal

            detail_masuk += (
                f"\n• {t.keterangan}"
                f"\n  Rp {t.nominal:,.0f}"
            )

        else:

            total_keluar += t.nominal

            detail_keluar += (
                f"\n• {t.keterangan}"
                f"\n  Rp {t.nominal:,.0f}"
            )

    # =========================
    # HUTANG HARI INI
    # =========================

    hutang = HutangPiutang.query.filter(
        HutangPiutang.nomor_wa == nomor_wa,
        HutangPiutang.tipe == "HUTANG",
        HutangPiutang.tanggal.between(
            awal,
            akhir
        )
    ).all()

    total_hutang = sum(
        h.nominal for h in hutang
    )

    detail_hutang = ""

    for h in hutang:

        detail_hutang += (
            f"\n• {h.nama}"
            f"\n  Rp {h.nominal:,.0f}"
        )

    # =========================
    # PIUTANG HARI INI
    # =========================

    piutang = HutangPiutang.query.filter(
        HutangPiutang.nomor_wa == nomor_wa,
        HutangPiutang.tipe == "PIUTANG",
        HutangPiutang.tanggal.between(
            awal,
            akhir
        )
    ).all()

    total_piutang = sum(
        p.nominal for p in piutang
    )

    detail_piutang = ""

    for p in piutang:

        detail_piutang += (
            f"\n• {p.nama}"
            f"\n  Rp {p.nominal:,.0f}"
        )

    saldo = total_masuk - total_keluar

    # =========================
    # SALDO KESELURUHAN
    # =========================

    total_semua_masuk = db.session.query(
        db.func.coalesce(
            db.func.sum(Transaksi.nominal),
            0
        )
    ).filter(
        Transaksi.nomor_wa == nomor_wa,
        Transaksi.tipe == "MASUK"
    ).scalar()

    total_semua_keluar = db.session.query(
        db.func.coalesce(
            db.func.sum(Transaksi.nominal),
            0
        )
    ).filter(
        Transaksi.nomor_wa == nomor_wa,
        Transaksi.tipe == "KELUAR"
    ).scalar()

    saldo_total = total_semua_masuk - total_semua_keluar

    Link = generate_dashboard_link(nomor_wa)

    laporan = f"""💚 *Hai! Ini ringkasan keuanganmu hari ini*

📅 {hari_ini.strftime("%d %B %Y")}

Hari ini, berikut gambaran keuanganmu:

━━━━━━━━━━━━━━━━━━

📊 *Ringkasan Hari Ini*

💰 Uang masuk
*Rp {total_masuk:,.0f}*

💸 Uang keluar
*Rp {total_keluar:,.0f}*

🤝 Hutang baru
*Rp {total_hutang:,.0f}*

📥 Piutang baru
*Rp {total_piutang:,.0f}*

━━━━━━━━━━━━━━━━━━

💳 *Posisi Saldo*

Saldo dari transaksi hari ini:
*Rp {saldo:,.0f}*

Saldo keseluruhan:
*Rp {saldo_total:,.0f}*

━━━━━━━━━━━━━━━━━━

🟢 *Uang Masuk Hari Ini*
{detail_masuk or "Belum ada pemasukan hari ini."}

🔴 *Uang Keluar Hari Ini*
{detail_keluar or "Belum ada pengeluaran hari ini."}

🟠 *Hutang Hari Ini*
{detail_hutang or "Tidak ada hutang baru hari ini."}

🔵 *Piutang Hari Ini*
{detail_piutang or "Tidak ada piutang baru hari ini."}

━━━━━━━━━━━━━━━━━━

📱 Mau melihat catatan keuanganmu lebih lengkap?

🌐 {Link}

_Link aktif selama 30 menit._

Semoga keuanganmu hari ini tetap terkontrol dan berjalan sesuai rencana. 😊

*ChatSaku • Teman mengatur keuanganmu*
"""
    return laporan

def generate_laporan_bulanan(nomor_wa, periode):

    summary = MonthlySummary.query.filter_by(
        nomor_wa=nomor_wa,
        periode=periode
    ).first()

    if not summary:
        return None

    transaksi = Transaksi.query.filter(
        Transaksi.nomor_wa == nomor_wa,
        func.to_char(
            Transaksi.tanggal,
            "YYYY-MM"
        ) == periode,
        Transaksi.tipe == "KELUAR"
    ).all()

    kategori = {}

    for trx in transaksi:
        key = trx.kategori or "-"
        kategori[key] = kategori.get(key, 0) + trx.nominal

    kategori_terbesar = "-"

    nominal_terbesar = 0

    if kategori:
        kategori_terbesar = max(
            kategori,
            key=kategori.get
        )
        nominal_terbesar = kategori[kategori_terbesar]

    return f"""
📊 *Laporan Bulanan ChatSaku*

📅 Periode : {periode}

═══════════════════

💵 Saldo Awal
Rp {summary.saldo_awal:,.0f}

📈 Total Masuk
Rp {summary.total_masuk:,.0f}

📉 Total Keluar
Rp {summary.total_keluar:,.0f}

💰 Saving
Rp {summary.saving:,.0f}

🏦 Saldo Akhir
Rp {summary.saldo_akhir:,.0f}

━━━━━━━━━━━━━━━━━━━

🏆 Pengeluaran Terbesar

{kategori_terbesar}
Rp {nominal_terbesar:,.0f}

━━━━━━━━━━━━━━━━━━━

Jumlah Transaksi
{summary.total_transaksi}

Terima kasih telah menggunakan ChatSaku 😊
"""

def kirim_laporan_bulanan(periode):

    users = User.query.filter_by(
        aktif=True
    ).all()

    for user in users:

        try:

            laporan = generate_laporan_bulanan(
                user.nomor_wa,
                periode
            )

            if laporan:

                kirim_wa(
                    user.nomor_wa,
                    laporan
                )

        except Exception as e:

            print(e)

def scheduler_closing():

    with app.app_context():

        periode = previous_period()

        if not validate_period(periode):

            print("Periode tidak valid")

            return

        hasil = closing_month(periode)

        print(hasil)
def kirim_laporan_harian():

    print("=" * 60)
    print("Scheduler dijalankan :", now_jakarta())
    print("=" * 60)

    with app.app_context():

        print("🚀 kirim_laporan_harian dijalankan")

        users = User.query.all()

        print("Jumlah user:", len(users))

        for user in users:

            print(
                "Proses user:",
                user.nomor_wa,
                "paket:",
                user.paket
            )

            try:

                if not has_feature(user.nomor_wa, "laporan_harian"):
                    print("Lewat:", user.nomor_wa)
                    continue

                laporan = generate_laporan_harian(user.nomor_wa)

                kirim_wa(
                    user.nomor_wa,
                    laporan
                )

                print("✅ Berhasil:", user.nomor_wa)

            except Exception as e:

                print("❌ Error:", e)

def previous_period():

    now = now_jakarta()

    if now.month == 1:
        return f"{now.year-1}-12"

    return f"{now.year}-{now.month-1:02d}"

def copy_budget_next_month(nomor_wa, periode):

    tujuan = next_period(periode)

    budget_list = Budget.query.filter_by(
        nomor_wa=nomor_wa,
        periode=periode,
        auto_repeat=True
    ).all()

    for item in budget_list:

        sudah = Budget.query.filter_by(
            nomor_wa=nomor_wa,
            periode=tujuan,
            kategori=item.kategori
        ).first()

        if sudah:
            continue

        db.session.add(

            Budget(
                nomor_wa=item.nomor_wa,
                kategori=item.kategori,
                nominal=item.nominal,
                periode=tujuan,
                auto_repeat=True
            )

        )

def closing_user(user, periode):

    tahun, bulan = map(int, periode.split("-"))

    awal = datetime(
        tahun,
        bulan,
        1,
        0,
        0,
        0
    )

    akhir = datetime(
        tahun,
        bulan,
        monthrange(tahun, bulan)[1],
        23,
        59,
        59
    )

    saldo_awal = calculate_opening_balance(
        user.nomor_wa,
        periode
    )

    # ==============================
    # TOTAL PEMASUKAN
    # ==============================

    masuk = (
        db.session.query(
            func.coalesce(
                func.sum(Transaksi.nominal),
                0
            )
        )
        .filter(
            Transaksi.nomor_wa == user.nomor_wa,
            Transaksi.tipe == "MASUK",
            Transaksi.tanggal >= awal,
            Transaksi.tanggal <= akhir
        )
        .scalar()
    )

    # ==============================
    # TOTAL PENGELUARAN
    # ==============================

    keluar = (
        db.session.query(
            func.coalesce(
                func.sum(Transaksi.nominal),
                0
            )
        )
        .filter(
            Transaksi.nomor_wa == user.nomor_wa,
            Transaksi.tipe == "KELUAR",
            Transaksi.tanggal >= awal,
            Transaksi.tanggal <= akhir
        )
        .scalar()
    )

    # ==============================
    # JUMLAH TRANSAKSI
    # ==============================

    jumlah = (
        db.session.query(
            func.count(Transaksi.id)
        )
        .filter(
            Transaksi.nomor_wa == user.nomor_wa,
            Transaksi.tanggal >= awal,
            Transaksi.tanggal <= akhir
        )
        .scalar()
    )

    saving = masuk - keluar

    saldo_akhir = saldo_awal + saving

    # ==============================
    # INSERT / UPDATE SUMMARY
    # ==============================

    summary = MonthlySummary.query.filter_by(
        nomor_wa=user.nomor_wa,
        periode=periode
    ).first()

    if summary is None:

        summary = MonthlySummary(
            nomor_wa=user.nomor_wa,
            periode=periode
        )

        db.session.add(summary)

    summary.saldo_awal = saldo_awal
    summary.total_masuk = masuk
    summary.total_keluar = keluar
    summary.saving = saving
    summary.saldo_akhir = saldo_akhir
    summary.total_transaksi = jumlah
    summary.status = "CLOSED"
    summary.closed_at = now_jakarta()

    copy_budget_next_month(
        user.nomor_wa,
        periode
    )

    return True

def closing_month(periode=None):

    if periode is None:
        periode = previous_period()

    # ==========================
    # VALIDASI PERIODE
    # ==========================

    if not validate_period(periode):

        return {
            "status": False,
            "message": "Periode tidak valid"
        }

    # ==========================
    # LOCK
    # ==========================

    if not acquire_lock():

        return {
            "status": False,
            "message": "Closing sedang berjalan."
        }

    berhasil = 0
    gagal = 0

    try:

        users = User.query.filter_by(
            aktif=True
        ).all()

        print("=" * 60)
        print("MONTHLY CLOSING")
        print("Periode :", periode)
        print("Jumlah User :", len(users))
        print("=" * 60)

        for user in users:

            try:

                closing_user(
                    user,
                    periode
                )

                berhasil += 1

                print(
                    "SUCCESS :",
                    user.nomor_wa
                )

            except Exception as e:

                gagal += 1

                db.session.rollback()

                import traceback

                traceback.print_exc()

                print(
                    "FAILED :",
                    user.nomor_wa,
                    str(e)
                )

        db.session.commit()

        print("=" * 60)
        print("Closing selesai")
        print("Success :", berhasil)
        print("Failed  :", gagal)
        print("=" * 60)

        return {

            "status": True,

            "periode": periode,

            "success": berhasil,

            "failed": gagal

        }

    except Exception as e:

        db.session.rollback()

        import traceback

        traceback.print_exc()

        print("FATAL ERROR :", str(e))

        return {

            "status": False,

            "message": str(e)

        }

    finally:

        release_lock()

def recalculate_summary(

    nomor_wa,

    periode

):

    closing_user(

        User.query.filter_by(

            nomor_wa=nomor_wa

        ).first(),

        periode

    )

def validate_period(periode):
    """
    Validasi format periode YYYY-MM
    Contoh valid:
        2026-01
        2026-12

    Contoh tidak valid:
        2026
        26-01
        2026-13
        2026-00
        abc
    """

    if not periode:
        return False

    periode = periode.strip()

    # Format harus YYYY-MM
    if not re.match(r"^\d{4}-\d{2}$", periode):
        return False

    try:

        tahun, bulan = map(int, periode.split("-"))

        if tahun < 2020:
            return False

        if bulan < 1 or bulan > 12:
            return False

        datetime(tahun, bulan, 1)

        return True

    except Exception:

        return False

@app.route("/admin/closing-month")
def admin_closing():

    periode = request.args.get("periode")

    if not periode:

        periode = previous_period()

    if not validate_period(periode):

        return jsonify({

            "status": False,

            "message": "Format periode harus YYYY-MM"

        }), 400

    hasil = closing_month(periode)

    return jsonify(hasil)

@app.route("/admin/monthly-summary")
def monthly_summary():

    data = MonthlySummary.query.order_by(

        MonthlySummary.periode.desc(),

        MonthlySummary.nomor_wa

    ).all()

    rows = []

    for item in data:

        rows.append({

            "periode": item.periode,

            "nomor": item.nomor_wa,

            "saldo_awal": item.saldo_awal,

            "masuk": item.total_masuk,

            "keluar": item.total_keluar,

            "saving": item.saving,

            "saldo_akhir": item.saldo_akhir,

            "status": item.status

        })

    return jsonify(rows)

@app.route("/admin/reclosing/<periode>")
def admin_reclosing(periode):

    if not validate_period(periode):

        return jsonify({

            "status":False,

            "message":"Periode salah"

        }),400

    cascade_reclosing(
        periode
    )

    return jsonify({

        "status":True,

        "message":"Cascade selesai"

    })

def next_period(periode):

    tahun, bulan = map(int, periode.split("-"))

    if bulan == 12:
        return f"{tahun+1}-01"

    return f"{tahun}-{bulan+1:02d}"

@app.route("/admin/test-closing")
def test_closing():

    with app.app_context():

        hasil = closing_month()

        kirim_laporan_bulanan(
            hasil["periode"]
        )

    return jsonify(hasil)

@app.route("/admin/test-laporan-bulanan")
def test_laporan():

    nomor = request.args.get("nomor")

    periode = request.args.get("periode")

    laporan = generate_laporan_bulanan(
        nomor,
        periode
    )

    kirim_wa(
        nomor,
        laporan
    )

    return jsonify({
        "status":True
    })

@app.route("/admin/verify-summary")
def admin_verify():

    users = User.query.filter_by(
        aktif=True
    ).all()

    for user in users:

        verify_monthly_summary(
            user.nomor_wa
        )

    return jsonify({

        "status":True,

        "message":"Verification selesai"

    })


from datetime import datetime
from zoneinfo import ZoneInfo

def kirim_reminder_harian():

    with app.app_context():

        print("=" * 70)
        print("🔔 KIRIM REMINDER HARIAN CHATSAKU")
        print("=" * 70)

        try:

            sekarang = datetime.now(
                ZoneInfo("Asia/Jakarta")
            )

            hari_ini = sekarang.day

            print("Tanggal hari ini :", hari_ini)

            # ======================================
            # AMBIL REMINDER HARI INI
            # ======================================

            reminders = Reminder.query.filter(
                Reminder.aktif.is_(True),
                Reminder.tanggal == hari_ini
            ).all()

            print(
                "Total reminder :",
                len(reminders)
            )

            if not reminders:

                print(
                    "📭 Tidak ada reminder hari ini."
                )

                return

            # ======================================
            # KELOMPOKKAN REMINDER PER NOMOR WA
            # ======================================

            reminder_users = {}

            for reminder in reminders:

                nomor_wa = normalize_wa(
                    reminder.nomor_wa
                )

                if nomor_wa not in reminder_users:
                    reminder_users[nomor_wa] = []

                reminder_users[nomor_wa].append(
                    reminder
                )

            # ======================================
            # PROSES PER USER
            # ======================================

            for nomor_wa, user_reminders in reminder_users.items():

                try:

                    print("-" * 60)

                    print(
                        "Nomor :",
                        nomor_wa
                    )

                    # ==================================
                    # CARI USER
                    # ==================================

                    user = User.query.filter_by(
                        nomor_wa=nomor_wa
                    ).first()

                    if not user:

                        print(
                            f"⚠️ User tidak ditemukan : "
                            f"{nomor_wa}"
                        )

                        continue

                    # ==================================
                    # HANYA PREMIUM
                    # ==================================

                    if not has_feature(user.nomor_wa, "reminder"):
                        print("Lewat:", user.nomor_wa)
                        continue

                    # ==================================
                    # CEK AKUN AKTIF
                    # ==================================

                    if not user.aktif:

                        print(
                            f"⏭️ Skip akun nonaktif : "
                            f"{nomor_wa}"
                        )

                        continue

                    # ==================================
                    # CEK LANGGANAN
                    # ==================================

                    if (
                        user.akhir_langganan
                        and sekarang.date()
                        > user.akhir_langganan
                    ):

                        print(
                            f"⏭️ Skip langganan expired : "
                            f"{nomor_wa}"
                        )

                        continue

                    # ==================================
                    # BUAT PESAN
                    # ==================================

                    pesan = f"""🔔 *Reminder ChatSaku*

Halo *{user.nama}* 👋

Hari ini ada beberapa pengingat:

"""

                    total = 0

                    for index, reminder in enumerate(
                        user_reminders,
                        start=1
                    ):

                        nominal = int(
                            reminder.nominal or 0
                        )

                        total += nominal

                        pesan += (
                            f"{index}️⃣ "
                            f"📌 *{reminder.nama}*\n"
                            f"   💰 Rp {nominal:,.0f}\n\n"
                        )

                    pesan += (
                        "━━━━━━━━━━━━━━━━━━\n"
                        f"💰 *Total: Rp {total:,.0f}*\n"
                        "━━━━━━━━━━━━━━━━━━\n\n"
                        "Jangan sampai ada yang terlewat ya 😊\n\n"
                        "💚 _ChatSaku Finance Assistant_"
                    )

                    # ==================================
                    # KIRIM HANYA KE PEMILIK
                    # ==================================

                    kirim_wa(
                        nomor_wa,
                        pesan
                    )

                    print(
                        f"✅ {len(user_reminders)} "
                        f"reminder terkirim"
                    )

                    print(
                        f"   Nomor : {nomor_wa}"
                    )

                    print(
                        f"   User  : {user.nama}"
                    )

                    print(
                        f"   Paket : {user.paket}"
                    )

                except Exception as e:

                    print(
                        f"❌ Gagal memproses "
                        f"{nomor_wa}: {e}"
                    )

            print("=" * 70)
            print("✅ SELESAI KIRIM REMINDER")
            print("=" * 70)

        except Exception as e:

            import traceback

            print(
                "❌ ERROR REMINDER:",
                e
            )

            traceback.print_exc()

def scheduler_verify():

    users = User.query.filter_by(
        aktif=True
    ).all()

    for user in users:

        verify_monthly_summary(
            user.nomor_wa
        )

scheduler = BackgroundScheduler(
    timezone=ZoneInfo("Asia/Jakarta")
)

scheduler.add_job(
    func=kirim_reminder_harian,
    trigger="cron",
    hour=7,
    minute=00,
    id="reminder_harian",
    replace_existing=True
)

scheduler.add_job(
    func=kirim_laporan_harian,
    trigger="cron",
    hour=18,
    minute=00,
    id="laporan_harian",
    replace_existing=True
)

scheduler.add_job(
    func=scheduler_closing,
    trigger="cron",
    day=1,
    hour=0,
    minute=10,
    id="closing_month",
    replace_existing=True
)

scheduler.add_job(

    func=scheduler_verify,
    trigger="cron",
    hour=1,
    minute=0,
    id="verify_summary",
    replace_existing=True

)

scheduler.start()

atexit.register(lambda: scheduler.shutdown())
# schedule.every().day.at(
#     "12:20"
# ).do(
#     kirim_laporan_harian
# )
# # schedule.every(1).minutes.do(kirim_laporan_harian)

# print(schedule.jobs)

# threading.Thread(
#     target=scheduler_loop,
#     daemon=True
# ).start()

@app.route("/promo")
def promo():

    hari_ini = sekarang().date()

    promos = PromoPaket.query.filter(
        PromoPaket.aktif == True,
        PromoPaket.tanggal_mulai <= hari_ini,
        PromoPaket.tanggal_selesai >= hari_ini
    ).order_by(PromoPaket.nama).all()

    hasil = {}

    for p in promos:

        if p.nama not in hasil:
            hasil[p.nama] = {
                "nama": p.nama,
                "mulai": p.tanggal_mulai.strftime("%d %b %Y"),
                "selesai": p.tanggal_selesai.strftime("%d %b %Y"),
                "paket": {}
            }

        hasil[p.nama]["paket"][p.paket] = p.harga_promo

    return jsonify(list(hasil.values()))

import os
import uuid
import midtransclient

from datetime import datetime
from flask import request, jsonify

snap = midtransclient.Snap(
    is_production=True,
    server_key=os.getenv("MIDTRANS_SERVER_KEY")
)

print("=" * 50)
print("PRODUCTION :", snap.api_config.is_production)
print("SERVER KEY :", snap.api_config.server_key[:20])
print("=" * 50)

@app.route("/api/payment/create", methods=["POST"])
@jwt_required()
def create_payment():

    try:

        data = request.get_json()

        paket = data.get("paket", "").upper()

        user_id = get_jwt_identity()

        login_user = UserLogin.query.get(user_id)

        if not login_user:
            return jsonify({
                "success": False,
                "message": "User login tidak ditemukan."
            }),404

        HARGA_PAKET = {
            "STARTER": 19000,
            "PRO": 49000,
            "PREMIUM": 75000
        }

        if paket not in HARGA_PAKET:
            return jsonify({
                "success": False,
                "message": "Paket tidak ditemukan."
            }), 400

        # =====================================
        # Harga normal
        # =====================================

        harga_normal = HARGA_PAKET[paket]

        harga_bayar = harga_normal

        promo_id = None

        hari_ini = sekarang().date()

        promo = PromoPaket.query.filter(
            PromoPaket.paket == paket,
            PromoPaket.aktif == True,
            PromoPaket.tanggal_mulai <= hari_ini,
            PromoPaket.tanggal_selesai >= hari_ini
        ).first()

        if promo:

            harga_bayar = promo.harga_promo

            promo_id = promo.id

        order_id = f"CHATSAKU-{uuid.uuid4().hex[:12]}"

        parameter = {

            "transaction_details": {

                "order_id": order_id,

                "gross_amount": int(harga_bayar)

            },

            "credit_card": {

                "secure": True

            },

            "customer_details": {

                "first_name": login_user.nama,

                "phone": login_user.nomor_whatsapp

            },

            "item_details": [

                {

                    "id": paket,

                    "price": int(harga_bayar),

                    "quantity": 1,

                    "name": f"ChatSaku {paket}"

                }

            ]

        }

        transaction = snap.create_transaction(parameter)

        payment = Payment(

            user_login_id=login_user.id,

            promo_id=promo_id,

            order_id=order_id,

            paket=paket,

            harga_normal=harga_normal,

            harga_bayar=harga_bayar,

            status="PENDING",

            midtrans_token=transaction["token"],

            midtrans_response=json.dumps(transaction)

        )

        db.session.add(payment)

        db.session.commit()
        print("=" * 50)
        print("ORDER CREATED :", order_id)
        print("USER LOGIN :", login_user.id)
        print("PAKET :", paket)
        print("HARGA NORMAL :", harga_normal)
        print("HARGA BAYAR :", harga_bayar)

        if promo:
            print("PROMO :", promo.nama)
        else:
            print("PROMO : Tidak ada")

        return jsonify({
            "success": True,
            "token": transaction["token"],
            "redirect_url": transaction["redirect_url"],
            "order_id": order_id,
            "harga_normal": harga_normal,
            "harga_bayar": harga_bayar,
            "promo": promo.nama if promo else None
        })

    except Exception as e:

        import traceback
        traceback.print_exc()

        return jsonify({

            "success": False,

            "error": str(e)

        }), 500


import hashlib
import json
import os

@app.route("/midtrans/notification", methods=["POST"])
def notification():

    try:

        notif = request.get_json()

        if not notif:
            return "Invalid notification", 400

        print("=" * 60)
        print("MIDTRANS NOTIFICATION")
        print("ORDER :", notif.get("order_id"))
        print("STATUS:", notif.get("transaction_status"))
        print("=" * 60)

        order_id = notif.get("order_id")
        status = notif.get("transaction_status")
        status_code = notif.get("status_code")
        gross_amount = notif.get("gross_amount")
        signature_key = notif.get("signature_key")

        # =====================================
        # VALIDASI DATA WAJIB
        # =====================================

        if not all([
            order_id,
            status,
            status_code,
            gross_amount,
            signature_key
        ]):
            print("❌ Notification tidak lengkap")
            return "Invalid notification", 400

        # =====================================
        # VERIFIKASI SIGNATURE MIDTRANS
        # =====================================

        server_key = os.getenv("MIDTRANS_SERVER_KEY")

        raw_signature = (
            str(order_id)
            + str(status_code)
            + str(gross_amount)
            + str(server_key)
        )

        expected_signature = hashlib.sha512(
            raw_signature.encode("utf-8")
        ).hexdigest()

        if signature_key != expected_signature:

            print("❌ INVALID MIDTRANS SIGNATURE")
            print("ORDER :", order_id)

            return "Invalid signature", 403

        print("✅ MIDTRANS SIGNATURE VALID")

        # =====================================
        # CARI PAYMENT
        # =====================================

        payment = Payment.query.filter_by(
            order_id=order_id
        ).first()

        if payment is None:

            print("❌ Payment tidak ditemukan :", order_id)

            return "Not Found", 404

        # =====================================
        # CEGAH DOUBLE PROCESSING
        # =====================================

        if payment.status == "PAID":

            print("ℹ️ Payment sudah PAID :", order_id)

            return "OK", 200

        # =====================================
        # STATUS BELUM BERHASIL
        # =====================================

        if status == "pending":

            payment.status = "PENDING"

            db.session.commit()

            return "OK", 200

        if status == "expire":

            payment.status = "EXPIRED"

            db.session.commit()

            return "OK", 200

        if status == "cancel":

            payment.status = "CANCELLED"

            db.session.commit()

            return "OK", 200

        if status == "deny":

            payment.status = "DENIED"

            db.session.commit()

            return "OK", 200

        if status not in ["settlement", "capture"]:

            payment.status = status.upper()

            db.session.commit()

            return "OK", 200

        # =====================================
        # PEMBAYARAN BERHASIL
        # =====================================

        payment.status = "PAID"
        payment.paid_at = sekarang()

        login_user = UserLogin.query.get(
            payment.user_login_id
        )

        if not login_user:

            print("❌ UserLogin tidak ditemukan")

            db.session.commit()

            return "OK", 200


        # =====================================
        # NORMALIZE NOMOR WHATSAPP
        # =====================================

        nomor_wa = normalize_wa(
            login_user.nomor_whatsapp
        )

        print("NORMALIZED WA :", nomor_wa)


        # =====================================
        # CARI USER YANG SUDAH ADA
        # =====================================

        user = User.query.filter_by(
            nomor_wa=nomor_wa
        ).first()


        # =====================================
        # USER SUDAH ADA
        # =====================================

        if user:

            print("♻️ USER SUDAH ADA")
            print("USER ID :", user.id)
            print("NAMA LAMA :", user.nama)
            print("PAKET LAMA :", user.paket)
            print("EXPIRED LAMA :", user.akhir_langganan)

            # ---------------------------------
            # UPDATE DATA USER
            # ---------------------------------

            user.nama = login_user.nama
            user.paket = payment.paket
            user.aktif = True


            # ---------------------------------
            # PERPANJANG LANGGANAN
            # ---------------------------------

            if (
                user.akhir_langganan
                and user.akhir_langganan >= sekarang().date()
            ):

                # Masih aktif → tambah 30 hari

                user.akhir_langganan += timedelta(days=30)

                print(
                    "➕ LANGGANAN DIPERPANJANG 30 HARI"
                )

            else:

                # Sudah expired → mulai 30 hari dari hari ini

                user.akhir_langganan = (
                    sekarang().date()
                    + timedelta(days=30)
                )

                print(
                    "🔄 LANGGANAN DIMULAI ULANG 30 HARI"
                )


        # =====================================
        # USER BELUM ADA
        # =====================================

        else:

            print("🆕 USER BELUM ADA")
            print("MEMBUAT USER BARU")


            user = User(
                nama=login_user.nama,
                nomor_wa=nomor_wa,
                paket=payment.paket,
                aktif=True,
                akhir_langganan=(
                    sekarang().date()
                    + timedelta(days=30)
                )
            )

            db.session.add(user)


        # =====================================
        # SIMPAN DATABASE
        # =====================================

        db.session.commit()

        print("=" * 50)
        print("✅ USER BERHASIL DIUPDATE / DIBUAT")
        print("USER ID :", user.id)
        print("NAMA :", user.nama)
        print("WA :", user.nomor_wa)
        print("PAKET :", user.paket)
        print("AKTIF :", user.aktif)
        print("BERLAKU SAMPAI :", user.akhir_langganan)
        print("=" * 50)

        # =====================================
        # WA ADMIN
        # =====================================

        try:

            pesan_admin = f"""🎉 *Pembayaran ChatSaku Berhasil*

👤 Nama : {login_user.nama}
📱 WhatsApp : {nomor_wa}
📦 Paket : {payment.paket}
💰 Nominal : Rp {payment.harga_bayar:,}
🧾 Order ID : {payment.order_id}

Status : ✅ PAID
"""

            kirim_wa(
                ADMIN_NUMBER,
                pesan_admin
            )

        except Exception as e:

            print("❌ WA ADMIN ERROR:", e)

        # =====================================
        # WA CUSTOMER
        # =====================================

        try:

            pesan_user = f"""🎉 *Pembayaran Berhasil*

Halo *{login_user.nama}* 👋

Terima kasih telah berlangganan ChatSaku.

📦 Paket : *{payment.paket}*

📅 Berlaku sampai :
*{user.akhir_langganan.strftime('%d-%m-%Y')}*

Silakan mulai menggunakan seluruh fitur paket Anda.

Terima kasih 🙏
"""

            kirim_wa(
                nomor_wa,
                pesan_user
            )

        except Exception as e:

            print("❌ WA USER ERROR:", e)

        print("✅ PAYMENT UPDATED :", order_id)

        return "OK", 200

    except Exception as e:

        import traceback

        traceback.print_exc()

        return "Internal Server Error", 500

def list_period_between(start_period, end_period):

    hasil = []

    tahun, bulan = map(int, start_period.split("-"))
    end_tahun, end_bulan = map(int, end_period.split("-"))

    while True:

        hasil.append(f"{tahun}-{bulan:02d}")

        if tahun == end_tahun and bulan == end_bulan:
            break

        bulan += 1

        if bulan == 13:
            bulan = 1
            tahun += 1

    return hasil

def last_summary_period():

    last = db.session.query(

        func.max(
            MonthlySummary.periode
        )

    ).scalar()

    return last

def cascade_reclosing(start_period):

    akhir = last_summary_period()

    if akhir is None:

        return

    daftar = list_period_between(
        start_period,
        akhir
    )

    print("="*60)
    print("CASCADE RECLOSING")
    print(daftar)
    print("="*60)

    for periode in daftar:

        print("RECALCULATE :", periode)

        closing_month(
            periode
        )

@app.route("/payment/pending")
@jwt_required()
def pending_payment():

    user_id = get_jwt_identity()

    payment = Payment.query.filter_by(
        user_login_id=user_id,
        status="PENDING"
    ).order_by(
        Payment.created_at.desc()
    ).first()

    if not payment:
        return jsonify({
            "success": True,
            "payment": None
        })

    return jsonify({
        "success": True,
        "payment": {
            "order_id": payment.order_id,
            "paket": payment.paket,
            "harga": payment.harga_bayar,
            "status": payment.status,
            "created_at": payment.created_at.strftime("%d-%m-%Y %H:%M")
        }
    })

@app.route("/api/payment/history")
@jwt_required()
def payment_history():

    user_id = get_jwt_identity()

    payments = Payment.query.filter_by(
        user_login_id=user_id
    ).order_by(
        Payment.created_at.desc()
    ).all()

    return jsonify({
        "success": True,
        "payments": [
            {
                "order_id": p.order_id,
                "paket": p.paket,
                "harga": p.harga_bayar,
                "status": p.status,
                "created_at": p.created_at.strftime("%d-%m-%Y %H:%M")
            }
            for p in payments
        ]
    })


import requests


BABLAST_TOKEN = "9fYxtSorLpNAf89dbKjk7o5l0LtAqm7Q5PABLTNYSVWWLMOfYAg0pxim8z4deuVo2OMOlMdzIrfE0q3BBvQpHr9EIjQn0x5c2lOR"


def kirim_template_waba(phone, nama, invoice):

    url = "https://api.bablast.id/waba/send-template"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {BABLAST_TOKEN}"
    }


    payload = {

        "phone": phone,

        "template_name": "saldo",

        "language": "id",

        "parameters": [

            {
                "type": "text",
                "text": nama
            },

            {
                "type": "text",
                "text": invoice
            }

        ]

    }


    response = requests.post(
        url,
        headers=headers,
        json=payload
    )


    return response.json()

# =========================
# DASHBOARD
# =========================

def get_logged_in_user():
    user_id = get_jwt_identity()

    if not user_id:
        return None

    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None

    return UserLogin.query.filter_by(
        id=user_id
    ).first()

from datetime import datetime
from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import func, or_

from models import db, UserLogin, Transaksi


# =========================================================
# GET USER LOGIN DARI JWT
# =========================================================

def get_logged_in_user():

    user_id = get_jwt_identity()

    if not user_id:
        return None

    try:
        user_id = int(user_id)

    except (TypeError, ValueError):
        return None

    return UserLogin.query.filter_by(
        id=user_id
    ).first()


# =========================================================
# SUMMARY TRANSAKSI
# =========================================================

@app.route("/api/transaksi/summary", methods=["GET"])
@jwt_required()
def transaksi_summary():

    # =====================================================
    # USER LOGIN
    # =====================================================

    user = get_logged_in_user()

    if not user:
        return jsonify({
            "success": False,
            "message": "User tidak ditemukan."
        }), 401

    nomor_wa = user.nomor_whatsapp

    # =====================================================
    # VERIFY MONTHLY SUMMARY
    # =====================================================

    verify_monthly_summary(nomor_wa)

    # =====================================================
    # SEMUA TRANSAKSI USER
    #
    # PENTING:
    # Tidak ada filter bulan di sini.
    # Saldo = seluruh riwayat transaksi.
    # =====================================================

    query = Transaksi.query.filter(
        Transaksi.nomor_wa == nomor_wa
    )

    all_data = query.order_by(
        Transaksi.tanggal.desc()
    ).all()

    # =====================================================
    # TOTAL PEMASUKAN - SEMUA TRANSAKSI
    # =====================================================

    total_masuk = sum(
        x.nominal or 0
        for x in all_data
        if x.tipe == "MASUK"
    )

    # =====================================================
    # TOTAL PENGELUARAN - SEMUA TRANSAKSI
    # =====================================================

    total_keluar = sum(
        x.nominal or 0
        for x in all_data
        if x.tipe == "KELUAR"
    )

    # =====================================================
    # SALDO - SEMUA TRANSAKSI
    # =====================================================

    saldo = total_masuk - total_keluar

    # =====================================================
    # SAVING
    # =====================================================

    saving = saldo

    saving_persen = 0

    if total_masuk > 0:

        saving_persen = round(
            (saving / total_masuk) * 100,
            1
        )

    # =====================================================
    # JUMLAH TRANSAKSI
    # =====================================================

    jumlah_transaksi = len(
        all_data
    )

    # =====================================================
    # TRANSAKSI TERBARU
    # =====================================================

    transaksi_terbaru = []

    for trx in all_data[:10]:

        transaksi_terbaru.append({

            "id": trx.id,

            "jenis": (
                trx.tipe.lower()
                if trx.tipe
                else ""
            ),

            "tipe": trx.tipe,

            "keterangan": (
                trx.keterangan
                or "-"
            ),

            "kategori": (
                trx.kategori
                or "-"
            ),

            "tanggal": (
                trx.tanggal.strftime("%d %b")
                if trx.tanggal
                else "-"
            ),

            "jam": (
                trx.tanggal.strftime("%H:%M")
                if trx.tanggal
                else "-"
            ),

            "tanggal_full": (
                trx.tanggal.strftime(
                    "%d/%m/%Y %H:%M"
                )
                if trx.tanggal
                else "-"
            ),

            "nominal": (
                trx.nominal or 0
            ),

            "saldo": saldo

        })

    # =====================================================
    # TRANSAKSI HARI INI
    # =====================================================

    today = sekarang().date()

    trx_today = [

        x for x in all_data

        if x.tanggal
        and x.tanggal.date() == today

    ]

    transaksi_hari_ini = len(
        trx_today
    )

    masuk_hari_ini = sum(

        x.nominal or 0

        for x in trx_today

        if x.tipe == "MASUK"

    )

    keluar_hari_ini = sum(

        x.nominal or 0

        for x in trx_today

        if x.tipe == "KELUAR"

    )

    saving_hari_ini = (
        masuk_hari_ini
        - keluar_hari_ini
    )

    # =====================================================
    # BUDGET BULAN INI
    #
    # HANYA bagian ini yang memakai periode.
    # =====================================================

    periode = periode_sekarang()

    budget_list = Budget.query.filter_by(
        nomor_wa=nomor_wa,
        periode=periode
    ).all()

    budget_data = []

    for b in budget_list:

        terpakai = db.session.query(
            db.func.coalesce(
                db.func.sum(
                    Transaksi.nominal
                ),
                0
            )
        ).filter(

            Transaksi.nomor_wa == nomor_wa,

            Transaksi.tipe == "KELUAR",

            Transaksi.kategori == b.kategori,

            db.func.to_char(
                Transaksi.tanggal,
                "YYYY-MM"
            ) == periode

        ).scalar()

        terpakai = int(
            terpakai or 0
        )

        budget_nominal = int(
            b.nominal or 0
        )

        sisa = (
            budget_nominal
            - terpakai
        )

        persen = 0

        if budget_nominal > 0:

            persen = round(
                (terpakai / budget_nominal) * 100
            )

        budget_data.append({

            "kategori": b.kategori,

            "budget": budget_nominal,

            "terpakai": terpakai,

            "sisa": sisa,

            "persen": persen

        })

    # =====================================================
    # TARGET PEMBELIAN / TABUNGAN
    # =====================================================

    target_pembelian = TargetPembelian.query.filter(

        TargetPembelian.nomor_wa == nomor_wa,

        TargetPembelian.aktif == True

    ).order_by(

        TargetPembelian.deadline.asc()

    ).first()

    target_data = None

    if target_pembelian:

        target = (
            target_pembelian.target
            or 0
        )

        terkumpul = (
            target_pembelian.terkumpul
            or 0
        )

        progress = 0

        if target > 0:

            progress = round(
                (
                    terkumpul
                    / target
                ) * 100,
                1
            )

        progress = min(
            progress,
            100
        )

        sisa = max(
            target - terkumpul,
            0
        )

        sisa_hari = (

            target_pembelian.deadline
            - sekarang().date()

        ).days

        target_data = {

            "id": target_pembelian.id,

            "nama": target_pembelian.nama,

            "target": target,

            "terkumpul": terkumpul,

            "sisa": sisa,

            "progress": progress,

            "deadline": (
                target_pembelian.deadline.strftime(
                    "%Y-%m-%d"
                )
                if target_pembelian.deadline
                else None
            ),

            "sisa_hari": sisa_hari,

            "selesai": progress >= 100

        }

    # =====================================================
    # REMINDER
    # =====================================================

    reminders = Reminder.query.filter_by(
        nomor_wa=nomor_wa,
        aktif=True
    ).order_by(
        Reminder.tanggal.asc()
    ).all()

    reminder_count = len(
        reminders
    )

    reminder_today = 0
    reminder_week = 0
    reminder_month = 0
    reminder_overdue = 0

    reminder_list = []

    for r in reminders:

        tanggal = date(
            today.year,
            today.month,
            r.tanggal
        )

        if tanggal < today:

            if today.month == 12:

                tanggal = date(
                    today.year + 1,
                    1,
                    r.tanggal
                )

            else:

                tanggal = date(
                    today.year,
                    today.month + 1,
                    r.tanggal
                )

        selisih = (
            tanggal - today
        ).days

        if selisih < 0:

            reminder_overdue += 1

        elif selisih == 0:

            reminder_today += 1

        elif selisih <= 7:

            reminder_week += 1

        reminder_month += 1

        if selisih < 0:

            status = (
                f"Terlambat {abs(selisih)} hari"
            )

            warna = "danger"

        elif selisih == 0:

            status = "Hari ini"

            warna = "warning"

        elif selisih == 1:

            status = "Besok"

            warna = "warning"

        else:

            status = (
                f"{selisih} hari lagi"
            )

            warna = "success"

        reminder_list.append({

            "hari": tanggal.strftime("%d"),

            "bulan": tanggal.strftime("%b").upper(),

            "judul": r.nama,

            "kategori": getattr(
                r,
                "kategori",
                "-"
            ),

            "catatan": getattr(
                r,
                "catatan",
                ""
            ),

            "nominal": r.nominal or 0,

            "status": status,

            "status_color": warna

        })

    # =====================================================
    # HUTANG
    # =====================================================

    hutang_list = HutangPiutang.query.filter(

        HutangPiutang.nomor_wa == nomor_wa,

        HutangPiutang.tipe == "HUTANG",

        HutangPiutang.status != "LUNAS"

    ).order_by(

        HutangPiutang.tanggal.desc()

    ).all()

    # =====================================================
    # PIUTANG
    # =====================================================

    piutang_list = HutangPiutang.query.filter(

        HutangPiutang.nomor_wa == nomor_wa,

        HutangPiutang.tipe == "PIUTANG",

        HutangPiutang.status != "LUNAS"

    ).order_by(

        HutangPiutang.tanggal.desc()

    ).all()

    total_hutang = sum(
        x.nominal or 0
        for x in hutang_list
    )

    total_piutang = sum(
        x.nominal or 0
        for x in piutang_list
    )

    net_balance = (
        total_piutang
        - total_hutang
    )

    # =====================================================
    # AI INSIGHT
    # =====================================================

    try:

        from utils.ai_insight import generate_ai_insight

        insight = generate_ai_insight(
            nomor_wa
        )

    except Exception as e:

        print(
            "AI INSIGHT ERROR:",
            e
        )

        insight = None

    # =====================================================
    # TREND
    #
    # Mengikuti dashboard Railway:
    # semua transaksi.
    # =====================================================

    trend_label = []
    trend_value = []

    for trx in reversed(all_data):

        tanggal = trx.tanggal.strftime(
            "%d %b"
        )

        if tanggal not in trend_label:

            trend_label.append(
                tanggal
            )

            trend_value.append(
                trx.nominal or 0
            )

        else:

            index = trend_label.index(
                tanggal
            )

            trend_value[index] += (
                trx.nominal or 0
            )

    # =====================================================
    # RESPONSE
    # =====================================================

    return jsonify({

        "success": True,

        "status": True,

        # Periode hanya informasi budget,
        # bukan periode saldo.
        "periode": periode,

        # =================================================
        # SALDO GLOBAL
        # =================================================

        "saldo": int(saldo),

        "masuk": int(total_masuk),

        "keluar": int(total_keluar),

        "saving": int(saving),

        "saving_persen": saving_persen,

        "jumlah_transaksi": int(
            jumlah_transaksi
        ),

        # =================================================
        # HARI INI
        # =================================================

        "transaksi_hari_ini": int(
            transaksi_hari_ini
        ),

        "masuk_hari_ini": int(
            masuk_hari_ini
        ),

        "keluar_hari_ini": int(
            keluar_hari_ini
        ),

        "saving_hari_ini": int(
            saving_hari_ini
        ),

        # =================================================
        # TRANSAKSI
        # =================================================

        "rows": transaksi_terbaru,

        # =================================================
        # BUDGET
        # =================================================

        "budget": budget_data,

        # =================================================
        # TARGET
        # =================================================

        "target": target_data,

        # =================================================
        # REMINDER
        # =================================================

        "reminder": {

            "count": reminder_count,

            "today": reminder_today,

            "week": reminder_week,

            "month": reminder_month,

            "overdue": reminder_overdue,

            "list": reminder_list

        },

        # =================================================
        # HUTANG PIUTANG
        # =================================================

        "hutang_piutang": {

            "total_hutang": int(
                total_hutang
            ),

            "total_piutang": int(
                total_piutang
            ),

            "net_balance": int(
                net_balance
            )

        },

        # =================================================
        # TREND
        # =================================================

        "trend": {

            "label": trend_label,

            "value": trend_value

        },

        # =================================================
        # AI
        # =================================================

        "insight": insight

    })


# =========================================================
# GET TRANSAKSI
# =========================================================

@app.route("/api/transaksi", methods=["GET"])
@jwt_required()
def get_transaksi():

    user = get_logged_in_user()

    if not user:
        return jsonify({
            "success": False,
            "message": "User tidak ditemukan."
        }), 401

    nomor_wa = user.nomor_whatsapp

    page = request.args.get(
        "page",
        1,
        type=int
    )

    limit = request.args.get(
        "limit",
        20,
        type=int
    )

    search = request.args.get(
        "search",
        "",
        type=str
    ).strip()

    tipe = request.args.get(
        "tipe",
        "",
        type=str
    ).strip().upper()

    bulan = request.args.get(
        "bulan",
        "",
        type=str
    ).strip()

    # =====================================================
    # VALIDASI PAGINATION
    # =====================================================

    if page < 1:
        page = 1

    if limit < 1:
        limit = 20

    if limit > 100:
        limit = 100

    # =====================================================
    # QUERY USER
    # =====================================================

    query = Transaksi.query.filter(
        Transaksi.nomor_wa == nomor_wa
    )

    # =====================================================
    # FILTER TIPE
    # =====================================================

    if tipe in ["MASUK", "KELUAR"]:

        query = query.filter(
            Transaksi.tipe == tipe
        )

    # =====================================================
    # FILTER BULAN
    # =====================================================

    if bulan:

        try:

            tahun, bulan_num = map(
                int,
                bulan.split("-")
            )

            if bulan_num < 1 or bulan_num > 12:
                raise ValueError

            awal_bulan = datetime(
                tahun,
                bulan_num,
                1
            )

            if bulan_num == 12:

                akhir_bulan = datetime(
                    tahun + 1,
                    1,
                    1
                )

            else:

                akhir_bulan = datetime(
                    tahun,
                    bulan_num + 1,
                    1
                )

            query = query.filter(
                Transaksi.tanggal >= awal_bulan,
                Transaksi.tanggal < akhir_bulan
            )

        except (ValueError, TypeError):

            return jsonify({
                "success": False,
                "message": "Format bulan harus YYYY-MM."
            }), 400

    # =====================================================
    # SEARCH
    # =====================================================

    if search:

        pattern = f"%{search}%"

        query = query.filter(

            or_(

                Transaksi.keterangan.ilike(
                    pattern
                ),

                Transaksi.kategori.ilike(
                    pattern
                ),

                Transaksi.subkategori.ilike(
                    pattern
                )

            )

        )

    # =====================================================
    # ORDER
    # =====================================================

    query = query.order_by(

        Transaksi.tanggal.desc(),

        Transaksi.id.desc()

    )

    # =====================================================
    # PAGINATION
    # =====================================================

    pagination = query.paginate(

        page=page,

        per_page=limit,

        error_out=False

    )

    data = []

    for t in pagination.items:

        data.append({

            "id": t.id,

            "tanggal": (
                t.tanggal.isoformat()
                if t.tanggal
                else None
            ),

            "tanggal_display": (
                t.tanggal.strftime(
                    "%d/%m/%Y %H:%M"
                )
                if t.tanggal
                else "-"
            ),

            "tipe": t.tipe,

            "nominal": int(
                t.nominal or 0
            ),

            "kategori": (
                t.kategori or ""
            ),

            "subkategori": (
                t.subkategori or ""
            ),

            "keterangan": (
                t.keterangan or ""
            )

        })

    return jsonify({

        "success": True,

        "data": data,

        "pagination": {

            "page": pagination.page,

            "limit": pagination.per_page,

            "total": pagination.total,

            "pages": pagination.pages

        }

    })


# =========================================================
# CREATE TRANSAKSI
# =========================================================

@app.route("/api/transaksi", methods=["POST"])
@jwt_required()
def create_transaksi():

    user = get_logged_in_user()

    if not user:

        return jsonify({
            "success": False,
            "message": "User tidak ditemukan."
        }), 401

    # =====================================================
    # NOMOR WA DIAMBIL DARI DATABASE
    # =====================================================

    nomor_wa = user.nomor_whatsapp

    data = request.get_json(
        silent=True
    ) or {}

    tipe = str(
        data.get("tipe", "")
    ).strip().upper()

    kategori = str(
        data.get("kategori", "")
    ).strip()

    subkategori = str(
        data.get("subkategori", "")
    ).strip()

    keterangan = str(
        data.get("keterangan", "")
    ).strip()

    nominal = data.get("nominal")

    tanggal = data.get("tanggal")

    # =====================================================
    # VALIDASI TIPE
    # =====================================================

    if tipe not in ["MASUK", "KELUAR"]:

        return jsonify({
            "success": False,
            "message": "Tipe transaksi harus MASUK atau KELUAR."
        }), 400

    # =====================================================
    # VALIDASI NOMINAL
    # =====================================================

    try:

        nominal = int(nominal)

    except (ValueError, TypeError):

        return jsonify({
            "success": False,
            "message": "Nominal harus berupa angka."
        }), 400

    if nominal <= 0:

        return jsonify({
            "success": False,
            "message": "Nominal harus lebih dari 0."
        }), 400

    # =====================================================
    # VALIDASI PANJANG
    # =====================================================

    if len(kategori) > 50:

        return jsonify({
            "success": False,
            "message": "Kategori maksimal 50 karakter."
        }), 400

    if len(subkategori) > 100:

        return jsonify({
            "success": False,
            "message": "Subkategori maksimal 100 karakter."
        }), 400

    if len(keterangan) > 255:

        return jsonify({
            "success": False,
            "message": "Keterangan maksimal 255 karakter."
        }), 400

    # =====================================================
    # TANGGAL
    # =====================================================

    tanggal_obj = datetime.now()

    if tanggal:

        try:

            tanggal_obj = datetime.fromisoformat(
                tanggal
            )

        except ValueError:

            return jsonify({
                "success": False,
                "message": "Format tanggal tidak valid."
            }), 400

    # =====================================================
    # CREATE
    # =====================================================

    transaksi = Transaksi(

        tanggal=tanggal_obj,

        tipe=tipe,

        nominal=nominal,

        kategori=kategori or None,

        subkategori=subkategori or None,

        keterangan=keterangan or None,

        nomor_wa=nomor_wa

    )

    db.session.add(transaksi)

    db.session.commit()

    return jsonify({

        "success": True,

        "message": "Transaksi berhasil ditambahkan.",

        "data": {

            "id": transaksi.id,

            "tanggal": transaksi.tanggal.isoformat(),

            "tipe": transaksi.tipe,

            "nominal": int(
                transaksi.nominal or 0
            ),

            "kategori": transaksi.kategori,

            "subkategori": transaksi.subkategori,

            "keterangan": transaksi.keterangan

        }

    }), 201


# =========================================================
# UPDATE TRANSAKSI
# =========================================================

@app.route(
    "/api/transaksi/<int:transaksi_id>",
    methods=["PUT"]
)
@jwt_required()
def update_transaksi(transaksi_id):

    user = get_logged_in_user()

    if not user:

        return jsonify({
            "success": False,
            "message": "User tidak ditemukan."
        }), 401

    nomor_wa = user.nomor_whatsapp

    # =====================================================
    # CARI TRANSAKSI MILIK USER
    # =====================================================

    transaksi = Transaksi.query.filter_by(

        id=transaksi_id,

        nomor_wa=nomor_wa

    ).first()

    if not transaksi:

        return jsonify({
            "success": False,
            "message": "Transaksi tidak ditemukan."
        }), 404

    data = request.get_json(
        silent=True
    ) or {}

    tipe = str(
        data.get(
            "tipe",
            transaksi.tipe
        )
    ).strip().upper()

    kategori = str(
        data.get(
            "kategori",
            transaksi.kategori or ""
        )
    ).strip()

    subkategori = str(
        data.get(
            "subkategori",
            transaksi.subkategori or ""
        )
    ).strip()

    keterangan = str(
        data.get(
            "keterangan",
            transaksi.keterangan or ""
        )
    ).strip()

    nominal = data.get(
        "nominal",
        transaksi.nominal
    )

    tanggal = data.get("tanggal")

    # =====================================================
    # VALIDASI TIPE
    # =====================================================

    if tipe not in ["MASUK", "KELUAR"]:

        return jsonify({
            "success": False,
            "message": "Tipe transaksi tidak valid."
        }), 400

    # =====================================================
    # VALIDASI NOMINAL
    # =====================================================

    try:

        nominal = int(nominal)

    except (ValueError, TypeError):

        return jsonify({
            "success": False,
            "message": "Nominal harus berupa angka."
        }), 400

    if nominal <= 0:

        return jsonify({
            "success": False,
            "message": "Nominal harus lebih dari 0."
        }), 400

    # =====================================================
    # VALIDASI PANJANG
    # =====================================================

    if len(kategori) > 50:

        return jsonify({
            "success": False,
            "message": "Kategori maksimal 50 karakter."
        }), 400

    if len(subkategori) > 100:

        return jsonify({
            "success": False,
            "message": "Subkategori maksimal 100 karakter."
        }), 400

    if len(keterangan) > 255:

        return jsonify({
            "success": False,
            "message": "Keterangan maksimal 255 karakter."
        }), 400

    # =====================================================
    # UPDATE TANGGAL
    # =====================================================

    if tanggal:

        try:

            transaksi.tanggal = datetime.fromisoformat(
                tanggal
            )

        except ValueError:

            return jsonify({
                "success": False,
                "message": "Format tanggal tidak valid."
            }), 400

    # =====================================================
    # UPDATE
    # =====================================================

    transaksi.tipe = tipe

    transaksi.nominal = nominal

    transaksi.kategori = (
        kategori or None
    )

    transaksi.subkategori = (
        subkategori or None
    )

    transaksi.keterangan = (
        keterangan or None
    )

    db.session.commit()

    return jsonify({

        "success": True,

        "message": "Transaksi berhasil diperbarui.",

        "data": {

            "id": transaksi.id,

            "tanggal": transaksi.tanggal.isoformat(),

            "tipe": transaksi.tipe,

            "nominal": int(
                transaksi.nominal or 0
            ),

            "kategori": transaksi.kategori,

            "subkategori": transaksi.subkategori,

            "keterangan": transaksi.keterangan

        }

    })


# =========================================================
# DELETE TRANSAKSI
# =========================================================

@app.route(
    "/api/transaksi/<int:transaksi_id>",
    methods=["DELETE"]
)
@jwt_required()
def delete_transaksi(transaksi_id):

    user = get_logged_in_user()

    if not user:

        return jsonify({
            "success": False,
            "message": "User tidak ditemukan."
        }), 401

    nomor_wa = user.nomor_whatsapp

    # =====================================================
    # PASTIKAN TRANSAKSI MILIK USER
    # =====================================================

    transaksi = Transaksi.query.filter_by(

        id=transaksi_id,

        nomor_wa=nomor_wa

    ).first()

    if not transaksi:

        return jsonify({
            "success": False,
            "message": "Transaksi tidak ditemukan."
        }), 404

    db.session.delete(transaksi)

    db.session.commit()

    return jsonify({

        "success": True,

        "message": "Transaksi berhasil dihapus."

    })

# =========================
# TEST
# =========================
@app.route("/test-wa")
def test_wa():
    kirim_wa("6285871264448", "Test dari Railway berhasil")
    return {"status": True}


@app.route("/webhook-test", methods=["GET", "POST"])
def webhook_test():
    print("========== WEBHOOK TEST MASUK ==========")
    print("METHOD:", request.method)
    print("DATA:", request.get_data(as_text=True))
    print("=========================================")

    return jsonify({
        "status": True,
        "message": "Railway B webhook test OK"
    })

@app.route("/debug-token")
def debug_token():
    token = os.getenv("FONTE_TOKEN")
    return {
        "exists": bool(token),
        "length": len(token) if token else 0
    }

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
