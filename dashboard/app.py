"""
Dashboard de Partidos — LNBP Varonil
Estadísticas por cuarto y por mitades, nivel equipo y jugador.

Uso:
    streamlit run app.py
"""

import streamlit as st
import pandas as pd
from supabase import create_client

# ── CONSTANTES ───────────────────────────────────────────────────────────────

COMPETICION_ID = 1

TEAM_NAMES = {
    1: "Abejas", 2: "Astros", 3: "Correcaminos", 4: "Diablos",
    5: "Dorados", 6: "El Calor", 7: "Freseros", 8: "Fuerza Regia",
    9: "Gambusinos", 10: "Lobos", 11: "Mineros", 12: "Panteras",
    13: "Santos", 14: "Soles",
}

FALTAS_COM = {"personal", "technical", "benchTechnical",
              "disqualifying", "unsportsmanlike", "offensive"}

DISPLAY_COLS = [
    "MIN", "PTS", "REB", "REBO", "REBD",
    "AST", "TOV", "STL", "BLK", "FC", "FD",
    "FG", "2P", "3P", "TL",
]

DISPLAY_COLS_TEAM = [
    "PTS", "REB", "REBO", "REBD",
    "AST", "TOV", "STL", "BLK", "FC", "FD",
    "FG", "2P", "3P", "TL",
]

# ── SUPABASE ─────────────────────────────────────────────────────────────────

@st.cache_resource
def get_supabase():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"],
    )


@st.cache_data(ttl=300)
def fetch_partidos():
    sb = get_supabase()
    res = (
        sb.table("partidos")
        .select("partido_id, match_time_utc, home_team_id, away_team_id")
        .eq("competicion_id", COMPETICION_ID)
        .not_.is_("timestamp_ingestion", "null")
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


# ── ESTADÍSTICAS ─────────────────────────────────────────────────────────────

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
    if at == "2pt"      and suc: return 2
    if at == "3pt"      and suc: return 3
    if at == "freeThrow" and suc: return 1
    return 0


def aggregate_acciones(acciones, periods=None):
    """
    Agrega acciones por (equipo_id, player_id).
    player_id=None → stats de equipo.
    periods=None  → todos los cuartos.
    """
    result: dict[tuple, dict] = {}

    for row in acciones:
        p = row.get("period", 0)
        if periods is not None and p not in periods:
            continue

        eq  = row.get("equipo_id")
        pl  = row.get("player_id")
        at  = (row.get("actiontype") or "").strip()
        st  = (row.get("subtype")    or "").strip()
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
                if   st == "offensive":  s["REBO"] += 1
                elif st == "defensive":  s["REBD"] += 1
            elif at == "turnover":  s["TOV"] += 1
            elif at == "steal":     s["STL"] += 1
            elif at == "block":     s["BLK"] += 1
            elif at == "assist":    s["AST"] += 1
            elif at == "foul":
                if   st == "drawn":     s["FD"] += 1
                elif st in FALTAS_COM:  s["FC"] += 1

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


# ── FORMATO ──────────────────────────────────────────────────────────────────

def fmt_min(m: float) -> str:
    mins = int(m)
    secs = round((m - mins) * 60)
    if secs == 60:
        mins += 1
        secs = 0
    return f"{mins}:{secs:02d}"


def fmt_shot(made, att) -> str:
    return f"{made}/{att}"


def row_display(s: dict, include_min: bool = False, min_val: float = 0.0) -> dict:
    d = {}
    if include_min:
        d["MIN"] = fmt_min(min_val)
    d["PTS"]  = s["PTS"]
    d["REB"]  = s["REB"]
    d["REBO"] = s["REBO"]
    d["REBD"] = s["REBD"]
    d["AST"]  = s["AST"]
    d["TOV"]  = s["TOV"]
    d["STL"]  = s["STL"]
    d["BLK"]  = s["BLK"]
    d["FC"]   = s["FC"]
    d["FD"]   = s["FD"]
    d["FG"]   = fmt_shot(s["FGM"], s["FGA"])
    d["2P"]   = fmt_shot(s["2PM"], s["2PA"])
    d["3P"]   = fmt_shot(s["3PM"], s["3PA"])
    d["TL"]   = fmt_shot(s["FTM"], s["FTA"])
    return d


# ── TABLAS ───────────────────────────────────────────────────────────────────

PERIOD_SETS = {
    "Q1": {1}, "Q2": {2}, "1H": {1, 2},
    "Q3": {3}, "Q4": {4}, "2H": {3, 4},
    "Total": None,
}


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
        row["_min_raw"] = m
        rows.append(row)

    df = pd.DataFrame(rows).set_index("Jugador")
    df = df.sort_values("_min_raw", ascending=False).drop(columns=["_min_raw"])
    return df


# ── UI ───────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Dashboard LNBP Varonil",
    page_icon="🏀",
    layout="wide",
)

st.title("🏀 Dashboard de Partidos — LNBP Varonil")

partidos = fetch_partidos()
if not partidos:
    st.warning("No hay partidos procesados aún.")
    st.stop()


def partido_label(p):
    home  = TEAM_NAMES.get(p["home_team_id"], "?")
    away  = TEAM_NAMES.get(p["away_team_id"], "?")
    fecha = (p.get("match_time_utc") or "")[:10]
    return f"{fecha}  ·  {home} vs {away}"


labels = [partido_label(p) for p in partidos]

with st.sidebar:
    st.header("Partido")
    selected = st.selectbox("Selecciona", labels)
    partido  = partidos[labels.index(selected)]

partido_id = partido["partido_id"]
home_id    = partido["home_team_id"]
away_id    = partido["away_team_id"]
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

# ── Marcador final ────────────────────────────────────────────────────────────
all_stats = aggregate_acciones(acciones)
home_pts  = all_stats.get((home_id, None), empty_stats())["PTS"]
away_pts  = all_stats.get((away_id, None), empty_stats())["PTS"]

col1, col2, col3 = st.columns([3, 1, 3])
with col1:
    st.metric(home_name, home_pts)
with col2:
    st.markdown("<div style='text-align:center;padding-top:20px;font-size:1.2rem'>VS</div>",
                unsafe_allow_html=True)
with col3:
    st.metric(away_name, away_pts)

st.divider()

# ── Tabs ─────────────────────────────────────────────────────────────────────
tab_eq, tab_jug = st.tabs(["Equipo — por cuartos", "Jugadores — por cuartos"])

with tab_eq:
    col_h, col_a = st.columns(2)

    with col_h:
        st.subheader(home_name)
        st.dataframe(
            team_table(acciones, home_id, has_ot, max_period),
            use_container_width=True,
        )

    with col_a:
        st.subheader(away_name)
        st.dataframe(
            team_table(acciones, away_id, has_ot, max_period),
            use_container_width=True,
        )

with tab_jug:
    period_opts = list(PERIOD_SETS.keys())
    if has_ot:
        period_opts.insert(-1, "OT")

    selected_per = st.radio("Cuarto / Mitad", period_opts, horizontal=True)

    if selected_per == "OT":
        periods = set(range(5, max_period + 1))
    else:
        periods = PERIOD_SETS[selected_per]

    col_h, col_a = st.columns(2)

    with col_h:
        st.subheader(home_name)
        df_h = player_table(acciones, stints, home_id, player_names, periods)
        if df_h.empty:
            st.info("Sin datos.")
        else:
            st.dataframe(df_h, use_container_width=True)

    with col_a:
        st.subheader(away_name)
        df_a = player_table(acciones, stints, away_id, player_names, periods)
        if df_a.empty:
            st.info("Sin datos.")
        else:
            st.dataframe(df_a, use_container_width=True)
