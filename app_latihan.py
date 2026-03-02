import streamlit as st
import simpy
import random
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from dataclasses import dataclass

# ============================
# KONFIGURASI
# ============================
@dataclass
class Config:
    NUM_MAHASISWA: int = 500
    NUM_STAFF_PER_KELOMPOK: int = 2
    NUM_KELOMPOK: int = 2
    MIN_SERVICE_TIME: float = 1.0
    MAX_SERVICE_TIME: float = 3.0
    MEAN_INTERARRIVAL: float = 120 / 500
    START_HOUR: int = 8
    START_MINUTE: int = 0
    RANDOM_SEED: int = 42


# ============================
# MODEL SIMULASI
# ============================
class KantinPrasmananDES:
    def __init__(self, config: Config):
        self.config = config
        self.env = simpy.Environment()
        self.staff = simpy.Resource(
            self.env,
            capacity=config.NUM_STAFF_PER_KELOMPOK * config.NUM_KELOMPOK
        )

        self.data = []
        self.queue_lengths = []

        random.seed(config.RANDOM_SEED)
        np.random.seed(config.RANDOM_SEED)

    def service_time(self):
        return random.uniform(
            self.config.MIN_SERVICE_TIME,
            self.config.MAX_SERVICE_TIME
        )

    def interarrival(self):
        return random.expovariate(1.0 / self.config.MEAN_INTERARRIVAL)

    def mahasiswa(self, id):
        datang = self.env.now

        with self.staff.request() as req:
            yield req
            mulai = self.env.now
            tunggu = mulai - datang

            service = self.service_time()
            yield self.env.timeout(service)

            selesai = self.env.now

            self.data.append({
                "ID": id,
                "Datang": datang,
                "Mulai": mulai,
                "Selesai": selesai,
                "Tunggu": tunggu,
                "Layanan": service
            })

    def kedatangan(self):
        for i in range(self.config.NUM_MAHASISWA):
            self.env.process(self.mahasiswa(i))
            yield self.env.timeout(self.interarrival())
            self.queue_lengths.append({
                "Waktu": self.env.now,
                "Antrian": len(self.staff.queue)
            })

    def run(self):
        self.env.process(self.kedatangan())
        self.env.run()
        df = pd.DataFrame(self.data)
        queue_df = pd.DataFrame(self.queue_lengths)
        return df, queue_df


# ============================
# STREAMLIT APP
# ============================
def main():
    st.set_page_config(layout="wide")
    st.title("🍽️ Simulasi Prasmanan Kantin (Streamlit Only)")

    with st.sidebar:
        st.header("⚙️ Parameter")

        mahasiswa = st.number_input("Jumlah Mahasiswa", 100, 2000, 500)
        kelompok = st.number_input("Jumlah Kelompok", 1, 5, 2)
        staff_per_kelompok = st.number_input("Staff per Kelompok", 1, 5, 2)

        min_service = st.slider("Min Service Time", 0.5, 5.0, 1.0)
        max_service = st.slider("Max Service Time", 1.0, 10.0, 3.0)

        run_btn = st.button("🚀 Jalankan Simulasi")

    if run_btn:
        config = Config(
            NUM_MAHASISWA=mahasiswa,
            NUM_KELOMPOK=kelompok,
            NUM_STAFF_PER_KELOMPOK=staff_per_kelompok,
            MIN_SERVICE_TIME=min_service,
            MAX_SERVICE_TIME=max_service
        )

        model = KantinPrasmananDES(config)

        with st.spinner("Menjalankan simulasi..."):
            df, queue_df = model.run()

        st.success("Simulasi selesai!")

        # ============================
        # METRICS
        # ============================
        col1, col2, col3 = st.columns(3)

        col1.metric("Rata-rata Waktu Tunggu",
                    f"{df['Tunggu'].mean():.2f} menit")

        col2.metric("Maksimum Waktu Tunggu",
                    f"{df['Tunggu'].max():.2f} menit")

        col3.metric("Total Waktu Simulasi",
                    f"{df['Selesai'].max():.2f} menit")

        st.divider()

        # ============================
        # VISUALISASI STREAMLIT
        # ============================

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Distribusi Waktu Tunggu")
            st.bar_chart(df["Tunggu"])

        with col2:
            st.subheader("Panjang Antrian")
            if not queue_df.empty:
                st.line_chart(
                    queue_df.set_index("Waktu")
                )

        st.divider()

        col3, col4 = st.columns(2)

        with col3:
            st.subheader("Distribusi Waktu Layanan")
            st.area_chart(df["Layanan"])

        with col4:
            st.subheader("Timeline Selesai")
            st.line_chart(df["Selesai"])

        st.divider()

        st.subheader("Data Lengkap")
        st.dataframe(df, use_container_width=True)

    else:
        st.info("Atur parameter di sidebar lalu klik Jalankan Simulasi 🚀")


if __name__ == "__main__":
    main()