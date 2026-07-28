"""
Vista: líderes de temporada por cuarto/mitad — equipos e individuales.
"""

import sys
import os
import streamlit as st
import pandas as pd
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from utils import get_supabase, TEAM_NAMES, COMPETICION_ID, PERIOD_SETS, empty_stats

st.set_page_config(page_title="Líderes — LNBP Varonil", page_icon="🏀", layout="wide")

FALTAS_COM = {"personal", "technical", "benchTechnical",
              "disqualifying", "unsportsmanlike", "offensive"}

# ── FETCH ─────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def fetch_partido_ids():
    sb = get_supabase()
    res = (
        sb.table("partidos")
        .select("partido_id")
        .eq("competicion_id", COMPETICION_ID)
        .filter("timestamp_ingestion", "not.is", "null")
        .execute()
    )
    return [r["partido_id"] for r in (res.data or [])]


@st.cache_data(ttl=600)
def fetch_all_acciones(partido_ids: tuple):
    """Descarga todas las acciones de los partidos procesados (paginado)."""
    if not partido_ids:
        return []
    sb       = get_supabase()
    all_rows = []
    page     = 1000
    offset   = 0
    while True:
        res = (
            sb.table("acciones_partido")
            .select("partido_id, period, equipo_id, player_id, actiontype, subtype, success")
            .in_("partido_id", list(partido_ids))
            .range(offset, offset + page - 1)
            .execute()
        )
        batch = res.data or []
        all_rows.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return all_rows


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


# ── AGREGACIÓN ────────────────────────────────────────────────────────────────

def _pts(at, suc):
    if at == "2pt"       and suc: return 2
    if at == "3pt"       and suc: return 3
    if at == "freeThrow" and suc: return 1
    return 0


def build_agg(acciones, periods):
    """
    Devuelve:
      team_stats:   {equipo_id: {stat: val, ...}}
      player_stats: {player_id: {stat: val, ...}}
      team_games:   {equipo_id: n_partidos_distintos}
      player_games: {player_id: n_partidos_distintos}
    """
    team_stats   = defaultdict(lambda: {**empty_stats()})
    player_stats = defaultdict(lambda: {**empty_stats()})
    team_games   = defaultdict(set)   # equipo_id → {partido_ids}
    player_games = defaultdict(set)   # player_id → {partido_ids}

    for row in acciones:
        p = row.get("period", 0)
        if periods is not None and p not in periods:
            continue

        gid = row.get("partido_id")
        eq  = row.get("equipo_id")
        pl  = row.get("player_id")
        at  = (row.get("actiontype") or "").strip()
        st_ = (row.get("subtype")    or "").strip()
        suc = bool(row.get("success"))

        if eq:
            team_games[eq].add(gid)
        if pl:
            player_games[pl].add(gid)

        def _apply(s):
            s["PTS"] += _pts(at, suc)
            if at in ("2pt", "3pt"):
                s["FGA"] += 1
                if suc: s["FGM"] += 1
                if at == "2pt":
                    s["2PA"] += 1
                    if suc: s["2PM"] += 1
                else:
                    s["3PA"] += 1
                    if suc: s["3PM"] += 1
            elif at == "freeThrow":
                s["FTA"] += 1
                if suc: s["FTM"] += 1
            elif at == "rebound":
                s["REB"] += 1
                if   st_ == "offensive":  s["REBO"] += 1
                elif st_ == "defensive":  s["REBD"] += 1
            elif at == "turnover":  s["TOV"] += 1
            elif at == "steal":     s["STL"] += 1
            elif at == "block":     s["BLK"] += 1
            elif at == "assist":    s["AST"] += 1
            elif at == "foul":
                if   st_ == "drawn":    s["FD"] += 1
                elif st_ in FALTAS_COM: s["FC"] += 1

        if eq:
            _apply(team_stats[eq])
        if pl:
            _apply(player_stats[pl])

    return (
        dict(team_stats),
        dict(player_stats),
        {k: len(v) for k, v in team_games.items()},
        {k: len(v) for k, v in player_games.items()},
    )


# ── DISPLAY ───────────────────────────────────────────────────────────────────

STATS = [
    ("PTS",  "Puntos",      True),
    ("REB",  "Rebotes",     True),
    ("AST",  "Asistencias", True),
    ("FGA",  "Tiros",       True),
    ("3PM",  "Triples",     True),
    ("FTM",  "T. Libres",   True),
    ("TOV",  "Pérdidas",    False),
    ("STL",  "Robos",       True),
    ("BLK",  "Bloqueos",    True),
]


def top_table(stats, games, stat, label_fn, n=10, higher=True):
    rows = []
    for key, s in stats.items():
        g = games.get(key, 1)
        if g == 0:
            continue
        val = round(s[stat] / g, 1)
        rows.append({"#": 0, "Nombre": label_fn(key), "G": g, "Prom": val})
    rows.sort(key=lambda r: r["Prom"], reverse=higher)
    for i, r in enumerate(rows[:n], 1):
        r["#"] = i
    return pd.DataFrame(rows[:n]).set_index("#") if rows else pd.DataFrame()


def dh(df):
    return 38 + 35 * max(len(df), 1)


# ── UI ────────────────────────────────────────────────────────────────────────

st.title("🏆 Líderes de Temporada")

partido_ids = tuple(fetch_partido_ids())
if not partido_ids:
    st.info("No hay partidos procesados aún.")
    st.stop()

n_games = len(partido_ids)
st.caption(f"{n_games} partido{'s' if n_games != 1 else ''} procesado{'s' if n_games != 1 else ''}")

acciones = fetch_all_acciones(partido_ids)
if not acciones:
    st.warning("Sin datos de acciones.")
    st.stop()

selected_per = st.radio("Cuarto / Mitad", list(PERIOD_SETS.keys()), horizontal=True)
periods      = PERIOD_SETS[selected_per]

team_stats, player_stats, team_games, player_games = build_agg(acciones, periods)

player_names = fetch_players(tuple(player_stats.keys()))
team_label   = lambda eq: TEAM_NAMES.get(eq, f"ID {eq}")
player_label = lambda pl: player_names.get(pl, f"ID {pl}")

tab_eq, tab_jug = st.tabs(["Equipos", "Jugadores"])

with tab_eq:
    st.caption(f"Promedio por partido — {selected_per}")
    cols = st.columns(len(STATS))
    for col, (stat, label, higher) in zip(cols, STATS):
        with col:
            st.markdown(f"**{label}**")
            df = top_table(team_stats, team_games, stat, team_label, n=14, higher=higher)
            if not df.empty:
                st.dataframe(df[["Nombre", "Prom"]], height=dh(df), use_container_width=True)

with tab_jug:
    st.caption(f"Promedio por partido — {selected_per}")
    cols = st.columns(len(STATS))
    for col, (stat, label, higher) in zip(cols, STATS):
        with col:
            st.markdown(f"**{label}**")
            df = top_table(player_stats, player_games, stat, player_label, n=10, higher=higher)
            if not df.empty:
                st.dataframe(df[["Nombre", "Prom"]], height=dh(df), use_container_width=True)
