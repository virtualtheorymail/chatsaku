from collections import defaultdict
from datetime import date
from calendar import monthrange

from models import (
    Transaksi,
    Budget,
    Reminder,
    TargetPembelian,
)

# from app import transaksi_user, periode_sekarang


# =========================================================
# HELPER FORMAT RUPIAH
# =========================================================

def rupiah(nominal):
    return f"Rp {nominal:,.0f}"


# =========================================================
# AI FINANCE INSIGHT
# =========================================================

def generate_ai_insight(
    nomor,
    transaksi_baru=None,
    event=None
):


    periode = periode_sekarang()

    # =====================================================
    # AMBIL DATA TRANSAKSI
    # =====================================================

    all_data = transaksi_user(nomor).all()

    total_masuk = sum(
        x.nominal or 0
        for x in all_data
        if x.tipe == "MASUK"
    )

    total_keluar = sum(
        x.nominal or 0
        for x in all_data
        if x.tipe == "KELUAR"
    )

    saldo = total_masuk - total_keluar


    # =====================================================
    # HASIL ANALISIS
    # =====================================================

    insight = []

    # =====================================================
    # DATA KATEGORI
    # =====================================================

    kategori = defaultdict(int)

    for trx in all_data:

        if trx.tipe == "KELUAR":

            nama_kategori = (
                trx.kategori or "Lainnya"
            )

            kategori[nama_kategori] += (
                trx.nominal or 0
            )


    # =====================================================
    # HARI BERJALAN
    # =====================================================

    hari_ini = date.today()

    jumlah_hari = monthrange(
        hari_ini.year,
        hari_ini.month
    )[1]

    hari_berjalan = hari_ini.day


    # =====================================================
    # RINGKASAN UTAMA
    # =====================================================

    if total_masuk == 0 and total_keluar == 0:

        insight.append(
            "🧠 Belum ada cukup transaksi untuk membaca kondisi keuangan kamu bulan ini."
        )

    else:

        insight.append(
            f"🧠 Bulan ini kamu sudah mencatat "
            f"pemasukan {rupiah(total_masuk)} "
            f"dan pengeluaran {rupiah(total_keluar)}."
        )


    # =====================================================
    # KONDISI CASHFLOW
    # =====================================================

    if total_masuk > 0:

        rasio_pengeluaran = (
            total_keluar /
            total_masuk
        ) * 100

        if total_keluar > total_masuk:

            insight.append(
                "⚠️ Saat ini pengeluaran kamu lebih besar "
                "daripada pemasukan. Sebaiknya tahan dulu "
                "pengeluaran yang tidak terlalu penting."
            )

        elif rasio_pengeluaran >= 90:

            insight.append(
                "⚠️ Sebagian besar pemasukan kamu sudah "
                "terpakai. Coba sisakan ruang untuk kebutuhan "
                "mendadak atau tabungan."
            )

        elif rasio_pengeluaran >= 70:

            insight.append(
                "🟡 Pengeluaran kamu sudah cukup besar, "
                "sekitar {:.0f}% dari pemasukan.".format(
                    rasio_pengeluaran
                )
            )

        elif rasio_pengeluaran >= 50:

            insight.append(
                "🟢 Kondisi cashflow kamu masih cukup baik. "
                "Pengeluaran masih berada di bawah pemasukan."
            )

        else:

            insight.append(
                "🟢 Cashflow kamu terlihat cukup sehat. "
                "Masih ada ruang untuk menabung atau mencapai target keuangan."
            )

    elif total_keluar > 0:

        insight.append(
            "⚠️ Kamu sudah mencatat pengeluaran, "
            "tetapi belum ada pemasukan yang tercatat bulan ini."
        )


    # =====================================================
    # SALDO
    # =====================================================

    if saldo > 0:

        insight.append(
            f"💰 Setelah seluruh transaksi yang tercatat, "
            f"saldo kamu sekitar {rupiah(saldo)}."
        )

    elif saldo < 0:

        insight.append(
            f"🚨 Pengeluaran saat ini lebih besar "
            f"sebesar {rupiah(abs(saldo))} dibanding pemasukan."
        )

    else:

        insight.append(
            "ℹ️ Pemasukan dan pengeluaran kamu saat ini berada di posisi yang sama."
        )


    # =====================================================
    # KATEGORI TERBESAR
    # =====================================================

    if kategori and total_keluar > 0:

        terbesar = max(
            kategori,
            key=kategori.get
        )

        nominal_terbesar = kategori[terbesar]

        persen_kategori = (
            nominal_terbesar /
            total_keluar
        ) * 100

        insight.append(
            f"🍽️ Pengeluaran terbesar kamu ada di kategori "
            f"*{str(terbesar).title()}*, sekitar "
            f"{rupiah(nominal_terbesar)} "
            f"atau {persen_kategori:.0f}% dari seluruh pengeluaran."
        )

        # -------------------------------------------------
        # SARAN BERDASARKAN KATEGORI
        # -------------------------------------------------

        kategori_lower = str(
            terbesar
        ).lower()

        if any(
            x in kategori_lower
            for x in [
                "makan",
                "makanan",
                "kuliner",
                "jajan"
            ]
        ):

            insight.append(
                "💡 Kalau ingin mulai berhemat, "
                "pengeluaran makanan bisa jadi tempat pertama "
                "yang diperhatikan. Coba tentukan batas harian "
                "agar pengeluaran lebih mudah dikontrol."
            )

        elif any(
            x in kategori_lower
            for x in [
                "transport",
                "bensin",
                "kendaraan",
                "parkir"
            ]
        ):

            insight.append(
                "💡 Pengeluaran transportasi cukup dominan. "
                "Coba perhatikan perjalanan yang sebenarnya "
                "bisa digabung atau dikurangi."
            )

        elif any(
            x in kategori_lower
            for x in [
                "belanja",
                "shopping",
                "kebutuhan"
            ]
        ):

            insight.append(
                "💡 Untuk kategori ini, coba bedakan "
                "antara kebutuhan dan keinginan sebelum melakukan pembelian."
            )


    # =====================================================
    # BUDGET
    # =====================================================

    budget_perlu_diperhatikan = []

    budgets = Budget.query.filter_by(
        nomor_wa=nomor,
        periode=periode
    ).all()

    for budget in budgets:

        terpakai = kategori.get(
            budget.kategori,
            0
        )

        if budget.nominal <= 0:
            continue

        persen = (
            terpakai /
            budget.nominal
        ) * 100

        sisa_budget = max(
            budget.nominal - terpakai,
            0
        )

        if persen >= 100:

            budget_perlu_diperhatikan.append(
                f"🚨 Budget *{budget.kategori.title()}* "
                f"sudah terlampaui sebesar "
                f"{rupiah(terpakai - budget.nominal)}."
            )

        elif persen >= 90:

            budget_perlu_diperhatikan.append(
                f"⚠️ Budget *{budget.kategori.title()}* "
                f"tinggal sekitar {rupiah(sisa_budget)} "
                f"lagi."
            )

        elif persen >= 75:

            budget_perlu_diperhatikan.append(
                f"🟡 Budget *{budget.kategori.title()}* "
                f"sudah terpakai {persen:.0f}%."
            )


    # Tambahkan maksimal 3 budget agar pesan tidak terlalu panjang

    if budget_perlu_diperhatikan:

        insight.append(
            "📊 *Budget yang perlu diperhatikan:*"
        )

        insight.extend(
            budget_perlu_diperhatikan[:3]
        )


    # =====================================================
    # SARAN TABUNGAN
    # =====================================================

    if total_masuk > total_keluar and saldo > 0:

        if total_masuk > 0:

            rasio_sisa = (
                saldo /
                total_masuk
            ) * 100

            if rasio_sisa >= 30:

                insight.append(
                    "💡 Kamu masih punya ruang yang cukup bagus "
                    "untuk menyisihkan sebagian uang ke tabungan."
                )

            elif rasio_sisa >= 10:

                insight.append(
                    "💡 Ada sisa uang yang bisa mulai "
                    "dialihkan ke tabungan meskipun jumlahnya kecil."
                )


    # =====================================================
    # REMINDER
    # =====================================================

    reminders = Reminder.query.filter_by(
        nomor_wa=nomor
    ).all()

    reminder_dekat = []

    for r in reminders:

        try:

            selisih = r.tanggal - hari_ini.day

        except Exception:

            continue

        if selisih == 0:

            reminder_dekat.append(
                f"📅 *{r.nama}* jatuh tempo hari ini."
            )

        elif 0 < selisih <= 3:

            reminder_dekat.append(
                f"⏰ *{r.nama}* jatuh tempo "
                f"{selisih} hari lagi."
            )


    if reminder_dekat:

        insight.append(
            "🔔 *Pengingat terdekat:*"
        )

        insight.extend(
            reminder_dekat[:3]
        )


    # =====================================================
    # TARGET TABUNGAN
    # =====================================================

    targets = TargetPembelian.query.filter_by(
        nomor_wa=nomor,
        aktif=True
    ).all()

    target_diperhatikan = []

    for target in targets:

        if not target.target or target.target <= 0:
            continue

        progress = (
            target.terkumpul /
            target.target
        ) * 100

        sisa = max(
            target.target -
            target.terkumpul,
            0
        )

        try:

            sisa_hari = (
                target.deadline -
                hari_ini
            ).days

        except Exception:

            sisa_hari = None


        if progress >= 100:

            target_diperhatikan.append(
                f"🎉 Target *{target.nama}* sudah tercapai."
            )

        elif sisa_hari is not None and sisa_hari < 0:

            target_diperhatikan.append(
                f"⌛ Target *{target.nama}* "
                f"melewati deadline dan masih kurang "
                f"{rupiah(sisa)}."
            )

        elif sisa_hari is not None and sisa_hari <= 7:

            target_diperhatikan.append(
                f"⏰ Target *{target.nama}* tinggal "
                f"{sisa_hari} hari lagi dan masih kurang "
                f"{rupiah(sisa)}."
            )

        elif progress >= 75:

            target_diperhatikan.append(
                f"💪 Target *{target.nama}* sudah mencapai "
                f"{progress:.0f}%. Tinggal sedikit lagi!"
            )

        else:

            target_diperhatikan.append(
                f"🎯 Target *{target.nama}* baru mencapai "
                f"{progress:.0f}%. Masih perlu "
                f"{rupiah(sisa)}."
            )


    if target_diperhatikan:

        insight.append(
            "🎯 *Perkembangan target kamu:*"
        )

        insight.extend(
            target_diperhatikan[:3]
        )


    # =====================================================
    # SARAN AKHIR
    # =====================================================

    if total_masuk > 0 and total_keluar > 0:

        if total_keluar < total_masuk:

            sisa_persen = (
                saldo /
                total_masuk
            ) * 100

            if sisa_persen >= 20:

                insight.append(
                    "✨ *Saran saya:* kondisi kamu cukup baik. "
                    "Kalau bisa, pertahankan pola ini dan sisihkan "
                    "sebagian saldo untuk tabungan atau dana darurat."
                )

            else:

                insight.append(
                    "💡 *Saran saya:* coba kurangi beberapa "
                    "pengeluaran kecil yang tidak terlalu penting. "
                    "Sedikit penghematan setiap hari bisa terasa besar di akhir bulan."
                )

        else:

            insight.append(
                "💡 *Saran saya:* untuk sementara prioritaskan "
                "kebutuhan utama dan kurangi pengeluaran yang bisa ditunda."
            )


    # =====================================================
    # FALLBACK
    # =====================================================

    if not insight:

        insight.append(
            "🧠 Belum cukup data untuk memberikan analisis keuangan."
        )


    return insight
