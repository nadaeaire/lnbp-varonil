import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
import matplotlib
matplotlib.use('Agg')
from datetime import datetime

# --- IMPORTACIÓN DEL LOGGER ---
# Ajusta esto si tu función está en otro archivo o se llama distinto
try:
    from modules.utils import guardar_actividad
except ImportError:
    # Fallback silencioso por si no existe el módulo aún, para que no truene
    def guardar_actividad(accion, detalle): pass

# AHORA RECIBE id_jugador
def render_view(id_jugador, df_games, df_players, df_rosters, df_teams, df_tiros=None):
    
    # --- A. PREPARACIÓN DE DATOS BIO ---
    # Usamos el ID dinámico que viene de main.py
    pid_str = str(id_jugador)
    
    df_players['player_id_str'] = df_players['player_id'].astype(str)
    df_rosters['player_id_str'] = df_rosters['player_id'].astype(str)
    
    # Buscar Datos Personales
    player_data = df_players[df_players['player_id_str'] == pid_str]
    if player_data.empty:
        st.error(f"El jugador con ID {id_jugador} no existe en la base de datos.")
        return
    p_info = player_data.iloc[0]

    # Buscar Roster
    if 'effective_start_date' in df_rosters.columns:
        df_rosters['effective_start_date'] = pd.to_datetime(df_rosters['effective_start_date'], errors='coerce')
    
    roster_data = df_rosters[df_rosters['player_id_str'] == pid_str].sort_values('effective_start_date', ascending=False)
    
    equipo_nombre = "Sin Equipo"
    jersey = "?"
    posicion = "N/A"
    equipo_id_encontrado = None 
    
    if not roster_data.empty:
        r_info = roster_data.iloc[0]
        jersey = r_info.get('shirt_number', '?')
        posicion = r_info.get('playing_position', 'N/A')
        equipo_id_encontrado = r_info.get('equipo_id')

        # Cruce con Equipos
        if equipo_id_encontrado is not None and not df_teams.empty:
            if 'equipo_id' in df_teams.columns:
                df_teams['equipo_id_str'] = df_teams['equipo_id'].astype(str).str.strip()
                id_buscado = str(equipo_id_encontrado).strip()
                team_match = df_teams[df_teams['equipo_id_str'] == id_buscado]
                if not team_match.empty:
                    equipo_nombre = team_match.iloc[0].get('nombre', 'Nombre no encontrado')
                else:
                    equipo_nombre = f"ID {id_buscado} no hallado"

    # Datos físicos
    fecha_fmt = "N/A"
    edad = "N/A"
    if pd.notna(p_info.get('date_of_birth')):
        try:
            born = pd.to_datetime(p_info.get('date_of_birth'))
            fecha_fmt = born.strftime('%d/%m/%Y')
            today = datetime.now()
            edad = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        except: pass
            
    try:
        altura = int(float(p_info.get('height_cm', 0)))
        peso = int(float(p_info.get('weight_kg', 0)))
    except:
        altura, peso = 0, 0

    # --- PREPARACIÓN DE STATS ---
    if df_games.empty:
        df_active_games = pd.DataFrame()
        max_games = 0
    else:
        if 'id_player' in df_games.columns:
            df_games['id_player_str'] = df_games['id_player'].astype(str)
            df_player_stats = df_games[df_games['id_player_str'] == pid_str].copy()
            df_player_stats['sMinutes'] = pd.to_numeric(df_player_stats['sMinutes'], errors='coerce').fillna(0)
            df_active_games = df_player_stats[df_player_stats['sMinutes'] > 0].copy()
            
            if 'Fecha' in df_active_games.columns:
                 df_active_games['Fecha'] = pd.to_datetime(df_active_games['Fecha'], errors='coerce')
                 df_active_games = df_active_games.sort_values('Fecha', ascending=False)
            max_games = len(df_active_games)
        else:
            df_active_games = pd.DataFrame()
            max_games = 0

    # --- B. VISUALIZACIÓN ---
    st.title("Perfil individual")

    # --- CALLBACK PARA EL SLIDER (TRACKING) ---
    def on_slider_change():
        # Capturamos el valor nuevo del slider
        new_val = st.session_state["slider_perfil"]
        # Guardamos la actividad
        guardar_actividad("Interacción", f"Perfil Jugador - Filtro Slider: Últimos {new_val} juegos")

    col_vacia, col_slider = st.columns([1, 1])
    with col_vacia: st.write("") 
    with col_slider:
        if max_games > 1:
            games_window = st.slider(
                "Calcular últimos X juegos:", 
                min_value=1, 
                max_value=max_games, 
                value=max_games,
                key="slider_perfil",
                on_change=on_slider_change # <--- AQUÍ SE ACTIVA EL LOG
            )
        else:
            st.info("Datos disponibles limitados.")
            games_window = 1
    
    if not df_active_games.empty:
        df_filtered_games = df_active_games.head(games_window).copy()
    else:
        df_filtered_games = pd.DataFrame()

    nombre_completo = f"{p_info.get('first_name', '')} {p_info.get('family_name', '')}".strip()
    st.markdown(f"""
        <div style="line-height: 1;">
            <div style="margin-top: 0px; margin-bottom: 0px; padding-bottom: 5px; font-weight: bold; font-size: 40px;">
                #{jersey} - {nombre_completo} ({posicion})
            </div>
            <div style="margin-top: 0px; padding-top: 0px; color: #6f6f6f; font-weight: normal; font-size: 25px;">
                {equipo_nombre}
            </div>
        </div>
    """, unsafe_allow_html=True)

    st.divider()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Estatura", f"{altura} cm")
    c2.metric("Peso", f"{peso} kg")
    c3.metric("Fecha Nacimiento", fecha_fmt)
    c4.metric("Edad", str(edad))
    c5.metric("Nacionalidad", p_info.get('nationality', 'N/A'))
    st.divider()

    if df_filtered_games.empty:
        st.info("No hay datos de juego disponibles.")
        return

    # --- C. TABLA PROMEDIOS ---
    st.subheader(f"Estadísticas por partido")
    leaderboard = df_filtered_games.groupby(['id_player']).agg({
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

    def calc_pct(num, den): return np.divide(num, den, out=np.zeros_like(num, dtype=float), where=den!=0) * 100
    leaderboard['FG%'] = calc_pct(leaderboard['FGM'], leaderboard['FGA'])
    leaderboard['2P%'] = calc_pct(leaderboard['2PM'], leaderboard['2PA'])
    leaderboard['3P%'] = calc_pct(leaderboard['sThreePointersMade'], leaderboard['3PA'])
    leaderboard['FT%'] = calc_pct(leaderboard['FTM'], leaderboard['FTA'])

    cols_order = ["GP", "JT", "MPG", "FGM", "FGA", "FG%", "2PM", "2PA", "2P%", "3PM", "3PA", "3P%", "FTM", "FTA", "FT%", "RBO", "RBD", "sReboundsTotal", "sAssists", "TOV", "STL", "BLK", "PF", "PFR", "sPoints"]
    leaderboard['3PM'] = leaderboard['sThreePointersMade']
    cols_final = [c for c in cols_order if c in leaderboard.columns]

    st.dataframe(leaderboard[cols_final], hide_index=True, use_container_width=True, 
        column_config={
            "GP": st.column_config.NumberColumn("JJ", format="%d"), 
            "JT": st.column_config.NumberColumn("JT", format="%d"), 
            "MPG": st.column_config.NumberColumn("MIN", format="%.1f"), 
            "sPoints": st.column_config.NumberColumn("PTS", format="%.1f"), 
            "RBO": st.column_config.NumberColumn("RBO", format="%.1f"), 
            "RBD": st.column_config.NumberColumn("RBD", format="%.1f"), 
            "sReboundsTotal": st.column_config.NumberColumn("RBT", format="%.1f"), 
            "sAssists": st.column_config.NumberColumn("AST", format="%.1f"), 
            "FGM": st.column_config.NumberColumn("FGM", format="%.1f"), 
            "FGA": st.column_config.NumberColumn("FGA", format="%.1f"), 
            "2PM": st.column_config.NumberColumn("2PA", format="%.1f"), 
            "3PM": st.column_config.NumberColumn("3PM", format="%.1f"), 
            "3PA": st.column_config.NumberColumn("3PA", format="%.1f"), 
            "FTM": st.column_config.NumberColumn("FTM", format="%.1f"), 
            "FTA": st.column_config.NumberColumn("FTA", format="%.1f"), 
            "FG%": st.column_config.NumberColumn("FG%", format="%.1f%%"), 
            "2P%": st.column_config.NumberColumn("2P%", format="%.1f%%"), 
            "FT%": st.column_config.NumberColumn("FT%", format="%.1f%%"), 
            "3P%": st.column_config.NumberColumn("3P%", format="%.1f%%"), 
            "TOV": st.column_config.NumberColumn("TOV", format="%.1f"), 
            "STL": st.column_config.NumberColumn("STL", format="%.1f"), 
            "BLK": st.column_config.NumberColumn("BLK", format="%.1f"), 
            "PF": st.column_config.NumberColumn("PF", format="%.1f"), 
            "PFR": st.column_config.NumberColumn("PFR", format="%.1f")
            })

    # --- D. TABLA PER28 ---
    st.subheader("Estadísticas PER28")
    _p28_totals = df_filtered_games.groupby(['id_player']).agg({
        'sMinutes': 'sum', 'starter': 'sum', 'id_abe': 'count',
        'sPoints': 'sum', 'sReboundsTotal': 'sum', 'sReboundsOffensive': 'sum',
        'sReboundsDefensive': 'sum', 'sAssists': 'sum', 'sTurnovers': 'sum',
        'sSteals': 'sum', 'sBlocks': 'sum', 'sFoulsPersonal': 'sum', 'sFoulsOn': 'sum',
        'sFieldGoalsMade': 'sum', 'sFieldGoalsAttempted': 'sum',
        'sTwoPointersMade': 'sum', 'sTwoPointersAttempted': 'sum',
        'sThreePointersMade': 'sum', 'sThreePointersAttempted': 'sum',
        'sFreeThrowsMade': 'sum', 'sFreeThrowsAttempted': 'sum',
    }).reset_index()
    _mpg = df_filtered_games.groupby('id_player')['sMinutes'].mean()
    _p28_totals['MPG'] = _p28_totals['id_player'].map(_mpg)
    _p28_totals.rename(columns={'id_abe': 'GP', 'starter': 'JT'}, inplace=True)

    if not _p28_totals.empty:
        _tm = _p28_totals['sMinutes'].replace(0, np.nan)
        def _p28(s): return (s / _tm * 28).round(2)

        _p28_totals['FG%'] = np.where(_p28_totals['sFieldGoalsAttempted']   > 0, _p28_totals['sFieldGoalsMade']    / _p28_totals['sFieldGoalsAttempted']   * 100, 0.0)
        _p28_totals['2P%'] = np.where(_p28_totals['sTwoPointersAttempted']   > 0, _p28_totals['sTwoPointersMade']   / _p28_totals['sTwoPointersAttempted']   * 100, 0.0)
        _p28_totals['3P%'] = np.where(_p28_totals['sThreePointersAttempted'] > 0, _p28_totals['sThreePointersMade'] / _p28_totals['sThreePointersAttempted'] * 100, 0.0)
        _p28_totals['FT%'] = np.where(_p28_totals['sFreeThrowsAttempted']    > 0, _p28_totals['sFreeThrowsMade']    / _p28_totals['sFreeThrowsAttempted']    * 100, 0.0)

        _p28_totals['PTS'] = _p28(_p28_totals['sPoints'])
        _p28_totals['RBT'] = _p28(_p28_totals['sReboundsTotal'])
        _p28_totals['RBO'] = _p28(_p28_totals['sReboundsOffensive'])
        _p28_totals['RBD'] = _p28(_p28_totals['sReboundsDefensive'])
        _p28_totals['AST'] = _p28(_p28_totals['sAssists'])
        _p28_totals['TOV'] = _p28(_p28_totals['sTurnovers'])
        _p28_totals['STL'] = _p28(_p28_totals['sSteals'])
        _p28_totals['BLK'] = _p28(_p28_totals['sBlocks'])
        _p28_totals['PF']  = _p28(_p28_totals['sFoulsPersonal'])
        _p28_totals['PFR'] = _p28(_p28_totals['sFoulsOn'])
        _p28_totals['FGM'] = _p28(_p28_totals['sFieldGoalsMade'])
        _p28_totals['FGA'] = _p28(_p28_totals['sFieldGoalsAttempted'])
        _p28_totals['2PM'] = _p28(_p28_totals['sTwoPointersMade'])
        _p28_totals['2PA'] = _p28(_p28_totals['sTwoPointersAttempted'])
        _p28_totals['3PM'] = _p28(_p28_totals['sThreePointersMade'])
        _p28_totals['3PA'] = _p28(_p28_totals['sThreePointersAttempted'])
        _p28_totals['FTM'] = _p28(_p28_totals['sFreeThrowsMade'])
        _p28_totals['FTA'] = _p28(_p28_totals['sFreeThrowsAttempted'])

        _p28_cols = ["GP", "JT", "MPG", "FGM", "FGA", "FG%", "2PM", "2PA", "2P%",
                     "3PM", "3PA", "3P%", "FTM", "FTA", "FT%",
                     "RBO", "RBD", "RBT", "AST", "TOV", "STL", "BLK", "PF", "PFR", "PTS"]
        _p28_show = [c for c in _p28_cols if c in _p28_totals.columns]
        st.dataframe(_p28_totals[_p28_show], hide_index=True, use_container_width=True,
            column_config={
                "GP":  st.column_config.NumberColumn("JJ",  format="%d"),
                "JT":  st.column_config.NumberColumn("JT",  format="%d"),
                "MPG": st.column_config.NumberColumn("MIN", format="%.1f"),
                "PTS": st.column_config.NumberColumn("PTS", format="%.1f"),
                "RBT": st.column_config.NumberColumn("RBT", format="%.1f"),
                "RBO": st.column_config.NumberColumn("RBO", format="%.1f"),
                "RBD": st.column_config.NumberColumn("RBD", format="%.1f"),
                "AST": st.column_config.NumberColumn("AST", format="%.1f"),
                "TOV": st.column_config.NumberColumn("TOV", format="%.1f"),
                "STL": st.column_config.NumberColumn("STL", format="%.1f"),
                "BLK": st.column_config.NumberColumn("BLK", format="%.1f"),
                "PF":  st.column_config.NumberColumn("PF",  format="%.1f"),
                "PFR": st.column_config.NumberColumn("PFR", format="%.1f"),
                "FGM": st.column_config.NumberColumn("FGM", format="%.1f"),
                "FGA": st.column_config.NumberColumn("FGA", format="%.1f"),
                "2PM": st.column_config.NumberColumn("2PM", format="%.1f"),
                "2PA": st.column_config.NumberColumn("2PA", format="%.1f"),
                "3PM": st.column_config.NumberColumn("3PM", format="%.1f"),
                "3PA": st.column_config.NumberColumn("3PA", format="%.1f"),
                "FTM": st.column_config.NumberColumn("FTM", format="%.1f"),
                "FTA": st.column_config.NumberColumn("FTA", format="%.1f"),
                "FG%": st.column_config.NumberColumn("FG%", format="%.1f%%"),
                "2P%": st.column_config.NumberColumn("2P%", format="%.1f%%"),
                "3P%": st.column_config.NumberColumn("3P%", format="%.1f%%"),
                "FT%": st.column_config.NumberColumn("FT%", format="%.1f%%"),
            })

    # --- E. TABLA AVANZADAS (FIJA) ---
    st.subheader("Estadísticas avanzadas")
    totals = df_filtered_games.groupby(['id_player']).agg({
        'id_abe': 'count', 'sMinutes': 'sum', 'sPoints': 'sum', 'sFieldGoalsMade': 'sum', 'sFieldGoalsAttempted': 'sum', 'sThreePointersMade': 'sum', 'sTwoPointersMade': 'sum', 'sFreeThrowsMade': 'sum', 'sFreeThrowsAttempted': 'sum', 'sReboundsOffensive': 'sum', 'sReboundsDefensive': 'sum', 'sReboundsTotal': 'sum', 'sAssists': 'sum', 'sTurnovers': 'sum', 'sSteals': 'sum', 'sBlocks': 'sum', 'sFoulsPersonal': 'sum',
        'Tm_FGA': 'sum', 'Tm_FTA': 'sum', 'Tm_TOV': 'sum', 'Tm_MIN': 'sum', 'Tm_FG': 'sum', 'Tm_ORB': 'sum', 'Tm_DRB': 'sum', 'Tm_TRB': 'sum', 'Tm_AST': 'sum', 'Tm_STL': 'sum', 'Tm_BLK': 'sum', 'Tm_3PM': 'sum', 'Tm_FTM': 'sum', 'Tm_2PM': 'sum', 'Tm_3PA': 'sum', 'Tm_PF': 'sum',
        'Opp_DRB': 'sum', 'Opp_ORB': 'sum', 'Opp_TRB': 'sum', 'Opp_FGA': 'sum', 'Opp_FG': 'sum', 'Opp_3PA': 'sum', 'Opp_3PM': 'sum', 'Opp_PF': 'sum', 'Opp_FTA': 'sum', 'Opp_FTM': 'sum', 'Opp_TOV': 'sum', 'Opp_MIN': 'sum'
    }).reset_index()

    if not totals.empty:
        totals['eFG%'] = np.divide((totals['sFieldGoalsMade'] + 0.5 * totals['sThreePointersMade']), totals['sFieldGoalsAttempted'], out=np.zeros_like(totals['sFieldGoalsMade'], dtype=float), where=totals['sFieldGoalsAttempted']!=0) * 100
        tsa = 2 * (totals['sFieldGoalsAttempted'] + 0.44 * totals['sFreeThrowsAttempted'])
        totals['TS%'] = np.divide(totals['sPoints'], tsa, out=np.zeros_like(totals['sPoints'], dtype=float), where=tsa!=0) * 100
        pp_shot = (totals['sTwoPointersMade'] * 2) + (totals['sThreePointersMade'] * 3)
        totals['PtsXShot'] = np.divide(pp_shot, totals['sFieldGoalsAttempted'], out=np.zeros_like(pp_shot, dtype=float), where=totals['sFieldGoalsAttempted']!=0)
        
        usg_den = totals['sMinutes'] * (totals['Tm_FGA'] + 0.44 * totals['Tm_FTA'] + totals['Tm_TOV'])
        usg_num = (totals['sFieldGoalsAttempted'] + 0.44 * totals['sFreeThrowsAttempted'] + totals['sTurnovers']) * (totals['Tm_MIN'] / 5)
        totals['USG%'] = np.divide(usg_num, usg_den, out=np.zeros_like(usg_num, dtype=float), where=usg_den!=0) * 100

        cols_blindaje = ['USG%', 'TS%', 'eFG%', 'PtsXShot']
        for c in cols_blindaje:
            if c not in totals.columns: totals[c] = 0.0
        
        totals[cols_blindaje] = totals[cols_blindaje].fillna(0.0)
        
        st.dataframe(totals[cols_blindaje], hide_index=True, use_container_width=True, 
            column_config={"USG%": st.column_config.NumberColumn("USG%", format="%.1f%%"), "TS%": st.column_config.NumberColumn("TS%", format="%.1f%%"), "eFG%": st.column_config.NumberColumn("eFG%", format="%.1f%%"), "PtsXShot": st.column_config.NumberColumn("PPS", format="%.2f")})
    
    st.markdown("""<div style="line-height: 1.5; margin-top: -8px; font-size: 15px; color: #aaa; font-style: italic;">
        <div>USG% (Usage Rate) = Estimado de jugadas usadas</div>
        <div>TS% (True Shooting) = Eficiencia de anotación</div>
        <div>eFG% (Effective FG) = Eficiencia de tiro</div>
        <div>PtsXShot = Puntos por tiro</div></div>""", unsafe_allow_html=True)
    st.divider()

    # --- NAVEGACIÓN PERSONALIZADA (CON TRACKING) ---
    if 'active_tab_player' not in st.session_state:
        st.session_state.active_tab_player = "Game Log"

    _rol = st.session_state.get("user_role", "basic")
    _shot_tab = (_rol == "all")

    # Si el usuario no tiene acceso a tiros y estaba en ShotChart, redirigir
    if not _shot_tab and st.session_state.active_tab_player == "ShotChart":
        st.session_state.active_tab_player = "Game Log"

    if _shot_tab:
        c_t1, c_t2, c_t3 = st.columns(3)
    else:
        c_t1, c_t2 = st.columns(2)
        c_t3 = None

    with c_t1:
        type_btn1 = "primary" if st.session_state.active_tab_player == "Game Log" else "secondary"
        if st.button("📝 Game Log", key="btn_tab_log", use_container_width=True, type=type_btn1):
            guardar_actividad("Navegación", "Perfil Jugador - Click Pestaña Game Log")
            st.session_state.active_tab_player = "Game Log"
            st.rerun()
    with c_t2:
        type_btn2 = "primary" if st.session_state.active_tab_player == "Trends" else "secondary"
        if st.button("📈 Trends", key="btn_tab_trends", use_container_width=True, type=type_btn2):
            guardar_actividad("Navegación", "Perfil Jugador - Click Pestaña Trends")
            st.session_state.active_tab_player = "Trends"
            st.rerun()
    if c_t3 is not None:
        with c_t3:
            type_btn3 = "primary" if st.session_state.active_tab_player == "ShotChart" else "secondary"
            if st.button("🎯 Mapa de Tiros Beta", key="btn_tab_shotchart", use_container_width=True, type=type_btn3):
                guardar_actividad("Navegación", "Perfil Jugador - Click Pestaña Mapa de Tiro")
                st.session_state.active_tab_player = "ShotChart"
                st.rerun()

    #st.markdown("---")

    # ------------------------------------------------
    # PESTAÑA 1: GAME LOG
    # ------------------------------------------------
    if st.session_state.active_tab_player == "Game Log":
        st.subheader("Game Log")

        col_rival_final = "Opp_Name"
        if col_rival_final in df_filtered_games.columns:
            df_filtered_games[col_rival_final] = df_filtered_games[col_rival_final].astype(str).replace(['0', '0.0', 'nan', 'None'], '-')
        else:
            df_filtered_games[col_rival_final] = "-"

        # EMOJIS VICTORIA/DERROTA
        if 'Tm_Score' in df_filtered_games.columns and 'Opp_Score' in df_filtered_games.columns:
            s_tm = pd.to_numeric(df_filtered_games['Tm_Score'], errors='coerce').fillna(0)
            s_opp = pd.to_numeric(df_filtered_games['Opp_Score'], errors='coerce').fillna(0)
            condiciones = [s_tm > s_opp, s_tm < s_opp]
            elecciones = ['✅ ', '❌ ']
            emojis = np.select(condiciones, elecciones, default='➖ ')
            df_filtered_games[col_rival_final] = emojis + df_filtered_games[col_rival_final]

        # CÁLCULOS FILA POR FILA (NUMÉRICOS PRIMERO)
        if 'sFieldGoalsAttempted' in df_filtered_games.columns:
            df_filtered_games['FG%_val'] = np.where(df_filtered_games['sFieldGoalsAttempted'] > 0, (df_filtered_games['sFieldGoalsMade'] / df_filtered_games['sFieldGoalsAttempted']) * 100, 0.0)
        
        if 'sThreePointersAttempted' in df_filtered_games.columns:
            df_filtered_games['3P%_val'] = np.where(df_filtered_games['sThreePointersAttempted'] > 0, (df_filtered_games['sThreePointersMade'] / df_filtered_games['sThreePointersAttempted']) * 100, 0.0)

        if 'sFreeThrowsAttempted' in df_filtered_games.columns:
            df_filtered_games['FT%_val'] = np.where(df_filtered_games['sFreeThrowsAttempted'] > 0, (df_filtered_games['sFreeThrowsMade'] / df_filtered_games['sFreeThrowsAttempted']) * 100, 0.0)

        if 'sFieldGoalsAttempted' in df_filtered_games.columns:
            num_efg = df_filtered_games['sFieldGoalsMade'] + 0.5 * df_filtered_games['sThreePointersMade']
            den_efg = df_filtered_games['sFieldGoalsAttempted']
            df_filtered_games['eFG%_val'] = np.divide(num_efg, den_efg, out=np.zeros_like(num_efg, dtype=float), where=den_efg!=0) * 100

        if 'sPoints' in df_filtered_games.columns:
            tsa = 2 * (df_filtered_games['sFieldGoalsAttempted'] + 0.44 * df_filtered_games['sFreeThrowsAttempted'])
            df_filtered_games['TS%_val'] = np.divide(df_filtered_games['sPoints'], tsa, out=np.zeros_like(tsa, dtype=float), where=tsa!=0) * 100

        if 'sFieldGoalsAttempted' in df_filtered_games.columns:
            pts_shots = (df_filtered_games['sTwoPointersMade'] * 2) + (df_filtered_games['sThreePointersMade'] * 3)
            den_pps = df_filtered_games['sFieldGoalsAttempted']
            df_filtered_games['PPS_val'] = np.divide(pts_shots, den_pps, out=np.zeros_like(den_pps, dtype=float), where=den_pps!=0)

        tm_cols = ['Tm_FGA', 'Tm_FTA', 'Tm_TOV', 'Tm_MIN']
        if all(col in df_filtered_games.columns for col in tm_cols):
            usg_num = (df_filtered_games['sFieldGoalsAttempted'] + 0.44 * df_filtered_games['sFreeThrowsAttempted'] + df_filtered_games['sTurnovers']) * (df_filtered_games['Tm_MIN'] / 5)
            usg_den = df_filtered_games['sMinutes'] * (df_filtered_games['Tm_FGA'] + 0.44 * df_filtered_games['Tm_FTA'] + df_filtered_games['Tm_TOV'])
            df_filtered_games['USG%_val'] = np.divide(usg_num, usg_den, out=np.zeros_like(usg_num, dtype=float), where=usg_den!=0) * 100
        else:
            df_filtered_games['USG%_val'] = 0.0

        # FORMATEO VISUAL (STRING)
        def format_pct(made, att): return f"{(made/att)*100:.1f}%" if att > 0 else "-"
        
        df_filtered_games['FG%'] = df_filtered_games.apply(lambda x: format_pct(x.get('sFieldGoalsMade',0), x.get('sFieldGoalsAttempted',0)), axis=1)
        df_filtered_games['3P%'] = df_filtered_games.apply(lambda x: format_pct(x.get('sThreePointersMade',0), x.get('sThreePointersAttempted',0)), axis=1)
        df_filtered_games['FT%'] = df_filtered_games.apply(lambda x: format_pct(x.get('sFreeThrowsMade',0), x.get('sFreeThrowsAttempted',0)), axis=1)
        df_filtered_games['eFG%'] = df_filtered_games.apply(lambda x: f"{x['eFG%_val']:.1f}%" if x['sFieldGoalsAttempted'] > 0 else "-", axis=1)
        df_filtered_games['TS%'] = df_filtered_games.apply(lambda x: f"{x['TS%_val']:.1f}%" if (x['sFieldGoalsAttempted'] > 0 or x['sFreeThrowsAttempted'] > 0) else "-", axis=1)
        df_filtered_games['PPS'] = df_filtered_games.apply(lambda x: f"{x['PPS_val']:.2f}" if x['sFieldGoalsAttempted'] > 0 else "-", axis=1)
        df_filtered_games['USG%'] = df_filtered_games.apply(lambda x: f"{x['USG%_val']:.1f}%" if x['sMinutes'] > 0 else "-", axis=1)

        cols_log = [
            "Fecha", col_rival_final, "sMinutes", "sPoints", "USG%", "TS%", "eFG%", "PPS",
            "sFieldGoalsMade", "sFieldGoalsAttempted", "FG%",
            "sThreePointersMade", "sThreePointersAttempted", "3P%",
            "sFreeThrowsMade", "sFreeThrowsAttempted", "FT%",
            "sReboundsOffensive", "sReboundsDefensive", "sReboundsTotal", "sAssists", "sSteals", "sBlocks", "sTurnovers", "sFoulsPersonal"
        ]
        cols_final_log = [c for c in cols_log if c in df_filtered_games.columns]
        
        # ESTILO NEGRITAS
        col_map = {c: c for c in cols_final_log if c not in ["Fecha", col_rival_final]}
        custom_map = { "FG%": "FG%_val", "3P%": "3P%_val", "FT%": "FT%_val", "eFG%": "eFG%_val", "TS%": "TS%_val", "USG%": "USG%_val", "PPS": "PPS_val" }
        col_map.update(custom_map)

        def highlight_season_highs(df):
            styles = pd.DataFrame('', index=df.index, columns=df.columns)
            for vis_col, num_col in col_map.items():
                if vis_col in df.columns and num_col in df.columns:
                    max_val = df[num_col].max()
                    if max_val > 0:
                        is_max = df[num_col] == max_val
                        styles.loc[is_max, vis_col] = 'font-weight: 900; color: #000;'
            return styles

        styled_df = df_filtered_games.style.apply(highlight_season_highs, axis=None)

        st.dataframe(styled_df, column_order=cols_final_log, hide_index=True, use_container_width=True, height=((len(df_filtered_games)+1)*35)+3,
            column_config={
                "Fecha": st.column_config.DateColumn("Fecha", format="DD/MM/YYYY"), 
                col_rival_final: st.column_config.TextColumn("Rival"), 
                "sMinutes": st.column_config.NumberColumn("MIN", format="%.0f"),
                "sPoints": st.column_config.NumberColumn("PTS", format="%d"),
                "sReboundsTotal": st.column_config.NumberColumn("REBT", format="%d"),
                "sAssists": st.column_config.NumberColumn("AST", format="%d"),
                "sSteals": st.column_config.NumberColumn("STL", format="%d"),
                "sBlocks": st.column_config.NumberColumn("BLK", format="%d"),
                "sTurnovers": st.column_config.NumberColumn("TOV", format="%d"),
                "sFieldGoalsMade": st.column_config.NumberColumn("FGM", format="%d"),
                "sFieldGoalsAttempted": st.column_config.NumberColumn("FGA", format="%d"),
                "sThreePointersMade": st.column_config.NumberColumn("3PM", format="%d"),
                "sThreePointersAttempted": st.column_config.NumberColumn("3PA", format="%d"),
                "sFreeThrowsMade": st.column_config.NumberColumn("FTM", format="%d"),
                "sFreeThrowsAttempted": st.column_config.NumberColumn("FTA", format="%d"),
                "sReboundsOffensive": st.column_config.NumberColumn("REBO", format="%d"),
                "sReboundsDefensive": st.column_config.NumberColumn("REBD", format="%d"),
                "sFoulsPersonal": st.column_config.NumberColumn("PF", format="%d"),
                "FG%": st.column_config.TextColumn("FG%"), "3P%": st.column_config.TextColumn("3P%"), "FT%": st.column_config.TextColumn("FT%"), "USG%": st.column_config.TextColumn("USG%"), "TS%": st.column_config.TextColumn("TS%"), "eFG%": st.column_config.TextColumn("eFG%"), "PPS": st.column_config.TextColumn("PPS")
            })

    # ------------------------------------------------
    # PESTAÑA 2: TRENDS TIRO Y EFICIENCIAS
    # ------------------------------------------------
    elif st.session_state.active_tab_player == "Trends":
        st.subheader("Tendencias de Eficiencia")
        
        # 1. Preparar data ASCENDENTE
        df_trends = df_filtered_games.sort_values('Fecha', ascending=True).copy()
        
        # Calcular 2P% (Faltaba)
        if 'sTwoPointersAttempted' in df_trends.columns:
            df_trends['2P%_val'] = np.where(df_trends['sTwoPointersAttempted'] > 0, 
                                            (df_trends['sTwoPointersMade'] / df_trends['sTwoPointersAttempted']) * 100, 
                                            0.0)
        else:
            df_trends['2P%_val'] = 0.0

        # Recalcular valores si no existen (copia de seguridad)
        if 'sFieldGoalsAttempted' in df_trends.columns:
            df_trends['FG%_val'] = np.where(df_trends['sFieldGoalsAttempted'] > 0, (df_trends['sFieldGoalsMade'] / df_trends['sFieldGoalsAttempted']) * 100, 0.0)
            num_efg = df_trends['sFieldGoalsMade'] + 0.5 * df_trends['sThreePointersMade']
            df_trends['eFG%_val'] = np.divide(num_efg, df_trends['sFieldGoalsAttempted'], out=np.zeros_like(num_efg, dtype=float), where=df_trends['sFieldGoalsAttempted']!=0) * 100

        if 'sThreePointersAttempted' in df_trends.columns:
            df_trends['3P%_val'] = np.where(df_trends['sThreePointersAttempted'] > 0, (df_trends['sThreePointersMade'] / df_trends['sThreePointersAttempted']) * 100, 0.0)

        if 'sFreeThrowsAttempted' in df_trends.columns:
            df_trends['FT%_val'] = np.where(df_trends['sFreeThrowsAttempted'] > 0, (df_trends['sFreeThrowsMade'] / df_trends['sFreeThrowsAttempted']) * 100, 0.0)

        if 'sPoints' in df_trends.columns:
            tsa = 2 * (df_trends['sFieldGoalsAttempted'] + 0.44 * df_trends['sFreeThrowsAttempted'])
            df_trends['TS%_val'] = np.divide(df_trends['sPoints'], tsa, out=np.zeros_like(tsa, dtype=float), where=tsa!=0) * 100

        if all(col in df_trends.columns for col in ['Tm_FGA', 'Tm_FTA', 'Tm_TOV', 'Tm_MIN']):
            usg_num = (df_trends['sFieldGoalsAttempted'] + 0.44 * df_trends['sFreeThrowsAttempted'] + df_trends['sTurnovers']) * (df_trends['Tm_MIN'] / 5)
            usg_den = df_trends['sMinutes'] * (df_trends['Tm_FGA'] + 0.44 * df_trends['Tm_FTA'] + df_trends['Tm_TOV'])
            df_trends['USG%_val'] = np.divide(usg_num, usg_den, out=np.zeros_like(usg_num, dtype=float), where=usg_den!=0) * 100
        else:
            df_trends['USG%_val'] = 0.0

        # Construir dataframe de gráfica
        df_trends['Fecha_Str'] = df_trends['Fecha'].dt.strftime('%d/%m/%y')
        chart_data = pd.DataFrame()
        chart_data['Fecha'] = df_trends['Fecha_Str']
        
        col_rival_clean = "Opp_Name"
        if col_rival_clean in df_trends.columns:
             chart_data['Rival'] = df_trends[col_rival_clean]
        else:
             chart_data['Rival'] = "-"

        metrics_map = {
            "FG%": "FG%_val",
            "2P%": "2P%_val",
            "3P%": "3P%_val",
            "FT%": "FT%_val",
            "eFG%": "eFG%_val",
            "TS%": "TS%_val",
            "USG%": "USG%_val"
        }
        
        for label, col_val in metrics_map.items():
            if col_val in df_trends.columns:
                chart_data[label] = df_trends[col_val]
            else:
                chart_data[label] = 0.0
                
        all_metrics = list(metrics_map.keys())
        selected_metrics = st.multiselect("Seleccionar métricas a visualizar:", all_metrics, default=all_metrics, key="multiselect_trends")
        
        if selected_metrics:
            # Transformar para Altair
            data_long = chart_data.melt(['Fecha', 'Rival'], value_vars=selected_metrics, var_name='Métricas', value_name='Valor')

            # Etiqueta para el tooltip (con %)
            def format_tool(row): return f"{row['Valor']:.1f}%"
            data_long['Etiqueta'] = data_long.apply(format_tool, axis=1)

            # Chart con leyenda abajo y sin interacción (ZOOM OFF)
            chart = alt.Chart(data_long).mark_line(point=True).encode(
                x=alt.X('Fecha', sort=None, title='Fecha'),
                y=alt.Y('Valor', title='Porcentaje'),
                color=alt.Color('Métricas', title='Métricas', legend=alt.Legend(orient='bottom')),
                tooltip=[
                    alt.Tooltip('Fecha', title='📅 Fecha'),
                    alt.Tooltip('Rival', title='🆚 Rival'),
                    alt.Tooltip('Métricas', title='📊 Métricas'),
                    alt.Tooltip('Etiqueta', title='📈 Valor')
                ]
            ).properties(height=600) # Sin interactive()

            st.altair_chart(chart, use_container_width=True)
        else:
            st.info("Selecciona al menos una métrica para visualizar.")

    # ------------------------------------------------
    # PESTAÑA 3: MAPA DE TIRO
    # ------------------------------------------------
    elif st.session_state.active_tab_player == "ShotChart":
        from modules.shot_chart import normalizar_tiros, generar_shot_chart_zonas, generar_shot_chart_scatter

        st.subheader("Mapa de Tiros Beta")

        if df_tiros is None or df_tiros.empty:
            st.info("No hay datos de tiros disponibles.")
        else:
            # Limpiar player_id: dropear nulls y asegurar tipo numérico
            df_tiros_clean = df_tiros.dropna(subset=['player_id']).copy()
            df_tiros_clean['player_id'] = pd.to_numeric(df_tiros_clean['player_id'], errors='coerce')
            df_tiros_clean = df_tiros_clean.dropna(subset=['player_id'])

            # Filtrar tiros por categoría del jugador (via equipo_id → competicion_id)
            if equipo_id_encontrado is not None and 'competicion_id' in df_teams.columns:
                team_row = df_teams[df_teams['equipo_id'].astype(str) == str(equipo_id_encontrado).strip()]
                if not team_row.empty:
                    comp_id = str(team_row.iloc[0]['competicion_id'])
                    # IDs de equipos de la misma categoría
                    equipos_misma_cat = df_teams[df_teams['competicion_id'].astype(str) == comp_id]['equipo_id'].astype(int).tolist()
                    df_tiros_clean = df_tiros_clean[df_tiros_clean['equipo_id'].isin(equipos_misma_cat)]

            pid_num = int(id_jugador)
            df_player_shots = df_tiros_clean[df_tiros_clean['player_id'] == pid_num].copy()

            if df_player_shots.empty:
                st.info("Este jugador no tiene tiros registrados.")
            else:
                # Normalizar coordenadas
                df_player_shots = normalizar_tiros(df_player_shots)
                df_player_shots = df_player_shots[df_player_shots['court_y'] <= 12.0]

                n_tiros = len(df_player_shots)

                # Resumen con rankings (vs jugadores de la misma categoría)
                df_cat_norm = normalizar_tiros(df_tiros_clean.copy())
                df_cat_norm = df_cat_norm[df_cat_norm['court_y'] <= 12.0]

                vol_by_player = df_cat_norm.groupby('player_id').agg(
                    total=('r', 'count'),
                    total_2pt=('actiontype', lambda x: (x == '2pt').sum()),
                    total_3pt=('actiontype', lambda x: (x == '3pt').sum()),
                ).reset_index()
                n_jugadores = len(vol_by_player)

                vol_by_player['rank_total'] = vol_by_player['total'].rank(ascending=False, method='min').astype(int)
                vol_by_player['rank_2pt'] = vol_by_player['total_2pt'].rank(ascending=False, method='min').astype(int)
                vol_by_player['rank_3pt'] = vol_by_player['total_3pt'].rank(ascending=False, method='min').astype(int)

                pl_vol = vol_by_player[vol_by_player['player_id'] == pid_num]

                df_2pt = df_player_shots[df_player_shots['actiontype'] == '2pt'] if 'actiontype' in df_player_shots.columns else pd.DataFrame()
                df_3pt = df_player_shots[df_player_shots['actiontype'] == '3pt'] if 'actiontype' in df_player_shots.columns else pd.DataFrame()

                n_2pt = len(df_2pt)
                n_3pt = len(df_3pt)
                made_2pt = int(df_2pt['r'].sum()) if n_2pt > 0 else 0
                made_3pt = int(df_3pt['r'].sum()) if n_3pt > 0 else 0
                made_total = made_2pt + made_3pt
                pct_total = (made_total / n_tiros * 100) if n_tiros > 0 else 0
                pct_2pt = (made_2pt / n_2pt * 100) if n_2pt > 0 else 0
                pct_3pt = (made_3pt / n_3pt * 100) if n_3pt > 0 else 0

                c1, c2, c3 = st.columns(3)
                if not pl_vol.empty:
                    pv = pl_vol.iloc[0]
                    with c1:
                        st.metric("Total tiros", f"{made_total}/{n_tiros}  ({pct_total:.1f}%)",
                                  f"#{int(pv['rank_total'])} de {n_jugadores}", delta_color="off")
                    with c2:
                        st.metric("Dobles (2PT)", f"{made_2pt}/{n_2pt}  ({pct_2pt:.1f}%)",
                                  f"#{int(pv['rank_2pt'])} de {n_jugadores}", delta_color="off")
                    with c3:
                        st.metric("Triples (3PT)", f"{made_3pt}/{n_3pt}  ({pct_3pt:.1f}%)",
                                  f"#{int(pv['rank_3pt'])} de {n_jugadores}", delta_color="off")
                else:
                    with c1:
                        st.metric("Total tiros", f"{made_total}/{n_tiros}  ({pct_total:.1f}%)")
                    with c2:
                        st.metric("Dobles (2PT)", f"{made_2pt}/{n_2pt}  ({pct_2pt:.1f}%)")
                    with c3:
                        st.metric("Triples (3PT)", f"{made_3pt}/{n_3pt}  ({pct_3pt:.1f}%)")

                if n_tiros < 3:
                    st.info(f"Solo {n_tiros} tiros registrados. Se necesitan al menos 3 para generar el mapa.")
                else:
                    st.divider()

                    # Benchmark: jugadores de la misma categoría (excluyendo al actual)
                    df_liga = df_cat_norm[df_cat_norm['player_id'] != pid_num].copy()

                    # Dos gráficas: zonas + scatter
                    col_zonas, col_scatter = st.columns(2)

                    with col_zonas:
                        st.caption("**Zonas** — FG% vs promedio de categoría (rojo = arriba, azul = abajo)")
                        fig_zonas = generar_shot_chart_zonas(
                            df_player_shots, titulo=nombre_completo, df_liga=df_liga
                        )
                        st.pyplot(fig_zonas, use_container_width=True)

                    with col_scatter:
                        st.caption("**Marca de tiros** — Anotados / Fallados")
                        fig_scatter = generar_shot_chart_scatter(
                            df_player_shots, titulo=nombre_completo
                        )
                        st.pyplot(fig_scatter, use_container_width=True)