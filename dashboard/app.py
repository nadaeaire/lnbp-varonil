"""
Dashboard de Partidos — LNBP Varonil
Vista: estadísticas de un partido por cuartos y mitades.

Uso:
    streamlit run app.py
"""

import streamlit as st
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import (
    get_supabase, TEAM_NAMES, COMPETICION_ID, PERIOD_SETS,
    aggregate_acciones, aggregate_stints,
    empty_stats, fmt_min, fmt_shot, row_display,
)

# ── SUPABASE ─────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def fetch_partidos():
    sb = get_supabase()
    res = (
        sb.table("partidos")
        .select("partido_id, match_time_utc, equipo_local_id, equipo_visitante_id")
        .eq("competicion_id", COMPETICION_ID)
        .filter("timestamp_ingestion", "not.is", "null")
        .order("match_time_utc", desc=True)
        .execute()
    )
    return res.data or []


@st.cache_data(ttl=300)
def fetch_acciones(partido_id):
    sb = get_supabase()
    res = (
        sb.table("acciones_partido")
        .select("period, equipo_id, player_id, actiontype, subtype, success")
        .eq("partido_id", partido_id)
        .limit(3000)
        .execute()
    )
    return res.data or []


@st.cache_data(ttl=300)
def fetch_stints(partido_id):
    sb = get_supabase()
    res = (
        sb.table("stints")
        .select("period, player_id, equipo_id, minutos")
        .eq("partido_id", partido_id)
        .execute()
    )
    return res.data or []


@st.cache_data(ttl=300)
def fetch_players(player_ids: list):
    if not player_ids:
        return {}
    sb = get_supabase()
    res = (
        sb.table("players")
        .select("player_id, first_name, family_name")
        .in_("player_id", player_ids)
        .execute()
    )
    return {
        r["player_id"]: f"{r['family_name']} {r['first_name'][0]}."
        for r in (res.data or [])
    }


# ── TABLAS ───────────────────────────────────────────────────────────────────

def team_table(acciones, team_id, has_ot, max_period):
    sets = dict(PERIOD_SETS)
    order = ["Q1", "Q2", "1H", "Q3", "Q4", "2H"]
    if has_ot:
        sets["OT"] = set(range(5, max_period + 1))
        order.append("OT")
    order.append("Total")

    rows = []
    for label in order:
        s = aggregate_acciones(acciones, sets[label]).get((team_id, None), empty_stats())
        row = {"Periodo": label}
        row.update(row_display(s))
        rows.append(row)

    return pd.DataFrame(rows).set_index("Periodo")


def player_table(acciones, stints, team_id, player_names, periods):
    stats = aggregate_acciones(acciones, periods)
    mins  = aggregate_stints(stints, periods)

    pids = {pl for (eq, pl) in stats if eq == team_id and pl is not None}
    pids |= {pl for (eq, pl) in mins  if eq == team_id and pl is not None}

    if not pids:
        return pd.DataFrame()

    rows = []
    for pid in pids:
        s = stats.get((team_id, pid), empty_stats())
        m = mins.get((team_id, pid), 0.0)
        row = {"Jugador": player_names.get(pid, f"ID {pid}")}
        row.update(row_display(s, include_min=True, min_val=m))
        row["_sort"] = m
        rows.append(row)

    df = pd.DataFrame(rows).set_index("Jugador")
    df = df.sort_values("_sort", ascending=False).drop(columns=["_sort"])
    return df


# ── UI ───────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Dashboard LNBP Varonil",
    page_icon="🏀",
    layout="wide",
)

st.title("🏀 Partido — por cuartos")

partidos = fetch_partidos()
if not partidos:
    st.warning("No hay partidos procesados aún.")
    st.stop()


def partido_label(p):
    home  = TEAM_NAMES.get(p["equipo_local_id"], "?")
    away  = TEAM_NAMES.get(p["equipo_visitante_id"], "?")
    fecha = (p.get("match_time_utc") or "")[:10]
    return f"{fecha}  ·  {home} vs {away}"


labels   = [partido_label(p) for p in partidos]

with st.sidebar:
    st.header("Partido")
    selected = st.selectbox("Selecciona", labels)
    partido  = partidos[labels.index(selected)]

partido_id = partido["partido_id"]
home_id    = partido["equipo_local_id"]
away_id    = partido["equipo_visitante_id"]
home_name  = TEAM_NAMES.get(home_id, "?")
away_name  = TEAM_NAMES.get(away_id, "?")

acciones = fetch_acciones(partido_id)
stints   = fetch_stints(partido_id)

if not acciones:
    st.warning("No hay datos de acciones para este partido.")
    st.stop()

max_period = max((r.get("period") or 0 for r in acciones), default=4)
has_ot     = max_period > 4

player_ids   = list({r["player_id"] for r in acciones if r.get("player_id")}
                  | {r["player_id"] for r in stints   if r.get("player_id")})
player_names = fetch_players(player_ids)

# Marcador final
all_stats = aggregate_acciones(acciones)
home_pts  = all_stats.get((home_id, None), empty_stats())["PTS"]
away_pts  = all_stats.get((away_id, None), empty_stats())["PTS"]

col1, col2, col3 = st.columns([3, 1, 3])
with col1:
    st.metric(home_name, home_pts)
with col2:
    st.markdown(
        "<div style='text-align:center;padding-top:20px;font-size:1.2rem'>VS</div>",
        unsafe_allow_html=True,
    )
with col3:
    st.metric(away_name, away_pts)

st.divider()

tab_eq, tab_jug = st.tabs(["Equipo — por cuartos", "Jugadores — por cuartos"])

with tab_eq:
    col_h, col_a = st.columns(2)
    with col_h:
        st.subheader(home_name)
        st.dataframe(team_table(acciones, home_id, has_ot, max_period), use_container_width=True)
    with col_a:
        st.subheader(away_name)
        st.dataframe(team_table(acciones, away_id, has_ot, max_period), use_container_width=True)

with tab_jug:
    period_opts = list(PERIOD_SETS.keys())
    if has_ot:
        period_opts.insert(-1, "OT")

    selected_per = st.radio("Cuarto / Mitad", period_opts, horizontal=True)
    periods = set(range(5, max_period + 1)) if selected_per == "OT" else PERIOD_SETS[selected_per]

    col_h, col_a = st.columns(2)
    with col_h:
        st.subheader(home_name)
        df_h = player_table(acciones, stints, home_id, player_names, periods)
        st.dataframe(df_h, use_container_width=True) if not df_h.empty else st.info("Sin datos.")
    with col_a:
        st.subheader(away_name)
        df_a = player_table(acciones, stints, away_id, player_names, periods)
        st.dataframe(df_a, use_container_width=True) if not df_a.empty else st.info("Sin datos.")
