import streamlit as st
import pandas as pd
import numpy as np
import math
import modules.utils as utils

def render_view(df, df_players, df_rosters, categoria_sel):
    st.title(f"Advanced Stats | {categoria_sel}")

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

    col_team_sel, col_games_slider = st.columns([1, 1])
    with col_team_sel:
        if 'adv_equipo' not in st.session_state:
            st.session_state.adv_equipo = "Todos"
        _idx_eq = lista_equipos.index(st.session_state.adv_equipo) if st.session_state.adv_equipo in lista_equipos else 0
        equipo_filtro = st.selectbox("Filtrar por Equipo:", lista_equipos, index=_idx_eq, key="adv_team")
        st.session_state.adv_equipo = equipo_filtro
        utils.rastrear_cambio("Filtro Equipo (Adv)", equipo_filtro) 
    with col_games_slider:
        if max_games_found > 1:
            games_window = st.slider("Calcular durante los últimos X juegos:", 1, max_games_found, max_games_found, key="adv_slider")
        else:
            st.info("Mostrando datos disponibles.")
            games_window = 1
        utils.rastrear_cambio("Slider Juegos (Adv)", games_window) 

    # --- DATOS DE CONTEXTO ---
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

    # --- 2. FILTRADO DATA ---
    if equipo_filtro != "Todos":
        df_view = df[df['equipo_nombre'] == equipo_filtro]
    else:
        df_view = df

    df_active_games = df_view[df_view['sMinutes'] > 0].copy()
    
    if games_window < max_games_found:
        df_active_games = df_active_games.sort_values(by='Fecha', ascending=False)
        df_active_games = df_active_games.groupby('id_player').head(games_window)
        st.toast(f"Métricas basadas en los últimos {games_window} juegos.", icon="🛸")

    if games_window < max_games_found:
        threshold_games = math.ceil(games_window * 0.40)
    else:
        if equipo_filtro != "Todos":
             base_games = df_view.groupby('equipo_nombre')['id_abe'].nunique().max()
        else:
             base_games = df_view.groupby('equipo_nombre')['id_abe'].nunique().min()
        if pd.isna(base_games): base_games = 1
        threshold_games = math.ceil(base_games * 0.50)

    # --- 3. AGRUPACIÓN TOTALES ---
    totals = df_active_games.groupby(['id_player', 'Nombre', 'equipo_nombre']).agg({
        'id_abe': 'count', 'sMinutes': 'sum', 'starter': 'sum',
        'sPoints': 'sum', 'sFieldGoalsMade': 'sum', 'sFieldGoalsAttempted': 'sum',
        'sThreePointersMade': 'sum', 'sTwoPointersMade': 'sum',
        'sFreeThrowsMade': 'sum', 'sFreeThrowsAttempted': 'sum',
        'sReboundsOffensive': 'sum', 'sReboundsDefensive': 'sum', 'sReboundsTotal': 'sum',
        'sAssists': 'sum', 'sTurnovers': 'sum', 'sSteals': 'sum', 'sBlocks': 'sum',
        'sFoulsPersonal': 'sum',
        'Tm_FGA': 'sum', 'Tm_FTA': 'sum', 'Tm_TOV': 'sum', 'Tm_MIN': 'sum',
        'Tm_FG': 'sum', 'Tm_ORB': 'sum', 'Tm_DRB': 'sum', 'Tm_TRB': 'sum',
        'Tm_AST': 'sum', 'Tm_STL': 'sum', 'Tm_BLK': 'sum', 'Tm_3PM': 'sum',
        'Tm_FTM': 'sum', 'Tm_2PM': 'sum', 'Tm_3PA': 'sum', 'Tm_PF': 'sum',
        'Opp_DRB': 'sum', 'Opp_ORB': 'sum', 'Opp_TRB': 'sum', 'Opp_FGA': 'sum', 'Opp_FG': 'sum', 'Opp_3PA': 'sum', 'Opp_3PM': 'sum',
        'Opp_PF': 'sum', 'Opp_FTA': 'sum', 'Opp_FTM': 'sum', 'Opp_TOV': 'sum', 'Opp_MIN': 'sum'
    }).reset_index()

    totals['MPG'] = np.divide(totals['sMinutes'], totals['id_abe'], out=np.zeros_like(totals['sMinutes'], dtype=float), where=totals['id_abe']!=0)
    totals.rename(columns={'id_abe': 'GP', 'starter': 'JT'}, inplace=True)

    # --- 4. CÁLCULOS DEAN OLIVER ---
    denom_orb_perc = totals['Tm_ORB'] + totals['Opp_DRB']
    orb_perc = np.divide(totals['Tm_ORB'], denom_orb_perc, out=np.zeros_like(totals['Tm_ORB'], dtype=float), where=denom_orb_perc!=0)
    missed_fg = totals['Tm_FGA'] - totals['Tm_FG']
    totals['Tm_Poss'] = totals['Tm_FGA'] - (orb_perc * missed_fg * 1.07) + totals['Tm_TOV'] + (0.4 * totals['Tm_FTA'])

    denom_opp_orb_perc = totals['Opp_ORB'] + totals['Tm_DRB']
    opp_orb_perc = np.divide(totals['Opp_ORB'], denom_opp_orb_perc, out=np.zeros_like(totals['Opp_ORB'], dtype=float), where=denom_opp_orb_perc!=0)
    opp_missed_fg = totals['Opp_FGA'] - totals['Opp_FG']
    Opp_Poss = totals['Opp_FGA'] - (opp_orb_perc * opp_missed_fg * 1.07) + totals['Opp_TOV'] + (0.4 * totals['Opp_FTA'])

    totals['Opp_POSS'] = Opp_Poss 

    tm_min_5 = totals['Tm_MIN'] / 5 
    totals['Pace'] = 40 * np.divide((totals['Tm_Poss'] + Opp_Poss), (2 * tm_min_5), out=np.zeros_like(totals['Tm_Poss'], dtype=float), where=tm_min_5!=0)

    time_ratio = np.divide(totals['sMinutes'], tm_min_5, out=np.zeros_like(totals['sMinutes'], dtype=float), where=tm_min_5!=0)
    term_a = 1.14 * np.divide((totals['Tm_AST'] - totals['sAssists']), totals['Tm_FG'], out=np.zeros_like(totals['Tm_AST'], dtype=float), where=totals['Tm_FG']!=0)
    part_a = time_ratio * term_a
    tm_ast_pm = np.divide(totals['Tm_AST'], totals['Tm_MIN'], out=np.zeros_like(totals['Tm_AST'], dtype=float), where=totals['Tm_MIN']!=0)
    tm_fg_pm = np.divide(totals['Tm_FG'], totals['Tm_MIN'], out=np.zeros_like(totals['Tm_FG'], dtype=float), where=totals['Tm_MIN']!=0)
    num_b = (tm_ast_pm * totals['sMinutes'] * 5) - totals['sAssists']
    den_b = (tm_fg_pm * totals['sMinutes'] * 5) - totals['sFieldGoalsMade']
    term_b = np.divide(num_b, den_b, out=np.zeros_like(num_b, dtype=float), where=den_b!=0)
    part_b = term_b * (1 - time_ratio)
    qAST = part_a + part_b
    pts_from_fg = totals['sPoints'] - totals['sFreeThrowsMade']
    pts_fg_no_ast = 2 * (totals['sFieldGoalsMade'] + 0.5 * totals['sThreePointersMade'])
    ratio_pts_att_num = 2 * totals['sFieldGoalsAttempted']
    FG_Part = totals['sFieldGoalsMade'] * (1 - 0.5 * (np.divide(pts_from_fg, ratio_pts_att_num, out=np.zeros_like(pts_from_fg, dtype=float), where=ratio_pts_att_num!=0) * qAST))
    Tm_PTS = (totals['Tm_FG'] * 2) + totals['Tm_3PM'] + totals['Tm_FTM']
    tm_pts_fg = Tm_PTS - totals['Tm_FTM']
    tm_pts_others = tm_pts_fg - pts_from_fg
    tm_fga_others = totals['Tm_FGA'] - totals['sFieldGoalsAttempted']
    factor_2 = np.divide(tm_pts_others, (2 * tm_fga_others), out=np.zeros_like(tm_pts_others, dtype=float), where=tm_fga_others!=0)
    AST_Part = 0.5 * (factor_2 * totals['sAssists'])
    ft_rate = np.divide(totals['sFreeThrowsMade'], totals['sFreeThrowsAttempted'], out=np.zeros_like(totals['sFreeThrowsMade'], dtype=float), where=totals['sFreeThrowsAttempted']!=0)
    FT_Part = (1 - (1 - ft_rate)**2) * 0.4 * totals['sFreeThrowsAttempted']
    denom_orb = totals['Tm_ORB'] + totals['Opp_DRB']
    Team_ORB_Perc = np.divide(totals['Tm_ORB'], denom_orb, out=np.zeros_like(totals['Tm_ORB'], dtype=float), where=denom_orb!=0)
    ft_rate_team = np.divide(totals['Tm_FTM'], totals['Tm_FTA'], out=np.zeros_like(totals['Tm_FTM'], dtype=float), where=totals['Tm_FTA']!=0)
    tm_ft_poss = (1 - (1 - ft_rate_team)**2) * totals['Tm_FTA'] * 0.4
    Team_Scoring_Poss = totals['Tm_FG'] + tm_ft_poss
    denom_play = totals['Tm_FGA'] + (totals['Tm_FTA'] * 0.4) + totals['Tm_TOV']
    Team_Play_Perc = np.divide(Team_Scoring_Poss, denom_play, out=np.zeros_like(Team_Scoring_Poss, dtype=float), where=denom_play!=0)
    t1 = (1 - Team_ORB_Perc) * Team_Play_Perc
    t2 = Team_ORB_Perc * (1 - Team_Play_Perc)
    Team_ORB_Weight = np.divide(t1, (t1 + t2), out=np.zeros_like(t1, dtype=float), where=(t1 + t2)!=0)
    ORB_Part = totals['sReboundsOffensive'] * Team_ORB_Weight * Team_Play_Perc
    orb_ratio = np.divide(totals['Tm_ORB'], Team_Scoring_Poss, out=np.zeros_like(totals['Tm_ORB'], dtype=float), where=Team_Scoring_Poss!=0)
    ORB_Adj = 1 - (orb_ratio * Team_ORB_Weight * Team_Play_Perc)
    totals['ScPoss'] = (FG_Part + AST_Part + FT_Part) * ORB_Adj + ORB_Part
    ratio_pts_att_num_pprod = 2 * totals['sFieldGoalsAttempted']
    ratio_pts_att = np.divide(pts_from_fg, ratio_pts_att_num_pprod, out=np.zeros_like(pts_from_fg, dtype=float), where=ratio_pts_att_num_pprod!=0)
    adjust_mult = 0.5 * ratio_pts_att * qAST
    PProd_FG_Part = pts_fg_no_ast * (1 - adjust_mult)
    tm_fg_others = totals['Tm_FG'] - totals['sFieldGoalsMade']
    tm_3p_others = totals['Tm_3PM'] - totals['sThreePointersMade']
    num_factor1 = tm_fg_others + (0.5 * tm_3p_others)
    factor_1 = 2 * np.divide(num_factor1, tm_fg_others, out=np.zeros_like(num_factor1, dtype=float), where=tm_fg_others!=0)
    factor_2_pprod = 0.5 * np.divide(tm_pts_others, (2 * tm_fga_others), out=np.zeros_like(tm_pts_others, dtype=float), where=tm_fga_others!=0)
    PProd_AST_Part = factor_1 * factor_2_pprod * totals['sAssists']
    base_orb = totals['sReboundsOffensive'] * Team_ORB_Weight * Team_Play_Perc
    team_pps = np.divide(Tm_PTS, Team_Scoring_Poss, out=np.zeros_like(Tm_PTS, dtype=float), where=Team_Scoring_Poss!=0)
    PProd_ORB_Part = base_orb * team_pps
    totals['PProd'] = (PProd_FG_Part + PProd_AST_Part + totals['sFreeThrowsMade']) * ORB_Adj + PProd_ORB_Part
    FGxPoss = (totals['sFieldGoalsAttempted'] - totals['sFieldGoalsMade']) * (1 - 1.07 * Team_ORB_Perc)
    ft_rate_calc = np.divide(totals['sFreeThrowsMade'], totals['sFreeThrowsAttempted'], out=np.zeros_like(totals['sFreeThrowsMade'], dtype=float), where=totals['sFreeThrowsAttempted']!=0)
    FTxPoss = ((1 - ft_rate_calc)**2) * 0.4 * totals['sFreeThrowsAttempted']
    totals['TotPoss'] = totals['ScPoss'] + FGxPoss + FTxPoss + totals['sTurnovers']
    totals['ORtg'] = np.divide(totals['PProd'], totals['TotPoss'], out=np.zeros_like(totals['PProd'], dtype=float), where=totals['TotPoss']!=0) * 100
    totals['Floor%'] = np.divide(totals['ScPoss'], totals['TotPoss'], out=np.zeros_like(totals['ScPoss'], dtype=float), where=totals['TotPoss']!=0) * 100
    
    Opp_PTS = (totals['Opp_FG'] * 2) + totals['Opp_3PM'] + totals['Opp_FTM']
    Team_Defensive_Rating = 100 * np.divide(Opp_PTS, Opp_Poss, out=np.zeros_like(Opp_PTS, dtype=float), where=Opp_Poss!=0)
    denom_dor_perc = totals['Opp_ORB'] + totals['Tm_DRB']
    DOR_Perc = np.divide(totals['Opp_ORB'], denom_dor_perc, out=np.zeros_like(totals['Opp_ORB'], dtype=float), where=denom_dor_perc!=0)
    DFG_Perc = np.divide(totals['Opp_FG'], totals['Opp_FGA'], out=np.zeros_like(totals['Opp_FG'], dtype=float), where=totals['Opp_FGA']!=0)
    den_fmwt = ( DFG_Perc * ( 1 - DOR_Perc ) + ( 1 - DFG_Perc ) * DOR_Perc )
    FMwt = np.divide( ( DFG_Perc * ( 1 - DOR_Perc ) ), den_fmwt, out=np.zeros_like(DFG_Perc, dtype=float), where=den_fmwt!=0)
    stops_1 = totals['sSteals'] + totals['sBlocks'] * FMwt * ( 1 - 1.07 * DOR_Perc ) + totals['sReboundsDefensive'] * ( 1 - FMwt )
    den_tm_pf = totals['Tm_PF']
    stops_2 = (
        (np.divide( ( totals['Opp_FGA'] - totals['Opp_FG'] - totals['Tm_BLK'] ), totals['Tm_MIN'], out=np.zeros_like(totals['Opp_FGA'], dtype=float), where=totals['Tm_MIN']!=0) * FMwt * ( 1 - 1.07 * DOR_Perc ))
        + ( np.divide( ( totals['Opp_TOV'] - totals['Tm_STL'] ), totals['Tm_MIN'], out=np.zeros_like(totals['Opp_TOV'], dtype=float), where=totals['Tm_MIN']!=0 ))
    ) * totals['sMinutes'] + ( np.divide( totals['sFoulsPersonal'], den_tm_pf, out=np.zeros_like(totals['sFoulsPersonal'], dtype=float), where=den_tm_pf!=0 ) * 0.4 * totals['Opp_FTA'] * ( 1 - ( np.divide( totals['Opp_FTM'], totals['Opp_FTA'], out=np.zeros_like(totals['Opp_FTM'], dtype=float), where=totals['Opp_FTA']!=0 ) ) ) ** 2 )
    Stops = stops_1 + stops_2
    Stop_Perc = np.divide( (Stops * totals['Opp_MIN']), (totals['Tm_Poss'] * totals['sMinutes']), out=np.zeros_like(Stops, dtype=float), where=(totals['Tm_Poss'] * totals['sMinutes'])!=0)
    Opp_Scoring_Poss = totals['Opp_FG'] + ( 1 - ( 1 - ( np.divide( totals['Opp_FTM'], totals['Opp_FTA'], out=np.zeros_like(totals['Opp_FTM'], dtype=float), where=totals['Opp_FTA']!=0 ) ) ) ** 2 ) * totals['Opp_FTA'] * 0.4
    D_Pts_per_ScPoss = np.divide(Opp_PTS, Opp_Scoring_Poss, out=np.zeros_like(Opp_PTS, dtype=float), where=Opp_Scoring_Poss!=0)
    totals['DRtg'] = Team_Defensive_Rating + 0.2 * (100 * D_Pts_per_ScPoss * (1 - Stop_Perc) - Team_Defensive_Rating)

    totals['ORB%'] = np.divide((totals['sReboundsOffensive'] * tm_min_5), denom_orb, out=np.zeros_like(totals['sReboundsOffensive'], dtype=float), where=denom_orb!=0) * 100
    denom_drb = totals['Tm_DRB'] + totals['Opp_ORB']
    totals['DRB%'] = np.divide((totals['sReboundsDefensive'] * tm_min_5), denom_drb, out=np.zeros_like(totals['sReboundsDefensive'], dtype=float), where=denom_drb!=0) * 100
    denom_trb = totals['Tm_TRB'] + totals['Opp_TRB']
    totals['TRB%'] = np.divide((totals['sReboundsTotal'] * tm_min_5), denom_trb, out=np.zeros_like(totals['sReboundsTotal'], dtype=float), where=denom_trb!=0) * 100
    denom_ast = ((totals['sMinutes'] / tm_min_5) * totals['Tm_FG']) - totals['sFieldGoalsMade']
    totals['AST%'] = np.divide(totals['sAssists'], denom_ast, out=np.zeros_like(totals['sAssists'], dtype=float), where=denom_ast!=0) * 100
    denom_blk = totals['Opp_FGA'] - totals['Opp_3PA']
    totals['BLK%'] = np.divide((totals['sBlocks'] * tm_min_5), denom_blk, out=np.zeros_like(totals['sBlocks'], dtype=float), where=denom_blk!=0) * 100
    totals['STL%'] = np.divide((totals['sSteals'] * tm_min_5), totals['Opp_POSS'], out=np.zeros_like(totals['sSteals'], dtype=float), where=totals['Opp_POSS']!=0) * 100

    totals['FG3r'] = np.divide(totals['sThreePointersMade'], totals['sFieldGoalsAttempted'], out=np.zeros_like(totals['sThreePointersMade'], dtype=float), where=totals['sFieldGoalsAttempted']!=0)
    foul_ratio = np.divide(totals['Tm_FTA'], totals['Opp_PF'], out=np.zeros_like(totals['Tm_FTA'], dtype=float), where=totals['Opp_PF']!=0)
    foul_ratio = np.where(foul_ratio == 0, 1.0, foul_ratio) 
    part_ft = np.divide(totals['sFreeThrowsAttempted'], foul_ratio, out=np.zeros_like(totals['sFreeThrowsAttempted'], dtype=float), where=foul_ratio!=0)
    part_ast = totals['sAssists'] / 0.17
    totals['Touches'] = totals['sFieldGoalsAttempted'] + totals['sTurnovers'] + part_ft + part_ast
    totals['Touches_Per_Game'] = np.divide(totals['Touches'], totals['GP'], out=np.zeros_like(totals['Touches'], dtype=float), where=totals['GP']!=0)
    touches_total = totals['Touches']
    totals['%Pass'] = np.divide(part_ast, touches_total, out=np.zeros_like(part_ast, dtype=float), where=touches_total!=0) * 100
    totals['%Shoot'] = np.divide(totals['sFieldGoalsAttempted'], touches_total, out=np.zeros_like(totals['sFieldGoalsAttempted'], dtype=float), where=touches_total!=0) * 100
    totals['%Fouled'] = np.divide(part_ft, touches_total, out=np.zeros_like(part_ft, dtype=float), where=touches_total!=0) * 100
    totals['%TO'] = np.divide(totals['sTurnovers'], touches_total, out=np.zeros_like(totals['sTurnovers'], dtype=float), where=touches_total!=0) * 100
    totals['eFG%'] = np.divide((totals['sFieldGoalsMade'] + 0.5 * totals['sThreePointersMade']), totals['sFieldGoalsAttempted'], out=np.zeros_like(totals['sFieldGoalsMade'], dtype=float), where=totals['sFieldGoalsAttempted']!=0) * 100
    poss = totals['sFieldGoalsAttempted'] + (0.44 * totals['sFreeThrowsAttempted']) + totals['sTurnovers']
    totals['TOV%'] = np.divide(totals['sTurnovers'], poss, out=np.zeros_like(totals['sTurnovers'], dtype=float), where=poss!=0) * 100
    totals['FTr'] = np.divide(totals['sFreeThrowsMade'], totals['sFieldGoalsAttempted'], out=np.zeros_like(totals['sFreeThrowsMade'], dtype=float), where=totals['sFieldGoalsAttempted']!=0)
    tsa = 2 * (totals['sFieldGoalsAttempted'] + 0.44 * totals['sFreeThrowsAttempted'])
    totals['TS%'] = np.divide(totals['sPoints'], tsa, out=np.zeros_like(totals['sPoints'], dtype=float), where=tsa!=0) * 100
    totals['PF/40'] = np.divide(totals['sFoulsPersonal'], totals['sMinutes'], out=np.zeros_like(totals['sFoulsPersonal'], dtype=float), where=totals['sMinutes']!=0) * 40
    pp_shot = (totals['sTwoPointersMade'] * 2) + (totals['sThreePointersMade'] * 3)
    totals['PtsXShot'] = np.divide(pp_shot, totals['sFieldGoalsAttempted'], out=np.zeros_like(pp_shot, dtype=float), where=totals['sFieldGoalsAttempted']!=0)
    usg_den_player = totals['sMinutes'] * (totals['Tm_FGA'] + 0.44 * totals['Tm_FTA'] + totals['Tm_TOV'])
    usg_num_player = (totals['sFieldGoalsAttempted'] + 0.44 * totals['sFreeThrowsAttempted'] + totals['sTurnovers']) * (totals['Tm_MIN'] / 5)
    totals['USG%'] = np.divide(usg_num_player, usg_den_player, out=np.zeros_like(usg_num_player, dtype=float), where=usg_den_player!=0) * 100

    cols_clean = ['ORtg', 'DRtg', 'Floor%', 'eFG%', 'TOV%', 'FTr', 'TS%', 'PF/40', 'PtsXShot', 'USG%', 'ORB%', 'DRB%', 'TRB%', 'AST%', 'BLK%', 'STL%', 'FG3r', '%Pass', '%Shoot', '%Fouled', '%TO']
    totals[cols_clean] = totals[cols_clean].fillna(0.0)

    # --- 5. ENRIQUECIMIENTO ---
    totals['id_player_str'] = totals['id_player'].astype(str)
    totals['Pos'] = totals['id_player_str'].map(mapa_posicion).fillna("N/A")
    totals['Altura'] = totals['id_player_str'].map(mapa_altura).fillna(0)

    # --- 6. FILTROS AVANZADOS ---
    st.markdown("---")
    c_search, c_pos, c_hgt = st.columns([1.5, 1.5, 2])
    with c_search:
        search_query = st.text_input("🔍 Buscar por nombre o apellido", placeholder="Ingresa un nombre o apellido...", key="search_adv")
        if search_query: utils.rastrear_cambio("Búsqueda Texto (Adv)", search_query)
    with c_pos:
        opciones_pos = sorted(totals[totals['Pos'] != "N/A"]['Pos'].unique())
        filtro_posicion = st.multiselect("Posición", options=opciones_pos, placeholder="Todas", key="pos_adv")
        if filtro_posicion: utils.rastrear_cambio("Filtro Posición (Adv)", str(filtro_posicion))
    with c_hgt:
        alturas_validas = totals[totals['Altura'] > 0]['Altura']
        if not alturas_validas.empty:
            min_h_data, max_h_data = int(alturas_validas.min()), int(alturas_validas.max())
        else:
            min_h_data, max_h_data = 150, 210
        filtro_altura = st.slider("Rango de Estatura (cm)", min_value=min_h_data, max_value=max_h_data, value=(min_h_data, max_h_data), key="slider_height_adv")
        if filtro_altura != (min_h_data, max_h_data): utils.rastrear_cambio("Filtro Altura (Adv)", str(filtro_altura))

    # --- 7. APLICACIÓN DE FILTROS ---
    if search_query:
        totals = totals[totals['Nombre'].str.contains(search_query, case=False, na=False)]
    if filtro_posicion:
        totals = totals[totals['Pos'].isin(filtro_posicion)]
    if filtro_altura != (min_h_data, max_h_data):
        totals = totals[(totals['Altura'] >= filtro_altura[0]) & (totals['Altura'] <= filtro_altura[1])]

    # --- 8. VISUALIZACIÓN ---
    if 'adv_sort_col' not in st.session_state: st.session_state.adv_sort_col = 'PPS'
    if 'adv_sort_asc' not in st.session_state: st.session_state.adv_sort_asc = False
    if 'adv_page' not in st.session_state: st.session_state.adv_page = 0

    opciones_adv = {"MIN": "MPG", "USG%": "USG%", "TS%": "TS%", "eFG%": "eFG%", "PPS": "PtsXShot", "ALT": "Altura"}
    nombres_largos_adv = {"USG%": "Usage - Un estimado de las jugadas usadas de su equipo mientras estuvo en la duela", "TS%": "True Shooting% - Eficiencia para anotar", "eFG%": "Effective FG% - Eficiencia de tiro", "PPS": "Puntos por Tiro", "MIN": "Minutos", "ALT": "Altura en centímetros"}

    st.markdown("##### Ordenar por:")
    lista_adv = list(opciones_adv.keys())
    try: idx = lista_adv.index("PPS")
    except: idx = 0
    sort_key_adv = st.radio("Métrica:", options=lista_adv, index=idx, horizontal=True, label_visibility="collapsed", key="radio_adv")
    utils.rastrear_cambio("Ordenar Por (Adv)", sort_key_adv) 

    nueva_col_adv = opciones_adv[sort_key_adv]
    if st.session_state.adv_sort_col != nueva_col_adv:
        st.session_state.adv_sort_col = nueva_col_adv
        st.session_state.adv_sort_asc = False
        st.session_state.adv_page = 0

    flecha = "⬆️" if st.session_state.adv_sort_asc else "⬇️"
    nombre_adv = nombres_largos_adv.get(sort_key_adv, sort_key_adv)
    st.caption(f"Ordenando por **{nombre_adv}** ({flecha})")

    c_btn, _, c_chk = st.columns([1.5, 6, 3])
    with c_btn:
        if st.button("🔄 Invertir Orden", key="btn_inv_adv", use_container_width=True):
            st.session_state.adv_sort_asc = not st.session_state.adv_sort_asc
            st.rerun()
    with c_chk:
        qualified_adv = st.checkbox(f"Qualified: mínimo {threshold_games} juegos + 10 min/partido", value=False, key="chk_adv")
        utils.rastrear_cambio("Filtro Qualified (Adv)", qualified_adv)

    if qualified_adv:
        totals = totals[(totals['GP'] >= threshold_games) & (totals['MPG'] >= 10.0)]

    totals = totals.sort_values(by=st.session_state.adv_sort_col, ascending=st.session_state.adv_sort_asc)

    # Paginación
    ROWS_PER_PAGE = 30
    total_rows = len(totals)
    total_pages = math.ceil(total_rows / ROWS_PER_PAGE)
    
    if st.session_state.adv_page >= total_pages: st.session_state.adv_page = 0
    if total_pages == 0: st.session_state.adv_page = 0
        
    start_idx = st.session_state.adv_page * ROWS_PER_PAGE
    end_idx = start_idx + ROWS_PER_PAGE
    df_page_adv = totals.iloc[start_idx:end_idx]

    dynamic_h = (len(df_page_adv) + 1) * 35 + 3

    cols_vis_adv = ["Nombre", "Pos", "equipo_nombre", "GP", "JT", "MPG", "USG%", "TS%", "eFG%", "PtsXShot", "Altura"]

    # ⚠️ CAMBIO PRINCIPAL AQUÍ: ACTIVAR SELECCIÓN
    event = st.dataframe(
        df_page_adv[cols_vis_adv],
        hide_index=True, use_container_width=True, height=dynamic_h,
        on_select="rerun", 
        selection_mode="single-row", 
        column_config={
            "Nombre": st.column_config.TextColumn("Nombre"),
            "equipo_nombre": st.column_config.TextColumn("Equipo"),
            "Pos": st.column_config.TextColumn("POS"),
            "Altura": st.column_config.NumberColumn("ALT", format="%d"),
            "GP": st.column_config.NumberColumn("GP", format="%d"),
            "JT": st.column_config.NumberColumn("JT", format="%d"),
            "MPG": st.column_config.NumberColumn("MIN", format="%.1f"),
            "USG%": st.column_config.NumberColumn("USG%", format="%.1f%%"),
            "TS%": st.column_config.NumberColumn("TS%", format="%.1f%%"),
            "eFG%": st.column_config.NumberColumn("eFG%", format="%.1f%%"),
            "PtsXShot": st.column_config.NumberColumn("PPS", format="%.2f"),
        }
    )

    # ⚠️ CORRECTO USO DE VIEW_MODE
    # Guardar: solo actuar si hay selección Y no estamos ya en modo profile
    # (evita doble-rerun con on_select="rerun")
    if len(event.selection.rows) > 0 and st.session_state.get('view_mode') != 'profile':
        selected_row_idx = event.selection.rows[0]
        player_id_sel = df_page_adv.iloc[selected_row_idx]['id_player']
        st.session_state['selected_player_id'] = player_id_sel
        st.session_state['view_mode'] = 'profile'
        st.rerun()

    c_p1, c_pi, c_p2 = st.columns([1, 2, 1])
    with c_p1:
        if st.session_state.adv_page > 0:
            if st.button("⬅️ Anterior", key="prev_adv"):
                st.session_state.adv_page -= 1
                st.rerun()
    with c_pi:
        if total_pages > 0:
            st.markdown(f"<div style='text-align: center'>Página <b>{st.session_state.adv_page + 1}</b> de <b>{total_pages}</b></div>", unsafe_allow_html=True)
        else:
            st.warning("No hay jugadors que coincidan con los filtros.")
    with c_p2:
        if st.session_state.adv_page < total_pages - 1:
            if st.button("Siguiente ➡️", key="next_adv"):
                st.session_state.adv_page += 1
                st.rerun()