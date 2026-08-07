import os, sys
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd
import modules.utils as utils
import modules.auth as auth
from modules.data_loader import (
    cargar_base_datos, cargar_metadata_jugadores, cargar_catalogo_equipos,
    cargar_datos_equipos_only, cargar_tiros, cargar_lookup_etapas,
    cargar_catalogo_temporadas, aplicar_display_names
)

import views.players_avg as view_players_avg
import views.players_adv as view_players_adv
import views.equipos_smry as view_equipos_smry
import views.equipos_4f as view_equipos_4f
import views.players_prfl as view_players_prfl
import views.equipos_tiros as view_equipos_tiros
import views.equipos_avg as view_equipos_avg
import views.players_per28 as view_players_per28

try:
    IS_TEST = st.secrets["entorno"] == "test"
except Exception:
    IS_TEST = False

st.set_page_config(
    page_title="Analytics LNBP Varonil — GravityStats",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="collapsed"
)

utils.cargar_estilos_css()
utils.inyectar_ga()

if IS_TEST:
    st.session_state["password_correct"] = True
    st.session_state["user_email"] = "develop@gravitystats.app"
else:
    if not auth.check_password():
        st.stop()

if 'selected_player_id' not in st.session_state:
    st.session_state.selected_player_id = None

if 'view_mode' not in st.session_state:
    st.session_state.view_mode = 'main'

try:
    import concurrent.futures
    with st.spinner('Cargando base de datos...'):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as _ex:
            _f_raw    = _ex.submit(cargar_base_datos)
            _f_meta   = _ex.submit(cargar_metadata_jugadores)
            _f_eq_cat = _ex.submit(cargar_catalogo_equipos)
            _f_eq_raw = _ex.submit(cargar_datos_equipos_only)
            df_raw                 = _f_raw.result()
            df_players, df_rosters = _f_meta.result()
            df_equipos_cat         = _f_eq_cat.result()
            df_equipos_raw         = _f_eq_raw.result()
except Exception as e:
    st.error(f"Error técnico cargando datos: {e}")
    st.stop()

df_temporadas = cargar_catalogo_temporadas()

_temporada_lookup = {}
if not df_equipos_raw.empty and 'id_abe' in df_equipos_raw.columns and 'temporada_id' in df_equipos_raw.columns:
    _tl = df_equipos_raw[['id_abe', 'temporada_id']].dropna(subset=['temporada_id']).drop_duplicates('id_abe')
    _temporada_lookup = dict(zip(_tl['id_abe'], _tl['temporada_id'].astype(int)))

_TEMP_SEASON_STARTS: dict[int, pd.Timestamp] = {
    1: pd.Timestamp('2026-07-23'),
}

def _fecha_a_temp_id(f):
    if pd.isna(f) or not _TEMP_SEASON_STARTS:
        return None
    for tid, start in sorted(_TEMP_SEASON_STARTS.items(), reverse=True):
        if f >= start:
            return tid
    return None

if not df_raw.empty and 'Fecha' in df_raw.columns:
    df_raw['temporada_id'] = df_raw['Fecha'].apply(_fecha_a_temp_id)

# --- Sidebar ---
st.sidebar.image("GravityStats_Logo.png", width=300)
st.sidebar.markdown(
    """
    <div style="margin-top: -20px;">
        <h1 style="margin-top: 20px; margin-bottom: 0px; font-size: 25px; color: #dc362a;">Analytics LNBP Varonil</h1>
        <h3 style="margin-top: -25px; font-weight: bold; color: #0a173c;">GravityStats</h3>
    </div>
    """,
    unsafe_allow_html=True
)

if IS_TEST:
    st.sidebar.markdown(
        '<div style="background-color:#ff4b4b;color:white;text-align:center;padding:4px 8px;border-radius:4px;font-size:12px;font-weight:bold;margin-bottom:10px;">'
        'AMBIENTE DE PRUEBA'
        '</div>',
        unsafe_allow_html=True
    )

_TODAS_TEMPS = "Toda la historia"
_temp_nombres = df_temporadas['nombre'].tolist() if not df_temporadas.empty else []
_temp_opts = [_TODAS_TEMPS] + _temp_nombres
temporada_sel = st.sidebar.selectbox(
    "Temporada:", _temp_opts,
    index=1 if len(_temp_opts) > 1 else 0
)
utils.rastrear_cambio("Temporada Seleccionada", temporada_sel)

temporada_sel_id = None
if temporada_sel != _TODAS_TEMPS and not df_temporadas.empty:
    _tm = df_temporadas[df_temporadas['nombre'] == temporada_sel]
    if not _tm.empty:
        temporada_sel_id = int(_tm.iloc[0]['temporada_id'])
    elif not df_equipos_raw.empty and 'temporada_id' in df_equipos_raw.columns:
        _avail = df_equipos_raw['temporada_id'].dropna()
        if not _avail.empty:
            temporada_sel_id = int(_avail.min())

etapa_sel = st.sidebar.radio(
    "Etapa:",
    ["Toda la Temporada", "Temporada Regular", "Playoffs"],
    index=0,
    horizontal=True
)
utils.rastrear_cambio("Etapa Seleccionada", etapa_sel)

df_etapas = cargar_lookup_etapas()
if not df_etapas.empty and not df_raw.empty and 'id_abe' in df_raw.columns:
    etapa_map = dict(zip(df_etapas['id_abe'], df_etapas['etapa']))
    if 'etapa' in df_raw.columns:
        df_raw = df_raw.drop(columns=['etapa'])
    df_raw['etapa'] = df_raw['id_abe'].astype(str).map(etapa_map).fillna('1').astype(str)

# LNBP Varonil: liga única, sin filtro de categoría
categoria_sel = "LNBP Varonil"
df = df_raw.copy() if not df_raw.empty else pd.DataFrame()
df_eq = df_equipos_raw.copy() if not df_equipos_raw.empty else pd.DataFrame()

if temporada_sel_id is not None:
    if not df.empty and 'temporada_id' in df.columns:
        df = df[df['temporada_id'] == temporada_sel_id].copy()
    if not df_eq.empty and 'temporada_id' in df_eq.columns:
        df_eq = df_eq[df_eq['temporada_id'] == temporada_sel_id].copy()

if etapa_sel == "Temporada Regular":
    if not df.empty and 'etapa' in df.columns:
        df = df[df['etapa'] == '1'].copy()
    if not df_eq.empty and 'etapa' in df_eq.columns:
        df_eq = df_eq[df_eq['etapa'] == '1'].copy()
elif etapa_sel == "Playoffs":
    if not df.empty and 'etapa' in df.columns:
        df = df[df['etapa'] != '1'].copy()
    if not df_eq.empty and 'etapa' in df_eq.columns:
        df_eq = df_eq[df_eq['etapa'] != '1'].copy()

st.sidebar.divider()

def reset_view():
    st.session_state.view_mode = 'main'

_VISTAS_POR_ROL = {
    "basic":  ["🤝 Equipos", "📊 Por partido", "🛸 Avanzadas"],
    "medium": ["🤝 Equipos", "📋 Equipos por partido", "4️⃣ Four Factors",
               "🎯 Mapa de Tiros Beta", "📊 Por partido", "🛸 Avanzadas"],
    "all":    ["🤝 Equipos", "📋 Equipos por partido", "4️⃣ Four Factors",
               "🎯 Mapa de Tiros Beta", "📊 Por partido", "📐 PER28", "🛸 Avanzadas"],
}
_rol = st.session_state.get("user_role", "basic")
opciones_menu = _VISTAS_POR_ROL.get(_rol, _VISTAS_POR_ROL["basic"])

opcion = st.sidebar.radio("Ir a:", opciones_menu, on_change=reset_view)
utils.rastrear_cambio("Vista Principal", opcion)

# TODO: agregar alias de equipos LNBP cuando se conozcan
alias_equipos: dict[str, str] = {}

# --- Enrutador ---
if st.session_state.view_mode == 'profile':
    if st.button("⬅️ Volver a la lista", type="secondary"):
        st.session_state.view_mode = 'main'
        st.rerun()

    current_pid = st.session_state.selected_player_id
    # TODO: llenar con los competicion_ids reales de LNBP por temporada
    _TEMP_TO_COMP: dict[int, tuple] = {}
    _comp_ids_perfil = _TEMP_TO_COMP.get(temporada_sel_id, ()) if temporada_sel_id else ()
    df_tiros = cargar_tiros(competicion_ids=_comp_ids_perfil)
    view_players_prfl.render_view(current_pid, df, df_players, df_rosters, df_equipos_cat, df_tiros)

else:
    if opcion == "📊 Por partido":
        if df.empty:
            st.info("No hay datos de jugadores para esta temporada/etapa.")
        else:
            view_players_avg.render_view(df, df_players, df_rosters, categoria_sel)

    elif opcion == "📐 PER28":
        if df.empty:
            st.info("No hay datos de jugadores para esta temporada/etapa.")
        else:
            view_players_per28.render_view(df, df_players, df_rosters, categoria_sel)

    elif opcion == "🛸 Avanzadas":
        if df.empty:
            st.info("No hay datos de jugadores para esta temporada/etapa.")
        else:
            view_players_adv.render_view(df, df_players, df_rosters, categoria_sel)

    elif opcion == "🤝 Equipos":
        view_equipos_smry.render_view(df_eq if not df_eq.empty else df, categoria_sel)

    elif opcion == "📋 Equipos por partido":
        view_equipos_avg.render_view(df_eq if not df_eq.empty else df, categoria_sel)

    elif opcion == "4️⃣ Four Factors":
        view_equipos_4f.render_view(df_eq if not df_eq.empty else df, categoria_sel)

    elif opcion == "🎯 Mapa de Tiros Beta":
        _TEMP_TO_COMP: dict[int, tuple] = {1: (1,)}
        _comp_ids_tiros = _TEMP_TO_COMP.get(temporada_sel_id, ()) if temporada_sel_id else ()
        df_tiros = cargar_tiros(competicion_ids=_comp_ids_tiros)
        if etapa_sel != "Toda la Temporada" and not df_tiros.empty and not df_etapas.empty:
            df_tiros['_pid_str'] = df_tiros['partido_id'].astype(str).str.split('.').str[0]
            df_tiros = df_tiros.merge(df_etapas, left_on='_pid_str', right_on='id_abe', how='left')
            df_tiros['etapa'] = df_tiros['etapa'].fillna('1').astype(str)
            if etapa_sel == "Temporada Regular":
                df_tiros = df_tiros[df_tiros['etapa'] == '1'].copy()
            else:
                df_tiros = df_tiros[df_tiros['etapa'] != '1'].copy()
            df_tiros.drop(columns=['_pid_str', 'id_abe', 'etapa'], errors='ignore', inplace=True)
        view_equipos_tiros.render_view(
            df_tiros,
            df_equipos_raw,
            categoria_sel,
            alias_equipos,
            df_equipos_cat
        )
