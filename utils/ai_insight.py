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
# AI FINANCE INSIGHT
# =========================================================

def generate_ai_insight(
    nomor,
    transaksi_baru=None,
    event=None
):

    # =====================================================
    # IMPORT LOKAL
    # MENGHINDARI CIRCULAR IMPORT
    # =====================================================

    from app import transaksi_user, periode_sekarang

    periode = periode_sekarang()

    hari_ini = date.today()

    # =====================================================
    # AMBIL SEMUA TRANSAKSI USER
    # =====================================================

    all_data = transaksi_user(nomor).all()

    # =====================================================
    # FILTER TRANSAKSI BULAN INI
    # =====================================================

    transaksi_bulan_ini = []

    for trx in all_data:

        try:
            tanggal_trx = trx.tanggal

            if hasattr(tanggal_trx, "date"):
                tanggal_trx = tanggal_trx.date()

            if (
                tanggal_trx.year == hari_ini.year
                and tanggal_trx.month == hari_ini.month
            ):
                transaksi_bulan_ini.append(trx)

        except Exception:
            continue


    # =====================================================
    # EVENT: KELUAR
    #
    # KHUSUS:
    # - transaksi pengeluaran baru
    # - kategori
    # - subkategori
    # - pengeluaran berulang
    # - total kategori
    # - budget kategori
    #
    # TIDAK:
    # - pemasukan
    # - saldo
    # - reminder
    # - target
    # - tabungan
    # - cashflow
    # =====================================================

    if event == "KELUAR":

        insight = []

        # =================================================
        # VALIDASI TRANSAKSI BARU
        # =================================================

        if not transaksi_baru:

            return [
                "🧠 Belum ada transaksi pengeluaran baru "
                "untuk dianalisis."
            ]


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


        # =================================================
        # 1. INSIGHT TRANSAKSI BARU
        # =================================================

        if nominal_baru <= 10000:

            insight.append(
                f"💡 Pengeluaran "
                f"{rupiah(nominal_baru)} "
                f"untuk {keterangan_baru.lower()} "
                f"sudah dicatat."
            )

            insight.append(
                "Pengeluaran kecil terlihat ringan, "
                "tetapi kalau sering dilakukan tetap "
                "bisa cukup besar dalam sebulan."
            )

        elif nominal_baru <= 50000:

            insight.append(
                f"💡 Pengeluaran "
                f"{rupiah(nominal_baru)} "
                f"untuk {keterangan_baru.lower()} "
                f"sudah dicatat."
            )

            insight.append(
                f"Coba perhatikan frekuensi pengeluaran "
                f"*{str(kategori_baru).title()}* "
                f"selama bulan ini."
            )

        else:

            insight.append(
                f"💡 Pengeluaran "
                f"{rupiah(nominal_baru)} "
                f"untuk {keterangan_baru.lower()} "
                f"sudah dicatat."
            )

            insight.append(
                f"Pastikan pengeluaran ini masih sesuai "
                f"dengan kebutuhan dan budget "
                f"*{str(kategori_baru).title()}*."
            )


        # =================================================
        # 2. HITUNG TOTAL KATEGORI BULAN INI
        # =================================================

        total_kategori = 0
        jumlah_kategori = 0

        for trx in transaksi_bulan_ini:

            if trx.tipe != "KELUAR":
                continue

            if (
                str(trx.kategori or "").lower()
                ==
                str(kategori_baru or "").lower()
            ):

                total_kategori += (
                    trx.nominal or 0
                )

                jumlah_kategori += 1


        # =================================================
        # 3. DETEKSI PENGELUARAN BERULANG
        # =================================================

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


        # =================================================
        # 4. DETEKSI SUBKATEGORI BERULANG
        # =================================================

        if subkategori_baru:

            jumlah_subkategori = 0
            total_subkategori = 0

            for trx in transaksi_bulan_ini:

                if trx.tipe != "KELUAR":
                    continue

                if (
                    str(trx.subkategori or "").lower()
                    ==
                    str(subkategori_baru or "").lower()
                ):

                    jumlah_subkategori += 1

                    total_subkategori += (
                        trx.nominal or 0
                    )


            # =============================================
            # JIKA SUDAH 3X
            # =============================================

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


        # =================================================
        # 5. BUDGET KATEGORI
        # =================================================

        budget = Budget.query.filter_by(
            nomor_wa=nomor,
            kategori=kategori_baru,
            periode=periode
        ).first()


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


                # =========================================
                # BUDGET HABIS / LEWAT
                # =========================================

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


                # =========================================
                # 90%+
                # =========================================

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


                # =========================================
                # 75%+
                # =========================================

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


                # =========================================
                # 50%+
                # =========================================

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


                # =========================================
                # < 50%
                # =========================================

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


        # =================================================
        # 6. TIDAK ADA BUDGET
        # =================================================

        else:

            insight.append(
                f"🎯 Belum ada budget untuk kategori "
                f"*{str(kategori_baru).title()}*."
            )

            insight.append(
                f"Kalau ingin mengontrol pengeluaran "
                f"{str(kategori_baru).lower()}, "
                f"kamu bisa membuat budget, misalnya:"
            )

            insight.append(
                f"💡 *budget "
                f"{str(kategori_baru).lower()} "
                f"1000000*"
            )


        # =================================================
        # 7. INSIGHT KHUSUS PENGELUARAN BESAR
        # =================================================

        if nominal_baru >= 500000:

            insight.append(
                f"⚠️ Pengeluaran ini cukup besar, "
                f"yaitu {rupiah(nominal_baru)}."
            )

            insight.append(
                "Sebaiknya pastikan pengeluaran ini "
                "memang sudah direncanakan."
            )


        # =================================================
        # 8. FALLBACK
        # =================================================

        if not insight:

            insight.append(
                f"💡 Pengeluaran "
                f"{rupiah(nominal_baru)} "
                f"untuk "
                f"{keterangan_baru.lower()} "
                f"sudah dicatat."
            )


        return insight


    # =====================================================
    # EVENT LAIN
    #
    # Untuk sementara jangan keluarkan insight umum.
    # Ini mencegah transaksi KELUAR/MASUK mendapatkan
    # analisis yang tidak relevan.
    # =====================================================

    return []
