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

def generate_insight_keluar(
    nomor,
    transaksi_baru,
    periode,
    hari_ini,
    all_data
):

    insight = []

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

    # =====================================================
    # FILTER TRANSAKSI BULAN INI
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
    # 1. INSIGHT TRANSAKSI BARU
    # =====================================================

    if nominal_baru <= 10000:

        insight.append(
            f"💡 Pengeluaran {rupiah(nominal_baru)} "
            f"untuk {keterangan_baru.lower()} sudah dicatat."
        )

        insight.append(
            "Pengeluaran kecil terlihat ringan, "
            "tetapi kalau sering dilakukan tetap "
            "bisa cukup besar dalam sebulan."
        )

    elif nominal_baru <= 50000:

        insight.append(
            f"💡 Pengeluaran {rupiah(nominal_baru)} "
            f"untuk {keterangan_baru.lower()} sudah dicatat."
        )

        insight.append(
            f"Coba perhatikan frekuensi pengeluaran "
            f"*{str(kategori_baru).title()}* "
            f"selama bulan ini."
        )

    else:

        insight.append(
            f"💡 Pengeluaran {rupiah(nominal_baru)} "
            f"untuk {keterangan_baru.lower()} sudah dicatat."
        )

        insight.append(
            f"Pastikan pengeluaran ini masih sesuai "
            f"dengan kebutuhan dan budget "
            f"*{str(kategori_baru).title()}*."
        )

    # =====================================================
    # 2. HITUNG TOTAL KATEGORI
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

            total_kategori += (
                trx.nominal or 0
            )

            jumlah_kategori += 1

    # =====================================================
    # 3. FREKUENSI KATEGORI
    # =====================================================

    if jumlah_kategori >= 3:

        insight.append(
            f"📊 Kamu sudah melakukan "
            f"*{jumlah_kategori} transaksi* "
            f"di kategori "
            f"*{str(kategori_baru).title()}* "
            f"bulan ini."
        )

        insight.append(
            f"Total pengeluaran kategori ini sudah "
            f"{rupiah(total_kategori)}."
        )

    # =====================================================
    # 4. DETEKSI SUBKATEGORI BERULANG
    # =====================================================

    if subkategori_key:

        jumlah_subkategori = 0

        total_subkategori = 0

        for trx in transaksi_bulan_ini:

            if str(trx.tipe or "").upper() != "KELUAR":
                continue

            subkategori_trx = str(
                trx.subkategori or ""
            ).lower().strip()

            if subkategori_trx == subkategori_key:

                jumlah_subkategori += 1

                total_subkategori += (
                    trx.nominal or 0
                )

        if jumlah_subkategori >= 3:

            insight.append(
                f"🔁 Pengeluaran "
                f"*{str(subkategori_baru).title()}* "
                f"sudah tercatat "
                f"{jumlah_subkategori} kali bulan ini."
            )

            insight.append(
                f"Totalnya sudah mencapai "
                f"{rupiah(total_subkategori)}."
            )

    # =====================================================
    # 5. CARI BUDGET KATEGORI
    # =====================================================

    budget = Budget.query.filter_by(
        nomor_wa=nomor,
        kategori=kategori_baru,
        periode=periode
    ).first()

    # =====================================================
    # 6. BUDGET TERSEDIA
    # =====================================================

    if budget:

        nominal_budget = int(
            budget.nominal or 0
        )

        if nominal_budget > 0:

            terpakai = total_kategori

            persen = (
                terpakai /
                nominal_budget
            ) * 100

            sisa = (
                nominal_budget -
                terpakai
            )

            # =============================================
            # BUDGET LEWAT
            # =============================================

            if persen >= 100:

                insight.append(
                    f"🚨 Budget "
                    f"*{str(kategori_baru).title()}* "
                    f"sudah terlampaui."
                )

                insight.append(
                    f"Penggunaan: "
                    f"{rupiah(terpakai)} / "
                    f"{rupiah(nominal_budget)}."
                )

                insight.append(
                    f"Sudah melebihi budget sebesar "
                    f"{rupiah(abs(sisa))}."
                )

            # =============================================
            # BUDGET 90%
            # =============================================

            elif persen >= 90:

                insight.append(
                    f"🚨 Budget "
                    f"*{str(kategori_baru).title()}* "
                    f"tinggal sedikit lagi."
                )

                insight.append(
                    f"Terpakai "
                    f"{persen:.0f}% "
                    f"({rupiah(terpakai)} / "
                    f"{rupiah(nominal_budget)})."
                )

                insight.append(
                    f"Sisa budget sekitar "
                    f"{rupiah(sisa)}."
                )

            # =============================================
            # BUDGET 75%
            # =============================================

            elif persen >= 75:

                insight.append(
                    f"🟡 Budget "
                    f"*{str(kategori_baru).title()}* "
                    f"sudah terpakai "
                    f"{persen:.0f}%."
                )

                insight.append(
                    f"Sisa sekitar "
                    f"{rupiah(sisa)} "
                    f"dari budget "
                    f"{rupiah(nominal_budget)}."
                )

            # =============================================
            # BUDGET 50%
            # =============================================

            elif persen >= 50:

                insight.append(
                    f"🟢 Budget "
                    f"*{str(kategori_baru).title()}* "
                    f"terpakai "
                    f"{persen:.0f}%."
                )

                insight.append(
                    f"Masih tersisa "
                    f"{rupiah(sisa)} "
                    f"untuk kategori ini."
                )

            # =============================================
            # BUDGET < 50%
            # =============================================

            else:

                insight.append(
                    f"🎯 Budget "
                    f"*{str(kategori_baru).title()}* "
                    f"masih cukup aman."
                )

                insight.append(
                    f"Terpakai "
                    f"{persen:.0f}% "
                    f"dan masih tersisa "
                    f"{rupiah(sisa)}."
                )

    # =====================================================
    # 7. BELUM ADA BUDGET
    # =====================================================

    else:

        insight.append(
            f"🎯 Belum ada budget untuk kategori "
            f"*{str(kategori_baru).title()}*."
        )

        insight.append(
            f"Kalau ingin mengontrol pengeluaran "
            f"{str(kategori_baru).lower()}, "
            f"kamu bisa membuat budget."
        )

        insight.append(
            f"💡 Contoh: "
            f"*budget {str(kategori_baru).lower()} 1000000*"
        )

    # =====================================================
    # 8. PENGELUARAN BESAR
    # =====================================================

    if nominal_baru >= 500000:

        insight.append(
            f"⚠️ Pengeluaran ini cukup besar, "
            f"yaitu {rupiah(nominal_baru)}."
        )

        insight.append(
            "Sebaiknya pastikan pengeluaran ini "
            "memang sudah direncanakan."
        )

    # =====================================================
    # FALLBACK
    # =====================================================

    if not insight:

        insight.append(
            f"💡 Pengeluaran "
            f"{rupiah(nominal_baru)} "
            f"untuk "
            f"{keterangan_baru.lower()} "
            f"sudah dicatat."
        )

    return insight


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
