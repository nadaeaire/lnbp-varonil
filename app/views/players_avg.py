import streamlit as st
import pandas as pd
import numpy as np
import math
import modules.utils as utils 

def render_view(df, df_players, df_rosters, categoria_sel):
    st.title(f"Leaderboard por partido | {categoria_sel}")

    # --- 0. PREPARACIÓN DE METADATA ---
    df_players['player_id_str'] = df_players['player_id'].astype(str)
    df_rosters['player_id_str'] = df_rosters['player_id'].astype(str)
    
    mapa_posicion = {}
    if not df_rosters.empty:
        if 'effective_start_date' in df_rosters.columns:
            df_last_pos = df_rosters.sort_values('effective_start_date', ascending=False).drop_duplicates(subset=['player_id_str'])
            mapa_posicion = pd.Series(df_last_pos.playing_position.values, index=df_last_pos.player_id_str).to_dict()

    mapa_altura = {}
    mapa_peso = {} 
    if not df_players.empty:
        df_players['height_cm'] = pd.to_numeric(df_players['height_cm'], errors='coerce').fillna(0)
        df_players['weight_kg'] = pd.to_numeric(df_players['weight_kg'], errors='coerce').fillna(0)
        mapa_altura = pd.Series(df_players.height_cm.values, index=df_players.player_id_str).to_dict()
        mapa_peso = pd.Series(df_players.weight_kg.values, index=df_players.player_id_str).to_dict()

    # --- 1. FILTROS BÁSICOS ---
    max_games_found = df.groupby('equipo_nombre')['id_abe'].nunique().max()
    if not max_games_found or pd.isna(max_games_found): max_games_found = 1
    else: max_games_found = int(max_games_found)

    lista_equipos = sorted(df['equipo_nombre'].unique())
    lista_equipos.insert(0, "Todos")

    col_team, col_slider = st.columns([1, 1])
    with col_team:
        if 'avg_equipo' not in st.session_state:
            st.session_state.avg_equipo = "Todos"
        _idx_eq = lista_equipos.index(st.session_state.avg_equipo) if st.session_state.avg_equipo in lista_equipos else 0
        equipo_filtro = st.selectbox("Filtrar por Equipo:", lista_equipos, index=_idx_eq, key="sel_team_avg")
        st.session_state.avg_equipo = equipo_filtro
        utils.rastrear_cambio("Filtro Equipo (Avg)", equipo_filtro) 
    with col_slider:
        if max_games_found > 1:
            games_window = st.slider("Calcular durante los últimos X juegos:", 1, max_games_found, max_games_found, key="slider_avg")
        else:
            st.info("Mostrando datos disponibles.")
            games_window = 1
        utils.rastrear_cambio("Slider Juegos (Avg)", games_window)

    # --- DATOS DE CONTEXTO DEL EQUIPO ---
    if equipo_filtro != "Todos":
        df_active_context = df[df['sMinutes'] > 0][['id_player', 'equipo_nombre']].drop_duplicates()
        df_active_context['id_player_str'] = df_active_context['id_player'].astype(str)
        df_active_context['h'] = df_active_context['id_player_str'].map(mapa_altura).fillna(0)
        df_active_context['w'] = df_active_context['id_player_str'].map(mapa_peso).fillna(0)
        df_active_context['h_clean'] = df_active_context['h'].replace(0, np.nan)
        df_active_context['w_clean'] = df_active_context['w'].replace(0, np.nan)
        
        team_stats_context = df_active_context.groupby('equipo_nombre').agg({
            'id_player': 'count', 'h_clean': 'mean', 'w_clean': 'mean'
        }).reset_index()
        
        team_stats_context['rank_p'] = team_stats_context['id_player'].rank(ascending=False, method='min')
        team_stats_context['rank_h'] = team_stats_context['h_clean'].rank(ascending=False, method='min')
        team_stats_context['rank_w'] = team_stats_context['w_clean'].rank(ascending=False, method='min')
        
        stats_this_team = team_stats_context[team_stats_context['equipo_nombre'] == equipo_filtro]
        
        if not stats_this_team.empty:
            row = stats_this_team.iloc[0]
            total_teams = len(team_stats_context)
            n_players = int(row['id_player'])
            rank_p = f"#{int(row['rank_p'])}" if pd.notna(row['rank_p']) else "-"
            val_h = f"{row['h_clean']:.1f} cm" if pd.notna(row['h_clean']) else "N/A"
            rank_h = f"#{int(row['rank_h'])}" if pd.notna(row['rank_h']) else "-"
            val_w = f"{row['w_clean']:.1f} kg" if pd.notna(row['w_clean']) else "N/A"
            rank_w = f"#{int(row['rank_w'])}" if pd.notna(row['rank_w']) else "-"
            lbl_jugadores = "Jugadors utilizadas" if "Femenil" in categoria_sel else "Jugadores utilizados"

            st.markdown("---")
            m1, m2, m3 = st.columns(3)
            m1.metric(lbl_jugadores, n_players, f"Rank {rank_p} de {total_teams}", delta_color="off")
            m2.metric("Estatura Promedio", val_h, f"Rank {rank_h} de {total_teams}", delta_color="off")
            m3.metric("Peso Promedio", val_w, f"Rank {rank_w} de {total_teams}", delta_color="off")
            st.markdown("---")

    # --- 2. FILTRADO DE DATA ---
    if equipo_filtro != "Todos":
        df_view = df[df['equipo_nombre'] == equipo_filtro]
    else:
        df_view = df

    df_active_games = df_view[df_view['sMinutes'] > 0].copy()
    if games_window < max_games_found:
        df_active_games = df_active_games.sort_values(by='Fecha', ascending=False)
        df_active_games = df_active_games.groupby('id_player').head(games_window)

    if games_window < max_games_found:
        threshold_games = math.ceil(games_window * 0.40)
    else:
        if equipo_filtro != "Todos":
            base_games = df_view.groupby('equipo_nombre')['id_abe'].nunique().max()
        else:
            base_games = df_view.groupby('equipo_nombre')['id_abe'].nunique().min()
        if pd.isna(base_games): base_games = 1
        threshold_games = math.ceil(base_games * 0.50)

    # --- 3. AGRUPACIÓN ---
    leaderboard = df_active_games.groupby(['id_player', 'Nombre', 'equipo_nombre']).agg({
        'sPoints': 'mean', 'sReboundsTotal': 'mean', 'sAssists': 'mean',
        'sThreePointersMade': 'mean', 'sMinutes': 'mean', 'starter': 'sum',
        'sFieldGoalsMade': 'mean', 'sFieldGoalsAttempted': 'mean',
        'sTwoPointersMade': 'mean', 'sTwoPointersAttempted': 'mean',
        'sThreePointersAttempted': 'mean', 'sFreeThrowsMade': 'mean',
        'sFreeThrowsAttempted': 'mean', 'sReboundsOffensive': 'mean',
        'sReboundsDefensive': 'mean', 'sTurnovers': 'mean', 'sSteals': 'mean',
        'sBlocks': 'mean', 'sFoulsPersonal': 'mean', 'sFoulsOn': 'mean',
        'id_abe': 'count'
    }).reset_index()

    leaderboard.rename(columns={'id_abe': 'GP', 'sMinutes': 'MPG', 'starter': 'JT', 'sFieldGoalsMade': 'FGM', 'sFieldGoalsAttempted': 'FGA', 'sTwoPointersMade': '2PM', 'sTwoPointersAttempted': '2PA', 'sThreePointersAttempted': '3PA', 'sFreeThrowsMade': 'FTM', 'sFreeThrowsAttempted': 'FTA', 'sReboundsOffensive': 'RBO', 'sReboundsDefensive': 'RBD', 'sTurnovers': 'TOV', 'sSteals': 'STL', 'sBlocks': 'BLK', 'sFoulsPersonal': 'PF', 'sFoulsOn': 'PFR'}, inplace=True)

    def calc_pct(num, den):
        return np.divide(num, den, out=np.zeros_like(num, dtype=float), where=den!=0) * 100

    leaderboard['FG%'] = calc_pct(leaderboard['FGM'], leaderboard['FGA'])
    leaderboard['2P%'] = calc_pct(leaderboard['2PM'], leaderboard['2PA'])
    leaderboard['3P%'] = calc_pct(leaderboard['sThreePointersMade'], leaderboard['3PA'])
    leaderboard['FT%'] = calc_pct(leaderboard['FTM'], leaderboard['FTA'])

    # --- 4. ENRIQUECIMIENTO ---
    leaderboard['id_player_str'] = leaderboard['id_player'].astype(str)
    leaderboard['Pos'] = leaderboard['id_player_str'].map(mapa_posicion).fillna("N/A")
    leaderboard['Altura'] = leaderboard['id_player_str'].map(mapa_altura).fillna(0)

    # --- 5. FILTROS AVANZADOS ---
    st.markdown("---") 
    c_search, c_pos, c_hgt = st.columns([1.5, 1.5, 2])
    with c_search:
        search_query = st.text_input("🔍 Buscar jugador", placeholder="Nombre o Apellido...", key="search_avg")
        if search_query: utils.rastrear_cambio("Búsqueda Texto (Avg)", search_query)
    with c_pos:
        opciones_pos = sorted(leaderboard[leaderboard['Pos'] != "N/A"]['Pos'].unique())
        filtro_posicion = st.multiselect("Posición", options=opciones_pos, placeholder="Todas", key="pos_avg")
        if filtro_posicion: utils.rastrear_cambio("Filtro Posición (Avg)", str(filtro_posicion))
    with c_hgt:
        alturas_validas = leaderboard[leaderboard['Altura'] > 0]['Altura']
        if not alturas_validas.empty:
            min_h_data, max_h_data = int(alturas_validas.min()), int(alturas_validas.max())
        else:
            min_h_data, max_h_data = 150, 210
        filtro_altura = st.slider("Rango de Estatura (cm)", min_value=min_h_data, max_value=max_h_data, value=(min_h_data, max_h_data), key="slider_height_avg")
        if filtro_altura != (min_h_data, max_h_data): utils.rastrear_cambio("Filtro Altura (Avg)", str(filtro_altura))

    # --- 6. APLICACIÓN DE FILTROS ---
    if search_query:
        leaderboard = leaderboard[leaderboard['Nombre'].str.contains(search_query, case=False, na=False)]
    if filtro_posicion:
        leaderboard = leaderboard[leaderboard['Pos'].isin(filtro_posicion)]
    if filtro_altura != (min_h_data, max_h_data):
        leaderboard = leaderboard[(leaderboard['Altura'] >= filtro_altura[0]) & (leaderboard['Altura'] <= filtro_altura[1])]

    # --- 7. ORDENAMIENTO ---
    if 'sort_col' not in st.session_state: st.session_state.sort_col = 'sPoints'
    if 'sort_asc' not in st.session_state: st.session_state.sort_asc = False
    if 'page_number' not in st.session_state: st.session_state.page_number = 0

    opciones_orden = {
        "MIN": "MPG", "FGM": "FGM", "FGA": "FGA", "FG%": "FG%", "2PM": "2PM", "2PA": "2PA", "2P%": "2P%", "3PM": "sThreePointersMade", "3PA": "3PA", "3P%": "3P%", "FTM": "FTM", "FTA": "FTA", "FT%": "FT%", "RBO": "RBO", "RBD": "RBD", "RBT": "sReboundsTotal", "AST": "sAssists", "TOV": "TOV", "STL": "STL", "BLK": "BLK", "PF": "PF", "PFR": "PFR", "PTS": "sPoints", "ALT": "Altura"
    }
    nombres_largos = {"PTS": "Puntos por partido", "RBT": "Rebotes totales", "AST": "Asistencias", "MIN": "Minutos", "3PM": "Triples Anotados", "FGM": "Tiros Anotados", "FG%": "% de Campo", "2P%": "% de Dobles", "FT%": "% de Libres", "3P%": "% de Triples", "ALT": "Altura en centímetros"}

    st.markdown("##### Ordenar por:")
    lista_opciones = list(opciones_orden.keys())
    try: idx = lista_opciones.index("PTS")
    except: idx = 0
    sort_key_sel = st.radio("Métrica:", options=lista_opciones, index=idx, horizontal=True, label_visibility="collapsed", key="rad_avg")
    utils.rastrear_cambio("Ordenar Por (Avg)", sort_key_sel)

    nueva_col = opciones_orden[sort_key_sel]
    if st.session_state.sort_col != nueva_col:
        st.session_state.sort_col = nueva_col
        st.session_state.sort_asc = False
        st.session_state.page_number = 0

    flecha = "⬆️ Menor a Mayor" if st.session_state.sort_asc else "⬇️ Mayor a Menor"
    nombre_mostrar = nombres_largos.get(sort_key_sel, sort_key_sel)
    st.caption(f"Ordenando por **{nombre_mostrar}** ({flecha})")

    c_btn, _, c_check = st.columns([1.5, 6, 3])
    with c_btn:
        if st.button("🔄 Invertir Orden", key="btn_inv_avg", use_container_width=True):
            st.session_state.sort_asc = not st.session_state.sort_asc
            st.rerun()
    with c_check:
        qualified_on = st.checkbox(f"Qualified: mínimo {threshold_games} juegos + 10 min/partido", value=False, key="chk_basic")
        utils.rastrear_cambio("Filtro Qualified (Basic)", qualified_on)

    if qualified_on:
        leaderboard = leaderboard[(leaderboard['GP'] >= threshold_games) & (leaderboard['MPG'] >= 10.0)]

    leaderboard = leaderboard.sort_values(by=st.session_state.sort_col, ascending=st.session_state.sort_asc)

    # --- 8. TABLA ---
    ROWS_PER_PAGE = 30
    total_rows = len(leaderboard)
    total_pages = math.ceil(total_rows / ROWS_PER_PAGE)
    
    if st.session_state.page_number >= total_pages: st.session_state.page_number = 0
    if total_pages == 0: st.session_state.page_number = 0
        
    start_idx = st.session_state.page_number * ROWS_PER_PAGE
    end_idx = start_idx + ROWS_PER_PAGE
    df_page = leaderboard.iloc[start_idx:end_idx]

    dynamic_height = (len(df_page) + 1) * 35 + 3

    orden_columnas = ["Nombre", "equipo_nombre", "Pos", "GP", "JT", "MPG", "FGM", "FGA", "FG%", "2PM", "2PA", "2P%", "sThreePointersMade", "3PA", "3P%", "FTM", "FTA", "FT%", "RBO", "RBD", "sReboundsTotal", "sAssists", "TOV", "STL", "BLK", "PF", "PFR", "sPoints", "Altura"]
    cols_finales = [c for c in orden_columnas if c in df_page.columns]

    # --- INTERACCIÓN ---
    event = st.dataframe(
        df_page[cols_finales],
        hide_index=True, use_container_width=True, height=dynamic_height,
        on_select="rerun", 
        selection_mode="single-row", 
        column_config={
            "Nombre": st.column_config.TextColumn("Nombre"),
            "equipo_nombre": st.column_config.TextColumn("Equipo"),
            "Pos": st.column_config.TextColumn("Pos"),
            "Altura": st.column_config.NumberColumn("ALT", format="%d"),
            "GP": st.column_config.NumberColumn("JJ", format="%d"),
            "JT": st.column_config.NumberColumn("JT", format="%d"),
            "MPG": st.column_config.NumberColumn("MIN", format="%.1f"),
            "sPoints": st.column_config.NumberColumn("PTS", format="%.1f"),
            "sReboundsTotal": st.column_config.NumberColumn("RBT", format="%.1f"),
            "sAssists": st.column_config.NumberColumn("AST", format="%.1f"),
            "sThreePointersMade": st.column_config.NumberColumn("3PM", format="%.1f"),
            "FGM": st.column_config.NumberColumn("FGM", format="%.1f"),
            "FGA": st.column_config.NumberColumn("FGA", format="%.1f"),
            "2PM": st.column_config.NumberColumn("2PM", format="%.1f"),
            "2PA": st.column_config.NumberColumn("2PA", format="%.1f"),
            "3PA": st.column_config.NumberColumn("3PA", format="%.1f"),
            "FTM": st.column_config.NumberColumn("FTM", format="%.1f"),
            "FTA": st.column_config.NumberColumn("FTA", format="%.1f"),
            "RBO": st.column_config.NumberColumn("RBO", format="%.1f"),
            "RBD": st.column_config.NumberColumn("RBD", format="%.1f"),
            "TOV": st.column_config.NumberColumn("TOV", format="%.1f"),
            "STL": st.column_config.NumberColumn("STL", format="%.1f"),
            "BLK": st.column_config.NumberColumn("BLK", format="%.1f"),
            "PF": st.column_config.NumberColumn("PF", format="%.1f"),
            "PFR": st.column_config.NumberColumn("PFR", format="%.1f"),
            "FG%": st.column_config.NumberColumn("FG%", format="%.1f%%"),
            "2P%": st.column_config.NumberColumn("2P%", format="%.1f%%"),
            "FT%": st.column_config.NumberColumn("FT%", format="%.1f%%"),
            "3P%": st.column_config.NumberColumn("3P%", format="%.1f%%")
        }
    )

    # ⚠️ CORRECTO USO DE VIEW_MODE
    # Guardar: solo actuar si hay selección Y no estamos ya en modo profile
    # (evita doble-rerun con on_select="rerun")
    if len(event.selection.rows) > 0 and st.session_state.get('view_mode') != 'profile':
        selected_row_idx = event.selection.rows[0]
        player_id_sel = df_page.iloc[selected_row_idx]['id_player']

        st.session_state['selected_player_id'] = player_id_sel
        st.session_state['view_mode'] = 'profile'
        st.rerun()

    c_p1, c_pi, c_p2 = st.columns([1, 2, 1])
    with c_p1:
        if st.session_state.page_number > 0:
            if st.button("⬅️ Anterior", key="prev_avg"):
                st.session_state.page_number -= 1
                st.rerun()
    with c_pi:
        if total_pages > 0:
            st.markdown(f"<div style='text-align: center'>Página <b>{st.session_state.page_number + 1}</b> de <b>{total_pages}</b></div>", unsafe_allow_html=True)
        else:
            st.warning("No hay jugadors que coincidan con los filtros.")
    with c_p2:
        if st.session_state.page_number < total_pages - 1:
            if st.button("Siguiente ➡️", key="next_basic"):
                st.session_state.page_number += 1
                st.rerun()
