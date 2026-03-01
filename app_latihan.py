import streamlit as st
import simpy
import random
import numpy as np
from datetime import datetime, timedelta
import pandas as pd
from dataclasses import dataclass
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ============================
# KONFIGURASI SIMULASI
# ============================
@dataclass
class Config:
    """Konfigurasi parameter simulasi"""
    # Parameter dasar
    NUM_MAHASISWA: int = 500
    NUM_STAFF_PER_KELOMPOK: int = 2
    NUM_KELOMPOK: int = 2
    
    # Distribusi waktu
    MIN_SERVICE_TIME: float = 1.0
    MAX_SERVICE_TIME: float = 3.0
    
    # Waktu kedatangan
    MEAN_INTERARRIVAL: float = 120 / 500
    
    # Jam mulai
    START_HOUR: int = 8
    START_MINUTE: int = 0
    
    # Seed untuk reproduktibilitas
    RANDOM_SEED: int = 42

# ============================
# MODEL SIMULASI
# ============================
class KantinPrasmananDES:
    def __init__(self, config: Config):
        self.config = config
        self.env = simpy.Environment()
        
        # Resources: Staff per kelompok
        self.kelompok_staff = [
            simpy.Resource(self.env, capacity=config.NUM_STAFF_PER_KELOMPOK)
            for _ in range(config.NUM_KELOMPOK)
        ]
        
        # Antrian tunggal untuk semua mahasiswa
        self.antrian = simpy.Store(self.env)
        
        # Statistik
        self.statistics = {
            'mahasiswa_data': [],
            'queue_lengths': [],
            'queue_times': [],
            'service_times': [],
            'utilization': {i: [] for i in range(config.NUM_KELOMPOK)}
        }
        
        # Waktu mulai simulasi
        self.start_time = datetime(2024, 1, 1, config.START_HOUR, config.START_MINUTE)
        
        # Set random seed
        random.seed(config.RANDOM_SEED)
        np.random.seed(config.RANDOM_SEED)
    
    def waktu_ke_jam(self, waktu_simulasi: float) -> datetime:
        return self.start_time + timedelta(minutes=waktu_simulasi)
    
    def generate_service_time(self) -> float:
        return random.uniform(self.config.MIN_SERVICE_TIME, self.config.MAX_SERVICE_TIME)
    
    def generate_interarrival_time(self) -> float:
        return random.expovariate(1.0 / self.config.MEAN_INTERARRIVAL)
    
    def proses_mahasiswa(self, mahasiswa_id: int):
        waktu_datang = self.env.now
        
        # 1. Masuk ke antrian
        yield self.antrian.put(mahasiswa_id)
        
        # Catat panjang antrian
        self.statistics['queue_lengths'].append({
            'time': self.env.now,
            'queue_length': len(self.antrian.items)
        })
        
        # 2. Tunggu sampai ada staff yang tersedia
        kelompok_terpilih = None
        
        while kelompok_terpilih is None:
            for i, kelompok in enumerate(self.kelompok_staff):
                if kelompok.count < kelompok.capacity:
                    kelompok_terpilih = i
                    break
            
            if kelompok_terpilih is None:
                yield self.env.timeout(0.01)
        
        # 3. Keluar dari antrian
        yield self.antrian.get()
        
        # 4. Hitung waktu tunggu
        waktu_mulai_layanan = self.env.now
        waktu_tunggu = waktu_mulai_layanan - waktu_datang
        
        # 5. Gunakan staff dari kelompok terpilih
        with self.kelompok_staff[kelompok_terpilih].request() as request:
            yield request
            
            # Catat utilisasi
            self.statistics['utilization'][kelompok_terpilih].append({
                'time': self.env.now,
                'in_use': self.kelompok_staff[kelompok_terpilih].count
            })
            
            # 6. Proses layanan
            service_time = self.generate_service_time()
            yield self.env.timeout(service_time)
            
            # 7. Selesai
            waktu_selesai = self.env.now
            
            # Simpan data mahasiswa
            self.statistics['mahasiswa_data'].append({
                'id': mahasiswa_id,
                'waktu_datang': waktu_datang,
                'waktu_mulai': waktu_mulai_layanan,
                'waktu_selesai': waktu_selesai,
                'waktu_tunggu': waktu_tunggu,
                'waktu_layanan': service_time,
                'kelompok': kelompok_terpilih,
                'jam_datang': self.waktu_ke_jam(waktu_datang),
                'jam_selesai': self.waktu_ke_jam(waktu_selesai)
            })
            
            self.statistics['queue_times'].append(waktu_tunggu)
            self.statistics['service_times'].append(service_time)
    
    def proses_kedatangan(self):
        for i in range(self.config.NUM_MAHASISWA):
            self.env.process(self.proses_mahasiswa(i))
            
            if i < self.config.NUM_MAHASISWA - 1:
                interarrival = self.generate_interarrival_time()
                yield self.env.timeout(interarrival)
    
    def run_simulation(self):
        self.env.process(self.proses_kedatangan())
        self.env.run()
        return self.analyze_results()
    
    def analyze_results(self):
        if not self.statistics['mahasiswa_data']:
            return None, None
        
        df = pd.DataFrame(self.statistics['mahasiswa_data'])
        
        results = {
            'total_mahasiswa': len(df),
            'waktu_selesai_terakhir': df['waktu_selesai'].max(),
            'jam_selesai_terakhir': self.waktu_ke_jam(df['waktu_selesai'].max()),
            
            # Statistik waktu tunggu
            'avg_waktu_tunggu': df['waktu_tunggu'].mean(),
            'max_waktu_tunggu': df['waktu_tunggu'].max(),
            'min_waktu_tunggu': df['waktu_tunggu'].min(),
            'std_waktu_tunggu': df['waktu_tunggu'].std(),
            
            # Statistik waktu layanan
            'avg_waktu_layanan': df['waktu_layanan'].mean(),
            'total_waktu_layanan': df['waktu_layanan'].sum(),
            
            # Utilisasi
            'utilisasi_kelompok': {},
            
            # Distribusi per jam
            'distribusi_jam': self.calculate_hourly_distribution(df)
        }
        
        total_simulation_time = df['waktu_selesai'].max()
        for kelompok in range(self.config.NUM_KELOMPOK):
            kelompok_df = df[df['kelompok'] == kelompok]
            if len(kelompok_df) > 0:
                total_service_time = kelompok_df['waktu_layanan'].sum()
                utilisation = (total_service_time / 
                             (total_simulation_time * self.config.NUM_STAFF_PER_KELOMPOK)) * 100
                results['utilisasi_kelompok'][kelompok] = utilisation
            else:
                results['utilisasi_kelompok'][kelompok] = 0
        
        return results, df
    
    def calculate_hourly_distribution(self, df):
        df['jam'] = df['jam_selesai'].dt.hour
        hourly = df.groupby('jam').size().reset_index(name='jumlah')
        return dict(zip(hourly['jam'], hourly['jumlah']))

# ============================
# FUNGSI VISUALISASI PLOTLY
# ============================
def create_wait_time_distribution(df):
    """Buat histogram distribusi waktu tunggu"""
    fig = px.histogram(
        df, 
        x='waktu_tunggu',
        nbins=30,
        title='📊 Distribusi Waktu Tunggu Mahasiswa',
        labels={'waktu_tunggu': 'Waktu Tunggu (menit)', 'count': 'Jumlah Mahasiswa'},
        color_discrete_sequence=['#1f77b4'],
        opacity=0.8
    )
    
    # Tambah garis rata-rata
    avg_wait = df['waktu_tunggu'].mean()
    fig.add_vline(
        x=avg_wait, 
        line_dash="dash", 
        line_color="red",
        annotation_text=f"Rata-rata: {avg_wait:.2f} menit",
        annotation_position="top right"
    )
    
    fig.update_layout(
        xaxis_title="Waktu Tunggu (menit)",
        yaxis_title="Frekuensi",
        showlegend=False,
        hovermode="x unified"
    )
    
    return fig

def create_timeline_chart(df):
    """Buat timeline kedatangan dan penyelesaian"""
    fig = go.Figure()
    
    # Scatter untuk kedatangan
    fig.add_trace(go.Scatter(
        x=df['waktu_datang'],
        y=df['id'],
        mode='markers',
        name='Kedatangan',
        marker=dict(size=5, color='blue', opacity=0.5),
        hovertemplate='Mahasiswa ID: %{y}<br>Waktu: %{x:.1f} menit<extra></extra>'
    ))
    
    # Scatter untuk selesai
    fig.add_trace(go.Scatter(
        x=df['waktu_selesai'],
        y=df['id'],
        mode='markers',
        name='Selesai',
        marker=dict(size=5, color='green', opacity=0.5),
        hovertemplate='Mahasiswa ID: %{y}<br>Waktu: %{x:.1f} menit<extra></extra>'
    ))
    
    fig.update_layout(
        title='📈 Timeline Kedatangan dan Penyelesaian',
        xaxis_title="Waktu Simulasi (menit)",
        yaxis_title="ID Mahasiswa",
        hovermode="closest",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    
    return fig

def create_hourly_distribution_chart(results):
    """Buat chart distribusi per jam"""
    hours = list(results['distribusi_jam'].keys())
    counts = list(results['distribusi_jam'].values())
    
    fig = px.bar(
        x=hours,
        y=counts,
        title='🕐 Distribusi Penyelesaian per Jam',
        labels={'x': 'Jam', 'y': 'Jumlah Mahasiswa'},
        color=counts,
        color_continuous_scale='Viridis'
    )
    
    fig.update_layout(
        xaxis_title="Jam",
        yaxis_title="Jumlah Mahasiswa",
        coloraxis_showscale=False
    )
    
    return fig

def create_service_time_boxplot(df, config):
    """Buat boxplot waktu layanan per kelompok"""
    kelompok_data = []
    kelompok_labels = []
    
    for kelompok in sorted(df['kelompok'].unique()):
        kelompok_df = df[df['kelompok'] == kelompok]
        kelompok_data.append(kelompok_df['waktu_layanan'].values)
        kelompok_labels.append(f'Kelompok {kelompok+1}')
    
    fig = go.Figure()
    
    for i, data in enumerate(kelompok_data):
        fig.add_trace(go.Box(
            y=data,
            name=kelompok_labels[i],
            boxpoints='outliers',
            marker_color=px.colors.qualitative.Set2[i],
            hoverinfo='y'
        ))
    
    fig.update_layout(
        title='👨•🍳 Waktu Layanan per Kelompok Staff',
        yaxis_title="Waktu Layanan (menit)",
        xaxis_title="Kelompok Staff",
        showlegend=True
    )
    
    return fig

def create_queue_length_chart(model):
    """Buat chart panjang antrian sepanjang waktu"""
    if not model.statistics['queue_lengths']:
        return None
    
    queue_df = pd.DataFrame(model.statistics['queue_lengths'])
    
    fig = px.line(
        queue_df,
        x='time',
        y='queue_length',
        title='📊 Panjang Antrian Sepanjang Waktu',
        labels={'time': 'Waktu Simulasi (menit)', 'queue_length': 'Panjang Antrian'},
        color_discrete_sequence=['#ff7f0e']
    )
    
    fig.update_layout(
        xaxis_title="Waktu (menit)",
        yaxis_title="Panjang Antrian",
        hovermode="x unified"
    )
    
    return fig

def create_utilization_gauge_chart(results, config):
    """Buat gauge chart untuk utilisasi staff"""
    avg_util = np.mean(list(results['utilisasi_kelompok'].values()))
    
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=avg_util,
        title={'text': f"Rata-rata Utilisasi Staff ({config.NUM_KELOMPOK} kelompok)"},
        delta={'reference': 80},
        gauge={
            'axis': {'range': [0, 100]},
            'bar': {'color': "darkblue"},
            'steps': [
                {'range': [0, 50], 'color': "lightgray"},
                {'range': [50, 80], 'color': "gray"},
                {'range': [80, 100], 'color': "darkgray"}
            ],
            'threshold': {
                'line': {'color': "red", 'width': 4},
                'thickness': 0.75,
                'value': 90
            }
        }
    ))
    
    fig.update_layout(height=300)
    return fig

# ============================
# APLIKASI STREAMLIT
# ============================
def main():
    st.set_page_config(
        page_title="Simulasi Kantin IT Del",
        page_icon="🍽️",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Sidebar untuk input parameter
    with st.sidebar:
        st.subheader("⚙️ Parameter Simulasi")

        # Input parameter
        num_mahasiswa = st.number_input(
            "Jumlah Mahasiswa", 
            min_value=100, 
            max_value=2000, 
            value=500,
            step=50,
            help="Total mahasiswa yang akan dilayani"
        )
        
        num_kelompok = st.number_input(
            "Jumlah Kelompok Staff", 
            min_value=1, 
            max_value=5, 
            value=2,
            help="Jumlah kelompok staff yang tersedia"
        )
        
        num_staff_per_kelompok = st.number_input(
            "Staff per Kelompok", 
            min_value=1, 
            max_value=5, 
            value=2,
            help="Jumlah staff dalam setiap kelompok"
        )
        
        st.markdown("---")
        
        # Parameter waktu layanan
        st.subheader("⏱️ Parameter Waktu Layanan")
        min_service = st.slider(
            "Waktu Layanan Minimum (menit)",
            min_value=0.5,
            max_value=5.0,
            value=1.0,
            step=0.5
        )
        
        max_service = st.slider(
            "Waktu Layanan Maksimum (menit)",
            min_value=1.0,
            max_value=10.0,
            value=3.0,
            step=0.5
        )
        
        st.markdown("---")
        
        # Jam mulai
        st.subheader("🕐 Waktu Mulai")
        start_hour = st.slider("Jam Mulai", 0, 23, 8)
        start_minute = st.slider("Menit Mulai", 0, 59, 0)
        
        st.markdown("---")
        
        # Tombol aksi
        run_simulation = st.button(
                "🚀 Jalankan Simulasi", 
                type="primary",
                use_container_width=True
            )
            
        reset_params = st.button(
                "🔄 Reset Parameter",
                use_container_width=True
            )
            
        
        if reset_params:
            st.rerun()
    
    # Header utama
    st.title("🍽️ Simulasi Prasmanan di Kantin ITDel")
    st.markdown("""
    **Simulasi Discrete Event System (DES)** untuk analisis kinerja pelayanan kantin 
    dengan variasi jumlah staff dan mahasiswa.
    """)
    
    # Jika tombol di-klik, jalankan simulasi
    if run_simulation:
        with st.spinner("Menjalankan simulasi..."):
            # Setup konfigurasi
            config = Config(
                NUM_MAHASISWA=num_mahasiswa,
                NUM_STAFF_PER_KELOMPOK=num_staff_per_kelompok,
                NUM_KELOMPOK=num_kelompok,
                MIN_SERVICE_TIME=min_service,
                MAX_SERVICE_TIME=max_service,
                START_HOUR=start_hour,
                START_MINUTE=start_minute
            )
            
            # Jalankan simulasi
            model = KantinPrasmananDES(config)
            results, df = model.run_simulation()
            
            if results:
                # Tampilkan summary metrics
                st.success(f"✅ Simulasi selesai! {num_mahasiswa} mahasiswa dilayani.")
                
                # Metrics utama
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric(
                        "⏱️ Waktu Tunggu Rata-rata",
                        f"{results['avg_waktu_tunggu']:.2f} menit"
                    )
                
                with col2:
                    st.metric(
                        "⏰ Waktu Selesai Terakhir",
                        results['jam_selesai_terakhir'].strftime('%H:%M')
                    )
                
                with col3:
                    total_staff = num_kelompok * num_staff_per_kelompok
                    st.metric(
                        "👨•🍳 Total Staff",
                        f"{total_staff} orang"
                    )
                
                with col4:
                    avg_util = np.mean(list(results['utilisasi_kelompok'].values()))
                    st.metric(
                        "📈 Rata-rata Utilisasi",
                        f"{avg_util:.1f}%"
                    )
                
                # Tampilkan detail hasil
                with st.expander("📋 Detail Hasil Simulasi", expanded=False):
                    col_left, col_right = st.columns(2)
                    
                    with col_left:
                        st.subheader("Statistik Waktu Tunggu")
                        st.write(f"**Rata-rata:** {results['avg_waktu_tunggu']:.2f} menit")
                        st.write(f"**Maksimum:** {results['max_waktu_tunggu']:.2f} menit")
                        st.write(f"**Minimum:** {results['min_waktu_tunggu']:.2f} menit")
                        st.write(f"**Standar Deviasi:** {results['std_waktu_tunggu']:.2f} menit")
                        
                        st.subheader("Statistik Waktu Layanan")
                        st.write(f"**Rata-rata:** {results['avg_waktu_layanan']:.2f} menit")
                        st.write(f"**Total:** {results['total_waktu_layanan']:.2f} menit")
                    
                    with col_right:
                        st.subheader("Utilisasi per Kelompok")
                        for kelompok, util in results['utilisasi_kelompok'].items():
                            st.write(f"**Kelompok {kelompok+1}:** {util:.1f}%")
                        
                        st.subheader("Parameter Simulasi")
                        st.write(f"**Jumlah Mahasiswa:** {num_mahasiswa}")
                        st.write(f"**Jumlah Kelompok:** {num_kelompok}")
                        st.write(f"**Staff per Kelompok:** {num_staff_per_kelompok}")
                        st.write(f"**Total Staff:** {num_kelompok * num_staff_per_kelompok}")
                        st.write(f"**Waktu Mulai:** {start_hour:02d}:{start_minute:02d}")
                        st.write(f"**Rentang Waktu Layanan:** {min_service}-{max_service} menit")
                
                # VISUALISASI
                st.markdown("---")
                st.header("📊 Visualisasi Hasil")
                
                # Baris 1: Distribusi waktu tunggu dan timeline
                col1, col2 = st.columns(2)
                
                with col1:
                    fig_wait = create_wait_time_distribution(df)
                    st.plotly_chart(fig_wait, use_container_width=True)
                
                with col2:
                    fig_timeline = create_timeline_chart(df)
                    st.plotly_chart(fig_timeline, use_container_width=True)
                
                # Baris 2: Distribusi per jam dan boxplot
                col3, col4 = st.columns(2)
                
                with col3:
                    fig_hourly = create_hourly_distribution_chart(results)
                    st.plotly_chart(fig_hourly, use_container_width=True)
                
                with col4:
                    fig_boxplot = create_service_time_boxplot(df, config)
                    st.plotly_chart(fig_boxplot, use_container_width=True)
                
                # Baris 3: Panjang antrian dan gauge utilisasi
                col5, col6 = st.columns(2)
                
                with col5:
                    fig_queue = create_queue_length_chart(model)
                    if fig_queue:
                        st.plotly_chart(fig_queue, use_container_width=True)
                
                with col6:
                    fig_gauge = create_utilization_gauge_chart(results, config)
                    st.plotly_chart(fig_gauge, use_container_width=True)
                
                # Tampilkan data tabel
                st.markdown("---")
                st.subheader("📄 Data Hasil Simulasi")
                
                with st.expander("Lihat Data", expanded=False):
                    st.dataframe(
                        df.sort_values('id'),
                        column_config={
                            "id": st.column_config.NumberColumn("ID Mahasiswa"),
                            "waktu_tunggu": st.column_config.NumberColumn("Waktu Tunggu", format="%.2f"),
                            "waktu_layanan": st.column_config.NumberColumn("Waktu Layanan", format="%.2f"),
                            "jam_datang": st.column_config.DatetimeColumn("Waktu Datang"),
                            "jam_selesai": st.column_config.DatetimeColumn("Waktu Selesai"),
                            "kelompok": st.column_config.NumberColumn("Kelompok")
                        },
                        hide_index=True,
                        use_container_width=True
                    )
                    
                    # Tombol download
                    csv = df.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="📥 Download Data CSV",
                        data=csv,
                        file_name=f"simulasi_kantin_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                
                # Analisis sensitivitas otomatis
            else:
                st.error("❌ Gagal menjalankan simulasi!")
    
    else:
        # Tampilan default sebelum simulasi dijalankan
        st.info("""
        ### 🚀 Mulai Simulasi
        
        **Langkah-langkah:**
        1. Atur parameter simulasi di sidebar kiri
        2. Klik tombol **"Jalankan Simulasi"** 
        3. Tunggu proses simulasi selesai
        4. Lihat hasil dan visualisasi
        
        **Parameter default:**
        - Jumlah Mahasiswa: 500
        - Kelompok Staff: 2 kelompok
        - Staff per Kelompok: 2 orang
        - Total Staff: 4 orang
        - Waktu Layanan: 1-3 menit
        - Jam Mulai: 08:00
        """)
        
        # Preview chart kosong
        st.markdown("---")
        st.subheader("🎯 Preview Visualisasi")
        
        col1, col2 = st.columns(2)
        with col1:
            st.write("📊 **Distribusi Waktu Tunggu**")
            st.info("Chart akan muncul setelah simulasi dijalankan")
        
        with col2:
            st.write("📈 **Timeline Pelayanan**")
            st.info("Chart akan muncul setelah simulasi dijalankan")
    
    # Footer
    st.markdown("---")
    st.caption(
        f"**MODSIM: Discrete Event System (DES)** | "
        f"Terakhir diupdate: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    )

if __name__ == "__main__":
    main()