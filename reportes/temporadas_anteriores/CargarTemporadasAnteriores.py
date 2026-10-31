"""
Ingesta de temporadas anteriores (LNBP 2022-2025) usando NuevaLiga_DB.py sin modificarlo.

Requisito: la tabla `partidos` ya tiene los juegos (partidos_2022_2025.csv) con
timestamp_ingestion en null. Este script solo procesa los pendientes de cada temporada,
así que se puede volver a correr: retoma donde se quedó.

Uso:
    python CargarTemporadasAnteriores.py                 # las 4 temporadas
    python CargarTemporadasAnteriores.py 5               # solo temporada_id 5 (LNBP 2025)
    python CargarTemporadasAnteriores.py 5 --max 3       # prueba con 3 partidos
    python CargarTemporadasAnteriores.py 5 --minutos 340 # se detiene entre partidos al pasar 340 min
"""
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POSTGAME = os.path.normpath(os.path.join(BASE_DIR, "..", "postgame"))
sys.path.insert(0, POSTGAME)
import NuevaLiga_DB as NL
from NuevaLiga_DB import team_utils
from supabase import create_client

# ==============================================================================
# --- CONFIGURACIÓN ---
# ==============================================================================

# temporada_id -> (competicion_id, seasonId Sportradar)
TEMPORADAS = {
    2: (2, "520799a0-01b3-11ed-82e5-2109564f649b"),   # LNBP 2022
    3: (4, "81b74ea4-3936-11ee-b192-f12da13c8dc7"),   # LNBP 2023
    4: (5, "eb6a1d5b-24fd-11ef-86df-c1d9b327161d"),   # LNBP 2024
    5: (6, "b1b57094-3f54-11f0-9a4e-9fb16b8df604"),   # LNBP 2025
}

# Etapa por rango de fechas, por competicion_id (1 regular, 2 play-in, 3 semis/cuartos,
# 4 finales de zona/semis, 5 gran final). 2023 no tuvo play-in.
NL.ETAPAS_POR_COMPETICION.update({
    2: [("2022-07-21", "2022-09-24", "1"), ("2022-09-25", "2022-10-08", "3"),
        ("2022-10-09", "2022-10-22", "4"), ("2022-10-23", "2022-10-28", "5")],
    4: [("2023-08-18", "2023-11-08", "1"), ("2023-11-09", "2023-11-22", "3"),
        ("2023-11-23", "2023-12-02", "4"), ("2023-12-03", "2023-12-14", "5")],
    5: [("2024-07-11", "2024-10-18", "1"), ("2024-10-19", "2024-10-24", "2"),
        ("2024-10-25", "2024-11-05", "3"), ("2024-11-06", "2024-11-27", "4"),
        ("2024-11-28", "2024-12-05", "5")],
    6: [("2025-07-03", "2025-10-01", "1"), ("2025-10-02", "2025-10-08", "2"),
        ("2025-10-09", "2025-10-19", "3"), ("2025-10-20", "2025-11-02", "4"),
        ("2025-11-03", "2025-11-10", "5")],
})

# Dos juegos de 2022 que el detalle marca FINISHED en vez de CONFIRMED
NL.FORCE_PARTIDO_IDS = [326, 372]

# FRE lo usan Plateros (id 17, 2022-2024) y Gambusinos (id 9, 2025): se resuelve por temporada.
EQUIPO_FRE = {2: 17, 3: 17, 4: 17, 5: 9}

# ==============================================================================
# --- EJECUCIÓN ---
# ==============================================================================

# Con %run en la misma consola el script se ejecuta más de una vez: guardamos la función
# original una sola vez para no envolver el wrapper dentro de sí mismo.
_buscar_original = getattr(team_utils, "_buscar_id_equipo_original", team_utils.buscar_id_equipo)
team_utils._buscar_id_equipo_original = _buscar_original


def _buscar_con_fre(nombre_json, codigo_json, *args, **kwargs):
    if (codigo_json or "").strip().upper() == "FRE":
        return EQUIPO_FRE[NL.TEMPORADA_ID], "fre_temporada"
    return _buscar_original(nombre_json, codigo_json, *args, **kwargs)


team_utils.buscar_id_equipo = _buscar_con_fre


def _fetch_con_reintentos(url, descripcion=""):
    """La API da timeouts ocasionales: 3 intentos con 45 s cada uno antes de rendirse."""
    print(f"   🌐 Descargando {descripcion}...")
    for intento in range(1, 4):
        try:
            resp = NL.requests.get(url, timeout=45)
            resp.raise_for_status()
            print(f"      ✅ OK ({resp.status_code})")
            return resp.json()
        except Exception as e:
            print(f"      ❌ Intento {intento}/3: {e}")
            if intento == 3:
                raise
            time.sleep(2 * intento)


NL.fetch_json = _fetch_con_reintentos


LIMITE = {"fin": None}   # momento (time.time) a partir del cual no se empiezan partidos nuevos


def _se_acabo_el_tiempo():
    return LIMITE["fin"] is not None and time.time() >= LIMITE["fin"]


def cargar_temporada(supabase, temporada_id, max_partidos):
    comp, season = TEMPORADAS[temporada_id]
    NL.COMPETICION_ID = comp
    NL.TEMPORADA_ID = temporada_id
    NL.SEASON_ID = season
    inicio = supabase.table("temporadas").select("fecha_inicio").eq("temporada_id", temporada_id).execute().data[0]["fecha_inicio"]
    NL.ROSTER_START_DATE = inicio

    print(f"\n{'#'*60}\n# temporada_id={temporada_id} | competicion_id={comp} | inicio={inicio}\n{'#'*60}")
    pendientes = NL.obtener_partidos_pendientes(supabase)
    if max_partidos:
        pendientes = pendientes[:max_partidos]
    print(f"   Partidos a procesar: {len(pendientes)}")
    if not pendientes:
        return 0, 0

    team_utils.reset_log()
    mapa_n, mapa_c, equipos_raw, mapa_n_comp, mapa_c_comp, codigos_dup = team_utils.cargar_mapa_equipos(supabase)
    mapa_players = {}
    ok = fallidos = 0
    for row in pendientes:
        if _se_acabo_el_tiempo():
            print("   ⏱️ Límite de tiempo alcanzado: se detiene entre partidos. Vuelve a correrlo para continuar.")
            break
        try:
            if NL.procesar_partido(supabase, row["game_json_url"], row["partido_id"],
                                   mapa_n, mapa_c, equipos_raw, mapa_n_comp, mapa_c_comp, codigos_dup,
                                   mapa_players):
                ok += 1
            else:
                fallidos += 1
        except Exception as e:
            print(f"   Error inesperado en partido {row['partido_id']}: {e}")
            import traceback; traceback.print_exc()
            fallidos += 1

    print(f"\n   temporada {temporada_id}: procesados {ok} | fallidos {fallidos}")
    if mapa_players:
        NL.enriquecer_bio_jugadores(supabase, mapa_players)
    sin_equipo = team_utils.get_equipos_no_encontrados()
    if sin_equipo:
        print(f"   ⚠️ Equipos no encontrados: {sorted(sin_equipo)}")
    return ok, fallidos


if __name__ == "__main__":
    args = sys.argv[1:]
    max_partidos = None
    if "--max" in args:
        i = args.index("--max")
        max_partidos = int(args[i + 1])
        del args[i:i + 2]
    if "--minutos" in args:
        i = args.index("--minutos")
        LIMITE["fin"] = time.time() + float(args[i + 1]) * 60
        del args[i:i + 2]
    temporadas = [int(a) for a in args] or list(TEMPORADAS)

    supabase = create_client(NL.URL, NL.KEY)
    total_ok = total_fail = 0
    for t in temporadas:
        ok, fail = cargar_temporada(supabase, t, max_partidos)
        total_ok += ok
        total_fail += fail
    print(f"\n{'='*60}\n✅ TOTAL: procesados {total_ok} | fallidos {total_fail}\n{'='*60}")
