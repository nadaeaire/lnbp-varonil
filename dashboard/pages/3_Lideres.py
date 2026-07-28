"""
Vista: líderes de temporada — equipos e individuales.
Stats: PTS, REB, AST, FG, 3P, TL, TOV, STL, BLK.
"""

import sys
import os
import streamlit as st
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from utils import get_supabase, TEAM_NAMES, COMPETICION_ID, parse_min

st.set_page_config(page_title="Líderes — LNBP Varonil", page_icon="🏀", layout="wide")

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


@st.cache_data(ttl=300)
def fetch_team_stats(partido_ids: tuple):
    if not partido_ids:
        return []
    sb = get_supabase()
    res = (
        sb.table("partidos_detalle")
        .select(
            "equipo_id, score, "
            "tot_sfieldgoalsmade, tot_sfieldgoalsattempted, "
            "tot_stwopointersmade, tot_stwopointersattempted, "
            "tot_sthreepointersmade, tot_sthreepointersattempted, "
            "tot_sfreethrowsmade, tot_sfreethrowsattempted, "
            "tot_sreboundstotal, tot_sreboundsoffensive, tot_sreboundsdefensive, "
            "tot_sassists, tot_sturnovers, tot_ssteals, tot_sblocks, "
            "tot_sfoulspersonal, tot_sfoulson"
        )
        .in_("partido_id", list(partido_ids))
        .limit(5000)
        .execute()
    )
    return res.data or []


@st.cache_data(ttl=300)
def fetch_player_stats(partido_ids: tuple):
    if not partido_ids:
        return []
    sb = get_supabase()
    res = (
        sb.table("players_detalle")
        .select(
            "player_id, sminutes, spoints, "
            "sfieldgoalsmade, sfieldgoalsattempted, "
            "stwopointersmade, stwopointersattempted, "
            "sthreepointersmade, sthreepointersattempted, "
            "sfreethrowsmade, sfreethrowsattempted, "
            "sreboundstotal, sreboundsoffensive, sreboundsdefensive, "
            "sassists, sturnovers, ssteals, sblocks"
        )
        .in_("partido_id", list(partido_ids))
        .limit(5000)
        .execute()
    )
    # Solo jugadores que hayan jugado
    return [r for r in (res.data or []) if parse_min(r.get("sminutes", "0:00")) > 0]


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

def aggregate_teams(rows):
    result = {}
    for r in rows:
        eq = r["equipo_id"]
        if eq not in result:
            result[eq] = {k: 0 for k in [
                "G", "PTS", "REB", "REBO", "REBD",
                "AST", "TOV", "STL", "BLK",
                "FGM", "FGA", "2PM", "2PA", "3PM", "3PA", "FTM", "FTA",
            ]}
        s = result[eq]
        s["G"]    += 1
        s["PTS"]  += r.get("score", 0) or 0
        s["REB"]  += r.get("tot_sreboundstotal", 0) or 0
        s["REBO"] += r.get("tot_sreboundsoffensive", 0) or 0
        s["REBD"] += r.get("tot_sreboundsdefensive", 0) or 0
        s["AST"]  += r.get("tot_sassists", 0) or 0
        s["TOV"]  += r.get("tot_sturnovers", 0) or 0
        s["STL"]  += r.get("tot_ssteals", 0) or 0
        s["BLK"]  += r.get("tot_sblocks", 0) or 0
        s["FGM"]  += r.get("tot_sfieldgoalsmade", 0) or 0
        s["FGA"]  += r.get("tot_sfieldgoalsattempted", 0) or 0
        s["2PM"]  += r.get("tot_stwopointersmade", 0) or 0
        s["2PA"]  += r.get("tot_stwopointersattempted", 0) or 0
        s["3PM"]  += r.get("tot_sthreepointersmade", 0) or 0
        s["3PA"]  += r.get("tot_sthreepointersattempted", 0) or 0
        s["FTM"]  += r.get("tot_sfreethrowsmade", 0) or 0
        s["FTA"]  += r.get("tot_sfreethrowsattempted", 0) or 0
    return result


def aggregate_players(rows):
    result = {}
    for r in rows:
        pid = r["player_id"]
        if pid not in result:
            result[pid] = {k: 0 for k in [
                "G", "PTS", "REB", "REBO", "REBD",
                "AST", "TOV", "STL", "BLK",
                "FGM", "FGA", "2PM", "2PA", "3PM", "3PA", "FTM", "FTA",
            ]}
            result[pid]["MIN"] = 0.0
        s = result[pid]
        s["G"]    += 1
        s["MIN"]  += parse_min(r.get("sminutes", "0:00"))
        s["PTS"]  += r.get("spoints", 0) or 0
        s["REB"]  += r.get("sreboundstotal", 0) or 0
        s["REBO"] += r.get("sreboundsoffensive", 0) or 0
        s["REBD"] += r.get("sreboundsdefensive", 0) or 0
        s["AST"]  += r.get("sassists", 0) or 0
        s["TOV"]  += r.get("sturnovers", 0) or 0
        s["STL"]  += r.get("ssteals", 0) or 0
        s["BLK"]  += r.get("sblocks", 0) or 0
        s["FGM"]  += r.get("sfieldgoalsmade", 0) or 0
        s["FGA"]  += r.get("sfieldgoalsattempted", 0) or 0
        s["2PM"]  += r.get("stwopointersmade", 0) or 0
        s["2PA"]  += r.get("stwopointersattempted", 0) or 0
        s["3PM"]  += r.get("sthreepointersmade", 0) or 0
        s["3PA"]  += r.get("sthreepointersattempted", 0) or 0
        s["FTM"]  += r.get("sfreethrowsmade", 0) or 0
        s["FTA"]  += r.get("sfreethrowsattempted", 0) or 0
    return result


def top_table(agg, stat, label_fn, n=10, higher_is_better=True):
    rows = []
    for k, s in agg.items():
        g = s["G"]
        if g == 0:
            continue
        val = round(s[stat] / g, 1)
        rows.append({"#": 0, "Nombre": label_fn(k), "G": g, "Prom": val, "Total": s[stat]})
    rows.sort(key=lambda r: r["Prom"], reverse=higher_is_better)
    for i, r in enumerate(rows[:n], 1):
        r["#"] = i
    return pd.DataFrame(rows[:n]).set_index("#")


# ── UI ────────────────────────────────────────────────────────────────────────

st.title("🏆 Líderes de Temporada")

partido_ids  = tuple(fetch_partido_ids())
if not partido_ids:
    st.info("No hay partidos procesados aún.")
    st.stop()

team_rows   = fetch_team_stats(partido_ids)
player_rows = fetch_player_stats(partido_ids)

team_agg   = aggregate_teams(team_rows)
player_agg = aggregate_players(player_rows)

player_names = fetch_players(tuple(player_agg.keys()))

team_label   = lambda eq_id: TEAM_NAMES.get(eq_id, f"ID {eq_id}")
player_label = lambda pid:   player_names.get(pid, f"ID {pid}")

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

tab_eq, tab_jug = st.tabs(["Equipos", "Jugadores"])

with tab_eq:
    st.caption("Promedio por partido · todos los equipos")
    cols = st.columns(len(STATS))
    for col, (stat, label, higher) in zip(cols, STATS):
        with col:
            st.markdown(f"**{label}**")
            df = top_table(team_agg, stat, team_label, n=14, higher_is_better=higher)
            st.dataframe(df[["Nombre", "Prom"]], use_container_width=True, hide_index=False)

with tab_jug:
    st.caption("Promedio por partido · todos los jugadores con al menos 1 partido")
    cols = st.columns(len(STATS))
    for col, (stat, label, higher) in zip(cols, STATS):
        with col:
            st.markdown(f"**{label}**")
            df = top_table(player_agg, stat, player_label, n=10, higher_is_better=higher)
            st.dataframe(df[["Nombre", "Prom"]], use_container_width=True, hide_index=False)
