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
from routes.nlp_router import parse_message
import re

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

# ============================================================
# ============================================================
# CHATSAKU - TARGET & TABUNG NLP SYSTEM
# ============================================================
#
# SUPPORT:
#
# TARGET:
#   target
#   target saya
#   saya punya target apa
#   saya punya target apa saja
#   lihat target
#   target motor
#   detail target motor
#   cek target motor
#   hapus target motor
#
# CREATE TARGET:
#   target laptop 12000000 31-12-2026
#   saya ingin menabung laptop 30 juta sampai 20-12-2026
#   saya mau menabung motor 25 juta sampai 31-12-2026
#
# TABUNG:
#   tabung laptop 500000
#   tabung laptop 500 ribu
#   nabung motor 1 juta
#   saya mau menabung motor 5000000
#
# ============================================================
# ============================================================


# ============================================================
# HELPER PARSE NOMINAL
# ============================================================

def _parse_nominal_chat_saku(value):

    if value is None:
        return None

    try:

        # Sudah angka
        if isinstance(value, (int, float)):

            value = int(float(value))

            if value > 0:
                return value

            return None

        text = str(value).strip().lower()

        if not text:
            return None

        # Hapus Rp
        text = re.sub(
            r'^rp\s*',
            '',
            text,
            flags=re.IGNORECASE
        ).strip()

        # ====================================================
        # SATUAN
        # ====================================================

        match = re.fullmatch(
            r'(\d+(?:[.,]\d+)?)\s*'
            r'(juta|jt|ribu|rb|miliar|milyar)',
            text,
            re.IGNORECASE
        )

        if match:

            angka_text = match.group(1)
            satuan = match.group(2).lower()

            angka_text = angka_text.replace(',', '.')

            angka = float(angka_text)

            if satuan in ("ribu", "rb"):

                return int(
                    angka * 1000
                )

            if satuan in ("juta", "jt"):

                return int(
                    angka * 1000000
                )

            if satuan in ("miliar", "milyar"):

                return int(
                    angka * 1000000000
                )

        # ====================================================
        # ANGKA BIASA
        # ====================================================

        return normalize_nominal(text)

    except Exception as e:

        print(
            "❌ ERROR PARSE NOMINAL CHATSAKU:",
            repr(e)
        )

        return None

# ============================================================
# DETEKSI REMINDER NLP
# ============================================================

def deteksi_reminder_nlp(message, data=None):

    if not message:
        return None

    text = str(message).strip()
    text_lower = re.sub(
        r'\s+',
        ' ',
        text.lower()
    ).strip()

    if data is None:
        data = {}

    # ========================================================
    # ACTION LIST
    # ========================================================

    pola_list = [

        r'^reminder$',

        r'^list\s+reminder$',
        r'^list\s+reminder\s+saya$',

        r'^daftar\s+reminder$',
        r'^daftar\s+reminder\s+saya$',

        r'^lihat\s+reminder$',
        r'^lihat\s+reminder\s+saya$',

        r'^cek\s+reminder$',
        r'^cek\s+reminder\s+saya$',

        r'^reminder\s+saya$',
        r'^reminder\s+saya\s+apa$',
        r'^reminder\s+saya\s+apa\s+saja$',

        r'^saya\s+punya\s+reminder$',
        r'^saya\s+punya\s+reminder\s+apa$',
        r'^saya\s+punya\s+reminder\s+apa\s+saja$',

        r'^apa\s+reminder\s+saya$',
        r'^apa\s+reminder\s+saya\s+saja$',

        r'^reminder\s+apa$',
        r'^reminder\s+apa\s+saja$'
    ]

    for pola in pola_list:

        if re.search(
            pola,
            text_lower,
            re.IGNORECASE
        ):

            return {
                "intent": "reminder",
                "action": "list",
                "nama": None,
                "tanggal": None,
                "nominal": None
            }

    # ========================================================
    # ACTION DELETE
    # ========================================================

    pola_delete = [

        r'^hapus\s+reminder\s+(.+)$',

        r'^hapuskan\s+reminder\s+(.+)$',

        r'^hapusreminder\s+(.+)$',

        r'^hapus\s+reminder\s*:\s*(.+)$'
    ]

    for pola in pola_delete:

        match = re.search(
            pola,
            text_lower,
            re.IGNORECASE
        )

        if match:

            nama = match.group(1).strip()

            return {
                "intent": "reminder",
                "action": "delete",
                "nama": nama,
                "tanggal": None,
                "nominal": None
            }

    # ========================================================
    # CREATE REMINDER
    # ========================================================

    pola_create = [

        r'^reminder\s+',

        r'^buat\s+reminder\s+',

        r'^buatkan\s+reminder\s+',

        r'^tambah\s+reminder\s+',

        r'^set\s+reminder\s+',

        r'^saya\s+ingin\s+reminder\s+',

        r'^saya\s+mau\s+reminder\s+'
    ]

    ada_create = any(
        re.search(
            pola,
            text_lower,
            re.IGNORECASE
        )
        for pola in pola_create
    )

    # ========================================================
    # NLP UTAMA
    #
    # Kalau NLP sudah mengatakan reminder,
    # tetapi bukan list/delete, anggap CREATE.
    # ========================================================

    if data.get("intent") == "reminder":

        ada_list_word = any(
            kata in text_lower
            for kata in [
                "list reminder",
                "daftar reminder",
                "lihat reminder",
                "cek reminder",
                "reminder saya",
                "punya reminder",
                "reminder apa"
            ]
        )

        if ada_list_word:

            return {
                "intent": "reminder",
                "action": "list",
                "nama": None,
                "tanggal": None,
                "nominal": None
            }

        if not ada_create:

            ada_create = True

    if not ada_create:
        return None

    # ========================================================
    # NAMA
    # ========================================================

    nama = text

    # Hapus prefix
    nama = re.sub(
        r'^buatkan\s+reminder\s+',
        '',
        nama,
        flags=re.IGNORECASE
    )

    nama = re.sub(
        r'^buat\s+reminder\s+',
        '',
        nama,
        flags=re.IGNORECASE
    )

    nama = re.sub(
        r'^tambah\s+reminder\s+',
        '',
        nama,
        flags=re.IGNORECASE
    )

    nama = re.sub(
        r'^set\s+reminder\s+',
        '',
        nama,
        flags=re.IGNORECASE
    )

    nama = re.sub(
        r'^reminder\s+',
        '',
        nama,
        flags=re.IGNORECASE
    )

    nama = re.sub(
        r'^saya\s+(ingin|mau)\s+reminder\s+',
        '',
        nama,
        flags=re.IGNORECASE
    )

    # ========================================================
    # TANGGAL
    # ========================================================

    tanggal = None

    match_tanggal = re.search(
        r'\b(?:tanggal|tgl|tanggl)?\s*(\d{1,2})\b',
        nama,
        re.IGNORECASE
    )

    if match_tanggal:

        try:

            kandidat = int(
                match_tanggal.group(1)
            )

            if 1 <= kandidat <= 31:

                tanggal = kandidat

                nama = re.sub(
                    r'\b(?:tanggal|tgl|tanggl)?\s*'
                    + str(kandidat)
                    + r'\b',
                    '',
                    nama,
                    count=1,
                    flags=re.IGNORECASE
                )

        except Exception:
            tanggal = None

    # ========================================================
    # NOMINAL
    # ========================================================

    nominal = None

    pola_uang = re.search(
        r'(\d+(?:[.,]\d+)?)\s*'
        r'(juta|jt|ribu|rb|miliar|milyar)\b',
        nama,
        re.IGNORECASE
    )

    if pola_uang:

        try:

            angka = float(
                pola_uang.group(1).replace(
                    ",",
                    "."
                )
            )

            satuan = (
                pola_uang.group(2)
                .lower()
            )

            if satuan in (
                "ribu",
                "rb"
            ):

                nominal = int(
                    angka * 1000
                )

            elif satuan in (
                "juta",
                "jt"
            ):

                nominal = int(
                    angka * 1000000
                )

            elif satuan in (
                "miliar",
                "milyar"
            ):

                nominal = int(
                    angka * 1000000000
                )

            # Hapus nominal dari nama
            nama = re.sub(
                re.escape(
                    pola_uang.group(0)
                ),
                '',
                nama,
                count=1,
                flags=re.IGNORECASE
            )

        except Exception as e:

            print(
                "❌ ERROR PARSE NOMINAL REMINDER:",
                repr(e)
            )

    # ========================================================
    # FALLBACK NOMINAL ANGKA BIASA
    # ========================================================

    if not nominal:

        angka_list = re.findall(
            r'(?:rp\s*)?[\d.,]+',
            nama,
            re.IGNORECASE
        )

        if angka_list:

            for angka_text in reversed(
                angka_list
            ):

                try:

                    kandidat = normalize_nominal(
                        angka_text
                    )

                    if kandidat and kandidat > 0:

                        nominal = kandidat

                        nama = nama.replace(
                            angka_text,
                            '',
                            1
                        )

                        break

                except Exception:
                    pass

    # ========================================================
    # BERSIHKAN NAMA
    # ========================================================

    nama = re.sub(
        r'\b(tanggal|tgl)\b',
        '',
        nama,
        flags=re.IGNORECASE
    )

    nama = re.sub(
        r'\s+',
        ' ',
        nama
    ).strip()

    # Hapus kata penghubung di ujung
    nama = re.sub(
        r'\b(sebesar|rp)\b',
        '',
        nama,
        flags=re.IGNORECASE
    ).strip()

    return {
        "intent": "reminder",
        "action": "create",
        "nama": nama or None,
        "tanggal": tanggal,
        "nominal": nominal
    }


    # ============================================================
    # NORMALISASI REMINDER NLP
    #
    # LETAKKAN SETELAH NLP UTAMA
    # DAN SEBELUM HANDLER REMINDER
    # ============================================================

    reminder_nlp = deteksi_reminder_nlp(
        message,
        nlp
    )

    print("========================================")
    print("🔔 REMINDER NLP")
    print("MESSAGE :", message)
    print("RESULT  :", reminder_nlp)
    print("========================================")


    if reminder_nlp:

        nlp["intent"] = "reminder"

        nlp["action"] = reminder_nlp.get(
            "action"
        )

        nlp["nama"] = reminder_nlp.get(
            "nama"
        )

        nlp["tanggal"] = reminder_nlp.get(
            "tanggal"
        )

        nlp["nominal"] = reminder_nlp.get(
            "nominal"
        )

        intent = "reminder"

        print("🔔 INTENT REMINDER DINORMALISASI")

        print(
            "ACTION  :",
            nlp.get("action")
        )

        print(
            "NAMA    :",
            nlp.get("nama")
        )

        print(
            "TANGGAL :",
            nlp.get("tanggal")
        )

        print(
            "NOMINAL :",
            nlp.get("nominal")
        )


    # ============================================================
    # HANDLER REMINDER
    # ============================================================

    if intent == "reminder":

        # ========================================================
        # CEK FITUR
        # ========================================================

        if not has_feature(
            sender,
            "reminder"
        ):

            kirim_wa(
                sender,
                "🔒 Reminder tersedia di paket PRO."
            )

            return jsonify(
                status=True
            )

        action = nlp.get(
            "action"
        )

        nomor_owner = get_owner_number(
            sender
        )

        print("========================================")
        print("🔔 PROSES REMINDER")
        print("SENDER  :", sender)
        print("OWNER   :", nomor_owner)
        print("ACTION  :", action)
        print("NAMA    :", nlp.get("nama"))
        print("TANGGAL :", nlp.get("tanggal"))
        print("NOMINAL :", nlp.get("nominal"))
        print("========================================")


        # ========================================================
        # LIST REMINDER
        # ========================================================

        if action == "list":

            reminders = Reminder.query.filter_by(
                nomor_wa=nomor_owner,
                aktif=True
            ).order_by(
                Reminder.tanggal.asc()
            ).all()

            if not reminders:

                kirim_wa(
                    sender,
                    """🔔 *REMINDER*

    📭 Belum ada reminder.

    Contoh membuat reminder:

    *reminder listrik tanggal 20 500 ribu*

    _ChatSaku Finance Assistant_"""
                )

                return jsonify({
                    "status": True,
                    "intent": "reminder",
                    "action": "list"
                })

            pesan = (
                "🔔 *DAFTAR REMINDER*\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
            )

            if nomor_owner != sender:

                pesan += (
                    "👁 *Mode Viewer*\n"
                    "Data reminder milik owner akun.\n\n"
                )

            total = 0

            for i, r in enumerate(
                reminders,
                1
            ):

                nominal_reminder = (
                    r.nominal or 0
                )

                total += nominal_reminder

                pesan += (
                    f"*{i}. {str(r.nama).title()}*\n\n"
                    f"📅 Jatuh Tempo : "
                    f"Tanggal {r.tanggal}\n"
                    f"💰 Nominal : "
                    f"Rp {nominal_reminder:,.0f}\n\n"
                    "━━━━━━━━━━━━━━━━━━\n\n"
                )

            pesan += (
                f"💵 *Total Reminder*\n"
                f"Rp {total:,.0f}\n\n"
                "_ChatSaku Finance Assistant_"
            )

            kirim_wa(
                sender,
                pesan
            )

            return jsonify({
                "status": True,
                "intent": "reminder",
                "action": "list"
            })


        # ========================================================
        # DELETE REMINDER
        # ========================================================

        if action == "delete":

            if not has_feature(
                sender,
                "hapusreminder"
            ):

                kirim_wa(
                    sender,
                    """🔒 *Fitur Hapus Reminder tersedia pada paket PRO dan PREMIUM.*

    Upgrade sekarang untuk mengelola reminder.

    🌐 www.chatsaku.com"""
                )

                return jsonify(
                    status=True
                )

            if is_viewer(sender):

                kirim_wa(
                    sender,
                    """🔒 *Mode Viewer*

    Anda hanya dapat melihat Reminder.

    Perubahan Reminder hanya dapat dilakukan oleh Owner."""
                )

                return jsonify(
                    status=True
                )

            nama = nlp.get(
                "nama"
            )

            if not nama:

                kirim_wa(
                    sender,
                    """❌ *Nama reminder belum ditemukan.*

    Contoh:

    *hapus reminder listrik*

    atau:

    *hapusreminder listrik*"""
                )

                return jsonify(
                    status=True
                )

            nama = str(
                nama
            ).strip()

            reminder = Reminder.query.filter_by(
                nomor_wa=nomor_owner,
                aktif=True
            ).all()

            reminder_found = None

            nama_lower = nama.lower()

            for item in reminder:

                if (
                    str(
                        item.nama
                    ).strip().lower()
                    == nama_lower
                ):

                    reminder_found = item
                    break

            if not reminder_found:

                kirim_wa(
                    sender,
                    f"""❌ *Reminder tidak ditemukan.*

    🔔 Reminder:
    *{nama}*

    Gunakan:

    *reminder*

    untuk melihat semua reminder.

    _ChatSaku Finance Assistant_"""
                )

                return jsonify(
                    status=True
                )

            nama_reminder = (
                reminder_found.nama
            )

            # Soft delete
            reminder_found.aktif = False

            db.session.commit()

            kirim_wa(
                sender,
                f"""🗑️ *Reminder Berhasil Dihapus*

    🔔 Reminder:
    *{nama_reminder}*

    Reminder sudah tidak aktif.

    _ChatSaku Finance Assistant_"""
            )

            return jsonify({
                "status": True,
                "intent": "reminder",
                "action": "delete",
                "nama": nama_reminder
            })


        # ========================================================
        # CREATE REMINDER
        # ========================================================

        if action == "create":

            if is_viewer(sender):

                kirim_wa(
                    sender,
                    """🔒 *Mode Viewer*

    Anda hanya dapat melihat Reminder.

    Perubahan Reminder hanya dapat dilakukan oleh Owner."""
                )

                return jsonify(
                    status=True
                )

            nama = nlp.get(
                "nama"
            )

            tanggal = nlp.get(
                "tanggal"
            )

            nominal = nlp.get(
                "nominal"
            )

            # ====================================================
            # VALIDASI NAMA
            # ====================================================

            if not nama:

                kirim_wa(
                    sender,
                    """❌ *Nama reminder belum ditemukan.*

    Contoh:

    *reminder listrik tanggal 20 500 ribu*

    *reminder internet tanggal 10 350 ribu*"""
                )

                return jsonify(
                    status=True
                )

            # ====================================================
            # VALIDASI TANGGAL
            # ====================================================

            try:

                tanggal = int(
                    tanggal
                )

            except (
                ValueError,
                TypeError
            ):

                tanggal = 0

            if tanggal < 1 or tanggal > 31:

                kirim_wa(
                    sender,
                    """❌ *Tanggal reminder belum ditemukan atau tidak valid.*

    Tanggal harus antara *1 sampai 31*.

    Contoh:

    *reminder listrik tanggal 20 500 ribu*"""
                )

                return jsonify(
                    status=True
                )

            # ====================================================
            # VALIDASI NOMINAL
            # ====================================================

            try:

                nominal = normalize_nominal(
                    nominal
                )

            except Exception:

                nominal = None

            if not nominal or nominal <= 0:

                kirim_wa(
                    sender,
                    """❌ *Nominal reminder belum ditemukan.*

    Contoh:

    *reminder listrik tanggal 20 500 ribu*

    *reminder internet tanggal 10 350 ribu*"""
                )

                return jsonify(
                    status=True
                )

            # ====================================================
            # NORMALISASI NAMA
            # ====================================================

            nama = str(
                nama
            ).strip()

            nama = re.sub(
                r'\s+',
                ' ',
                nama
            ).strip()

            # ====================================================
            # CARI REMINDER
            # ====================================================

            reminder = Reminder.query.filter_by(
                nomor_wa=nomor_owner,
                aktif=True
            ).all()

            reminder_found = None

            nama_lower = nama.lower()

            for item in reminder:

                if (
                    str(
                        item.nama
                    ).strip().lower()
                    == nama_lower
                ):

                    reminder_found = item
                    break

            # ====================================================
            # UPDATE
            # ====================================================

            if reminder_found:

                reminder_found.tanggal = tanggal

                reminder_found.nominal = nominal

                reminder_found.aktif = True

                status_text = "Diperbarui"

            # ====================================================
            # CREATE
            # ====================================================

            else:

                reminder_found = Reminder(

                    nomor_wa=nomor_owner,

                    nama=nama,

                    tanggal=tanggal,

                    nominal=nominal,

                    aktif=True
                )

                db.session.add(
                    reminder_found
                )

                status_text = "Dibuat"

            try:

                db.session.commit()

            except Exception as e:

                db.session.rollback()

                print(
                    "❌ ERROR SAVE REMINDER:",
                    repr(e)
                )

                kirim_wa(
                    sender,
                    """❌ *Gagal menyimpan reminder.*

    Silakan coba kembali beberapa saat lagi.

    _ChatSaku Finance Assistant_"""
                )

                return jsonify(
                    status=False
                ), 500

            # ====================================================
            # RESPONSE
            # ====================================================

            kirim_wa(
                sender,
                f"""🔔 *Reminder {status_text}*

    ━━━━━━━━━━━━━━━━━━

    📄 *Tagihan*
    {nama.title()}

    📅 *Jatuh Tempo*
    Tanggal {tanggal}

    💰 *Estimasi*
    Rp {nominal:,.0f}

    ━━━━━━━━━━━━━━━━━━

    Ketik:

    *reminder*

    untuk melihat seluruh reminder.

    _ChatSaku Finance Assistant_"""
            )

            return jsonify({
                "status": True,
                "intent": "reminder",
                "action": "create",
                "nama": nama,
                "tanggal": tanggal,
                "nominal": nominal
            })


        # ========================================================
        # ACTION TIDAK DIKENALI
        # ========================================================

        kirim_wa(
            sender,
            """❌ *Perintah reminder tidak dikenali.*

    Contoh:

    🔔 *reminder*
    🔔 *list reminder saya*
    🔔 *saya punya reminder apa aja*

    ➕ *reminder listrik tanggal 20 500 ribu*

    🗑️ *hapus reminder listrik*

    _ChatSaku Finance Assistant_"""
        )

        return jsonify(
            status=True
        )

# ============================================================
# TARGET & TABUNG NLP - FINAL
# ============================================================

import re
from datetime import datetime, date


# ============================================================
# HELPER: PARSE NOMINAL
# ============================================================

def parse_nominal_finance(text):
    """
    Mendukung:

    500000
    5.000.000
    Rp 5.000.000
    500 ribu
    500 rb
    5 juta
    5 jt
    1,5 juta
    1.5 juta
    1 miliar
    """

    if not text:
        return None

    text = str(text).lower().strip()

    # --------------------------------------------------------
    # NOMINAL DENGAN SATUAN
    # --------------------------------------------------------

    pola_uang = re.search(
        r'(?:rp\s*)?'
        r'(\d+(?:[.,]\d+)?)\s*'
        r'(juta|jt|ribu|rb|miliar|milyar)\b',
        text,
        re.IGNORECASE
    )

    if pola_uang:

        try:

            angka_text = pola_uang.group(1)
            satuan = pola_uang.group(2).lower()

            # Indonesia:
            # 1,5 juta = 1.5 juta
            angka_float = float(
                angka_text.replace(",", ".")
            )

            if satuan in ("ribu", "rb"):

                return int(
                    angka_float * 1_000
                )

            if satuan in ("juta", "jt"):

                return int(
                    angka_float * 1_000_000
                )

            if satuan in ("miliar", "milyar"):

                return int(
                    angka_float * 1_000_000_000
                )

        except Exception as e:

            print(
                "❌ ERROR PARSE NOMINAL SATUAN:",
                repr(e)
            )

    # --------------------------------------------------------
    # NOMINAL ANGKA BIASA
    # --------------------------------------------------------

    angka_list = re.findall(
        r'(?:rp\s*)?[\d.,]+',
        text,
        re.IGNORECASE
    )

    if not angka_list:
        return None

    for angka_text in reversed(angka_list):

        # Jangan ambil tanggal
        if re.fullmatch(
            r'\d{1,2}[-/.]\d{1,2}[-/.]\d{4}',
            angka_text
        ):
            continue

        try:

            hasil = normalize_nominal(
                angka_text
            )

            if hasil and hasil > 0:
                return int(hasil)

        except Exception as e:

            print(
                "❌ ERROR NORMALIZE NOMINAL:",
                repr(e)
            )

    return None


# ============================================================
# HELPER: PARSE DEADLINE
# ============================================================

def parse_deadline_finance(text):

    if not text:
        return None

    match = re.search(
        r'\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b',
        str(text)
    )

    if not match:
        return None

    try:

        return datetime.strptime(
            f"{match.group(1)}-"
            f"{match.group(2)}-"
            f"{match.group(3)}",
            "%d-%m-%Y"
        ).date()

    except Exception as e:

        print(
            "❌ ERROR PARSE DEADLINE:",
            repr(e)
        )

        return None


# ============================================================
# CLEAN TARGET NAME
# ============================================================

def clean_target_name(text):

    if not text:
        return None

    nama = str(text).strip()

    # ========================================================
    # HAPUS DEADLINE
    # ========================================================

    nama = re.sub(
        r'\b\d{1,2}[-/.]\d{1,2}[-/.]\d{4}\b',
        '',
        nama,
        flags=re.IGNORECASE
    )

    # ========================================================
    # HAPUS NOMINAL SATUAN
    # ========================================================

    nama = re.sub(
        r'\b\d+(?:[.,]\d+)?\s*'
        r'(?:juta|jt|ribu|rb|miliar|milyar)\b',
        '',
        nama,
        flags=re.IGNORECASE
    )

    # ========================================================
    # HAPUS NOMINAL ANGKA BIASA
    # ========================================================

    nama = re.sub(
        r'(?:rp\s*)?[\d.,]+',
        '',
        nama,
        flags=re.IGNORECASE
    )

    # ========================================================
    # HAPUS KATA PEMBUKA
    # URUTAN DARI PALING PANJANG
    # ========================================================

    pola_hapus = [

        # saya ingin membuat target laptop
        r'^saya\s+ingin\s+membuat\s+target\s+',

        # saya mau membuat target laptop
        r'^saya\s+mau\s+membuat\s+target\s+',

        # saya ingin buat target laptop
        r'^saya\s+ingin\s+buat\s+target\s+',

        # saya mau buat target laptop
        r'^saya\s+mau\s+buat\s+target\s+',

        # ingin membuat target laptop
        r'^ingin\s+membuat\s+target\s+',

        # mau membuat target laptop
        r'^mau\s+membuat\s+target\s+',

        # buatkan target tabungan laptop
        r'^buatkan\s+target\s+tabungan\s+',

        # buatkan target laptop
        r'^buatkan\s+target\s+',

        # buat target tabungan laptop
        r'^buat\s+target\s+tabungan\s+',

        # buat target laptop
        r'^buat\s+target\s+',

        # bikin target tabungan laptop
        r'^bikin\s+target\s+tabungan\s+',

        # bikin target laptop
        r'^bikin\s+target\s+',

        # saya ingin menabung untuk laptop
        r'^saya\s+ingin\s+menabung\s+untuk\s+',

        # saya mau menabung untuk laptop
        r'^saya\s+mau\s+menabung\s+untuk\s+',

        # saya ingin menabung laptop
        r'^saya\s+ingin\s+menabung\s+',

        # saya mau menabung laptop
        r'^saya\s+mau\s+menabung\s+',

        # ingin menabung untuk laptop
        r'^ingin\s+menabung\s+untuk\s+',

        # mau menabung untuk laptop
        r'^mau\s+menabung\s+untuk\s+',

        # ingin menabung laptop
        r'^ingin\s+menabung\s+',

        # mau menabung laptop
        r'^mau\s+menabung\s+',

        # menabung untuk laptop
        r'^menabung\s+untuk\s+',

        # nabung untuk laptop
        r'^nabung\s+untuk\s+',

        # saya ingin beli laptop
        r'^saya\s+ingin\s+beli\s+',

        # saya mau beli laptop
        r'^saya\s+mau\s+beli\s+',

        # ingin beli laptop
        r'^ingin\s+beli\s+',

        # mau beli laptop
        r'^mau\s+beli\s+',

        # target untuk beli laptop
        r'^target\s+untuk\s+beli\s+',

        # target beli laptop
        r'^target\s+beli\s+',

        # target tabungan laptop
        r'^target\s+tabungan\s+',

        # target menabung laptop
        r'^target\s+menabung\s+',

        # target laptop
        r'^target\s+',

        # tabung laptop
        r'^tabung\s+',

        # nabung laptop
        r'^nabung\s+',

        # menabung laptop
        r'^menabung\s+'
    ]

    for pola in pola_hapus:

        nama = re.sub(
            pola,
            '',
            nama,
            count=1,
            flags=re.IGNORECASE
        )

    # ========================================================
    # HAPUS KATA PENGHUBUNG
    # ========================================================

    nama = re.sub(
        r'\b(sampai|hingga|tanggal|tgl|sebesar|dengan)\b',
        '',
        nama,
        flags=re.IGNORECASE
    )

    # ========================================================
    # NORMALISASI SPASI
    # ========================================================

    nama = re.sub(
        r'\s+',
        ' ',
        nama
    ).strip()

    # ========================================================
    # HAPUS PUNCTUATION DI AWAL / AKHIR
    # ========================================================

    nama = nama.strip(
        " ,.-:;|"
    )

    return nama or None


# ============================================================
# DETEKSI TABUNG NLP
# ============================================================

def deteksi_tabung_nlp(message, data=None):

    if not message:
        return None

    text = str(message).strip()
    text_lower = text.lower()

    if data is None:
        data = {}

    # ========================================================
    # JIKA NLP UTAMA SUDAH MENGENALI TABUNG
    # ========================================================

    if data.get("intent") == "tabung":

        nominal = parse_nominal_finance(text)

        if not nominal:
            nominal = data.get("nominal")

        nama = data.get("nama")

        if not nama:
            nama = data.get("keterangan")

        if not nama:
            nama = clean_target_name(text)

        return {
            "intent": "tabung",
            "action": "add",
            "nama": clean_target_name(nama),
            "nominal": nominal
        }

    # ========================================================
    # DETEKSI POLA TABUNG
    # ========================================================

    pola_tabung = [

        r'^tabung\b',

        r'^nabung\b',

        r'^menabung\b',

        r'^saya\s+tabung\b',

        r'^saya\s+nabung\b',

        r'^saya\s+menabung\b',

        r'^saya\s+ingin\s+menabung\b',

        r'^saya\s+mau\s+menabung\b',

        r'^ingin\s+menabung\b',

        r'^mau\s+menabung\b'
    ]

    terdeteksi = any(
        re.search(
            pola,
            text_lower,
            re.IGNORECASE
        )
        for pola in pola_tabung
    )

    if not terdeteksi:
        return None

    # ========================================================
    # DEADLINE
    #
    # Kalau ada deadline, JANGAN dianggap tambah tabungan.
    # Akan diproses oleh deteksi_target_nlp().
    # ========================================================

    deadline = parse_deadline_finance(
        text
    )

    if deadline:

        return None

    # ========================================================
    # NOMINAL
    # ========================================================

    nominal = parse_nominal_finance(
        text
    )

    # ========================================================
    # NAMA
    # ========================================================

    nama = clean_target_name(
        text
    )

    return {

        "intent": "tabung",

        "action": "add",

        "nama": nama,

        "nominal": nominal

    }


# ============================================================
# DETEKSI TARGET TABUNGAN NLP
# ============================================================

def deteksi_target_nlp(message, data=None):

    if not message:
        return None

    text = str(message).strip()

    text_lower = re.sub(
        r'\s+',
        ' ',
        text.lower()
    ).strip()

    if data is None:
        data = {}

    # ========================================================
    # HELPER
    # ========================================================

    def parse_target_deadline(value):

        try:
            return parse_deadline_finance(value)
        except Exception:
            pass

        # fallback manual
        match = re.search(
            r'\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b',
            str(value)
        )

        if match:

            try:

                return datetime.strptime(
                    f"{match.group(1)}-"
                    f"{match.group(2)}-"
                    f"{match.group(3)}",
                    "%d-%m-%Y"
                ).date()

            except Exception:
                return None

        return None


    def parse_target_nominal(value):

        if not value:
            return None

        value = str(value).strip()

        # ====================================================
        # PENTING:
        #
        # HAPUS TANGGAL DULU
        #
        # Supaya:
        #
        # 500000000 31-12-2026
        #
        # tidak menjadi:
        #
        # 2026
        # ====================================================

        value_without_date = re.sub(
            r'\b\d{1,2}[-/.]\d{1,2}[-/.]\d{4}\b',
            ' ',
            value
        )

        value_without_date = re.sub(
            r'\s+',
            ' ',
            value_without_date
        ).strip()

        # ====================================================
        # NOMINAL SATUAN
        #
        # 30 juta
        # 30 jt
        # 500 ribu
        # 500 rb
        # 1 miliar
        # ====================================================

        match = re.search(
            r'(\d+(?:[.,]\d+)?)\s*'
            r'(juta|jt|ribu|rb|miliar|milyar)\b',
            value_without_date,
            re.IGNORECASE
        )

        if match:

            try:

                angka = float(
                    match.group(1).replace(",", ".")
                )

                satuan = (
                    match.group(2)
                    .lower()
                )

                if satuan in (
                    "ribu",
                    "rb"
                ):

                    return int(
                        angka * 1000
                    )

                if satuan in (
                    "juta",
                    "jt"
                ):

                    return int(
                        angka * 1000000
                    )

                if satuan in (
                    "miliar",
                    "milyar"
                ):

                    return int(
                        angka * 1000000000
                    )

            except Exception as e:

                print(
                    "❌ ERROR PARSE NOMINAL TARGET SATUAN:",
                    repr(e)
                )

        # ====================================================
        # NOMINAL ANGKA BIASA
        #
        # 500000000
        # Rp 500000000
        # 12.000.000
        # ====================================================

        angka = re.findall(
            r'(?:rp\s*)?[\d.,]+',
            value_without_date,
            re.IGNORECASE
        )

        if angka:

            # Ambil angka terakhir yang valid
            # tetapi tanggal sudah dibuang

            for angka_text in reversed(angka):

                try:

                    kandidat = normalize_nominal(
                        angka_text
                    )

                    if kandidat and kandidat > 0:

                        return int(
                            kandidat
                        )

                except Exception:
                    pass

        return None


    def extract_target_name(value):

        nama = str(
            value or ""
        ).strip()

        # ====================================================
        # HAPUS DEADLINE
        # ====================================================

        nama = re.sub(
            r'\b\d{1,2}[-/.]\d{1,2}[-/.]\d{4}\b',
            ' ',
            nama
        )

        # ====================================================
        # HAPUS NOMINAL SATUAN
        # ====================================================

        nama = re.sub(
            r'\b\d+(?:[.,]\d+)?\s*'
            r'(?:juta|jt|ribu|rb|miliar|milyar)\b',
            ' ',
            nama,
            flags=re.IGNORECASE
        )

        # ====================================================
        # HAPUS NOMINAL ANGKA
        # ====================================================

        nama = re.sub(
            r'(?:rp\s*)?[\d.,]+',
            ' ',
            nama,
            flags=re.IGNORECASE
        )

        # ====================================================
        # HAPUS KATA PEMBUKA TARGET
        # ====================================================

        pola_hapus = [

            # target
            r'^target\s+tabungan\s+',
            r'^target\s+menabung\s+',
            r'^target\s+untuk\s+beli\s+',
            r'^target\s+beli\s+',
            r'^target\s+',

            # buat target
            r'^buatkan\s+target\s+tabungan\s+',
            r'^buatkan\s+target\s+',
            r'^buat\s+target\s+tabungan\s+',
            r'^buat\s+target\s+',

            # bikin target
            r'^bikin\s+target\s+tabungan\s+',
            r'^bikin\s+target\s+',

            # saya ingin
            r'^saya\s+ingin\s+menabung\s+untuk\s+',
            r'^saya\s+ingin\s+menabung\s+',
            r'^saya\s+mau\s+menabung\s+untuk\s+',
            r'^saya\s+mau\s+menabung\s+',

            # ingin
            r'^ingin\s+menabung\s+untuk\s+',
            r'^ingin\s+menabung\s+',
            r'^mau\s+menabung\s+untuk\s+',
            r'^mau\s+menabung\s+',

            # menabung
            r'^menabung\s+untuk\s+',
            r'^nabung\s+untuk\s+',

            # beli
            r'^saya\s+ingin\s+beli\s+',
            r'^saya\s+mau\s+beli\s+',
            r'^ingin\s+beli\s+',
            r'^mau\s+beli\s+',

            # generic
            r'^untuk\s+',
            r'^buat\s+'
        ]

        for pola in pola_hapus:

            nama = re.sub(
                pola,
                '',
                nama,
                flags=re.IGNORECASE
            )

        # ====================================================
        # HAPUS KATA PENGHUBUNG
        # ====================================================

        nama = re.sub(
            r'\b(sampai|hingga|tanggal|tgl|sebesar|dengan)\b',
            ' ',
            nama,
            flags=re.IGNORECASE
        )

        # ====================================================
        # RAPKAN
        # ====================================================

        nama = re.sub(
            r'\s+',
            ' ',
            nama
        ).strip()

        # ====================================================
        # HAPUS KARAKTER ANEH DI AWAL/AKHIR
        # ====================================================

        nama = re.sub(
            r'^[\s\-_:,]+|[\s\-_:,]+$',
            '',
            nama
        ).strip()

        return nama or None


    # ========================================================
    # ACTION LIST
    # ========================================================

    pola_list = [

        r'\btarget saya apa\b',
        r'\btarget saya apa saja\b',

        r'\bapa target saya\b',
        r'\bapa saja target saya\b',

        r'\bsaya punya target apa\b',
        r'\bsaya punya target apa saja\b',

        r'\bsaya punya list target\b',
        r'\bsaya punya list target apa\b',

        r'\bsaya punya daftar target\b',
        r'\bsaya punya daftar target apa\b',

        r'\blist target\b',
        r'\bdaftar target\b',

        r'\blihat semua target\b',
        r'\blihat target\b',

        r'\bcek semua target\b',
        r'\bcek target\b',

        r'\btarget saya\b',
        r'\btarget tabungan saya\b',
        r'\btabungan saya\b',

        r'\bpunya target apa\b',
        r'\bpunya target apa saja\b'
    ]

    for pola in pola_list:

        if re.search(
            pola,
            text_lower,
            re.IGNORECASE
        ):

            return {
                "intent": "target",
                "action": "list",
                "nama": None,
                "nominal": None,
                "deadline": None
            }


    # ========================================================
    # ACTION DELETE
    #
    # hapus target laptop
    # hapuskan target laptop
    # hapus target tabungan laptop
    # hapustarget laptop
    # ========================================================

    pola_delete = [

        r'^hapus\s+target\s+tabungan\s+(.+)$',

        r'^hapuskan\s+target\s+tabungan\s+(.+)$',

        r'^hapus\s+target\s+(.+)$',

        r'^hapuskan\s+target\s+(.+)$',

        r'^hapustarget\s+(.+)$',

        r'^hapus\s+target\s*:\s*(.+)$'
    ]

    for pola in pola_delete:

        match = re.search(
            pola,
            text_lower,
            re.IGNORECASE
        )

        if match:

            nama = extract_target_name(
                match.group(1)
            )

            return {
                "intent": "target",
                "action": "delete",
                "nama": nama,
                "nominal": None,
                "deadline": None
            }


    # ========================================================
    # DEADLINE
    # ========================================================

    deadline = parse_target_deadline(
        text
    )


    # ========================================================
    # NOMINAL
    # ========================================================

    nominal = parse_target_nominal(
        text
    )


    # ========================================================
    # CREATE TARGET
    #
    # WAJIB ADA DEADLINE
    #
    # Contoh CREATE:
    #
    # buat target jalan-jalan 500000000 31-12-2026
    #
    # saya mau menabung motor 5 juta sampai 31-12-2026
    #
    # ========================================================

    pola_create_target = [

        "target",

        "target tabungan",

        "target menabung",

        "ingin menabung",

        "mau menabung",

        "saya ingin menabung",

        "saya mau menabung",

        "ingin punya",

        "mau punya",

        "ingin beli",

        "mau beli",

        "saya ingin beli",

        "saya mau beli",

        "target beli",

        "target untuk beli",

        "menabung untuk",

        "nabung untuk",

        "buat target",

        "bikin target",

        "buatkan target",

        "buatkan target tabungan"
    ]

    ada_pola_create = any(
        pola in text_lower
        for pola in pola_create_target
    )


    # ========================================================
    # CREATE
    # ========================================================

    if (
        ada_pola_create
        and deadline
    ):

        nama = extract_target_name(
            text
        )

        return {
            "intent": "target",
            "action": "create",
            "nama": nama,
            "nominal": nominal,
            "deadline": deadline
        }


    # ========================================================
    # DETAIL TARGET
    #
    # target laptop
    # detail target laptop
    # cek target laptop
    # lihat target laptop
    # ========================================================

    pola_detail = [

        r'^detail\s+target\s+(.+)$',

        r'^detail\s+(.+)$',

        r'^cek\s+target\s+(.+)$',

        r'^lihat\s+target\s+(.+)$',

        r'^target\s+(.+)$'
    ]

    for pola in pola_detail:

        match = re.search(
            pola,
            text_lower,
            re.IGNORECASE
        )

        if not match:
            continue

        nama = match.group(1).strip()

        # ====================================================
        # JANGAN DETAIL JIKA CREATE
        # ====================================================

        if nominal and deadline:
            continue

        # ====================================================
        # JANGAN AMBIL KALIMAT LIST
        # ====================================================

        if nama in (
            "saya",
            "saya apa",
            "saya apa saja",
            "saya punya",
            "saya punya apa",
            "apa",
            "apa saja"
        ):
            continue

        nama = extract_target_name(
            nama
        )

        if nama:

            return {
                "intent": "target",
                "action": "detail",
                "nama": nama,
                "nominal": None,
                "deadline": None
            }


    # ========================================================
    # FALLBACK NLP UTAMA
    #
    # Jika NLP utama:
    #
    # intent = target
    #
    # tetapi action belum ada.
    # ========================================================

    if data.get("intent") == "target":

        keterangan = str(
            data.get("keterangan") or ""
        ).lower().strip()

        # ====================================================
        # LIST
        # ====================================================

        pola_list_fallback = [

            "target saya",

            "punya target",

            "list target",

            "daftar target",

            "lihat target",

            "cek target",

            "target apa",

            "target apa saja",

            "target saya apa",

            "target saya apa saja"
        ]

        if any(
            kata in text_lower
            for kata in pola_list_fallback
        ):

            return {
                "intent": "target",
                "action": "list",
                "nama": None,
                "nominal": None,
                "deadline": None
            }


        # ====================================================
        # CREATE
        # ====================================================

        if (
            nominal
            and deadline
        ):

            nama = extract_target_name(
                text
            )

            return {
                "intent": "target",
                "action": "create",
                "nama": nama,
                "nominal": nominal,
                "deadline": deadline
            }


    # ========================================================
    # TIDAK TERDETEKSI
    # ========================================================

    return None
# ============================================================
# FALLBACK DETEKSI PEMASUKAN
# ============================================================

def deteksi_pemasukan_nlp(message, data=None):

    if not message:
        return None

    text = message.lower().strip()

    if data is None:
        data = {}

    # ========================================================
    # HASIL NLP YANG SUDAH ADA
    # ========================================================

    intent_nlp = data.get("intent")
    nominal_nlp = data.get("nominal")
    keterangan_nlp = data.get("keterangan")


    # ========================================================
    # CEK APAKAH KALIMAT MENGANDUNG INDIKASI PEMASUKAN
    # ========================================================

    terdeteksi_masuk = False

    for pola in pola_masuk:

        if pola in text:

            terdeteksi_masuk = True
            break

    # ========================================================
    # JIKA NLP SUDAH MENGENALI MASUK
    # ========================================================

    if intent_nlp == "masuk":

        terdeteksi_masuk = True

    # ========================================================
    # JIKA TIDAK TERDETEKSI
    # ========================================================

    if not terdeteksi_masuk:

        return None

    # ========================================================
    # EKSTRAK NOMINAL
    # ========================================================

    nominal = nominal_nlp

    try:

        if nominal:

            nominal = int(
                float(nominal)
            )

        else:

            nominal = 0

    except (
        ValueError,
        TypeError
    ):

        nominal = 0

    # ========================================================
    # CARI ANGKA DALAM PESAN
    # ========================================================

    if nominal <= 0:

        angka = re.findall(
            r'(?:rp\s*)?[\d.,]+',
            text,
            re.IGNORECASE
        )

        if angka:

            kandidat = angka[-1]

            try:

                nominal = normalize_nominal(
                    kandidat
                )

            except Exception:

                nominal = 0

    # ========================================================
    # DUKUNGAN "RIBU", "JUTA", "MILYAR"
    # ========================================================

    if nominal <= 0:

        pola_uang = re.search(
            r'(\d+(?:[.,]\d+)?)\s*'
            r'(juta|jt|ribu|rb|miliar|milyar)',
            text,
            re.IGNORECASE
        )

        if pola_uang:

            angka_text = pola_uang.group(1)
            satuan = pola_uang.group(2).lower()

            try:

                angka_float = float(
                    angka_text.replace(",", ".")
                )

                if satuan in [
                    "ribu",
                    "rb"
                ]:

                    nominal = int(
                        angka_float * 1000
                    )

                elif satuan in [
                    "juta",
                    "jt"
                ]:

                    nominal = int(
                        angka_float * 1000000
                    )

                elif satuan in [
                    "miliar",
                    "milyar"
                ]:

                    nominal = int(
                        angka_float * 1000000000
                    )

            except Exception:

                nominal = 0

    # ========================================================
    # EKSTRAK KETERANGAN
    # ========================================================

    keterangan = keterangan_nlp

    if not keterangan:

        keterangan = message

    keterangan = str(
        keterangan
    ).strip()

    # ========================================================
    # HAPUS NOMINAL DARI AKHIR KETERANGAN
    # ========================================================

    keterangan = re.sub(
        r'\s+(?:rp\s*)?[\d.,]+\s*$',
        '',
        keterangan,
        flags=re.IGNORECASE
    ).strip()

    # ========================================================
    # HAPUS NOMINAL + SATUAN
    # ========================================================

    keterangan = re.sub(
        r'\s+\d+(?:[.,]\d+)?\s*'
        r'(?:juta|jt|ribu|rb|miliar|milyar)\s*$',
        '',
        keterangan,
        flags=re.IGNORECASE
    ).strip()

    if not keterangan:

        keterangan = "Pemasukan"

    # ========================================================
    # HASIL
    # ========================================================

    return {
        "intent": "masuk",
        "action": "create",
        "nominal": nominal,
        "keterangan": keterangan
    }

# ============================================================
# DETEKSI HUTANG / PIUTANG NLP
# ============================================================

def deteksi_hutang_nlp(message, data=None):

    if not message:
        return None

    text = str(message).strip()

    text_lower = re.sub(
        r'\s+',
        ' ',
        text.lower()
    ).strip()

    if data is None:
        data = {}

    # ========================================================
    # LIST HUTANG
    # ========================================================

    pola_list_hutang = [

        r'^hutang$',
        r'^list hutang$',
        r'^daftar hutang$',
        r'^lihat hutang$',
        r'^lihat semua hutang$',
        r'^cek hutang$',
        r'^cek semua hutang$',

        r'^hutang saya$',
        r'^hutang saya apa$',
        r'^hutang saya apa saja$',

        r'^apa hutang saya$',
        r'^apa saja hutang saya$',

        r'^saya punya hutang apa$',
        r'^saya punya hutang apa saja$',

        r'^list hutang saya$',
        r'^daftar hutang saya$',

        r'^lihat daftar hutang$',
        r'^lihat daftar hutang saya$'
    ]

    for pola in pola_list_hutang:

        if re.search(
            pola,
            text_lower,
            re.IGNORECASE
        ):

            return {
                "intent": "hutang",
                "action": "list",
                "nama": None,
                "nominal": None,
                "keterangan": None
            }

    # ========================================================
    # LIST PIUTANG
    # ========================================================

    pola_list_piutang = [

        r'^piutang$',
        r'^list piutang$',
        r'^daftar piutang$',
        r'^lihat piutang$',
        r'^lihat semua piutang$',
        r'^cek piutang$',
        r'^cek semua piutang$',

        r'^piutang saya$',
        r'^piutang saya apa$',
        r'^piutang saya apa saja$',

        r'^apa piutang saya$',
        r'^apa saja piutang saya$',

        r'^saya punya piutang apa$',
        r'^saya punya piutang apa saja$',

        r'^list piutang saya$',
        r'^daftar piutang saya$'
    ]

    for pola in pola_list_piutang:

        if re.search(
            pola,
            text_lower,
            re.IGNORECASE
        ):

            return {
                "intent": "piutang",
                "action": "list",
                "nama": None,
                "nominal": None,
                "keterangan": None
            }

    # ========================================================
    # HAPUS HUTANG
    # ========================================================

    pola_delete_hutang = [

        r'^hapus hutang\s+(.+)$',
        r'^hapuskan hutang\s+(.+)$',
        r'^hapus hutang ke\s+(.+)$',
        r'^hapus hutang dari\s+(.+)$',
        r'^hapusutang\s+(.+)$'
    ]

    for pola in pola_delete_hutang:

        match = re.search(
            pola,
            text_lower,
            re.IGNORECASE
        )

        if match:

            nama = match.group(1).strip()

            nama = re.sub(
                r'^(ke|dari)\s+',
                '',
                nama,
                flags=re.IGNORECASE
            ).strip()

            return {
                "intent": "hutang",
                "action": "delete",
                "nama": nama,
                "nominal": None,
                "keterangan": None
            }

    # ========================================================
    # HAPUS PIUTANG
    # ========================================================

    pola_delete_piutang = [

        r'^hapus piutang\s+(.+)$',
        r'^hapuskan piutang\s+(.+)$',
        r'^hapus piutang dari\s+(.+)$',
        r'^hapuspiutang\s+(.+)$'
    ]

    for pola in pola_delete_piutang:

        match = re.search(
            pola,
            text_lower,
            re.IGNORECASE
        )

        if match:

            nama = match.group(1).strip()

            nama = re.sub(
                r'^(ke|dari)\s+',
                '',
                nama,
                flags=re.IGNORECASE
            ).strip()

            return {
                "intent": "piutang",
                "action": "delete",
                "nama": nama,
                "nominal": None,
                "keterangan": None
            }

    # ========================================================
    # SUDAH BAYAR / LUNAS
    # ========================================================

    pola_lunas_hutang = [

        r'^(.*)\s+sudah bayar$',
        r'^(.*)\s+sudah membayar$',
        r'^(.*)\s+sudah lunas$',
        r'^hutang\s+(.+)\s+sudah bayar$',
        r'^hutang\s+(.+)\s+sudah lunas$',
        r'^tandai hutang\s+(.+)\s+lunas$',
        r'^hutang\s+(.+)\s+lunas$'
    ]

    for pola in pola_lunas_hutang:

        match = re.search(
            pola,
            text_lower,
            re.IGNORECASE
        )

        if match:

            nama = match.group(1).strip()

            nama = re.sub(
                r'^hutang\s+',
                '',
                nama,
                flags=re.IGNORECASE
            ).strip()

            return {
                "intent": "hutang",
                "action": "lunas",
                "nama": nama,
                "nominal": None,
                "keterangan": None
            }

    # ========================================================
    # BUAT HUTANG
    #
    # contoh:
    #
    # hutang ke ucup 20000
    # saya hutang ke budi 500 ribu
    # saya punya hutang ke andi 2 juta
    # hutang budi 500000 pinjam uang
    # ========================================================

    pola_create_hutang = [

        r'^hutang\s+',

        r'^saya\s+hutang\s+',

        r'^saya\s+punya\s+hutang\s+',

        r'^saya\s+berhutang\s+',

        r'^berhutang\s+',

        r'^catat\s+hutang\s+',

        r'^buat\s+hutang\s+'
    ]

    ada_hutang = any(
        re.search(
            pola,
            text_lower,
            re.IGNORECASE
        )
        for pola in pola_create_hutang
    )

    if ada_hutang:

        # ====================================================
        # NOMINAL
        # ====================================================

        nominal = parse_nominal_finance(
            text
        )

        # ====================================================
        # NAMA
        # ====================================================

        nama_text = text_lower

        # hapus nominal
        nama_text = re.sub(
            r'\b\d+(?:[.,]\d+)?\s*'
            r'(?:juta|jt|ribu|rb|miliar|milyar)\b',
            '',
            nama_text,
            flags=re.IGNORECASE
        )

        nama_text = re.sub(
            r'(?:rp\s*)?[\d.,]+',
            '',
            nama_text,
            flags=re.IGNORECASE
        )

        # hapus kata pembuka
        pola_bersih = [

            r'^saya\s+punya\s+hutang\s+',

            r'^saya\s+hutang\s+',

            r'^saya\s+berhutang\s+',

            r'^berhutang\s+',

            r'^catat\s+hutang\s+',

            r'^buat\s+hutang\s+',

            r'^hutang\s+'
        ]

        for pola in pola_bersih:

            nama_text = re.sub(
                pola,
                '',
                nama_text,
                flags=re.IGNORECASE
            )

        # ====================================================
        # HAPUS "KE"
        # ====================================================

        nama_text = re.sub(
            r'^ke\s+',
            '',
            nama_text,
            flags=re.IGNORECASE
        )

        # ====================================================
        # PISAH KETERANGAN
        # ====================================================

        keterangan = ""

        kata_keterangan = [
            "untuk",
            "karena",
            "buat",
            "sebagai"
        ]

        for kata in kata_keterangan:

            match = re.search(
                rf'\b{kata}\b(.+)',
                nama_text,
                re.IGNORECASE
            )

            if match:

                sebelum = nama_text[:match.start()].strip()

                keterangan = match.group(0).strip()

                nama_text = sebelum

                break

        # ====================================================
        # BERSIHKAN
        # ====================================================

        nama_text = re.sub(
            r'\s+',
            ' ',
            nama_text
        ).strip()

        # ====================================================
        # FALLBACK NLP UTAMA
        # ====================================================

        if not nama_text:

            nama_text = str(
                data.get("keterangan") or ""
            ).strip()

        return {

            "intent": "hutang",

            "action": "create",

            "nama": nama_text or None,

            "nominal": nominal,

            "keterangan": keterangan
        }

    # ========================================================
    # FALLBACK DARI NLP UTAMA
    # ========================================================

    if data.get("intent") in (
        "hutang",
        "utang"
    ):

        keterangan = str(
            data.get("keterangan") or ""
        ).strip()

        # -----------------------------------------------
        # LIST
        # -----------------------------------------------

        if any(
            kata in text_lower
            for kata in [
                "list hutang",
                "daftar hutang",
                "lihat hutang",
                "cek hutang",
                "hutang saya",
                "punya hutang apa"
            ]
        ):

            return {
                "intent": "hutang",
                "action": "list",
                "nama": None,
                "nominal": None,
                "keterangan": None
            }

        # -----------------------------------------------
        # CREATE
        # -----------------------------------------------

        nominal = parse_nominal_finance(
            text
        )

        if nominal:

            return {
                "intent": "hutang",
                "action": "create",
                "nama": keterangan,
                "nominal": nominal,
                "keterangan": ""
            }

    return None

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

    # ==========================================
    # NLP CHATSAKU
    # ==========================================

    print("========================================")
    print("🧠 MULAI PARSE NLP")
    print("MESSAGE :", message)
    print("========================================")


    # ============================================================
    # PARSE NLP UTAMA
    # ============================================================

    try:

        nlp = parse_message(
            message
        )

        if not isinstance(
            nlp,
            dict
        ):

            nlp = {
                "intent": None,
                "nominal": None,
                "keterangan": message
            }

        print("========================================")
        print("🧠 PARSE NLP SELESAI")
        print("NLP :", nlp)
        print("========================================")


    except Exception as e:

        print("========================================")
        print("❌ ERROR parse_message()")
        print("MESSAGE :", message)
        print("ERROR   :", repr(e))
        print("========================================")

        nlp = {
            "intent": None,
            "action": None,
            "nama": None,
            "nominal": None,
            "deadline": None,
            "keterangan": message
        }


    # ============================================================
    # PASTIKAN FIELD NLP ADA
    # ============================================================

    if "intent" not in nlp:
        nlp["intent"] = None

    if "action" not in nlp:
        nlp["action"] = None

    if "nama" not in nlp:
        nlp["nama"] = None

    if "nominal" not in nlp:
        nlp["nominal"] = None

    if "deadline" not in nlp:
        nlp["deadline"] = None

    if "keterangan" not in nlp:
        nlp["keterangan"] = message


    # ============================================================
    # NORMALISASI HUTANG NLP
    #
    # INI WAJIB SEBELUM:
    #
    # intent = nlp.get("intent")
    #
    # dan sebelum:
    #
    # if not intent:
    #
    # ============================================================

    print("========================================")
    print("💳 CEK HUTANG NLP")
    print("MESSAGE :", message)
    print("========================================")


    try:

        hutang_nlp = deteksi_hutang_nlp(
            message,
            nlp
        )

    except Exception as e:

        print("========================================")
        print("❌ ERROR deteksi_hutang_nlp()")
        print("ERROR :", repr(e))
        print("========================================")

        hutang_nlp = None


    print("========================================")
    print("💳 HUTANG NLP RESULT")
    print("RESULT :", hutang_nlp)
    print("========================================")


    if hutang_nlp:

        nlp["intent"] = hutang_nlp.get(
            "intent"
        )

        nlp["action"] = hutang_nlp.get(
            "action"
        )

        nlp["nama"] = hutang_nlp.get(
            "nama"
        )

        nlp["nominal"] = hutang_nlp.get(
            "nominal"
        )

        nlp["keterangan"] = hutang_nlp.get(
            "keterangan"
        )

        print("========================================")
        print("💳 HUTANG BERHASIL DINORMALISASI")
        print("INTENT     :", nlp.get("intent"))
        print("ACTION     :", nlp.get("action"))
        print("NAMA       :", nlp.get("nama"))
        print("NOMINAL    :", nlp.get("nominal"))
        print("KETERANGAN :", nlp.get("keterangan"))
        print("========================================")


    # ============================================================
    # NORMALISASI TARGET NLP
    # ============================================================

    print("========================================")
    print("🎯 CEK TARGET NLP")
    print("MESSAGE :", message)
    print("========================================")


    try:

        target_nlp = deteksi_target_nlp(
            message,
            nlp
        )

    except Exception as e:

        print("========================================")
        print("❌ ERROR deteksi_target_nlp()")
        print("ERROR :", repr(e))
        print("========================================")

        target_nlp = None


    print("========================================")
    print("🎯 TARGET NLP RESULT")
    print("RESULT :", target_nlp)
    print("========================================")


    if target_nlp:

        nlp["intent"] = target_nlp.get(
            "intent"
        )

        nlp["action"] = target_nlp.get(
            "action"
        )

        nlp["nama"] = target_nlp.get(
            "nama"
        )

        nlp["nominal"] = target_nlp.get(
            "nominal"
        )

        nlp["deadline"] = target_nlp.get(
            "deadline"
        )

        print("========================================")
        print("🎯 TARGET BERHASIL DINORMALISASI")
        print("INTENT   :", nlp.get("intent"))
        print("ACTION   :", nlp.get("action"))
        print("NAMA     :", nlp.get("nama"))
        print("NOMINAL  :", nlp.get("nominal"))
        print("DEADLINE :", nlp.get("deadline"))
        print("========================================")


    # ============================================================
    # NORMALISASI REMINDER NLP
    # ============================================================

    print("========================================")
    print("🔔 CEK REMINDER NLP")
    print("MESSAGE :", message)
    print("========================================")


    try:

        reminder_nlp = deteksi_reminder_nlp(
            message,
            nlp
        )

    except Exception as e:

        print("========================================")
        print("❌ ERROR deteksi_reminder_nlp()")
        print("ERROR :", repr(e))
        print("========================================")

        reminder_nlp = None


    print("========================================")
    print("🔔 REMINDER NLP RESULT")
    print("RESULT :", reminder_nlp)
    print("========================================")


    if reminder_nlp:

        nlp["intent"] = reminder_nlp.get(
            "intent"
        )

        nlp["action"] = reminder_nlp.get(
            "action"
        )

        nlp["nama"] = reminder_nlp.get(
            "nama"
        )

        nlp["nominal"] = reminder_nlp.get(
            "nominal"
        )

        nlp["tanggal"] = reminder_nlp.get(
            "tanggal"
        )

        nlp["keterangan"] = reminder_nlp.get(
            "keterangan"
        )

        print("========================================")
        print("🔔 REMINDER BERHASIL DINORMALISASI")
        print("INTENT     :", nlp.get("intent"))
        print("ACTION     :", nlp.get("action"))
        print("NAMA       :", nlp.get("nama"))
        print("NOMINAL    :", nlp.get("nominal"))
        print("TANGGAL    :", nlp.get("tanggal"))
        print("KETERANGAN :", nlp.get("keterangan"))
        print("========================================")


    # ============================================================
    # INTENT FINAL
    # ============================================================

    intent = nlp.get(
        "intent"
    )

    action = nlp.get(
        "action"
    )


    print("========================================")
    print("🤖 NLP RESULT FINAL")
    print("TEXT   :", message)
    print("INTENT :", intent)
    print("ACTION :", action)
    print("DATA   :", nlp)
    print("========================================")


    # ============================================================
    # IGNORE NON COMMAND
    #
    # HARUS PALING BAWAH
    # ============================================================

    if not intent:

        print("========================================")
        print("🚫 IGNORE NON COMMAND")
        print("MESSAGE :", message)
        print("INTENT  :", intent)
        print("DATA    :", nlp)
        print("========================================")

        return jsonify(
            status=True
        )


    # ============================================================
    # NLP FALLBACK TRANSAKSI
    # ============================================================
    # Digunakan ketika parse_message() belum mengenali intent.
    #
    # Contoh:
    #
    # saya dapat sumbangan 3000000
    # saya dapat gaji 5000000
    # menerima transfer 750000
    # dapat bonus 1000000
    #
    # akan menjadi:
    #
    # intent  = masuk
    # nominal = 3000000
    # ============================================================

    if not intent:

        text_lower = (
            message or ""
        ).lower().strip()


        # ========================================================
        # POLA PEMASUKAN
        # ========================================================

        pola_masuk = [

            "saya dapat",
            "aku dapat",
            "kami dapat",

            "dapat uang",
            "dapat duit",
            "dapat pemasukan",

            "saya menerima",
            "aku menerima",
            "kami menerima",

            "menerima uang",
            "menerima duit",

            "menerima transfer",
            "terima transfer",

            "dapat transfer",
            "saya dapat transfer",
            "aku dapat transfer",

            "diberi uang",
            "diberi duit",

            "dikasih uang",
            "dikasih duit",

            "dapat kiriman",

            "uang masuk",
            "ada uang masuk",

            "gaji",
            "gajian",

            "bonus",

            "pendapatan",
            "pemasukan",

            "sumbangan",
            "donasi",

            "hasil jual",
            "hasil jualan",
            "hasil penjualan",

            "hasil usaha",
            "hasil dagang",

            "hasil kerja",
            "hasil proyek",

            "dibayar",
            "sudah dibayar",

            "menerima pembayaran",
            "pembayaran diterima",

            "bayaran masuk"

        ]


        # ========================================================
        # DETEKSI PEMASUKAN
        # ========================================================

        terdeteksi_masuk = any(
            pola in text_lower
            for pola in pola_masuk
        )


        # ========================================================
        # JIKA PEMASUKAN
        # ========================================================

        if terdeteksi_masuk:

            nominal = None


            # ====================================================
            # CARI NOMINAL ANGKA
            # ====================================================

            angka = re.findall(
                r'(?:rp\s*)?[\d.,]+',
                text_lower,
                re.IGNORECASE
            )


            if angka:

                try:

                    nominal = normalize_nominal(
                        angka[-1]
                    )

                except Exception as e:

                    print(
                        "❌ ERROR NORMALIZE NOMINAL:",
                        repr(e)
                    )

                    nominal = None


            # ====================================================
            # DUKUNGAN NOMINAL:
            #
            # 3 juta
            # 3 jt
            # 500 ribu
            # 500 rb
            # 1 miliar
            # ====================================================

            if not nominal:

                pola_uang = re.search(
                    r'(\d+(?:[.,]\d+)?)\s*'
                    r'(juta|jt|ribu|rb|miliar|milyar)',
                    text_lower,
                    re.IGNORECASE
                )


                if pola_uang:

                    angka_text = (
                        pola_uang.group(1)
                        .replace(",", ".")
                    )

                    satuan = (
                        pola_uang.group(2)
                        .lower()
                    )


                    try:

                        angka_float = float(
                            angka_text
                        )


                        if satuan in (
                            "ribu",
                            "rb"
                        ):

                            nominal = int(
                                angka_float * 1000
                            )


                        elif satuan in (
                            "juta",
                            "jt"
                        ):

                            nominal = int(
                                angka_float * 1000000
                            )


                        elif satuan in (
                            "miliar",
                            "milyar"
                        ):

                            nominal = int(
                                angka_float * 1000000000
                            )


                    except Exception as e:

                        print(
                            "❌ ERROR PARSING SATUAN:",
                            repr(e)
                        )

                        nominal = None


            # ====================================================
            # JIKA NOMINAL VALID
            # ====================================================

            if nominal and nominal > 0:

                intent = "masuk"


                # =================================================
                # KETERANGAN
                # =================================================

                keterangan = message


                # =================================================
                # HAPUS NOMINAL ANGKA DARI AKHIR
                # =================================================

                keterangan = re.sub(
                    r'\s+(?:rp\s*)?[\d.,]+\s*$',
                    '',
                    keterangan,
                    flags=re.IGNORECASE
                ).strip()


                # =================================================
                # HAPUS NOMINAL SATUAN
                # =================================================

                keterangan = re.sub(
                    r'\s+\d+(?:[.,]\d+)?\s*'
                    r'(?:juta|jt|ribu|rb|miliar|milyar)\s*$',
                    '',
                    keterangan,
                    flags=re.IGNORECASE
                ).strip()


                if not keterangan:

                    keterangan = "Pemasukan"


                # =================================================
                # UPDATE NLP RESULT
                # =================================================

                nlp = {

                    "intent": "masuk",

                    "nominal": nominal,

                    "keterangan": keterangan

                }


                print("========================================")
                print("🤖 NLP FALLBACK")
                print(f"TEXT       : {message}")
                print(f"INTENT     : {intent}")
                print(f"NOMINAL    : {nominal}")
                print(f"KETERANGAN : {keterangan}")
                print(f"DATA       : {nlp}")
                print("========================================")

        # ============================================================
        # DETEKSI TARGET NLP
        # ============================================================

        hasil_target = None

        try:

            hasil_target = deteksi_target_nlp(
                message,
                nlp
            )

        except Exception as e:

            print(
                "❌ ERROR deteksi_target_nlp:",
                repr(e)
            )


        if hasil_target:

            nlp = hasil_target

            intent = "target"

            print("========================================")
            print("🎯 TARGET TERDETEKSI")
            print("TEXT     :", message)
            print("INTENT   :", intent)
            print("NAMA     :", nlp.get("nama"))
            print("NOMINAL  :", nlp.get("nominal"))
            print("DEADLINE :", nlp.get("deadline"))
            print("========================================")

    # ============================================================
    # MAPPING INTENT → COMMAND
    # ============================================================

    if intent:

        if intent == "saldo":

            cmd = "saldo"


        elif intent == "hari_ini":

            cmd = "hari ini"


        elif intent == "dashboard":

            cmd = "dashboard"


        elif intent == "insight":

            cmd = "insight"


        elif intent == "budget":

            cmd = "budget"


        elif intent == "reminder":

            cmd = "reminder"


        elif intent == "hapusreminder":

            cmd = "hapusreminder"


        elif intent == "hutang":

            cmd = "hutang"


        elif intent == "piutang":

            cmd = "piutang"


        elif intent == "bayarhutang":

            cmd = "bayarhutang"


        elif intent == "bayarpiutang":

            cmd = "bayarpiutang"


        elif intent == "target":

            cmd = "target"


        elif intent == "tabung":

            cmd = "tabung"


        elif intent == "help":

            cmd = "help"


        # ========================================================
        # MASUK
        # ========================================================

        elif intent == "masuk":

            cmd = "masuk"


        # ========================================================
        # KELUAR
        # ========================================================

        elif intent == "keluar":

            cmd = "keluar"


    # ============================================================
    # VALID COMMAND
    # ============================================================

    valid_command = (

        intent is not None

        or

        cmd == "saldo"

        or cmd == "hari ini"

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

        or cmd.startswith(
            "halo chatsaku, saya ingin mencoba versi gratis"
        )

        or cmd == "menu"

        or cmd == "fitur"

        or cmd == "help"

        or cmd == "target"

        or cmd.startswith("target ")

        or cmd.startswith("tabung")

        or cmd.startswith("hapustarget")

        or cmd == "hutang"

        or cmd.startswith("hutang ")

        or cmd == "piutang"

        or cmd.startswith("piutang ")

        or cmd.startswith("bayarhutang")

        or cmd.startswith("bayarpiutang")

    )


    # ============================================================
    # IGNORE NON COMMAND
    # HARUS PALING BAWAH
    # ============================================================

    if not valid_command:

        print("========================================")
        print("🚫 IGNORE NON COMMAND")
        print(f"MESSAGE : {message}")
        print(f"INTENT  : {intent}")
        print(f"DATA    : {nlp}")
        print("========================================")

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
    _"menu"_

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

    # ============================================================
    # NORMALISASI INTENT REMINDER NLP
    # ============================================================

    reminder_nlp = deteksi_reminder_nlp(
        message,
        nlp
    )

    print("========================================")
    print("🔔 REMINDER NLP")
    print("MESSAGE :", message)
    print("RESULT  :", reminder_nlp)
    print("========================================")

    if reminder_nlp:

        intent = "reminder"

        nlp["intent"] = "reminder"

        nlp["action"] = reminder_nlp.get(
            "action"
        )

        nlp["nama"] = reminder_nlp.get(
            "nama"
        )

        nlp["tanggal"] = reminder_nlp.get(
            "tanggal"
        )

        nlp["nominal"] = reminder_nlp.get(
            "nominal"
        )

        print("========================================")
        print("🔔 INTENT REMINDER DINORMALISASI")
        print("INTENT   :", intent)
        print("ACTION   :", nlp.get("action"))
        print("NAMA     :", nlp.get("nama"))
        print("TANGGAL  :", nlp.get("tanggal"))
        print("NOMINAL  :", nlp.get("nominal"))
        print("========================================")

    # ============================================================
    # REMINDER NLP
    #
    # ACTION:
    #
    # list
    # create
    # update
    # delete
    # ============================================================

    if intent == "reminder":

        action = nlp.get(
            "action"
        )

        nama = nlp.get(
            "nama"
        )

        tanggal = nlp.get(
            "tanggal"
        )

        nominal = nlp.get(
            "nominal"
        )

        print("========================================")
        print("🔔 PROSES REMINDER")
        print("SENDER  :", sender)
        print("MESSAGE :", message)
        print("INTENT  :", intent)
        print("ACTION  :", action)
        print("NAMA    :", nama)
        print("TANGGAL :", tanggal)
        print("NOMINAL :", nominal)
        print("========================================")

        # ========================================================
        # CEK FITUR
        # ========================================================

        if action == "delete":

            if not has_feature(
                sender,
                "hapusreminder"
            ):

                kirim_wa(
                    sender,
                    """🔒 *Fitur Hapus Reminder tersedia pada paket PRO dan PREMIUM.*

    Upgrade sekarang agar dapat:

    ✅ Budget Bulanan
    ✅ Reminder
    ✅ Target Tabungan
    ✅ Hutang Piutang
    ✅ AI Insight
    ✅ Dashboard Lengkap

    🌐 www.chatsaku.com

    _ChatSaku Finance Assistant_"""
                )

                return jsonify(
                    status=True
                )

        else:

            if not has_feature(
                sender,
                "reminder"
            ):

                kirim_wa(
                    sender,
                    """🔒 *Reminder tersedia di paket PRO dan PREMIUM.*

    Upgrade sekarang agar dapat:

    ✅ Budget Bulanan
    ✅ Reminder
    ✅ Target Tabungan
    ✅ Hutang Piutang
    ✅ AI Insight
    ✅ Dashboard Lengkap

    🌐 www.chatsaku.com

    _ChatSaku Finance Assistant_"""
                )

                return jsonify(
                    status=True
                )

        # ========================================================
        # OWNER
        # ========================================================

        nomor_owner = get_owner_number(
            sender
        )

        # ========================================================
        # ACTION LIST
        # ========================================================

        if action == "list":

            reminders = Reminder.query.filter_by(
                nomor_wa=nomor_owner,
                aktif=True
            ).order_by(
                Reminder.tanggal.asc()
            ).all()

            if not reminders:

                kirim_wa(
                    sender,
                    """📭 *Belum ada reminder.*

    Contoh:

    🔔 reminder listrik tanggal 20 500 ribu

    🔔 reminder internet tanggal 25 350 ribu

    _ChatSaku Finance Assistant_"""
                )

                return jsonify(
                    status=True
                )

            pesan = "🔔 *DAFTAR REMINDER*\n"
            pesan += "━━━━━━━━━━━━━━━━━━\n\n"

            total = 0

            for i, r in enumerate(
                reminders,
                1
            ):

                nilai = (
                    r.nominal or 0
                )

                total += nilai

                pesan += (
                    f"*{i}. {r.nama.title()}*\n"
                    f"📅 Tanggal : {r.tanggal}\n"
                    f"💰 Nominal : Rp {nilai:,.0f}\n\n"
                )

            pesan += "━━━━━━━━━━━━━━━━━━\n"
            pesan += (
                f"💵 *Total Tagihan*\n"
                f"Rp {total:,.0f}"
            )

            if is_viewer(sender):

                pesan += (
                    "\n\n👁 *Mode Viewer*\n"
                    "Data Reminder milik Owner."
                )

            pesan += (
                "\n\n_ChatSaku Finance Assistant_"
            )

            kirim_wa(
                sender,
                pesan
            )

            return jsonify({
                "status": True,
                "intent": "reminder",
                "action": "list"
            })

        # ========================================================
        # ACTION DELETE
        # ========================================================

        if action == "delete":

            if not nama:

                kirim_wa(
                    sender,
                    """❌ *Nama reminder belum ditemukan.*

    Contoh:

    *hapus reminder listrik*

    atau:

    *hapusreminder listrik*"""
                )

                return jsonify(
                    status=True
                )

            # ----------------------------------------------------
            # VIEWER TIDAK BOLEH DELETE
            # ----------------------------------------------------

            if is_viewer(sender):

                kirim_wa(
                    sender,
                    """🔒 *Mode Viewer*

    Anda hanya dapat melihat Reminder.

    Perubahan Reminder hanya dapat dilakukan oleh Owner."""
                )

                return jsonify(
                    status=True
                )

            # ----------------------------------------------------
            # CARI REMINDER
            # ----------------------------------------------------

            reminder = Reminder.query.filter_by(
                nomor_wa=nomor_owner,
                nama=nama
            ).first()

            # ----------------------------------------------------
            # FALLBACK CASE-INSENSITIVE
            # ----------------------------------------------------

            if not reminder:

                reminders = Reminder.query.filter_by(
                    nomor_wa=nomor_owner,
                    aktif=True
                ).all()

                for r in reminders:

                    if (
                        (r.nama or "").lower()
                        == nama.lower()
                    ):

                        reminder = r
                        break

            # ----------------------------------------------------
            # TIDAK DITEMUKAN
            # ----------------------------------------------------

            if not reminder:

                kirim_wa(
                    sender,
                    f"""❌ *Reminder tidak ditemukan.*

    🔔 Reminder:
    *{nama}*

    Ketik:

    *reminder*

    untuk melihat daftar reminder."""
                )

                return jsonify(
                    status=True
                )

            # ----------------------------------------------------
            # HAPUS
            # ----------------------------------------------------

            try:

                reminder.aktif = False

                db.session.commit()

            except Exception as e:

                db.session.rollback()

                print(
                    "❌ ERROR DELETE REMINDER:",
                    repr(e)
                )

                kirim_wa(
                    sender,
                    "❌ Gagal menghapus reminder."
                )

                return jsonify(
                    status=False
                ), 500

            kirim_wa(
                sender,
                f"""🗑️ *Reminder Berhasil Dihapus*

    ━━━━━━━━━━━━━━━━━━

    📄 *Tagihan*
    {reminder.nama.title()}

    ━━━━━━━━━━━━━━━━━━

    _ChatSaku Finance Assistant_"""
            )

            return jsonify({
                "status": True,
                "intent": "reminder",
                "action": "delete",
                "nama": reminder.nama
            })

        # ========================================================
        # ACTION CREATE / UPDATE
        # ========================================================

        if action in (
            "create",
            "update"
        ):

            # ----------------------------------------------------
            # VIEWER
            # ----------------------------------------------------

            if is_viewer(sender):

                kirim_wa(
                    sender,
                    """🔒 *Mode Viewer*

    Anda hanya dapat melihat Reminder.

    Perubahan Reminder hanya dapat dilakukan oleh Owner."""
                )

                return jsonify(
                    status=True
                )

            # ----------------------------------------------------
            # VALIDASI NAMA
            # ----------------------------------------------------

            if not nama:

                kirim_wa(
                    sender,
                    """❌ *Nama reminder belum ditemukan.*

    Contoh:

    🔔 *reminder listrik tanggal 20 500 ribu*

    🔔 *reminder internet tanggal 25 350 ribu*

    _ChatSaku Finance Assistant_"""
                )

                return jsonify(
                    status=True
                )

            # ----------------------------------------------------
            # VALIDASI TANGGAL
            # ----------------------------------------------------

            try:

                tanggal = int(
                    tanggal or 0
                )

            except (
                ValueError,
                TypeError
            ):

                tanggal = 0

            if tanggal < 1 or tanggal > 31:

                kirim_wa(
                    sender,
                    """❌ *Tanggal reminder belum ditemukan atau tidak valid.*

    Tanggal harus antara *1 sampai 31*.

    Contoh:

    *reminder listrik tanggal 20 500 ribu*"""
                )

                return jsonify(
                    status=True
                )

            # ----------------------------------------------------
            # VALIDASI NOMINAL
            # ----------------------------------------------------

            try:

                nominal = normalize_nominal(
                    nominal
                )

            except Exception:

                nominal = None

            if not nominal or nominal <= 0:

                kirim_wa(
                    sender,
                    """❌ *Nominal reminder belum ditemukan.*

    Contoh:

    *reminder listrik tanggal 20 500000*

    atau:

    *reminder listrik tanggal 20 500 ribu*"""
                )

                return jsonify(
                    status=True
                )

            # ----------------------------------------------------
            # NORMALISASI NAMA
            # ----------------------------------------------------

            nama = str(
                nama
            ).strip()

            nama = re.sub(
                r'\s+',
                ' ',
                nama
            ).strip()

            if not nama:

                kirim_wa(
                    sender,
                    "❌ Nama reminder belum diisi."
                )

                return jsonify(
                    status=True
                )

            # ----------------------------------------------------
            # CARI REMINDER
            # ----------------------------------------------------

            reminder = Reminder.query.filter_by(
                nomor_wa=nomor_owner,
                nama=nama
            ).first()

            # ----------------------------------------------------
            # FALLBACK CASE-INSENSITIVE
            # ----------------------------------------------------

            if not reminder:

                reminders = Reminder.query.filter_by(
                    nomor_wa=nomor_owner,
                    aktif=True
                ).all()

                for r in reminders:

                    if (
                        (r.nama or "").lower()
                        == nama.lower()
                    ):

                        reminder = r
                        break

            # ----------------------------------------------------
            # UPDATE
            # ----------------------------------------------------

            if reminder:

                reminder.tanggal = tanggal
                reminder.nominal = nominal
                reminder.aktif = True

                status_text = "Diperbarui"

            # ----------------------------------------------------
            # CREATE
            # ----------------------------------------------------

            else:

                try:

                    reminder = Reminder(
                        nomor_wa=nomor_owner,
                        nama=nama,
                        tanggal=tanggal,
                        nominal=nominal,
                        aktif=True
                    )

                    db.session.add(
                        reminder
                    )

                    status_text = "Dibuat"

                except Exception as e:

                    db.session.rollback()

                    print(
                        "❌ ERROR CREATE REMINDER:",
                        repr(e)
                    )

                    kirim_wa(
                        sender,
                        "❌ Gagal membuat reminder."
                    )

                    return jsonify(
                        status=False
                    ), 500

            # ----------------------------------------------------
            # COMMIT
            # ----------------------------------------------------

            try:

                db.session.commit()

            except Exception as e:

                db.session.rollback()

                print(
                    "❌ ERROR COMMIT REMINDER:",
                    repr(e)
                )

                kirim_wa(
                    sender,
                    "❌ Gagal menyimpan reminder."
                )

                return jsonify(
                    status=False
                ), 500

            # ----------------------------------------------------
            # RESPONSE
            # ----------------------------------------------------

            kirim_wa(
                sender,
                f"""🔔 *Reminder {status_text}*

    ━━━━━━━━━━━━━━━━━━

    📄 *Tagihan*
    {nama.title()}

    📅 *Jatuh Tempo*
    Tanggal {tanggal}

    💰 *Estimasi*
    Rp {nominal:,.0f}

    ━━━━━━━━━━━━━━━━━━

    Ketik:

    *reminder*

    untuk melihat seluruh reminder.

    _ChatSaku Finance Assistant_"""
            )

            return jsonify({
                "status": True,
                "intent": "reminder",
                "action": "update" if status_text == "Diperbarui" else "create",
                "nama": nama,
                "tanggal": tanggal,
                "nominal": nominal
            })

        # ========================================================
        # ACTION TIDAK DIKENALI
        # ========================================================

        kirim_wa(
            sender,
            """❌ *Perintah reminder tidak dikenali.*

    Contoh:

    🔔 *reminder*

    🔔 *reminder listrik tanggal 20 500000*

    🔔 *reminder listrik tanggal 20 500 ribu*

    🗑️ *hapus reminder listrik*

    _ChatSaku Finance Assistant_"""
        )

        return jsonify(
            status=True
        )

    # ============================================================
    # ============================================================
    # NORMALISASI TARGET / TABUNG
    # ============================================================
    # LETAKKAN SETELAH:
    #
    # nlp = hasil NLP utama
    # intent = nlp.get("intent")
    #
    # DAN SEBELUM HANDLER:
    # if intent == "target":
    # if intent == "tabung":
    # ============================================================


    # ============================================================
    # 1. DETEKSI TARGET NLP
    # ============================================================

    target_nlp = deteksi_target_nlp(
        message,
        nlp
    )

    # ============================================================
    # 2. DETEKSI TABUNG NLP
    # ============================================================

    tabung_nlp = deteksi_tabung_nlp(
        message,
        nlp
    )

    print("========================================")
    print("🎯 TARGET NLP :", target_nlp)
    print("💰 TABUNG NLP :", tabung_nlp)
    print("========================================")


    # ============================================================
    # 3. PRIORITAS TARGET
    # ============================================================
    #
    # Jika target_nlp menghasilkan action:
    #
    # list
    # detail
    # delete
    # create
    #
    # maka gunakan hasil tersebut.
    # ============================================================

    if target_nlp:

        target_action = target_nlp.get("action")

        # --------------------------------------------------------
        # LIST / DETAIL / DELETE
        # --------------------------------------------------------

        if target_action in (
            "list",
            "detail",
            "delete"
        ):

            intent = "target"

            nlp["intent"] = "target"
            nlp["action"] = target_action
            nlp["nama"] = target_nlp.get("nama")
            nlp["nominal"] = target_nlp.get("nominal")
            nlp["deadline"] = target_nlp.get("deadline")

        # --------------------------------------------------------
        # CREATE TARGET
        # --------------------------------------------------------

        elif target_action == "create":

            intent = "target"

            nlp["intent"] = "target"
            nlp["action"] = "create"
            nlp["nama"] = target_nlp.get("nama")
            nlp["nominal"] = target_nlp.get("nominal")
            nlp["deadline"] = target_nlp.get("deadline")

            print("🎯 INTENT DIUBAH MENJADI TARGET CREATE")


    # ============================================================
    # 4. JIKA BUKAN TARGET → CEK TABUNG
    # ============================================================
    #
    # Contoh:
    #
    # saya mau menabung motor 5000000
    #
    # Tidak ada deadline.
    #
    # Maka:
    #
    # intent = tabung
    # action = add
    #
    # BUKAN target.
    # ============================================================

    elif tabung_nlp:

        intent = "tabung"

        nlp["intent"] = "tabung"
        nlp["action"] = "add"
        nlp["nama"] = tabung_nlp.get("nama")
        nlp["nominal"] = tabung_nlp.get("nominal")

        print("💰 INTENT DIUBAH MENJADI TABUNG ADD")


    # ============================================================
    # DEBUG FINAL INTENT
    # ============================================================

    print("========================================")
    print("🧠 INTENT FINAL")
    print("MESSAGE :", message)
    print("INTENT  :", intent)
    print("ACTION  :", nlp.get("action"))
    print("NAMA    :", nlp.get("nama"))
    print("NOMINAL :", nlp.get("nominal"))
    print("DEADLINE:", nlp.get("deadline"))
    print("========================================")


    # ============================================================
    # ============================================================
    # HANDLER TARGET
    # ============================================================
    # ============================================================

    if intent == "target":

        # ========================================================
        # CEK FITUR
        # ========================================================

        if not has_feature(
            sender,
            "target"
        ):

            kirim_wa(
                sender,
                """🔒 *Fitur Target Tabungan hanya tersedia pada paket PREMIUM.*

    Upgrade sekarang agar dapat:

    ✅ Budget Bulanan
    ✅ Reminder
    ✅ Target Tabungan
    ✅ Hutang Piutang
    ✅ AI Insight
    ✅ Dashboard Lengkap

    🌐 www.chatsaku.com

    _ChatSaku Finance Assistant_"""
            )

            return jsonify(
                status=True
            )


        # ========================================================
        # ACTION
        # ========================================================

        action = nlp.get("action")

        print("========================================")
        print("🎯 TARGET HANDLER")
        print("ACTION :", action)
        print("NAMA   :", nlp.get("nama"))
        print("========================================")


        # ========================================================
        # OWNER
        # ========================================================

        nomor_owner = get_owner_number(
            sender
        )


        # ========================================================
        # ========================================================
        # ACTION LIST
        # ========================================================
        # ========================================================

        if action == "list":

            data_target = TargetPembelian.query.filter_by(
                nomor_wa=nomor_owner,
                aktif=True
            ).order_by(
                TargetPembelian.deadline.asc()
            ).all()


            # ----------------------------------------------------
            # TIDAK ADA TARGET
            # ----------------------------------------------------

            if not data_target:

                kirim_wa(
                    sender,
                    """🎯 *TARGET TABUNGAN*

    Belum ada target tabungan.

    Contoh membuat target:

    *Saya ingin menabung laptop 30 juta sampai 20-12-2026*

    _ChatSaku Finance Assistant_"""
                )

                return jsonify(
                    status=True
                )


            # ----------------------------------------------------
            # RESPONSE
            # ----------------------------------------------------

            text_response = (
                "🎯 *TARGET TABUNGAN*\n\n"
            )

            if nomor_owner != sender:

                text_response += (
                    "👁 *Mode Viewer*\n"
                    "Data milik owner akun.\n\n"
                )


            for i, target in enumerate(
                data_target,
                1
            ):

                terkumpul = (
                    target.terkumpul or 0
                )

                target_nominal = (
                    target.target or 0
                )

                persen = round(
                    (
                        terkumpul /
                        target_nominal
                    ) * 100
                ) if target_nominal else 0

                persen = min(
                    persen,
                    100
                )

                sisa = max(
                    target_nominal -
                    terkumpul,
                    0
                )

                deadline_text = "-"

                if target.deadline:

                    deadline_text = (
                        target.deadline.strftime(
                            "%d-%m-%Y"
                        )
                    )


                text_response += f"""*{i}. {target.nama}*

    💰 Target
    Rp {target_nominal:,.0f}

    💵 Terkumpul
    Rp {terkumpul:,.0f}

    📊 Progress
    {persen}%

    💸 Sisa
    Rp {sisa:,.0f}

    📅 Deadline
    {deadline_text}

    ━━━━━━━━━━━━━━━━━━

    """


            text_response += (
                "_ChatSaku Finance Assistant_"
            )

            kirim_wa(
                sender,
                text_response
            )

            return jsonify({
                "status": True,
                "intent": "target",
                "action": "list"
            })


        # ========================================================
        # ========================================================
        # ACTION DELETE
        # ========================================================
        # ========================================================

        if action == "delete":

            nama = nlp.get(
                "nama"
            )

            if not nama:

                kirim_wa(
                    sender,
                    """❌ *Nama target belum ditemukan.*

    Contoh:

    *hapus target laptop*

    atau:

    *hapus laptop*

    atau:

    *hapustarget laptop*"""
                )

                return jsonify(
                    status=True
                )


            # ----------------------------------------------------
            # BERSIHKAN NAMA DELETE
            # ----------------------------------------------------

            nama = str(
                nama
            ).strip()


            # Hapus kata "target"
            nama = re.sub(
                r'\btarget\b',
                '',
                nama,
                flags=re.IGNORECASE
            )


            # Hapus kata pembuka
            nama = re.sub(
                r'^(saya|aku|kami)\s+',
                '',
                nama,
                flags=re.IGNORECASE
            )


            # ----------------------------------------------------
            # KASUS:
            #
            # hapus saya ingin membuat target leptop
            #
            # menjadi:
            #
            # leptop
            # ----------------------------------------------------

            nama = re.sub(
                r'\b(saya|aku|kami)\b',
                '',
                nama,
                flags=re.IGNORECASE
            )

            nama = re.sub(
                r'\b(ingin|mau|akan)\b',
                '',
                nama,
                flags=re.IGNORECASE
            )

            nama = re.sub(
                r'\b(membuat|buat|bikin|buatkan)\b',
                '',
                nama,
                flags=re.IGNORECASE
            )

            nama = re.sub(
                r'\b(target|tabungan)\b',
                '',
                nama,
                flags=re.IGNORECASE
            )


            nama = re.sub(
                r'\s+',
                ' ',
                nama
            ).strip()


            if not nama:

                kirim_wa(
                    sender,
                    """❌ *Nama target belum ditemukan.*

    Contoh:

    *hapus target laptop*"""
                )

                return jsonify(
                    status=True
                )


            print("========================================")
            print("🗑 DELETE TARGET")
            print("NAMA ASLI :", nlp.get("nama"))
            print("NAMA FINAL:", nama)
            print("========================================")


            # ----------------------------------------------------
            # CARI TARGET
            # ----------------------------------------------------

            semua_target = TargetPembelian.query.filter_by(
                nomor_wa=nomor_owner,
                aktif=True
            ).all()

            target = None

            nama_lower = nama.lower()


            for item in semua_target:

                item_nama = str(
                    item.nama or ""
                ).strip().lower()

                if item_nama == nama_lower:

                    target = item
                    break


            # ----------------------------------------------------
            # FALLBACK CONTAINS
            # ----------------------------------------------------

            if not target:

                for item in semua_target:

                    item_nama = str(
                        item.nama or ""
                    ).strip().lower()

                    if (
                        nama_lower in item_nama
                        or
                        item_nama in nama_lower
                    ):

                        target = item
                        break


            # ----------------------------------------------------
            # TIDAK DITEMUKAN
            # ----------------------------------------------------

            if not target:

                kirim_wa(
                    sender,
                    f"""❌ *Target tidak ditemukan.*

    🎯 Target:
    *{nama}*

    Gunakan:

    *target*

    untuk melihat semua target.

    _ChatSaku Finance Assistant_"""
                )

                return jsonify(
                    status=True
                )


            # ----------------------------------------------------
            # HAPUS
            # ----------------------------------------------------

            nama_target = target.nama

            target.aktif = False

            db.session.commit()


            kirim_wa(
                sender,
                f"""🗑 *Target Berhasil Dihapus*

    🎯 Target:
    *{nama_target}*

    Target sudah tidak aktif.

    _ChatSaku Finance Assistant_"""
            )

            return jsonify({
                "status": True,
                "intent": "target",
                "action": "delete",
                "nama": nama_target
            })


        # ========================================================
        # ========================================================
        # ACTION DETAIL
        # ========================================================
        # ========================================================

        if action == "detail":

            nama = nlp.get(
                "nama"
            )

            if not nama:

                kirim_wa(
                    sender,
                    """❌ *Nama target belum ditemukan.*

    Contoh:

    *target laptop*

    atau:

    *detail target laptop*"""
                )

                return jsonify(
                    status=True
                )


            nama = str(
                nama
            ).strip()


            # ----------------------------------------------------
            # CARI TARGET
            # ----------------------------------------------------

            semua_target = TargetPembelian.query.filter_by(
                nomor_wa=nomor_owner,
                aktif=True
            ).all()

            target = None

            nama_lower = nama.lower()


            for item in semua_target:

                item_nama = str(
                    item.nama or ""
                ).strip().lower()

                if item_nama == nama_lower:

                    target = item
                    break


            # ----------------------------------------------------
            # FALLBACK CONTAINS
            # ----------------------------------------------------

            if not target:

                for item in semua_target:

                    item_nama = str(
                        item.nama or ""
                    ).strip().lower()

                    if (
                        nama_lower in item_nama
                        or
                        item_nama in nama_lower
                    ):

                        target = item
                        break


            if not target:

                kirim_wa(
                    sender,
                    f"""❌ *Target tidak ditemukan.*

    🎯 Target:
    *{nama}*

    Gunakan:

    *target*

    untuk melihat daftar target."""
                )

                return jsonify(
                    status=True
                )


            # ----------------------------------------------------
            # HITUNG
            # ----------------------------------------------------

            terkumpul = (
                target.terkumpul or 0
            )

            target_nominal = (
                target.target or 0
            )

            persen = round(
                (
                    terkumpul /
                    target_nominal
                ) * 100
            ) if target_nominal else 0

            persen = min(
                persen,
                100
            )

            sisa = max(
                target_nominal -
                terkumpul,
                0
            )


            deadline_text = "-"

            if target.deadline:

                deadline_text = (
                    target.deadline.strftime(
                        "%d-%m-%Y"
                    )
                )


            viewer_info = ""

            if nomor_owner != sender:

                viewer_info = (
                    "\n👁 *Mode Viewer*\n"
                )


            kirim_wa(
                sender,
                f"""🎯 *{target.nama}*
    {viewer_info}
    ━━━━━━━━━━━━━━━━━━

    🎯 *Target*
    Rp {target_nominal:,.0f}

    💰 *Terkumpul*
    Rp {terkumpul:,.0f}

    💵 *Sisa*
    Rp {sisa:,.0f}

    📊 *Progress*
    {persen}%

    📅 *Deadline*
    {deadline_text}

    ━━━━━━━━━━━━━━━━━━

    Untuk menambah tabungan:

    *tabung {target.nama} 500000*

    _ChatSaku Finance Assistant_"""
            )

            return jsonify({
                "status": True,
                "intent": "target",
                "action": "detail",
                "nama": target.nama,
                "nominal": target_nominal,
                "terkumpul": terkumpul,
                "sisa": sisa,
                "progress": persen
            })


        # ========================================================
        # ========================================================
        # ACTION CREATE
        # ========================================================
        # ========================================================

        if action == "create":

            nama = nlp.get(
                "nama"
            )

            nominal = nlp.get(
                "nominal"
            )

            deadline = nlp.get(
                "deadline"
            )


            # ----------------------------------------------------
            # NAMA
            # ----------------------------------------------------

            if not nama:

                kirim_wa(
                    sender,
                    """❌ *Nama target belum ditemukan.*

    Contoh:

    🎯 *saya ingin menabung laptop 30 juta sampai 20-12-2026*

    _ChatSaku Finance Assistant_"""
                )

                return jsonify(
                    status=True
                )


            # ----------------------------------------------------
            # NOMINAL
            # ----------------------------------------------------

            try:

                if nominal:

                    nominal = int(
                        float(nominal)
                    )

                else:

                    nominal = parse_nominal_finance(
                        message
                    )

            except Exception:

                nominal = None


            if not nominal or nominal <= 0:

                kirim_wa(
                    sender,
                    """❌ *Nominal target belum ditemukan.*

    Contoh:

    🎯 *saya ingin menabung laptop 30 juta sampai 20-12-2026*

    🎯 *target motor 25000000 sampai 31-12-2026*"""
                )

                return jsonify(
                    status=True
                )


            # ----------------------------------------------------
            # DEADLINE
            # ----------------------------------------------------

            if isinstance(
                deadline,
                str
            ):

                deadline = parse_deadline_finance(
                    deadline
                )


            if not deadline:

                deadline = parse_deadline_finance(
                    message
                )


            if not deadline:

                kirim_wa(
                    sender,
                    """❌ *Deadline target belum ditemukan.*

    Contoh:

    🎯 *saya ingin menabung laptop 30 juta sampai 20-12-2026*

    Gunakan format:

    *DD-MM-YYYY*

    Contoh:

    *20-12-2026*"""
                )

                return jsonify(
                    status=True
                )


            # ----------------------------------------------------
            # DEADLINE TIDAK BOLEH LEWAT
            # ----------------------------------------------------

            if deadline < date.today():

                kirim_wa(
                    sender,
                    f"""❌ *Deadline tidak valid.*

    Tanggal:

    *{deadline.strftime("%d-%m-%Y")}*

    sudah lewat.

    Silakan gunakan tanggal yang akan datang."""
                )

                return jsonify(
                    status=True
                )


            # ----------------------------------------------------
            # CLEAN NAMA
            # ----------------------------------------------------

            nama = clean_target_name(
                nama
            )


            if not nama:

                kirim_wa(
                    sender,
                    """❌ *Nama target belum ditemukan.*

    Contoh:

    🎯 *saya ingin menabung laptop 30 juta sampai 20-12-2026*"""
                )

                return jsonify(
                    status=True
                )


            # ----------------------------------------------------
            # OWNER
            # ----------------------------------------------------

            nomor_owner = get_owner_number(
                sender
            )


            # ----------------------------------------------------
            # CEK DUPLIKAT
            # ----------------------------------------------------

            semua_target = TargetPembelian.query.filter_by(
                nomor_wa=nomor_owner,
                aktif=True
            ).all()

            nama_lower = nama.lower()

            target_sama = None


            for item in semua_target:

                if (
                    str(
                        item.nama or ""
                    ).strip().lower()
                    == nama_lower
                ):

                    target_sama = item
                    break


            if target_sama:

                deadline_lama = "-"

                if target_sama.deadline:

                    deadline_lama = (
                        target_sama.deadline.strftime(
                            "%d-%m-%Y"
                        )
                    )


                terkumpul_lama = (
                    target_sama.terkumpul or 0
                )

                target_lama = (
                    target_sama.target or 0
                )

                progress_lama = round(
                    (
                        terkumpul_lama /
                        target_lama
                    ) * 100
                ) if target_lama else 0


                kirim_wa(
                    sender,
                    f"""⚠️ *Target tersebut sudah ada.*

    🎯 *Nama*
    {target_sama.nama}

    💰 *Target*
    Rp {target_lama:,.0f}

    💵 *Terkumpul*
    Rp {terkumpul_lama:,.0f}

    📊 *Progress*
    {progress_lama}%

    📅 *Deadline*
    {deadline_lama}

    Silakan gunakan nama target lain.

    _ChatSaku Finance Assistant_"""
                )

                return jsonify(
                    status=True
                )


            # ============================================================
            # CREATE DATABASE TARGET
            # ============================================================

            try:

                print("========================================")
                print("💾 INSERT TARGET KE DATABASE")
                print("========================================")
                print("nomor_wa  :", nomor_owner)
                print("nama      :", nama)
                print("target    :", nominal)
                print("deadline  :", deadline)
                print("terkumpul :", 0)
                print("aktif     :", True)
                print("========================================")

                target = TargetPembelian(
                    nomor_wa=nomor_owner,
                    nama=nama,
                    target=int(nominal),
                    deadline=deadline,
                    terkumpul=0,
                    aktif=True
                )

                db.session.add(target)

                print("💾 db.session.add() berhasil")

                db.session.commit()

                print("✅ db.session.commit() BERHASIL")
                print("TARGET ID :", target.id)
                print("========================================")

            except Exception as e:

                db.session.rollback()

                import traceback

                print("========================================")
                print("❌ ERROR CREATE TARGET")
                print("========================================")
                print("ERROR TYPE :", type(e).__name__)
                print("ERROR      :", repr(e))
                print("MESSAGE    :", str(e))
                print("----------------------------------------")
                traceback.print_exc()
                print("========================================")

                kirim_wa(
                    sender,
                    """❌ *Gagal membuat target.*

            Terjadi kesalahan saat menyimpan target ke database.

            Silakan coba kembali beberapa saat lagi.

            _ChatSaku Finance Assistant_"""
                )

                return jsonify(
                    status=False,
                    error=str(e)
                ), 500


            # ----------------------------------------------------
            # RESPONSE
            # ----------------------------------------------------

            kirim_wa(
                sender,
                f"""🎯 *Target Berhasil Dibuat*

    ━━━━━━━━━━━━━━━━━━

    🎯 *Nama Target*
    {nama}

    💰 *Target*
    Rp {nominal:,.0f}

    📅 *Deadline*
    {deadline.strftime("%d-%m-%Y")}

    💵 *Terkumpul*
    Rp 0

    📊 *Progress*
    0%

    ━━━━━━━━━━━━━━━━━━

    💚 Selamat menabung!

    Untuk menambah tabungan:

    *tabung {nama} 500000*

    _ChatSaku Finance Assistant_"""
            )


            return jsonify({

                "status": True,

                "intent": "target",

                "action": "create",

                "nama": nama,

                "nominal": nominal,

                "deadline": deadline.strftime(
                    "%d-%m-%Y"
                )

            })


        # ========================================================
        # ACTION TIDAK DIKENALI
        # ========================================================

        kirim_wa(
            sender,
            """❌ *Perintah target tidak dikenali.*

    Contoh:

    🎯 *target*

    🎯 *target laptop*

    🎯 *target laptop 12000000 31-12-2026*

    🗑 *hapus target laptop*

    _ChatSaku Finance Assistant_"""
        )

        return jsonify(
            status=True
        )


    # ============================================================
    # ============================================================
    # HANDLER TAMBAH TABUNGAN
    # ============================================================
    # ============================================================

    if intent == "tabung":

        # ========================================================
        # CEK FITUR
        # ========================================================

        if not has_feature(
            sender,
            "tabung"
        ):

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

    🌐 www.chatsaku.com

    _ChatSaku Finance Assistant_"""
            )

            return jsonify(
                status=True
            )

        # ========================================================
        # DATA
        # ========================================================

        nama = nlp.get(
            "nama"
        )

        nominal = nlp.get(
            "nominal"
        )

        # ========================================================
        # FALLBACK
        # ========================================================

        if not nama:

            nama = nlp.get(
                "keterangan"
            )

        if not nama:

            tabung_fallback = deteksi_tabung_nlp(
                message,
                nlp
            )

            if tabung_fallback:

                nama = tabung_fallback.get(
                    "nama"
                )

                if not nominal:

                    nominal = tabung_fallback.get(
                        "nominal"
                    )

        # ========================================================
        # NAMA
        # ========================================================

        nama = clean_target_name(
            nama
        )

        if not nama:

            kirim_wa(
                sender,
                """❌ *Nama target belum ditemukan.*

    Contoh:

    *tabung laptop 500000*

    *tabung motor 500 ribu*"""
            )

            return jsonify(
                status=True
            )

        # ========================================================
        # NOMINAL
        # ========================================================

        if not nominal:

            nominal = parse_nominal_finance(
                message
            )

        else:

            try:

                nominal = int(
                    float(nominal)
                )

            except Exception:

                nominal = parse_nominal_finance(
                    str(nominal)
                )

        if not nominal or nominal <= 0:

            kirim_wa(
                sender,
                """❌ *Nominal tabungan belum ditemukan.*

    Contoh:

    *tabung laptop 500000*

    *tabung laptop 500 ribu*"""
            )

            return jsonify(
                status=True
            )

        print("========================================")
        print("💰 PROSES TAMBAH TABUNGAN")
        print("SENDER  :", sender)
        print("OWNER   :", get_owner_number(sender))
        print("NAMA    :", nama)
        print("NOMINAL :", nominal)
        print("========================================")

        # ========================================================
        # OWNER
        # ========================================================

        nomor_owner = get_owner_number(
            sender
        )

        # ========================================================
        # CARI TARGET
        # ========================================================

        target = TargetPembelian.query.filter_by(
            nomor_wa=nomor_owner,
            aktif=True
        ).all()

        target_ditemukan = None

        nama_lower = nama.lower()

        for item in target:

            if (
                str(
                    item.nama
                ).strip().lower()
                == nama_lower
            ):

                target_ditemukan = item
                break

        if not target_ditemukan:

            kirim_wa(
                sender,
                f"""❌ *Target tidak ditemukan.*

    🎯 Target:
    *{nama}*

    Gunakan:

    *target*

    untuk melihat daftar target.

    Contoh:

    *tabung {nama} 500000*"""
            )

            return jsonify(
                status=True
            )

        target = target_ditemukan

        # ========================================================
        # TAMBAH TABUNGAN
        # ========================================================

        try:

            target.terkumpul = (
                target.terkumpul or 0
            ) + nominal

            db.session.commit()

        except Exception as e:

            db.session.rollback()

            print(
                "❌ ERROR TAMBAH TABUNGAN:",
                repr(e)
            )

            kirim_wa(
                sender,
                "❌ Gagal menyimpan tabungan."
            )

            return jsonify(
                status=False
            ), 500

        # ========================================================
        # PROGRESS
        # ========================================================

        target_nominal = (
            target.target or 0
        )

        terkumpul = (
            target.terkumpul or 0
        )

        persen = round(
            (
                terkumpul /
                target_nominal
            ) * 100
        ) if target_nominal else 0

        persen = min(
            persen,
            100
        )

        sisa = max(
            target_nominal - terkumpul,
            0
        )

        # ========================================================
        # RESPONSE
        # ========================================================

        if persen >= 100:

            progress_message = (
                "🎉 *TARGET TERCAPAI!*"
            )

        else:

            progress_message = (
                "💚 Semangat terus menabung!"
            )

        kirim_wa(
            sender,
            f"""💚 *Tabungan Berhasil*

    ━━━━━━━━━━━━━━━━━━

    🎯 *Target*
    {target.nama}

    ➕ *Ditabung*
    Rp {nominal:,.0f}

    💰 *Terkumpul*
    Rp {terkumpul:,.0f}

    🎯 *Target*
    Rp {target_nominal:,.0f}

    📊 *Progress*
    {persen}%

    💵 *Sisa*
    Rp {sisa:,.0f}

    ━━━━━━━━━━━━━━━━━━

    {progress_message}

    _ChatSaku Finance Assistant_"""
        )

        return jsonify({

            "status": True,

            "intent": "tabung",

            "action": "add",

            "nama": target.nama,

            "nominal": nominal,

            "terkumpul": terkumpul,

            "target": target_nominal,

            "progress": persen,

            "sisa": sisa

        })
    # # ============================================================
    # # TARGET TABUNGAN - NLP ROUTER
    # # ============================================================

    # if intent == "target":

    #     # ========================================================
    #     # CEK FITUR
    #     # ========================================================

    #     if not has_feature(sender, "target"):

    #         kirim_wa(
    #             sender,
    #             """🔒 *Fitur Target Tabungan hanya tersedia pada paket PREMIUM.*

    # Upgrade sekarang agar dapat:

    # ✅ Budget Bulanan
    # ✅ Reminder
    # ✅ Target Tabungan
    # ✅ Hutang Piutang
    # ✅ AI Insight
    # ✅ Dashboard Lengkap

    # 🌐 www.chatsaku.com

    # _ChatSaku Finance Assistant_"""
    #         )

    #         return jsonify(status=True)

    #     # ========================================================
    #     # AMBIL OWNER
    #     # ========================================================

    #     nomor = get_owner_number(sender)

    #     # ========================================================
    #     # AMBIL ACTION NLP
    #     # ========================================================

    #     action = nlp.get(
    #         "action",
    #         "create"
    #     )

    #     nama = nlp.get("nama")
    #     nominal = nlp.get("nominal")
    #     deadline = nlp.get("deadline")

    #     print("========================================")
    #     print("🎯 TARGET NLP ROUTER")
    #     print("SENDER   :", sender)
    #     print("OWNER    :", nomor)
    #     print("MESSAGE  :", message)
    #     print("INTENT   :", intent)
    #     print("ACTION   :", action)
    #     print("NAMA     :", nama)
    #     print("NOMINAL  :", nominal)
    #     print("DEADLINE :", deadline)
    #     print("========================================")

    #     # ========================================================
    #     # ACTION: LIST
    #     # ========================================================

    #     if action == "list":

    #         data = TargetPembelian.query.filter_by(
    #             nomor_wa=nomor,
    #             aktif=True
    #         ).all()

    #         if not data:

    #             kirim_wa(
    #                 sender,
    #                 """🎯 *Target Tabungan*

    # Belum ada target tabungan.

    # Contoh:

    # _saya ingin menabung untuk laptop 12 juta sampai 31-12-2026_"""
    #             )

    #             return jsonify(status=True)

    #         text = "🎯 *TARGET TABUNGAN*\n\n"

    #         if nomor != sender:
    #             text += "👁 *Mode Viewer (Data Owner)*\n\n"

    #         for i, x in enumerate(data, 1):

    #             terkumpul = x.terkumpul or 0
    #             target_nominal = x.target or 0

    #             persen = round(
    #                 (terkumpul / target_nominal) * 100
    #             ) if target_nominal else 0

    #             persen = min(
    #                 persen,
    #                 100
    #             )

    #             sisa = max(
    #                 target_nominal - terkumpul,
    #                 0
    #             )

    #             text += f"""*{i}. {x.nama}*

    # 📊 Progress : {persen}%
    # 💰 Terkumpul : Rp {terkumpul:,.0f}
    # 🎯 Target : Rp {target_nominal:,.0f}
    # 💵 Sisa : Rp {sisa:,.0f}
    # 📅 Deadline : {x.deadline.strftime("%d-%m-%Y") if x.deadline else "-"}

    # """

    #         text += "_ChatSaku Finance Assistant_"

    #         kirim_wa(
    #             sender,
    #             text
    #         )

    #         return jsonify(status=True)

    #     # ========================================================
    #     # ACTION: DETAIL
    #     # ========================================================

    #     if action == "detail":

    #         if not nama:

    #             kirim_wa(
    #                 sender,
    #                 """❌ Nama target belum disebutkan.

    # Contoh:

    # _detail target laptop_

    # atau

    # _lihat detail target laptop_"""
    #             )

    #             return jsonify(status=True)

    #         target = TargetPembelian.query.filter_by(
    #             nomor_wa=nomor,
    #             nama=nama,
    #             aktif=True
    #         ).first()

    #         if not target:

    #             kirim_wa(
    #                 sender,
    #                 f"""❌ *Target tidak ditemukan.*

    # 🎯 Target:
    # *{nama}*

    # Gunakan:

    # _target_

    # untuk melihat semua target."""
    #             )

    #             return jsonify(status=True)

    #         terkumpul = target.terkumpul or 0
    #         target_nominal = target.target or 0

    #         persen = round(
    #             (terkumpul / target_nominal) * 100
    #         ) if target_nominal else 0

    #         persen = min(
    #             persen,
    #             100
    #         )

    #         sisa = max(
    #             target_nominal - terkumpul,
    #             0
    #         )

    #         viewer_info = ""

    #         if nomor != sender:
    #             viewer_info = "\n👁 *Mode Viewer (Data Owner)*\n"

    #         kirim_wa(
    #             sender,
    #             f"""🎯 *{target.nama}*

    # ━━━━━━━━━━━━━━━━━━

    # 💰 *Terkumpul*
    # Rp {terkumpul:,.0f}

    # 🎯 *Target*
    # Rp {target_nominal:,.0f}

    # 💵 *Sisa*
    # Rp {sisa:,.0f}

    # 📊 *Progress*
    # {persen}%

    # 📅 *Deadline*
    # {target.deadline.strftime("%d-%m-%Y") if target.deadline else "-"}

    # ━━━━━━━━━━━━━━━━━━
    # {viewer_info}
    # _ChatSaku Finance Assistant_"""
    #         )

    #         return jsonify(status=True)

    #     # ========================================================
    #     # ACTION: DELETE
    #     # ========================================================

    #     if action == "delete":

    #         if not nama:

    #             kirim_wa(
    #                 sender,
    #                 """❌ Nama target belum disebutkan.

    # Contoh:

    # _hapus target laptop_

    # atau:

    # _hapustarget laptop_"""
    #             )

    #             return jsonify(status=True)

    #         target = TargetPembelian.query.filter_by(
    #             nomor_wa=nomor,
    #             nama=nama,
    #             aktif=True
    #         ).first()

    #         if not target:

    #             kirim_wa(
    #                 sender,
    #                 f"""❌ *Target tidak ditemukan.*

    # 🎯 Target:
    # *{nama}*"""
    #             )

    #             return jsonify(status=True)

    #         db.session.delete(
    #             target
    #         )

    #         db.session.commit()

    #         kirim_wa(
    #             sender,
    #             f"""🗑️ *Target berhasil dihapus.*

    # 🎯 Target:
    # *{nama}*

    # _ChatSaku Finance Assistant_"""
    #         )

    #         return jsonify(status=True)

    #     # ========================================================
    #     # ACTION: CREATE
    #     # ========================================================

    #     if action == "create":

    #         # ====================================================
    #         # VALIDASI NAMA
    #         # ====================================================

    #         if not nama:

    #             kirim_wa(
    #                 sender,
    #                 """❌ *Nama target belum ditemukan.*

    # Contoh:

    # 🎯 _target laptop 12000000 31-12-2026_

    # atau:

    # 🎯 _saya ingin menabung untuk laptop 12 juta sampai 31-12-2026_"""
    #             )

    #             return jsonify(status=True)

    #         # ====================================================
    #         # VALIDASI NOMINAL
    #         # ====================================================

    #         try:

    #             nominal = normalize_nominal(
    #                 nominal
    #             )

    #         except Exception as e:

    #             print(
    #                 "❌ ERROR NORMALIZE TARGET:",
    #                 repr(e)
    #             )

    #             nominal = None

    #         if not nominal or nominal <= 0:

    #             kirim_wa(
    #                 sender,
    #                 """❌ *Nominal target belum ditemukan.*

    # Contoh:

    # 🎯 _saya ingin menabung untuk laptop 30 juta sampai 20-12-2026_"""
    #             )

    #             return jsonify(status=True)

    #         # ====================================================
    #         # VALIDASI DEADLINE
    #         # ====================================================

    #         if not deadline:

    #             kirim_wa(
    #                 sender,
    #                 """❌ *Deadline target belum ditemukan.*

    # Contoh:

    # 🎯 _saya ingin menabung untuk laptop 30 juta sampai 20-12-2026_

    # Tanggal harus menggunakan format:

    # *DD-MM-YYYY*"""
    #             )

    #             return jsonify(status=True)

    #         # ====================================================
    #         # NORMALISASI NAMA
    #         # ====================================================

    #         nama = str(
    #             nama
    #         ).strip()

    #         # ====================================================
    #         # CEK TARGET DUPLIKAT
    #         # ====================================================

    #         cek = TargetPembelian.query.filter_by(
    #             nomor_wa=nomor,
    #             nama=nama,
    #             aktif=True
    #         ).first()

    #         if cek:

    #             kirim_wa(
    #                 sender,
    #                 f"""⚠️ *Target tersebut sudah ada.*

    # 🎯 Nama
    # *{nama}*

    # 💰 Target
    # Rp {cek.target:,.0f}

    # 📅 Deadline
    # {cek.deadline.strftime("%d-%m-%Y")}

    # Gunakan nama target berbeda jika ingin membuat target baru.

    # _ChatSaku Finance Assistant_"""
    #             )

    #             return jsonify(status=True)

    #         # ====================================================
    #         # BUAT TARGET
    #         # ====================================================

    #         target = TargetPembelian(

    #             nomor_wa=nomor,

    #             nama=nama,

    #             target=nominal,

    #             deadline=deadline

    #         )

    #         db.session.add(
    #             target
    #         )

    #         db.session.commit()

    #         # ====================================================
    #         # RESPONSE
    #         # ====================================================

    #         kirim_wa(
    #             sender,
    #             f"""🎯 *Target Berhasil Dibuat*

    # ━━━━━━━━━━━━━━━━━━

    # 🎯 *Nama Target*
    # {nama}

    # 💰 *Target*
    # Rp {nominal:,.0f}

    # 📅 *Deadline*
    # {deadline.strftime("%d-%m-%Y")}

    # ━━━━━━━━━━━━━━━━━━

    # 💚 Selamat menabung!

    # Untuk menambah tabungan:

    # *tabung {nama} 500000*

    # _ChatSaku Finance Assistant_"""
    #         )

    #         return jsonify({

    #             "status": True,

    #             "intent": "target",

    #             "action": "create",

    #             "nama": nama,

    #             "nominal": nominal,

    #             "deadline": deadline.strftime("%d-%m-%Y")

    #         })

    #     # ========================================================
    #     # ACTION TIDAK DIKENAL
    #     # ========================================================

    #     kirim_wa(
    #         sender,
    #         "❌ Perintah target tidak dikenali."
    #     )

    #     return jsonify(status=True)

    # =========================
    # SALDO
    # =========================
    # if cmd == "saldo":
    if intent == "saldo":

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

    # ============================================================
# MASUK / PEMASUKAN
# NLP + FALLBACK NATURAL LANGUAGE
# ============================================================




    # ============================================================
    # MASUK / PEMASUKAN
    # NLP NATURAL LANGUAGE
    # ============================================================

    # ============================================================
    # JALANKAN DETEKSI PEMASUKAN SATU KALI
    # ============================================================

    hasil_masuk = None

    try:

        hasil_masuk = deteksi_pemasukan_nlp(
            message,
            data
        )

    except Exception as e:

        print("❌ ERROR deteksi_pemasukan_nlp:", repr(e))


    # ============================================================
    # JIKA NLP MENGENALI PEMASUKAN
    # ============================================================

    if intent == "masuk" or hasil_masuk:

        try:

            # ====================================================
            # PRIORITASKAN HASIL NLP
            # ====================================================

            if hasil_masuk:

                data = hasil_masuk

                intent = "masuk"


            # ====================================================
            # DEBUG NLP
            # ====================================================

            print("========================================")
            print("🤖 PEMASUKAN NLP")
            print("TEXT       :", message)
            print("INTENT     :", intent)
            print("DATA       :", data)
            print("NOMINAL    :", data.get("nominal"))
            print("KETERANGAN :", data.get("keterangan"))
            print("========================================")


            # ====================================================
            # AMBIL NOMINAL DARI NLP
            # ====================================================

            nominal = data.get(
                "nominal"
            )


            # ====================================================
            # NORMALISASI NOMINAL
            # ====================================================

            try:

                if nominal:

                    nominal = int(
                        float(nominal)
                    )

                else:

                    nominal = 0

            except (
                ValueError,
                TypeError
            ):

                nominal = 0


            # ====================================================
            # FALLBACK:
            #
            # 4000000
            # Rp 4000000
            # 4.000.000
            # ====================================================

            if nominal <= 0:

                angka = re.findall(
                    r'(?:rp\s*)?[\d.,]+',
                    message,
                    re.IGNORECASE
                )

                if angka:

                    try:

                        nominal = normalize_nominal(
                            angka[-1]
                        )

                    except Exception as e:

                        print(
                            "❌ ERROR normalize nominal:",
                            repr(e)
                        )

                        nominal = 0


            # ====================================================
            # FALLBACK:
            #
            # 4 juta
            # 4 jt
            # 500 ribu
            # 500 rb
            # 1 miliar
            # ====================================================

            if nominal <= 0:

                pola_uang = re.search(
                    r'(\d+(?:[.,]\d+)?)\s*'
                    r'(juta|jt|ribu|rb|miliar|milyar)',
                    message.lower(),
                    re.IGNORECASE
                )

                if pola_uang:

                    angka_text = (
                        pola_uang.group(1)
                        .replace(",", ".")
                    )

                    satuan = (
                        pola_uang.group(2)
                        .lower()
                    )

                    try:

                        angka_float = float(
                            angka_text
                        )


                        if satuan in [
                            "ribu",
                            "rb"
                        ]:

                            nominal = int(
                                angka_float * 1000
                            )


                        elif satuan in [
                            "juta",
                            "jt"
                        ]:

                            nominal = int(
                                angka_float * 1000000
                            )


                        elif satuan in [
                            "miliar",
                            "milyar"
                        ]:

                            nominal = int(
                                angka_float * 1000000000
                            )


                    except Exception as e:

                        print(
                            "❌ ERROR parsing satuan:",
                            repr(e)
                        )

                        nominal = 0


            # ====================================================
            # VALIDASI NOMINAL
            # ====================================================

            if not nominal or nominal <= 0:

                kirim_wa(
                    sender,
                    """❌ *Nominal Pemasukan Tidak Ditemukan.*

    Contoh:

    💰 saya dapat sumbangan 4000000
    💰 saya dapat gaji 5000000
    💰 menerima transfer 750000
    💰 dapat bonus 1000000
    💰 uang masuk 2 juta"""
                )

                return jsonify({
                    "status": True
                })


            # ====================================================
            # KETERANGAN
            # ====================================================

            keterangan = data.get(
                "keterangan"
            )


            if not keterangan:

                keterangan = message


            keterangan = str(
                keterangan
            ).strip()


            # ====================================================
            # BERSIHKAN NOMINAL ANGKA DARI KETERANGAN
            #
            # "saya dapat sumbangan 4000000"
            #
            # menjadi:
            #
            # "saya dapat sumbangan"
            # ====================================================

            keterangan = re.sub(
                r'\s+(?:rp\s*)?[\d.,]+\s*$',
                '',
                keterangan,
                flags=re.IGNORECASE
            ).strip()


            # ====================================================
            # BERSIHKAN:
            #
            # 4 juta
            # 500 ribu
            # 1 miliar
            # ====================================================

            keterangan = re.sub(
                r'\s+\d+(?:[.,]\d+)?\s*'
                r'(?:juta|jt|ribu|rb|miliar|milyar)\s*$',
                '',
                keterangan,
                flags=re.IGNORECASE
            ).strip()


            # ====================================================
            # FALLBACK KETERANGAN
            # ====================================================

            if not keterangan:

                keterangan = "Pemasukan"


            # ====================================================
            # NOMOR OWNER
            # ====================================================

            nomor = get_owner_number(
                sender
            )


            # ====================================================
            # DEBUG SEBELUM SIMPAN
            # ====================================================

            print("========================================")
            print("💰 SIMPAN PEMASUKAN")
            print("SENDER     :", sender)
            print("OWNER      :", nomor)
            print("NOMINAL    :", nominal)
            print("KETERANGAN :", keterangan)
            print("========================================")


            # ====================================================
            # BUAT TRANSAKSI
            # ====================================================

            trx = Transaksi(

                tanggal=sekarang(),

                tipe="MASUK",

                nominal=nominal,

                keterangan=keterangan,

                nomor_wa=nomor

            )


            db.session.add(
                trx
            )


            # ====================================================
            # COMMIT
            # ====================================================

            db.session.commit()


            # ====================================================
            # TOTAL PEMASUKAN
            # ====================================================

            masuk = transaksi_user(
                nomor
            ).filter(
                Transaksi.tipe == "MASUK"
            ).with_entities(
                db.func.sum(
                    Transaksi.nominal
                )
            ).scalar() or 0


            # ====================================================
            # TOTAL PENGELUARAN
            # ====================================================

            keluar = transaksi_user(
                nomor
            ).filter(
                Transaksi.tipe == "KELUAR"
            ).with_entities(
                db.func.sum(
                    Transaksi.nominal
                )
            ).scalar() or 0


            # ====================================================
            # SALDO
            # ====================================================

            saldo = (
                masuk -
                keluar
            )


            # ====================================================
            # DASHBOARD
            # ====================================================

            try:

                link = generate_dashboard_link(
                    sender
                )

            except Exception as e:

                print(
                    "⚠️ Dashboard link error:",
                    repr(e)
                )

                link = ""


            # ====================================================
            # PESAN WHATSAPP
            # ====================================================

            pesan = f"""✅ *Transaksi Berhasil Dicatat*

    ━━━━━━━━━━━━━━━━━━

    💰 *PEMASUKAN*

    💵 Nominal
    *Rp {nominal:,.0f}*

    📝 Keterangan
    {keterangan}

    🕒 {sekarang().strftime("%d %b %Y • %H:%M")}

    ━━━━━━━━━━━━━━━━━━

    💳 *Saldo Saat Ini*
    *Rp {saldo:,.0f}*
    """


            # ====================================================
            # DASHBOARD
            # ====================================================

            if link:

                pesan += f"""

    🌐 Dashboard
    {link}
    """


            pesan += """

    ━━━━━━━━━━━━━━━━━━
    _ChatSaku Finance Assistant_
    """


            # ====================================================
            # DEBUG KIRIM
            # ====================================================

            print("========================================")
            print("📤 KIRIM BALASAN PEMASUKAN")
            print("SENDER :", sender)
            print("MESSAGE:")
            print(pesan)
            print("========================================")


            # ====================================================
            # KIRIM WHATSAPP
            # ====================================================

            hasil_kirim = kirim_wa(
                sender,
                pesan
            )


            print(
                "📨 HASIL KIRIM WA:",
                hasil_kirim
            )


            # ====================================================
            # SELESAI
            # ====================================================

            return jsonify({

                "status": True,

                "intent": "masuk",

                "action": "create",

                "nominal": nominal,

                "keterangan": keterangan,

                "saldo": saldo

            })


        # ========================================================
        # ERROR
        # ========================================================

        except Exception as e:

            db.session.rollback()

            print("========================================")
            print("❌ ERROR PEMASUKAN")
            print("SENDER :", sender)
            print("MESSAGE:", message)
            print("DATA   :", data)
            print("ERROR  :", repr(e))
            print("========================================")


            kirim_wa(
                sender,
                """❌ *Terjadi kesalahan saat mencatat pemasukan.*

    Silakan coba lagi.

    Contoh:

    💰 saya dapat sumbangan 4000000
    💰 gaji 5000000
    💰 menerima transfer 750000"""
            )


            return jsonify({

                "status": False,

                "error": str(e)

            }), 500

    # =========================
    # KELUAR
    # =========================
    # if cmd.startswith("keluar"):
    if intent == "keluar":

        try:

            # ==================================================
            # AMBIL HASIL NLP
            # ==================================================

            nominal = data.get("nominal")
            keterangan = data.get("keterangan", "")

            # ==================================================
            # FALLBACK NOMINAL DARI PESAN ASLI
            # ==================================================
            # Jika NLP gagal menemukan nominal,
            # ambil angka dari message.
            #
            # Contoh:
            # beli baso dengan arip 30000
            # beli bakso 20.000
            # bayar listrik Rp150.000
            # ==================================================

            if not nominal or nominal <= 0:

                angka = re.findall(
                    r'(?:Rp\s*)?[\d.,]+',
                    message,
                    re.IGNORECASE
                )

                if angka:

                    kandidat = angka[-1]

                    try:
                        nominal = normalize_nominal(kandidat)
                    except Exception:
                        nominal = 0

            # Pastikan integer
            try:
                nominal = int(float(nominal or 0))
            except (ValueError, TypeError):
                nominal = 0

            # ==================================================
            # VALIDASI NOMINAL
            # ==================================================

            if nominal <= 0:

                kirim_wa(
                    sender,
                    """❌ *Nominal tidak ditemukan.*

    Contoh:
    • beli bakso 20000
    • bayar listrik 150000
    • keluar 25000 grab
    """
                )

                return jsonify({"status": True})

            # ==================================================
            # BERSIHKAN KETERANGAN
            # ==================================================

            if not keterangan:
                keterangan = message

            keterangan = keterangan.strip()

            pola_nominal = re.compile(
                r"""
                \s+
                Rp?\s*
                [\d.,]+
                \s*$
                """,
                re.IGNORECASE | re.VERBOSE
            )

            keterangan = pola_nominal.sub("", keterangan).strip()

            if not keterangan:
                keterangan = "Pengeluaran"

            # ==================================================
            # CARI KATEGORI
            # ==================================================

            kategori, subkategori = cari_kategori(keterangan)

            # Fallback jika kategori kosong
            if not kategori:
                kategori = "lainnya"

            if not subkategori:
                subkategori = "lainnya"

            # ==================================================
            # SIMPAN TRANSAKSI
            # ==================================================

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

            print("========================================")
            print("💰 TRANSAKSI KELUAR BERHASIL")
            print("SENDER      :", sender)
            print("NOMINAL     :", nominal)
            print("KETERANGAN  :", keterangan)
            print("KATEGORI    :", kategori)
            print("SUBKATEGORI :", subkategori)
            print("========================================")

            # ==================================================
            # TOTAL SALDO
            # ==================================================

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

            # ==================================================
            # DASHBOARD
            # ==================================================

            link = generate_dashboard_link(sender)

            # ==================================================
            # BUDGET
            # ==================================================

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
                    if budget.nominal > 0
                    else 0
                )

                sisa = budget.nominal - total_keluar

                # Batasi progress bar maksimal 10 blok
                blok = min(10, max(0, int(persen / 10)))

                bar = (
                    "🟩" * blok +
                    "⬜" * (10 - blok)
                )

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
    Rp {max(sisa, 0):,.0f}

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

            # ==================================================
            # KIRIM BALASAN WHATSAPP
            # ==================================================

            pesan = f"""🏦 *Notifikasi Transaksi*
    ──────────────────

    ✅ *Pengeluaran Berhasil Dicatat*

    💸 Nominal
    *Rp {nominal:,.0f}*

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

    🌐 Dashboard
    {link}

    ──────────────────
    _ChatSaku Finance Assistant_
    """

            print("========================================")
            print("📤 MENGIRIM BALASAN WA")
            print("========================================")
            print(pesan)

            hasil_kirim = kirim_wa(
                sender,
                pesan
            )

            print("📨 HASIL KIRIM WA :", hasil_kirim)

            return jsonify({
                "status": True,
                "intent": "keluar",
                "nominal": nominal,
                "keterangan": keterangan
            })

        except ValueError:

            db.session.rollback()

            kirim_wa(
                sender,
                """❌ Nominal tidak valid.

    Contoh:
    beli bakso 20000
    bayar listrik 150000
    keluar 25000 grab"""
            )

            return jsonify({"status": True})

        except Exception as e:

            db.session.rollback()

            print("========================================")
            print("❌ ERROR TRANSAKSI KELUAR")
            print("ERROR :", repr(e))
            print("========================================")

            kirim_wa(
                sender,
                f"""❌ *Terjadi kesalahan saat mencatat transaksi.*

    Silakan coba lagi.

    Contoh:
    beli bakso 20000"""
            )

            return jsonify({
                "status": False,
                "error": str(e)
            }), 500

    # =========================
    # HARI INI
    # =========================
    if cmd == "hari ini":

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

    # ============================================================
    # BUDGET - NLP HANDLER
    # ============================================================

    if intent == "budget":

        nomor = get_owner_number(sender)

        try:

            # ====================================================
            # CEK FITUR
            # ====================================================

            if not has_feature(sender, "budget"):

                kirim_wa(
                    sender,
                    """🔒 *Fitur Budget*

    Fitur Budget hanya tersedia pada paket PRO dan PREMIUM.

    Upgrade sekarang agar dapat:

    ✅ Budget Bulanan
    ✅ Reminder
    ✅ AI Insight
    ✅ Dashboard Lengkap
    """
                )

                return jsonify({"status": True})

            # ====================================================
            # AMBIL HASIL NLP
            # ====================================================

            kategori = data.get("kategori")
            nominal = data.get("nominal")

            # Support "action" maupun "aksi"
            aksi_budget = data.get("action") or data.get("aksi")

            # Normalisasi
            if kategori:

                kategori = str(
                    kategori
                ).lower().strip()

            # ====================================================
            # DEBUG NLP
            # ====================================================

            print("========================================")
            print("🎯 BUDGET NLP RESULT")
            print("SENDER   :", sender)
            print("MESSAGE  :", message)
            print("INTENT   :", intent)
            print("ACTION   :", aksi_budget)
            print("KATEGORI :", kategori)
            print("NOMINAL  :", nominal)
            print("DATA     :", data)
            print("========================================")

            # ====================================================
            # TEXT ASLI
            # ====================================================

            text_budget = (
                message or ""
            ).lower().strip()

            # ====================================================
            # FALLBACK ACTION
            # ====================================================
            #
            # Jika NLP belum mengirim action,
            # kita tentukan dari kalimat user.
            #
            # budget
            # -> lihat
            #
            # buat budget makanan 500000
            # -> buat
            #
            # ubah budget makanan 750000
            # -> update
            #
            # ====================================================

            if not aksi_budget:

                # -----------------------------
                # LIHAT
                # -----------------------------

                if text_budget in [
                    "budget",
                    "lihat budget",
                    "cek budget",
                    "cek budget saya",
                    "lihat budget saya",
                    "tampilkan budget",
                    "tampilkan budget saya",
                    "budget saya"
                ]:

                    aksi_budget = "lihat"

                # -----------------------------
                # UPDATE
                # -----------------------------

                elif any(
                    kata in text_budget
                    for kata in [
                        "ubah budget",
                        "edit budget",
                        "update budget",
                        "ganti budget",
                        "rubah budget"
                    ]
                ):

                    aksi_budget = "update"

                # -----------------------------
                # CREATE
                # -----------------------------

                elif any(
                    kata in text_budget
                    for kata in [
                        "buat budget",
                        "buatkan budget",
                        "bikin budget",
                        "tambahkan budget",
                        "tambah budget",
                        "atur budget"
                    ]
                ):

                    aksi_budget = "buat"

                else:

                    # -------------------------
                    # ADA ANGKA = CREATE
                    # -------------------------

                    angka_test = re.findall(
                        r'(?:rp\s*)?[\d.,]+',
                        text_budget,
                        re.IGNORECASE
                    )

                    if angka_test:

                        aksi_budget = "buat"

                    else:

                        aksi_budget = "lihat"

            # ====================================================
            # FALLBACK NOMINAL
            # ====================================================

            try:

                if nominal:

                    nominal = int(
                        float(nominal)
                    )

                else:

                    nominal = 0

            except (
                ValueError,
                TypeError
            ):

                nominal = 0

            # ====================================================
            # JIKA NLP GAGAL NOMINAL
            # AMBIL DARI PESAN ASLI
            # ====================================================

            if nominal <= 0:

                angka = re.findall(
                    r'(?:rp\s*)?[\d.,]+',
                    text_budget,
                    re.IGNORECASE
                )

                if angka:

                    kandidat = angka[-1]

                    try:

                        nominal = normalize_nominal(
                            kandidat
                        )

                    except Exception:

                        nominal = 0

            # ====================================================
            # FALLBACK KATEGORI
            # ====================================================

            if not kategori:

                for nama_kategori in KATEGORI.keys():

                    if nama_kategori.lower() in text_budget:

                        kategori = (
                            nama_kategori.lower()
                        )

                        break

            # ====================================================
            # ACTION: LIHAT
            # ====================================================

            if aksi_budget in [
                "lihat",
                "view",
                "list",
                "cek",
                "show"
            ]:

                periode = periode_sekarang()

                budgets = Budget.query.filter_by(
                    nomor_wa=nomor,
                    periode=periode
                ).order_by(
                    Budget.kategori.asc()
                ).all()

                # =================================================
                # BELUM ADA BUDGET
                # =================================================

                if not budgets:

                    kirim_wa(
                        sender,
                        f"""📭 *Belum Ada Budget*

    Belum ada budget untuk periode:

    📅 *{periode}*

    Contoh:

    💰 budget makanan 500000
    💰 budget transport 1000000
    """
                    )

                    return jsonify({
                        "status": True
                    })

                # =================================================
                # HEADER
                # =================================================

                pesan = (
                    f"🎯 *Budget Bulan {periode}*\n"
                    f"━━━━━━━━━━━━━━\n\n"
                )

                total_budget = 0
                total_terpakai = 0

                # =================================================
                # PERIODE BULAN
                # =================================================

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

                # =================================================
                # LOOP BUDGET
                # =================================================

                for b in budgets:

                    total_budget += b.nominal

                    # ---------------------------------------------
                    # TOTAL TERPAKAI
                    # ---------------------------------------------

                    terpakai = transaksi_user(
                        nomor
                    ).filter(
                        Transaksi.tipe == "KELUAR",
                        Transaksi.kategori == b.kategori,
                        Transaksi.tanggal >= awal_bulan,
                        Transaksi.tanggal < akhir_bulan
                    ).with_entities(
                        db.func.sum(
                            Transaksi.nominal
                        )
                    ).scalar() or 0

                    total_terpakai += terpakai

                    # ---------------------------------------------
                    # PERSENTASE
                    # ---------------------------------------------

                    persen = (
                        (terpakai / b.nominal) * 100
                        if b.nominal > 0
                        else 0
                    )

                    # ---------------------------------------------
                    # SISA
                    # ---------------------------------------------

                    sisa = (
                        b.nominal - terpakai
                    )

                    # ---------------------------------------------
                    # PROGRESS BAR
                    # ---------------------------------------------

                    blok = min(
                        10,
                        max(
                            0,
                            int(persen / 10)
                        )
                    )

                    progress = (
                        "🟩" * blok +
                        "⬜" * (10 - blok)
                    )

                    # ---------------------------------------------
                    # STATUS
                    # ---------------------------------------------

                    if persen < 50:

                        status = "🟢 Aman"

                    elif persen < 80:

                        status = "🟡 Waspada"

                    elif persen <= 100:

                        status = "🟠 Hampir Habis"

                    else:

                        status = "🔴 Terlampaui"

                    # ---------------------------------------------
                    # TAMBAHKAN KE PESAN
                    # ---------------------------------------------

                    pesan += (
                        f"📂 *{b.kategori.title()}*\n"
                        f"💰 Budget   : "
                        f"Rp {b.nominal:,.0f}\n"
                        f"📉 Terpakai : "
                        f"Rp {terpakai:,.0f}\n"
                        f"💵 Sisa     : "
                        f"Rp {max(sisa, 0):,.0f}\n"
                        f"📊 {persen:.1f}%\n"
                        f"{progress}\n"
                        f"{status}\n\n"
                    )

                # =================================================
                # TOTAL BUDGET
                # =================================================

                pesan += (
                    "━━━━━━━━━━━━━━\n"
                )

                total_sisa = (
                    total_budget -
                    total_terpakai
                )

                total_persen = (
                    (total_terpakai / total_budget) * 100
                    if total_budget > 0
                    else 0
                )

                blok = min(
                    10,
                    max(
                        0,
                        int(total_persen / 10)
                    )
                )

                progress_total = (
                    "🟩" * blok +
                    "⬜" * (10 - blok)
                )

                pesan += (
                    f"💼 *TOTAL BUDGET*\n\n"
                    f"💰 Budget   : "
                    f"Rp {total_budget:,.0f}\n"
                    f"📉 Terpakai : "
                    f"Rp {total_terpakai:,.0f}\n"
                    f"💵 Sisa     : "
                    f"Rp {max(total_sisa, 0):,.0f}\n\n"
                    f"📊 {total_persen:.1f}%\n"
                    f"{progress_total}"
                )

                # =================================================
                # KIRIM
                # =================================================

                kirim_wa(
                    sender,
                    pesan
                )

                return jsonify({
                    "status": True
                })

            # ====================================================
            # ACTION CREATE / UPDATE
            # ====================================================

            if aksi_budget not in [
                "buat",
                "create",
                "update",
                "edit"
            ]:

                kirim_wa(
                    sender,
                    """❌ *Perintah Budget Tidak Dipahami.*

    Contoh:

    • budget
    • buat budget makanan 500000
    • budget transport 1000000
    • ubah budget makanan 750000"""
                )

                return jsonify({
                    "status": True
                })

            # ====================================================
            # VIEWER CHECK
            # ====================================================

            if is_viewer(sender):

                kirim_wa(
                    sender,
                    """🔒 *Mode Viewer*

    Anda hanya dapat melihat Budget.

    Perubahan Budget hanya dapat dilakukan oleh Owner."""
                )

                return jsonify({
                    "status": True
                })

            # ====================================================
            # VALIDASI KATEGORI
            # ====================================================

            if not kategori:

                daftar = "\n".join(
                    f"• {x.title()}"
                    for x in KATEGORI.keys()
                )

                kirim_wa(
                    sender,
                    f"""❌ *Kategori Budget Belum Ditemukan.*

    Kategori yang tersedia:

    {daftar}

    Contoh:

    💰 budget makanan 500000"""
                )

                return jsonify({
                    "status": True
                })

            # ====================================================
            # NORMALISASI KATEGORI
            # ====================================================

            kategori = str(
                kategori
            ).lower().strip()

            # ====================================================
            # VALIDASI KATEGORI
            # ====================================================

            if kategori not in KATEGORI.keys():

                daftar = "\n".join(
                    f"• {x.title()}"
                    for x in KATEGORI.keys()
                )

                kirim_wa(
                    sender,
                    f"""❌ *Kategori Tidak Tersedia.*

    Kategori:

    {daftar}

    Contoh:

    budget makanan 500000"""
                )

                return jsonify({
                    "status": True
                })

            # ====================================================
            # VALIDASI NOMINAL
            # ====================================================

            if nominal <= 0:

                kirim_wa(
                    sender,
                    """❌ *Nominal Budget Tidak Valid.*

    Contoh:

    💰 budget makanan 500000
    💰 budget transport 1000000
    💰 budget listrik 750000"""
                )

                return jsonify({
                    "status": True
                })

            # ====================================================
            # PERIODE
            # ====================================================

            periode = periode_sekarang()

            # ====================================================
            # HITUNG SALDO
            # ====================================================

            saldo = hitung_saldo(
                nomor
            )

            # ====================================================
            # CARI BUDGET LAMA
            # ====================================================

            budget_lama = Budget.query.filter_by(
                nomor_wa=nomor,
                kategori=kategori,
                periode=periode
            ).first()

            # ====================================================
            # TOTAL SEMUA BUDGET
            # ====================================================

            total_budget = db.session.query(
                db.func.coalesce(
                    db.func.sum(
                        Budget.nominal
                    ),
                    0
                )
            ).filter(
                Budget.nomor_wa == nomor,
                Budget.periode == periode
            ).scalar() or 0

            # ====================================================
            # JIKA UPDATE
            # KURANGI BUDGET LAMA
            # ====================================================

            if budget_lama:

                total_budget -= (
                    budget_lama.nominal
                )

            # ====================================================
            # TOTAL SETELAH PERUBAHAN
            # ====================================================

            total_setelah = (
                total_budget +
                nominal
            )

            # ====================================================
            # VALIDASI SALDO
            # ====================================================

            if total_setelah > saldo:

                sisa = max(
                    saldo - total_budget,
                    0
                )

                kirim_wa(
                    sender,
                    f"""⚠️ *Budget Tidak Dapat Disimpan*

    ━━━━━━━━━━━━━━

    💰 Saldo Anda
    *Rp {saldo:,.0f}*

    📊 Total Budget Setelah Disimpan
    *Rp {total_setelah:,.0f}*

    ❌ Total budget melebihi saldo tersedia.

    💵 Maksimal budget tambahan
    *Rp {sisa:,.0f}*

    Silakan kurangi nominal budget atau tambahkan saldo terlebih dahulu."""
                )

                return jsonify({
                    "status": True
                })

            # ====================================================
            # CREATE / UPDATE DATABASE
            # ====================================================

            budget = Budget.query.filter_by(
                nomor_wa=nomor,
                kategori=kategori,
                periode=periode
            ).first()

            # ====================================================
            # UPDATE
            # ====================================================

            if budget:

                budget.nominal = nominal

                status = "Diperbarui"

            # ====================================================
            # CREATE
            # ====================================================

            else:

                budget = Budget(
                    nomor_wa=nomor,
                    kategori=kategori,
                    nominal=nominal,
                    periode=periode,
                    dibuat=sekarang(),
                    auto_repeat=True
                )

                db.session.add(
                    budget
                )

                status = "Dibuat"

            # ====================================================
            # COMMIT
            # ====================================================

            db.session.commit()

            # ====================================================
            # RESPONSE
            # ====================================================

            kirim_wa(
                sender,
                f"""🎯 *Budget {status}*

    ━━━━━━━━━━━━━━

    📂 Kategori
    *{kategori.title()}*

    💰 Budget
    *Rp {nominal:,.0f}*

    📅 Periode
    *{periode}*

    ━━━━━━━━━━━━━━

    Ketik:

    *budget*

    untuk melihat semua budget."""
            )

            print("========================================")
            print("✅ BUDGET BERHASIL")
            print("ACTION   :", aksi_budget)
            print("KATEGORI :", kategori)
            print("NOMINAL  :", nominal)
            print("PERIODE  :", periode)
            print("STATUS   :", status)
            print("========================================")

            return jsonify({
                "status": True,
                "intent": "budget",
                "action": aksi_budget,
                "kategori": kategori,
                "nominal": nominal,
                "periode": periode
            })

        # ========================================================
        # ERROR
        # ========================================================

        except Exception as e:

            db.session.rollback()

            print("========================================")
            print("❌ ERROR BUDGET")
            print("SENDER :", sender)
            print("MESSAGE:", message)
            print("ERROR  :", repr(e))
            print("========================================")

            kirim_wa(
                sender,
                """❌ *Terjadi kesalahan saat memproses Budget.*

    Silakan coba lagi beberapa saat lagi."""
            )

            return jsonify({
                "status": False,
                "error": str(e)
            }), 500

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


    # ============================================================
    # NORMALISASI HUTANG NLP
    # ============================================================

    hutang_nlp = deteksi_hutang_nlp(
        message,
        nlp
    )

    print("========================================")
    print("💳 DETEKSI HUTANG NLP")
    print("MESSAGE :", message)
    print("RESULT  :", hutang_nlp)
    print("========================================")

    if hutang_nlp:

        intent = hutang_nlp.get(
            "intent"
        )

        nlp["intent"] = intent
        nlp["action"] = hutang_nlp.get(
            "action"
        )
        nlp["nama"] = hutang_nlp.get(
            "nama"
        )
        nlp["nominal"] = hutang_nlp.get(
            "nominal"
        )
        nlp["keterangan"] = hutang_nlp.get(
            "keterangan"
        )

        print(
            "💳 INTENT HUTANG DIUBAH:",
            nlp
        )


    # ============================================================
    # DEBUG INTENT FINAL
    # ============================================================

    print("========================================")
    print("🧠 INTENT FINAL")
    print("MESSAGE    :", message)
    print("INTENT     :", intent)
    print("ACTION     :", nlp.get("action"))
    print("NAMA       :", nlp.get("nama"))
    print("NOMINAL    :", nlp.get("nominal"))
    print("KETERANGAN :", nlp.get("keterangan"))
    print("========================================")


    # ============================================================
    # HUTANG NLP
    # ============================================================

    if intent == "hutang":

        if not has_feature(
            sender,
            "hutang"
        ):

            kirim_wa(
                sender,
                """🔒 *Fitur Hutang hanya tersedia pada paket PREMIUM.*

    Upgrade sekarang agar dapat:

    ✅ Budget Bulanan
    ✅ Reminder
    ✅ Target Tabungan
    ✅ Hutang Piutang
    ✅ AI Insight
    ✅ Dashboard Lengkap

    🌐 www.chatsaku.com

    _ChatSaku Finance Assistant_"""
            )

            return jsonify(
                status=True
            )

        action = nlp.get(
            "action"
        )

        # ========================================================
        # LIST HUTANG
        # ========================================================

        if action == "list":

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

    Contoh:

    *hutang ke ucup 20000*

    _ChatSaku Finance Assistant_"""
                )

                return jsonify(
                    status=True
                )

            total = 0

            pesan = "💳 *DAFTAR HUTANG*\n"
            pesan += "━━━━━━━━━━━━━━━━━━\n\n"

            for i, h in enumerate(
                daftar,
                1
            ):

                status_text = (
                    "✅ LUNAS"
                    if h.status == "LUNAS"
                    else "⏳ BELUM LUNAS"
                )

                pesan += (
                    f"*{i}. {h.nama.title()}*\n"
                    f"💰 Rp {(h.nominal or 0):,.0f}\n"
                    f"📌 {status_text}\n"
                    f"📝 {h.keterangan or '-'}\n\n"
                )

                if h.status != "LUNAS":

                    total += (
                        h.nominal or 0
                    )

            pesan += "━━━━━━━━━━━━━━━━━━\n"
            pesan += (
                f"💵 *Total Hutang Aktif*\n"
                f"Rp {total:,.0f}\n\n"
            )

            pesan += (
                "_ChatSaku Finance Assistant_"
            )

            kirim_wa(
                sender,
                pesan
            )

            return jsonify({
                "status": True,
                "intent": "hutang",
                "action": "list"
            })

        # ========================================================
        # CREATE HUTANG
        # ========================================================

        if action == "create":

            nama = nlp.get(
                "nama"
            )

            nominal = nlp.get(
                "nominal"
            )

            keterangan = nlp.get(
                "keterangan"
            ) or ""

            # ====================================================
            # VALIDASI NAMA
            # ====================================================

            if not nama:

                kirim_wa(
                    sender,
                    """❌ *Nama orang belum ditemukan.*

    Contoh:

    *hutang ke ucup 20000*

    *hutang ke budi 500 ribu untuk makan*

    _ChatSaku Finance Assistant_"""
                )

                return jsonify(
                    status=True
                )

            # ====================================================
            # VALIDASI NOMINAL
            # ====================================================

            try:

                nominal = parse_nominal_finance(
                    str(nominal)
                ) if nominal else None

            except Exception:

                nominal = None

            if not nominal or nominal <= 0:

                kirim_wa(
                    sender,
                    """❌ *Nominal hutang belum ditemukan.*

    Contoh:

    *hutang ke ucup 20000*

    *hutang ke budi 500 ribu*"""
                )

                return jsonify(
                    status=True
                )

            # ====================================================
            # NORMALISASI NAMA
            # ====================================================

            nama = re.sub(
                r'\s+',
                ' ',
                str(nama)
            ).strip()

            nama = re.sub(
                r'^(ke|dari)\s+',
                '',
                nama,
                flags=re.IGNORECASE
            ).strip()

            if not nama:

                kirim_wa(
                    sender,
                    "❌ Nama orang belum ditemukan."
                )

                return jsonify(
                    status=True
                )

            # ====================================================
            # CREATE DATABASE
            # ====================================================

            try:

                hp = HutangPiutang(

                    nomor_wa=sender,

                    tipe="HUTANG",

                    nama=nama,

                    nominal=nominal,

                    status="AKTIF",

                    keterangan=keterangan
                )

                db.session.add(
                    hp
                )

                db.session.commit()

            except Exception as e:

                db.session.rollback()

                print(
                    "❌ ERROR CREATE HUTANG:",
                    repr(e)
                )

                kirim_wa(
                    sender,
                    """❌ *Gagal menyimpan hutang.*

    Terjadi kesalahan saat menyimpan data.

    Silakan coba kembali.

    _ChatSaku Finance Assistant_"""
                )

                return jsonify(
                    status=False
                ), 500

            # ====================================================
            # RESPONSE
            # ====================================================

            kirim_wa(
                sender,
                f"""✅ *Hutang Berhasil Dicatat*

    ━━━━━━━━━━━━━━━━━━

    👤 *Kepada*
    {nama.title()}

    💰 *Nominal*
    Rp {nominal:,.0f}

    📝 *Keterangan*
    {keterangan or "-"}

    📌 *Status*
    ⏳ BELUM LUNAS

    ━━━━━━━━━━━━━━━━━━

    Untuk melihat hutang:

    *list hutang*

    _ChatSaku Finance Assistant_"""
            )

            return jsonify({
                "status": True,
                "intent": "hutang",
                "action": "create",
                "nama": nama,
                "nominal": nominal,
                "keterangan": keterangan
            })



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

• hari ini
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

