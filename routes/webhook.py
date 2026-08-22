import os

from flask import Blueprint,Flask, request, jsonify, render_template, send_file, redirect
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta, time
from models import db, Transaksi, Budget, Reminder, User, RequestDemo, TargetPembelian, HutangPiutang, MonthlySummary, Transaksi, get_owner_number, SharedAccess, is_viewer
import requests
import os
import pandas as pd
import io
from zoneinfo import ZoneInfo
from itsdangerous import URLSafeTimedSerializer
from itsdangerous import BadSignature
from itsdangerous import SignatureExpired

from utils.duplicate import is_duplicate
from utils.helper import *

webhook_bp = Blueprint("webhook", __name__)

ADMIN_NUMBER = "6285872362212"

def is_admin(sender):
    return sender == ADMIN_NUMBER

def get_current_balance(nomor_wa):
    verify_monthly_summary(
        nomor_wa
    )
    """
    Menghitung saldo saat ini menggunakan snapshot MonthlySummary.

    Alur:
    1. Cari snapshot (closing) terakhir.
    2. Jika ada:
       saldo = saldo_akhir_snapshot
             + pemasukan setelah snapshot
             - pengeluaran setelah snapshot

    3. Jika belum ada snapshot:
       saldo = seluruh pemasukan
             - seluruh pengeluaran
    """

    last_summary = (
        MonthlySummary.query
        .filter_by(nomor_wa=nomor_wa)
        .order_by(MonthlySummary.periode.desc())
        .first()
    )

    # =====================================
    # BELUM ADA CLOSING
    # =====================================
    if last_summary is None:

        total_masuk = (
            db.session.query(
                func.coalesce(func.sum(Transaksi.nominal), 0)
            )
            .filter(
                Transaksi.nomor_wa == nomor_wa,
                Transaksi.tipe == "MASUK"
            )
            .scalar()
        )

        total_keluar = (
            db.session.query(
                func.coalesce(func.sum(Transaksi.nominal), 0)
            )
            .filter(
                Transaksi.nomor_wa == nomor_wa,
                Transaksi.tipe == "KELUAR"
            )
            .scalar()
        )

        return total_masuk - total_keluar

    # =====================================
    # ADA SNAPSHOT
    # =====================================

    tahun, bulan = map(int, last_summary.periode.split("-"))

    if bulan == 12:

        mulai = datetime(
            tahun + 1,
            1,
            1,
            0,
            0,
            0
        )

    else:

        mulai = datetime(
            tahun,
            bulan + 1,
            1,
            0,
            0,
            0
        )

    total_masuk = (
        db.session.query(
            func.coalesce(func.sum(Transaksi.nominal), 0)
        )
        .filter(
            Transaksi.nomor_wa == nomor_wa,
            Transaksi.tipe == "MASUK",
            Transaksi.tanggal >= mulai
        )
        .scalar()
    )

    total_keluar = (
        db.session.query(
            func.coalesce(func.sum(Transaksi.nominal), 0)
        )
        .filter(
            Transaksi.nomor_wa == nomor_wa,
            Transaksi.tipe == "KELUAR",
            Transaksi.tanggal >= mulai
        )
        .scalar()
    )

    saldo = (
        last_summary.saldo_akhir
        + total_masuk
        - total_keluar
    )

    return saldo

def refresh_summary_after_transaction(tanggal_transaksi):
    """
    Refresh MonthlySummary setelah transaksi ditambah,
    diubah atau dihapus.

    Hanya akan melakukan cascade jika bulan tersebut
    sudah pernah dilakukan closing.
    """

    periode = tanggal_transaksi.strftime("%Y-%m")

    summary = MonthlySummary.query.filter_by(
        periode=periode
    ).first()

    # Belum pernah closing
    if summary is None:
        return

    print("=" * 60)
    print("AUTO RECALCULATE")
    print("Periode :", periode)
    print("=" * 60)

    cascade_reclosing(periode)

# =========================
# WEBHOOK
# =========================
@webhook_bp.route("/webhook", methods=["POST"])
def webhook():
    print("========== WEBHOOK ASLI MASUK ==========")
    print("METHOD:", request.method)
    print("HEADERS:", dict(request.headers))
    payload = request.get_json(silent=True) or {}

    print("=" * 80)
    print("WEBHOOK INCOMING")
    print(payload)
    print("=" * 80)

    # ======================================
    # IGNORE STATUS EVENT
    # ======================================

    if payload.get("status") or payload.get("state"):
        return jsonify(status=True)

    if payload.get("event") in [
        "sent",
        "delivered",
        "read"
    ]:
        return jsonify(status=True)

    # ======================================
    # AMBIL DATA
    # ======================================

    # sender = normalize_wa(
    #     payload.get("sender")
    #     or payload.get("pengirim")
    #     or payload.get("from")
    #     or ""
    # )

    # message = str(
    #     payload.get("message")
    #     or payload.get("pesan")
    #     or ""
    # ).strip()

    # msg_id = (
    #     payload.get("id")
    #     or payload.get("inboxid")
    #     or f"{sender}:{int(time.time())}"
    # )

    # ======================================
    # AMBIL DATA BABLAST
    # ======================================

    data = payload.get("data") or {}

    sender = normalize_wa(
        data.get("from_phone")
        or data.get("from")
        or payload.get("sender")
        or payload.get("pengirim")
        or payload.get("from")
        or ""
    )

    message = str(
        data.get("content")
        or data.get("message")
        or payload.get("message")
        or payload.get("pesan")
        or ""
    ).strip()

    msg_id = (
        data.get("message_id")
        or payload.get("id")
        or payload.get("inboxid")
        or f"{sender}:{int(time.time())}"
    )

    pushname = str(
        data.get("from_name")
        or payload.get("pushname")
        or ""
    ).strip()

    print("========================================")
    print("📱 SENDER :", sender)
    print("👤 NAME   :", pushname)
    print("💬 MESSAGE:", message)
    print("🆔 MSG ID :", msg_id)
    print("========================================")

    if not sender:
        return jsonify(status=True)

    if not message:
        return jsonify(status=True)

    lower_msg = message.lower()

    print("Sender :", sender)
    print("Message:", message)

    # pushname = str(payload.get("pushname") or "").strip()

    # ======================================
    # ANTI LOOP
    # ======================================

    # pesan dari bot sendiri
    if message.startswith("[BOT]"):
        return jsonify(status=True)

    # footer fonnte
    if "sent via fonnte" in lower_msg:
        return jsonify(status=True)

    # balasan bot
    if "chatsaku finance assistant" in lower_msg:
        return jsonify(status=True)

    if "nomor belum terdaftar" in lower_msg:
        return jsonify(status=True)

    # nomor bot sendiri
    bot_number = normalize_wa(
        os.getenv("BOT_NUMBER", "")
    )

    if sender == bot_number:
        return jsonify(status=True)

    # ======================================
    # DUPLICATE FILTER
    # ======================================

    if is_duplicate(msg_id):
        return jsonify(status=True)

    # ======================================
    # COMMAND
    # ======================================

    cmd = lower_msg.strip()

    print("CMD :", cmd)

    print("SENDER :", sender)
    print("MESSAGE:", message)
    print("CMD    :", cmd)

    # ======================================
    # REQUEST DEMO
    # ======================================

    if cmd.startswith("halo chatsaku, saya ingin mencoba versi gratis"):

        print("="*50)
        print("REQUEST DEMO")
        print("Sender :", sender)
        print("Pushname :", pushname)
        print("="*50)


        demo = RequestDemo.query.filter_by(
            nomor_wa=sender
        ).first()

        if demo is None:

            demo = RequestDemo(
                nomor_wa=sender,
                nama=pushname or ""
            )

            db.session.add(demo)
            db.session.commit()

            kirim_wa(
                sender,
                """🎉 Terima kasih telah mendaftar ChatSaku Free.

    Permintaan Anda berhasil diterima.

    Silakan menunggu persiapan oleh admin 😊.

    _ChatSaku Finance Assistant_"""
            )

            # ==========================
            # NOTIFIKASI KE ADMIN
            # ==========================

            kirim_wa(
                ADMIN_NUMBER,   # contoh: "6281234567890"
                f"""🚀 *Request ChatSaku Free Baru*

    👤 Nama : {pushname or '-'}
    📱 Nomor : {sender}

    Ada pengguna baru yang meminta akses ChatSaku Free.

    Silakan lakukan follow up."""
            )

        else:

            kirim_wa(
                sender,
                """✅ Anda sudah pernah mendaftar ChatSaku Free.

    Silakan langsung kirim transaksi, misalnya:

    • masuk 500000 gaji
    • keluar 25000 makan"""
            )

        return jsonify({"status": True})

    # ======================================
    # VALIDASI USER
    # ======================================

    user = user_terdaftar(sender)

    print("User :", user)

    if not user:

        print("UNREGISTERED :", sender)

        kirim_wa(
            sender,
            """🚫 *Nomor Belum Terdaftar*

Maaf, nomor WhatsApp Anda belum terdaftar pada sistem *ChatSaku Finance*.

Silakan hubungi Admin untuk mengaktifkan akun Anda.

https://www.chatsaku.com

💚 _ChatSaku Finance Assistant_
"""
        )

        return jsonify(
            status=True,
            registered=False
        )

    # ======================================
    # CEK MASA BERLANGGANAN
    # ======================================

    from datetime import date

    if user.paket != "STARTER" and user.akhir_langganan:

        if date.today() > user.akhir_langganan:

            if user.aktif:

                user.aktif = False
                db.session.commit()

            kirim_wa(
                sender,
                f"""🔒 *Langganan ChatSaku Telah Berakhir*

    Paket : {user.paket}

    Berakhir pada:
    {user.akhir_langganan.strftime("%d-%m-%Y")}

    Silakan lakukan perpanjangan agar seluruh fitur dapat digunakan kembali.

    https://www.chatsaku.com

    💚 _ChatSaku Finance Assistant_"""
            )

            return jsonify(status=True)

    # Jika admin menonaktifkan akun
    if not user.aktif:

        kirim_wa(
            sender,
            """🚫 *Akun Anda Nonaktif*

    Silakan hubungi Admin ChatSaku untuk mengaktifkan kembali akun Anda.

    https://www.chatsaku.com"""
        )

        return jsonify(status=True)

    # =====================================================
    # HANYA RESPON COMMAND YANG DIKENAL
    # =====================================================
    valid_command = (
        cmd == "saldo"
        or cmd == "hariini"
        or cmd == "insight"
        or cmd == "dashboard"
        or cmd == "viewer"
        or cmd == "user"
        or cmd.startswith("adduser ")
        or cmd.startswith("deluser ")
        or cmd.startswith("paket ")
        or cmd.startswith("aktif ")
        or cmd.startswith("nonaktif ")
        or cmd.startswith("share ")
        or cmd.startswith("unshare ")
        or cmd.startswith("masuk")
        or cmd.startswith("keluar")
        or cmd.startswith("budget")
        or cmd.startswith("reminder")
        or cmd.startswith("hapusreminder")
        or cmd.startswith("halo chatsaku, saya ingin mencoba versi gratis")
        or cmd == "menu"
        or cmd == "fitur"
        or cmd == "help"
        or cmd == "target"
        or cmd.startswith("target ")
        or cmd.startswith("tabung")
        or cmd.startswith("hapustarget")
        or cmd=="hutang"
        or cmd.startswith("hutang ")
        or cmd=="piutang"
        or cmd.startswith("piutang ")
        or cmd.startswith("bayarhutang")
        or cmd.startswith("bayarpiutang")
    )

    if not valid_command:
        print("IGNORE NON COMMAND")
        return jsonify({
            "status": True,
            "ignored": True
        })

    # ======================================
    # List User
    # ======================================
    if cmd == "user":

        if not is_admin(sender):
            return jsonify(status=True)

        users = User.query.order_by(
            User.created_at.desc()
        ).all()

        if not users:

            kirim_wa(
                sender,
                "📭 Belum ada user."
            )

            return jsonify(status=True)

        text = (
            f"👥 *DAFTAR USER CHATSAKU*\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"Total User : {len(users)}\n\n"
        )

        for i, u in enumerate(users, 1):

            status = "🟢 Aktif" if u.aktif else "🔴 Nonaktif"

            expired = "-"

            if u.akhir_langganan:
                expired = u.akhir_langganan.strftime("%d-%m-%Y")

            text += (
                f"*{i}. {u.nama}*\n"
                f"📱 {u.nomor_wa}\n"
                f"💎 {u.paket}\n"
                f"{status}\n"
                f"📅 Expired : {expired}\n\n"
            )

            # Hindari pesan WA terlalu panjang
            if len(text) > 3300:
                kirim_wa(sender, text)
                text = ""

        if text:
            kirim_wa(sender, text)

        return jsonify(status=True)

    # ======================================
    # Tambah User
    # ======================================

    if cmd.startswith("adduser "):

        if not is_admin(sender):
            return jsonify(status=True)

        args = message.split()

        if len(args) < 5:

            kirim_wa(
                sender,
                """Format:

    adduser 628123456789 Bambang PREMIUM 30

    Paket:
    • STARTER
    • PRO
    • PREMIUM
    """
            )

            return jsonify(status=True)

        nomor = normalize_wa(args[1])

        nama = args[2]

        paket = args[3].upper()

        if paket not in FEATURES:

            kirim_wa(
                sender,
                "Paket hanya:\nSTARTER\nPRO\nPREMIUM"
            )

            return jsonify(status=True)

        try:
            lama = int(args[4])
        except:
            kirim_wa(
                sender,
                "Durasi harus berupa angka (hari)."
            )
            return jsonify(status=True)

        cek = User.query.filter_by(
            nomor_wa=nomor
        ).first()

        if cek:

            kirim_wa(
                sender,
                "❌ User sudah terdaftar."
            )

            return jsonify(status=True)

        # ==========================
        # HITUNG PERIODE LANGGANAN
        # ==========================

        mulai = date.today()

        akhir = mulai + timedelta(days=lama)

        # ==========================
        # BUAT USER
        # ==========================

        user = User(
            nama=nama,
            nomor_wa=nomor,
            paket=paket,
            aktif=True,
            mulai_langganan=mulai,
            akhir_langganan=akhir
        )

        db.session.add(user)
        db.session.commit()

        # ==========================
        # PESAN KE ADMIN
        # ==========================

        kirim_wa(
            sender,
            f"""✅ *User Berhasil Ditambahkan*

    👤 *Nama*
    {nama}

    📱 *Nomor*
    {nomor}

    🎁 *Paket*
    {paket}

    ⏳ *Durasi*
    {lama} Hari

    📅 *Mulai*
    {mulai.strftime('%d-%m-%Y')}

    📅 *Berakhir*
    {akhir.strftime('%d-%m-%Y')}

    🚀 User sudah dapat menggunakan ChatSaku.
    """
        )

        # ==========================
        # PESAN KE USER
        # ==========================

        kirim_wa(
            nomor,
            f"""🎉 *Selamat, Akun ChatSaku Anda Aktif!*

    Halo *{nama}* 👋

    Nomor WhatsApp Anda sekarang sudah dapat menggunakan *ChatSaku*.

    🎁 *Paket:* {paket}

    📅 *Periode Aktif*
    Mulai: {mulai.strftime('%d-%m-%Y')}
    Berakhir: {akhir.strftime('%d-%m-%Y')}

    Selama periode tersebut, Anda dapat menggunakan fitur ChatSaku sesuai dengan paket *{paket}* Anda.

    💬 Cukup kirim transaksi melalui WhatsApp dan biarkan ChatSaku membantu mencatat keuangan Anda.

    Contoh:
    _"Makan siang 25 ribu"_

    Selamat menggunakan *ChatSaku*! 💚

    🌐 www.chatsaku.com
    """
        )

        return jsonify(status=True)

    # ======================================
    # Delete User
    # ======================================

    if cmd.startswith("deluser "):

        if not is_admin(sender):
            return jsonify(status=True)

        args = message.split()

        if len(args) != 2:

            kirim_wa(
                sender,
                """Format:

    deluser 628123456789
    """
            )

            return jsonify(status=True)

        nomor = normalize_wa(args[1])

        # Tidak boleh menghapus admin
        if nomor == "6285872362212":

            kirim_wa(
                sender,
                "❌ User admin tidak dapat dihapus."
            )

            return jsonify(status=True)

        user = User.query.filter_by(
            nomor_wa=nomor
        ).first()

        if not user:

            kirim_wa(
                sender,
                "❌ User tidak ditemukan."
            )

            return jsonify(status=True)

        db.session.delete(user)

        db.session.commit()

        kirim_wa(
            sender,
            f"""✅ User berhasil dihapus

    👤 Nama
    {user.nama}

    📱 Nomor
    {user.nomor_wa}

    🎁 Paket
    {user.paket}
    """
        )

        return jsonify(status=True)

    # ======================================
    # Ganti Paket User
    # ======================================
    if cmd.startswith("paket "):

        if not is_admin(sender):
            return jsonify(status=True)

        args = message.split()

        if len(args) != 3:

            kirim_wa(
                sender,
                """Format:

    paket 628123456789 PREMIUM
    """
            )

            return jsonify(status=True)

        nomor = normalize_wa(args[1])

        paket = args[2].upper()

        if paket not in FEATURES:

            kirim_wa(
                sender,
                """Paket tersedia:

    • STARTER
    • PRO
    • PREMIUM
    """
            )

            return jsonify(status=True)

        user = User.query.filter_by(
            nomor_wa=nomor
        ).first()

        if not user:

            kirim_wa(
                sender,
                "❌ User tidak ditemukan."
            )

            return jsonify(status=True)

        paket_lama = user.paket

        user.paket = paket
        user.aktif = True

        db.session.commit()

        kirim_wa(
            sender,
            f"""✅ Paket berhasil diubah

    👤 Nama
    {user.nama}

    📱 Nomor
    {user.nomor_wa}

    📦 Paket Lama
    {paket_lama}

    🎁 Paket Baru
    {paket}
    """
        )

        return jsonify(status=True)

    # ======================================
    # Aktifkan User
    # ======================================

    if cmd.startswith("aktif "):

        if not is_admin(sender):
            return jsonify(status=True)

        args = message.split()

        if len(args) != 2:

            kirim_wa(
                sender,
                """Format:

    aktif 628123456789
    """
            )

            return jsonify(status=True)

        nomor = normalize_wa(args[1])

        user = User.query.filter_by(
            nomor_wa=nomor
        ).first()

        if not user:

            kirim_wa(
                sender,
                "❌ User tidak ditemukan."
            )

            return jsonify(status=True)

        if user.aktif:

            kirim_wa(
                sender,
                f"""ℹ️ User sudah aktif

    👤 {user.nama}
    📱 {user.nomor_wa}
    """
            )

            return jsonify(status=True)

        user.aktif = True

        db.session.commit()

        kirim_wa(
            sender,
            f"""✅ User berhasil diaktifkan

    👤 Nama
    {user.nama}

    📱 Nomor
    {user.nomor_wa}

    🎁 Paket
    {user.paket}

    🟢 Status
    Aktif
    """
        )

        return jsonify(status=True)

    # ======================================
    # Non Aktifkan User
    # ======================================

    if cmd.startswith("nonaktif "):

        if not is_admin(sender):
            return jsonify(status=True)

        args = message.split()

        if len(args) != 2:

            kirim_wa(
                sender,
                """Format:

    nonaktif 628123456789
    """
            )

            return jsonify(status=True)

        nomor = normalize_wa(args[1])

        # Jangan sampai admin menonaktifkan dirinya sendiri
        if nomor == sender:

            kirim_wa(
                sender,
                "❌ Anda tidak dapat menonaktifkan akun admin sendiri."
            )

            return jsonify(status=True)

        user = User.query.filter_by(
            nomor_wa=nomor
        ).first()

        if not user:

            kirim_wa(
                sender,
                "❌ User tidak ditemukan."
            )

            return jsonify(status=True)

        if not user.aktif:

            kirim_wa(
                sender,
                f"""ℹ️ User sudah nonaktif

    👤 {user.nama}
    📱 {user.nomor_wa}
    """
            )

            return jsonify(status=True)

        user.aktif = False

        db.session.commit()

        kirim_wa(
            sender,
            f"""✅ User berhasil dinonaktifkan

    👤 Nama
    {user.nama}

    📱 Nomor
    {user.nomor_wa}

    🎁 Paket
    {user.paket}

    🔴 Status
    Nonaktif
    """
        )

        return jsonify(status=True)

    # ======================================
    # TARGET BARU
    # ======================================

    if cmd.startswith("target "):

        if not has_feature(sender, "target"):

            kirim_wa(sender,
    """
    🔒 Fitur target tabungan hanya tersedia pada paket PREMIUM.

    Upgrade sekarang agar dapat:

    ✅ Budget Bulanan
    ✅ Reminder
    ✅ Target Tabungan
    ✅ Hutang Piutang
    ✅ AI Insight
    ✅ Dashboard Lengkap

            """)

        bagian = message.split()

        if len(bagian) >= 4:

            try:

                deadline = datetime.strptime(
                    bagian[-1],
                    "%d-%m-%Y"
                ).date()

                nominal = int(
                    bagian[-2].replace(".","")
                )

                nama = " ".join(
                    bagian[1:-2]
                )

            except:

                kirim_wa(
                    sender,
                    "Format:\n\ntarget laptop 12000000 31-12-2026"
                )

                return jsonify(status=True)

            cek = TargetPembelian.query.filter_by(
                nomor_wa=sender,
                nama=nama,
                aktif=True
            ).first()

            if cek:

                kirim_wa(
                    sender,
                    "Target tersebut sudah ada."
                )

                return jsonify(status=True)

            target = TargetPembelian(

                nomor_wa=sender,
                nama=nama,
                target=nominal,
                deadline=deadline

            )

            db.session.add(target)

            db.session.commit()

            kirim_wa(

                sender,

    f"""🎯 Target berhasil dibuat

Nama        : {nama}
Target      : Rp. {nominal:,.0f}
Deadline    :{deadline.strftime("%d-%m-%Y")}

Selamat menabung 💚
_ChatSaku Finance Assistant_"""
            )

            return jsonify(status=True)

    # ======================================
    # TABUNG
    # ======================================

    if cmd.startswith("tabung "):

        # ==========================================
        # CEK FITUR
        # ==========================================
        if not has_feature(sender, "tabung"):

            kirim_wa(
                sender,
                """🔒 *Fitur Tabungan hanya tersedia pada paket PREMIUM.*

    Upgrade sekarang agar dapat:

    ✅ Budget Bulanan
    ✅ Reminder
    ✅ Target Tabungan
    ✅ Hutang Piutang
    ✅ AI Insight
    ✅ Dashboard Lengkap
    """
            )

            return jsonify(status=True)

        # ==========================================
        # PARSING COMMAND
        # Format:
        # tabung laptop 500000
        # ==========================================
        bagian = message.strip().split()

        if len(bagian) < 3:

            kirim_wa(
                sender,
                """❌ Format tidak sesuai.

    Gunakan:

    *tabung [nama target] [nominal]*

    Contoh:

    tabung laptop 500000
    tabung motor 1000000
    tabung liburan 250000
    """
            )

            return jsonify(status=True)

        # ==========================================
        # AMBIL NOMINAL
        # ==========================================
        try:

            nominal = normalize_nominal(bagian[-1])

            if nominal is None or nominal <= 0:

                kirim_wa(
                    sender,
                    "❌ Nominal tabungan tidak valid."
                )

                return jsonify(status=True)

        except Exception as e:

            print("ERROR NORMALIZE NOMINAL:", e)

            kirim_wa(
                sender,
                "❌ Nominal tabungan tidak valid."
            )

            return jsonify(status=True)

        # ==========================================
        # AMBIL NAMA TARGET
        # ==========================================
        nama = " ".join(bagian[1:-1]).strip()

        if not nama:

            kirim_wa(
                sender,
                "❌ Nama target tabungan belum diisi."
            )

            return jsonify(status=True)

        # ==========================================
        # CARI TARGET
        # ==========================================
        target = TargetPembelian.query.filter_by(
            nomor_wa=sender,
            nama=nama,
            aktif=True
        ).first()

        if not target:

            kirim_wa(
                sender,
                f"""❌ *Target tidak ditemukan.*

    Target: *{nama}*

    Pastikan nama target sesuai dengan yang sudah dibuat.

    Contoh:
    *tabung laptop 500000*
    """
            )

            return jsonify(status=True)

        # ==========================================
        # VALIDASI TARGET
        # ==========================================
        if not target.target or target.target <= 0:

            kirim_wa(
                sender,
                "❌ Target tabungan tidak valid."
            )

            return jsonify(status=True)

        # ==========================================
        # TAMBAH TABUNGAN
        # ==========================================
        target.terkumpul = (target.terkumpul or 0) + nominal

        db.session.commit()

        # ==========================================
        # HITUNG PROGRESS
        # ==========================================
        persen = round(
            (target.terkumpul / target.target) * 100
        )

        if persen > 100:
            persen = 100

        # ==========================================
        # HITUNG SISA
        # ==========================================
        sisa = target.target - target.terkumpul

        if sisa < 0:
            sisa = 0

        # ==========================================
        # RESPONSE
        # ==========================================
        kirim_wa(
            sender,
            f"""💚 *Tabungan Berhasil*

    🎯 *{target.nama}*

    ➕ Ditabung
    Rp {nominal:,.0f}

    💰 Terkumpul
    Rp {target.terkumpul:,.0f}

    🎯 Target
    Rp {target.target:,.0f}

    📊 Progress
    {persen}%

    💵 Sisa
    Rp {sisa:,.0f}

    Semangat terus menabung! 🚀
    """
        )

        return jsonify(status=True)

    # ======================================
    # LIST TARGET
    # ======================================

    if cmd == "target":

        if not has_feature(sender, "target"):

            kirim_wa(
                sender,
                """
    🔒 Fitur Target Tabungan hanya tersedia pada paket PREMIUM.

    Upgrade sekarang agar dapat:

    ✅ Budget Bulanan
    ✅ Reminder
    ✅ Target Tabungan
    ✅ Hutang Piutang
    ✅ AI Insight
    ✅ Dashboard Lengkap
    """
            )

            return jsonify(status=True)

        nomor = get_owner_number(sender)

        data = TargetPembelian.query.filter_by(
            nomor_wa=nomor,
            aktif=True
        ).all()

        if not data:

            kirim_wa(
                sender,
                "Belum ada target tabungan."
            )

            return jsonify(status=True)

        text = "🎯 *TARGET TABUNGAN*\n\n"

        if nomor != sender:
            text += "👁 Mode Viewer (Data Owner)\n\n"

        for i, x in enumerate(data, 1):

            persen = round(
                (x.terkumpul / x.target) * 100
            ) if x.target else 0

            persen = min(persen, 100)

            sisa = max(x.target - x.terkumpul, 0)

            text += f"""*{i}. {x.nama}*

    📊 Progress : {persen}%
    💰 Terkumpul : Rp {x.terkumpul:,.0f}
    🎯 Target    : Rp {x.target:,.0f}
    💵 Sisa      : Rp {sisa:,.0f}

    _ChatSaku Finance Assistant_
    """

        kirim_wa(sender, text)

        return jsonify(status=True)

    # ======================================
    # DETAIL TARGET
    # ======================================
    if cmd.startswith("target "):

        if not has_feature(sender, "target"):

            kirim_wa(
                sender,
                """
    🔒 Fitur target tabungan hanya tersedia pada paket PREMIUM.

    Upgrade sekarang agar dapat:

    ✅ Budget Bulanan
    ✅ Reminder
    ✅ Target Tabungan
    ✅ Hutang Piutang
    ✅ AI Insight
    ✅ Dashboard Lengkap
    """
            )

            return jsonify(status=True)

        nomor = get_owner_number(sender)

        nama = message[7:].strip()

        target = TargetPembelian.query.filter_by(
            nomor_wa=nomor,
            nama=nama,
            aktif=True
        ).first()

        if not target:

            kirim_wa(
                sender,
                "❌ Target tidak ditemukan."
            )

            return jsonify(status=True)

        persen = round(
            (target.terkumpul / target.target) * 100
        ) if target.target else 0

        persen = min(persen, 100)

        sisa = max(target.target - target.terkumpul, 0)

        viewer_info = ""

        if nomor != sender:
            viewer_info = "\n👁 Mode Viewer (Data Owner)\n"

        kirim_wa(
            sender,
            f"""🎯 *{target.nama}*

    🎯 Target
    Rp {target.target:,.0f}

    💰 Terkumpul
    Rp {target.terkumpul:,.0f}

    💵 Sisa
    Rp {sisa:,.0f}

    📊 Progress
    {persen}%
    {viewer_info}
    _ChatSaku Finance Assistant_"""
        )

        return jsonify(status=True)

    # ======================================
    # HAPUS TARGET
    # ======================================

    if cmd.startswith("hapustarget"):

        if not has_feature(sender, "target"):

            kirim_wa(sender,
    """
    🔒 Fitur target tabungan hanya tersedia pada paket PREMIUM.

    Upgrade sekarang agar dapat:

    ✅ Budget Bulanan
    ✅ Reminder
    ✅ Target Tabungan
    ✅ Hutang Piutang
    ✅ AI Insight
    ✅ Dashboard Lengkap

            """)

        nama = message.replace(
            "hapustarget",
            ""
        ).strip()

        target = TargetPembelian.query.filter_by(

            nomor_wa=sender,
            nama=nama,
            aktif=True

        ).first()

        if target:

            db.session.delete(target)

            db.session.commit()

            kirim_wa(

                sender,

                "🗑 Target berhasil dihapus."

            )

        else:

            kirim_wa(

                sender,

                "Target tidak ditemukan."

            )

        return jsonify(status=True)

    # =========================
    # SALDO
    # =========================
    if cmd == "saldo":

        nomor = get_owner_number(sender)

        masuk = transaksi_user(nomor).filter(
            Transaksi.tipe == "MASUK"
        ).with_entities(
            db.func.sum(Transaksi.nominal)
        ).scalar() or 0

        keluar = transaksi_user(nomor).filter(
            Transaksi.tipe == "KELUAR"
        ).with_entities(
            db.func.sum(Transaksi.nominal)
        ).scalar() or 0

        saldo = get_current_balance(nomor)

        # link = generate_dashboard_link(sender)

        kirim_wa(
            sender,
            f"""💳 *Saldo Keuangan*
┌─────────────────────┐
📥 Masuk   : Rp {masuk:,.0f}
📤 Keluar  : Rp {keluar:,.0f}
 ──────────────────────
💰 Saldo   : *Rp {saldo:,.0f}*
└─────────────────────┘

_ChatSaku Finance Assistant_
"""
        )
        return jsonify({"status": True})

    # =========================
    # MASUK
    # =========================
    if cmd.startswith("masuk"):

        try:

            parts = message.split()

            if len(parts) < 2:

                kirim_wa(
                    sender,
                    "Format:\n\nmasuk 100000 gaji"
                )

                return jsonify(status=True)

            nominal = normalize_nominal(parts[1])

            if nominal is None or nominal <= 0:

                kirim_wa(
                    sender,
                    "❌ Nominal tidak valid."
                )

                return jsonify(status=True)

            keterangan = (
                " ".join(parts[2:])
                if len(parts) > 2
                else "-"
            )

            nomor = get_owner_number(sender)

            trx = Transaksi(

                tanggal=sekarang(),

                tipe="MASUK",

                nominal=nominal,

                keterangan=keterangan,

                nomor_wa=nomor

            )

            db.session.add(trx)

            db.session.commit()

            masuk = transaksi_user(sender).filter(
                Transaksi.tipe == "MASUK"
            ).with_entities(
                db.func.sum(Transaksi.nominal)
            ).scalar() or 0

            keluar = transaksi_user(sender).filter(
                Transaksi.tipe == "KELUAR"
            ).with_entities(
                db.func.sum(Transaksi.nominal)
            ).scalar() or 0

            saldo = masuk - keluar

            kirim_wa(
                sender,
                f"""✅ *Transaksi Berhasil*
    ┌────────────────────┐
    💰 *PEMASUKAN*

    💵 Nominal      : Rp {nominal:,.0f}
    📝 Keterangan   : {keterangan}

    🕒 {sekarang().strftime("%d %b %Y • %H:%M")}
    └────────────────────┘

    💳 *Saldo Saat Ini*
    Rp {saldo:,.0f}

    ━━━━━━━━━━━━━━━━━━
    _ChatSaku Finance Assistant_
    """
            )

        except Exception as e:

            print(e)

            kirim_wa(
                sender,
                "Format:\n\nmasuk 100000 gaji"
            )

        return jsonify(status=True)

    # =========================
    # KELUAR
    # =========================
    if cmd.startswith("keluar"):

        try:

            parts = message.split()

            if len(parts) < 3:

                kirim_wa(
                    sender,
                    "Format:\nkeluar 25000 grab"
                )

                return jsonify({"status": True})

            nominal = normalize_nominal(parts[1])

            if nominal <= 0:

                kirim_wa(
                    sender,
                    "Nominal harus lebih dari 0."
                )

                return jsonify({"status": True})

            keterangan = " ".join(parts[2:])

            kategori, subkategori = cari_kategori(keterangan)

            trx = Transaksi(
                tanggal=sekarang(),
                tipe="KELUAR",
                nominal=nominal,
                kategori=kategori,
                subkategori=subkategori,
                keterangan=keterangan,
                nomor_wa=sender
            )

            db.session.add(trx)
            db.session.commit()

            # ======================================
            # TOTAL SALDO
            # ======================================

            masuk = transaksi_user(sender).filter(
                Transaksi.tipe == "MASUK"
            ).with_entities(
                db.func.sum(Transaksi.nominal)
            ).scalar() or 0

            keluar = transaksi_user(sender).filter(
                Transaksi.tipe == "KELUAR"
            ).with_entities(
                db.func.sum(Transaksi.nominal)
            ).scalar() or 0

            saldo = masuk - keluar

            # ======================================
            # DASHBOARD
            # ======================================

            link = generate_dashboard_link(sender)

            # ======================================
            # BUDGET
            # ======================================

            periode = periode_sekarang()

            budget = Budget.query.filter_by(
                nomor_wa=sender,
                kategori=kategori,
                periode=periode
            ).first()

            budget_text = ""

            if budget:

                now = sekarang()

                awal_bulan = now.replace(
                    day=1,
                    hour=0,
                    minute=0,
                    second=0,
                    microsecond=0
                )

                if now.month == 12:
                    akhir_bulan = now.replace(
                        year=now.year + 1,
                        month=1,
                        day=1,
                        hour=0,
                        minute=0,
                        second=0,
                        microsecond=0
                    )
                else:
                    akhir_bulan = now.replace(
                        month=now.month + 1,
                        day=1,
                        hour=0,
                        minute=0,
                        second=0,
                        microsecond=0
                    )

                total_keluar = transaksi_user(sender).filter(
                    Transaksi.tipe == "KELUAR",
                    Transaksi.kategori == kategori,
                    Transaksi.tanggal >= awal_bulan,
                    Transaksi.tanggal < akhir_bulan
                ).with_entities(
                    db.func.sum(Transaksi.nominal)
                ).scalar() or 0

                persen = (
                    (total_keluar / budget.nominal) * 100
                    if budget.nominal > 0 else 0
                )

                sisa = budget.nominal - total_keluar

                blok = min(10, int(persen / 10))
                bar = "🟩" * blok + "⬜" * (10 - blok)

                if persen <= 50:
                    status = "🟢 Budget Aman"
                elif persen <= 80:
                    status = "🟡 Perlu Perhatian"
                elif persen <= 100:
                    status = "🟠 Hampir Habis"
                else:
                    status = "🔴 Budget Terlampaui"

                budget_text = f"""
    ──────────────────
    🏦 *Budget Bulan Ini*

    🏷️ Kategori
    {kategori.title()}

    💰 Budget
    Rp {budget.nominal:,.0f}

    💸 Terpakai
    Rp {total_keluar:,.0f}

    💳 Sisa Budget
    Rp {max(sisa,0):,.0f}

    📊 Progress
    {persen:.1f}%

    {bar}

    {status}
    """

                if persen > 100:

                    over = total_keluar - budget.nominal

                    budget_text += f"""

    ⚠️ Melebihi Budget
    Rp {over:,.0f}
    """

            else:

                budget_text = """
    ──────────────────

    🏦 *Budget Bulan Ini*

    ℹ️ Belum ada budget untuk kategori ini.

    Contoh:
    budget transport 1000000
    """

            kirim_wa(
                sender,
                f"""🏦 *Notifikasi Transaksi*
    ──────────────────

    ✅ *Debit Berhasil*
    💸 - Rp {nominal:,.0f}

    🏷️ Kategori
    {kategori.title()}

    📂 Subkategori
    {subkategori.title()}

    📝 Keterangan
    {keterangan}

    🕒 {sekarang().strftime("%d %b %Y • %H:%M")}

    {budget_text}

    ──────────────────

    💳 Saldo Tersedia
    *Rp {saldo:,.0f}*

    ──────────────────
    _ChatSaku Finance Assistant_
    """
            )

        except ValueError:

            kirim_wa(
                sender,
                "❌ Nominal tidak valid.\n\nContoh:\nkeluar 2.000.000 grab"
            )

        except Exception as e:

            print(e)

            kirim_wa(
                sender,
                f"""❌ Terjadi kesalahan

    {e}

    Format:
    keluar 25000 grab
    """
            )

        return jsonify({"status": True})

    # =========================
    # HARI INI
    # =========================
    if cmd == "hariini":

        nomor = get_owner_number(sender)

        today = sekarang().date()

        data = transaksi_user(nomor).filter(
            db.func.date(Transaksi.tanggal) == today
        ).all()

        total = sum(x.nominal for x in data)

        masuk_hari_ini = sum(
            x.nominal
            for x in data
            if x.tipe == "MASUK"
        )

        keluar_hari_ini = sum(
            x.nominal
            for x in data
            if x.tipe == "KELUAR"
        )

        viewer_info = ""

        if nomor != sender:
            viewer_info = "\n👁 *Mode Viewer (Data Owner)*\n"

        kirim_wa(
            sender,
            f"""📊 *Ringkasan Hari Ini*
    ━━━━━━━━━━━━━━

    🧾 *Jumlah Transaksi*
    {len(data)}

    📥 *Pemasukan*
    Rp {masuk_hari_ini:,.0f}

    📤 *Pengeluaran*
    Rp {keluar_hari_ini:,.0f}

    ━━━━━━━━━━━━━━

    💰 *Total Aktivitas*
    Rp {total:,.0f}
    {viewer_info}
    ━━━━━━━━━━━━━━

    _ChatSaku Finance Assistant_
    """
        )

        return jsonify({"status": True})

    # =========================
    # BUDGET
    # =========================
    if cmd.startswith("budget"):

        nomor = get_owner_number(sender)

        if not has_feature(sender, "budget"):

            kirim_wa(sender,
    """
    🔒 Fitur Budget hanya tersedia pada paket PRO dan PREMIUM.

    Upgrade sekarang agar dapat:

    ✅ Budget Bulanan
    ✅ Reminder
    ✅ AI Insight
    ✅ Dashboard Lengkap

            """)

            return jsonify(status=True)

        try:

            parts = message.lower().split()

            # =========================
            # LIHAT BUDGET
            # =========================
            if len(parts) == 1:

                periode = periode_sekarang()

                budgets = Budget.query.filter_by(
                    nomor_wa=nomor,
                    periode=periode
                ).order_by(
                    Budget.kategori.asc()
                ).all()

                if not budgets:

                    kirim_wa(
                        sender,
                        "📭 Belum ada budget bulan ini.\n\n"
                        "Contoh:\n"
                        "budget makanan 1500000"
                    )

                    return jsonify({"status": True})

                pesan = f"🎯 *Budget Bulan {periode}*\n"
                pesan += "━━━━━━━━━━━━━━\n\n"

                total_budget = 0
                total_terpakai = 0

                for b in budgets:

                    total_budget += b.nominal

                    now = sekarang()

                    awal_bulan = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

                    if now.month == 12:
                        akhir_bulan = now.replace(year=now.year + 1, month=1, day=1,
                                                hour=0, minute=0, second=0, microsecond=0)
                    else:
                        akhir_bulan = now.replace(month=now.month + 1, day=1,
                                                hour=0, minute=0, second=0, microsecond=0)

                    # =============================
                    # TOTAL PENGELUARAN KATEGORI BULAN INI
                    # =============================
                    terpakai = transaksi_user(nomor).filter(
                        Transaksi.tipe == "KELUAR",
                        Transaksi.kategori == b.kategori,
                        Transaksi.tanggal >= awal_bulan,
                        Transaksi.tanggal < akhir_bulan
                    ).with_entities(
                        db.func.sum(Transaksi.nominal)
                    ).scalar() or 0

                    total_terpakai += terpakai

                    persen = (
                        (terpakai / b.nominal) * 100
                        if b.nominal > 0 else 0
                    )

                    sisa = b.nominal - terpakai

                    blok = min(10, int(persen / 10))

                    progress = (
                        "🟩" * blok +
                        "⬜" * (10 - blok)
                    )

                    if persen < 50:
                        status = "🟢 Aman"

                    elif persen < 80:
                        status = "🟡 Waspada"

                    elif persen <= 100:
                        status = "🟠 Hampir Habis"

                    else:
                        status = "🔴 Terlampaui"

                    pesan += (
                        f"📂 *{b.kategori.title()}*\n"
                        f"💰 Budget   : Rp {b.nominal:,.0f}\n"
                        f"📉 Terpakai : Rp {terpakai:,.0f}\n"
                        f"💵 Sisa     : Rp {max(sisa,0):,.0f}\n"
                        f"📊 {persen:.1f}%\n"
                        f"{progress}\n"
                        f"{status}\n\n"
                    )

                pesan += "━━━━━━━━━━━━━━\n"

                total_persen = (
                    (total_terpakai / total_budget) * 100
                    if total_budget > 0 else 0
                )

                blok = min(10, int(total_persen / 10))

                progress = (
                    "🟩" * blok +
                    "⬜" * (10 - blok)
                )

                pesan += (
                    f"💼 *TOTAL BUDGET*\n\n"
                    f"💰 Budget   : Rp {total_budget:,.0f}\n"
                    f"📉 Terpakai : Rp {total_terpakai:,.0f}\n"
                    f"💵 Sisa     : Rp {max(total_budget-total_terpakai,0):,.0f}\n\n"
                    f"📊 {total_persen:.1f}%\n"
                    f"{progress}"
                )

                kirim_wa(sender, pesan)

                return jsonify({"status": True})

            if is_viewer(sender):

                kirim_wa(
                    sender,
                    """🔒 Mode Viewer

            Anda hanya dapat melihat Budget.

            Perubahan Budget hanya dapat dilakukan oleh Owner."""
                )

                return jsonify(status=True)

            # =========================
            # FORMAT
            # =========================
            if len(parts) < 3:

                kirim_wa(
                    sender,
                    "Format:\n"
                    "budget makanan 1500000"
                )

                return jsonify({"status":True})

            kategori = parts[1].lower()

            # =========================
            # VALIDASI KATEGORI
            # =========================
            if kategori not in KATEGORI.keys():

                daftar = "\n".join(
                    f"• {x.title()}"
                    for x in KATEGORI.keys()
                )

                kirim_wa(
                    sender,
                    f"""❌ Kategori tidak tersedia.

Kategori:

{daftar}

Contoh:
budget makanan 1500000
"""
                )

                return jsonify({"status":True})

            nominal = normalize_nominal(parts[2])

            if nominal <= 0:

                kirim_wa(
                    sender,
                    "Nominal budget harus lebih dari 0."
                )

                return jsonify(status=True)

            periode = periode_sekarang()

            # =========================
            # VALIDASI SALDO
            # =========================

            # Hitung saldo saat ini
            saldo = hitung_saldo(nomor)

            # Budget yang sudah ada (jika edit)
            budget_lama = Budget.query.filter_by(
                nomor_wa=nomor,
                kategori=kategori,
                periode=periode
            ).first()

            # Total budget bulan ini
            total_budget = db.session.query(
                db.func.coalesce(
                    db.func.sum(Budget.nominal),
                    0
                )
            ).filter(
                Budget.nomor_wa == nomor,
                Budget.periode == periode
            ).scalar()

            # Jika sedang mengubah budget,
            # kurangi budget lama agar tidak dihitung dua kali
            if budget_lama:
                total_budget -= budget_lama.nominal

            total_setelah = total_budget + nominal

            # Tidak boleh melebihi saldo
            if total_setelah > saldo:

                sisa = max(saldo - total_budget, 0)

                kirim_wa(
                    sender,
                    f"""⚠️ *Budget Tidak Dapat Dibuat*
━━━━━━━━━━━━━━

💰 Saldo Anda
Rp {saldo:,.0f}

📊 Total Budget Setelah Disimpan
Rp {total_setelah:,.0f}

❌ Budget melebihi saldo yang tersedia.

Sisa budget yang masih bisa dibuat:

💵 Rp {sisa:,.0f}

Silakan kurangi nominal budget atau tambahkan saldo terlebih dahulu.
"""
                )

                return jsonify({"status": True})

            budget = Budget.query.filter_by(
                nomor_wa=nomor,
                kategori=kategori,
                periode=periode
            ).first()

            if budget:

                budget.nominal = nominal

                status = "Diperbarui"

            else:

                budget = Budget(
                    nomor_wa=sender,
                    kategori=kategori,
                    nominal=nominal,
                    periode=periode
                )

                db.session.add(budget)

                status = "Dibuat"

            db.session.commit()

            kirim_wa(
                sender,
                f"""🎯 *Budget {status}*
━━━━━━━━━━━━━━

📂 Kategori
{kategori.title()}

💰 Budget
Rp {nominal:,.0f}

📅 Periode
{periode}

━━━━━━━━━━━━━━

Ketik *budget*
untuk melihat semua budget.
"""
            )

        except Exception as e:

            print(e)

            kirim_wa(
                sender,
                f"Terjadi kesalahan.\n\n{e}"
            )

        return jsonify({"status":True})

    # =========================
    # AI INSIGHT
    # =========================
    if cmd == "insight":

        from utils.ai_insight import generate_ai_insight

        if not has_feature(sender, "ai"):

            kirim_wa(
                sender,
                """🔒 *Fitur AI Insight* hanya tersedia pada paket PREMIUM.

    Upgrade sekarang untuk menikmati:

    ✅ Budget Bulanan
    ✅ Reminder
    ✅ Target Tabungan
    ✅ Hutang Piutang
    ✅ AI Finance Insight
    ✅ Dashboard Lengkap
    """
            )

            return jsonify(status=True)

        try:

            nomor = get_owner_number(sender)

            insight = generate_ai_insight(nomor)

            viewer_info = ""

            if nomor != sender:
                viewer_info = (
                    "👁 *Mode Viewer*\n"
                    "Analisis ini menggunakan data Owner.\n\n"
                )

            pesan = f"""🏦 *AI Finance Insight*
    ──────────────────

    {viewer_info}🧠 *Analisis AI*

    """

            for item in insight:
                pesan += f"• {item}\n"

            pesan += """

    ──────────────────
    _ChatSaku Finance Assistant_
    💚 AI Powered • WhatsApp Finance
    """

            kirim_wa(sender, pesan)

        except Exception as e:

            print(e)

            kirim_wa(
                sender,
                f"Terjadi kesalahan\n\n{e}"
            )

        return jsonify(status=True)

    # =========================
    # REMINDER
    # =========================
    if cmd.startswith("reminder"):
        if not has_feature(sender, "reminder"):

            kirim_wa(
                sender,
                "🔒 Reminder tersedia di paket PRO."
            )

            return jsonify(status=True)

        try:
            nomor = get_owner_number(sender)

            parts = message.lower().split()

            # =========================
            # LIHAT REMINDER
            # =========================
            if len(parts) == 1:

                reminders = Reminder.query.filter_by(
                    nomor_wa=nomor,
                    aktif=True
                ).order_by(
                    Reminder.tanggal.asc()
                ).all()

                if not reminders:

                    kirim_wa(
                        sender,
                        "📭 Belum ada reminder.\n\n"
                        "Contoh:\n"
                        "reminder listrik 20 500000"
                    )

                    return jsonify({"status": True})

                pesan = "🔔 *Reminder Tagihan*\n"
                pesan += "━━━━━━━━━━━━━━\n\n"

                total = 0

                for r in reminders:

                    total += r.nominal

                    pesan += (
                        f"📄 {r.nama.title()}\n"
                        f"📅 Tanggal : {r.tanggal}\n"
                        f"💰 Rp {r.nominal:,.0f}\n\n"
                    )

                pesan += "━━━━━━━━━━━━━━\n"
                pesan += f"💵 Total Tagihan\nRp {total:,.0f}"

                kirim_wa(sender, pesan)

                return jsonify({"status": True})

            if is_viewer(sender):

                kirim_wa(
                    sender,
                    """🔒 Mode Viewer

            Anda hanya dapat melihat Reminder.

            Perubahan Reminder hanya dapat dilakukan oleh Owner."""
                )

                return jsonify(status=True)

            # =========================
            # FORMAT
            # =========================
            if len(parts) < 4:

                kirim_wa(
                    sender,
                    "Format:\n"
                    "reminder listrik 20 500000"
                )

                return jsonify({"status": True})

            nama = parts[1]

            tanggal = int(parts[2])

            nominal = normalize_nominal(parts[3])

            if nominal is None:
                kirim_wa(sender, "Nominal reminder tidak valid.")
                return jsonify(status=True)

            if tanggal < 1 or tanggal > 31:

                kirim_wa(
                    sender,
                    "Tanggal harus antara 1-31."
                )

                return jsonify({"status": True})

            reminder = Reminder.query.filter_by(
                nomor_wa=sender,
                nama=nama
            ).first()

            if reminder:

                reminder.tanggal = tanggal
                reminder.nominal = nominal
                reminder.aktif = True

                status = "Diperbarui"

            else:

                reminder = Reminder(

                    nomor_wa=sender,

                    nama=nama,

                    tanggal=tanggal,

                    nominal=nominal

                )

                db.session.add(reminder)

                status = "Dibuat"

            db.session.commit()

            kirim_wa(
                sender,
                f"""🔔 *Reminder {status}*
━━━━━━━━━━━━━━

📄 Tagihan
{nama.title()}

📅 Jatuh Tempo
Tanggal {tanggal}

💰 Estimasi
Rp {nominal:,.0f}

━━━━━━━━━━━━━━

Ketik *reminder*
untuk melihat seluruh reminder.
"""
            )

        except Exception as e:

            print(e)

            kirim_wa(
                sender,
                str(e)
            )

        return jsonify({"status": True})

    # =========================
    # HAPUS REMINDER
    # =========================
    if cmd.startswith("hapusreminder"):

        if not has_feature(sender, "hapusreminder"):

            kirim_wa(sender,
    """
    🔒 Fitur Reminder hanya tersedia pada paket PRO dan PREMIUM.

    Upgrade sekarang agar dapat:

    ✅ Budget Bulanan
    ✅ Reminder
    ✅ Target Tabungan
    ✅ Hutang Piutang
    ✅ AI Insight
    ✅ Dashboard Lengkap

            """)

            return jsonify(status=True)

        try:

            parts = message.lower().split()

            if len(parts) < 2:

                kirim_wa(
                    sender,
                    "Format:\n"
                    "hapusreminder listrik"
                )

                return jsonify({"status": True})

            nama = parts[1]

            reminder = Reminder.query.filter_by(
                nomor_wa=sender,
                nama=nama
            ).first()

            if not reminder:

                kirim_wa(
                    sender,
                    "Reminder tidak ditemukan."
                )

                return jsonify({"status": True})

            db.session.delete(reminder)

            db.session.commit()

            kirim_wa(
                sender,
                f"""🗑️ Reminder berhasil dihapus

    📄 {nama.title()}
    """
            )

        except Exception as e:

            print(e)

            kirim_wa(
                sender,
                str(e)
            )

        return jsonify({"status": True})

    # =========================
    # HUTANG LIHAT
    # =========================

    if cmd == "hutang":

        if not has_feature(sender, "hutang"):

            kirim_wa(sender,
    """
    🔒 Fitur hutang hanya tersedia pada paket PREMIUM.

    Upgrade sekarang agar dapat:

    ✅ Budget Bulanan
    ✅ Reminder
    ✅ Target Tabungan
    ✅ Hutang Piutang
    ✅ AI Insight
    ✅ Dashboard Lengkap

            """)

            return jsonify(status=True)

        daftar = HutangPiutang.query.filter(
            HutangPiutang.nomor_wa == sender,
            HutangPiutang.tipe == "HUTANG"
        ).order_by(
            HutangPiutang.tanggal.desc()
        ).all()


        if not daftar:

            kirim_wa(
                sender,
                """💳 *Daftar Hutang*

    Belum ada data hutang.

    🤖 ChatSaku Finance"""
            )

            return jsonify(status=True)



        total = 0

        pesan = """💳 *Daftar Hutang*

    """


        for i, h in enumerate(daftar,1):

            status = (
                "✅ LUNAS"
                if h.status == "LUNAS"
                else "⏳ BELUM LUNAS"
            )


            pesan += f"""
    {i}. 👤 {h.nama}
    💰 Rp {h.nominal:,.0f}
    📌 {status}
    📝 {h.keterangan or "-"}

    """


            if h.status != "LUNAS":
                total += h.nominal



        pesan += f"""
    ━━━━━━━━━━━━━━
    Total Aktif:
    💰 Rp {total:,.0f}

    _ChatSaku Finance Assistant_
    """


        kirim_wa(
            sender,
            pesan
        )

        return jsonify(status=True)


    # =========================
    # TAMBAH HUTANG
    # =========================

    if cmd.startswith("hutang "):

        if not has_feature(sender, "hutang"):

            kirim_wa(sender,
    """
    🔒 Fitur hutang hanya tersedia pada paket PREMIUM.

    Upgrade sekarang agar dapat:

    ✅ Budget Bulanan
    ✅ Reminder
    ✅ Target Tabungan
    ✅ Hutang Piutang
    ✅ AI Insight
    ✅ Dashboard Lengkap

            """)

            return jsonify(status=True)

        data = message.split(" ", 3)

        if len(data) < 3:

            kirim_wa(
                sender,
                """❌ Format salah

    Contoh:

    hutang budi 500000 pinjam uang"""
            )

            return jsonify(status=True)


        nama = data[1]


        try:

            nominal = normalize_nominal(data[2])

        except:

            kirim_wa(
                sender,
                "❌ Nominal harus angka"
            )

            return jsonify(status=True)



        keterangan = ""

        if len(data) == 4:
            keterangan = data[3]



        hp = HutangPiutang(

            nomor_wa = sender,

            tipe = "HUTANG",

            nama = nama,

            nominal = nominal,

            status = "AKTIF",

            keterangan = keterangan

        )


        db.session.add(hp)

        db.session.commit()



        kirim_wa(
            sender,
            f"""✅ *Hutang Dicatat*

    👤 {nama}
    💰 Rp {nominal:,.0f}

    📝 {keterangan or "-"}

    Status:
    ⏳ BELUM LUNAS

    _ChatSaku Finance Assistant_"""
        )


        return jsonify(status=True)



    # =========================
    # LIHAT PIUTANG
    # =========================

    if cmd == "piutang":

        if not has_feature(sender, "piutang"):

            kirim_wa(sender,
    """
    🔒 Fitur Piutang hanya tersedia pada paket PREMIUM.

    Upgrade sekarang agar dapat:

    ✅ Budget Bulanan
    ✅ Reminder
    ✅ Target Tabungan
    ✅ Hutang Piutang
    ✅ AI Insight
    ✅ Dashboard Lengkap

            """)

            return jsonify(status=True)

        daftar = HutangPiutang.query.filter(
            HutangPiutang.nomor_wa == sender,
            HutangPiutang.tipe == "PIUTANG",
            HutangPiutang.status != "LUNAS"
        ).all()


        if not daftar:

            kirim_wa(
                sender,
                """📥 *Daftar Piutang*

    Tidak ada piutang aktif 😊

    _ChatSaku Finance Assistant_"""
            )

            return jsonify(status=True)



        total = 0


        pesan = """📥 *Daftar Piutang Aktif*

    """


        for i, p in enumerate(daftar, 1):

            jumlah = p.nominal or 0

            pesan += f"""
    {i}. 👤 {p.nama}
    💰 Rp {jumlah:,.0f}
    📝 {p.keterangan or "-"}
    """


            total += jumlah



        pesan += f"""
    ━━━━━━━━━━━━━━
    Total Piutang:
    💰 Rp {total:,.0f}

    _ChatSaku Finance Assistant_
    """


        kirim_wa(
            sender,
            pesan
        )


        return jsonify(status=True)

    # =========================
    # TAMBAH PIUTANG
    # =========================

    if cmd.startswith("piutang "):

        if not has_feature(sender, "piutang"):

            kirim_wa(sender,
    """
    🔒 Fitur Piutang hanya tersedia pada paket PREMIUM.

    Upgrade sekarang agar dapat:

    ✅ Budget Bulanan
    ✅ Reminder
    ✅ Target Tabungan
    ✅ Hutang Piutang
    ✅ AI Insight
    ✅ Dashboard Lengkap

            """)

            return jsonify(status=True)

        data = message.split(" ", 3)


        if len(data) < 3:

            kirim_wa(
                sender,
                """❌ Format Piutang salah

    Gunakan:

    piutang nama nominal keterangan

    Contoh:
    piutang agus 300000 makan bersama"""
            )

            return jsonify(status=True)



        nama = data[1]


        try:

            nominal = normalize_nominal(data[2])

        except:

            kirim_wa(
                sender,
                "❌ Nominal harus berupa angka."
            )

            return jsonify(status=True)



        keterangan = ""

        if len(data) == 4:
            keterangan = data[3]



        hp = HutangPiutang(

            nomor_wa=sender,

            tipe="PIUTANG",

            nama=nama,

            nominal=nominal,

            status="AKTIF",

            keterangan=keterangan

        )


        db.session.add(hp)

        db.session.commit()



        kirim_wa(
            sender,
            f"""✅ *Piutang Dicatat*

    👤 {nama}
    💰 Rp {nominal:,.0f}

    📝 {keterangan or "-"}

    Status:
    ⏳ BELUM DIBAYAR

    _ChatSaku Finance Assistant_"""
        )


        return jsonify(status=True)

    # =========================
    # BAYAR PIUTANG
    # =========================

    if cmd.startswith("bayarpiutang"):

        if not has_feature(sender, "piutang"):

            kirim_wa(sender,
    """
    🔒 Fitur Piutang hanya tersedia pada paket PREMIUM.

    Upgrade sekarang agar dapat:

    ✅ Budget Bulanan
    ✅ Reminder
    ✅ Target Tabungan
    ✅ Hutang Piutang
    ✅ AI Insight
    ✅ Dashboard Lengkap

            """)

            return jsonify(status=True)

        data = message.split(" ",1)


        if len(data)<2:

            kirim_wa(
                sender,
                """❌ Format salah

    Gunakan:

    bayarpiutang nama

    Contoh:
    bayarpiutang agus"""
            )

            return jsonify(status=True)



        nama=data[1].strip()



        piutang = HutangPiutang.query.filter(
            HutangPiutang.nomor_wa == sender,
            HutangPiutang.tipe == "PIUTANG",
            HutangPiutang.nama.ilike(nama),
            HutangPiutang.status != "LUNAS"
        ).first()



        if not piutang:

            kirim_wa(
                sender,
                f"""❌ Piutang {nama} tidak ditemukan"""
            )

            return jsonify(status=True)



        piutang.status="LUNAS"

        piutang.lunas_tanggal=sekarang()


        db.session.commit()



        kirim_wa(
            sender,
            f"""✅ *Piutang Diterima*

    👤 {piutang.nama}

    💰 Rp {piutang.nominal:,.0f}

    Status:
    ✅ SUDAH DIBAYAR

    🕒 {sekarang().strftime("%d %b %Y %H:%M")}

    _ChatSaku Finance Assistant_"""
        )


        return jsonify(status=True)

    # =========================
    # BAYAR HUTANG
    # =========================

    if cmd.startswith("bayarhutang"):

        if not has_feature(sender, "hutang"):

            kirim_wa(sender,
    """
    🔒 Fitur hutang hanya tersedia pada paket PREMIUM.

    Upgrade sekarang agar dapat:

    ✅ Budget Bulanan
    ✅ Reminder
    ✅ Target Tabungan
    ✅ Hutang Piutang
    ✅ AI Insight
    ✅ Dashboard Lengkap

            """)

            return jsonify(status=True)

        data = message.split(" ", 1)


        if len(data) < 2:

            kirim_wa(
                sender,
                """❌ Format salah

    Gunakan:

    bayarhutang nama

    Contoh:
    bayarhutang budi"""
            )

            return jsonify(status=True)



        nama = data[1].strip()



        hutang = HutangPiutang.query.filter(
            HutangPiutang.nomor_wa == sender,
            HutangPiutang.tipe == "HUTANG",
            HutangPiutang.nama.ilike(nama),
            HutangPiutang.status != "LUNAS"
        ).first()



        if not hutang:

            kirim_wa(
                sender,
                f"""❌ Hutang {nama} tidak ditemukan

    Pastikan nama sesuai."""
            )

            return jsonify(status=True)



        hutang.status = "LUNAS"
        hutang.lunas_tanggal = sekarang()


        db.session.commit()



        kirim_wa(
            sender,
            f"""✅ *Hutang Lunas*

    👤 {hutang.nama}

    💰 Rp {hutang.nominal:,.0f}

    Status:
    ✅ SUDAH LUNAS

    🕒 {sekarang().strftime("%d %b %Y %H:%M")}

    _ChatSaku Finance Assistant_"""
        )


        return jsonify(status=True)

    # =========================
    # DASHBOARD
    # =========================

    if cmd == "dashboard":

        nomor = get_owner_number(sender)

        link = generate_dashboard_link(nomor)

        mode = ""

        if nomor != sender:
            mode = (
                "\n👁 *Mode Viewer*\n"
                "Anda sedang melihat dashboard milik Owner.\n"
            )

        kirim_wa(
            sender,
            f"""📊 *Dashboard ChatSaku*

    Akses Dashboard:

    {link}

    {mode}
    Fitur:

    💰 Saldo
    📥 Pemasukan
    📤 Pengeluaran
    📈 Grafik
    💳 Hutang Piutang
    🎯 Target Tabungan
    🤖 AI Insight

    ⏳ Link berlaku 30 menit.

    _ChatSaku Finance Assistant_"""
        )

        return jsonify(status=True)

    # ==========================
    # MENU
    # ==========================
    if cmd in ["menu", "fitur", "help"]:

        kirim_wa(
            sender,
    f"""🤖 *ChatSaku Finance Assistant*

Selamat datang di *ChatSaku* 💚
Kelola seluruh keuangan langsung dari WhatsApp.
Cepat • Praktis • Tanpa Install Aplikasi

━━━━━━━━━━━━━━━━━━
💰 *TRANSAKSI*

➕ masuk 500000 Gaji
➖ keluar 25000 Makan Siang

Mencatat pemasukan & pengeluaran hanya dengan chat.

━━━━━━━━━━━━━━━━━━
💳 *KEUANGAN*

• saldo
   Melihat saldo terbaru.

• hariini
   Ringkasan transaksi hari ini.

• dashboard
   Membuka Dashboard Web secara realtime.

━━━━━━━━━━━━━━━━━━
📊 *BUDGET BULANAN*

• budget
   Melihat seluruh budget.

• budget makanan 1500000
   Membuat atau mengubah budget.

━━━━━━━━━━━━━━━━━━
🎯 *TARGET TABUNGAN*

• target
   Daftar target tabungan.

• target laptop 12000000 31-12-2026
   Membuat target baru.

• target laptop
   Melihat detail target.

• tabung laptop 500000
   Menambah tabungan.

• hapustarget laptop
   Menghapus target.

━━━━━━━━━━━━━━━━━━
🔔 *REMINDER TAGIHAN*

• reminder
   Daftar reminder.

• reminder listrik 20 500000
   Membuat reminder baru.

• hapusreminder listrik
   Menghapus reminder.

━━━━━━━━━━━━━━━━━━
🤝 *HUTANG & PIUTANG*

• hutang
   Daftar hutang.

• hutang Budi 500000 Pinjam uang
   Menambah hutang.

• bayarhutang Budi
   Melunasi hutang.

• piutang
   Daftar piutang.

• piutang Andi 300000 Pinjam modal
   Menambah piutang.

• bayarpiutang Andi
   Menandai piutang sudah dibayar.

━━━━━━━━━━━━━━━━━━
📈 *LAPORAN & ANALISIS*

• insight
   AI Finance Insight.

• statistik
   Statistik keuangan.

• excel
   Export laporan Excel.

• pdf
   Export laporan PDF.

━━━━━━━━━━━━━━━━━━
👥 *MULTI USER*

• viewer
   Daftar pengguna Viewer.

• share 08123456789
   Menambahkan Viewer.

• unshare 08123456789
   Menghapus Viewer.

━━━━━━━━━━━━━━━━━━
⚙️ *AKUN*

• paket
   Melihat paket yang aktif.

• fitur
   Daftar seluruh fitur ChatSaku.

• help
   Menampilkan bantuan.

━━━━━━━━━━━━━━━━━━
👑 *FITUR PREMIUM*

✨ Dashboard Web Realtime
✨ AI Finance Insight
✨ Budget Bulanan
✨ Reminder Tagihan
✨ Target Tabungan
✨ Hutang & Piutang
✨ Export Excel
✨ Export PDF
✨ Multi User & Viewer
✨ Laporan Harian Otomatis

━━━━━━━━━━━━━━━━━━
🌐 Website
https://chatsaku.com

📊 Dashboard
https://dashboard.chatsaku.com

💚 *ChatSaku Finance Assistant*

✔️ 100% melalui WhatsApp
✔️ Tanpa Install Aplikasi
✔️ Dashboard Web Realtime
✔️ AI Powered Financial Assistant
✔️ Aman & Terenkripsi

_Kelola keuangan lebih mudah, lebih cerdas, dan lebih praktis bersama ChatSaku._
"""
        )

        return jsonify(status=True)

    if cmd.startswith("share "):

        if not has_feature(sender, "share"):

            kirim_wa(
                sender,
                "🔒 Fitur Multi User tersedia pada paket PREMIUM."
            )

            return jsonify(status=True)

        args = message.split()[1:]

        if len(args) < 1:

            kirim_wa(
                sender,
                "Format:\n\nshare 081234567890"
            )

            return jsonify(status=True)

        nomor = normalize_wa(args[0])

        if nomor == sender:

            kirim_wa(
                sender,
                "❌ Tidak bisa membagikan akun ke nomor sendiri."
            )

            return jsonify(status=True)

        cek = SharedAccess.query.filter_by(
            owner=sender,
            member=nomor,
            aktif=True
        ).first()

        if cek:

            kirim_wa(
                sender,
                "Nomor tersebut sudah menjadi viewer."
            )

            return jsonify(status=True)

        db.session.add(

            SharedAccess(

                owner=sender,

                member=nomor

            )

        )

        db.session.commit()

        kirim_wa(
            sender,
            f"""✅ Viewer berhasil ditambahkan

    👤 {nomor}

    Nomor tersebut sekarang dapat melihat dashboard dan laporan Anda."""
        )

        return jsonify(status=True)

    if cmd.startswith("unshare "):

        if not has_feature(sender, "share"):

            kirim_wa(
                sender,
                "🔒 Fitur Multi User tersedia pada paket PREMIUM."
            )

            return jsonify(status=True)

        args = message.split()[1:]

        if len(args) < 1:

            kirim_wa(
                sender,
                "Format:\n\nunshare 081234567890"
            )

            return jsonify(status=True)

        nomor = normalize_wa(args[0])

        akses = SharedAccess.query.filter_by(
            owner=sender,
            member=nomor,
            aktif=True
        ).first()

        if not akses:

            kirim_wa(
                sender,
                "❌ Nomor tersebut bukan Viewer Anda."
            )

            return jsonify(status=True)

        akses.aktif = False

        db.session.commit()

        kirim_wa(
            sender,
            f"""✅ Viewer berhasil dihapus

    👤 {nomor}

    Nomor tersebut tidak lagi memiliki akses ke dashboard dan laporan Anda."""
        )

        return jsonify(status=True)

    if cmd == "viewer":

        if not has_feature(sender, "share"):

            kirim_wa(
                sender,
                "🔒 Fitur Multi User tersedia pada paket PREMIUM."
            )

            return jsonify(status=True)

        data = SharedAccess.query.filter_by(
            owner=sender,
            aktif=True
        ).all()

        if not data:

            kirim_wa(
                sender,
                "📭 Belum ada Viewer yang ditambahkan."
            )

            return jsonify(status=True)

        pesan = "👥 *DAFTAR VIEWER*\n"
        pesan += "━━━━━━━━━━━━━━\n\n"

        for i, item in enumerate(data, 1):

            pesan += f"{i}. {item.member}\n"

        pesan += (
            "\n━━━━━━━━━━━━━━\n"
            "Gunakan:\n"
            "unshare <nomor>\n"
            "untuk menghapus Viewer."
        )

        kirim_wa(sender, pesan)

        return jsonify(status=True)

    # ======================================
    # DETEKSI GAMBAR STRUK
    # ======================================

    image_url = (
        payload.get("image")
        or payload.get("media")
        or payload.get("url")
        or payload.get("file")
    )

    filename = str(payload.get("filename") or "").lower()

    is_image = (
        bool(image_url)
        or filename.endswith((".jpg", ".jpeg", ".png", ".webp"))
    )

    if is_image:

        try:

            hasil = proses_struk_chatgpt(
                sender=sender,
                image_url=image_url
            )

            if not hasil["success"]:

                kirim_wa(
                    sender,
                    "❌ Maaf, struk tidak dapat dibaca. Coba kirim foto yang lebih jelas."
                )

                return jsonify(status=True)

            for item in hasil["items"]:

                trx = Transaksi(
                    nomor_wa=sender,
                    tipe="keluar",
                    nominal=item["harga"],
                    kategori=item.get("kategori", "Belanja"),
                    subkategori="OCR Struk",
                    keterangan=f'{hasil["merchant"]} - {item["nama"]}'
                )

                db.session.add(trx)

            db.session.commit()

            text = f"""🧾 *Struk Berhasil Diproses*

    🏪 {hasil["merchant"]}

    📅 {hasil["tanggal"]}

    💰 Total
    Rp {hasil["total"]:,}

    📦 Item : {len(hasil["items"])}

    Semua transaksi telah disimpan ke ChatSaku ✅"""

            kirim_wa(sender, text)

        except Exception as e:

            print(e)

            kirim_wa(
                sender,
                "❌ Terjadi kesalahan saat membaca struk."
            )

        return jsonify(status=True)

    # =========================
    # DEFAULT
    # =========================
    return jsonify({
        "status": True
    })

