# modules/data_loader.py
import streamlit as st
import pandas as pd
import numpy as np
from supabase import create_client, Client
from datetime import datetime

# --- UTILIDAD INTERNA ---
def vectorizar_minutos(series):
    """Convierte minutos formato texto/float a float decimal."""
    mask_is_float = ~series.astype(str).str.contains(':')
    result_minutes = pd.Series(0.0, index=series.index)
    result_minutes.loc[mask_is_float] = pd.to_numeric(series.loc[mask_is_float], errors='coerce').fillna(0.0)
    m_s_part = series.loc[~mask_is_float].astype(str).str.split(':').str[:2].str.join(':')
    try:
        duration = pd.to_timedelta('00:' + m_s_part)
        result_minutes.loc[~mask_is_float] = duration.dt.total_seconds() / 60.0
    except:
        result_minutes.loc[~mask_is_float] = 0.0
    return result_minutes.fillna(0.0)

def _fetch_all_rows(table_name, select_cols="*", page_size=1000, max_pages=200):
    """Descarga TODAS las filas de una tabla paginando en bloques.

    page_size=1000 coincide con el max_rows por defecto de Supabase/PostgREST.
    Usar un page_size mayor al max_rows del servidor provoca que la paginación
    se detenga prematuramente (el servidor devuelve menos filas que page_size
    y el loop lo interpreta como la última página).
    """
    supabase = get_supabase_client()
    all_data = []
    offset = 0
    pages_fetched = 0
    prev_first_id = None
    while pages_fetched < max_pages:
        response = (
            supabase.table(table_name)
            .select(select_cols)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        if not response.data:
            break

        current_first_id = str(response.data[0]) if response.data else None
        if current_first_id is not None and current_first_id == prev_first_id:
            break
        prev_first_id = current_first_id

        fetched = len(response.data)
        all_data.extend(response.data)
        if fetched < page_size:
            break
        offset += fetched
        pages_fetched += 1
    return all_data

# --- CONEXIÓN SUPABASE ---
@st.cache_resource
def get_supabase_client() -> Client:
    try:
        url = st.secrets["supabase_config"]["url"]
        key = st.secrets["supabase_config"]["anon_key"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"Error Supabase Client: {e}")
        st.stop()

# --- Columnas específicas por vista (evitar SELECT *) ---
# OPTIMIZACIÓN: solo traer las columnas que realmente usan las vistas.
# Eliminadas: firstName, familyName (se usa Nombre), competition_id (se usa Categoria),
# Opp_POSS_DB (no se usa en ninguna vista).
_COLS_ANALITICA = ",".join([
    # Identificadores
    "id_player", "Nombre", "id_abe", "competition_id", "Fecha", "Categoria", "equipo_nombre",
    # Stats individuales del jugador
    "sMinutes", "sPoints", "starter",
    "sFieldGoalsMade", "sFieldGoalsAttempted",
    "sTwoPointersMade", "sTwoPointersAttempted",
    "sThreePointersMade", "sThreePointersAttempted",
    "sFreeThrowsMade", "sFreeThrowsAttempted",
    "sReboundsOffensive", "sReboundsDefensive", "sReboundsTotal",
    "sAssists", "sTurnovers", "sSteals", "sBlocks", "sFoulsPersonal", "sFoulsOn",
    # Totales de equipo (Tm_)
    "Tm_Score", "Tm_MIN", "Tm_FG", "Tm_FGA", "Tm_3PM", "Tm_3PA", "Tm_2PM",
    "Tm_FTM", "Tm_FTA", "Tm_ORB", "Tm_DRB", "Tm_TRB",
    "Tm_AST", "Tm_TOV", "Tm_STL", "Tm_BLK", "Tm_PF",
    # Totales del rival (Opp_)
    "Opp_Name", "Opp_Score", "Opp_MIN",
    "Opp_FG", "Opp_FGA", "Opp_3PM", "Opp_3PA",
    "Opp_FTM", "Opp_FTA", "Opp_ORB", "Opp_DRB", "Opp_TRB",
    "Opp_TOV", "Opp_PF",
])

# vista_equipos_master — columnas usadas por equipos_smry, equipos_4f y equipos_avg.
_COLS_EQUIPOS = ",".join([
    "id_abe", "competition_id", "equipo_nombre", "Fecha", "Categoria",
    "Tm_Score", "Tm_FG", "Tm_FGA", "Tm_3PM", "Tm_3PA", "Tm_2PM",
    "Tm_FTM", "Tm_FTA", "Tm_ORB", "Tm_DRB", "Tm_TRB",
    "Tm_AST", "Tm_TOV", "Tm_STL", "Tm_BLK", "Tm_PF", "Tm_PFR",
    "Opp_Score", "Opp_FG", "Opp_FGA", "Opp_3PM", "Opp_3PA", "Opp_2PM",
    "Opp_FTM", "Opp_FTA", "Opp_ORB", "Opp_DRB", "Opp_TRB",
    "Opp_AST", "Opp_TOV", "Opp_STL", "Opp_BLK", "Opp_PF", "Opp_PFR",
])

def _build_comp_cat_map():
    """Construye mapa competicion_id (str) → categoría desde la tabla competiciones."""
    _cc = {}
    try:
        comp_data = _fetch_all_rows("competiciones", select_cols="competicion_id,nombre,division")
        for c in (comp_data or []):
            cid = str(c.get('competicion_id', ''))
            cn = (c.get('nombre') or '').lower()
            div = int(c.get('division') or 1)
            if 'femenil' in cn:
                _cc[cid] = f'Femenil D{div}'
            elif 'varonil' in cn or 'lnbp' in cn:
                _cc[cid] = f'Varonil D{div}'
            else:
                _cc[cid] = cn.title() or f'Liga D{div}'
    except Exception:
        pass
    return _cc

# --- CARGA 1: JUGADORES Y ESTADÍSTICAS (VISTA MAESTRA) ---
@st.cache_data(ttl=3600)
def cargar_base_datos():
    """Carga la vista analítica de jugadores.

    Cadena de fallback: vista_analitica_master → vista_analitica_mat.
    La vista regular siempre refleja los datos más recientes;
    la materializada se usa solo como fallback.
    """
    all_data = None

    for vista in ("vista_analitica_mat", "vista_analitica_master"):
        try:
            all_data = _fetch_all_rows(vista, select_cols=_COLS_ANALITICA)
            if all_data:
                break
        except Exception:
            continue

    if not all_data:
        return pd.DataFrame()

    try:
        df_master = pd.DataFrame(all_data)

        # Normalizar id_abe a string entero limpio (evita "2323805.0" si la vista devuelve float)
        if 'id_abe' in df_master.columns:
            df_master['id_abe'] = df_master['id_abe'].astype(str).str.split('.').str[0]

        # Limpieza de Minutos
        if 'sMinutes' in df_master.columns:
             if df_master['sMinutes'].dtype == object or df_master['sMinutes'].dtype == str:
                 df_master['sMinutes'] = vectorizar_minutos(df_master['sMinutes'])
             else:
                 df_master['sMinutes'] = pd.to_numeric(df_master['sMinutes'], errors='coerce').fillna(0)

        if 'Tm_MIN' in df_master.columns:
             if df_master['Tm_MIN'].dtype == object:
                 df_master['Tm_MIN'] = vectorizar_minutos(df_master['Tm_MIN'])
             else:
                 df_master['Tm_MIN'] = pd.to_numeric(df_master['Tm_MIN'], errors='coerce').fillna(0)

        # Fechas
        if 'Fecha' in df_master.columns:
            df_master['Fecha'] = pd.to_datetime(df_master['Fecha'], errors='coerce')
        else:
             df_master['Fecha'] = datetime.now()

        # Sanitización Numérica (EXCLUYENDO Opp_Name)
        cols_numericas = [c for c in df_master.columns if c.startswith('s') or c.startswith('Tm_') or c.startswith('Opp_')]

        for col in cols_numericas:
             if col not in ['sMinutes', 'Tm_MIN', 'Opp_Name']:
                df_master[col] = pd.to_numeric(df_master[col], errors='coerce').fillna(0)

        # Limpieza específica para Opp_Name (Asegurar que sea Texto)
        if 'Opp_Name' in df_master.columns:
            df_master['Opp_Name'] = df_master['Opp_Name'].astype(str).replace(['nan', 'None', '0', '0.0'], '-')

        # Eliminar filas "auto-rival": equipo_nombre == Opp_Name
        if 'Opp_Name' in df_master.columns and 'equipo_nombre' in df_master.columns:
            df_master = df_master[df_master['Opp_Name'] != df_master['equipo_nombre']].copy()

        # Corregir Categoria para competicion_ids no mapeados en la vista SQL
        if 'competition_id' in df_master.columns and 'Categoria' in df_master.columns:
            _other_mask = df_master['Categoria'] == 'Otro'
            if _other_mask.any():
                _cc = _build_comp_cat_map()
                df_master.loc[_other_mask, 'Categoria'] = (
                    df_master.loc[_other_mask, 'competition_id'].astype(str).map(_cc).fillna('Otro')
                )

        df_master = aplicar_display_names(df_master)
        return df_master

    except Exception as e:
        st.error(f"⚠️ Error cargando datos de Jugadores: {e}")
        return pd.DataFrame()

# --- CARGA 2: EQUIPOS (CARRIL B - SIN DUPLICADOS) ---

def _cargar_equipos_desde_tablas_raw():
    """Construye datos de equipos consultando partidos_detalle y equipos directamente.

    Las vistas SQL (vista_equipos_master) usan INNER JOIN en la auto-unión de
    partidos_detalle para obtener stats del rival. Eso descarta silenciosamente
    los juegos donde el registro del rival no existe. Esta función hace el
    equivalente con LEFT JOIN en Python, preservando TODOS los juegos.
    """
    _PD_COLS = ",".join([
        "partido_id", "equipo_id", "dia", "score", "etapa",
        "tot_sfieldgoalsmade", "tot_sfieldgoalsattempted",
        "tot_stwopointersmade",
        "tot_sthreepointersmade", "tot_sthreepointersattempted",
        "tot_sfreethrowsmade", "tot_sfreethrowsattempted",
        "tot_sreboundsoffensive", "tot_sreboundsdefensive", "tot_sreboundstotal",
        "tot_sassists", "tot_sturnovers", "tot_ssteals", "tot_sblocks",
        "tot_sfoulspersonal", "tot_sfoulson",
    ])
    pd_data = _fetch_all_rows("partidos_detalle", select_cols=_PD_COLS)
    if not pd_data:
        return pd.DataFrame()

    eq_data = _fetch_all_rows("equipos", select_cols="equipo_id,nombre")
    pt_data = _fetch_all_rows("partidos", select_cols="partido_id,competicion_id")
    df_pd = pd.DataFrame(pd_data)
    df_eq = (pd.DataFrame(eq_data) if eq_data
             else pd.DataFrame(columns=["equipo_id", "nombre"]))
    df_pt = (pd.DataFrame(pt_data) if pt_data
             else pd.DataFrame(columns=["partido_id", "competicion_id"]))

    # competicion_id viene de partidos (1 por juego, correcto para cada temporada)
    # nombre viene de equipos (sin usar su competicion_id, que solo refleja la más reciente)
    df_team = df_pd.merge(df_eq[['equipo_id', 'nombre']], on='equipo_id', how='left')
    df_team = df_team.merge(df_pt[['partido_id', 'competicion_id']], on='partido_id', how='left')

    # Build opponent-side DataFrame (rename all stats to Opp_*)
    _opp_map = {
        'equipo_id': 'opp_equipo_id',
        'score': 'Opp_Score',
        'tot_sfieldgoalsmade': 'Opp_FG',
        'tot_sfieldgoalsattempted': 'Opp_FGA',
        'tot_sthreepointersmade': 'Opp_3PM',
        'tot_sthreepointersattempted': 'Opp_3PA',
        'tot_stwopointersmade': 'Opp_2PM',
        'tot_sfreethrowsmade': 'Opp_FTM',
        'tot_sfreethrowsattempted': 'Opp_FTA',
        'tot_sreboundsoffensive': 'Opp_ORB',
        'tot_sreboundsdefensive': 'Opp_DRB',
        'tot_sreboundstotal': 'Opp_TRB',
        'tot_sassists': 'Opp_AST',
        'tot_sturnovers': 'Opp_TOV',
        'tot_ssteals': 'Opp_STL',
        'tot_sblocks': 'Opp_BLK',
        'tot_sfoulspersonal': 'Opp_PF',
        'tot_sfoulson': 'Opp_PFR',
    }
    _opp_keep = ['partido_id', 'opp_equipo_id',
                 'Opp_Score', 'Opp_FG', 'Opp_FGA', 'Opp_3PM', 'Opp_3PA', 'Opp_2PM',
                 'Opp_FTM', 'Opp_FTA', 'Opp_ORB', 'Opp_DRB', 'Opp_TRB',
                 'Opp_AST', 'Opp_TOV', 'Opp_STL', 'Opp_BLK', 'Opp_PF', 'Opp_PFR']
    df_opp = df_pd.rename(columns=_opp_map)[_opp_keep]

    # LEFT JOIN: cada fila de df_team busca su rival en df_opp por partido_id.
    # Juego con 2 registros → 2 matches por fila (self + rival); filtramos self.
    # Juego con 1 registro  → 1 match (self); lo conservamos con Opp_* = 0.
    df_full = df_team.merge(df_opp, on='partido_id', how='left')
    df_full['_is_self'] = df_full['equipo_id'] == df_full['opp_equipo_id']

    # Detectar qué pares (partido_id, equipo_id) tienen al menos un rival real
    _has_opp = (
        df_full.loc[~df_full['_is_self'], ['partido_id', 'equipo_id']]
        .drop_duplicates()
        .assign(_has_opp=True)
    )
    df_full = df_full.merge(_has_opp, on=['partido_id', 'equipo_id'], how='left')
    df_full['_has_opp'] = df_full['_has_opp'].fillna(False)

    # Juegos con rival real → conservar solo filas no-self
    df_with_opp = df_full[~df_full['_is_self']].copy()

    # Juegos huérfanos (sin rival) → conservar fila self con Opp_* en 0
    df_orphan = df_full[df_full['_is_self'] & ~df_full['_has_opp']].copy()
    _opp_stat_cols = [c for c in df_full.columns if c.startswith('Opp_')]
    df_orphan[_opp_stat_cols] = 0

    df_r = pd.concat([df_with_opp, df_orphan], ignore_index=True)
    df_r.drop(columns=['_is_self', '_has_opp', 'opp_equipo_id'], errors='ignore', inplace=True)

    # --- Columnas estándar ---
    df_r['id_abe'] = df_r['partido_id'].apply(lambda x: str(int(x)) if pd.notna(x) else '')
    df_r['equipo_nombre'] = df_r['nombre']
    df_r['Fecha'] = pd.to_datetime(df_r['dia'], errors='coerce')
    df_r['Tm_Score'] = pd.to_numeric(df_r['score'], errors='coerce').fillna(0)

    _tm_map = {
        'tot_sfieldgoalsmade': 'Tm_FG', 'tot_sfieldgoalsattempted': 'Tm_FGA',
        'tot_sthreepointersmade': 'Tm_3PM', 'tot_sthreepointersattempted': 'Tm_3PA',
        'tot_stwopointersmade': 'Tm_2PM',
        'tot_sfreethrowsmade': 'Tm_FTM', 'tot_sfreethrowsattempted': 'Tm_FTA',
        'tot_sreboundsoffensive': 'Tm_ORB', 'tot_sreboundsdefensive': 'Tm_DRB',
        'tot_sreboundstotal': 'Tm_TRB',
        'tot_sassists': 'Tm_AST', 'tot_sturnovers': 'Tm_TOV', 'tot_ssteals': 'Tm_STL',
        'tot_sblocks': 'Tm_BLK', 'tot_sfoulspersonal': 'Tm_PF', 'tot_sfoulson': 'Tm_PFR',
    }
    for src, dst in _tm_map.items():
        if src in df_r.columns:
            df_r[dst] = pd.to_numeric(df_r[src], errors='coerce').fillna(0)

    _comp_cat = _build_comp_cat_map()
    def _cat(cid):
        try:
            return _comp_cat.get(str(int(float(cid))), 'Otro')
        except (ValueError, TypeError):
            return 'Otro'
    df_r['Categoria'] = df_r['competicion_id'].apply(_cat)

    # TODO: llenar con los competicion_id reales de LNBP → temporada_id
    _COMP_TO_TEMP_ID: dict[int, int] = {}
    def _temp_id(cid):
        try:
            return _COMP_TO_TEMP_ID.get(int(float(cid)))
        except (ValueError, TypeError):
            return None
    df_r['temporada_id'] = df_r['competicion_id'].apply(_temp_id)

    for col in _opp_stat_cols:
        if col in df_r.columns:
            df_r[col] = pd.to_numeric(df_r[col], errors='coerce').fillna(0)

    if 'etapa' in df_r.columns:
        df_r['etapa'] = df_r['etapa'].fillna('1').astype(str)

    expected = _COLS_EQUIPOS.split(',') + ['etapa', 'temporada_id']
    return df_r[[c for c in expected if c in df_r.columns]].copy()


@st.cache_data(ttl=3600)
def cargar_lookup_etapas():
    """Lookup directo: partido_id → etapa desde partidos_detalle."""
    data = _fetch_all_rows("partidos_detalle", select_cols="partido_id,etapa")
    if not data:
        return pd.DataFrame(columns=['id_abe', 'etapa'])
    df = pd.DataFrame(data)
    df['id_abe'] = df['partido_id'].astype(str)
    df = df[['id_abe', 'etapa']].drop_duplicates(subset=['id_abe'])
    df['etapa'] = df['etapa'].fillna('1').astype(str)
    return df

@st.cache_data(ttl=3600)
def cargar_catalogo_temporadas():
    """Carga catálogo de temporadas ordenado por fecha de inicio descendente."""
    data = _fetch_all_rows("temporadas", select_cols="temporada_id,nombre,fecha_inicio")
    if not data:
        return pd.DataFrame(columns=['temporada_id', 'nombre'])
    df = pd.DataFrame(data)
    df['temporada_id'] = pd.to_numeric(df['temporada_id'], errors='coerce').astype('Int64')
    if 'fecha_inicio' in df.columns:
        df['fecha_inicio'] = pd.to_datetime(df['fecha_inicio'], errors='coerce')
        df = df.sort_values('fecha_inicio', ascending=False)
    df = df.dropna(subset=['temporada_id']).reset_index(drop=True)
    df['nombre'] = df.apply(
        lambda r: r['nombre'] if pd.notna(r['nombre'])
        else f"Temporada {int(r['temporada_id'])}",
        axis=1
    )
    return df[['temporada_id', 'nombre']]

@st.cache_data(ttl=600)
def cargar_lookup_temporada():
    """Lookup directo: id_abe (str partido_id) → temporada_id (int) desde partidos."""
    data = _fetch_all_rows("partidos", select_cols="partido_id,temporada_id")
    if not data:
        return {}
    return {
        str(r['partido_id']): int(r['temporada_id'])
        for r in data
        if r.get('temporada_id') is not None
    }

@st.cache_data(ttl=3600)
def cargar_datos_equipos_only():
    """Carga datos de equipos con temporada_id correcto.

    Fuente primaria: tablas raw (join en Python) — garantiza temporada_id
    correcto desde competicion_id de partidos, no del equipo.
    Fallback: vistas SQL.
    """
    try:
        df = _cargar_equipos_desde_tablas_raw()
        if not df.empty:
            return df.drop_duplicates(subset=['id_abe', 'equipo_nombre'])
    except Exception:
        pass

    # TODO: llenar con los competicion_id reales de LNBP → temporada_id
    _COMP_TO_TEMP_ID: dict[int, int] = {}
    for vista in ("vista_equipos_mat", "vista_equipos_master"):
        try:
            all_data = _fetch_all_rows(vista, select_cols=_COLS_EQUIPOS)
            if all_data:
                df = pd.DataFrame(all_data)
                df = df.drop_duplicates(subset=['id_abe', 'equipo_nombre'])
                if 'Fecha' in df.columns:
                    df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
                if 'etapa' in df.columns:
                    df['etapa'] = df['etapa'].fillna('1').astype(str)
                if 'temporada_id' not in df.columns:
                    if 'competition_id' in df.columns:
                        df['temporada_id'] = df['competition_id'].apply(
                            lambda c: _COMP_TO_TEMP_ID.get(int(float(c))) if pd.notna(c) else None
                        )
                cols_num = ['Tm_Score', 'Opp_Score', 'Tm_FG', 'Tm_FGA', 'Tm_3PM', 'Tm_FTM',
                            'Tm_FTA', 'Tm_ORB', 'Tm_DRB', 'Tm_TOV', 'Opp_DRB', 'Opp_ORB',
                            'Opp_FG', 'Opp_FGA', 'Opp_3PM', 'Opp_FTM', 'Opp_FTA', 'Opp_TOV']
                for c in cols_num:
                    if c in df.columns:
                        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
                return df
        except Exception:
            continue

    st.error("No se pudo cargar datos de equipos.")
    return pd.DataFrame()
    
# --- CARGA 3: METADATA (PLAYERS & ROSTERS) ---
# Usamos un TTL más largo (ej. 1 hora) porque la estatura/peso no cambian seguido
@st.cache_data(ttl=3600) 
def cargar_metadata_jugadores():
    """
    Carga las tablas de dimensiones: players (bio) y rosters (equipos/posiciones).
    Retorna dos DataFrames: (df_players, df_rosters)
    """
    try:
        # 1. Fetch tabla 'players' (paginado para evitar límite de 1,000 filas)
        data_p = _fetch_all_rows("players")
        df_players = pd.DataFrame(data_p) if data_p else pd.DataFrame()

        # 2. Fetch tabla 'rosters' (paginado para evitar límite de 1,000 filas)
        data_r = _fetch_all_rows("rosters")
        df_rosters = pd.DataFrame(data_r) if data_r else pd.DataFrame()

        # --- Limpieza Preventiva ---
        
        # Convertir numéricos en Players
        if not df_players.empty:
            cols_bio = ['height_cm', 'weight_kg'] 
            for c in cols_bio:
                if c in df_players.columns:
                    df_players[c] = pd.to_numeric(df_players[c], errors='coerce').fillna(0)

        # Convertir fechas en Rosters (importante para ordenar por la más reciente)
        if not df_rosters.empty:
            if 'effective_start_date' in df_rosters.columns:
                df_rosters['effective_start_date'] = pd.to_datetime(df_rosters['effective_start_date'], errors='coerce')

        return df_players, df_rosters

    except Exception as e:
        st.error(f"⚠️ Error cargando Metadata (Players/Rosters): {e}")
        # Retornar DFs vacíos para no romper la app
        return pd.DataFrame(), pd.DataFrame()
    
# --- CARGA 4: TIROS (SHOT DATA) ---
@st.cache_data(ttl=3600)
def cargar_tiros(competicion_ids: tuple = ()):
    """Carga tiros desde Supabase, filtrado por competicion_ids si se proveen.

    Pasar competicion_ids como tuple (hasheable para el caché) para filtrar
    server-side y reducir el volumen de datos. Sin filtro → carga todo.
    """
    try:
        sb = get_supabase_client()
        select_cols = "tiro_id,partido_id,equipo_id,player_id,r,x,y,actiontype,subtype,per,competicion_id"
        page_size = 1000
        all_data = []
        offset = 0

        while True:
            q = sb.table("tiros").select(select_cols)
            if competicion_ids:
                q = q.in_("competicion_id", list(competicion_ids))
            response = q.range(offset, offset + page_size - 1).execute()
            if not response.data:
                break
            all_data.extend(response.data)
            if len(response.data) < page_size:
                break
            offset += len(response.data)

        if not all_data:
            return pd.DataFrame()

        df = pd.DataFrame(all_data)
        for c in ['x', 'y', 'r']:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors='coerce')
        df = df.dropna(subset=['x', 'y'])
        return df
    except Exception as e:
        st.error(f"Error cargando tiros: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def cargar_catalogo_equipos():
    """Carga solo el catálogo de equipos (ID y Nombre) para cruces."""
    try:
        # Pedimos explícitamente la tabla 'equipos' (paginado por seguridad)
        data = _fetch_all_rows("equipos", select_cols="equipo_id, nombre, competicion_id")
        return pd.DataFrame(data) if data else pd.DataFrame()
    except Exception as e:
        st.error(f"Error cargando catálogo equipos: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=300)
def cargar_display_names():
    """Carga el mapa player_id → nombre de despliegue desde la tabla players.

    Retorna dict {player_id (int): "Display First Display Family"}.
    Solo incluye jugadores que tienen al menos una columna de display definida.
    """
    try:
        data = _fetch_all_rows(
            "players",
            select_cols="player_id,first_name,family_name,display_first_name,display_family_name"
        )
        if not data:
            return {}
        result = {}
        for row in data:
            pid = row.get("player_id")
            if pid is None:
                continue
            df_name = row.get("display_first_name") or row.get("first_name") or ""
            dl_name = row.get("display_family_name") or row.get("family_name") or ""
            display = f"{df_name} {dl_name}".strip()
            # Solo agregar si difiere del nombre original
            orig = f"{row.get('first_name','')} {row.get('family_name','')}".strip()
            if display != orig:
                result[int(pid)] = display
        return result
    except Exception:
        return {}


def guardar_display_name(player_id: int, display_first: str, display_family: str) -> bool:
    """Actualiza display_first_name y display_family_name en Supabase.

    Pasar cadena vacía para borrar un override (vuelve al nombre original).
    Retorna True si el update fue exitoso.
    """
    try:
        sb = _get_supabase_client()
        payload = {
            "display_first_name": display_first.strip() or None,
            "display_family_name": display_family.strip() or None,
        }
        sb.table("players").update(payload).eq("player_id", player_id).execute()
        cargar_display_names.clear()
        return True
    except Exception as e:
        st.error(f"Error guardando nombre: {e}")
        return False


def aplicar_display_names(df: pd.DataFrame, col_id: str = "id_player", col_nombre: str = "Nombre") -> pd.DataFrame:
    """Reemplaza la columna Nombre con el nombre de despliegue donde esté definido."""
    display_map = cargar_display_names()
    if not display_map or df.empty or col_id not in df.columns:
        return df
    df = df.copy()
    df[col_nombre] = df[col_id].map(
        lambda pid: display_map.get(int(pid), None) if pd.notna(pid) else None
    ).fillna(df[col_nombre])
    return df