import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.colors as mcolors
import modules.utils as utils

def render_view(df_main, categoria_sel):
    # Derivar datos de equipos a partir de la vista maestra de jugadores.
    # df_main ya viene filtrado por categoría y con alias aplicados desde main.py.

    if df_main.empty:
        st.warning("No hay datos disponibles.")
        st.stop()

    # Deduplicar: una fila por partido por equipo
    df_teams = df_main.drop_duplicates(subset=['id_abe', 'equipo_nombre']).copy()
    if df_teams.empty:
        st.warning(f"No hay equipos en: {categoria_sel}")
        st.stop()

    # 3. Slider y Header
    max_games = df_teams.groupby('equipo_nombre')['id_abe'].nunique().max()
    max_games = int(max_games) if (max_games and not pd.isna(max_games)) else 1
    
    col_h, col_s = st.columns([1, 1])
    with col_h:
        st.title(f"Four Factors | {categoria_sel}")
    with col_s:
        st.markdown("<br>", unsafe_allow_html=True)
        if max_games > 1:
            window = st.slider("Analizar últimos X juegos:", 1, max_games, max_games, key="s_4f_v2")
        else:
            window = 1
        utils.rastrear_cambio("Slider 4Factors", window)

    # 4. Preparación de Datos (Rellenar Nulos)
    cols_check = [
        'Tm_Score', 'Tm_FG', 'Tm_FGA', 'Tm_3PM', 'Tm_FTM', 'Tm_FTA', 'Tm_ORB', 'Tm_DRB', 'Tm_TOV',
        'Opp_Score', 'Opp_FG', 'Opp_FGA', 'Opp_3PM', 'Opp_FTM', 'Opp_FTA', 'Opp_ORB', 'Opp_DRB', 'Opp_TOV'
    ]
    for c in cols_check:
        if c not in df_teams.columns: df_teams[c] = 0.0
        else: df_teams[c] = df_teams[c].fillna(0)

    df_games = df_teams.copy()

    # PTS: usar Score del DB por fila; si es 0, recalcular desde box score
    df_games['Tm_PTS'] = np.where(
        df_games['Tm_Score'] > 0,
        df_games['Tm_Score'],
        (2 * df_games['Tm_FG']) + df_games['Tm_3PM'] + df_games['Tm_FTM']
    )
    df_games['Opp_PTS'] = np.where(
        df_games['Opp_Score'] > 0,
        df_games['Opp_Score'],
        (2 * df_games['Opp_FG']) + df_games['Opp_3PM'] + df_games['Opp_FTM']
    )

    df_games['W'] = np.where(df_games['Tm_PTS'] > df_games['Opp_PTS'], 1, 0)
    df_games['L'] = (1 - df_games['W']).astype(int)

    # 5. Posesiones (Fórmula Original)
    # Equipo
    denom_orb = df_games['Tm_ORB'] + df_games['Opp_DRB']
    orb_pct = np.divide(df_games['Tm_ORB'], denom_orb, out=np.zeros_like(df_games['Tm_ORB'], dtype=float), where=denom_orb!=0)
    missed_fg = df_games['Tm_FGA'] - df_games['Tm_FG']
    df_games['Tm_Poss'] = (df_games['Tm_FGA'] - (orb_pct * missed_fg * 1.07) + df_games['Tm_TOV'] + (0.4 * df_games['Tm_FTA']))

    # Rival
    denom_orb_opp = df_games['Opp_ORB'] + df_games['Tm_DRB']
    orb_pct_opp = np.divide(df_games['Opp_ORB'], denom_orb_opp, out=np.zeros_like(df_games['Opp_ORB'], dtype=float), where=denom_orb_opp!=0)
    opp_missed_fg = df_games['Opp_FGA'] - df_games['Opp_FG']
    df_games['Opp_Poss'] = (df_games['Opp_FGA'] - (orb_pct_opp * opp_missed_fg * 1.07) + df_games['Opp_TOV'] + (0.4 * df_games['Opp_FTA']))

    # 6. Agregación (Sumar)
    df_sorted = df_games.sort_values(['equipo_nombre', 'Fecha'], ascending=[True, False])
    df_window = df_sorted.groupby('equipo_nombre').head(window)

    cols_sum = [
        'W', 'L', 'Tm_PTS', 'Opp_PTS', 'Tm_Poss', 'Opp_Poss',
        'Tm_FG', 'Tm_FGA', 'Tm_3PM', 'Tm_FTM', 'Tm_FTA', 'Tm_TOV', 'Tm_ORB', 'Tm_DRB',
        'Opp_FG', 'Opp_FGA', 'Opp_3PM', 'Opp_FTM', 'Opp_FTA', 'Opp_TOV', 'Opp_ORB', 'Opp_DRB'
    ]
    agg_dict = {c: 'sum' for c in cols_sum if c in df_window.columns}
    df_agg = df_window.groupby('equipo_nombre').agg(agg_dict).reset_index()

    # 7. Métricas Four Factors
    
    # General
    df_agg['Off_Rtg'] = np.divide(df_agg['Tm_PTS'], df_agg['Tm_Poss'], out=np.zeros_like(df_agg['Tm_PTS'], dtype=float), where=df_agg['Tm_Poss']!=0) * 100
    df_agg['Def_Rtg'] = np.divide(df_agg['Opp_PTS'], df_agg['Opp_Poss'], out=np.zeros_like(df_agg['Opp_PTS'], dtype=float), where=df_agg['Opp_Poss']!=0) * 100
    df_agg['Net_Rtg'] = df_agg['Off_Rtg'] - df_agg['Def_Rtg']

    # Ofensiva
    # eFG%
    num_efg = df_agg['Tm_FG'] + (0.5 * df_agg['Tm_3PM'])
    df_agg['Off_eFG'] = np.divide(num_efg, df_agg['Tm_FGA'], out=np.zeros_like(num_efg, dtype=float), where=df_agg['Tm_FGA']!=0)
    # TOV%
    denom_tov = df_agg['Tm_FGA'] + (0.44 * df_agg['Tm_FTA']) + df_agg['Tm_TOV']
    df_agg['Off_TOV_Pct'] = np.divide(df_agg['Tm_TOV'], denom_tov, out=np.zeros_like(df_agg['Tm_TOV'], dtype=float), where=denom_tov!=0)
    # ORB%
    denom_orb_pct = df_agg['Tm_ORB'] + df_agg['Opp_DRB']
    df_agg['Off_ORB_Pct'] = np.divide(df_agg['Tm_ORB'], denom_orb_pct, out=np.zeros_like(df_agg['Tm_ORB'], dtype=float), where=denom_orb_pct!=0)
    # FT Rate
    df_agg['Off_FTRate'] = np.divide(df_agg['Tm_FTM'], df_agg['Tm_FGA'], out=np.zeros_like(df_agg['Tm_FTM'], dtype=float), where=df_agg['Tm_FGA']!=0)

    # Defensa
    # Def eFG%
    num_efg_def = df_agg['Opp_FG'] + (0.5 * df_agg['Opp_3PM'])
    df_agg['Def_eFG'] = np.divide(num_efg_def, df_agg['Opp_FGA'], out=np.zeros_like(num_efg_def, dtype=float), where=df_agg['Opp_FGA']!=0)
    # Def TOV%
    denom_tov_def = df_agg['Opp_FGA'] + (0.44 * df_agg['Opp_FTA']) + df_agg['Opp_TOV']
    df_agg['Def_TOV_Pct'] = np.divide(df_agg['Opp_TOV'], denom_tov_def, out=np.zeros_like(df_agg['Opp_TOV'], dtype=float), where=denom_tov_def!=0)
    # Def DRB%
    denom_drb_pct = df_agg['Opp_ORB'] + df_agg['Tm_DRB']
    df_agg['Def_DRB_Pct'] = np.divide(df_agg['Tm_DRB'], denom_drb_pct, out=np.zeros_like(df_agg['Tm_DRB'], dtype=float), where=denom_drb_pct!=0)
    # Def FT Rate
    df_agg['Def_FTRate'] = np.divide(df_agg['Opp_FTM'], df_agg['Opp_FGA'], out=np.zeros_like(df_agg['Opp_FTM'], dtype=float), where=df_agg['Opp_FGA']!=0)

    # 8. Rankings
    # General
    df_agg['Rk_Net'] = df_agg['Net_Rtg'].rank(ascending=False, method='min')
    
    # Ofensiva
    df_agg['Rk_Off'] = df_agg['Off_Rtg'].rank(ascending=False, method='min')
    df_agg['Rk_Off_eFG'] = df_agg['Off_eFG'].rank(ascending=False, method='min')
    df_agg['Rk_Off_TOV'] = df_agg['Off_TOV_Pct'].rank(ascending=True, method='min') # Menos es mejor (Rank Asc)
    df_agg['Rk_Off_ORB'] = df_agg['Off_ORB_Pct'].rank(ascending=False, method='min')
    df_agg['Rk_Off_FTR'] = df_agg['Off_FTRate'].rank(ascending=False, method='min')

    # Defensa
    df_agg['Rk_Def'] = df_agg['Def_Rtg'].rank(ascending=True, method='min') # Menos es mejor
    df_agg['Rk_Def_eFG'] = df_agg['Def_eFG'].rank(ascending=True, method='min') # Menos es mejor
    df_agg['Rk_Def_TOV'] = df_agg['Def_TOV_Pct'].rank(ascending=False, method='min') # Más (forzados) es mejor
    df_agg['Rk_Def_DRB'] = df_agg['Def_DRB_Pct'].rank(ascending=False, method='min') # Más es mejor
    df_agg['Rk_Def_FTR'] = df_agg['Def_FTRate'].rank(ascending=True, method='min') # Menos es mejor

    # 9. Visualización con Radio Buttons
    st.markdown("### Four Factors (ocho, más bien)")
    
    # Diccionario de ordenamiento: Label -> (Columna, Ascendente?)
    mapa_orden = {
        "Victorias": ("W", False),
        "Derrotas": ("L", False),
        "NRtg": ("Net_Rtg", False),
        "ORtg": ("Net_Rtg", False),
        "eFG% O": ("Off_eFG", False),
        "TOV% O": ("Off_TOV_Pct", True),
        "ORB%": ("Off_ORB_Pct", False),
        "FTRate O": ("Off_FTRate", False),
        "DRtg": ("Def_Rtg", True),
        "eFG% D": ("Def_eFG", True),
        "TOV% D": ("Def_TOV_Pct", False),
        "DRB%": ("Def_DRB_Pct", False),
        "FTRate D": ("Def_FTRate", True),
    }
    
    nombres_largos = {
        "Victorias": "Partidos ganados", 
        "Derrotas": "Partidos perdidos",
        "NRtg": "Net Rating",
        "ORtg": "Rating Ofensivo",
        "eFG% O": "Eficiencia de tiro ofensiva (Effective Field Goal Percentage)",
        "TOV% O": "Control de balón - qué porcentaje de pérdidas por jugadas se tiene",
        "ORB%": "Capacidad de obtener rebotes ofensivos - porcentaje logrado a partir del total posible",
        "FTRate O": "Agresividad y capacidad de conseguir faltas y tirar tiros libres (Free Throw Rate)",
        "DRtg": "Rating Defensivo",
        "eFG% D": "Eficiencia de tiro defensiva (Effective Field Goal Percentage)",
        "TOV% D": "Porcentaje de pérdidas forzadas por jugadas al rival",
        "DRB%": "Capacidad de obtener rebotes defensivos - porcentaje logrado a partir del total posible",
        "FTRate D": "Defensa para evitar faltas y otorgarle tiros libres al rival (Free Throw Rate)",
    }

    # Radio Buttons Horizontales
    criterio_sort = st.radio("Ordenar tabla por:", options=list(mapa_orden.keys()), index=0, horizontal=True, label_visibility="collapsed")
    utils.rastrear_cambio("Sort 4Factors", criterio_sort)
    
    col_sort, asc_sort = mapa_orden[criterio_sort]
    df_disp = df_agg.sort_values(col_sort, ascending=asc_sort)
    
    # Flecha visual
    flecha = "⬆️" if asc_sort else "⬇️"
    #st.caption(f"Ordenando por **{criterio_sort}** ({flecha})")
    st.caption(f"Ordenando por **{nombres_largos.get(criterio_sort)}** ({flecha})")

    # Estructura MultiIndex
    # Nota: Usamos espacios en blanco en 'Rank' para hacer únicas las llaves del diccionario
    # Bloque 1: '' (Vacio para quitar "General")
    # Orden: Rank -> Metrica
    data_struct = {
        ('', 'Equipo'): df_disp['equipo_nombre'],
        ('', 'Victorias'): df_disp['W'],
        ('', 'Derrotas'): df_disp['L'],
        ('', 'Rank'): df_disp['Rk_Net'],
        ('', 'NRtg'): df_disp['Net_Rtg'],

        ('Ofensiva', 'Rank '): df_disp['Rk_Off'],
        ('Ofensiva', 'ORtg'): df_disp['Off_Rtg'],
        ('Ofensiva', 'Rank  '): df_disp['Rk_Off_eFG'],
        ('Ofensiva', 'eFG%'): df_disp['Off_eFG'],
        ('Ofensiva', 'Rank   '): df_disp['Rk_Off_TOV'],
        ('Ofensiva', 'TOV%'): df_disp['Off_TOV_Pct'],
        ('Ofensiva', 'Rank    '): df_disp['Rk_Off_ORB'],
        ('Ofensiva', 'ORB%'): df_disp['Off_ORB_Pct'],
        ('Ofensiva', 'Rank     '): df_disp['Rk_Off_FTR'],
        ('Ofensiva', 'FTRate'): df_disp['Off_FTRate'],

        ('Defensa', 'Rank      '): df_disp['Rk_Def'],
        ('Defensa', 'DRtg'): df_disp['Def_Rtg'],
        ('Defensa', 'Rank       '): df_disp['Rk_Def_eFG'],
        ('Defensa', 'eFG%'): df_disp['Def_eFG'],
        ('Defensa', 'Rank        '): df_disp['Rk_Def_TOV'],
        ('Defensa', 'TOV%'): df_disp['Def_TOV_Pct'],
        ('Defensa', 'Rank         '): df_disp['Rk_Def_DRB'],
        ('Defensa', 'DRB%'): df_disp['Def_DRB_Pct'],
        ('Defensa', 'Rank          '): df_disp['Rk_Def_FTR'],
        ('Defensa', 'FTRate'): df_disp['Def_FTRate'],
    }
    
    df_multi = pd.DataFrame(data_struct)
    
    # Formatos
    fmt = {
        ('', 'Victorias'): "{:.0f}",
        ('', 'Derrotas'): "{:.0f}", 
        ('', 'NRtg'): "{:+.1f}",
        ('', 'Rank'): "{:.0f}",
        ('Ofensiva', 'ORtg'): "{:.1f}",
        ('Defensa', 'DRtg'): "{:.1f}",
    }
    
    for col in df_multi.columns:
        lbl = col[1]
        # Si contiene "Rank" (con o sin espacios)
        if 'Rank' in lbl:
            fmt[col] = "{:.0f}"
        # Porcentajes
        elif '%' in lbl or 'TOV' in lbl or 'ORB' in lbl or 'DRB' in lbl or 'FTRate' in lbl:
            fmt[col] = "{:.1%}"

    # Gradiente
    # Seleccionamos columnas que contengan 'Rank' en el nombre
    cols_rank = [c for c in df_multi.columns if 'Rank' in c[1]]
    cmap = mcolors.LinearSegmentedColormap.from_list("SBR", ["#00D46B", "#ffffff", "#FF4534"])
    
    st.dataframe(
        df_multi.style.format(fmt).background_gradient(subset=cols_rank, cmap=cmap, vmin=1, vmax=len(df_multi)),
        height=(len(df_multi) * 35) + 75,
        use_container_width=True,
        hide_index=True
    )