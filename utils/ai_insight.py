from collections import defaultdict
from datetime import date
from calendar import monthrange

from models import (
    Transaksi,
    Budget,
    Reminder,
    TargetPembelian,
)


# =========================================================
# HELPER FORMAT RUPIAH
# =========================================================

def rupiah(nominal):

    try:
        return f"Rp {int(nominal):,.0f}"

    except Exception:
        return "Rp 0"


# =========================================================
# HELPER NOMINAL
# =========================================================

def nominal_transaksi(trx):

    try:
        return int(trx.nominal or 0)

    except Exception:
        return 0


# =========================================================
# HELPER NORMALISASI TANGGAL TRANSAKSI
# =========================================================

def tanggal_transaksi(trx):

    try:

        tanggal = trx.tanggal

        if hasattr(tanggal, "date"):
            return tanggal.date()

        return tanggal

    except Exception:

        return None


# =========================================================
# HELPER NAMA HARI
# =========================================================

def nama_hari(tanggal):

    daftar_hari = [
        "Senin",
        "Selasa",
        "Rabu",
        "Kamis",
        "Jumat",
        "Sabtu",
        "Minggu"
    ]

    try:

        return daftar_hari[
            tanggal.weekday()
        ]

    except Exception:

        return "-"


# =========================================================
# BUILD FINANCE REFERENCE
#
# Reference ini berisi data mentah + statistik
# yang dapat digunakan oleh AI Insight.
# =========================================================

def build_finance_reference(
    nomor,
    periode,
    hari_ini,
    all_data
):

    # =====================================================
    # TRANSAKSI BULAN INI
    # =====================================================

    transaksi_bulan_ini = []

    for trx in all_data:

        tanggal = tanggal_transaksi(trx)

        if not tanggal:
            continue

        if (
            tanggal.year == hari_ini.year
            and tanggal.month == hari_ini.month
        ):

            transaksi_bulan_ini.append(trx)

    # =====================================================
    # PISAH TRANSAKSI
    # =====================================================

    transaksi_masuk = [
        trx
        for trx in transaksi_bulan_ini
        if str(trx.tipe or "").upper() == "MASUK"
    ]

    transaksi_keluar = [
        trx
        for trx in transaksi_bulan_ini
        if str(trx.tipe or "").upper() == "KELUAR"
    ]

    # =====================================================
    # TOTAL
    # =====================================================

    total_masuk = sum(
        nominal_transaksi(x)
        for x in transaksi_masuk
    )

    total_keluar = sum(
        nominal_transaksi(x)
        for x in transaksi_keluar
    )

    saldo = (
        total_masuk -
        total_keluar
    )

    jumlah_masuk = len(
        transaksi_masuk
    )

    jumlah_keluar = len(
        transaksi_keluar
    )

    jumlah_transaksi = (
        jumlah_masuk +
        jumlah_keluar
    )

    # =====================================================
    # RATA-RATA TRANSAKSI
    # =====================================================

    rata_masuk = (

        total_masuk /
        jumlah_masuk

        if jumlah_masuk > 0

        else 0
    )

    rata_keluar = (

        total_keluar /
        jumlah_keluar

        if jumlah_keluar > 0

        else 0
    )

    # =====================================================
    # TRANSAKSI TERBESAR
    # =====================================================

    transaksi_keluar_terbesar = None

    if transaksi_keluar:

        transaksi_keluar_terbesar = max(
            transaksi_keluar,
            key=nominal_transaksi
        )

    transaksi_masuk_terbesar = None

    if transaksi_masuk:

        transaksi_masuk_terbesar = max(
            transaksi_masuk,
            key=nominal_transaksi
        )

    # =====================================================
    # TRANSAKSI TERKECIL
    # =====================================================

    transaksi_keluar_terkecil = None

    if transaksi_keluar:

        transaksi_keluar_terkecil = min(
            transaksi_keluar,
            key=nominal_transaksi
        )

    # =====================================================
    # KATEGORI
    # =====================================================

    kategori_data = defaultdict(
        lambda: {
            "total": 0,
            "jumlah": 0
        }
    )

    # =====================================================
    # SUBKATEGORI
    # =====================================================

    subkategori_data = defaultdict(
        lambda: {
            "total": 0,
            "jumlah": 0
        }
    )

    # =====================================================
    # SUMBER PEMASUKAN
    # =====================================================

    sumber_pemasukan = defaultdict(
        lambda: {
            "total": 0,
            "jumlah": 0
        }
    )

    # =====================================================
    # HARIAN
    # =====================================================

    harian = defaultdict(
        lambda: {
            "masuk": 0,
            "keluar": 0,
            "jumlah": 0
        }
    )

    # =====================================================
    # HARI DALAM MINGGU
    # =====================================================

    hari_mingguan = defaultdict(
        lambda: {
            "masuk": 0,
            "keluar": 0,
            "jumlah": 0
        }
    )

    # =====================================================
    # DATA TRANSAKSI
    # =====================================================

    transaksi_reference = []

    for trx in transaksi_bulan_ini:

        nominal = nominal_transaksi(
            trx
        )

        tanggal = tanggal_transaksi(
            trx
        )

        if not tanggal:
            continue

        tipe = str(
            trx.tipe or ""
        ).upper()

        kategori = str(
            trx.kategori or "Lainnya"
        ).strip()

        subkategori = str(
            trx.subkategori or "Lainnya"
        ).strip()

        keterangan = str(
            trx.keterangan or ""
        ).strip()

        # =================================================
        # REFERENCE TRANSAKSI
        # =================================================

        transaksi_reference.append({

            "tanggal":
                str(tanggal),

            "hari":
                nama_hari(tanggal),

            "tipe":
                tipe,

            "nominal":
                nominal,

            "kategori":
                kategori,

            "subkategori":
                subkategori,

            "keterangan":
                keterangan

        })

        # =================================================
        # HARIAN
        # =================================================

        harian[
            tanggal.day
        ]["jumlah"] += 1

        # =================================================
        # HARI MINGGUAN
        # =================================================

        hari_nama = nama_hari(
            tanggal
        )

        hari_mingguan[
            hari_nama
        ]["jumlah"] += 1

        # =================================================
        # PEMASUKAN
        # =================================================

        if tipe == "MASUK":

            harian[
                tanggal.day
            ]["masuk"] += nominal

            hari_mingguan[
                hari_nama
            ]["masuk"] += nominal

            sumber = (

                trx.kategori
                or trx.subkategori
                or trx.keterangan
                or "Lainnya"

            )

            sumber = str(
                sumber
            ).strip()

            sumber_pemasukan[
                sumber
            ]["total"] += nominal

            sumber_pemasukan[
                sumber
            ]["jumlah"] += 1

        # =================================================
        # PENGELUARAN
        # =================================================

        elif tipe == "KELUAR":

            harian[
                tanggal.day
            ]["keluar"] += nominal

            hari_mingguan[
                hari_nama
            ]["keluar"] += nominal

            kategori_data[
                kategori
            ]["total"] += nominal

            kategori_data[
                kategori
            ]["jumlah"] += 1

            subkategori_data[
                subkategori
            ]["total"] += nominal

            subkategori_data[
                subkategori
            ]["jumlah"] += 1

    # =====================================================
    # KATEGORI REFERENCE
    # =====================================================

    kategori_reference = []

    for nama, data in kategori_data.items():

        total = data["total"]

        jumlah = data["jumlah"]

        persen = (

            total /
            total_keluar *
            100

            if total_keluar > 0

            else 0
        )

        rata = (

            total /
            jumlah

            if jumlah > 0

            else 0
        )

        kategori_reference.append({

            "nama":
                nama,

            "total":
                total,

            "jumlah_transaksi":
                jumlah,

            "persentase":
                round(persen, 2),

            "rata_rata":
                round(rata)

        })

    kategori_reference.sort(
        key=lambda x: x["total"],
        reverse=True
    )

    # =====================================================
    # SUBKATEGORI REFERENCE
    # =====================================================

    subkategori_reference = []

    for nama, data in subkategori_data.items():

        total = data["total"]

        jumlah = data["jumlah"]

        persen = (

            total /
            total_keluar *
            100

            if total_keluar > 0

            else 0
        )

        rata = (

            total /
            jumlah

            if jumlah > 0

            else 0
        )

        subkategori_reference.append({

            "nama":
                nama,

            "total":
                total,

            "jumlah_transaksi":
                jumlah,

            "persentase":
                round(persen, 2),

            "rata_rata":
                round(rata)

        })

    subkategori_reference.sort(
        key=lambda x: x["total"],
        reverse=True
    )

    # =====================================================
    # PEMASUKAN REFERENCE
    # =====================================================

    pemasukan_reference = []

    for nama, data in sumber_pemasukan.items():

        persen = (

            data["total"] /
            total_masuk *
            100

            if total_masuk > 0

            else 0
        )

        pemasukan_reference.append({

            "sumber":
                nama,

            "total":
                data["total"],

            "jumlah":
                data["jumlah"],

            "persentase":
                round(persen, 2)

        })

    pemasukan_reference.sort(
        key=lambda x: x["total"],
        reverse=True
    )

    # =====================================================
    # HARI TERBOROS
    # =====================================================

    hari_terboros = None

    if harian:

        hari_terboros = max(
            harian.items(),
            key=lambda x: x[1]["keluar"]
        )

    # =====================================================
    # HARI TERMURAH
    # =====================================================

    hari_termurah = None

    hari_dengan_pengeluaran = {

        hari: data

        for hari, data in harian.items()

        if data["keluar"] > 0

    }

    if hari_dengan_pengeluaran:

        hari_termurah = min(
            hari_dengan_pengeluaran.items(),
            key=lambda x: x[1]["keluar"]
        )

    # =====================================================
    # HARI MINGGUAN TERBOROS
    # =====================================================

    hari_mingguan_terboros = None

    if hari_mingguan:

        hari_mingguan_terboros = max(
            hari_mingguan.items(),
            key=lambda x: x[1]["keluar"]
        )

    # =====================================================
    # RATA-RATA PENGELUARAN PER HARI
    # =====================================================

    hari_yang_ada_pengeluaran = [

        x

        for x in harian.values()

        if x["keluar"] > 0

    ]

    rata_keluar_hari = (

        total_keluar /
        len(hari_yang_ada_pengeluaran)

        if hari_yang_ada_pengeluaran

        else 0
    )

    # =====================================================
    # RATA-RATA SEMUA HARI BERJALAN
    # =====================================================

    rata_keluar_hari_berjalan = (

        total_keluar /
        hari_ini.day

        if hari_ini.day > 0

        else 0
    )

    # =====================================================
    # TRANSAKSI KECIL
    # =====================================================

    transaksi_kecil = [

        trx

        for trx in transaksi_keluar

        if nominal_transaksi(trx) <= 50000

    ]

    total_transaksi_kecil = sum(

        nominal_transaksi(x)

        for x in transaksi_kecil

    )

    # =====================================================
    # TRANSAKSI BESAR
    # =====================================================

    transaksi_besar = [

        trx

        for trx in transaksi_keluar

        if nominal_transaksi(trx) >= 500000

    ]

    total_transaksi_besar = sum(

        nominal_transaksi(x)

        for x in transaksi_besar

    )

    # =====================================================
    # TRANSAKSI MENENGAH
    # =====================================================

    transaksi_menengah = [

        trx

        for trx in transaksi_keluar

        if (
            50000 <
            nominal_transaksi(trx) <
            500000
        )

    ]

    total_transaksi_menengah = sum(

        nominal_transaksi(x)

        for x in transaksi_menengah

    )

    # =====================================================
    # PERSENTASE BULAN BERJALAN
    # =====================================================

    jumlah_hari = monthrange(
        hari_ini.year,
        hari_ini.month
    )[1]

    persentase_bulan = (

        hari_ini.day /
        jumlah_hari *
        100

    )

    # =====================================================
    # PROYEKSI
    # =====================================================

    proyeksi_bulan = (

        rata_keluar_hari_berjalan *
        jumlah_hari

    )

    # =====================================================
    # CASHFLOW RATIO
    # =====================================================

    rasio_pengeluaran = (

        total_keluar /
        total_masuk *
        100

        if total_masuk > 0

        else None

    )

    rasio_saldo = (

        saldo /
        total_masuk *
        100

        if total_masuk > 0

        else None

    )

    # =====================================================
    # BUDGET
    # =====================================================

    budgets = Budget.query.filter_by(
        nomor_wa=nomor,
        periode=periode
    ).all()

    budget_reference = []

    for budget in budgets:

        nominal_budget = int(
            budget.nominal or 0
        )

        terpakai = kategori_data.get(
            budget.kategori,
            {}
        ).get(
            "total",
            0
        )

        persen = (

            terpakai /
            nominal_budget *
            100

            if nominal_budget > 0

            else 0
        )

        sisa = (

            nominal_budget -
            terpakai

        )

        budget_reference.append({

            "kategori":
                budget.kategori,

            "budget":
                nominal_budget,

            "terpakai":
                terpakai,

            "sisa":
                sisa,

            "persentase":
                round(persen, 2),

            "status":

                "TERLAMPAUI"
                if persen >= 100

                else "KRITIS"
                if persen >= 90

                else "WASPADA"
                if persen >= 75

                else "AMAN"

        })

    budget_reference.sort(
        key=lambda x: x["persentase"],
        reverse=True
    )

    # =====================================================
    # REMINDER
    # =====================================================

    reminders = Reminder.query.filter_by(
        nomor_wa=nomor
    ).all()

    reminder_reference = []

    for reminder in reminders:

        try:

            if isinstance(
                reminder.tanggal,
                int
            ):

                selisih = (

                    reminder.tanggal -
                    hari_ini.day

                )

            else:

                tanggal_reminder = (
                    reminder.tanggal
                )

                if hasattr(
                    tanggal_reminder,
                    "date"
                ):

                    tanggal_reminder = (
                        tanggal_reminder.date()
                    )

                selisih = (

                    tanggal_reminder -
                    hari_ini

                ).days

            reminder_reference.append({

                "nama":
                    reminder.nama,

                "selisih_hari":
                    selisih

            })

        except Exception:

            continue

    reminder_reference.sort(
        key=lambda x: x["selisih_hari"]
    )

    # =====================================================
    # TARGET
    # =====================================================

    targets = TargetPembelian.query.filter_by(
        nomor_wa=nomor,
        aktif=True
    ).all()

    target_reference = []

    for target in targets:

        try:

            nominal_target = int(
                target.target or 0
            )

            terkumpul = int(
                target.terkumpul or 0
            )

            if nominal_target <= 0:
                continue

            progress = (

                terkumpul /
                nominal_target *
                100

            )

            sisa = max(

                nominal_target -
                terkumpul,

                0

            )

            deadline = target.deadline

            if hasattr(
                deadline,
                "date"
            ):

                deadline = deadline.date()

            sisa_hari = (

                deadline -
                hari_ini

            ).days

            target_reference.append({

                "nama":
                    target.nama,

                "target":
                    nominal_target,

                "terkumpul":
                    terkumpul,

                "sisa":
                    sisa,

                "progress":
                    round(progress, 2),

                "deadline":
                    str(deadline),

                "sisa_hari":
                    sisa_hari,

                "status":

                    "TERCAPAI"
                    if progress >= 100

                    else "TERLAMBAT"
                    if sisa_hari < 0

                    else "SEGERA"
                    if sisa_hari <= 7

                    else "BERJALAN"

            })

        except Exception:

            continue

    # =====================================================
    # BEHAVIOUR SIGNAL
    # =====================================================

    behaviour = []

    # -----------------------------------------------------
    # TRANSAKSI KECIL BERULANG
    # -----------------------------------------------------

    if (
        len(transaksi_kecil) >= 5
        and total_keluar > 0
    ):

        persen_kecil = (

            total_transaksi_kecil /
            total_keluar *
            100

        )

        behaviour.append({

            "type":
                "transaksi_kecil_berulang",

            "jumlah":
                len(transaksi_kecil),

            "total":
                total_transaksi_kecil,

            "persentase":
                round(persen_kecil, 2)

        })

    # -----------------------------------------------------
    # TRANSAKSI BESAR
    # -----------------------------------------------------

    if transaksi_besar:

        behaviour.append({

            "type":
                "transaksi_besar",

            "jumlah":
                len(transaksi_besar),

            "total":
                total_transaksi_besar

        })

    # -----------------------------------------------------
    # KATEGORI DOMINAN
    # -----------------------------------------------------

    if kategori_reference:

        kategori_terbesar = (
            kategori_reference[0]
        )

        if (
            kategori_terbesar["persentase"]
            >= 30
        ):

            behaviour.append({

                "type":
                    "kategori_dominan",

                "kategori":
                    kategori_terbesar["nama"],

                "total":
                    kategori_terbesar["total"],

                "persentase":
                    kategori_terbesar["persentase"]

            })

    # -----------------------------------------------------
    # FREKUENSI KATEGORI
    # -----------------------------------------------------

    for item in kategori_reference:

        if item["jumlah_transaksi"] >= 5:

            behaviour.append({

                "type":
                    "kategori_sering",

                "kategori":
                    item["nama"],

                "jumlah":
                    item["jumlah_transaksi"],

                "total":
                    item["total"]

            })

    # -----------------------------------------------------
    # WEEKEND BOROS
    # -----------------------------------------------------

    weekend_keluar = (

        hari_mingguan.get(
            "Sabtu",
            {}
        ).get(
            "keluar",
            0
        )

        +

        hari_mingguan.get(
            "Minggu",
            {}
        ).get(
            "keluar",
            0
        )

    )

    weekday_keluar = (

        total_keluar -
        weekend_keluar

    )

    if (
        weekend_keluar > 0
        and total_keluar > 0
        and weekend_keluar >
        weekday_keluar / 5 * 2
    ):

        behaviour.append({

            "type":
                "weekend_lebih_boros",

            "total_weekend":
                weekend_keluar,

            "total_weekday":
                weekday_keluar

        })

    # -----------------------------------------------------
    # CASHFLOW NEGATIF
    # -----------------------------------------------------

    if total_keluar > total_masuk:

        behaviour.append({

            "type":
                "cashflow_negatif",

            "defisit":
                abs(saldo)

        })

    # -----------------------------------------------------
    # PENGELUARAN TINGGI
    # -----------------------------------------------------

    if (
        rasio_pengeluaran is not None
        and rasio_pengeluaran >= 80
    ):

        behaviour.append({

            "type":
                "pengeluaran_tinggi",

            "persentase":
                round(
                    rasio_pengeluaran,
                    2
                )

        })

    # =====================================================
    # HASIL REFERENCE
    # =====================================================

    return {

        "periode": {

            "tanggal":
                str(hari_ini),

            "hari":
                nama_hari(hari_ini),

            "hari_berjalan":
                hari_ini.day,

            "jumlah_hari":
                jumlah_hari,

            "persentase_bulan":
                round(
                    persentase_bulan,
                    2
                )

        },

        "cashflow": {

            "total_masuk":
                total_masuk,

            "total_keluar":
                total_keluar,

            "saldo":
                saldo,

            "rasio_pengeluaran":
                round(
                    rasio_pengeluaran,
                    2
                )
                if rasio_pengeluaran
                is not None
                else None,

            "rasio_saldo":
                round(
                    rasio_saldo,
                    2
                )
                if rasio_saldo
                is not None
                else None,

            "rata_rata_masuk":
                round(rata_masuk),

            "rata_rata_keluar":
                round(rata_keluar),

            "rata_rata_keluar_per_hari":
                round(
                    rata_keluar_hari_berjalan
                ),

            "rata_rata_hari_ada_pengeluaran":
                round(
                    rata_keluar_hari
                ),

            "proyeksi_bulan":
                round(
                    proyeksi_bulan
                )

        },

        "transaksi": {

            "total":
                jumlah_transaksi,

            "jumlah_masuk":
                jumlah_masuk,

            "jumlah_keluar":
                jumlah_keluar,

            "transaksi_kecil":
                len(transaksi_kecil),

            "nominal_transaksi_kecil":
                total_transaksi_kecil,

            "transaksi_menengah":
                len(transaksi_menengah),

            "nominal_transaksi_menengah":
                total_transaksi_menengah,

            "transaksi_besar":
                len(transaksi_besar),

            "nominal_transaksi_besar":
                total_transaksi_besar

        },

        "transaksi_terbesar": {

            "keluar":

                {

                    "nominal":
                        nominal_transaksi(
                            transaksi_keluar_terbesar
                        )
                        if transaksi_keluar_terbesar
                        else 0,

                    "kategori":
                        getattr(
                            transaksi_keluar_terbesar,
                            "kategori",
                            None
                        )
                        if transaksi_keluar_terbesar
                        else None,

                    "subkategori":
                        getattr(
                            transaksi_keluar_terbesar,
                            "subkategori",
                            None
                        )
                        if transaksi_keluar_terbesar
                        else None,

                    "keterangan":
                        getattr(
                            transaksi_keluar_terbesar,
                            "keterangan",
                            None
                        )
                        if transaksi_keluar_terbesar
                        else None

                },

            "masuk":

                {

                    "nominal":
                        nominal_transaksi(
                            transaksi_masuk_terbesar
                        )
                        if transaksi_masuk_terbesar
                        else 0,

                    "kategori":
                        getattr(
                            transaksi_masuk_terbesar,
                            "kategori",
                            None
                        )
                        if transaksi_masuk_terbesar
                        else None,

                    "keterangan":
                        getattr(
                            transaksi_masuk_terbesar,
                            "keterangan",
                            None
                        )
                        if transaksi_masuk_terbesar
                        else None

                },

            "terkecil":

                {

                    "nominal":
                        nominal_transaksi(
                            transaksi_keluar_terkecil
                        )
                        if transaksi_keluar_terkecil
                        else 0,

                    "kategori":
                        getattr(
                            transaksi_keluar_terkecil,
                            "kategori",
                            None
                        )
                        if transaksi_keluar_terkecil
                        else None

                }

        },

        "kategori":
            kategori_reference,

        "subkategori":
            subkategori_reference,

        "sumber_pemasukan":
            pemasukan_reference,

        "harian": {

            "data":
                dict(harian),

            "hari_terboros":
                hari_terboros[0]
                if hari_terboros
                else None,

            "nominal_hari_terboros":
                hari_terboros[1]["keluar"]
                if hari_terboros
                else 0,

            "hari_termurah":
                hari_termurah[0]
                if hari_termurah
                else None,

            "nominal_hari_termurah":
                hari_termurah[1]["keluar"]
                if hari_termurah
                else 0,

            "pengeluaran_harian_terbesar":
                pengeluaran_harian_terbesar(
                    harian
                )

        },

        "mingguan": {

            "data":
                dict(hari_mingguan),

            "hari_terboros":
                hari_mingguan_terboros[0]
                if hari_mingguan_terboros
                else None,

            "nominal":
                hari_mingguan_terboros[1]["keluar"]
                if hari_mingguan_terboros
                else 0

        },

        "budget":
            budget_reference,

        "reminder":
            reminder_reference,

        "target":
            target_reference,

        "behaviour":
            behaviour,

        "transaksi_detail":
            transaksi_reference

    }


# =========================================================
# HELPER PENGELUARAN HARIAN TERBESAR
# =========================================================

def pengeluaran_harian_terbesar(harian):

    if not harian:
        return None

    try:

        terbesar = max(
            harian.items(),
            key=lambda x: x[1]["keluar"]
        )

        return {

            "tanggal":
                terbesar[0],

            "nominal":
                terbesar[1]["keluar"]

        }

    except Exception:

        return None


# =========================================================
# MAIN AI INSIGHT ROUTER
# =========================================================

def generate_ai_insight(
    nomor,
    transaksi_baru=None,
    event=None
):

    # =====================================================
    # IMPORT LOKAL
    # =====================================================

    from app import transaksi_user, periode_sekarang

    # =====================================================
    # PERIODE
    # =====================================================

    periode = periode_sekarang()

    hari_ini = date.today()

    # =====================================================
    # AMBIL SEMUA TRANSAKSI USER
    # =====================================================

    all_data = transaksi_user(
        nomor
    ).all()

    # =====================================================
    # BUILD REFERENCE
    # =====================================================

    reference = build_finance_reference(

        nomor=nomor,

        periode=periode,

        hari_ini=hari_ini,

        all_data=all_data

    )

    # =====================================================
    # DEBUG REFERENCE
    # =====================================================

    print("========================================")
    print("🧠 CHATSAKU AI REFERENCE")
    print("========================================")

    print(
        "PERIODE :",
        reference["periode"]
    )

    print(
        "CASHFLOW :",
        reference["cashflow"]
    )

    print(
        "TRANSAKSI :",
        reference["transaksi"]
    )

    print(
        "KATEGORI :",
        reference["kategori"]
    )

    print(
        "SUBKATEGORI :",
        reference["subkategori"]
    )

    print(
        "PEMASUKAN :",
        reference["sumber_pemasukan"]
    )

    print(
        "HARIAN :",
        reference["harian"]
    )

    print(
        "MINGGUAN :",
        reference["mingguan"]
    )

    print(
        "BUDGET :",
        reference["budget"]
    )

    print(
        "REMINDER :",
        reference["reminder"]
    )

    print(
        "TARGET :",
        reference["target"]
    )

    print(
        "BEHAVIOUR :",
        reference["behaviour"]
    )

    print("========================================")

    # =====================================================
    # ROUTING EVENT
    # =====================================================

    if str(
        event or ""
    ).upper() == "KELUAR":

        return generate_insight_keluar(

            nomor=nomor,

            transaksi_baru=transaksi_baru,

            periode=periode,

            hari_ini=hari_ini,

            all_data=all_data,

            reference=reference

        )

    # =====================================================
    # FULL INSIGHT
    # =====================================================

    return generate_full_insight(

        nomor=nomor,

        periode=periode,

        hari_ini=hari_ini,

        all_data=all_data,

        reference=reference

    )


# =========================================================
# MODE KELUAR
#
# Insight pendek setelah user mencatat pengeluaran.
# =========================================================

def generate_insight_keluar(

    nomor,

    transaksi_baru,

    periode,

    hari_ini,

    all_data,

    reference

):

    # =====================================================
    # VALIDASI
    # =====================================================

    if not transaksi_baru:

        return [
            "🧠 Belum ada transaksi pengeluaran baru "
            "untuk dianalisis."
        ]

    # =====================================================
    # DATA TRANSAKSI BARU
    # =====================================================

    nominal_baru = nominal_transaksi(
        transaksi_baru
    )

    kategori_baru = (

        transaksi_baru.kategori
        or "Lainnya"

    )

    subkategori_baru = (

        transaksi_baru.subkategori
        or ""

    )

    keterangan_baru = (

        transaksi_baru.keterangan
        or "pengeluaran"

    ).strip()

    kategori_key = str(
        kategori_baru
    ).lower().strip()

    subkategori_key = str(
        subkategori_baru
    ).lower().strip()

    kategori_title = str(
        kategori_baru
    ).title()

    # =====================================================
    # REFERENCE
    # =====================================================

    cashflow = reference[
        "cashflow"
    ]

    kategori_reference = reference[
        "kategori"
    ]

    # =====================================================
    # CARI KATEGORI
    # =====================================================

    data_kategori = None

    for item in kategori_reference:

        if str(
            item["nama"]
        ).lower().strip() == kategori_key:

            data_kategori = item

            break

    # =====================================================
    # CARI SUBKATEGORI
    # =====================================================

    data_subkategori = None

    for item in reference[
        "subkategori"
    ]:

        if str(
            item["nama"]
        ).lower().strip() == subkategori_key:

            data_subkategori = item

            break

    # =====================================================
    # BUDGET
    # =====================================================

    budget_data = None

    for item in reference[
        "budget"
    ]:

        if str(
            item["kategori"]
        ).lower().strip() == kategori_key:

            budget_data = item

            break

    # =====================================================
    # PRIORITAS 1
    # BUDGET TERLAMPAUI
    # =====================================================

    if budget_data:

        persen = budget_data[
            "persentase"
        ]

        sisa = budget_data[
            "sisa"
        ]

        if persen >= 100:

            return [

                f"🚨 Waduh, pengeluaran "
                f"{rupiah(nominal_baru)} untuk "
                f"{keterangan_baru.lower()} membuat "
                f"budget *{kategori_title}* terlampaui "
                f"{rupiah(abs(sisa))}."

            ]

        if persen >= 90:

            return [

                f"⚠️ Hati-hati, budget "
                f"*{kategori_title}* sekarang sudah "
                f"terpakai {persen:.0f}%. "
                f"Tinggal {rupiah(max(sisa, 0))} lagi."

            ]

        if persen >= 75:

            return [

                f"🟡 Pengeluaran ini membuat budget "
                f"*{kategori_title}* sudah terpakai "
                f"{persen:.0f}%. Masih ada "
                f"{rupiah(max(sisa, 0))}."

            ]

    # =====================================================
    # PRIORITAS 2
    # SUBKATEGORI BERULANG
    # =====================================================

    if data_subkategori:

        jumlah = data_subkategori[
            "jumlah_transaksi"
        ]

        total = data_subkategori[
            "total"
        ]

        if jumlah >= 3:

            return [

                f"🔁 Eh, *{subkategori_baru.title()}* "
                f"sudah muncul {jumlah} kali bulan ini. "
                f"Totalnya sudah {rupiah(total)}."

            ]

    # =====================================================
    # PRIORITAS 3
    # KATEGORI SERING
    # =====================================================

    if data_kategori:

        jumlah = data_kategori[
            "jumlah_transaksi"
        ]

        total = data_kategori[
            "total"
        ]

        if jumlah >= 5:

            return [

                f"👀 *{kategori_title}* mulai sering muncul "
                f"di catatan kamu. Sudah {jumlah} transaksi "
                f"dengan total {rupiah(total)} bulan ini."

            ]

    # =====================================================
    # PRIORITAS 4
    # PENGELUARAN BESAR
    # =====================================================

    if nominal_baru >= 500000:

        total_masuk = cashflow[
            "total_masuk"
        ]

        if total_masuk > 0:

            persen = (

                nominal_baru /
                total_masuk *
                100

            )

            if persen >= 20:

                return [

                    f"⚠️ Pengeluaran "
                    f"{rupiah(nominal_baru)} ini cukup besar, "
                    f"sekitar {persen:.0f}% dari pemasukan "
                    f"bulan ini."

                ]

        return [

            f"⚠️ Pengeluaran "
            f"{rupiah(nominal_baru)} untuk "
            f"{keterangan_baru.lower()} cukup besar. "
            f"Pastikan memang sesuai rencana ya."

        ]

    # =====================================================
    # PRIORITAS 5
    # KATEGORI DOMINAN
    # =====================================================

    if data_kategori:

        persen = data_kategori[
            "persentase"
        ]

        if (
            persen >= 40
            and data_kategori[
                "jumlah_transaksi"
            ] >= 2
        ):

            return [

                f"📊 Pengeluaran *{kategori_title}* "
                f"mulai cukup dominan. Sekarang sekitar "
                f"{persen:.0f}% dari seluruh pengeluaran "
                f"bulan ini."

            ]

    # =====================================================
    # PRIORITAS 6
    # PENGELUARAN KECIL BERULANG
    # =====================================================

    if (
        nominal_baru <= 50000
        and data_kategori
        and data_kategori[
            "jumlah_transaksi"
        ] >= 2
    ):

        return [

            f"💡 Nominalnya memang kecil, tapi "
            f"*{kategori_title}* sudah beberapa kali "
            f"muncul bulan ini. Kalau terus berulang, "
            f"totalnya bisa terasa juga."

        ]

    # =====================================================
    # PRIORITAS 7
    # CASHFLOW
    # =====================================================

    total_masuk = cashflow[
        "total_masuk"
    ]

    total_keluar = cashflow[
        "total_keluar"
    ]

    if total_masuk > 0:

        rasio = (

            total_keluar /
            total_masuk *
            100

        )

        if rasio >= 90:

            return [

                f"⚠️ Setelah pengeluaran ini, "
                f"sekitar {rasio:.0f}% pemasukan kamu "
                f"sudah terpakai bulan ini. "

            ]

    # =====================================================
    # FALLBACK
    # =====================================================

    return [

        f"💚 Oke, pengeluaran "
        f"{rupiah(nominal_baru)} untuk "
        f"{keterangan_baru.lower()} sudah dicatat."

    ]


# =========================================================
# FULL INSIGHT
# =========================================================

def generate_full_insight(

    nomor,

    periode,

    hari_ini,

    all_data,

    reference

):

    insight = []

    # =====================================================
    # AMBIL REFERENCE
    # =====================================================

    cashflow = reference[
        "cashflow"
    ]

    transaksi = reference[
        "transaksi"
    ]

    kategori = reference[
        "kategori"
    ]

    behaviour = reference[
        "behaviour"
    ]

    budgets = reference[
        "budget"
    ]

    reminders = reference[
        "reminder"
    ]

    targets = reference[
        "target"
    ]

    # =====================================================
    # TOTAL
    # =====================================================

    total_masuk = cashflow[
        "total_masuk"
    ]

    total_keluar = cashflow[
        "total_keluar"
    ]

    saldo = cashflow[
        "saldo"
    ]

    # =====================================================
    # DATA KOSONG
    # =====================================================

    if (
        total_masuk == 0
        and total_keluar == 0
    ):

        return [

            "🧠 Belum ada cukup transaksi "
            "untuk membaca kondisi keuangan "
            "kamu bulan ini."

        ]

    # =====================================================
    # RINGKASAN
    # =====================================================

    insight.append(

        f"🧠 Bulan ini kamu sudah mencatat "
        f"pemasukan {rupiah(total_masuk)} "
        f"dan pengeluaran {rupiah(total_keluar)}."

    )

    # =====================================================
    # CASHFLOW
    # =====================================================

    if total_masuk > 0:

        rasio = (
            cashflow[
                "rasio_pengeluaran"
            ]
            or 0
        )

        if total_keluar > total_masuk:

            insight.append(

                "⚠️ Pengeluaran kamu saat ini "
                "sudah lebih besar daripada pemasukan. "
                "Coba tahan dulu pengeluaran yang "
                "masih bisa ditunda."

            )

        elif rasio >= 90:

            insight.append(

                "⚠️ Hampir seluruh pemasukan kamu "
                "sudah terpakai bulan ini. Ruang untuk "
                "kebutuhan mendadak mulai tipis."

            )

        elif rasio >= 70:

            insight.append(

                f"🟡 Pengeluaran kamu sudah mencapai "
                f"sekitar {rasio:.0f}% dari pemasukan."

            )

        elif rasio >= 50:

            insight.append(

                "🟢 Cashflow kamu masih cukup baik. "
                "Pengeluaran masih berada di bawah "
                "pemasukan."

            )

        else:

            insight.append(

                "🟢 Sejauh ini cashflow kamu terlihat "
                "cukup sehat dan masih punya ruang "
                "untuk menabung."

            )

    elif total_keluar > 0:

        insight.append(

            "⚠️ Kamu sudah mencatat pengeluaran, "
            "tetapi belum ada pemasukan yang "
            "tercatat bulan ini."

        )

    # =====================================================
    # SALDO
    # =====================================================

    if saldo > 0:

        insight.append(

            f"💰 Setelah transaksi bulan ini, "
            f"saldo bersih tercatat sekitar "
            f"{rupiah(saldo)}."

        )

    elif saldo < 0:

        insight.append(

            f"🚨 Pengeluaran saat ini lebih besar "
            f"{rupiah(abs(saldo))} dibanding pemasukan."

        )

    # =====================================================
    # KATEGORI TERBESAR
    # =====================================================

    if kategori:

        terbesar = kategori[0]

        insight.append(

            f"👀 Yang paling banyak mengambil uang "
            f"kamu saat ini adalah *{str(terbesar['nama']).title()}*, "
            f"sebesar {rupiah(terbesar['total'])} "
            f"atau {terbesar['persentase']:.0f}% "
            f"dari seluruh pengeluaran."

        )

    # =====================================================
    # SUBKATEGORI TERBESAR
    # =====================================================

    subkategori = reference[
        "subkategori"
    ]

    if subkategori:

        terbesar_sub = subkategori[0]

        if (
            terbesar_sub[
                "jumlah_transaksi"
            ] >= 2
        ):

            insight.append(

                f"🔎 Lebih detail lagi, "
                f"*{str(terbesar_sub['nama']).title()}* "
                f"sudah menghabiskan "
                f"{rupiah(terbesar_sub['total'])} "
                f"dalam {terbesar_sub['jumlah_transaksi']} "
                f"transaksi."

            )

    # =====================================================
    # BEHAVIOUR
    # =====================================================

    behaviour_ditampilkan = 0

    for item in behaviour:

        if behaviour_ditampilkan >= 3:
            break

        tipe = item.get(
            "type"
        )

        # -------------------------------------------------
        # TRANSAKSI KECIL
        # -------------------------------------------------

        if tipe == "transaksi_kecil_berulang":

            insight.append(

                f"💡 Ada {item['jumlah']} transaksi kecil "
                f"dengan total {rupiah(item['total'])}. "
                f"Nominal kecil yang sering berulang "
                f"kadang justru paling sulit terasa."

            )

            behaviour_ditampilkan += 1

        # -------------------------------------------------
        # KATEGORI DOMINAN
        # -------------------------------------------------

        elif tipe == "kategori_dominan":

            insight.append(

                f"📊 *{str(item['kategori']).title()}* "
                f"cukup dominan dalam pola pengeluaran kamu, "
                f"mencapai {item['persentase']:.0f}%."

            )

            behaviour_ditampilkan += 1

        # -------------------------------------------------
        # WEEKEND
        # -------------------------------------------------

        elif tipe == "weekend_lebih_boros":

            insight.append(

                f"🗓️ Menariknya, pengeluaran akhir pekan "
                f"cukup besar dibanding hari biasa. "
                f"Mungkin ada pola pengeluaran tertentu "
                f"yang muncul saat weekend."

            )

            behaviour_ditampilkan += 1

        # -------------------------------------------------
        # CASHFLOW NEGATIF
        # -------------------------------------------------

        elif tipe == "cashflow_negatif":

            insight.append(

                f"⚠️ Saat ini pengeluaran sudah lebih besar "
                f"{rupiah(item['defisit'])} dibanding pemasukan."

            )

            behaviour_ditampilkan += 1

    # =====================================================
    # HARI TERBOROS
    # =====================================================

    hari_terboros = reference[
        "harian"
    ].get(
        "hari_terboros"
    )

    nominal_hari_terboros = reference[
        "harian"
    ].get(
        "nominal_hari_terboros",
        0
    )

    if (
        hari_terboros
        and nominal_hari_terboros > 0
    ):

        insight.append(

            f"📅 Hari paling banyak mengeluarkan uang "
            f"sejauh ini adalah tanggal *{hari_terboros}*, "
            f"sekitar {rupiah(nominal_hari_terboros)}."

        )

    # =====================================================
    # BUDGET
    # =====================================================

    budget_perlu_diperhatikan = []

    for budget in budgets:

        persen = budget[
            "persentase"
        ]

        sisa = budget[
            "sisa"
        ]

        if persen >= 100:

            budget_perlu_diperhatikan.append(

                f"🚨 Budget *{str(budget['kategori']).title()}* "
                f"sudah terlampaui "
                f"{rupiah(abs(sisa))}."

            )

        elif persen >= 90:

            budget_perlu_diperhatikan.append(

                f"⚠️ Budget *{str(budget['kategori']).title()}* "
                f"tinggal {rupiah(max(sisa, 0))}."

            )

        elif persen >= 75:

            budget_perlu_diperhatikan.append(

                f"🟡 Budget *{str(budget['kategori']).title()}* "
                f"sudah terpakai {persen:.0f}%."

            )

    if budget_perlu_diperhatikan:

        insight.append(
            "📊 *Budget yang perlu diperhatikan:*"
        )

        insight.extend(
            budget_perlu_diperhatikan[:3]
        )

    elif budgets:

        insight.append(

            "🎯 Budget kamu bulan ini "
            "masih berada dalam batas aman."

        )

    else:

        insight.append(

            "🎯 Kamu belum punya budget bulan ini. "
            "Budget sederhana per kategori bisa "
            "membantu kamu melihat batas pengeluaran."

        )

    # =====================================================
    # PROYEKSI
    # =====================================================

    proyeksi = cashflow[
        "proyeksi_bulan"
    ]

    hari_berjalan = reference[
        "periode"
    ][
        "hari_berjalan"
    ]

    jumlah_hari = reference[
        "periode"
    ][
        "jumlah_hari"
    ]

    if (
        total_keluar > 0
        and hari_berjalan < jumlah_hari
    ):

        insight.append(

            f"📈 Kalau pola pengeluaran sekarang "
            f"terus berjalan, total bulan ini berpotensi "
            f"mencapai sekitar {rupiah(proyeksi)}."

        )

    # =====================================================
    # REMINDER
    # =====================================================

    reminder_dekat = [

        r

        for r in reminders

        if 0 <= r[
            "selisih_hari"
        ] <= 3

    ]

    if reminder_dekat:

        insight.append(
            "🔔 *Ada yang perlu diingat:*"
        )

        for reminder in reminder_dekat[:3]:

            selisih = reminder[
                "selisih_hari"
            ]

            if selisih == 0:

                insight.append(

                    f"📅 *{reminder['nama']}* "
                    f"jatuh tempo hari ini."

                )

            else:

                insight.append(

                    f"⏰ *{reminder['nama']}* "
                    f"jatuh tempo {selisih} hari lagi."

                )

    # =====================================================
    # TARGET
    # =====================================================

    target_perlu_diperhatikan = []

    for target in targets:

        progress = target[
            "progress"
        ]

        sisa = target[
            "sisa"
        ]

        sisa_hari = target[
            "sisa_hari"
        ]

        if progress >= 100:

            target_perlu_diperhatikan.append(

                f"🎉 Target *{target['nama']}* "
                f"sudah tercapai."

            )

        elif sisa_hari < 0:

            target_perlu_diperhatikan.append(

                f"⌛ Target *{target['nama']}* "
                f"melewati deadline dan masih kurang "
                f"{rupiah(sisa)}."

            )

        elif sisa_hari <= 7:

            target_perlu_diperhatikan.append(

                f"⏰ Target *{target['nama']}* "
                f"tinggal {sisa_hari} hari lagi dan "
                f"masih kurang {rupiah(sisa)}."

            )

        elif progress >= 75:

            target_perlu_diperhatikan.append(

                f"💪 Target *{target['nama']}* "
                f"sudah mencapai {progress:.0f}%. "
                f"Tinggal sedikit lagi."

            )

    if target_perlu_diperhatikan:

        insight.append(
            "🎯 *Perkembangan target:*"
        )

        insight.extend(
            target_perlu_diperhatikan[:3]
        )

    # =====================================================
    # SARAN AKHIR
    # =====================================================

    if (
        total_masuk > 0
        and total_keluar > 0
    ):

        if saldo > 0:

            sisa_persen = (

                saldo /
                total_masuk *
                100

            )

            if sisa_persen >= 30:

                insight.append(

                    "✨ *Kalau melihat pola sekarang:* "
                    "kamu masih punya ruang yang cukup "
                    "untuk menabung atau memperkuat "
                    "dana cadangan."

                )

            elif sisa_persen >= 10:

                insight.append(

                    "💡 Masih ada sedikit ruang dari "
                    "pemasukan kamu. Kalau ingin mulai "
                    "menabung, tidak harus besar—yang "
                    "penting konsisten."

                )

            else:

                insight.append(

                    "💡 Sisa pemasukan kamu mulai tipis. "
                    "Coba perhatikan pengeluaran kecil "
                    "yang paling sering muncul."

                )

        else:

            insight.append(

                "💡 Untuk sementara, prioritaskan "
                "kebutuhan utama dan tahan pengeluaran "
                "yang masih bisa ditunda."

            )

    # =====================================================
    # FALLBACK
    # =====================================================

    if not insight:

        insight.append(

            "🧠 Belum cukup data untuk memberikan "
            "analisis keuangan."

        )

    return insight
