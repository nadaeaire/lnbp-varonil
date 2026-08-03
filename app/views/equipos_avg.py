import streamlit as st
import pandas as pd
import numpy as np
import modules.utils as utils

def render_view(df, categoria_sel):
    st.title(f"Equipos por partido | {categoria_sel}")

    if df.empty:
        st.warning("No hay datos disponibles.")
        st.stop()

    # --- 1. UNA FILA POR PARTIDO POR EQUIPO (df_eq ya viene así) ---
    df_teams = df.drop_duplicates(subset=['id_abe', 'equipo_nombre']).copy()

    # --- 2. FILTRO DE VENTANA DE JUEGOS ---
    max_games_found = df_teams.groupby('equipo_nombre')['id_abe'].nunique().max()
    if not max_games_found or pd.isna(max_games_found):
        max_games_found = 1
    else:
        max_games_found = int(max_games_found)

    _, col_slider = st.columns([1, 1])
    with col_slider:
        if max_games_found > 1:
            games_window = st.slider(
                "Calcular durante los últimos X juegos:",
                1, max_games_found, max_games_found,
                key="slider_eq_avg"
            )
        else:
            st.info("Mostrando datos disponibles.")
            games_window = 1
        utils.rastrear_cambio("Slider Juegos (Eq Avg)", games_window)

    if games_window < max_games_found:
        df_teams = df_teams.sort_values(by='Fecha', ascending=False)
        df_teams = df_teams.groupby('equipo_nombre').head(games_window)

    # --- 3. PROMEDIOS POR EQUIPO ---
    cols_mean = [
        'Tm_Score', 'Tm_FG', 'Tm_FGA', 'Tm_3PM', 'Tm_3PA', 'Tm_2PM',
        'Tm_FTM', 'Tm_FTA', 'Tm_ORB', 'Tm_DRB', 'Tm_TRB',
        'Tm_AST', 'Tm_TOV', 'Tm_STL', 'Tm_BLK', 'Tm_PF', 'Tm_PFR',
        'Opp_Score', 'Opp_FG', 'Opp_FGA', 'Opp_3PM', 'Opp_3PA', 'Opp_2PM',
        'Opp_FTM', 'Opp_FTA', 'Opp_ORB', 'Opp_DRB', 'Opp_TRB',
        'Opp_AST', 'Opp_TOV', 'Opp_STL', 'Opp_BLK', 'Opp_PF', 'Opp_PFR',
    ]
    cols_agg = {c: 'mean' for c in cols_mean if c in df_teams.columns}
    cols_agg['id_abe'] = 'count'

    leaderboard = df_teams.groupby('equipo_nombre').agg(cols_agg).reset_index()
    leaderboard.rename(columns={'id_abe': 'GP'}, inplace=True)

    # --- 4. COLUMNAS DERIVADAS (porcentajes como ratio 0-1 para formato {:.1%}) ---
    def calc_pct(num_col, den_col):
        if num_col not in leaderboard.columns or den_col not in leaderboard.columns:
            return np.zeros(len(leaderboard))
        num = leaderboard[num_col].values
        den = leaderboard[den_col].values
        return np.divide(num, den, out=np.zeros_like(num, dtype=float), where=den != 0)

    # Ofensiva
    leaderboard['FG%'] = calc_pct('Tm_FG', 'Tm_FGA')
    leaderboard['3P%'] = calc_pct('Tm_3PM', 'Tm_3PA')
    leaderboard['FT%'] = calc_pct('Tm_FTM', 'Tm_FTA')
    if 'Tm_3PA' in leaderboard.columns:
        leaderboard['Tm_2PA'] = leaderboard['Tm_FGA'] - leaderboard['Tm_3PA']
        leaderboard['2P%'] = calc_pct('Tm_2PM', 'Tm_2PA')

    # Defensiva
    leaderboard['Opp_FG%'] = calc_pct('Opp_FG', 'Opp_FGA')
    leaderboard['Opp_3P%'] = calc_pct('Opp_3PM', 'Opp_3PA')
    leaderboard['Opp_FT%'] = calc_pct('Opp_FTM', 'Opp_FTA')
    if 'Opp_3PA' in leaderboard.columns:
        leaderboard['Opp_2PA'] = leaderboard['Opp_FGA'] - leaderboard['Opp_3PA']
        leaderboard['Opp_2P%'] = calc_pct('Opp_2PM', 'Opp_2PA')

    # --- 5. PESTAÑAS ---
    tab_off, tab_def = st.tabs(["Ofensiva", "Defensiva"])

    # ===================================================================
    #  PESTAÑA OFENSIVA
    # ===================================================================
    with tab_off:
        _render_tabla(
            leaderboard,
            prefix="off",
            opciones_orden={
                "PTS": "Tm_Score",
                "FGM": "Tm_FG", "FGA": "Tm_FGA", "FG%": "FG%",
                "2PM": "Tm_2PM", "2PA": "Tm_2PA", "2P%": "2P%",
                "3PM": "Tm_3PM", "3PA": "Tm_3PA", "3P%": "3P%",
                "FTM": "Tm_FTM", "FTA": "Tm_FTA", "FT%": "FT%",
                "RBO": "Tm_ORB", "RBD": "Tm_DRB", "RBT": "Tm_TRB",
                "AST": "Tm_AST", "TOV": "Tm_TOV",
                "STL": "Tm_STL", "BLK": "Tm_BLK",
                "PF": "Tm_PF", "PFR": "Tm_PFR",
            },
            default_sort="PTS",
            asc_keys=("TOV", "PF"),
            estructura={
                ('', 'Equipo'): 'equipo_nombre',
                ('', 'JJ'): 'GP',
                ('', 'PTS'): 'Tm_Score',
                ('Tiros totales', 'FGM'): 'Tm_FG',
                ('Tiros totales', 'FGA'): 'Tm_FGA',
                ('Tiros totales', 'FG%'): 'FG%',
                ('Dobles', '2PM'): 'Tm_2PM',
                ('Dobles', '2PA'): 'Tm_2PA',
                ('Dobles', '2P%'): '2P%',
                ('Triples', '3PM'): 'Tm_3PM',
                ('Triples', '3PA'): 'Tm_3PA',
                ('Triples', '3P%'): '3P%',
                ('Tiros libres', 'FTM'): 'Tm_FTM',
                ('Tiros libres', 'FTA'): 'Tm_FTA',
                ('Tiros libres', 'FT%'): 'FT%',
                ('Rebotes', 'RBO'): 'Tm_ORB',
                ('Rebotes', 'RBD'): 'Tm_DRB',
                ('Rebotes', 'RBT'): 'Tm_TRB',
                (' ', 'AST'): 'Tm_AST',
                (' ', 'TOV'): 'Tm_TOV',
                (' ', 'STL'): 'Tm_STL',
                (' ', 'BLK'): 'Tm_BLK',
                ('Faltas', 'PF'): 'Tm_PF',
                ('Faltas', 'PFR'): 'Tm_PFR',
            },
        )

    # ===================================================================
    #  PESTAÑA DEFENSIVA
    # ===================================================================
    with tab_def:
        _render_tabla(
            leaderboard,
            prefix="def",
            opciones_orden={
                "PTS": "Opp_Score",
                "FGM": "Opp_FG", "FGA": "Opp_FGA", "FG%": "Opp_FG%",
                "2PM": "Opp_2PM", "2PA": "Opp_2PA", "2P%": "Opp_2P%",
                "3PM": "Opp_3PM", "3PA": "Opp_3PA", "3P%": "Opp_3P%",
                "FTM": "Opp_FTM", "FTA": "Opp_FTA", "FT%": "Opp_FT%",
                "RBO": "Opp_ORB", "RBD": "Opp_DRB", "RBT": "Opp_TRB",
                "AST": "Opp_AST", "TOV": "Opp_TOV",
                "STL": "Opp_STL", "BLK": "Opp_BLK",
                "PF": "Opp_PF", "PFR": "Opp_PFR",
            },
            default_sort="PTS",
            asc_keys=("PTS", "FGM", "FGA", "FG%",
                       "2PM", "2PA", "2P%",
                       "3PM", "3PA", "3P%",
                       "FTM", "FTA", "FT%",
                       "RBO", "RBD", "RBT"),
            estructura={
                ('', 'Equipo'): 'equipo_nombre',
                ('', 'JJ'): 'GP',
                ('', 'PTS'): 'Opp_Score',
                ('Tiros totales', 'FGM'): 'Opp_FG',
                ('Tiros totales', 'FGA'): 'Opp_FGA',
                ('Tiros totales', 'FG%'): 'Opp_FG%',
                ('Dobles', '2PM'): 'Opp_2PM',
                ('Dobles', '2PA'): 'Opp_2PA',
                ('Dobles', '2P%'): 'Opp_2P%',
                ('Triples', '3PM'): 'Opp_3PM',
                ('Triples', '3PA'): 'Opp_3PA',
                ('Triples', '3P%'): 'Opp_3P%',
                ('Tiros libres', 'FTM'): 'Opp_FTM',
                ('Tiros libres', 'FTA'): 'Opp_FTA',
                ('Tiros libres', 'FT%'): 'Opp_FT%',
                ('Rebotes', 'RBO'): 'Opp_ORB',
                ('Rebotes', 'RBD'): 'Opp_DRB',
                ('Rebotes', 'RBT'): 'Opp_TRB',
                (' ', 'AST'): 'Opp_AST',
                (' ', 'TOV'): 'Opp_TOV',
                (' ', 'STL'): 'Opp_STL',
                (' ', 'BLK'): 'Opp_BLK',
                ('Faltas', 'PF'): 'Opp_PF',
                ('Faltas', 'PFR'): 'Opp_PFR',
            },
        )


# ===================================================================
#  HELPER: tabla ordenable reutilizable para ambas pestañas
# ===================================================================
def _render_tabla(leaderboard, *, prefix, opciones_orden, default_sort,
                  asc_keys, estructura):
    """Renderiza tabla MultiIndex con estilo, igual que equipos_4f y equipos_smry."""

    # Filtrar opciones cuya columna no exista
    opciones_orden = {k: v for k, v in opciones_orden.items() if v in leaderboard.columns}
    if not opciones_orden:
        st.info("Sin datos para esta pestaña.")
        return

    nombres_largos = {
        "PTS": "Puntos por partido", "RBT": "Rebotes totales",
        "AST": "Asistencias", "TOV": "Pérdidas",
        "3PM": "Triples Anotados", "FGM": "Tiros Anotados",
        "FG%": "% de Campo", "2PM": "Dobles Anotados", "2P%": "% de Dobles",
        "FT%": "% de Libres", "3P%": "% de Triples",
        "STL": "Robos", "BLK": "Bloqueos",
        "PF": "Faltas personales", "PFR": "Faltas recibidas",
    }

    lista_opciones = list(opciones_orden.keys())
    try:
        idx = lista_opciones.index(default_sort)
    except ValueError:
        idx = 0

    criterio_sort = st.radio(
        "Ordenar por:", options=lista_opciones, index=idx,
        horizontal=True, label_visibility="collapsed",
        key=f"rad_eq_{prefix}"
    )
    utils.rastrear_cambio(f"Ordenar Por (Eq {prefix})", criterio_sort)

    col_sort = opciones_orden[criterio_sort]
    ascendente = criterio_sort in asc_keys

    flecha = "⬆️" if ascendente else "⬇️"
    nombre_mostrar = nombres_largos.get(criterio_sort, criterio_sort)
    st.caption(f"Ordenando por **{nombre_mostrar}** ({flecha})")

    tabla = leaderboard.sort_values(by=col_sort, ascending=ascendente)

    # Construir DataFrame MultiIndex
    data_struct = {}
    for key, src_col in estructura.items():
        if src_col in tabla.columns:
            data_struct[key] = tabla[src_col].values

    df_multi = pd.DataFrame(data_struct)

    # Formatos automáticos
    fmt = {}
    for col in df_multi.columns:
        label = col[1]
        if label == 'Equipo':
            continue
        elif label == 'JJ':
            fmt[col] = "{:.0f}"
        elif '%' in label:
            fmt[col] = "{:.1%}"
        else:
            fmt[col] = "{:.1f}"

    # Forzar ancho de columna Equipo (esta vista tiene muchas columnas numéricas
    # de ancho similar, a diferencia de equipos_4f/smry que tienen Ranks angostos)
    st.dataframe(
        df_multi.style.format(fmt),
        height=(len(df_multi) * 35) + 75,
        use_container_width=True,
        hide_index=True,
    )
