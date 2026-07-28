"""
Vista: estadísticas acumuladas por equipo — totales y promedios por cuarto.
"""

import sys
import os
import streamlit as st
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from utils import (
    get_supabase, TEAM_NAMES, COMPETICION_ID, PERIOD_SETS,
    aggregate_acciones, aggregate_stints,
    empty_stats, fmt_min, fmt_shot, row_display,
)

st.set_page_config(page_title="Acumulado — LNBP Varonil", page_icon="🏀", layout="wide")

# ── FETCH ─────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def fetch_partidos_equipo(equipo_id):
    sb = get_supabase()
    res = (
        sb.table("partidos")
        .select("partido_id")
        .eq("competicion_id", COMPETICION_ID)
        .filter("timestamp_ingestion", "not.is", "null")
        .or_(f"equipo_local_id.eq.{equipo_id},equipo_visitante_id.eq.{equipo_id}")
        .execute()
    )
    return [r["partido_id"] for r in (res.data or [])]


@st.cache_data(ttl=300)
def fetch_acciones_equipo(equipo_id, partido_ids: tuple):
    if not partido_ids:
        return []
    sb = get_supabase()
    res = (
        sb.table("acciones_partido")
        .select("period, equipo_id, player_id, actiontype, subtype, success")
        .eq("equipo_id", equipo_id)
        .in_("partido_id", list(partido_ids))
        .limit(10000)
        .execute()
    )
    return res.data or []


@st.cache_data(ttl=300)
def fetch_stints_equipo(equipo_id, partido_ids: tuple):
    if not partido_ids:
        return []
    sb = get_supabase()
    res = (
        sb.table("stints")
        .select("period, player_id, equipo_id, minutos")
        .eq("equipo_id", equipo_id)
        .in_("partido_id", list(partido_ids))
        .limit(10000)
        .execute()
    )
    return res.data or []


@st.cache_data(ttl=300)
def fetch_players(player_ids: tuple):
    if not player_ids:
        return {}
    sb = get_supabase()
    res = (
        sb.table("players")
        .select("player_id, first_name, family_name")
        .in_("player_id", list(player_ids))
        .execute()
    )
    return {
        r["player_id"]: f"{r['family_name']} {r['first_name'][0]}."
        for r in (res.data or [])
    }


# ── HELPERS ───────────────────────────────────────────────────────────────────

DISPLAY_ORDER = ["Q1", "Q2", "1H", "Q3", "Q4", "2H", "Total"]


def avg_display(s: dict, n: int) -> dict:
    def a(v): return round(v / n, 1) if n else 0
    return {
        "PTS":  a(s["PTS"]),  "REB":  a(s["REB"]),
        "REBO": a(s["REBO"]), "REBD": a(s["REBD"]),
        "AST":  a(s["AST"]),  "TOV":  a(s["TOV"]),
        "STL":  a(s["STL"]),  "BLK":  a(s["BLK"]),
        "FC":   a(s["FC"]),   "FD":   a(s["FD"]),
        "FG":   fmt_shot(round(a(s["FGM"]), 1), round(a(s["FGA"]), 1)),
        "2P":   fmt_shot(round(a(s["2PM"]), 1), round(a(s["2PA"]), 1)),
        "3P":   fmt_shot(round(a(s["3PM"]), 1), round(a(s["3PA"]), 1)),
        "TL":   fmt_shot(round(a(s["FTM"]), 1), round(a(s["FTA"]), 1)),
    }


# ── UI ────────────────────────────────────────────────────────────────────────

st.title("📈 Acumulado por Equipo")

with st.sidebar:
    st.header("Equipo")
    team_options = sorted(TEAM_NAMES.items(), key=lambda x: x[1])
    team_name_sel = st.selectbox("Selecciona", [n for _, n in team_options])
    equipo_id = next(i for i, n in team_options if n == team_name_sel)

partido_ids = tuple(fetch_partidos_equipo(equipo_id))
n_games = len(partido_ids)

if n_games == 0:
    st.info("Este equipo no tiene partidos procesados aún.")
    st.stop()

st.caption(f"{n_games} partido{'s' if n_games != 1 else ''} procesado{'s' if n_games != 1 else ''}")

acciones     = fetch_acciones_equipo(equipo_id, partido_ids)
stints       = fetch_stints_equipo(equipo_id, partido_ids)
player_ids   = tuple({r["player_id"] for r in acciones if r.get("player_id")}
                   | {r["player_id"] for r in stints   if r.get("player_id")})
player_names = fetch_players(player_ids)

tab_eq, tab_jug = st.tabs(["Equipo — por cuartos", "Jugadores — por cuartos"])

# ── Tab equipo ────────────────────────────────────────────────────────────────
with tab_eq:
    rows_tot = []
    rows_avg = []

    for label in DISPLAY_ORDER:
        periods = PERIOD_SETS[label]
        s = aggregate_acciones(acciones, periods).get((equipo_id, None), empty_stats())
        rows_tot.append({"Periodo": label, **row_display(s)})
        rows_avg.append({"Periodo": label, **avg_display(s, n_games)})

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Totales")
        st.dataframe(pd.DataFrame(rows_tot).set_index("Periodo"), use_container_width=True)
    with col2:
        st.subheader("Promedio por partido")
        st.dataframe(pd.DataFrame(rows_avg).set_index("Periodo"), use_container_width=True)

# ── Tab jugadores ─────────────────────────────────────────────────────────────
with tab_jug:
    selected_per = st.radio("Cuarto / Mitad", DISPLAY_ORDER, horizontal=True)
    periods = PERIOD_SETS[selected_per]

    stats = aggregate_acciones(acciones, periods)
    mins  = aggregate_stints(stints, periods)

    pids = {pl for (eq, pl) in stats if eq == equipo_id and pl is not None}
    pids |= {pl for (eq, pl) in mins  if eq == equipo_id and pl is not None}

    rows = []
    for pid in pids:
        s = stats.get((equipo_id, pid), empty_stats())
        m = mins.get((equipo_id, pid), 0.0)
        row = {"Jugador": player_names.get(pid, f"ID {pid}")}
        row.update(row_display(s, include_min=True, min_val=m))
        row["_sort"] = m
        rows.append(row)

    if rows:
        df = pd.DataFrame(rows).set_index("Jugador")
        df = df.sort_values("_sort", ascending=False).drop(columns=["_sort"])
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Sin datos para este período.")
