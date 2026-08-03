import streamlit as st
import pandas as pd
import numpy as np
import math
import modules.utils as utils

_BASE = 28

def render_view(df, df_players, df_rosters, categoria_sel):
    st.title(f"Leaderboard PER28 | {categoria_sel}")

    # --- 0. METADATA ---
    df_players['player_id_str'] = df_players['player_id'].astype(str)
    df_rosters['player_id_str'] = df_rosters['player_id'].astype(str)

    mapa_posicion = {}
    if not df_rosters.empty and 'effective_start_date' in df_rosters.columns:
        df_last_pos = df_rosters.sort_values('effective_start_date', ascending=False).drop_duplicates(subset=['player_id_str'])
        mapa_posicion = pd.Series(df_last_pos.playing_position.values, index=df_last_pos.player_id_str).to_dict()

    mapa_altura = {}
    mapa_peso = {}
    if not df_players.empty:
        df_players['height_cm'] = pd.to_numeric(df_players['height_cm'], errors='coerce').fillna(0)
        df_players['weight_kg'] = pd.to_numeric(df_players['weight_kg'], errors='coerce').fillna(0)
        mapa_altura = pd.Series(df_players.height_cm.values, index=df_players.player_id_str).to_dict()
        mapa_peso   = pd.Series(df_players.weight_kg.values, index=df_players.player_id_str).to_dict()

    # --- 1. FILTROS BÁSICOS ---
    max_games_found = df.groupby('equipo_nombre')['id_abe'].nunique().max()
    if not max_games_found or pd.isna(max_games_found): max_games_found = 1
    else: max_games_found = int(max_games_found)

    lista_equipos = ["Todos"] + sorted(df['equipo_nombre'].unique())

    col_team, col_slider = st.columns([1, 1])
    with col_team:
        if 'p28_equipo' not in st.session_state:
            st.session_state.p28_equipo = "Todos"
        _idx_eq = lista_equipos.index(st.session_state.p28_equipo) if st.session_state.p28_equipo in lista_equipos else 0
        equipo_filtro = st.selectbox("Filtrar por Equipo:", lista_equipos, index=_idx_eq, key="sel_team_p28")
        st.session_state.p28_equipo = equipo_filtro
        utils.rastrear_cambio("Filtro Equipo (P28)", equipo_filtro)
    with col_slider:
        if max_games_found > 1:
            games_window = st.slider("Calcular durante los últimos X juegos:", 1, max_games_found, max_games_found, key="slider_p28")
        else:
            st.info("Mostrando datos disponibles.")
            games_window = 1
        utils.rastrear_cambio("Slider Juegos (P28)", games_window)

    # --- 2. FILTRADO DE DATA ---
    df_view = df[df['equipo_nombre'] == equipo_filtro] if equipo_filtro != "Todos" else df
    df_active = df_view[df_view['sMinutes'] > 0].copy()

    if games_window < max_games_found:
        df_active = df_active.sort_values('Fecha', ascending=False).groupby('id_player').head(games_window)

    if games_window < max_games_found:
        threshold_games = math.ceil(games_window * 0.40)
    else:
        base_games = (df_view.groupby('equipo_nombre')['id_abe'].nunique().max()
                      if equipo_filtro != "Todos"
                      else df_view.groupby('equipo_nombre')['id_abe'].nunique().min())
        if pd.isna(base_games): base_games = 1
        threshold_games = math.ceil(base_games * 0.50)

    # --- 3. AGRUPACIÓN POR TOTALES ---
    agg_cols = {
        'sMinutes': 'sum',
        'sPoints': 'sum', 'sReboundsTotal': 'sum', 'sReboundsOffensive': 'sum',
        'sReboundsDefensive': 'sum', 'sAssists': 'sum', 'sTurnovers': 'sum',
        'sSteals': 'sum', 'sBlocks': 'sum', 'sFoulsPersonal': 'sum', 'sFoulsOn': 'sum',
        'sFieldGoalsMade': 'sum', 'sFieldGoalsAttempted': 'sum',
        'sTwoPointersMade': 'sum', 'sTwoPointersAttempted': 'sum',
        'sThreePointersMade': 'sum', 'sThreePointersAttempted': 'sum',
        'sFreeThrowsMade': 'sum', 'sFreeThrowsAttempted': 'sum',
        'starter': 'sum',
        'id_abe': 'count',
        # MIN promedio (igual que "Por partido")
    }
    lb = df_active.groupby(['id_player', 'Nombre', 'equipo_nombre']).agg(agg_cols).reset_index()

    # MIN promedio separado (igual que "Por partido")
    mpg = df_active.groupby('id_player')['sMinutes'].mean().rename('MPG')
    lb = lb.merge(mpg, on='id_player', how='left')

    lb.rename(columns={'id_abe': 'GP', 'starter': 'JT'}, inplace=True)

    # --- 4. CÁLCULO PER28 ---
    # p28 recibe una Serie (no un nombre de columna) para leer los totales
    # originales antes de que cualquier columna sea sobrescrita.
    total_min = lb['sMinutes'].replace(0, np.nan)

    def p28(series):
        return (series / total_min * _BASE).round(2)

    # Porcentajes desde totales (antes de cualquier transformación)
    lb['FG%'] = np.where(lb['sFieldGoalsAttempted']  > 0, lb['sFieldGoalsMade']   / lb['sFieldGoalsAttempted']  * 100, 0.0)
    lb['2P%'] = np.where(lb['sTwoPointersAttempted']  > 0, lb['sTwoPointersMade']  / lb['sTwoPointersAttempted']  * 100, 0.0)
    lb['3P%'] = np.where(lb['sThreePointersAttempted']> 0, lb['sThreePointersMade']/ lb['sThreePointersAttempted']* 100, 0.0)
    lb['FT%'] = np.where(lb['sFreeThrowsAttempted']   > 0, lb['sFreeThrowsMade']   / lb['sFreeThrowsAttempted']   * 100, 0.0)

    # Stats PER28 — cada una lee el total original y escribe a columna nueva
    lb['PTS'] = p28(lb['sPoints'])
    lb['RBT'] = p28(lb['sReboundsTotal'])
    lb['RBO'] = p28(lb['sReboundsOffensive'])
    lb['RBD'] = p28(lb['sReboundsDefensive'])
    lb['AST'] = p28(lb['sAssists'])
    lb['TOV'] = p28(lb['sTurnovers'])
    lb['STL'] = p28(lb['sSteals'])
    lb['BLK'] = p28(lb['sBlocks'])
    lb['PF']  = p28(lb['sFoulsPersonal'])
    lb['PFR'] = p28(lb['sFoulsOn'])
    lb['FGM'] = p28(lb['sFieldGoalsMade'])
    lb['FGA'] = p28(lb['sFieldGoalsAttempted'])
    lb['2PM'] = p28(lb['sTwoPointersMade'])
    lb['2PA'] = p28(lb['sTwoPointersAttempted'])
    lb['3PM'] = p28(lb['sThreePointersMade'])
    lb['3PA'] = p28(lb['sThreePointersAttempted'])
    lb['FTM'] = p28(lb['sFreeThrowsMade'])
    lb['FTA'] = p28(lb['sFreeThrowsAttempted'])

    # --- 5. ENRIQUECIMIENTO ---
    lb['id_player_str'] = lb['id_player'].astype(str)
    lb['Pos']    = lb['id_player_str'].map(mapa_posicion).fillna("N/A")
    lb['Altura'] = lb['id_player_str'].map(mapa_altura).fillna(0)

    # --- 6. FILTROS AVANZADOS ---
    st.markdown("---")
    c_search, c_pos, c_hgt = st.columns([1.5, 1.5, 2])
    with c_search:
        search_query = st.text_input("🔍 Buscar jugador", placeholder="Nombre o Apellido...", key="search_p28")
        if search_query: utils.rastrear_cambio("Búsqueda Texto (P28)", search_query)
    with c_pos:
        opciones_pos = sorted(lb[lb['Pos'] != "N/A"]['Pos'].unique())
        filtro_pos = st.multiselect("Posición", options=opciones_pos, placeholder="Todas", key="pos_p28")
        if filtro_pos: utils.rastrear_cambio("Filtro Posición (P28)", str(filtro_pos))
    with c_hgt:
        alturas_validas = lb[lb['Altura'] > 0]['Altura']
        min_h = int(alturas_validas.min()) if not alturas_validas.empty else 150
        max_h = int(alturas_validas.max()) if not alturas_validas.empty else 210
        filtro_altura = st.slider("Rango de Estatura (cm)", min_value=min_h, max_value=max_h, value=(min_h, max_h), key="slider_height_p28")
        if filtro_altura != (min_h, max_h): utils.rastrear_cambio("Filtro Altura (P28)", str(filtro_altura))

    if search_query:
        lb = lb[lb['Nombre'].str.contains(search_query, case=False, na=False)]
    if filtro_pos:
        lb = lb[lb['Pos'].isin(filtro_pos)]
    if filtro_altura != (min_h, max_h):
        lb = lb[(lb['Altura'] >= filtro_altura[0]) & (lb['Altura'] <= filtro_altura[1])]

    # --- 7. ORDENAMIENTO ---
    if 'sort_col_p28' not in st.session_state: st.session_state.sort_col_p28 = 'PTS'
    if 'sort_asc_p28' not in st.session_state: st.session_state.sort_asc_p28 = False
    if 'page_p28' not in st.session_state: st.session_state.page_p28 = 0

    opciones_orden = {
        "MIN": "MPG", "FGM": "FGM", "FGA": "FGA", "FG%": "FG%",
        "2PM": "2PM", "2PA": "2PA", "2P%": "2P%",
        "3PM": "3PM",  "3PA": "3PA", "3P%": "3P%",
        "FTM": "FTM", "FTA": "FTA", "FT%": "FT%",
        "RBO": "RBO", "RBD": "RBD", "RBT": "RBT",
        "AST": "AST", "TOV": "TOV", "STL": "STL",
        "BLK": "BLK", "PF": "PF", "PFR": "PFR",
        "PTS": "PTS", "ALT": "Altura",
    }
    nombres_largos = {
        "PTS": "Puntos PER28", "RBT": "Rebotes PER28", "AST": "Asistencias PER28",
        "MIN": "Minutos promedio", "3PM": "Triples PER28",
        "FG%": "% de Campo", "2P%": "% de Dobles", "FT%": "% de Libres", "3P%": "% de Triples",
        "ALT": "Altura en centímetros",
    }

    st.markdown("##### Ordenar por:")
    lista_ops = list(opciones_orden.keys())
    try: idx = lista_ops.index("PTS")
    except: idx = 0
    sort_key_sel = st.radio("Métrica:", options=lista_ops, index=idx, horizontal=True, label_visibility="collapsed", key="rad_p28")
    utils.rastrear_cambio("Ordenar Por (P28)", sort_key_sel)

    nueva_col = opciones_orden[sort_key_sel]
    if st.session_state.sort_col_p28 != nueva_col:
        st.session_state.sort_col_p28 = nueva_col
        st.session_state.sort_asc_p28 = False
        st.session_state.page_p28 = 0

    flecha = "⬆️ Menor a Mayor" if st.session_state.sort_asc_p28 else "⬇️ Mayor a Menor"
    nombre_mostrar = nombres_largos.get(sort_key_sel, sort_key_sel)
    st.caption(f"Ordenando por **{nombre_mostrar}** ({flecha})")

    c_btn, _, c_check = st.columns([1.5, 6, 3])
    with c_btn:
        if st.button("🔄 Invertir Orden", key="btn_inv_p28", use_container_width=True):
            st.session_state.sort_asc_p28 = not st.session_state.sort_asc_p28
            st.rerun()
    with c_check:
        qualified_on = st.checkbox(f"Qualified: mínimo {threshold_games} juegos + 10 min/partido", value=True, key="chk_p28")
        utils.rastrear_cambio("Filtro Qualified (P28)", qualified_on)

    if qualified_on:
        lb = lb[(lb['GP'] >= threshold_games) & (lb['MPG'] >= 10.0)]

    lb = lb.sort_values(by=st.session_state.sort_col_p28, ascending=st.session_state.sort_asc_p28)

    # --- 8. TABLA ---
    ROWS_PER_PAGE = 30
    total_rows  = len(lb)
    total_pages = math.ceil(total_rows / ROWS_PER_PAGE)

    if st.session_state.page_p28 >= total_pages: st.session_state.page_p28 = 0
    if total_pages == 0: st.session_state.page_p28 = 0

    start_idx = st.session_state.page_p28 * ROWS_PER_PAGE
    df_page = lb.iloc[start_idx:start_idx + ROWS_PER_PAGE]

    orden_cols = ["Nombre", "equipo_nombre", "Pos", "GP", "JT", "MPG",
                  "FGM", "FGA", "FG%", "2PM", "2PA", "2P%",
                  "3PM", "3PA", "3P%", "FTM", "FTA", "FT%",
                  "RBO", "RBD", "RBT", "AST", "TOV", "STL", "BLK", "PF", "PFR",
                  "PTS", "Altura"]
    cols_finales = [c for c in orden_cols if c in df_page.columns]

    event = st.dataframe(
        df_page[cols_finales],
        hide_index=True, use_container_width=True,
        height=(len(df_page) + 1) * 35 + 3,
        on_select="rerun", selection_mode="single-row",
        column_config={
            "Nombre":       st.column_config.TextColumn("Nombre"),
            "equipo_nombre":st.column_config.TextColumn("Equipo"),
            "Pos":          st.column_config.TextColumn("Pos"),
            "Altura":       st.column_config.NumberColumn("ALT", format="%d"),
            "GP":           st.column_config.NumberColumn("JJ",  format="%d"),
            "JT":           st.column_config.NumberColumn("JT",  format="%d"),
            "MPG":          st.column_config.NumberColumn("MIN", format="%.1f"),
            "PTS":          st.column_config.NumberColumn("PTS", format="%.1f"),
            "RBT":          st.column_config.NumberColumn("RBT", format="%.1f"),
            "AST":          st.column_config.NumberColumn("AST", format="%.1f"),
            "3PM":          st.column_config.NumberColumn("3PM", format="%.1f"),
            "FGM":          st.column_config.NumberColumn("FGM", format="%.1f"),
            "FGA":          st.column_config.NumberColumn("FGA", format="%.1f"),
            "2PM":          st.column_config.NumberColumn("2PM", format="%.1f"),
            "2PA":          st.column_config.NumberColumn("2PA", format="%.1f"),
            "3PA":          st.column_config.NumberColumn("3PA", format="%.1f"),
            "FTM":          st.column_config.NumberColumn("FTM", format="%.1f"),
            "FTA":          st.column_config.NumberColumn("FTA", format="%.1f"),
            "RBO":          st.column_config.NumberColumn("RBO", format="%.1f"),
            "RBD":          st.column_config.NumberColumn("RBD", format="%.1f"),
            "TOV":          st.column_config.NumberColumn("TOV", format="%.1f"),
            "STL":          st.column_config.NumberColumn("STL", format="%.1f"),
            "BLK":          st.column_config.NumberColumn("BLK", format="%.1f"),
            "PF":           st.column_config.NumberColumn("PF",  format="%.1f"),
            "PFR":          st.column_config.NumberColumn("PFR", format="%.1f"),
            "FG%":          st.column_config.NumberColumn("FG%", format="%.1f%%"),
            "2P%":          st.column_config.NumberColumn("2P%", format="%.1f%%"),
            "FT%":          st.column_config.NumberColumn("FT%", format="%.1f%%"),
            "3P%":          st.column_config.NumberColumn("3P%", format="%.1f%%"),
        }
    )

    if len(event.selection.rows) > 0 and st.session_state.get('view_mode') != 'profile':
        selected_row_idx = event.selection.rows[0]
        st.session_state['selected_player_id'] = df_page.iloc[selected_row_idx]['id_player']
        st.session_state['view_mode'] = 'profile'
        st.rerun()

    c_p1, c_pi, c_p2 = st.columns([1, 2, 1])
    with c_p1:
        if st.session_state.page_p28 > 0:
            if st.button("⬅️ Anterior", key="prev_p28"):
                st.session_state.page_p28 -= 1
                st.rerun()
    with c_pi:
        if total_pages > 0:
            st.markdown(f"<div style='text-align: center'>Página <b>{st.session_state.page_p28 + 1}</b> de <b>{total_pages}</b></div>", unsafe_allow_html=True)
        else:
            st.warning("No hay jugadors que coincidan con los filtros.")
    with c_p2:
        if st.session_state.page_p28 < total_pages - 1:
            if st.button("Siguiente ➡️", key="next_p28"):
                st.session_state.page_p28 += 1
                st.rerun()
