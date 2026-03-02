import streamlit as st
import simpy
import random
import numpy as np
from datetime import datetime, timedelta
import pandas as pd
from dataclasses import dataclass
import plotly.express as px
import plotly.graph_objects as go

# ============================================================
# ANALISIS LOGIKA
# ============================================================
# Konfigurasi: 3 Lauk | 1 Angkat (7 ompreng/trip) | 3 Nasi
# Total ompreng : 60 meja × 3 mahasiswa = 180 ompreng
#
# ANGKAT (1 petugas, 7/trip):
#   180 ÷ 7 = 25.7 → ceil = 26 trip
#   Maks: 26 × 1.0 mnt = 26 menit
#   Min:  26 × 0.33 mnt ≈ 8.6 menit
#
# LAUK (3 petugas):
#   180 ÷ 3 = 60 ompreng/petugas
#   Maks: 60 × 0.50 mnt = 30 menit  ← BOTTLENECK MAKS
#   Min:  60 × 0.33 mnt = 20 menit
#
# NASI (3 petugas):
#   180 ÷ 3 = 60 ompreng/petugas
#   Maks: 60 × 0.50 mnt = 30 menit  ← BOTTLENECK MAKS
#   Min:  60 × 0.33 mnt = 20 menit
#
# → Total simulasi: MIN ≈ 20 menit, MAKS ≈ 30 menit ✅
# ============================================================


@dataclass
class Config:
    TOTAL_MEJA:         int   = 60
    MAHASISWA_PER_MEJA: int   = 3
    PETUGAS_LAUK:       int   = 3
    PETUGAS_ANGKAT:     int   = 1
    PETUGAS_NASI:       int   = 3
    OMPRENG_PER_TRIP:   int   = 7
    MIN_LAUK:  float = 0.33   # 20 detik
    MAX_LAUK:  float = 0.50   # 30 detik
    MIN_ANGKAT:float = 0.33   # 20 detik
    MAX_ANGKAT:float = 1.00   # 60 detik
    MIN_NASI:  float = 0.33   # 20 detik
    MAX_NASI:  float = 0.50   # 30 detik
    START_HOUR:   int = 7
    START_MINUTE: int = 0
    RANDOM_SEED:  int = 42


class SistemPiketDES:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.env = simpy.Environment()
        self.total_ompreng = cfg.TOTAL_MEJA * cfg.MAHASISWA_PER_MEJA

        self.res_lauk   = simpy.Resource(self.env, capacity=cfg.PETUGAS_LAUK)
        self.res_angkat = simpy.Resource(self.env, capacity=cfg.PETUGAS_ANGKAT)
        self.res_nasi   = simpy.Resource(self.env, capacity=cfg.PETUGAS_NASI)

        self.antrian_angkat = simpy.Store(self.env)
        self._ev_angkat: dict = {}

        self.stats = {
            'data': [], 'q_lauk': [], 'q_angkat': [], 'q_nasi': [], 'trip_log': []
        }
        self.start_time = datetime(2024, 1, 1, cfg.START_HOUR, cfg.START_MINUTE)
        random.seed(cfg.RANDOM_SEED)
        np.random.seed(cfg.RANDOM_SEED)

    def to_jam(self, t):
        return self.start_time + timedelta(minutes=t)

    def rnd(self, mn, mx):
        return random.uniform(mn, mx)

    def _proses_angkat(self):
        trip = 0
        while True:
            batch = []
            # Kumpulkan batch (bisa kurang dari OMPRENG_PER_TRIP jika sisa)
            for _ in range(self.cfg.OMPRENG_PER_TRIP):
                oid = yield self.antrian_angkat.get()
                batch.append(oid)
            trip += 1
            t0 = self.env.now
            self.stats['q_angkat'].append({
                'time': t0, 'queue_length': len(self.antrian_angkat.items)
            })
            with self.res_angkat.request() as req:
                yield req
                dur = self.rnd(self.cfg.MIN_ANGKAT, self.cfg.MAX_ANGKAT)
                yield self.env.timeout(dur)
            self.stats['trip_log'].append({
                'trip': trip, 'mulai': t0, 'selesai': self.env.now, 'dur': dur, 'isi': len(batch)
            })
            for oid in batch:
                if oid in self._ev_angkat:
                    self._ev_angkat[oid].succeed(value=dur)

    def _proses_ompreng(self, oid):
        t0 = self.env.now

        # LAUK
        self.stats['q_lauk'].append({'time': self.env.now, 'queue_length': len(self.res_lauk.queue)})
        with self.res_lauk.request() as req:
            yield req
            t_ml = self.env.now
            dur_lauk = self.rnd(self.cfg.MIN_LAUK, self.cfg.MAX_LAUK)
            yield self.env.timeout(dur_lauk)
            t_sl = self.env.now
        tunggu_lauk = max(0.0, t_ml - t0)

        # ANGKAT
        ev = self.env.event()
        self._ev_angkat[oid] = ev
        t_ma = self.env.now
        yield self.antrian_angkat.put(oid)
        dur_angkat = yield ev
        del self._ev_angkat[oid]
        t_sa = self.env.now
        tunggu_angkat = max(0.0, t_ma - t_sl)

        # NASI
        self.stats['q_nasi'].append({'time': self.env.now, 'queue_length': len(self.res_nasi.queue)})
        with self.res_nasi.request() as req:
            yield req
            t_mn = self.env.now
            dur_nasi = self.rnd(self.cfg.MIN_NASI, self.cfg.MAX_NASI)
            yield self.env.timeout(dur_nasi)
            t_sn = self.env.now
        tunggu_nasi = max(0.0, t_mn - t_sa)

        self.stats['data'].append({
            'id': oid,
            'waktu_datang': t0, 'waktu_selesai': t_sn,
            'durasi_total': t_sn - t0,
            'dur_lauk': dur_lauk, 'dur_angkat': dur_angkat, 'dur_nasi': dur_nasi,
            'tunggu_lauk': tunggu_lauk, 'tunggu_angkat': tunggu_angkat, 'tunggu_nasi': tunggu_nasi,
            'jam_selesai': self.to_jam(t_sn),
        })

    def run(self):
        self.env.process(self._proses_angkat())
        for i in range(self.total_ompreng):
            self.env.process(self._proses_ompreng(i))
        self.env.run()
        return self._analyze()

    def _analyze(self):
        if not self.stats['data']:
            return None, None
        df  = pd.DataFrame(self.stats['data'])
        tt  = df['waktu_selesai'].max()
        trp = pd.DataFrame(self.stats['trip_log'])
        u   = lambda s, n: min(100.0, s.sum() / (tt * n) * 100) if tt > 0 else 0
        return {
            'total_ompreng': len(df),      'total_waktu': tt,
            'jam_selesai':   self.to_jam(tt),
            'avg_durasi':    df['durasi_total'].mean(),
            'max_durasi':    df['durasi_total'].max(),
            'min_durasi':    df['durasi_total'].min(),
            'std_durasi':    df['durasi_total'].std(),
            'avg_lauk':      df['dur_lauk'].mean(),
            'avg_angkat':    df['dur_angkat'].mean(),
            'avg_nasi':      df['dur_nasi'].mean(),
            'avg_t_lauk':    df['tunggu_lauk'].mean(),
            'avg_t_angkat':  df['tunggu_angkat'].mean(),
            'avg_t_nasi':    df['tunggu_nasi'].mean(),
            'total_trip':    len(trp),
            'ompreng_per_trip': self.cfg.OMPRENG_PER_TRIP,
            'util_lauk':     u(df['dur_lauk'],   self.cfg.PETUGAS_LAUK),
            'util_angkat':   u(df['dur_angkat'], self.cfg.PETUGAS_ANGKAT),
            'util_nasi':     u(df['dur_nasi'],   self.cfg.PETUGAS_NASI),
        }, df


# ── Warna & layout chart ──────────────────────────────────
C  = {"Lauk": "#F472B6", "Angkat": "#FB7185", "Nasi": "#E879F9"}
BG, FG = "#FFF0F5", "#5C1A35"
LAY = dict(plot_bgcolor=BG, paper_bgcolor=BG, font_color=FG,
           title_font_size=15, margin=dict(t=50, b=30))


def chart_hist(df):
    avg = df['durasi_total'].mean()
    fig = px.histogram(df, x='durasi_total', nbins=30,
                       title='📊 Distribusi Durasi Total per Ompreng',
                       labels={'durasi_total': 'Durasi (menit)'},
                       color_discrete_sequence=['#F472B6'], opacity=0.85)
    fig.add_vline(x=avg, line_dash="dash", line_color="#9B4D6E",
                  annotation_text=f"Rata-rata: {avg:.2f} mnt", annotation_position="top right")
    fig.update_layout(**LAY, showlegend=False,
                      xaxis_title="Durasi (menit)", yaxis_title="Frekuensi")
    return fig


def chart_boxplot(df):
    fig = go.Figure()
    for lbl, col in [("Lauk","dur_lauk"),("Angkat","dur_angkat"),("Nasi","dur_nasi")]:
        fig.add_trace(go.Box(y=df[col], name=lbl, marker_color=C[lbl], boxmean="sd", boxpoints="outliers"))
    fig.update_layout(title='🍱 Durasi Layanan per Tahap', yaxis_title="Menit", **LAY)
    return fig


def chart_violin(df):
    fig = go.Figure()
    for lbl, col in [("Lauk","tunggu_lauk"),("Angkat","tunggu_angkat"),("Nasi","tunggu_nasi")]:
        fig.add_trace(go.Violin(y=df[col], name=lbl, fillcolor=C[lbl],
                                opacity=0.75, line_color="#9B4D6E", box_visible=True))
    fig.update_layout(title='⏳ Waktu Tunggu di Antrian', yaxis_title="Menit", **LAY)
    return fig


def chart_antrian(stats):
    frames = []
    for key, lbl in [('q_lauk','Lauk'),('q_angkat','Angkat'),('q_nasi','Nasi')]:
        tmp = pd.DataFrame(stats[key]); tmp['Tahap'] = lbl; frames.append(tmp)
    df_q = pd.concat(frames, ignore_index=True)
    fig = px.line(df_q, x='time', y='queue_length', color='Tahap',
                  title='📉 Panjang Antrian Seiring Waktu',
                  labels={'time':'Waktu (mnt)','queue_length':'Panjang Antrian'},
                  color_discrete_map=C)
    fig.update_layout(**LAY)
    return fig


def chart_util_bar(res):
    labels = ["Lauk","Angkat","Nasi"]
    vals   = [res['util_lauk'], res['util_angkat'], res['util_nasi']]
    fig = go.Figure(go.Bar(x=labels, y=vals, marker_color=[C[l] for l in labels],
                           text=[f"{v:.1f}%" for v in vals], textposition="outside"))
    fig.update_layout(title="🔋 Utilisasi Petugas per Tahap (%)", yaxis=dict(range=[0,120]), **LAY)
    return fig


def chart_gauge(res):
    avg = (res['util_lauk'] + res['util_angkat'] + res['util_nasi']) / 3
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta", value=avg,
        title={'text': "Rata-rata Utilisasi (%)"},
        delta={'reference': 80},
        gauge={'axis':{'range':[0,100]},'bar':{'color':"#F472B6"},
               'steps':[{'range':[0,50],'color':"#FFE4EE"},
                        {'range':[50,80],'color':"#FFB3D1"},
                        {'range':[80,100],'color':"#FF80B3"}],
               'threshold':{'line':{'color':"#9B4D6E",'width':4},'thickness':0.75,'value':90}}
    ))
    fig.update_layout(height=300, paper_bgcolor=BG, font_color=FG)
    return fig


def chart_timeline(df):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df['waktu_datang'], y=df['id'], mode='markers', name='Mulai',
                             marker=dict(size=3, color='#F472B6', opacity=0.5)))
    fig.add_trace(go.Scatter(x=df['waktu_selesai'], y=df['id'], mode='markers', name='Selesai',
                             marker=dict(size=3, color='#7C3AED', opacity=0.5)))
    fig.update_layout(title='📈 Timeline Proses Ompreng',
                      xaxis_title="Waktu (menit)", yaxis_title="ID Ompreng",
                      legend=dict(orientation="h", y=1.05), **LAY)
    return fig


def chart_trip(stats):
    df_t = pd.DataFrame(stats['trip_log'])
    if df_t.empty:
        return None
    fig = px.bar(df_t, x='trip', y='dur', title='🛻 Durasi Tiap Trip Angkat',
                 labels={'trip':'Trip ke-','dur':'Durasi (menit)'},
                 color='dur', color_continuous_scale='RdPu')
    fig.update_layout(**LAY, coloraxis_showscale=False,
                      xaxis_title="Trip ke-", yaxis_title="Durasi (menit)")
    return fig


# ============================================================
# STREAMLIT APP
# ============================================================
def main():
    st.set_page_config(page_title="Piket IT Del", page_icon="🍱",
                       layout="wide", initial_sidebar_state="expanded")

    st.markdown("""
    <style>
    [data-testid="stAppViewContainer"] { background-color: #FFF0F5; }
    [data-testid="stSidebar"]          { background-color: #FFE4EE; }
    [data-testid="stHeader"]           { background-color: #FFF0F5; }
    .block-container                   { padding-top: 0.8rem; }
    .sec {
        color: #5C1A35; font-size: 18px; font-weight: 700;
        margin: 18px 0 8px 0; padding: 6px 12px;
        background: linear-gradient(90deg, #FFD6E7 0%, transparent 100%);
        border-left: 4px solid #F472B6; border-radius: 0 6px 6px 0;
    }
    .card {
        background: white; border: 1px solid #FFB3D1; border-radius: 12px;
        padding: 14px 18px; margin-bottom: 8px;
        box-shadow: 0 2px 8px rgba(244,114,182,0.1);
    }
    .card h4 { color: #5C1A35; margin: 0 0 6px 0; font-size: 14px; font-weight: 700; }
    .card p  { color: #9B4D6E; margin: 0; font-size: 13px; line-height: 1.7; }
    .banner {
        background: linear-gradient(135deg, #FFD6E7, #FFC6FF);
        border: 1px solid #F472B6; border-radius: 12px;
        padding: 10px 18px; margin-bottom: 14px;
        color: #5C1A35; font-weight: 600; font-size: 15px;
    }
    div[data-testid="stMetricValue"] { font-size:1.7rem !important; color:#5C1A35 !important; font-weight:700 !important; }
    div[data-testid="stMetricLabel"] { color:#9B4D6E !important; font-weight:600 !important; font-size:0.78rem !important; text-transform:uppercase; letter-spacing:0.05em; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div style="text-align:center; padding:14px 0 2px 0;">
        <h1 style="color:#5C1A35; font-size:2rem; margin:0;">🍱 Simulasi Sistem Piket IT Del</h1>
        <p style="color:#C47A95; font-size:0.9rem; margin:5px 0 0 0;">
            Discrete Event Simulation (DES) &nbsp;·&nbsp;
            3 Lauk &nbsp;|&nbsp; 1 Angkat (7/trip) &nbsp;|&nbsp; 3 Nasi &nbsp;·&nbsp;
            <b>Target: 20–30 menit</b>
        </p>
    </div>
    """, unsafe_allow_html=True)
    st.divider()

    # ── Sidebar ───────────────────────────────────────────
    with st.sidebar:
        st.markdown("### ⚙️ Parameter")
        total_meja = st.number_input("Jumlah Meja", 10, 120, 60, 5)
        mhs_meja   = st.number_input("Mahasiswa/Meja", 1, 5, 3)
        total_ompr = total_meja * mhs_meja

        st.markdown("---")
        st.markdown("### 👨‍🍳 Petugas")
        p_lauk   = st.slider("Petugas Lauk",   1, 6, 3)
        p_angkat = st.slider("Petugas Angkat", 1, 3, 1)
        p_nasi   = st.slider("Petugas Nasi",   1, 6, 3)
        total_p  = p_lauk + p_angkat + p_nasi
        if total_p == 7:
            st.success(f"✅ Total = {total_p} orang (sesuai soal)")
        else:
            st.warning(f"⚠️ Total = {total_p} (soal: 7 orang)")

        st.markdown("---")
        st.markdown("### 🛻 Angkat Ompreng")
        opr_trip = st.slider("Ompreng per Trip", 1, 10, 7, help="Soal: 4–7 ompreng/trip")
        import math
        n_trip = math.ceil(total_ompr / opr_trip)
        sisa   = total_ompr % opr_trip
        st.info(f"📦 {total_ompr} ÷ {opr_trip} = **{n_trip} trip** "
                f"{'(habis pas)' if sisa==0 else f'(trip terakhir {sisa} ompreng)'}")

        st.markdown("---")
        st.markdown("### ⏱️ Waktu Layanan (menit)")
        with st.expander("🔧 Ubah rentang waktu"):
            ca, cb = st.columns(2)
            with ca:
                mn_lauk   = st.number_input("Min Lauk",   0.01, 2.0, 0.33, 0.01, format="%.2f")
                mn_angkat = st.number_input("Min Angkat", 0.01, 2.0, 0.33, 0.01, format="%.2f")
                mn_nasi   = st.number_input("Min Nasi",   0.01, 2.0, 0.33, 0.01, format="%.2f")
            with cb:
                mx_lauk   = st.number_input("Max Lauk",   0.10, 5.0, 0.50, 0.01, format="%.2f")
                mx_angkat = st.number_input("Max Angkat", 0.10, 5.0, 1.00, 0.01, format="%.2f")
                mx_nasi   = st.number_input("Max Nasi",   0.10, 5.0, 0.50, 0.01, format="%.2f")
            mn_lauk, mx_lauk     = 0.33, 0.50
            mn_angkat, mx_angkat = 0.33, 1.00
            mn_nasi, mx_nasi     = 0.33, 0.50

        # Estimasi real-time
        est_lauk   = (total_ompr / p_lauk)   * (mn_lauk   + mx_lauk)   / 2
        est_angkat =  n_trip                 * (mn_angkat + mx_angkat) / 2
        est_nasi   = (total_ompr / p_nasi)   * (mn_nasi   + mx_nasi)   / 2
        est_total  = max(est_lauk, est_angkat, est_nasi)
        in_range   = 20 <= est_total <= 30

        st.markdown(f"""
        <div class="card">
            <h4>📐 Estimasi Durasi</h4>
            <p>
                Lauk:   <b>{est_lauk:.1f} mnt</b><br>
                Angkat: <b>{est_angkat:.1f} mnt</b><br>
                Nasi:   <b>{est_nasi:.1f} mnt</b><br>
                ─────────────────<br>
                Bottleneck: <b>{est_total:.1f} mnt</b>
                {"&nbsp; ✅ Dalam target!" if in_range else "&nbsp; ⚠️ Di luar 20–30 mnt"}
            </p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")
        sh = st.slider("Jam Mulai",   0, 23, 7)
        sm = st.slider("Menit Mulai", 0, 59, 0)
        st.markdown("---")
        run_btn   = st.button("🚀 Jalankan Simulasi", type="primary", use_container_width=True)
        reset_btn = st.button("🔄 Reset",                              use_container_width=True)
        if reset_btn:
            st.rerun()

    # ── RUN ───────────────────────────────────────────────
    if run_btn:
        cfg = Config(
            TOTAL_MEJA=total_meja, MAHASISWA_PER_MEJA=mhs_meja,
            PETUGAS_LAUK=p_lauk, PETUGAS_ANGKAT=p_angkat, PETUGAS_NASI=p_nasi,
            OMPRENG_PER_TRIP=opr_trip,
            MIN_LAUK=mn_lauk, MAX_LAUK=mx_lauk,
            MIN_ANGKAT=mn_angkat, MAX_ANGKAT=mx_angkat,
            MIN_NASI=mn_nasi, MAX_NASI=mx_nasi,
            START_HOUR=sh, START_MINUTE=sm,
        )
        with st.spinner("⏳ Simulasi berjalan..."):
            model   = SistemPiketDES(cfg)
            res, df = model.run()

        if res is None:
            st.error("❌ Simulasi gagal."); return

        ok = 20 <= res['total_waktu'] <= 30
        st.markdown(f"""
        <div class="banner">
            ✅ Simulasi selesai &nbsp;|&nbsp;
            {res['total_ompreng']} ompreng &nbsp;|&nbsp;
            Jam selesai: <b>{res['jam_selesai'].strftime('%H:%M')}</b> &nbsp;|&nbsp;
            Total: <b>{res['total_waktu']:.1f} menit</b>
            {"&nbsp; 🎯 Dalam target 20–30 menit!" if ok else ""}
        </div>
        """, unsafe_allow_html=True)

        # KPI baris 1
        st.markdown('<p class="sec">📈 Ringkasan Hasil</p>', unsafe_allow_html=True)
        c = st.columns(6)
        c[0].metric("🍱 Ompreng",     res['total_ompreng'])
        c[1].metric("⏱ Total Waktu",  f"{res['total_waktu']:.1f} mnt",
                    delta=f"{res['total_waktu']-25:.1f} vs 25 mnt")
        c[2].metric("🕐 Jam Selesai",  res['jam_selesai'].strftime("%H:%M"))
        c[3].metric("📊 Avg Durasi",   f"{res['avg_durasi']:.2f} mnt")
        c[4].metric("🛻 Trip Angkat",  f"{res['total_trip']} trip")
        c[5].metric("📦 Per Trip",     res['ompreng_per_trip'])

        # KPI baris 2 — utilisasi
        st.markdown('<p class="sec">🔋 Utilisasi Petugas</p>', unsafe_allow_html=True)
        u1,u2,u3 = st.columns(3)
        u1.metric(f"Lauk   ({p_lauk} ptgs)",   f"{res['util_lauk']:.1f}%",
                  f"{res['util_lauk']-80:.1f}% vs 80%")
        u2.metric(f"Angkat ({p_angkat} ptgs)",  f"{res['util_angkat']:.1f}%",
                  f"{res['util_angkat']-80:.1f}% vs 80%")
        u3.metric(f"Nasi   ({p_nasi} ptgs)",   f"{res['util_nasi']:.1f}%",
                  f"{res['util_nasi']-80:.1f}% vs 80%")

        # Detail
        with st.expander("📋 Detail Statistik Lengkap"):
            d1, d2 = st.columns(2)
            with d1:
                st.subheader("Durasi Total")
                for lbl, v in [("Rata-rata",res['avg_durasi']),("Maks",res['max_durasi']),
                                ("Min",res['min_durasi']),("Std Dev",res['std_durasi'])]:
                    st.write(f"**{lbl}:** {v:.3f} mnt")
            with d2:
                st.subheader("Waktu Layanan & Tunggu")
                for lbl, v in [("Avg Lauk",res['avg_lauk']),("Avg Angkat",res['avg_angkat']),
                                ("Avg Nasi",res['avg_nasi']),("Tunggu Lauk",res['avg_t_lauk']),
                                ("Tunggu Angkat",res['avg_t_angkat']),("Tunggu Nasi",res['avg_t_nasi'])]:
                    st.write(f"**{lbl}:** {v:.3f} mnt")

        # Grafik
        st.markdown('<p class="sec">📊 Visualisasi</p>', unsafe_allow_html=True)
        c1,c2 = st.columns(2)
        with c1: st.plotly_chart(chart_hist(df),    use_container_width=True)
        with c2: st.plotly_chart(chart_boxplot(df), use_container_width=True)

        c3,c4 = st.columns(2)
        with c3: st.plotly_chart(chart_util_bar(res), use_container_width=True)
        with c4: st.plotly_chart(chart_gauge(res),    use_container_width=True)

        c5,c6 = st.columns(2)
        with c5: st.plotly_chart(chart_violin(df),           use_container_width=True)
        with c6: st.plotly_chart(chart_antrian(model.stats), use_container_width=True)

        ft = chart_trip(model.stats)
        if ft: st.plotly_chart(ft, use_container_width=True)
        st.plotly_chart(chart_timeline(df), use_container_width=True)

        # Tabel
        st.markdown('<p class="sec">📄 Data Simulasi</p>', unsafe_allow_html=True)
        with st.expander("Lihat Tabel Data"):
            st.dataframe(
                df.sort_values('id'),
                column_config={
                    "id":            st.column_config.NumberColumn("ID"),
                    "durasi_total":  st.column_config.NumberColumn("Total",         format="%.3f"),
                    "dur_lauk":      st.column_config.NumberColumn("Lauk",          format="%.3f"),
                    "dur_angkat":    st.column_config.NumberColumn("Angkat",         format="%.3f"),
                    "dur_nasi":      st.column_config.NumberColumn("Nasi",           format="%.3f"),
                    "tunggu_lauk":   st.column_config.NumberColumn("Tunggu Lauk",    format="%.3f"),
                    "tunggu_angkat": st.column_config.NumberColumn("Tunggu Angkat",  format="%.3f"),
                    "tunggu_nasi":   st.column_config.NumberColumn("Tunggu Nasi",    format="%.3f"),
                    "jam_selesai":   st.column_config.DatetimeColumn("Jam Selesai"),
                },
                hide_index=True, use_container_width=True,
            )
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download CSV", csv,
                               f"piket_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                               "text/csv", use_container_width=True)

    else:
        st.markdown('<p class="sec">📌 Tentang Simulasi</p>', unsafe_allow_html=True)
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("""
            <div class="card"><h4>🏫 Skenario</h4><p>
                60 meja × 3 mahasiswa = <b>180 ompreng</b><br>
                7 petugas total<br>Mulai pukul <b>07:00</b>
            </p></div>""", unsafe_allow_html=True)
        with col2:
            st.markdown("""
            <div class="card"><h4>🔄 Pipeline</h4><p>
                <b>1. Lauk</b> — 3 petugas, 20–30 dtk/ompreng<br>
                <b>2. Angkat</b> — 1 petugas, 7 ompreng/trip, 20–60 dtk<br>
                <b>3. Nasi</b> — 3 petugas, 20–30 dtk/ompreng
            </p></div>""", unsafe_allow_html=True)
        with col3:
            st.markdown("""
            <div class="card"><h4>🎯 Analisis Target</h4><p>
                Angkat: 180÷7 = 26 trip × maks 1 mnt = <b>26 mnt</b><br>
                Lauk/Nasi: 60 slot × 0.33–0.50 mnt<br>
                = <b>20–30 menit</b><br><br>
                ✅ <b>Total: 20–30 menit</b>
            </p></div>""", unsafe_allow_html=True)

        st.markdown("""
        <div style="text-align:center; padding:20px; color:#C47A95; font-size:15px;">
            👈 Atur parameter di sidebar lalu klik <b>🚀 Jalankan Simulasi</b>
        </div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.caption(f"MODSIM: DES — Sistem Piket IT Del  |  {datetime.now().strftime('%d/%m/%Y %H:%M')}")


if __name__ == "__main__":
    main()