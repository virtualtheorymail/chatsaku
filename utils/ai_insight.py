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
# HELPER NORMALISASI TANGGAL TRANSAKSI
# =========================================================

def tanggal_transaksi(trx):
    """
    Mengubah tanggal transaksi menjadi object date.
    Mendukung:
    - datetime
    - date
    """

    try:

        tanggal = trx.tanggal

        if hasattr(tanggal, "date"):
            return tanggal.date()

        return tanggal

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
    #
    # Jangan pindahkan ke bagian atas file.
    # Ini untuk mencegah circular import dengan app.py
    # =====================================================

    from app import transaksi_user, periode_sekarang

    # =====================================================
    # PERIODE
    # =====================================================

    periode = periode_sekarang()

    hari_ini = date.today()

    # =====================================================
    # AMBIL TRANSAKSI USER
    # =====================================================

    all_data = transaksi_user(nomor).all()

    # =====================================================
    # ROUTING EVENT
    # =====================================================

    # -----------------------------------------------------
    # TRANSAKSI KELUAR
    # -----------------------------------------------------

    if str(event or "").upper() == "KELUAR":

        return generate_insight_keluar(
            nomor=nomor,
            transaksi_baru=transaksi_baru,
            periode=periode,
            hari_ini=hari_ini,
            all_data=all_data
        )

    # -----------------------------------------------------
    # FULL INSIGHT
    #
    # Dipakai untuk:
    #
    # insight
    #
    # maupun:
    #
    # generate_ai_insight(nomor)
    # -----------------------------------------------------

    return generate_full_insight(
        nomor=nomor,
        periode=periode,
        hari_ini=hari_ini,
        all_data=all_data
    )


# =========================================================
# =========================================================
# MODE KELUAR
# =========================================================
# =========================================================

# =========================================================
# MODE KELUAR - SINGLE LINE AI INSIGHT
# =========================================================

def generate_insight_keluar(
    nomor,
    transaksi_baru,
    periode,
    hari_ini,
    all_data
):

    # =====================================================
    # VALIDASI
    # =====================================================

    if not transaksi_baru:
        return [
            "🧠 Belum ada transaksi pengeluaran baru untuk dianalisis."
        ]

    # =====================================================
    # DATA TRANSAKSI BARU
    # =====================================================

    nominal_baru = int(
        transaksi_baru.nominal or 0
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
    # TOTAL PENGELUARAN BULAN INI
    # =====================================================

    total_keluar = sum(
        int(x.nominal or 0)
        for x in transaksi_bulan_ini
        if str(x.tipe or "").upper() == "KELUAR"
    )

    # =====================================================
    # TOTAL PEMASUKAN BULAN INI
    # =====================================================

    total_masuk = sum(
        int(x.nominal or 0)
        for x in transaksi_bulan_ini
        if str(x.tipe or "").upper() == "MASUK"
    )

    # =====================================================
    # TOTAL KATEGORI
    # =====================================================

    total_kategori = 0
    jumlah_kategori = 0

    for trx in transaksi_bulan_ini:

        if str(trx.tipe or "").upper() != "KELUAR":
            continue

        kategori_trx = str(
            trx.kategori or ""
        ).lower().strip()

        if kategori_trx == kategori_key:

            total_kategori += int(
                trx.nominal or 0
            )

            jumlah_kategori += 1

    # =====================================================
    # SUBKATEGORI
    # =====================================================

    jumlah_subkategori = 0
    total_subkategori = 0

    if subkategori_key:

        for trx in transaksi_bulan_ini:

            if str(trx.tipe or "").upper() != "KELUAR":
                continue

            subkategori_trx = str(
                trx.subkategori or ""
            ).lower().strip()

            if subkategori_trx == subkategori_key:

                jumlah_subkategori += 1

                total_subkategori += int(
                    trx.nominal or 0
                )

    # =====================================================
    # CARI BUDGET
    # =====================================================

    budget = Budget.query.filter_by(
        nomor_wa=nomor,
        kategori=kategori_baru,
        periode=periode
    ).first()

    # =====================================================
    # PRIORITAS 1
    # BUDGET TERLAMPAUI
    # =====================================================

    if budget:

        nominal_budget = int(
            budget.nominal or 0
        )

        if nominal_budget > 0:

            persen = (
                total_kategori /
                nominal_budget
            ) * 100

            sisa = (
                nominal_budget -
                total_kategori
            )

            if persen >= 100:

                return [
                    f"🚨 Pengeluaran {rupiah(nominal_baru)} untuk "
                    f"{keterangan_baru.lower()} membuat budget "
                    f"{kategori_title} terlampaui {rupiah(abs(sisa))}."
                ]

            # =================================================
            # PRIORITAS 2
            # BUDGET 90%
            # =================================================

            if persen >= 90:

                return [
                    f"⚠️ Pengeluaran ini membuat budget "
                    f"{kategori_title} sudah terpakai {persen:.0f}%, "
                    f"tersisa {rupiah(sisa)}."
                ]

            # =================================================
            # PRIORITAS 3
            # BUDGET 75%
            # =================================================

            if persen >= 75:

                return [
                    f"🟡 Pengeluaran {rupiah(nominal_baru)} menambah "
                    f"pemakaian budget {kategori_title} menjadi "
                    f"{persen:.0f}%; masih tersisa {rupiah(sisa)}."
                ]

    # =====================================================
    # PRIORITAS 4
    # PENGELUARAN BERULANG
    # =====================================================

    if jumlah_subkategori >= 3:

        return [
            f"🔁 Pengeluaran {keterangan_baru.lower()} sudah "
            f"{jumlah_subkategori} kali bulan ini dengan total "
            f"{rupiah(total_subkategori)}."
        ]

    if jumlah_kategori >= 5:

        return [
            f"📊 Kategori {kategori_title} sudah {jumlah_kategori} "
            f"kali digunakan bulan ini dengan total "
            f"{rupiah(total_kategori)}."
        ]

    # =====================================================
    # PRIORITAS 5
    # PENGELUARAN BESAR
    # =====================================================

    if nominal_baru >= 500000:

        if total_masuk > 0:

            persen_pemasukan = (
                nominal_baru /
                total_masuk
            ) * 100

            if persen_pemasukan >= 20:

                return [
                    f"⚠️ Pengeluaran {rupiah(nominal_baru)} untuk "
                    f"{keterangan_baru.lower()} cukup besar, sekitar "
                    f"{persen_pemasukan:.0f}% dari pemasukan bulan ini."
                ]

        return [
            f"⚠️ Pengeluaran {rupiah(nominal_baru)} untuk "
            f"{keterangan_baru.lower()} cukup besar, pastikan "
            f"masih sesuai rencana."
        ]

    # =====================================================
    # PRIORITAS 6
    # KONTEKS KATEGORI
    # =====================================================

    if total_keluar > 0:

        persen_total = (
            total_kategori /
            total_keluar
        ) * 100

        if persen_total >= 40 and jumlah_kategori >= 2:

            return [
                f"📊 Pengeluaran {kategori_title} mulai cukup dominan, "
                f"mencapai {persen_total:.0f}% dari total pengeluaran "
                f"bulan ini."
            ]

    # =====================================================
    # PRIORITAS 7
    # PENGELUARAN KECIL TAPI BERULANG
    # =====================================================

    if nominal_baru <= 50000 and jumlah_kategori >= 2:

        return [
            f"💡 Pengeluaran kecil seperti {keterangan_baru.lower()} "
            f"mulai muncul beberapa kali bulan ini; kalau terus "
            f"berulang, totalnya bisa cukup terasa."
        ]

    # =====================================================
    # FALLBACK
    # =====================================================

    return [
        f"💡 Pengeluaran {rupiah(nominal_baru)} untuk "
        f"{keterangan_baru.lower()} sudah dicatat."
    ]


# =========================================================
# =========================================================
# FULL INSIGHT
# =========================================================
# =========================================================

def generate_full_insight(
    nomor,
    periode,
    hari_ini,
    all_data
):

    insight = []

    # =====================================================
    # DATA BULAN INI
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
    # TOTAL PEMASUKAN
    # =====================================================

    total_masuk = sum(
        x.nominal or 0
        for x in transaksi_bulan_ini
        if str(x.tipe or "").upper() == "MASUK"
    )

    # =====================================================
    # TOTAL PENGELUARAN
    # =====================================================

    total_keluar = sum(
        x.nominal or 0
        for x in transaksi_bulan_ini
        if str(x.tipe or "").upper() == "KELUAR"
    )

    # =====================================================
    # SALDO
    # =====================================================

    saldo = total_masuk - total_keluar

    # =====================================================
    # DATA KATEGORI
    # =====================================================

    kategori = defaultdict(int)

    jumlah_transaksi_kategori = defaultdict(int)

    for trx in transaksi_bulan_ini:

        if str(trx.tipe or "").upper() != "KELUAR":
            continue

        nama_kategori = (
            trx.kategori
            or "Lainnya"
        )

        kategori[nama_kategori] += (
            trx.nominal or 0
        )

        jumlah_transaksi_kategori[
            nama_kategori
        ] += 1

    # =====================================================
    # DATA SUBKATEGORI
    # =====================================================

    subkategori = defaultdict(int)

    for trx in transaksi_bulan_ini:

        if str(trx.tipe or "").upper() != "KELUAR":
            continue

        nama_subkategori = (
            trx.subkategori
            or "Lainnya"
        )

        subkategori[nama_subkategori] += (
            trx.nominal or 0
        )

    # =====================================================
    # HARI BERJALAN
    # =====================================================

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
            "🧠 Belum ada cukup transaksi untuk "
            "membaca kondisi keuangan kamu bulan ini."
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
                "Masih ada ruang untuk menabung atau "
                "mencapai target keuangan."
            )

    elif total_keluar > 0:

        insight.append(
            "⚠️ Kamu sudah mencatat pengeluaran, "
            "tetapi belum ada pemasukan yang tercatat "
            "bulan ini."
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
            f"sebesar {rupiah(abs(saldo))} "
            f"dibanding pemasukan bulan ini."
        )

    else:

        insight.append(
            "ℹ️ Pemasukan dan pengeluaran bulan ini "
            "berada di posisi yang sama."
        )

    # =====================================================
    # KATEGORI TERBESAR
    # =====================================================

    if kategori and total_keluar > 0:

        terbesar = max(
            kategori,
            key=kategori.get
        )

        nominal_terbesar = kategori[
            terbesar
        ]

        persen_kategori = (
            nominal_terbesar /
            total_keluar
        ) * 100

        insight.append(
            f"🍽️ Pengeluaran terbesar kamu ada di kategori "
            f"*{str(terbesar).title()}*, sekitar "
            f"{rupiah(nominal_terbesar)} "
            f"atau {persen_kategori:.0f}% "
            f"dari seluruh pengeluaran bulan ini."
        )

        # =================================================
        # SARAN KATEGORI
        # =================================================

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
                "antara kebutuhan dan keinginan sebelum "
                "melakukan pembelian."
            )

    # =====================================================
    # KATEGORI YANG SERING TRANSAKSI
    # =====================================================

    kategori_sering = sorted(
        jumlah_transaksi_kategori.items(),
        key=lambda x: x[1],
        reverse=True
    )

    if kategori_sering:

        nama_kategori, jumlah = kategori_sering[0]

        if jumlah >= 5:

            insight.append(
                f"🔁 Kategori "
                f"*{str(nama_kategori).title()}* "
                f"sudah memiliki {jumlah} transaksi "
                f"bulan ini."
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

        sisa_budget = (
            budget.nominal -
            terpakai
        )

        if persen >= 100:

            budget_perlu_diperhatikan.append(
                f"🚨 Budget "
                f"*{budget.kategori.title()}* "
                f"sudah terlampaui sebesar "
                f"{rupiah(abs(sisa_budget))}."
            )

        elif persen >= 90:

            budget_perlu_diperhatikan.append(
                f"⚠️ Budget "
                f"*{budget.kategori.title()}* "
                f"tinggal sekitar "
                f"{rupiah(max(sisa_budget, 0))} lagi."
            )

        elif persen >= 75:

            budget_perlu_diperhatikan.append(
                f"🟡 Budget "
                f"*{budget.kategori.title()}* "
                f"sudah terpakai "
                f"{persen:.0f}%."
            )

    # =====================================================
    # TAMPILKAN BUDGET
    # =====================================================

    if budget_perlu_diperhatikan:

        insight.append(
            "📊 *Budget yang perlu diperhatikan:*"
        )

        insight.extend(
            budget_perlu_diperhatikan[:3]
        )

    elif budgets:

        insight.append(
            "🎯 Budget kamu saat ini masih "
            "dalam batas yang relatif aman."
        )

    else:

        insight.append(
            "🎯 Kamu belum memiliki budget bulan ini. "
            "Membuat budget per kategori bisa membantu "
            "mengontrol pengeluaran."
        )

    # =====================================================
    # PROYEKSI PENGELUARAN
    # =====================================================

    if (
        total_keluar > 0
        and hari_berjalan > 0
    ):

        rata_harian = (
            total_keluar /
            hari_berjalan
        )

        proyeksi_bulan = (
            rata_harian *
            jumlah_hari
        )

        if jumlah_hari > hari_berjalan:

            insight.append(
                f"📈 Dengan rata-rata pengeluaran "
                f"{rupiah(rata_harian)} per hari, "
                f"pengeluaran bulan ini berpotensi "
                f"mencapai sekitar "
                f"{rupiah(proyeksi_bulan)} "
                f"jika pola ini berlanjut."
            )

    # =====================================================
    # SARAN TABUNGAN
    # =====================================================

    if total_masuk > total_keluar and saldo > 0:

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

            # ---------------------------------------------
            # Jika r.tanggal adalah integer day-of-month
            # ---------------------------------------------

            if isinstance(
                r.tanggal,
                int
            ):

                selisih = (
                    r.tanggal -
                    hari_ini.day
                )

            # ---------------------------------------------
            # Jika r.tanggal adalah date/datetime
            # ---------------------------------------------

            else:

                tanggal_reminder = r.tanggal

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

        except Exception:

            continue

        if selisih == 0:

            reminder_dekat.append(
                f"📅 *{r.nama}* "
                f"jatuh tempo hari ini."
            )

        elif 0 < selisih <= 3:

            reminder_dekat.append(
                f"⏰ *{r.nama}* "
                f"jatuh tempo "
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

        except Exception:

            sisa_hari = None

        if progress >= 100:

            target_diperhatikan.append(
                f"🎉 Target "
                f"*{target.nama}* "
                f"sudah tercapai."
            )

        elif (
            sisa_hari is not None
            and sisa_hari < 0
        ):

            target_diperhatikan.append(
                f"⌛ Target "
                f"*{target.nama}* "
                f"melewati deadline dan masih kurang "
                f"{rupiah(sisa)}."
            )

        elif (
            sisa_hari is not None
            and sisa_hari <= 7
        ):

            target_diperhatikan.append(
                f"⏰ Target "
                f"*{target.nama}* tinggal "
                f"{sisa_hari} hari lagi dan masih kurang "
                f"{rupiah(sisa)}."
            )

        elif progress >= 75:

            target_diperhatikan.append(
                f"💪 Target "
                f"*{target.nama}* sudah mencapai "
                f"{progress:.0f}%. "
                f"Tinggal sedikit lagi!"
            )

        else:

            target_diperhatikan.append(
                f"🎯 Target "
                f"*{target.nama}* baru mencapai "
                f"{progress:.0f}%. "
                f"Masih perlu "
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
                    "Sedikit penghematan setiap hari bisa terasa "
                    "besar di akhir bulan."
                )

        else:

            insight.append(
                "💡 *Saran saya:* untuk sementara prioritaskan "
                "kebutuhan utama dan kurangi pengeluaran "
                "yang bisa ditunda."
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
