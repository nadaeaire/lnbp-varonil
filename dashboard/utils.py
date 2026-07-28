"""Constantes, conexión Supabase y funciones de agregación compartidas."""

import streamlit as st
from supabase import create_client

COMPETICION_ID = 1

TEAM_NAMES = {
    1: "Abejas", 2: "Astros", 3: "Correcaminos", 4: "Diablos",
    5: "Dorados", 6: "El Calor", 7: "Freseros", 8: "Fuerza Regia",
    9: "Gambusinos", 10: "Lobos", 11: "Mineros", 12: "Panteras",
    13: "Santos", 14: "Soles",
}

FALTAS_COM = {"personal", "technical", "benchTechnical",
              "disqualifying", "unsportsmanlike", "offensive"}

PERIOD_SETS = {
    "Q1": {1}, "Q2": {2}, "1H": {1, 2},
    "Q3": {3}, "Q4": {4}, "2H": {3, 4},
    "Total": None,
}


@st.cache_resource
def get_supabase():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"],
    )


def empty_stats():
    return {
        "PTS": 0, "REB": 0, "REBO": 0, "REBD": 0,
        "AST": 0, "TOV": 0, "STL": 0, "BLK": 0,
        "FC": 0, "FD": 0,
        "FGM": 0, "FGA": 0,
        "2PM": 0, "2PA": 0,
        "3PM": 0, "3PA": 0,
        "FTM": 0, "FTA": 0,
    }


def _pts(at, suc):
    if at == "2pt"       and suc: return 2
    if at == "3pt"       and suc: return 3
    if at == "freeThrow" and suc: return 1
    return 0


def aggregate_acciones(acciones, periods=None):
    """
    Agrega acciones por (equipo_id, player_id).
    player_id=None → stats de equipo.
    periods=None   → todos los cuartos.
    """
    result: dict[tuple, dict] = {}

    for row in acciones:
        p = row.get("period", 0)
        if periods is not None and p not in periods:
            continue

        eq  = row.get("equipo_id")
        pl  = row.get("player_id")
        at  = (row.get("actiontype") or "").strip()
        st_ = (row.get("subtype")    or "").strip()
        suc = bool(row.get("success"))

        keys = [(eq, None)]
        if pl:
            keys.append((eq, pl))

        for key in keys:
            if key not in result:
                result[key] = empty_stats()
            s = result[key]

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

    return result


def aggregate_stints(stints, periods=None):
    """Devuelve {(equipo_id, player_id): minutos_totales}."""
    result: dict[tuple, float] = {}
    for row in stints:
        p  = row.get("period", 0)
        if periods is not None and p not in periods:
            continue
        pl = row.get("player_id")
        eq = row.get("equipo_id")
        mn = float(row.get("minutos") or 0)
        if pl and eq:
            key = (eq, pl)
            result[key] = result.get(key, 0.0) + mn
    return result


def fmt_min(m: float) -> str:
    mins = int(m)
    secs = round((m - mins) * 60)
    if secs == 60:
        mins += 1; secs = 0
    return f"{mins}:{secs:02d}"


def parse_min(s: str) -> float:
    try:
        m, sec = str(s).split(":")
        return int(m) + int(sec) / 60
    except Exception:
        return 0.0


def fmt_shot(made, att) -> str:
    return f"{made}/{att}"


def row_display(s: dict, include_min: bool = False, min_val: float = 0.0) -> dict:
    d = {}
    if include_min:
        d["MIN"] = fmt_min(min_val)
    d.update({
        "PTS":  s["PTS"],  "REB":  s["REB"],
        "REBO": s["REBO"], "REBD": s["REBD"],
        "AST":  s["AST"],  "TOV":  s["TOV"],
        "STL":  s["STL"],  "BLK":  s["BLK"],
        "FC":   s["FC"],   "FD":   s["FD"],
        "FG":   fmt_shot(s["FGM"], s["FGA"]),
        "2P":   fmt_shot(s["2PM"], s["2PA"]),
        "3P":   fmt_shot(s["3PM"], s["3PA"]),
        "TL":   fmt_shot(s["FTM"], s["FTA"]),
    })
    return d
