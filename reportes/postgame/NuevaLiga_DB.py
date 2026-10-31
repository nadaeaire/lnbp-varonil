"""
NuevaLiga_DB.py
---------------
Ingesta directa a Supabase de partidos de la nueva liga (LNBP Femenil / Sportradar).
Sigue el mismo patrón que los scripts LDM_* existentes.

Configuración previa necesaria en Supabase:
  - competiciones: registro con competicion_id = COMPETICION_ID
  - temporadas:    registro con temporada_id   = TEMPORADA_ID
  - equipos:       registros con la abreviatura/nombre de los equipos de la nueva liga
  - players:       se crean automáticamente vía get_or_create_player (por person_id_ext)

Uso:
  1. Edita COMPETICION_ID y TEMPORADA_ID si es necesario.
  2. Agrega los state params en STATES al final del script.
  3. Ejecuta:  python3 NuevaLiga_DB.py
"""

import os
import sys
import re
import json
import base64
import zlib
import requests
from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo
    _TZ_MX = ZoneInfo("America/Mexico_City")
except ImportError:
    import pytz
    _TZ_MX = pytz.timezone("America/Mexico_City")
from supabase import create_client, Client

# team_utils vive en recs/cron/ — lo añadimos al path para que funcione
# independientemente del directorio desde el que se ejecute este script.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "recs", "cron"))
import team_utils
from tiro_zonas import classify_shot

# ─────────────────────────────────────────
# CONFIGURACIÓN — AJUSTAR ANTES DE EJECUTAR
# ─────────────────────────────────────────

COMPETICION_ID     = 1            # competiciones.competicion_id  (nueva liga)
TEMPORADA_ID       = 1            # temporadas.temporada_id
ROSTER_START_DATE  = "2026-07-23" # fecha genérica para rosters (placeholder)

# Etapa por rango de fecha local del partido, por competición.
# "1" regular, "2" play-in, "3" semifinales de zona, "4" finales de zona, "5" gran final,
# "6" Copa Value. Una competición sin entrada aquí usa ETAPA_POR_DEFECTO (temporadas
# anteriores: todo "1" hasta que se agreguen sus rangos de playoffs).
ETAPAS_POR_COMPETICION = {
    1: [
        ("2026-07-23", "2026-10-08", "1"),
        ("2026-10-11", "2026-10-16", "2"),
        ("2026-10-18", "2026-10-24", "3"),
    ],
}
ETAPA_POR_DEFECTO = {3: "6"}   # Copa Value; cualquier otra competición sin rangos → "1"

def etapa_para_fecha(fixture):
    rangos = ETAPAS_POR_COMPETICION.get(COMPETICION_ID)
    if rangos is None:
        return ETAPA_POR_DEFECTO.get(COMPETICION_ID, "1")
    fecha = (fixture.get("startTimeLocal") or fixture.get("startTimeUTC") or "")[:10]
    for ini, fin, etapa in rangos:
        if ini <= fecha <= fin:
            return etapa
    raise ValueError(f"Sin etapa definida para la fecha {fecha!r}: agrega el rango en "
                     f"ETAPAS_POR_COMPETICION[{COMPETICION_ID}].")

# Backfill de tiro_zona: agrega partido_ids para actualizar la zona de tiros ya guardados.
BACKFILL_TIRO_ZONA_IDS = []

# Backfill de stints: agrega partido_ids para calcular/recalcular stints ya procesados.
# Usa BACKFILL_STINTS_IDS para partido(s) específico(s), o pon BACKFILL_STINTS_TODOS = True
# para procesar automáticamente todos los partidos jugados (con game_json_url).
BACKFILL_STINTS_IDS   = []
BACKFILL_STINTS_TODOS = False

# Backfill de partidos_detalle: re-descarga y recalcula box stats (fecha, FGA, métricas avanzadas).
BACKFILL_PARTIDOS_IDS = []

# Backfill de pbp_scores: recalcula snapshots de marcador para partidos ya procesados.
BACKFILL_PBP_SCORES_IDS = []

# Backfill de posesiones: recalcula el conteo y duración de posesiones desde el PBP.
# Usa BACKFILL_POSESIONES_IDS para partido(s) específico(s), o pon BACKFILL_POSESIONES_TODOS = True
# para procesar automáticamente todos los partidos jugados (con game_json_url).
BACKFILL_POSESIONES_IDS   = []
BACKFILL_POSESIONES_TODOS = False

# Backfill de DNP en rosters: pon True para agregar jugadores que viajaron pero no jugaron.
BACKFILL_DNP_ROSTERS = False

# Backfill de DNP en players_detalle: pon True para agregar filas con stats en cero para DNP históricos.
BACKFILL_DNP_PLAYERS_DETALLE = False

# Backfill de acciones_partido: reinserta el PBP completo para partidos ya procesados.
BACKFILL_ACCIONES_IDS = []

# Backfill de tiros: reinserta el shot chart para partidos ya procesados.
BACKFILL_TIROS_IDS = []

# Backfill de métricas TO (live/dead ball): agrega partido_ids ya procesados.
BACKFILL_PARTIDO_IDS = []

# Forzar proceso de partidos que siguen en IN_PROGRESS por error del anotador.
FORCE_PARTIDO_IDS = []

# Equipo principal (El Calor) — usado para detectar Garbage Time desde su perspectiva.
EQUIPO_ID = 6

# Nacionalidades que el script NO debe sobreescribir aunque la API diga otra cosa.
# Formato: {player_id: "Nacionalidad correcta"}
NATIONALITY_OVERRIDES = {
    109: "México",          # API dice "Estados Unidos" — incorrecto
    134: "Estados Unidos",  # API dice "México" — incorrecto
    199: "México"
}

API_BASE   = "https://embed-api.eui.connect.sportradar.com/v1/embed/14/fixture_detail"
API_BIO    = "https://embed-api.eui.connect.sportradar.com/v1/embed/14/person_detail"
SEASON_ID  = "cc7d79f3-43ee-11f1-b893-293ce3dbc120"  # season UUID Sportradar — LNBP 2026

# Supabase — variables de entorno (igual que LDM_*)
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
from config import SUPABASE_URL as URL, SUPABASE_KEY as KEY

# ─────────────────────────────────────────
# UTILIDADES GENERALES
# ─────────────────────────────────────────

def safe_get(d, k, default=None):
    val = d.get(k)
    return val if val is not None else default

def safe_int(val, default=0):
    try:   return int(float(val)) if val is not None else default
    except: return default

def safe_bool(val, default=False):
    if val is None:        return default
    if isinstance(val, bool): return val
    return bool(val)

def trunc(val, max_len=200):
    """Trunca a max_len para respetar límites de varchar."""
    s = str(val) if val is not None else ""
    return s[:max_len]

def parse_iso_minutes(val):
    """'PT11M44S' → '11:44'  |  None → '00:00'"""
    if not val:
        return "00:00"
    m = re.search(r'PT(\d+)M(?:(\d+)S)?', str(val))
    if m:
        mins = int(m.group(1))
        secs = int(m.group(2)) if m.group(2) else 0
        return f"{mins}:{secs:02d}"
    return "00:00"

def iso_to_seconds(val):
    """'PT38M32S' → float minutos"""
    if not val:
        return 0.0
    m = re.search(r'PT(?:(\d+)M)?(?:(\d+)S)?', str(val))
    if m:
        mins = int(m.group(1)) if m.group(1) else 0
        secs = int(m.group(2)) if m.group(2) else 0
        return round(mins + secs / 60, 3)
    return 0.0

def clock_iso_to_mmss(val):
    """'PT9M47S' → '09:47'"""
    if not val:
        return "00:00"
    m = re.search(r'PT(?:(\d+)M)?(?:(\d+)S)?', str(val))
    if m:
        mins = int(m.group(1)) if m.group(1) else 0
        secs = int(m.group(2)) if m.group(2) else 0
        return f"{mins:02d}:{secs:02d}"
    return "00:00"

def calcular_gt(period, clock_iso):
    """
    Calcula el game time acumulado (tiempo total transcurrido).
    Periodos regulares (1-4): 10 min c/u.  Overtime (5+): 5 min c/u.
    """
    DURACION_REGULAR = 10 * 60
    DURACION_OT      = 5  * 60
    period = int(period) if period else 1
    if period <= 4:
        base_seg = (period - 1) * DURACION_REGULAR
        dur_seg  = DURACION_REGULAR
    else:
        base_seg = 4 * DURACION_REGULAR + (period - 5) * DURACION_OT
        dur_seg  = DURACION_OT
    m = re.search(r'PT(?:(\d+)M)?(?:(\d+)S)?', str(clock_iso)) if clock_iso else None
    if m:
        clock_seg = (int(m.group(1)) if m.group(1) else 0) * 60 + \
                    (int(m.group(2)) if m.group(2) else 0)
    else:
        clock_seg = 0
    gt_seg = max(0, base_seg + (dur_seg - clock_seg))
    return f"{gt_seg // 60:02d}:{gt_seg % 60:02d}"

def split_name(full_name):
    """'ANIYA THOMAS' → ('ANIYA', 'THOMAS')"""
    if not full_name:
        return ("", "")
    parts = str(full_name).strip().split(" ", 1)
    return (parts[0], parts[1]) if len(parts) > 1 else (parts[0], "")

# ─────────────────────────────────────────
# DESCARGA DE JSONs (Sportradar Embed API)
# ─────────────────────────────────────────

def fetch_json(url, descripcion=""):
    print(f"   🌐 Descargando {descripcion}...")
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        print(f"      ✅ OK ({resp.status_code})")
        return resp.json()
    except Exception as e:
        print(f"      ❌ Error: {e}")
        raise

def derivar_urls(box_data, box_url):
    """Lee el nodo 'tabs' del box JSON → URLs de PBP y tiros."""
    tabs = box_data.get("data", {}).get("tabs", [])
    base = box_url.split("?")[0]
    urls = {}
    for tab in tabs:
        sub  = tab.get("sub", "")
        link = tab.get("link", "")
        if sub in ("pbp", "shot_chart") and link.startswith("&~w=f~"):
            state = link.replace("&~w=f~", "")
            urls[sub] = f"{base}?state={state}"
    if "pbp" not in urls:
        raise ValueError("No se encontró tab 'pbp' en el box JSON.")
    if "shot_chart" not in urls:
        raise ValueError("No se encontró tab 'shot_chart' en el box JSON.")
    return urls["pbp"], urls["shot_chart"]

def cargar_jsons(box_url):
    """Descarga box score, PBP y tiros usando solo el box_url como entrada."""
    box           = fetch_json(box_url, "Box Score")
    pbp_url, tiros_url = derivar_urls(box, box_url)
    print(f"   📎 URL PBP:   {pbp_url}")
    print(f"   📎 URL Tiros: {tiros_url}")
    pbp_j   = fetch_json(pbp_url,   "Play By Play")
    tiros_j = fetch_json(tiros_url, "Tiros / Shot Chart")
    return box, pbp_j, tiros_j

# ─────────────────────────────────────────
# RESOLUCIÓN DE FOREIGN KEYS
# ─────────────────────────────────────────

def get_next_partido_id(supabase):
    """
    Retorna el próximo partido_id disponible para COMPETICION_ID.
    Si no hay partidos aún, comienza desde 1.
    """
    try:
        res = supabase.table("partidos") \
            .select("partido_id") \
            .eq("competicion_id", COMPETICION_ID) \
            .order("partido_id", desc=True) \
            .limit(1) \
            .execute()
        data = res.data if hasattr(res, "data") else []
        return (data[0]["partido_id"] + 1) if data else 1
    except Exception as e:
        print(f"   ⚠️ Error obteniendo max partido_id: {e}. Comenzando desde 1.")
        return 1

def get_or_create_player(supabase, person_id_ext, first_name, family_name, mapa_players):
    """
    Busca player_id por person_id_ext (UUID del proveedor).
    Si no existe en la BD, lo crea.
    Usa mapa_players como caché en memoria para evitar queries repetidas.
    """
    if person_id_ext in mapa_players:
        return mapa_players[person_id_ext]

    # 1. Buscar en BD por person_id_ext
    try:
        res = supabase.table("players") \
            .select("player_id") \
            .eq("person_id_ext", person_id_ext) \
            .execute()
        data = res.data if hasattr(res, "data") else []
        if data:
            pid = data[0]["player_id"]
            mapa_players[person_id_ext] = pid
            return pid
    except Exception as e:
        print(f"   ⚠️ Error buscando jugador {person_id_ext}: {e}")

    # 2. Crear nuevo jugador
    try:
        first_clean  = str(first_name).strip().title()  if first_name  else ""
        family_clean = str(family_name).strip().title() if family_name else ""
        nuevo = {
            "first_name":    first_clean,
            "family_name":   family_clean,
            "person_id_ext": person_id_ext,
        }
        res_ins = supabase.table("players").insert(nuevo).execute()
        data_ins = res_ins.data if hasattr(res_ins, "data") else []
        if data_ins:
            pid = data_ins[0]["player_id"]
            mapa_players[person_id_ext] = pid
            print(f"   ✨ Nuevo jugador: {first_clean} {family_clean} → player_id={pid}")
            return pid
    except Exception as e:
        print(f"   ❌ Error creando jugador {person_id_ext}: {e}")

    return None

def insertar_chunked(supabase, tabla, payloads, on_conflict=None, chunk_size=500):
    """
    Inserta en lotes de 500 para evitar timeouts en payloads grandes.
    - on_conflict=None  → INSERT simple (para tablas con PK serial, ej: tiros)
    - on_conflict=str   → UPSERT con esa clave de conflicto (ej: 'partido_id,equipo_id')
    """
    total = 0
    for i in range(0, len(payloads), chunk_size):
        batch = payloads[i : i + chunk_size]
        if on_conflict:
            supabase.table(tabla).upsert(batch, on_conflict=on_conflict).execute()
        else:
            supabase.table(tabla).insert(batch).execute()
        total += len(batch)
    return total

# ─────────────────────────────────────────
# PARSEO BOX SCORE
# ─────────────────────────────────────────

def parsear_box(box):
    """
    Extrae info del partido, stats de equipos y jugadores crudos del box JSON.
    Retorna: (info, [home_stats, away_stats], jugadores_raw, equipo_map, home_id, away_id)
    """
    fixture     = box["data"]["fixture"]
    competitors = fixture["competitors"]

    equipo_map = {}
    for c in competitors:
        equipo_map[c["entityId"]] = {
            "isHome": c["isHome"],
            "code":   c["code"],
            "name":   c["name"],
            "score":  c.get("score", 0),
            "rol":    "L" if c["isHome"] else "V",
            "tno":    1 if c["isHome"] else 2,
        }

    home_id = next(eid for eid, v in equipo_map.items() if     v["isHome"])
    away_id = next(eid for eid, v in equipo_map.items() if not v["isHome"])

    info = {
        "start_utc":   fixture.get("startTimeUTC", ""),
        "start_local": fixture.get("startDateTime", ""),
        "fixture_id":  fixture.get("fixtureId", ""),
        "comp_name":   fixture.get("competitionName", ""),
        "season_id":   box["data"].get("seasonId", ""),
    }

    base   = box["data"]["statistics"]["data"]["base"]
    home_b = base["home"]
    away_b = base["away"]

    etapa_partido = etapa_para_fecha(fixture)

    def stats_equipo(block, eid):
        e  = block["entity"]
        te = block["totalEntityStats"]
        _rival_eid = away_id if equipo_map[eid]["isHome"] else home_id

        # ── Derivar FGA y 3PA (la API omite estos campos a veces) ──────────
        _e_fgm   = safe_get(e, "fieldGoalsMade",        0) or 0
        _e_fgpct = safe_get(e, "fieldGoalsPercentage",  0) or 0
        _e_2pa   = safe_get(e, "pointsTwoAttempted",    0) or 0
        _e_3pm   = safe_get(e, "pointsThreeMade",       0) or 0
        _e_3pct  = safe_get(e, "pointsThreePercentage", 0) or 0

        # 3PA: directo → desde porcentaje → se calcula después con FGA
        if "pointsThreeAttempted" in e:
            _e_3pa = (e["pointsThreeAttempted"] or 0)
        elif _e_3pct > 0:
            _e_3pa = round(_e_3pm * 100 / _e_3pct)
        else:
            _e_3pa = None   # se resolverá con FGA - 2PA

        # FGA: directo → desde porcentaje → 2PA + 3PA
        if "fieldGoalsAttempted" in e:
            _e_fga = (e["fieldGoalsAttempted"] or 0)
        elif _e_fgpct > 0:
            _e_fga = round(_e_fgm * 100 / _e_fgpct)
        else:
            _e_fga = _e_2pa + (_e_3pa or 0)

        # Si 3PA aún es desconocido, derivar de FGA - 2PA
        if _e_3pa is None:
            _e_3pa = max(0, _e_fga - _e_2pa)
        # ───────────────────────────────────────────────────────────────────

        return {
            "score":          equipo_map[eid]["score"],
            "full_score":     equipo_map[eid]["score"],
            "rival_score":    equipo_map[_rival_eid]["score"],
            "rol_partido":    equipo_map[eid]["rol"],
            "etapa":          etapa_partido,
            "coach_nombre":   None,     # no disponible en nueva liga
            # Stats básicas
            "tot_sminutes":                safe_get(e, "minutes") and parse_iso_minutes(safe_get(e, "minutes")) or "00:00",
            "tot_sfieldgoalsmade":         _e_fgm,
            "tot_sfieldgoalsattempted":    _e_fga,
            "tot_sthreepointersmade":      _e_3pm,
            "tot_sthreepointersattempted": _e_3pa,
            "tot_stwopointersmade":        safe_get(e, "pointsTwoMade", 0),
            "tot_stwopointersattempted":   _e_2pa,
            "tot_sfreethrowsmade":         safe_get(e, "freeThrowsMade", 0),
            "tot_sfreethrowsattempted":    safe_get(e, "freeThrowsAttempted", 0),
            "tot_sreboundsoffensive":      safe_get(e, "reboundsOffensive", 0),
            "tot_sreboundsdefensive":      safe_get(e, "reboundsDefensive", 0),
            "tot_sreboundstotal":          safe_get(e, "rebounds", 0),
            "tot_sassists":                safe_get(e, "assists", 0),
            "tot_sturnovers":              safe_get(e, "turnovers", 0),
            "tot_ssteals":                 safe_get(e, "steals", 0),
            "tot_sblocks":                 safe_get(e, "blocks", 0),
            "tot_sblocksreceived":         safe_get(e, "blocksReceived", 0),
            "tot_sfoulspersonal":          safe_get(e, "foulsTotal", 0),
            "tot_sfoulson":                safe_get(e, "foulsDrawn", 0),
            "tot_spointsinthepaint":       safe_get(e, "pointsInThePaint", 0),
            "tot_spointssecondchance":     safe_get(e, "pointsSecondChanceMade", 0),
            # totalEntityStats
            "tot_spointsfromturnovers":    safe_get(te, "pointsFromTurnover", 0),
            "tot_spointsfastbreak":        safe_get(te, "pointsFastBreak", 0),
            "tot_sbenchpoints":            safe_get(te, "pointsFromBench", 0),
            "tot_sbiggestlead":            safe_get(te, "biggestLead", 0),
            "tot_sbiggestscoringrun":      safe_get(te, "biggestScoringRun", 0),
            "tot_sleadchanges":            safe_get(te, "leadChanges", 0),
            "tot_stimeleading":            iso_to_seconds(safe_get(te, "timeInLead")),
            "tot_stimesscoreslevel":       None,   # no disponible en nueva liga
        }

    home_stats = stats_equipo(home_b, home_id)
    away_stats = stats_equipo(away_b, away_id)

    # Jugadores crudos (con referencias a equipo)
    jugadores_raw = []
    for block, eid in [(home_b, home_id), (away_b, away_id)]:
        for grupo in block.get("persons", []):
            for row in grupo.get("rows", []):
                row["_entityId"]    = eid
                row["_equipo_code"] = equipo_map[eid]["code"]
                jugadores_raw.append(row)

    return info, [home_stats, away_stats], jugadores_raw, equipo_map, home_id, away_id

# ─────────────────────────────────────────
# MÉTRICAS AVANZADAS
# ─────────────────────────────────────────

def calcular_avanzadas(tm, rival):
    def g(k):
        v = tm.get(k, 0)
        try:   return float(v) if v is not None else 0.0
        except: return 0.0
    def r(k):
        v = rival.get(k, 0)
        try:   return float(v) if v is not None else 0.0
        except: return 0.0

    fga   = g("tot_sfieldgoalsattempted")
    fgm   = g("tot_sfieldgoalsmade")
    fgm3  = g("tot_sthreepointersmade")
    fta   = g("tot_sfreethrowsattempted")
    ftm   = g("tot_sfreethrowsmade")
    rebo  = g("tot_sreboundsoffensive")
    rebd  = g("tot_sreboundsdefensive")
    tov   = g("tot_sturnovers")
    ast   = g("tot_sassists")
    stl   = g("tot_ssteals")
    blk   = g("tot_sblocks")
    score = g("score")

    r_rebd  = r("tot_sreboundsdefensive")
    r_rebo  = r("tot_sreboundsoffensive")
    r_score = r("score")

    denom_rebs = rebo + r_rebd
    orb_factor = (rebo / denom_rebs) if denom_rebs > 0 else 0
    posesiones = fga - (orb_factor * (fga - fgm) * 1.07) + tov + (0.4 * fta)
    posesiones = round(posesiones, 1)
    pos_calc   = posesiones if posesiones > 0 else 1

    ortg = round((score   / pos_calc) * 100, 1)
    drtg = round((r_score / pos_calc) * 100, 1)
    nrtg = round(ortg - drtg, 1)

    tsa  = fga + (0.44 * fta)
    tsp  = round(score / (2 * tsa), 3) if tsa > 0 else 0

    ff_efg  = round((fgm + 0.5 * fgm3) / fga, 3) if fga > 0 else 0
    denom_t = fga + (0.44 * fta) + tov
    ff_tov  = round(tov / denom_t, 3)  if denom_t > 0              else 0
    ff_oreb = round(rebo / (rebo + r_rebd), 3) if (rebo + r_rebd)  > 0 else 0
    ff_dreb = round(rebd / (rebd + r_rebo), 3) if (rebd + r_rebo)  > 0 else 0
    ff_ftr  = round(ftm  / fga, 3)             if fga              > 0 else 0
    ast_tov = round(ast  / tov, 1)             if tov              > 0 else 0
    astp1   = round(ast  / fgm, 3)             if fgm              > 0 else 0
    astp2   = round(ast  / pos_calc, 3)
    stlp    = round(stl  / pos_calc, 3)
    blkp    = round(blk  / pos_calc, 3)

    return {
        "posesiones": posesiones, "ortg": ortg, "drtg": drtg, "nrtg": nrtg,
        "tsa": tsa, "tsp": tsp,
        "ff_efg": ff_efg, "ff_tov": ff_tov, "ff_oreb": ff_oreb,
        "ff_dreb": ff_dreb, "ff_ftr": ff_ftr, "ast_tov": ast_tov,
        "astp1": astp1, "astp2": astp2, "stlp": stlp, "blkp": blkp,
        "victoria": ortg > drtg,
    }

# ─────────────────────────────────────────
# MÉTRICAS DE TURNOVERS (live-ball / dead-ball)
# ─────────────────────────────────────────

def calcular_to_metrics(all_events):
    """
    Analiza la secuencia plana de eventos del PBP y clasifica turnovers.
    all_events : lista plana de dicts del JSON de Sportradar, en orden cronológico.

    Retorna:
        is_live_map  : {índice → True/False} — solo para índices de tipo 'turnover'
        team_stats   : {entityId → {'live_to', 'dead_to', 'pts_off_opp_live_to'}}
        player_stats : {personId → {'live_to', 'dead_to'}}

    Regla: turnover[i] seguido de steal[i+1] → live-ball. Si no → dead-ball.
    pts_off_opp_live_to: puntos que el equipo robador anotó antes de perder la posesión.
    """
    n = len(all_events)
    is_live_map  = {}
    team_stats   = {}
    player_stats = {}

    def _team(eid):
        if eid not in team_stats:
            team_stats[eid] = {"live_to": 0, "dead_to": 0, "pts_off_opp_live_to": 0}
        return team_stats[eid]

    def _player(pid):
        if pid not in player_stats:
            player_stats[pid] = {"live_to": 0, "dead_to": 0}
        return player_stats[pid]

    def _score(ev, eid):
        scores = ev.get("scores") or {}
        return safe_int(scores.get(eid, 0))

    # Fase 1 — clasificar cada turnover como live o dead
    for i, ev in enumerate(all_events):
        if ev.get("eventType") != "turnover":
            continue
        next_ev = all_events[i + 1] if i + 1 < n else None
        is_live = bool(next_ev and next_ev.get("eventType") == "steal")
        is_live_map[i] = is_live

        eid = ev.get("entityId", "")
        pid = ev.get("personId")
        ts  = _team(eid)
        if is_live:
            ts["live_to"] += 1
        else:
            ts["dead_to"] += 1

        if pid:
            ps = _player(pid)
            if is_live:
                ps["live_to"] += 1
            else:
                ps["dead_to"] += 1

    # Fase 2 — pts_off_opp_live_to (crédito al equipo que robó el balón)
    for i, ev in enumerate(all_events):
        if ev.get("eventType") != "steal":
            continue

        stealing_eid   = ev.get("entityId", "")
        score_at_steal = _score(ev, stealing_eid)
        last_score     = score_at_steal

        j = i + 1
        while j < n:
            e     = all_events[j]
            e_eid = e.get("entityId", "")
            et    = e.get("eventType", "")

            # Fin de posesión: rebote defensivo del rival
            if et == "rebound" and e_eid != stealing_eid:
                break
            # Fin de posesión: el equipo que robó vuelve a perder el balón
            if et == "turnover" and e_eid == stealing_eid:
                break
            # Fin de posesión: tiempo muerto
            if et == "timeOut":
                break
            # Fin de posesión: canasta del rival
            if et in ("2pt", "3pt") and e_eid != stealing_eid and e.get("success"):
                break
            # Fin de posesión: el equipo que robó anotó una canasta
            if et in ("2pt", "3pt") and e_eid == stealing_eid and e.get("success"):
                current = _score(e, stealing_eid)
                if current > last_score:
                    last_score = current
                break
            # Fin de posesión: último tiro libre del equipo que robó
            if (et == "freeThrow" and e_eid == stealing_eid and
                    e.get("eventSubType") in ("1Of1", "2Of2", "3Of3")):
                current = _score(e, stealing_eid)
                if current > last_score:
                    last_score = current
                break
            # Fin de posesión: el rival va a la línea (foul cometido por el equipo que robó)
            if et == "freeThrow" and e_eid != stealing_eid:
                break

            current = _score(e, stealing_eid)
            if current > last_score:
                last_score = current
            j += 1

        pts = last_score - score_at_steal
        if pts > 0:
            _team(stealing_eid)["pts_off_opp_live_to"] += pts

    return is_live_map, team_stats, player_stats


def calcular_stints(all_events, equipo_ids, mapa_players, starters_dict, partido_id):
    """
    Calcula los stints de cada jugador a partir del PBP.

    Parámetros:
        all_events    : lista plana de eventos en orden cronológico
        equipo_ids    : dict entityId (UUID) → equipo_id (int)
        mapa_players  : dict personId (UUID) → player_id (int)
        starters_dict : dict personId (UUID) → entityId (UUID)  (titulares Q1)
        partido_id    : int

    Retorna list[dict], una fila por stint.
    """
    from collections import defaultdict

    def parse_clock(clock_str):
        if not clock_str:
            return 0
        m = re.match(r"PT(\d+)M(\d+)S", clock_str)
        return int(m.group(1)) * 60 + int(m.group(2)) if m else 0

    def period_max(pid):
        return 300 if pid > 4 else 600

    all_entity_ids = list(equipo_ids.keys())

    def rival_score(scores, entity_id):
        rivals = [e for e in all_entity_ids if e != entity_id]
        return safe_int(scores.get(rivals[0], 0)) if rivals else 0

    # Agrupar eventos por periodo
    events_by_period = {}
    for ev in all_events:
        p = int(ev.get("periodId", 1))
        events_by_period.setdefault(p, []).append(ev)

    on_court       = {}   # personId → info dict
    completed      = []   # stints cerrados

    for period_id in sorted(events_by_period.keys()):
        evs  = events_by_period[period_id]
        pmax = period_max(period_id)

        # Marcador al inicio del periodo
        first_scores = next(
            (e.get("scores", {}) or {} for e in evs if e.get("scores")), {}
        )

        if period_id == 1:
            # Inicializar con titulares del Q1
            for person_id, entity_id in starters_dict.items():
                pid   = mapa_players.get(person_id)
                eq_id = equipo_ids.get(entity_id)
                if not pid or not eq_id:
                    continue
                on_court[person_id] = {
                    "player_id":   pid,
                    "entity_id":   entity_id,
                    "eq_id":       eq_id,
                    "entry_clock": pmax,
                    "entry_sf":    safe_int(first_scores.get(entity_id, 0)),
                    "entry_sc":    rival_score(first_scores, entity_id),
                }
        else:
            # Heredar jugadores del periodo anterior, reiniciar entry_clock
            new_on_court = {}
            for person_id, info in on_court.items():
                entity_id = info["entity_id"]
                new_on_court[person_id] = {
                    **info,
                    "entry_clock": pmax,
                    "entry_sf":    safe_int(first_scores.get(entity_id, 0)),
                    "entry_sc":    rival_score(first_scores, entity_id),
                }
            on_court = new_on_court

        # Agrupar sustituciones por clock (salidas antes que entradas)
        subs_by_clock = defaultdict(lambda: {"out": [], "in": []})
        for ev in evs:
            if ev.get("eventType") != "substitution":
                continue
            clk   = parse_clock(ev.get("clock", ""))
            stype = ev.get("eventSubType", "")
            if stype in ("out", "in"):
                subs_by_clock[clk][stype].append(ev)

        def _close_stint(person_id, exit_clock, exit_scores):
            info      = on_court.pop(person_id)
            entity_id = info["entity_id"]
            sf = safe_int(exit_scores.get(entity_id, 0)) if exit_scores else info["entry_sf"]
            sc = rival_score(exit_scores, entity_id)     if exit_scores else info["entry_sc"]
            mins = round((info["entry_clock"] - exit_clock) / 60.0, 2)
            completed.append({
                "partido_id":         partido_id,
                "player_id":          info["player_id"],
                "equipo_id":          info["eq_id"],
                "_entity_id":         entity_id,   # temporal para Fase 2
                "period":             period_id,
                "clock_start":        info["entry_clock"],
                "clock_end":          exit_clock,
                "minutos":            max(mins, 0.01),
                "score_favor_start":  info["entry_sf"],
                "score_contra_start": info["entry_sc"],
                "score_favor_end":    sf,
                "score_contra_end":   sc,
                "pts_favor":          sf - info["entry_sf"],
                "pts_contra":         sc - info["entry_sc"],
                "plus_minus":         (sf - info["entry_sf"]) - (sc - info["entry_sc"]),
                "fga_stint": 0, "fta_stint": 0, "to_stint": 0,
                "reb_stint": 0, "faltas_com": 0, "faltas_rec": 0,
                "pace_stint": None, "usg_stint": None, "densidad_contacto": None,
            })

        for clk in sorted(subs_by_clock.keys(), reverse=True):
            # Salidas primero
            for ev in subs_by_clock[clk]["out"]:
                pid_ev = ev.get("personId")
                if pid_ev and pid_ev in on_court:
                    _close_stint(pid_ev, clk, ev.get("scores", {}) or {})
            # Entradas
            for ev in subs_by_clock[clk]["in"]:
                person_id = ev.get("personId")
                if not person_id:
                    continue
                if person_id in on_court:
                    # Evento "in" duplicado para alguien ya en cancha (artefacto del API).
                    # Ignorar para no sobreescribir entry_clock y perder el stint real.
                    continue
                entity_id = ev.get("entityId", "")
                pid   = mapa_players.get(person_id)
                eq_id = equipo_ids.get(entity_id)
                if not pid or not eq_id:
                    continue
                scores = ev.get("scores", {}) or {}
                on_court[person_id] = {
                    "player_id":   pid,
                    "entity_id":   entity_id,
                    "eq_id":       eq_id,
                    "entry_clock": clk,
                    "entry_sf":    safe_int(scores.get(entity_id, 0)),
                    "entry_sc":    rival_score(scores, entity_id),
                }

        # Cerrar stints abiertos al final del periodo
        # Se crean los registros pero NO se elimina de on_court — las jugadores
        # que continúan en cancha se heredan al inicio del siguiente periodo.
        last_scores = {}
        for ev in reversed(evs):
            s = ev.get("scores", {}) or {}
            if s:
                last_scores = s
                break

        for person_id, info in on_court.items():
            entity_id = info["entity_id"]
            sf   = safe_int(last_scores.get(entity_id, info["entry_sf"]))
            sc   = rival_score(last_scores, entity_id) if last_scores else info["entry_sc"]
            mins = round((info["entry_clock"] - 0) / 60.0, 2)
            completed.append({
                "partido_id":         partido_id,
                "player_id":          info["player_id"],
                "equipo_id":          info["eq_id"],
                "_entity_id":         entity_id,   # temporal para Fase 2
                "period":             period_id,
                "clock_start":        info["entry_clock"],
                "clock_end":          0,
                "minutos":            max(mins, 0.01),
                "score_favor_start":  info["entry_sf"],
                "score_contra_start": info["entry_sc"],
                "score_favor_end":    sf,
                "score_contra_end":   sc,
                "pts_favor":          sf - info["entry_sf"],
                "pts_contra":         sc - info["entry_sc"],
                "plus_minus":         (sf - info["entry_sf"]) - (sc - info["entry_sc"]),
                "fga_stint": 0, "fta_stint": 0, "to_stint": 0,
                "reb_stint": 0, "faltas_com": 0, "faltas_rec": 0,
                "pace_stint": None, "usg_stint": None, "densidad_contacto": None,
            })

    # ── Fase 2: contar acciones y calcular métricas por stint ────────────────
    FALTAS_COM    = {"personal", "technical", "benchTechnical",
                     "disqualifying", "unsportsmanlike", "offensive"}
    pid_to_person = {v: k for k, v in mapa_players.items()}

    for stint in completed:
        pid       = stint["player_id"]
        entity_id = stint.pop("_entity_id")   # quitar antes de guardar en BD
        period    = stint["period"]
        cs        = stint["clock_start"]
        ce        = stint["clock_end"]
        mins      = stint["minutos"]
        person_id = pid_to_person.get(pid)
        if not person_id:
            continue

        fga = fta = to = reb = faltas_com = faltas_rec = 0
        # Stats equipo (a) y rival (b) para posesiones y pace
        a_fga = a_fgm = a_or = a_dr = a_to = a_fta = 0
        b_fga = b_fgm = b_or = b_dr = b_to = b_fta = 0

        for ev in events_by_period.get(period, []):
            clk_str = ev.get("clock", "") or ""
            m_clk   = re.match(r"PT(\d+)M(\d+)S", clk_str)
            ev_clk  = int(m_clk.group(1)) * 60 + int(m_clk.group(2)) if m_clk else 0
            if not (ce <= ev_clk <= cs):
                continue

            et        = ev.get("eventType",    "") or ""
            est       = ev.get("eventSubType", "") or ""
            ev_person = ev.get("personId")
            ev_entity = ev.get("entityId", "")
            success   = ev.get("success", False)
            is_team   = ev_entity == entity_id

            # Stats de equipo/rival
            if et in ("2pt", "3pt"):
                if is_team: a_fga += 1; a_fgm += 1 if success else 0
                else:        b_fga += 1; b_fgm += 1 if success else 0
            elif et == "freeThrow":
                if is_team: a_fta += 1
                else:        b_fta += 1
            elif et == "turnover":
                if is_team: a_to += 1
                else:        b_to += 1
            elif et == "rebound":
                if est == "offensive":
                    if is_team: a_or += 1
                    else:        b_or += 1
                elif est == "defensive":
                    if is_team: a_dr += 1
                    else:        b_dr += 1

            # Stats de la jugador
            if ev_person == person_id:
                if et in ("2pt", "3pt"):    fga       += 1
                elif et == "freeThrow":     fta       += 1
                elif et == "turnover":      to        += 1
                elif et == "rebound":       reb       += 1
                elif et == "foul":
                    if   est == "drawn":    faltas_rec += 1
                    elif est in FALTAS_COM: faltas_com += 1

        # Posesiones — fórmula completa
        # POSS = FGA - (OR / (OR + OppDR)) * (FGA - FGM) * 1.07 + TOV + 0.4 * FTA
        def calc_poss(fga, fgm, or_, opp_dr, to, fta):
            denom    = or_ + opp_dr
            miss_adj = (or_ / denom) * (fga - fgm) * 1.07 if denom > 0 else 0
            return fga - miss_adj + to + 0.4 * fta

        poss_a = calc_poss(a_fga, a_fgm, a_or, b_dr, a_to, a_fta)
        poss_b = calc_poss(b_fga, b_fgm, b_or, a_dr, b_to, b_fta)

        # Pace = [200 / (5 * mins)] * (poss_a + poss_b) / 2  =  20 * (poss_a + poss_b) / mins
        pace = round(20 * (poss_a + poss_b) / mins, 1) if mins > 0 else None

        # Usage = (FGA + 0.44·FTA + TOV) / (TmFGA + 0.44·TmFTA + TmTOV)
        # (TmMP/5 y MP se cancelan porque el jugador juega el stint completo)
        tm_plays = a_fga + 0.44 * a_fta + a_to
        usg = round((fga + 0.44 * fta + to) / tm_plays, 3) if tm_plays > 0 else None

        # Densidad de contacto (rebotes + faltas cometidas + faltas recibidas) / minutos
        densidad = round((reb + faltas_com + faltas_rec) / mins, 2) if mins > 0 else None

        stint["fga_stint"]         = fga
        stint["fta_stint"]         = fta
        stint["to_stint"]          = to
        stint["reb_stint"]         = reb
        stint["faltas_com"]        = faltas_com
        stint["faltas_rec"]        = faltas_rec
        stint["pace_stint"]        = pace
        stint["usg_stint"]         = usg
        stint["densidad_contacto"] = densidad

    return completed


def backfill_stints(supabase, partido_id):
    """
    Re-descarga el JSON de un partido ya procesado y recalcula/reinserta sus stints.
    Requiere que partidos.game_json_url esté disponible en la BD.
    """
    print(f"\n   🔁 Backfill stints — partido_id={partido_id}")

    # 1. Obtener URL del partido
    try:
        res = supabase.table("partidos") \
            .select("game_json_url") \
            .eq("partido_id", partido_id) \
            .single() \
            .execute()
        box_url = (res.data or {}).get("game_json_url")
        if not box_url:
            print(f"   ⚠️ No hay game_json_url para partido_id={partido_id}. Saltando.")
            return
    except Exception as e:
        print(f"   ❌ Error obteniendo URL: {e}")
        return

    # 2. Descargar JSONs
    try:
        box, pbp_j, _ = cargar_jsons(box_url)
    except Exception as e:
        print(f"   ❌ Error descargando JSONs: {e}")
        return

    # 3. Parsear box para obtener jugadores, equipos y titulares
    try:
        _, _, jugadores_raw, equipo_map, _, _ = parsear_box(box)
    except Exception as e:
        print(f"   ❌ Error parseando box: {e}")
        return

    # 4. Construir equipo_ids (entityId → equipo_id de la BD)
    try:
        entity_list  = list(equipo_map.keys())
        codes        = [equipo_map[e]["code"] for e in entity_list]
        res_eq = supabase.table("equipos") \
            .select("equipo_id, abreviatura") \
            .in_("abreviatura", codes) \
            .execute()
        code_to_dbid = {r["abreviatura"]: r["equipo_id"] for r in (res_eq.data or [])}
        equipo_ids   = {eid: code_to_dbid[equipo_map[eid]["code"]]
                        for eid in entity_list
                        if equipo_map[eid]["code"] in code_to_dbid}
        if len(equipo_ids) < 2:
            print(f"   ❌ No se resolvieron los 2 equipos. Saltando.")
            return
    except Exception as e:
        print(f"   ❌ Error resolviendo equipos: {e}")
        return

    # 5. Construir mapa_players (personId → player_id)
    person_ids = [j["personId"] for j in jugadores_raw if j.get("personId")]
    try:
        res_pl = supabase.table("players") \
            .select("player_id, person_id_ext") \
            .in_("person_id_ext", person_ids) \
            .execute()
        mapa_players = {r["person_id_ext"]: r["player_id"] for r in (res_pl.data or [])}
    except Exception as e:
        print(f"   ❌ Error obteniendo players: {e}")
        return

    # 6. Starters del Q1
    starters_dict = {
        j["personId"]: j["_entityId"]
        for j in jugadores_raw
        if safe_bool(j.get("starter")) and j.get("personId") and j.get("_entityId")
    }

    # 7. Calcular e insertar stints
    period_data = pbp_j.get("data", {}).get("periodData")
    if not period_data:
        print(f"   ⚠️  PBP no disponible aún para partido_id={partido_id}. Reintenta más tarde.")
        return
    all_events_flat = []
    for period in sorted(period_data, key=lambda p: p.get("periodId", 0)):
        all_events_flat.extend(period.get("events", []))

    stints = calcular_stints(all_events_flat, equipo_ids, mapa_players, starters_dict, partido_id)

    if stints:
        try:
            seen = set()
            stints_dedup = []
            for s in stints:
                key = (s["partido_id"], s["player_id"], s["period"], s["clock_start"])
                if key not in seen:
                    seen.add(key)
                    stints_dedup.append(s)
            if len(stints_dedup) < len(stints):
                print(f"   ⚠️ {len(stints) - len(stints_dedup)} stints duplicados eliminados.")
            supabase.table("stints").delete().eq("partido_id", partido_id).execute()
            n = insertar_chunked(supabase, "stints", stints_dedup,
                                 on_conflict="partido_id,player_id,period,clock_start")
            print(f"   ✅ {n} stints insertados para partido_id={partido_id}.")
        except Exception as e:
            print(f"   ❌ Error insertando stints: {e}")
    else:
        print(f"   ⚠️ No se generaron stints para partido_id={partido_id}.")


def insertar_pbp_scores(supabase, partido_id, all_events, equipo_ids):
    """
    Extrae el marcador de cada evento del PBP y lo inserta en pbp_scores.
    Guarda una fila por (partido_id, period, clock_secs, equipo_id) único.
    """
    rows = []
    seen = set()   # (period, clock_secs, equipo_id)

    for ev in all_events:
        scores = ev.get("scores") or {}
        if not scores:
            continue

        clock_str = ev.get("clock", "")
        m = re.match(r"PT(\d+)M(\d+(?:\.\d+)?)S", clock_str.upper()) if clock_str else None
        if not m:
            continue
        clock_secs = int(m.group(1)) * 60 + int(float(m.group(2)))

        try:
            period = int(ev.get("periodId", 0))
        except (TypeError, ValueError):
            continue
        if period < 1:
            continue

        for entity_id, score_val in scores.items():
            eq_id = equipo_ids.get(entity_id)
            if not eq_id:
                continue
            key = (period, clock_secs, eq_id)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "partido_id": partido_id,
                "period":     period,
                "clock_secs": clock_secs,
                "equipo_id":  eq_id,
                "score":      safe_int(score_val),
            })

    if rows:
        try:
            supabase.table("pbp_scores").delete().eq("partido_id", partido_id).execute()
            n = insertar_chunked(supabase, "pbp_scores", rows)
            print(f"   ✅ pbp_scores: {n} filas insertadas.")
        except Exception as e:
            print(f"   ❌ Error insertando pbp_scores: {e}")
    else:
        print(f"   ⚠️  pbp_scores: no se encontraron eventos con marcador.")


def calcular_posesiones(all_events, equipo_ids, partido_id):
    """
    Calcula las posesiones de cada equipo a partir del PBP.

    Señales de cambio de posesión:
      - rebound defensive      → el equipo que rebotea inicia posesión
      - turnover               → el rival inicia posesión (el steal se ignora)
      - 2pt/3pt success=true   → el rival inicia posesión
      - freeThrow (último de
        la serie) success=true → el rival inicia posesión
      - jumpBall won           → el equipo ganador inicia posesión
      - fin de periodo         → cierra la posesión actual en clock=0

    Retorna list[dict] con una fila por posesión.
    """
    def parse_clk(s):
        if not s:
            return None
        m = re.match(r"PT(\d+)M(\d+(?:\.\d+)?)S", str(s).upper())
        if m:
            return int(m.group(1)) * 60 + int(float(m.group(2)))
        return None

    def period_max_secs(pid):
        return 300 if int(pid) > 4 else 600

    def other_entity(eid):
        for e in equipo_ids:
            if e != eid:
                return e
        return None

    def is_last_ft(sub_type):
        """'2Of2', '3Of3', '1Of1' → True;  '1Of2', '2Of3' → False."""
        if not sub_type:
            return False
        m = re.match(r"(\d+)Of(\d+)", str(sub_type), re.IGNORECASE)
        return bool(m) and int(m.group(1)) == int(m.group(2))

    by_period = {}
    for ev in all_events:
        p = int(ev.get("periodId", 1))
        by_period.setdefault(p, []).append(ev)

    posesiones            = []
    current_team          = None   # entity_id del equipo con posesión
    poss_clk              = None   # clock al inicio de la posesión actual
    poss_per              = None   # periodo al inicio de la posesión actual
    last_shooter          = None   # entity_id del equipo que realizó el último intento de tiro
    last_foul_type        = None   # subtipo de la última falta (para manejar TL correctamente)
    poss_before_technical = None   # equipo con posesión antes de una falta técnica

    def close_poss(end_clk):
        eq_id = equipo_ids.get(current_team)
        if eq_id and poss_clk is not None:
            dur = poss_clk - end_clk
            if dur > 0:
                posesiones.append({
                    "partido_id":    partido_id,
                    "equipo_id":     eq_id,
                    "period":        poss_per,
                    "clock_inicio":  poss_clk,
                    "clock_fin":     end_clk,
                    "duracion_segs": dur,
                })

    def start_poss(team_eid, clk, per):
        nonlocal current_team, poss_clk, poss_per
        current_team = team_eid
        poss_clk     = clk
        poss_per     = per

    for period_id in sorted(by_period.keys()):
        evs  = sorted(by_period[period_id],
                      key=lambda e: -(parse_clk(e.get("clock", "")) or 0))
        pmax = period_max_secs(period_id)

        if current_team is None:
            # Detectar equipo inicial desde jumpBall o primer evento conocido
            for ev in evs:
                if ev.get("eventType") == "jumpBall" and ev.get("eventSubType") == "won":
                    eid = ev.get("entityId", "")
                    if eid in equipo_ids:
                        start_poss(eid, pmax, period_id)
                        break
            if current_team is None:
                for ev in evs:
                    eid = ev.get("entityId", "")
                    if eid in equipo_ids:
                        start_poss(eid, pmax, period_id)
                        break
        else:
            # Continuar posesión del periodo anterior reiniciando el clock
            poss_clk = pmax
            poss_per = period_id

        last_shooter          = None  # resetear al inicio de cada periodo
        last_foul_type        = None
        poss_before_technical = None

        for ev in evs:
            et  = ev.get("eventType", "")
            est = ev.get("eventSubType", "")
            eid = ev.get("entityId", "")
            clk = parse_clk(ev.get("clock", ""))

            # Capturar tipo de falta ANTES del filtro de eid, porque faltas
            # técnicas/de banquillo pueden tener un eid que no es entity de equipo.
            if et == "foul":
                last_foul_type = est
                if est in ("technical", "benchTechnical", "coachTechnical"):
                    poss_before_technical = current_team

            if clk is None or eid not in equipo_ids:
                continue

            if et == "jumpBall" and est == "won":
                if eid != current_team:
                    close_poss(clk)
                    start_poss(eid, clk, period_id)

            elif et in ("2pt", "3pt"):
                last_shooter = eid   # registrar equipo tirador siempre
                if ev.get("success"):
                    other = other_entity(eid)
                    close_poss(clk)
                    if other:
                        start_poss(other, clk, period_id)

            elif et == "freeThrow" and is_last_ft(est) and ev.get("success"):
                if last_foul_type in ("technical", "benchTechnical", "coachTechnical"):
                    # FIBA 29.2.4: posesión vuelve al equipo que tenía el balón
                    # antes de la técnica; el reloj de tiro continúa.
                    close_poss(clk)
                    if poss_before_technical:
                        start_poss(poss_before_technical, clk, period_id)
                elif last_foul_type == "unsportsmanlike":
                    # El equipo fouled (= quien tira el TL) retiene el balón.
                    if eid != current_team:
                        close_poss(clk)
                        start_poss(eid, clk, period_id)
                else:
                    # personal, drawn, o sin falta registrada → rival recibe.
                    other = other_entity(eid)
                    close_poss(clk)
                    if other:
                        start_poss(other, clk, period_id)
                last_foul_type        = None
                poss_before_technical = None

            elif et == "rebound":
                # Usamos last_shooter para detectar rebotes mal etiquetados:
                # si el equipo que rebotea ≠ equipo que tiró, hubo cambio de posesión
                # (independientemente de que Sportradar lo llame "offensive" o "defensive").
                # Si last_shooter es None (inicio de periodo sin tiro previo), caemos
                # al comportamiento clásico basado en la etiqueta.
                if last_shooter is not None:
                    if eid != last_shooter and eid != current_team:
                        close_poss(clk)
                        start_poss(eid, clk, period_id)
                else:
                    # Fallback: respetar la etiqueta de Sportradar
                    if est == "defensive" and eid != current_team:
                        close_poss(clk)
                        start_poss(eid, clk, period_id)

            elif et == "turnover":
                other = other_entity(eid)
                close_poss(clk)
                if other:
                    start_poss(other, clk, period_id)

            # steal, assist, block, foul, freeThrow no-último,
            # substitution, timeOut → no cambian posesión

        # Cerrar última posesión del periodo en el buzzer
        close_poss(0)

    return posesiones


def _calc_poss_formula(fga, fgm, or_, opp_dr, to_, fta):
    """Fórmula de posesiones del box score (igual que en calcular_stints)."""
    denom    = or_ + opp_dr
    miss_adj = (or_ / denom) * (fga - fgm) * 1.07 if denom > 0 else 0
    return fga - miss_adj + to_ + 0.4 * fta


def insertar_posesiones(supabase, partido_id, posesiones, formula_poss=None):
    """
    Inserta las posesiones en la BD y valida el conteo contra la fórmula del box score.

    formula_poss: dict {equipo_id: float} — resultado de _calc_poss_formula por equipo.
                  Si se provee, imprime la comparación PBP vs fórmula.
    """
    from collections import defaultdict

    if not posesiones:
        print(f"   ⚠️  posesiones: no se generaron posesiones para partido_id={partido_id}.")
        return

    try:
        supabase.table("posesiones").delete().eq("partido_id", partido_id).execute()
        n = insertar_chunked(supabase, "posesiones", posesiones)
        print(f"   ✅ posesiones: {n} filas insertadas.")

        # Agrupar por (equipo_id, period)
        by_eq_per = defaultdict(lambda: defaultdict(list))
        for p in posesiones:
            by_eq_per[p["equipo_id"]][p["period"]].append(p["duracion_segs"])

        all_eq_ids = sorted(by_eq_per.keys())

        # ── Resumen global por equipo
        for eq_id in all_eq_ids:
            all_durs = [d for durs in by_eq_per[eq_id].values() for d in durs]
            cnt   = len(all_durs)
            avg   = round(sum(all_durs) / cnt, 1)
            trans = sum(1 for d in all_durs if d <= 8)
            pct_t = round(trans / cnt * 100, 1)
            print(f"      equipo_id={eq_id}: {cnt} pos | avg={avg}s | transición={pct_t}%")
            if formula_poss and eq_id in formula_poss:
                formula_n = formula_poss[eq_id]
                delta     = abs(cnt - formula_n)
                flag      = "✅" if delta <= 4 else "⚠️ "
                print(f"      {flag} Validación PBP vs fórmula: {cnt} vs {formula_n:.1f} (Δ={delta:.1f})")

        # ── Desglose por cuarto y mitad
        def poss_q(eq_id, period):
            return len(by_eq_per[eq_id].get(period, []))

        def pace_for(periods, mins):
            """Pace normalizado a 40 min: 20 × (posA + posB) / mins."""
            total = sum(poss_q(e, p) for e in all_eq_ids for p in periods)
            return round(20 * total / mins, 1) if mins > 0 else None

        print(f"      {'─'*48}")
        print(f"      {'':20s}  Q1    Q2    Q3    Q4  │   H1    H2  │  Total")
        for eq_id in all_eq_ids:
            q = [poss_q(eq_id, i) for i in range(1, 5)]
            h1, h2 = q[0]+q[1], q[2]+q[3]
            tot = h1 + h2
            print(f"      Pos equipo_id={eq_id}  "
                  f"{q[0]:>3}   {q[1]:>3}   {q[2]:>3}   {q[3]:>3}  │  "
                  f"{h1:>4} {h2:>4}  │  {tot:>5}")
        pace_row = [pace_for([i], 10) for i in range(1, 5)]
        ph1 = pace_for([1, 2], 20)
        ph2 = pace_for([3, 4], 20)
        pt  = pace_for([1, 2, 3, 4], 40)
        print(f"      Pace              "
              f"{pace_row[0]:>5.1f} {pace_row[1]:>5.1f} {pace_row[2]:>5.1f} {pace_row[3]:>5.1f}  │"
              f" {ph1:>5.1f} {ph2:>5.1f}  │  {pt:>5.1f}")

    except Exception as e:
        print(f"   ❌ Error insertando posesiones: {e}")


def backfill_posesiones(supabase, partido_id):
    """Re-descarga el JSON y recalcula/reinserta posesiones para un partido ya procesado."""
    print(f"\n   🔁 Backfill posesiones — partido_id={partido_id}")

    try:
        res = (supabase.table("partidos")
               .select("game_json_url")
               .eq("partido_id", partido_id)
               .single()
               .execute())
        box_url = (res.data or {}).get("game_json_url")
        if not box_url:
            print(f"   ⚠️ No hay game_json_url para partido_id={partido_id}. Saltando.")
            return
    except Exception as e:
        print(f"   ❌ Error obteniendo URL: {e}")
        return

    try:
        box, pbp_j, _ = cargar_jsons(box_url)
    except Exception as e:
        print(f"   ❌ Error descargando JSONs: {e}")
        return

    try:
        _, _, _, equipo_map, _, _ = parsear_box(box)
        entity_list  = list(equipo_map.keys())
        codes        = [equipo_map[e]["code"] for e in entity_list]
        res_eq = (supabase.table("equipos")
                  .select("equipo_id, abreviatura")
                  .in_("abreviatura", codes)
                  .execute())
        code_to_dbid = {r["abreviatura"]: r["equipo_id"] for r in (res_eq.data or [])}
        equipo_ids   = {eid: code_to_dbid[equipo_map[eid]["code"]]
                        for eid in entity_list
                        if equipo_map[eid]["code"] in code_to_dbid}
        if len(equipo_ids) < 2:
            print(f"   ❌ No se resolvieron los 2 equipos. Saltando.")
            return
    except Exception as e:
        print(f"   ❌ Error resolviendo equipos: {e}")
        return

    period_data = pbp_j.get("data", {}).get("periodData", [])
    all_events_flat = []
    for period in sorted(period_data, key=lambda p: p.get("periodId", 0)):
        all_events_flat.extend(period.get("events", []))

    # Validación desde partidos_detalle
    formula_poss = {}
    try:
        res_det = (supabase.table("partidos_detalle")
                   .select("equipo_id, tot_sfieldgoalsattempted, tot_sfieldgoalsmade, "
                           "tot_sreboundsoffensive, tot_sreboundsdefensive, "
                           "tot_sturnovers, tot_sfreethrowsattempted")
                   .eq("partido_id", partido_id)
                   .execute())
        rows = res_det.data or []
        if len(rows) == 2:
            d = {r["equipo_id"]: r for r in rows}
            ids = list(d.keys())
            for eq_id in ids:
                opp_id = ids[1] if eq_id == ids[0] else ids[0]
                s, opp = d[eq_id], d[opp_id]
                formula_poss[eq_id] = _calc_poss_formula(
                    safe_int(s.get("tot_sfieldgoalsattempted")),
                    safe_int(s.get("tot_sfieldgoalsmade")),
                    safe_int(s.get("tot_sreboundsoffensive")),
                    safe_int(opp.get("tot_sreboundsdefensive")),
                    safe_int(s.get("tot_sturnovers")),
                    safe_int(s.get("tot_sfreethrowsattempted")),
                )
    except Exception as e:
        print(f"   ⚠️ No se pudo calcular validación de fórmula: {e}")

    posesiones = calcular_posesiones(all_events_flat, equipo_ids, partido_id)
    insertar_posesiones(supabase, partido_id, posesiones, formula_poss or None)


def backfill_pbp_scores(supabase, partido_id):
    """
    Re-descarga el JSON y recalcula/reinserta pbp_scores para un partido ya procesado.
    """
    print(f"\n   🔁 Backfill pbp_scores — partido_id={partido_id}")

    try:
        res = supabase.table("partidos") \
            .select("game_json_url") \
            .eq("partido_id", partido_id) \
            .single() \
            .execute()
        box_url = (res.data or {}).get("game_json_url")
        if not box_url:
            print(f"   ⚠️ No hay game_json_url para partido_id={partido_id}. Saltando.")
            return
    except Exception as e:
        print(f"   ❌ Error obteniendo URL: {e}")
        return

    try:
        box, pbp_j, _ = cargar_jsons(box_url)
    except Exception as e:
        print(f"   ❌ Error descargando JSONs: {e}")
        return

    try:
        _, _, _, equipo_map, _, _ = parsear_box(box)
    except Exception as e:
        print(f"   ❌ Error parseando box: {e}")
        return

    try:
        entity_list  = list(equipo_map.keys())
        codes        = [equipo_map[e]["code"] for e in entity_list]
        res_eq = supabase.table("equipos") \
            .select("equipo_id, abreviatura") \
            .in_("abreviatura", codes) \
            .execute()
        code_to_dbid = {r["abreviatura"]: r["equipo_id"] for r in (res_eq.data or [])}
        equipo_ids   = {eid: code_to_dbid[equipo_map[eid]["code"]]
                        for eid in entity_list
                        if equipo_map[eid]["code"] in code_to_dbid}
        if len(equipo_ids) < 2:
            print(f"   ❌ No se resolvieron los 2 equipos. Saltando.")
            return
    except Exception as e:
        print(f"   ❌ Error resolviendo equipos: {e}")
        return

    period_data = pbp_j.get("data", {}).get("periodData", [])
    all_events_flat = []
    for period in sorted(period_data, key=lambda p: p.get("periodId", 0)):
        all_events_flat.extend(period.get("events", []))

    insertar_pbp_scores(supabase, partido_id, all_events_flat, equipo_ids)


def calcular_garbage_time(all_events, equipo_ids):
    """
    Detecta el inicio del Garbage Time en el 4to cuarto.
    Umbrales adaptados para cuartos de 10 min (proporcional a NBA 12 min):
      10:00-7:30 (>=450 seg): diferencial >= 25
       7:30-5:00 (>=300 seg): diferencial >= 20
       5:00-0:00 (  <300 seg): diferencial >= 10
    Retorna dict {gt_start_secs, gt_scores: {entity_id: pts}}
    o None si no hubo garbage time.
    """
    def parse_clk(s):
        m = re.match(r"PT(\d+)M(\d+)S", s or "")
        return int(m.group(1)) * 60 + int(m.group(2)) if m else 0

    def threshold(secs):
        if secs >= 450: return 25
        if secs >= 300: return 20
        return 10

    eids = list(equipo_ids.keys())
    if len(eids) < 2:
        return None

    q4 = [e for e in all_events if int(e.get("periodId", 0)) == 4]
    q4.sort(key=lambda e: -parse_clk(e.get("clock", "")))

    gt_start_secs = None
    gt_scores     = None

    for ev in q4:
        scores = ev.get("scores") or {}
        if not scores:
            continue
        pts = {eid: safe_int(scores.get(eid, 0)) for eid in eids}
        if all(v == 0 for v in pts.values()):
            continue

        secs = parse_clk(ev.get("clock", ""))
        vals = list(pts.values())
        diff = abs(vals[0] - vals[1])
        thr  = threshold(secs)

        if diff >= thr:
            if gt_start_secs is None:
                gt_start_secs = secs
                gt_scores     = pts
        else:
            gt_start_secs = None
            gt_scores     = None

    if gt_start_secs is None:
        return None
    return {
        "gt_start_secs": gt_start_secs,
        "gt_scores":     gt_scores,
        "gt_minutos":     round(gt_start_secs / 60, 1),
    }


def backfill_partidos_detalle(supabase, partido_id):
    """
    Re-descarga el JSON de un partido ya procesado y recalcula/reinserta
    partidos_detalle (útil para corregir FGA=0, fecha incorrecta, etc.).
    """
    print(f"\n   🔁 Backfill partidos_detalle — partido_id={partido_id}")

    # 1. Obtener URL y match_time_utc desde la BD
    try:
        res = supabase.table("partidos") \
            .select("game_json_url, match_time_utc") \
            .eq("partido_id", partido_id) \
            .single() \
            .execute()
        box_url        = (res.data or {}).get("game_json_url")
        match_time_utc = (res.data or {}).get("match_time_utc", "")
        if not box_url:
            print(f"   ⚠️ No hay game_json_url para partido_id={partido_id}. Saltando.")
            return
    except Exception as e:
        print(f"   ❌ Error obteniendo URL: {e}")
        return

    # 2. Descargar JSON
    try:
        box, pbp_j, _ = cargar_jsons(box_url)
    except Exception as e:
        print(f"   ❌ Error descargando JSON: {e}")
        return

    # 3. Parsear box
    try:
        info, equipos_stats, jugadores_raw, equipo_map, home_id, away_id = parsear_box(box)
    except Exception as e:
        print(f"   ❌ Error parseando box: {e}")
        return

    # Diagnóstico: verificar FGA de cada equipo
    for _i, _tm in enumerate(equipos_stats):
        print(f"   🔍 Equipo {_i+1} ({_tm.get('rol_partido','?')}) → "
              f"FGM={_tm.get('tot_sfieldgoalsmade','?')} "
              f"FGA={_tm.get('tot_sfieldgoalsattempted','?')} "
              f"2PA={_tm.get('tot_stwopointersattempted','?')} "
              f"3PA={_tm.get('tot_sthreepointersattempted','?')}")

    # 4. Resolver equipo_ids (entityId → equipo_id de la BD)
    try:
        entity_list = list(equipo_map.keys())
        codes = [equipo_map[e]["code"] for e in entity_list]
        res_eq = supabase.table("equipos") \
            .select("equipo_id, abreviatura") \
            .in_("abreviatura", codes) \
            .execute()
        code_to_dbid = {r["abreviatura"]: r["equipo_id"] for r in (res_eq.data or [])}
        equipo_ids = {eid: code_to_dbid[equipo_map[eid]["code"]]
                      for eid in entity_list
                      if equipo_map[eid]["code"] in code_to_dbid}
        if len(equipo_ids) < 2:
            print(f"   ❌ No se resolvieron los 2 equipos. Saltando.")
            return
    except Exception as e:
        print(f"   ❌ Error resolviendo equipos: {e}")
        return

    # 5. Recalcular fecha (UTC-5 = Cancún)
    # Fuente primaria: match_time_utc de la BD (más confiable que el JSON de la API)
    start_utc   = info.get("start_utc", "")
    start_local = info.get("start_local", "")
    from datetime import timedelta
    dia = None
    try:
        # Prioridad 1: match_time_utc de la BD
        if match_time_utc:
            _utc_dt = datetime.fromisoformat(
                str(match_time_utc).replace("Z", "").split(".")[0].replace(" ", "T").split("+")[0]
            )
            _cst_dt = _utc_dt - timedelta(hours=5)
            dia = _cst_dt.strftime("%Y-%m-%d")
            hora = _utc_dt.strftime("%H:%M:%S")
        # Prioridad 2: startTimeUTC del JSON
        elif start_utc:
            _utc_dt = datetime.fromisoformat(
                start_utc.replace("Z", "").split(".")[0].replace(" ", "T")
            )
            _cst_dt = _utc_dt - timedelta(hours=5)
            dia = _cst_dt.strftime("%Y-%m-%d")
            hora = _utc_dt.strftime("%H:%M:%S")
        # Prioridad 3: startDateTime del JSON (local, sin conversión)
        elif start_local:
            dia  = start_local[:10]
            hora = start_local[11:19] if len(start_local) >= 19 else None
        else:
            hora = None
    except Exception:
        hora = start_utc[11:19] if len(start_utc) >= 19 else None
        if not dia:
            dia = start_local[:10] if start_local else (start_utc[:10] if start_utc else None)
    print(f"   📅 Fecha calculada: {dia}  (match_time_utc={match_time_utc})")

    # 6. (dia va directo en partidos_detalle — no existe en tabla partidos)

    # 7. Recalcular partidos_detalle
    tm1, tm2 = equipos_stats[0], equipos_stats[1]
    av1 = calcular_avanzadas(tm1, tm2)
    av2 = calcular_avanzadas(tm2, tm1)
    ritmo = round((av1["posesiones"] + av2["posesiones"]) / 2, 1)

    _pbp_data_gt = pbp_j.get("data", {}).get("pbp", {})
    _events_gt   = []
    for _ps in sorted(_pbp_data_gt.keys(), key=lambda x: int(x)):
        _events_gt.extend(_pbp_data_gt[_ps].get("events", []))
    gt = calcular_garbage_time(_events_gt, equipo_ids)

    detalle_payloads = []
    for tm, av, eid in [(tm1, av1, home_id), (tm2, av2, away_id)]:
        rival_eid = away_id if eid == home_id else home_id
        rival = tm2 if eid == home_id else tm1
        tot_cols = {k: tm[k] for k in tm if k.startswith("tot_")}
        av_cols  = {k: av[k] for k in av if k != "victoria"}
        row = {
            "partido_id":      partido_id,
            "equipo_id":       equipo_ids[eid],
            "dia":             dia,
            "hora":            hora,
            "score":           tm["score"],
            "full_score":      tm["full_score"],
            "victoria":        av["victoria"],
            "puntos_rival":    tm["rival_score"],
            "rebotes_d_rival": rival.get("tot_sreboundsdefensive", 0),
            "rol_partido":     tm["rol_partido"],
            "etapa":           tm["etapa"],
            "coach_nombre":    tm["coach_nombre"],
            "ritmo":           ritmo,
            "gt_start_secs":   gt["gt_start_secs"]               if gt else None,
            "gt_score_propio": gt["gt_scores"].get(eid)          if gt else None,
            "gt_score_rival":  gt["gt_scores"].get(rival_eid)    if gt else None,
            **tot_cols,
            **av_cols,
        }
        detalle_payloads.append(row)

    try:
        supabase.table("partidos_detalle").upsert(
            detalle_payloads, on_conflict="partido_id,equipo_id"
        ).execute()
        print(f"   ✅ partidos_detalle recalculado y actualizado (partido_id={partido_id}, dia={dia}).")
    except Exception as e:
        print(f"   ❌ Error actualizando partidos_detalle: {e}")


def backfill_tiros(supabase, partido_id):
    """
    Re-descarga el shot chart y reinserta tiros para un partido ya procesado.
    """
    print(f"\n   🔁 Backfill tiros — partido_id={partido_id}")

    try:
        res = supabase.table("partidos") \
            .select("game_json_url") \
            .eq("partido_id", partido_id) \
            .single() \
            .execute()
        box_url = (res.data or {}).get("game_json_url")
        if not box_url:
            print(f"   ⚠️ No hay game_json_url para partido_id={partido_id}. Saltando.")
            return
    except Exception as e:
        print(f"   ❌ Error obteniendo URL: {e}")
        return

    try:
        box, _, tiros_j = cargar_jsons(box_url)
    except Exception as e:
        print(f"   ❌ Error descargando JSONs: {e}")
        return

    try:
        _, _, jugadores_raw, equipo_map, _, _ = parsear_box(box)
    except Exception as e:
        print(f"   ❌ Error parseando box: {e}")
        return

    try:
        entity_list  = list(equipo_map.keys())
        codes        = [equipo_map[e]["code"] for e in entity_list]
        res_eq = supabase.table("equipos") \
            .select("equipo_id, abreviatura") \
            .in_("abreviatura", codes) \
            .execute()
        code_to_dbid = {r["abreviatura"]: r["equipo_id"] for r in (res_eq.data or [])}
        equipo_ids   = {eid: code_to_dbid[equipo_map[eid]["code"]]
                        for eid in entity_list
                        if equipo_map[eid]["code"] in code_to_dbid}
        if len(equipo_ids) < 2:
            print(f"   ❌ No se resolvieron los 2 equipos. Saltando.")
            return
    except Exception as e:
        print(f"   ❌ Error resolviendo equipos: {e}")
        return

    try:
        person_ids = [j["personId"] for j in jugadores_raw if j.get("personId")]
        res_pl = supabase.table("players") \
            .select("player_id, person_id_ext") \
            .in_("person_id_ext", person_ids) \
            .execute()
        mapa_players = {r["person_id_ext"]: r["player_id"] for r in (res_pl.data or [])}
    except Exception as e:
        print(f"   ❌ Error obteniendo players: {e}")
        return

    period_data_t = tiros_j.get("data", {}).get("periodData", [])
    shots = []
    for period in sorted(period_data_t, key=lambda p: p.get("periodId", 0)):
        shots.extend(period.get("shots", []))
    tiros = []
    for i, s in enumerate(shots, 1):
        eid         = s.get("entityId", "")
        eq_info     = equipo_map.get(eid, {})
        person_id_s = s.get("personId")
        player_id_t = mapa_players.get(person_id_s) if person_id_s else None
        tiros.append({
            "partido_id":     partido_id,
            "equipo_id":      equipo_ids.get(eid),
            "player_id":      player_id_t,
            "r":              1 if s.get("success") else 0,
            "x":              s.get("x"),
            "y":              s.get("y"),
            "p":              None,
            "pno":            None,
            "tno":            safe_int(eq_info.get("tno")),
            "per":            safe_int(s.get("periodId", 1)),
            "pertype":        "OVERTIME" if safe_int(s.get("periodId", 1)) > 4 else "REGULAR",
            "actiontype":     trunc(s.get("eventType", ""), 50),
            "actionnumber":   i,
            "previousaction": None,
            "subtype":        trunc(s.get("subType", ""), 50),
            "player":         trunc(s.get("name", ""), 100),
            "shirtnumber":    safe_int(s.get("bib")),
            "tiro_zona":      classify_shot(s.get("x", 0), s.get("y", 0)),
            "tiro_zona_beta": None,
        })

    if tiros:
        try:
            supabase.table("tiros").delete().eq("partido_id", partido_id).execute()
            n = insertar_chunked(supabase, "tiros", tiros)
            print(f"   ✅ tiros: {n} filas insertadas.")
        except Exception as e:
            print(f"   ❌ Error insertando tiros: {e}")
    else:
        print(f"   ⚠️ No se encontraron tiros para partido_id={partido_id}.")


def backfill_acciones(supabase, partido_id):
    """
    Re-descarga el JSON y recalcula/reinserta acciones_partido para un partido ya procesado.
    """
    print(f"\n   🔁 Backfill acciones_partido — partido_id={partido_id}")

    try:
        res = supabase.table("partidos") \
            .select("game_json_url") \
            .eq("partido_id", partido_id) \
            .single() \
            .execute()
        box_url = (res.data or {}).get("game_json_url")
        if not box_url:
            print(f"   ⚠️ No hay game_json_url para partido_id={partido_id}. Saltando.")
            return
    except Exception as e:
        print(f"   ❌ Error obteniendo URL: {e}")
        return

    try:
        box, pbp_j, _ = cargar_jsons(box_url)
    except Exception as e:
        print(f"   ❌ Error descargando JSONs: {e}")
        return

    try:
        _, _, jugadores_raw, equipo_map, home_id, away_id = parsear_box(box)
    except Exception as e:
        print(f"   ❌ Error parseando box: {e}")
        return

    try:
        entity_list  = list(equipo_map.keys())
        codes        = [equipo_map[e]["code"] for e in entity_list]
        res_eq = supabase.table("equipos") \
            .select("equipo_id, abreviatura") \
            .in_("abreviatura", codes) \
            .execute()
        code_to_dbid = {r["abreviatura"]: r["equipo_id"] for r in (res_eq.data or [])}
        equipo_ids   = {eid: code_to_dbid[equipo_map[eid]["code"]]
                        for eid in entity_list
                        if equipo_map[eid]["code"] in code_to_dbid}
        if len(equipo_ids) < 2:
            print(f"   ❌ No se resolvieron los 2 equipos. Saltando.")
            return
    except Exception as e:
        print(f"   ❌ Error resolviendo equipos: {e}")
        return

    try:
        person_ids = [j["personId"] for j in jugadores_raw if j.get("personId")]
        res_pl = supabase.table("players") \
            .select("player_id, person_id_ext") \
            .in_("person_id_ext", person_ids) \
            .execute()
        mapa_players = {r["person_id_ext"]: r["player_id"] for r in (res_pl.data or [])}
    except Exception as e:
        print(f"   ❌ Error obteniendo players: {e}")
        return

    period_data = pbp_j.get("data", {}).get("periodData", [])
    if not period_data:
        print(f"   ⚠️  PBP no disponible para partido_id={partido_id}.")
        return

    all_events_flat = []
    for period in sorted(period_data, key=lambda p: p.get("periodId", 0)):
        all_events_flat.extend(period.get("events", []))

    is_live_map, _, _ = calcular_to_metrics(all_events_flat)

    home_eid = next((k for k, v in equipo_map.items() if     v["isHome"]), None)
    away_eid = next((k for k, v in equipo_map.items() if not v["isHome"]), None)

    acciones   = []
    action_num = 1
    ev_idx     = 0
    for periodo in sorted(period_data, key=lambda p: p.get("periodId", 0)):
        events   = periodo.get("events", [])
        is_ot    = periodo.get("isOvertime", False)
        per_type = "OVERTIME" if is_ot else "REGULAR"

        for ev in events:
            eid     = ev.get("entityId", "")
            eq_info = equipo_map.get(eid, {})
            scores  = ev.get("scores", {}) or {}
            s1 = safe_int(scores.get(home_eid, 0))
            s2 = safe_int(scores.get(away_eid, 0))
            first_name, family_name = split_name(ev.get("name", ""))
            person_id_ev = ev.get("personId")
            player_id_a  = mapa_players.get(person_id_ev) if person_id_ev else None

            acciones.append({
                "partido_id":      partido_id,
                "actionnumber":    action_num,
                "equipo_id":       equipo_ids.get(eid),
                "player_id":       player_id_a,
                "tno":             safe_int(eq_info.get("tno")),
                "pno":             None,
                "gt":              calcular_gt(ev.get("periodId", 1), ev.get("clock")),
                "clock":           clock_iso_to_mmss(ev.get("clock")),
                "s1":              s1,
                "s2":              s2,
                "lead":            s1 - s2,
                "period":          safe_int(ev.get("periodId", 1)),
                "periodtype":      per_type,
                "success":         safe_bool(ev.get("success")),
                "actiontype":      trunc(ev.get("eventType", ""), 50),
                "previousaction":  None,
                "qualifier":       None,
                "subtype":         trunc(ev.get("eventSubType", ""), 50),
                "scoring":         None,
                "shirtnumber":     safe_int(ev.get("bib")),
                "player":          trunc(ev.get("name", ""), 100),
                "firstname":       trunc(first_name, 50),
                "familyname":      trunc(family_name, 50),
                "is_live_ball_to": is_live_map.get(ev_idx),
            })
            action_num += 1
            ev_idx     += 1

    if acciones:
        try:
            supabase.table("acciones_partido").delete().eq("partido_id", partido_id).execute()
            n = insertar_chunked(supabase, "acciones_partido", acciones, "partido_id,actionnumber")
            print(f"   ✅ acciones_partido: {n} filas insertadas.")
        except Exception as e:
            print(f"   ❌ Error insertando acciones_partido: {e}")
    else:
        print(f"   ⚠️ No se generaron acciones para partido_id={partido_id}.")


def backfill_to_metrics(supabase, partido_id):
    """
    Lee acciones_partido de la BD para un partido ya procesado y actualiza:
      - is_live_ball_to en acciones_partido
      - live_ball_to / dead_ball_to en players_detalle
      - live_ball_to / dead_ball_to / pts_off_opp_live_to en partidos_detalle
    """
    print(f"\n   🔄 Backfill TO metrics — partido_id={partido_id}")

    res = supabase.table("acciones_partido") \
        .select("actionnumber, actiontype, subtype, equipo_id, player_id, s1, s2, tno, success") \
        .eq("partido_id", partido_id) \
        .order("actionnumber") \
        .execute()
    events = res.data or []

    if not events:
        print(f"   ⚠️ Sin eventos para partido_id={partido_id}")
        return

    n = len(events)

    # Mapa equipo_id → tno (1=local→s1, 2=visitante→s2)
    equipo_tno = {}
    for ev in events:
        eid = ev.get("equipo_id")
        tno = ev.get("tno")
        if eid and tno and eid not in equipo_tno:
            equipo_tno[eid] = tno

    def _score(ev, eid):
        tno = equipo_tno.get(eid)
        if tno == 1:
            return ev.get("s1") or 0
        if tno == 2:
            return ev.get("s2") or 0
        return 0

    team_stats   = {}
    player_stats = {}
    live_nums    = []
    dead_nums    = []

    def _team(eid):
        if eid not in team_stats:
            team_stats[eid] = {"live_to": 0, "dead_to": 0, "pts_off_opp_live_to": 0}
        return team_stats[eid]

    def _player(pid):
        if pid not in player_stats:
            player_stats[pid] = {"live_to": 0, "dead_to": 0}
        return player_stats[pid]

    # Fase 1 — clasificar turnovers
    for i, ev in enumerate(events):
        if ev.get("actiontype") != "turnover":
            continue
        next_ev = events[i + 1] if i + 1 < n else None
        is_live = bool(next_ev and next_ev.get("actiontype") == "steal")

        if is_live:
            live_nums.append(ev["actionnumber"])
        else:
            dead_nums.append(ev["actionnumber"])

        eid = ev.get("equipo_id")
        pid = ev.get("player_id")

        if eid:
            ts = _team(eid)
            if is_live:
                ts["live_to"] += 1
            else:
                ts["dead_to"] += 1

        if pid:
            ps = _player(pid)
            if is_live:
                ps["live_to"] += 1
            else:
                ps["dead_to"] += 1

    # Fase 2 — pts_off_opp_live_to
    for i, ev in enumerate(events):
        if ev.get("actiontype") != "steal":
            continue

        stealing_eid   = ev.get("equipo_id")
        score_at_steal = _score(ev, stealing_eid)
        last_score     = score_at_steal

        j = i + 1
        while j < n:
            e     = events[j]
            e_eid = e.get("equipo_id")
            et    = e.get("actiontype", "")

            if et == "rebound" and e_eid != stealing_eid:
                break
            if et == "turnover" and e_eid == stealing_eid:
                break
            if et == "timeOut":
                break
            if et in ("2pt", "3pt") and e_eid != stealing_eid and e.get("success"):
                break
            if et in ("2pt", "3pt") and e_eid == stealing_eid and e.get("success"):
                current = _score(e, stealing_eid)
                if current > last_score:
                    last_score = current
                break
            if (et == "freeThrow" and e_eid == stealing_eid and
                    e.get("subtype") in ("1Of1", "2Of2", "3Of3")):
                current = _score(e, stealing_eid)
                if current > last_score:
                    last_score = current
                break
            if et == "freeThrow" and e_eid != stealing_eid:
                break

            current = _score(e, stealing_eid)
            if current > last_score:
                last_score = current
            j += 1

        pts = last_score - score_at_steal
        if pts > 0 and stealing_eid:
            _team(stealing_eid)["pts_off_opp_live_to"] += pts

    # UPDATE acciones_partido (2 queries batch)
    if live_nums:
        supabase.table("acciones_partido") \
            .update({"is_live_ball_to": True}) \
            .eq("partido_id", partido_id) \
            .in_("actionnumber", live_nums) \
            .execute()
    if dead_nums:
        supabase.table("acciones_partido") \
            .update({"is_live_ball_to": False}) \
            .eq("partido_id", partido_id) \
            .in_("actionnumber", dead_nums) \
            .execute()
    print(f"   ✅ acciones_partido: {len(live_nums)} live | {len(dead_nums)} dead")

    # UPDATE players_detalle
    for pid, stats in player_stats.items():
        supabase.table("players_detalle") \
            .update({"live_ball_to": stats["live_to"], "dead_ball_to": stats["dead_to"]}) \
            .eq("partido_id", partido_id) \
            .eq("player_id", pid) \
            .execute()
    print(f"   ✅ players_detalle: {len(player_stats)} jugadores actualizadas")

    # UPDATE partidos_detalle
    for eid, stats in team_stats.items():
        supabase.table("partidos_detalle") \
            .update({
                "live_ball_to":        stats["live_to"],
                "dead_ball_to":        stats["dead_to"],
                "pts_off_opp_live_to": stats["pts_off_opp_live_to"],
            }) \
            .eq("partido_id", partido_id) \
            .eq("equipo_id", eid) \
            .execute()
    print(f"   ✅ partidos_detalle: {len(team_stats)} equipos actualizados")


# ─────────────────────────────────────────
# PASO 9 — ENRIQUECIMIENTO BIOGRÁFICO
# ─────────────────────────────────────────

def enriquecer_bio_jugadores(supabase, mapa_players):
    """
    Consulta person_detail para cada jugador procesada y actualiza
    height_cm, weight_kg y nationality en la tabla players cuando
    el dato exista en Sportradar.
    Solo actualiza campos con valor — nunca sobreescribe con null.
    """
    total = len(mapa_players)
    print(f"\n{'─'*60}")
    print(f"🔬 PASO 9 — Enriquecimiento biográfico ({total} jugadores únicas)")

    actualizadas = 0
    sin_datos    = 0

    for person_id_ext, player_id in mapa_players.items():
        state_dict = {
            "s": SEASON_ID,
            "l": "es-ES",
            "z": "statistics",
            "p": person_id_ext,
        }
        state = base64.urlsafe_b64encode(
            zlib.compress(json.dumps(state_dict, separators=(",",":")).encode())
        ).decode().rstrip("=")

        try:
            r = requests.get(f"{API_BIO}?state={state}", timeout=10)
            if r.status_code != 200:
                sin_datos += 1
                continue

            info = r.json().get("data", {}).get("person", {}).get("info", [])

            update = {}
            for item in info:
                k = item.get("key", "")
                v = item.get("value")
                if v is None:
                    continue
                if k == "height":
                    update["height_cm"] = safe_int(v)
                elif k == "weight":
                    update["weight_kg"] = safe_int(v)
                elif k == "nationality":
                    if player_id in NATIONALITY_OVERRIDES:
                        update["nationality"] = NATIONALITY_OVERRIDES[player_id]
                    else:
                        update["nationality"] = str(v)

            if update:
                supabase.table("players").update(update).eq("player_id", player_id).execute()
                campos = ", ".join(f"{k}={v}" for k, v in update.items())
                print(f"   ✅ player_id={player_id:<5} → {campos}")
                actualizadas += 1
            else:
                sin_datos += 1

        except Exception as e:
            print(f"   ⚠️ Error en player_id={player_id} ({person_id_ext[:8]}...): {e}")

    print(f"\n   📊 Con datos: {actualizadas} | Sin datos en API: {sin_datos}")


# ─────────────────────────────────────────
# PROCESO DE UN PARTIDO
# ─────────────────────────────────────────

def procesar_partido(supabase, box_url, partido_id,
                     mapa_n, mapa_c, equipos_raw, mapa_n_comp, mapa_c_comp, codigos_dup,
                     mapa_players):
    """
    Descarga, parsea e inserta un partido completo en Supabase.
    Retorna True si se completó, False si se saltó.
    """
    print(f"\n{'─'*60}")
    print(f"⚡ Partido ID: {partido_id}")
    print(f"   URL: {box_url[:90]}...")

    # ── 1. Descargar JSONs
    box, pbp_j, tiros_j = cargar_jsons(box_url)

    # ── 1.5. Verificar que el partido haya concluido (status == "CONFIRMED")
    fixture_node = pbp_j.get("data", {}).get("fixture", {})
    status       = fixture_node.get("status", "")
    if status != "CONFIRMED":
        if partido_id in FORCE_PARTIDO_IDS:
            print(f"   ⚠️  Partido en status='{status}' — procesando igual por FORCE_PARTIDO_IDS.")
        else:
            print(f"   ⏳ Partido no finalizado (status='{status}'). Saltando.")
            return False

    # ── 2. Parsear box score
    info, equipos_stats, jugadores_raw, equipo_map, home_id, away_id = parsear_box(box)

    # ── 3. Resolver equipo_id (FK → tabla equipos)
    equipo_ids = {}   # entityId (UUID) → equipo_id (int)
    for eid, eq_info in equipo_map.items():
        db_id, metodo = team_utils.buscar_id_equipo(
            nombre_json=eq_info["name"],
            codigo_json=eq_info["code"],
            mapa_nombre=mapa_n,
            mapa_codigo=mapa_c,
            equipos_raw=equipos_raw,
            competicion_id=COMPETICION_ID,
            mapa_nombre_comp=mapa_n_comp,
            mapa_codigo_comp=mapa_c_comp,
            codigos_duplicados_comp=codigos_dup,
        )
        if db_id:
            equipo_ids[eid] = db_id
            print(f"   🏀 '{eq_info['code']}' → equipo_id={db_id} ({metodo})")
        else:
            team_utils.log_equipo_no_encontrado(
                eq_info["name"], eq_info["code"], partido_id, "NuevaLiga_DB"
            )

    if len(equipo_ids) < 2:
        print(f"   ❌ Faltan equipos. Saltando partido {partido_id}.")
        return False

    # ── 4. Insertar PARTIDOS
    start_utc   = info.get("start_utc", "")
    start_local = info.get("start_local", "")
    # Cancún = UTC-5 permanente (sin horario de verano).
    # startDateTime de la API puede venir en UTC, así que derivamos dia desde startTimeUTC - 5h
    # para evitar que un partido nocturno (ej. 22:00 CST = 03:00 UTC +1 día) tome la fecha incorrecta.
    hora = start_utc[11:19] if len(start_utc) >= 19 else None
    try:
        if start_utc:
            from datetime import timedelta
            _utc_dt = datetime.fromisoformat(
                start_utc.replace("Z", "").split(".")[0].replace(" ", "T")
            )
            _cst_dt = _utc_dt - timedelta(hours=5)
            dia = _cst_dt.strftime("%Y-%m-%d")
        elif start_local:
            dia = start_local[:10]
        else:
            dia = None
    except Exception:
        dia = start_local[:10] if start_local else (start_utc[:10] if start_utc else None)

    try:
        supabase.table("partidos") \
            .update({"timestamp_ingestion": datetime.now().isoformat()}) \
            .eq("partido_id", partido_id) \
            .eq("competicion_id", COMPETICION_ID) \
            .execute()
        print(f"   ✅ partidos: partido_id={partido_id} actualizado.")
    except Exception as e:
        print(f"   ❌ Error insertando partidos: {e}")
        return False

    # ── 5. Calcular avanzadas e insertar PARTIDOS_DETALLE
    tm1, tm2 = equipos_stats[0], equipos_stats[1]
    av1 = calcular_avanzadas(tm1, tm2)
    av2 = calcular_avanzadas(tm2, tm1)
    ritmo = round((av1["posesiones"] + av2["posesiones"]) / 2, 1)

    # Garbage time (requiere PBP — se calcula antes del upsert)
    _pbp_data_gt = pbp_j.get("data", {}).get("pbp", {})
    _events_gt   = []
    for _ps in sorted(_pbp_data_gt.keys(), key=lambda x: int(x)):
        _events_gt.extend(_pbp_data_gt[_ps].get("events", []))
    gt = calcular_garbage_time(_events_gt, equipo_ids)

    detalle_payloads = []
    for tm, av, eid in [(tm1, av1, home_id), (tm2, av2, away_id)]:
        rival_eid = away_id if eid == home_id else home_id
        rival = tm2 if eid == home_id else tm1
        tot_cols = {k: tm[k] for k in tm if k.startswith("tot_")}
        av_cols  = {k: av[k] for k in av if k != "victoria"}
        row = {
            "partido_id":      partido_id,
            "equipo_id":       equipo_ids[eid],
            "dia":             dia,
            "hora":            hora,
            "score":           tm["score"],
            "full_score":      tm["full_score"],
            "victoria":        av["victoria"],
            "puntos_rival":    tm["rival_score"],
            "rebotes_d_rival": rival.get("tot_sreboundsdefensive", 0),
            "rol_partido":     tm["rol_partido"],
            "etapa":           tm["etapa"],
            "coach_nombre":    tm["coach_nombre"],
            "ritmo":           ritmo,
            "gt_start_secs":   gt["gt_start_secs"]               if gt else None,
            "gt_score_propio": gt["gt_scores"].get(eid)          if gt else None,
            "gt_score_rival":  gt["gt_scores"].get(rival_eid)    if gt else None,
            **tot_cols,
            **av_cols,
        }
        detalle_payloads.append(row)

    try:
        supabase.table("partidos_detalle").upsert(
            detalle_payloads, on_conflict="partido_id,equipo_id"
        ).execute()
        print(f"   ✅ partidos_detalle: 2 filas insertadas.")
    except Exception as e:
        print(f"   ❌ Error insertando partidos_detalle: {e}")

    # ── 6. Procesar PLAYERS + PLAYERS_DETALLE
    # Se incluyen todos los jugadores del box; DNP quedan con stats en cero.
    detalle_jugadores = []
    for j in jugadores_raw:
        person_id    = j.get("personId", "")
        person_name  = j.get("personName", "")
        participated = j.get("participated", True)

        if not person_id:
            continue

        first_name, family_name = split_name(person_name)

        pid = get_or_create_player(supabase, person_id, first_name, family_name, mapa_players)
        if not pid:
            print(f"   ⚠️ No se resolvió player_id para {person_name} ({person_id})")
            continue

        if not participated:
            row = {
                "player_id":               pid,
                "partido_id":              partido_id,
                "active":                  False,
                "starter":                 False,
                "captain":                 False,
                "sminutes":                0,
                "spoints":                 0,
                "splusminuspoints":        None,
                "sfieldgoalsmade":         0,
                "sfieldgoalsattempted":    0,
                "stwopointersmade":        0,
                "stwopointersattempted":   0,
                "sthreepointersmade":      0,
                "sthreepointersattempted": 0,
                "sfreethrowsmade":         0,
                "sfreethrowsattempted":    0,
                "sreboundsoffensive":      0,
                "sreboundsdefensive":      0,
                "sreboundstotal":          0,
                "sassists":                0,
                "sturnovers":              0,
                "ssteals":                 0,
                "sblocks":                 0,
                "sblocksreceived":         0,
                "sfoulspersonal":          0,
                "sfoulson":                0,
                "spointsinthepaint":       0,
                "spointssecondchance":     0,
                "spointsfastbreak":        0,
            }
            detalle_jugadores.append(row)
            continue

        stats = j.get("statistics", {})

        # La API omite fieldGoalsAttempted y pointsThreeAttempted a nivel jugador.
        # Se derivan con la misma lógica que a nivel equipo (porcentajes → FGA-2PA).
        _s_fgm   = safe_get(stats, "fieldGoalsMade",        0) or 0
        _s_fgpct = safe_get(stats, "fieldGoalsPercentage",  0) or 0
        _s2pa    = safe_get(stats, "pointsTwoAttempted",    0) or 0
        _s3pm    = safe_get(stats, "pointsThreeMade",       0) or 0
        _s3pct   = safe_get(stats, "pointsThreePercentage", 0) or 0

        # 3PA
        if "pointsThreeAttempted" in stats:
            _s3pa = stats["pointsThreeAttempted"] or 0
        elif _s3pct > 0:
            _s3pa = round(_s3pm * 100 / _s3pct)
        else:
            _s3pa = None  # se resolverá con FGA - 2PA

        # FGA
        if "fieldGoalsAttempted" in stats:
            _sfga = stats["fieldGoalsAttempted"] or 0
        elif _s_fgpct > 0:
            _sfga = round(_s_fgm * 100 / _s_fgpct)
        else:
            _sfga = _s2pa + (_s3pa or 0)

        if _s3pa is None:
            _s3pa = max(0, _sfga - _s2pa)

        row = {
            "player_id":               pid,
            "partido_id":              partido_id,
            "active":                  safe_bool(j.get("active")),
            "starter":                 safe_bool(j.get("starter")),
            "captain":                 False,    # no disponible en nueva liga
            "sminutes":                parse_iso_minutes(safe_get(stats, "minutes")),
            "spoints":                 safe_get(stats, "points", 0),
            "splusminuspoints":        safe_get(stats, "plusMinus"),
            "sfieldgoalsmade":         _s_fgm,
            "sfieldgoalsattempted":    _sfga,
            "stwopointersmade":        safe_get(stats, "pointsTwoMade", 0),
            "stwopointersattempted":   _s2pa,
            "sthreepointersmade":      _s3pm,
            "sthreepointersattempted": _s3pa,
            "sfreethrowsmade":         safe_get(stats, "freeThrowsMade", 0),
            "sfreethrowsattempted":    safe_get(stats, "freeThrowsAttempted", 0),
            "sreboundsoffensive":      safe_get(stats, "reboundsOffensive", 0),
            "sreboundsdefensive":      safe_get(stats, "reboundsDefensive", 0),
            "sreboundstotal":          safe_get(stats, "rebounds", 0),
            "sassists":                safe_get(stats, "assists", 0),
            "sturnovers":              safe_get(stats, "turnovers", 0),
            "ssteals":                 safe_get(stats, "steals", 0),
            "sblocks":                 safe_get(stats, "blocks", 0),
            "sblocksreceived":         safe_get(stats, "blocksReceived", 0),
            "sfoulspersonal":          safe_get(stats, "foulsTotal", 0),
            "sfoulson":                safe_get(stats, "foulsDrawn", 0),
            "spointsinthepaint":       safe_get(stats, "pointsInThePaint", 0),
            "spointssecondchance":     safe_get(stats, "pointsSecondChanceMade", 0),
            "spointsfastbreak":        0,   # no disponible por jugador en nueva liga
        }
        detalle_jugadores.append(row)

    if detalle_jugadores:
        try:
            n = insertar_chunked(supabase, "players_detalle", detalle_jugadores, "player_id,partido_id")
            print(f"   ✅ players_detalle: {n} filas insertadas.")
        except Exception as e:
            print(f"   ❌ Error insertando players_detalle: {e}")

    # ── 6.5. Rosters — insert solo jugadores nuevos (no duplicar por re-run)
    # Se incluyen todos los jugadores del box (incluso DNP con participated=False).
    roster_candidates = []
    for j in jugadores_raw:
        person_id    = j.get("personId", "")
        eid          = j.get("_entityId", "")

        if not person_id:
            continue

        pid   = mapa_players.get(person_id)
        eq_id = equipo_ids.get(eid)
        if not pid or not eq_id:
            continue

        roster_candidates.append({
            "player_id":            pid,
            "equipo_id":            eq_id,
            "competicion_id":       COMPETICION_ID,
            "shirt_number":         safe_int(j.get("bib")),
            "effective_start_date": ROSTER_START_DATE,
        })

    if roster_candidates:
        try:
            # Verificar cuáles ya existen para esta competicion+equipo → solo insertar nuevos
            pids_check = [r["player_id"] for r in roster_candidates]
            res = supabase.table("rosters") \
                .select("player_id, equipo_id") \
                .eq("competicion_id", COMPETICION_ID) \
                .in_("player_id", pids_check) \
                .execute()
            ya_registrados = {(row["player_id"], row["equipo_id"]) for row in (res.data or [])}
            nuevos_rosters = [
                r for r in roster_candidates
                if (r["player_id"], r["equipo_id"]) not in ya_registrados
            ]

            if nuevos_rosters:
                insertar_chunked(supabase, "rosters", nuevos_rosters)
                print(f"   ✅ rosters: {len(nuevos_rosters)} nuevos "
                      f"({len(ya_registrados)} ya existían).")
            else:
                print(f"   ℹ️  rosters: todos los jugadores ya registrados.")
        except Exception as e:
            print(f"   ❌ Error insertando rosters: {e}")

    # ── 7. Procesar ACCIONES (PBP)
    home_eid = next((k for k, v in equipo_map.items() if     v["isHome"]), None)
    away_eid = next((k for k, v in equipo_map.items() if not v["isHome"]), None)

    # Aplanar todos los eventos en orden cronológico para calcular métricas de TO
    period_data = pbp_j.get("data", {}).get("periodData", [])
    all_events_flat = []
    for period in sorted(period_data, key=lambda p: p.get("periodId", 0)):
        all_events_flat.extend(period.get("events", []))
    is_live_map, to_team_stats, to_player_stats = calcular_to_metrics(all_events_flat)

    acciones   = []
    action_num = 1
    ev_idx     = 0   # índice global en all_events_flat para consultar is_live_map
    for periodo in sorted(period_data, key=lambda p: p.get("periodId", 0)):
        events   = periodo.get("events", [])
        is_ot    = periodo.get("isOvertime", False)
        per_type = "OVERTIME" if is_ot else "REGULAR"

        for ev in events:
            eid     = ev.get("entityId", "")
            eq_info = equipo_map.get(eid, {})
            scores  = ev.get("scores", {}) or {}

            s1 = safe_int(scores.get(home_eid, 0))
            s2 = safe_int(scores.get(away_eid, 0))

            first_name, family_name = split_name(ev.get("name", ""))

            # player_id desde caché (poblado en paso 6)
            person_id_ev = ev.get("personId")
            player_id_a  = mapa_players.get(person_id_ev) if person_id_ev else None

            pbp_row = {
                "partido_id":      partido_id,
                "actionnumber":    action_num,
                "equipo_id":       equipo_ids.get(eid),
                "player_id":       player_id_a,
                "tno":             safe_int(eq_info.get("tno")),
                "pno":             None,
                "gt":              calcular_gt(ev.get("periodId", 1), ev.get("clock")),
                "clock":           clock_iso_to_mmss(ev.get("clock")),
                "s1":              s1,
                "s2":              s2,
                "lead":            s1 - s2,
                "period":          safe_int(ev.get("periodId", 1)),
                "periodtype":      per_type,
                "success":         safe_bool(ev.get("success")),
                "actiontype":      trunc(ev.get("eventType", ""), 50),
                "previousaction":  None,
                "qualifier":       None,
                "subtype":         trunc(ev.get("eventSubType", ""), 50),
                "scoring":         None,
                "shirtnumber":     safe_int(ev.get("bib")),
                "player":          trunc(ev.get("name", ""), 100),
                "firstname":       trunc(first_name, 50),
                "familyname":      trunc(family_name, 50),
                "is_live_ball_to": is_live_map.get(ev_idx),  # None si no es turnover
            }
            acciones.append(pbp_row)
            action_num += 1
            ev_idx     += 1

    if acciones:
        try:
            n = insertar_chunked(supabase, "acciones_partido", acciones, "partido_id,actionnumber")
            print(f"   ✅ acciones_partido: {n} filas insertadas.")
        except Exception as e:
            print(f"   ❌ Error insertando acciones_partido: {e}")

    # ── 7.5 Actualizar métricas TO en players_detalle y partidos_detalle
    for person_id, stats in to_player_stats.items():
        pid = mapa_players.get(person_id)
        if not pid:
            continue
        try:
            supabase.table("players_detalle") \
                .update({"live_ball_to": stats["live_to"], "dead_ball_to": stats["dead_to"]}) \
                .eq("partido_id", partido_id) \
                .eq("player_id", pid) \
                .execute()
        except Exception as e:
            print(f"   ⚠️ Error actualizando TO jugador {pid}: {e}")
    if to_player_stats:
        print(f"   ✅ players_detalle TO: {len(to_player_stats)} jugadores actualizadas.")

    for entity_id, stats in to_team_stats.items():
        eq_id = equipo_ids.get(entity_id)
        if not eq_id:
            continue
        try:
            supabase.table("partidos_detalle") \
                .update({
                    "live_ball_to":        stats["live_to"],
                    "dead_ball_to":        stats["dead_to"],
                    "pts_off_opp_live_to": stats["pts_off_opp_live_to"],
                }) \
                .eq("partido_id", partido_id) \
                .eq("equipo_id", eq_id) \
                .execute()
        except Exception as e:
            print(f"   ⚠️ Error actualizando TO equipo {eq_id}: {e}")
    if to_team_stats:
        print(f"   ✅ partidos_detalle TO: {len(to_team_stats)} equipos actualizados.")

    # ── 8. Procesar TIROS
    # tiros usa tiro_id (bigint serial) como PK — NO hay unique constraint en
    # (partido_id, actionnumber), así que upsert fallaría.
    # Estrategia idempotente: borrar tiros previos del partido → INSERT limpio.
    try:
        supabase.table("tiros").delete().eq("partido_id", partido_id).execute()
        print(f"   🗑️  Tiros previos eliminados (partido {partido_id}).")
    except Exception as e:
        print(f"   ⚠️ No se pudieron eliminar tiros previos: {e}")

    period_data_t = tiros_j.get("data", {}).get("periodData", [])
    shots = []
    for period in sorted(period_data_t, key=lambda p: p.get("periodId", 0)):
        shots.extend(period.get("shots", []))
    tiros         = []
    action_num_t  = 1
    for s in shots:
        eid     = s.get("entityId", "")
        eq_info = equipo_map.get(eid, {})

        person_id_s = s.get("personId")
        player_id_t = mapa_players.get(person_id_s) if person_id_s else None

        tiro_row = {
            "partido_id":     partido_id,
            "equipo_id":      equipo_ids.get(eid),
            "player_id":      player_id_t,
            "r":              1 if s.get("success") else 0,
            "x":              s.get("x"),
            "y":              s.get("y"),
            "p":              None,    # no disponible en nueva liga
            "pno":            None,
            "tno":            safe_int(eq_info.get("tno")),
            "per":            safe_int(s.get("periodId", 1)),
            "pertype":        "OVERTIME" if safe_int(s.get("periodId", 1)) > 4 else "REGULAR",
            "actiontype":     trunc(s.get("eventType", ""), 50),
            "actionnumber":   action_num_t,
            "previousaction": None,
            "subtype":        trunc(s.get("subType", ""), 50),
            "player":         trunc(s.get("name", ""), 100),
            "shirtnumber":    safe_int(s.get("bib")),
            "tiro_zona":      classify_shot(s.get("x", 0), s.get("y", 0)),
            "tiro_zona_beta": None,
        }
        tiros.append(tiro_row)
        action_num_t += 1

    if tiros:
        try:
            n = insertar_chunked(supabase, "tiros", tiros)   # INSERT simple — sin on_conflict
            print(f"   ✅ tiros: {n} filas insertadas.")
        except Exception as e:
            print(f"   ❌ Error insertando tiros: {e}")

    # ── 8.5. Procesar STINTS
    starters_dict = {
        j["personId"]: j["_entityId"]
        for j in jugadores_raw
        if safe_bool(j.get("starter")) and j.get("personId") and j.get("_entityId")
    }

    stints = calcular_stints(
        all_events_flat, equipo_ids, mapa_players, starters_dict, partido_id
    )

    if stints:
        try:
            seen = set()
            stints_dedup = []
            for s in stints:
                key = (s["partido_id"], s["player_id"], s["period"], s["clock_start"])
                if key not in seen:
                    seen.add(key)
                    stints_dedup.append(s)
            if len(stints_dedup) < len(stints):
                print(f"   ⚠️ {len(stints) - len(stints_dedup)} stints duplicados eliminados.")
            supabase.table("stints").delete().eq("partido_id", partido_id).execute()
            n = insertar_chunked(supabase, "stints", stints_dedup,
                                 on_conflict="partido_id,player_id,period,clock_start")
            print(f"   ✅ stints: {n} filas insertadas.")
        except Exception as e:
            print(f"   ❌ Error insertando stints: {e}")

    # ── 8.6. Registrar marcador por evento (pbp_scores)
    insertar_pbp_scores(supabase, partido_id, all_events_flat, equipo_ids)

    # ── 8.7. Calcular y registrar posesiones desde PBP
    _formula_poss = {}
    for _tm, _opp, _eid in [(tm1, tm2, home_id), (tm2, tm1, away_id)]:
        _eq_id = equipo_ids.get(_eid)
        if _eq_id:
            _formula_poss[_eq_id] = _calc_poss_formula(
                safe_int(_tm.get("tot_sfieldgoalsattempted")),
                safe_int(_tm.get("tot_sfieldgoalsmade")),
                safe_int(_tm.get("tot_sreboundsoffensive")),
                safe_int(_opp.get("tot_sreboundsdefensive")),
                safe_int(_tm.get("tot_sturnovers")),
                safe_int(_tm.get("tot_sfreethrowsattempted")),
            )
    _posesiones = calcular_posesiones(all_events_flat, equipo_ids, partido_id)
    insertar_posesiones(supabase, partido_id, _posesiones, _formula_poss)

    # ── Resumen del partido
    local  = equipo_map[home_id]["code"]
    visita = equipo_map[away_id]["code"]
    sl     = equipo_map[home_id]["score"]
    sv     = equipo_map[away_id]["score"]
    print(f"\n   🏆 {local} {sl} – {sv} {visita} | "
          f"{len(detalle_jugadores)}j | {len(acciones)} acc | {len(tiros)} tiros")
    return True

# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────

def obtener_partidos_pendientes(supabase):
    """
    Consulta la tabla 'partidos' para obtener los partidos que ya sucedieron.

    match_time_utc almacena la hora LOCAL del partido (sin conversión a UTC),
    por lo que se compara directamente contra la hora local de México.

    Retorna lista de dicts con partido_id y game_json_url, ordenados por fecha.
    """
    now_mx  = datetime.now(_TZ_MX)
    now_str = now_mx.strftime("%Y-%m-%dT%H:%M:%S")

    print(f"   Hora actual (Centro Mexico): {now_mx.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    try:
        res = supabase.table("partidos") \
            .select("partido_id, game_json_url, match_time_utc") \
            .eq("competicion_id", COMPETICION_ID) \
            .lte("match_time_utc", now_str) \
            .not_.is_("game_json_url", "null") \
            .is_("timestamp_ingestion", "null") \
            .order("match_time_utc") \
            .execute()

        return res.data or []
    except Exception as e:
        print(f"   Error consultando partidos pendientes: {e}")
        return []


def backfill_dnp_rosters(supabase):
    """
    Recorre todos los partidos procesados de la competición y agrega a `rosters`
    los jugadores que viajaron pero no jugaron (participated=False).
    Solo inserta registros nuevos; no toca los existentes.
    """
    print(f"\n🔁 BACKFILL DNP ROSTERS — competicion_id={COMPETICION_ID}")

    try:
        res = supabase.table("partidos") \
            .select("partido_id, game_json_url") \
            .eq("competicion_id", COMPETICION_ID) \
            .not_.is_("timestamp_ingestion", "null") \
            .not_.is_("game_json_url", "null") \
            .order("partido_id") \
            .execute()
        partidos = res.data or []
    except Exception as e:
        print(f"   ❌ Error obteniendo partidos: {e}")
        return

    print(f"   Partidos a procesar: {len(partidos)}\n")
    mapa_players = {}
    total_nuevos = 0

    for row in partidos:
        partido_id = row["partido_id"]
        box_url    = row["game_json_url"]
        print(f"   Partido {partido_id}...", end=" ")

        try:
            box = fetch_json(box_url, "Box Score")
            _, _, jugadores_raw, equipo_map, _, _ = parsear_box(box)
        except Exception as e:
            print(f"❌ Error descargando/parseando: {e}")
            continue

        try:
            entity_list  = list(equipo_map.keys())
            codes        = [equipo_map[e]["code"] for e in entity_list]
            res_eq = supabase.table("equipos") \
                .select("equipo_id, abreviatura") \
                .in_("abreviatura", codes) \
                .execute()
            code_to_dbid = {r["abreviatura"]: r["equipo_id"] for r in (res_eq.data or [])}
            equipo_ids   = {eid: code_to_dbid[equipo_map[eid]["code"]]
                            for eid in entity_list
                            if equipo_map[eid]["code"] in code_to_dbid}
        except Exception as e:
            print(f"❌ Error resolviendo equipos: {e}")
            continue

        candidates = []
        for j in jugadores_raw:
            person_id    = j.get("personId", "")
            person_name  = j.get("personName", "")
            participated = j.get("participated", True)
            eid          = j.get("_entityId", "")

            if participated or not person_id:  # solo DNP
                continue

            first_name, family_name = split_name(person_name)
            pid   = get_or_create_player(supabase, person_id, first_name, family_name, mapa_players)
            eq_id = equipo_ids.get(eid)
            if not pid or not eq_id:
                continue

            candidates.append({
                "player_id":            pid,
                "equipo_id":            eq_id,
                "competicion_id":       COMPETICION_ID,
                "shirt_number":         safe_int(j.get("bib")),
                "effective_start_date": ROSTER_START_DATE,
            })

        if not candidates:
            print("sin DNP.")
            continue

        try:
            pids_check = [c["player_id"] for c in candidates]
            res_exist = supabase.table("rosters") \
                .select("player_id") \
                .eq("competicion_id", COMPETICION_ID) \
                .in_("player_id", pids_check) \
                .execute()
            ya_registrados = {r["player_id"] for r in (res_exist.data or [])}
            nuevos = [c for c in candidates if c["player_id"] not in ya_registrados]

            if nuevos:
                insertar_chunked(supabase, "rosters", nuevos)
                total_nuevos += len(nuevos)
                print(f"{len(nuevos)} DNP nuevos en rosters.")
            else:
                print("DNP ya registrados.")
        except Exception as e:
            print(f"❌ Error insertando rosters: {e}")

    print(f"\n✅ BACKFILL DNP ROSTERS COMPLETADO — {total_nuevos} nuevos jugadores agregados.")


def backfill_dnp_players_detalle(supabase):
    """
    Recorre todos los partidos procesados y agrega a `players_detalle` los jugadores
    que viajaron pero no jugaron (participated=False), con stats en cero.
    Solo inserta registros nuevos (no sobreescribe existentes).
    """
    print(f"\n🔁 BACKFILL DNP PLAYERS_DETALLE — competicion_id={COMPETICION_ID}")

    try:
        res = supabase.table("partidos") \
            .select("partido_id, game_json_url") \
            .eq("competicion_id", COMPETICION_ID) \
            .not_.is_("timestamp_ingestion", "null") \
            .not_.is_("game_json_url", "null") \
            .order("partido_id") \
            .execute()
        partidos = res.data or []
    except Exception as e:
        print(f"   ❌ Error obteniendo partidos: {e}")
        return

    print(f"   Partidos a procesar: {len(partidos)}\n")
    mapa_players = {}
    total_nuevos = 0

    for row in partidos:
        partido_id = row["partido_id"]
        box_url    = row["game_json_url"]
        print(f"   Partido {partido_id}...", end=" ")

        try:
            box = fetch_json(box_url, "Box Score")
            _, _, jugadores_raw, _, _, _ = parsear_box(box)
        except Exception as e:
            print(f"❌ Error descargando/parseando: {e}")
            continue

        # Jugadores ya registrados en players_detalle para este partido
        try:
            res_exist = supabase.table("players_detalle") \
                .select("player_id") \
                .eq("partido_id", partido_id) \
                .execute()
            ya_registrados = {r["player_id"] for r in (res_exist.data or [])}
        except Exception as e:
            print(f"❌ Error consultando players_detalle: {e}")
            continue

        nuevos = []
        for j in jugadores_raw:
            person_id    = j.get("personId", "")
            person_name  = j.get("personName", "")
            participated = j.get("participated", True)

            if participated or not person_id:  # solo DNP
                continue

            first_name, family_name = split_name(person_name)
            pid = get_or_create_player(supabase, person_id, first_name, family_name, mapa_players)
            if not pid or pid in ya_registrados:
                continue

            nuevos.append({
                "player_id":               pid,
                "partido_id":              partido_id,
                "active":                  False,
                "starter":                 False,
                "captain":                 False,
                "sminutes":                0,
                "spoints":                 0,
                "splusminuspoints":        None,
                "sfieldgoalsmade":         0,
                "sfieldgoalsattempted":    0,
                "stwopointersmade":        0,
                "stwopointersattempted":   0,
                "sthreepointersmade":      0,
                "sthreepointersattempted": 0,
                "sfreethrowsmade":         0,
                "sfreethrowsattempted":    0,
                "sreboundsoffensive":      0,
                "sreboundsdefensive":      0,
                "sreboundstotal":          0,
                "sassists":                0,
                "sturnovers":              0,
                "ssteals":                 0,
                "sblocks":                 0,
                "sblocksreceived":         0,
                "sfoulspersonal":          0,
                "sfoulson":                0,
                "spointsinthepaint":       0,
                "spointssecondchance":     0,
                "spointsfastbreak":        0,
            })

        if not nuevos:
            print("sin DNP nuevos.")
            continue

        try:
            insertar_chunked(supabase, "players_detalle", nuevos, "player_id,partido_id")
            total_nuevos += len(nuevos)
            print(f"{len(nuevos)} DNP agregados.")
        except Exception as e:
            print(f"❌ Error insertando: {e}")

    print(f"\n✅ BACKFILL DNP PLAYERS_DETALLE COMPLETADO — {total_nuevos} filas agregadas.")


def main():
    if not URL or not KEY:
        print("Error: define SUPABASE_URL y SUPABASE_KEY como variables de entorno.")
        return

    # ── Modo backfill: actualiza tiro_zona para tiros ya guardados
    if BACKFILL_TIRO_ZONA_IDS:
        print(f"🔁 MODO BACKFILL TIRO_ZONA — {len(BACKFILL_TIRO_ZONA_IDS)} partido(s): {BACKFILL_TIRO_ZONA_IDS}")
        try:
            supabase = create_client(URL, KEY)
        except Exception as e:
            print(f"Error de conexion Supabase: {e}")
            return
        for pid in BACKFILL_TIRO_ZONA_IDS:
            print(f"\n  Partido {pid}...")
            try:
                rows = supabase.table("tiros").select("tiro_id,x,y").eq("partido_id", pid).execute().data
                updates = [{"tiro_id": r["tiro_id"], "tiro_zona": classify_shot(r["x"] or 0, r["y"] or 0)} for r in rows]
                for u in updates:
                    supabase.table("tiros").update({"tiro_zona": u["tiro_zona"]}).eq("tiro_id", u["tiro_id"]).execute()
                print(f"  ✅ {len(updates)} tiros actualizados.")
            except Exception as e:
                print(f"  ❌ Error en partido {pid}: {e}")
        print("\n✅ BACKFILL TIRO_ZONA COMPLETADO")
        return

    # ── Modo backfill: agrega DNP a players_detalle
    if BACKFILL_DNP_PLAYERS_DETALLE:
        try:
            supabase = create_client(URL, KEY)
        except Exception as e:
            print(f"Error de conexion Supabase: {e}")
            return
        backfill_dnp_players_detalle(supabase)
        return

    # ── Modo backfill: agrega DNP a rosters
    if BACKFILL_DNP_ROSTERS:
        try:
            supabase = create_client(URL, KEY)
        except Exception as e:
            print(f"Error de conexion Supabase: {e}")
            return
        backfill_dnp_rosters(supabase)
        return

    # ── Modo backfill: recalcula stints para partidos ya procesados
    if BACKFILL_STINTS_IDS or BACKFILL_STINTS_TODOS:
        try:
            supabase = create_client(URL, KEY)
        except Exception as e:
            print(f"Error de conexion Supabase: {e}")
            return
        if BACKFILL_STINTS_TODOS:
            res = (supabase.table("partidos")
                   .select("partido_id, game_json_url")
                   .eq("competicion_id", COMPETICION_ID)
                   .order("partido_id")
                   .execute())
            ids = [r["partido_id"] for r in (res.data or []) if r.get("game_json_url")]
            print(f"🔁 MODO BACKFILL STINTS (todos) — {len(ids)} partido(s): {ids}")
        else:
            ids = BACKFILL_STINTS_IDS
            print(f"🔁 MODO BACKFILL STINTS — {len(ids)} partido(s): {ids}")
        for pid in ids:
            backfill_stints(supabase, pid)
        print("\n✅ BACKFILL STINTS COMPLETADO")
        return

    # ── Modo backfill: recalcula posesiones para partidos ya procesados
    if BACKFILL_POSESIONES_IDS or BACKFILL_POSESIONES_TODOS:
        try:
            supabase = create_client(URL, KEY)
        except Exception as e:
            print(f"Error de conexion Supabase: {e}")
            return
        if BACKFILL_POSESIONES_TODOS:
            res = (supabase.table("partidos")
                   .select("partido_id, game_json_url")
                   .eq("competicion_id", COMPETICION_ID)
                   .order("partido_id")
                   .execute())
            ids = [r["partido_id"] for r in (res.data or []) if r.get("game_json_url")]
            print(f"🔁 MODO BACKFILL POSESIONES (todos) — {len(ids)} partido(s): {ids}")
        else:
            ids = BACKFILL_POSESIONES_IDS
            print(f"🔁 MODO BACKFILL POSESIONES — {len(ids)} partido(s): {ids}")
        for pid in ids:
            backfill_posesiones(supabase, pid)
        print("\n✅ BACKFILL POSESIONES COMPLETADO")
        return

    if BACKFILL_PBP_SCORES_IDS:
        print(f"🔁 MODO BACKFILL PBP_SCORES — {len(BACKFILL_PBP_SCORES_IDS)} partido(s): {BACKFILL_PBP_SCORES_IDS}")
        try:
            supabase = create_client(URL, KEY)
        except Exception as e:
            print(f"Error de conexion Supabase: {e}")
            return
        for pid in BACKFILL_PBP_SCORES_IDS:
            backfill_pbp_scores(supabase, pid)
        print("\n✅ BACKFILL PBP_SCORES COMPLETADO")
        return

    if BACKFILL_ACCIONES_IDS:
        print(f"🔁 MODO BACKFILL ACCIONES_PARTIDO — {len(BACKFILL_ACCIONES_IDS)} partido(s): {BACKFILL_ACCIONES_IDS}")
        try:
            supabase = create_client(URL, KEY)
        except Exception as e:
            print(f"Error de conexion Supabase: {e}")
            return
        for pid in BACKFILL_ACCIONES_IDS:
            backfill_acciones(supabase, pid)
        print("\n✅ BACKFILL ACCIONES_PARTIDO COMPLETADO")
        return

    if BACKFILL_TIROS_IDS:
        print(f"🔁 MODO BACKFILL TIROS — {len(BACKFILL_TIROS_IDS)} partido(s): {BACKFILL_TIROS_IDS}")
        try:
            supabase = create_client(URL, KEY)
        except Exception as e:
            print(f"Error de conexion Supabase: {e}")
            return
        for pid in BACKFILL_TIROS_IDS:
            backfill_tiros(supabase, pid)
        print("\n✅ BACKFILL TIROS COMPLETADO")
        return

    # ── Modo backfill: recalcula partidos_detalle (fecha, FGA, métricas avanzadas)
    if BACKFILL_PARTIDOS_IDS:
        print(f"🔁 MODO BACKFILL PARTIDOS_DETALLE — {len(BACKFILL_PARTIDOS_IDS)} partido(s): {BACKFILL_PARTIDOS_IDS}")
        try:
            supabase = create_client(URL, KEY)
        except Exception as e:
            print(f"Error de conexion Supabase: {e}")
            return
        for pid in BACKFILL_PARTIDOS_IDS:
            backfill_partidos_detalle(supabase, pid)
        print("\n✅ BACKFILL PARTIDOS_DETALLE COMPLETADO")
        return

    # ── Modo backfill: recalcula métricas TO para partidos ya procesados
    if BACKFILL_PARTIDO_IDS:
        print(f"🔁 MODO BACKFILL — {len(BACKFILL_PARTIDO_IDS)} partido(s): {BACKFILL_PARTIDO_IDS}")
        try:
            supabase = create_client(URL, KEY)
        except Exception as e:
            print(f"Error de conexion Supabase: {e}")
            return
        for pid in BACKFILL_PARTIDO_IDS:
            backfill_to_metrics(supabase, pid)
        print("\n✅ BACKFILL COMPLETADO")
        return

    print("INICIANDO INGESTA NUEVA LIGA -> SUPABASE")
    print(f"   competicion_id : {COMPETICION_ID}")
    print(f"   temporada_id   : {TEMPORADA_ID}")

    try:
        supabase = create_client(URL, KEY)
    except Exception as e:
        print(f"Error de conexion Supabase: {e}")
        return

    # Obtener partidos a procesar desde la BD
    partidos_db = obtener_partidos_pendientes(supabase)
    if not partidos_db:
        print("No hay partidos por procesar (ninguno ha concluido aun o no hay URLs disponibles).")
        return

    print(f"   Partidos a procesar: {len(partidos_db)}\n")
    for p in partidos_db:
        print(f"   partido_id={p['partido_id']} | {p['match_time_utc']}")
    print()

    # Catálogo de equipos (igual que LDM_Partidos.py)
    team_utils.reset_log()
    mapa_n, mapa_c, equipos_raw, mapa_n_comp, mapa_c_comp, codigos_dup = \
        team_utils.cargar_mapa_equipos(supabase)

    if not mapa_n and not mapa_c:
        print("Catalogo de equipos vacio. Agrega los equipos a la tabla 'equipos'.")
        return

    # Caché de jugadores: person_id_ext → player_id
    mapa_players = {}

    procesados = 0
    fallidos   = 0

    for row in partidos_db:
        partido_id = row["partido_id"]
        box_url    = row["game_json_url"]
        try:
            ok = procesar_partido(
                supabase, box_url, partido_id,
                mapa_n, mapa_c, equipos_raw, mapa_n_comp, mapa_c_comp, codigos_dup,
                mapa_players,
            )
            if ok: procesados += 1
            else:  fallidos   += 1
        except Exception as e:
            print(f"   Error inesperado en partido {partido_id}: {e}")
            import traceback; traceback.print_exc()
            fallidos += 1

    print(f"\n{'='*60}")
    print(f"✅ INGESTA COMPLETADA")
    print(f"   Procesados: {procesados} | Fallidos: {fallidos}")
    print(f"{'='*60}")

    # ── 9. Enriquecimiento biográfico (altura, peso, nacionalidad)
    if mapa_players:
        enriquecer_bio_jugadores(supabase, mapa_players)

    # Equipos no encontrados (resumen final, igual que LDM_Main)
    no_encontrados = team_utils.get_equipos_no_encontrados()
    if no_encontrados:
        print(f"\n⚠️ EQUIPOS NO ENCONTRADOS ({len(no_encontrados)}):")
        for nombre, codigo in sorted(no_encontrados):
            print(f"   - Nombre: '{nombre}' | Código: '{codigo}'")
        print("   → Agrégalos a la tabla 'equipos' en Supabase y re-ejecuta.")
    else:
        print("\n✅ Todos los equipos fueron encontrados en el catálogo.")


if __name__ == "__main__":
    main()
