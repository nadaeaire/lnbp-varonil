# cron/team_utils.py
# Módulo centralizado para resolución de equipos.
# Todos los scripts del cron (Partidos, Players, PBP, Tiros) usan esto.

import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher

# --- NORMALIZACIÓN ---

def normalizar(texto):
    """Normaliza un nombre para comparación: quita acentos, upper, colapsa espacios."""
    if not texto:
        return ""
    # Quitar acentos (NFD → quitar diacríticos → NFC)
    nfkd = unicodedata.normalize('NFKD', str(texto))
    sin_acentos = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(sin_acentos.upper().split())

# --- CARGA DEL CATÁLOGO ---

def cargar_mapa_equipos(supabase_client):
    """Carga el catálogo de equipos y construye mapas de búsqueda normalizados.

    Retorna: (mapa_nombre, mapa_codigo, equipos_raw, mapa_nombre_comp, mapa_codigo_comp, codigos_duplicados_comp)
      - mapa_nombre:              {NOMBRE_NORMALIZADO: equipo_id}  (global, last-write-wins)
      - mapa_codigo:              {CODIGO_NORMALIZADO: equipo_id}  (global, last-write-wins)
      - equipos_raw:              lista original de dicts (para fuzzy matching)
      - mapa_nombre_comp:         {(NOMBRE_NORMALIZADO, competicion_id): equipo_id}
      - mapa_codigo_comp:         {(CODIGO_NORMALIZADO, competicion_id): equipo_id}
      - codigos_duplicados_comp:  {(CODIGO_NORMALIZADO, competicion_id)} códigos ambiguos
    """
    print("📚 Cargando catálogo de equipos...")
    try:
        res = supabase_client.table("equipos").select("equipo_id, nombre, abreviatura, competicion_id").execute()
        equipos = res.data if hasattr(res, 'data') else res
    except Exception as e:
        print(f"❌ Error cargando equipos: {e}")
        return {}, {}, [], {}, {}, set()

    mapa_nombre = {}
    mapa_codigo = {}
    mapa_nombre_comp = {}
    mapa_codigo_comp = {}

    for eq in equipos:
        n = eq.get('nombre', '').strip()
        c = eq.get('abreviatura', '').strip()
        eid = eq.get('equipo_id')
        comp = eq.get('competicion_id')

        n_norm = normalizar(n) if n else ''
        c_norm = normalizar(c) if c else ''

        if n_norm:
            mapa_nombre[n_norm] = eid
            if comp:
                mapa_nombre_comp[(n_norm, comp)] = eid
        if c_norm:
            mapa_codigo[c_norm] = eid
            if comp:
                mapa_codigo_comp[(c_norm, comp)] = eid

    # Detectar códigos duplicados dentro de la misma competición
    # (ej: UANE y UANL ambos con código "UAN" en comp 42034).
    # Cuando hay colisión, eliminamos la entrada del mapa para forzar
    # que se resuelva por nombre en vez de código.
    _code_comp_count = {}
    codigos_duplicados_comp = set()
    for eq in equipos:
        c = eq.get('abreviatura', '').strip()
        comp = eq.get('competicion_id')
        if c and comp:
            key = (normalizar(c), comp)
            _code_comp_count[key] = _code_comp_count.get(key, 0) + 1
    for key, count in _code_comp_count.items():
        if count > 1:
            mapa_codigo_comp.pop(key, None)
            codigos_duplicados_comp.add(key)
            print(f"   ⚠️ Código '{key[0]}' duplicado en competición {key[1]}, se resolverá por nombre.")

    print(f"   -> {len(equipos)} equipos cargados.")
    return mapa_nombre, mapa_codigo, equipos, mapa_nombre_comp, mapa_codigo_comp, codigos_duplicados_comp

# --- BÚSQUEDA DE EQUIPO ---

# Umbral mínimo de similitud para fuzzy match (0-1). 0.75 = 75% de caracteres coinciden.
FUZZY_THRESHOLD = 0.75

def buscar_id_equipo(nombre_json, codigo_json, mapa_nombre, mapa_codigo, equipos_raw=None,
                      competicion_id=None, mapa_nombre_comp=None, mapa_codigo_comp=None,
                      codigos_duplicados_comp=None):
    """Busca un equipo en el catálogo con fallback por niveles.

    Cuando se proporciona competicion_id, intenta primero una búsqueda
    específica por competición para evitar colisiones entre equipos
    femenil y varonil que comparten nombre o código.

    Niveles de búsqueda:
      1a. Match exacto por código + competición
      1b. Match exacto por código (global) — se salta si el código es
          duplicado dentro de la competición, para forzar resolución
          por nombre.
      2a. Match exacto por nombre + competición
      2b. Match exacto por nombre (global)
      3.  Fuzzy match (filtrado por competición si está disponible)

    Retorna: (equipo_id, metodo)
    """
    # 1) Código exacto
    if codigo_json:
        cod_norm = normalizar(codigo_json)
        # Intentar primero con competición específica
        if competicion_id and mapa_codigo_comp:
            found = mapa_codigo_comp.get((cod_norm, competicion_id))
            if found:
                return found, "codigo_comp"
        # Fallback global — solo si el código NO es duplicado en esta competición.
        # Si es duplicado, el mapa global apunta a un solo equipo (last-write-wins)
        # y ambos equipos resolverían al mismo ID erróneamente.
        es_duplicado = (codigos_duplicados_comp
                        and competicion_id
                        and (cod_norm, competicion_id) in codigos_duplicados_comp)
        if not es_duplicado:
            found = mapa_codigo.get(cod_norm)
            if found:
                return found, "codigo"

    # 2) Nombre exacto
    if nombre_json:
        nom_norm = normalizar(nombre_json)
        # Intentar primero con competición específica
        if competicion_id and mapa_nombre_comp:
            found = mapa_nombre_comp.get((nom_norm, competicion_id))
            if found:
                return found, "nombre_comp"
        # Fallback global
        found = mapa_nombre.get(nom_norm)
        if found:
            return found, "nombre"

    # 3) Fuzzy match sobre nombres del catálogo
    if nombre_json and equipos_raw:
        nom_norm = normalizar(nombre_json)

        # Filtrar candidatos por competición si está disponible
        candidates = equipos_raw
        if competicion_id:
            filtered = [eq for eq in equipos_raw if eq.get('competicion_id') == competicion_id]
            if filtered:
                candidates = filtered

        mejor_score = 0
        mejor_id = None
        mejor_nombre_cat = ""

        for eq in candidates:
            cat_nombre = normalizar(eq.get('nombre', ''))
            if not cat_nombre:
                continue
            score = SequenceMatcher(None, nom_norm, cat_nombre).ratio()
            if score > mejor_score:
                mejor_score = score
                mejor_id = eq.get('equipo_id')
                mejor_nombre_cat = eq.get('nombre', '')

        if mejor_score >= FUZZY_THRESHOLD and mejor_id:
            print(f"   🔍 Fuzzy match: '{nombre_json}' → '{mejor_nombre_cat}' (score={mejor_score:.2f})")
            return mejor_id, "fuzzy"

    # No encontrado
    return None, None

# --- LOG DE EQUIPOS NO ENCONTRADOS ---

# Acumulador global para evitar imprimir el mismo warning 100 veces
_equipos_no_encontrados = set()

def log_equipo_no_encontrado(nombre_json, codigo_json, match_id, contexto=""):
    """Loguea un equipo que no pudo ser resuelto. Solo imprime una vez por combinación."""
    key = (nombre_json, codigo_json)
    if key not in _equipos_no_encontrados:
        _equipos_no_encontrados.add(key)
        print(f"   ⚠️ EQUIPO NO ENCONTRADO en catálogo:")
        print(f"      Nombre JSON: '{nombre_json}'")
        print(f"      Código JSON: '{codigo_json}'")
        print(f"      Partido: {match_id} | Contexto: {contexto}")
        print(f"      → Revisa la tabla 'equipos' en Supabase y agrega este equipo.")

def reset_log():
    """Limpia el acumulador (útil entre ejecuciones)."""
    _equipos_no_encontrados.clear()

def get_equipos_no_encontrados():
    """Retorna el set de equipos que no fueron encontrados."""
    return _equipos_no_encontrados.copy()

# --- LECTURA DE PARTIDOS DESDE DB ---

COMPETICIONES_VALIDAS = {42033, 42034}

def cargar_partidos_desde_db(supabase_client):
    """Lee la tabla 'partidos' y retorna registros con las mismas claves
    que usaban los scripts cuando leían de Google Sheets.

    Solo retorna partidos cuya fecha (match_time_utc) ya pasó,
    evitando llamadas innecesarias a la API para partidos futuros.

    Retorna lista de dicts con claves:
      matchId, game_url, competitionId, matchTimeUTC, game_boxscore
    """
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z")
    all_rows = []
    page_size = 1000
    offset = 0
    while True:
        res = supabase_client.table("partidos") \
            .select("partido_id, competicion_id, match_time_utc, game_json_url, game_boxscore_url") \
            .in_("competicion_id", list(COMPETICIONES_VALIDAS)) \
            .lte("match_time_utc", now_utc) \
            .range(offset, offset + page_size - 1) \
            .execute()
        data = res.data if hasattr(res, 'data') else res
        if not data:
            break
        all_rows.extend(data)
        if len(data) < page_size:
            break
        offset += page_size

    records = []
    for r in all_rows:
        records.append({
            'matchId': r['partido_id'],
            'game_url': r.get('game_json_url', ''),
            'competitionId': r['competicion_id'],
            'matchTimeUTC': r.get('match_time_utc', ''),
            'game_boxscore': r.get('game_boxscore_url', ''),
        })
    return records
