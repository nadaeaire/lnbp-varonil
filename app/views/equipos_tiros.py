"""
Vista: Mapa de Tiro por Equipo.
Muestra shot charts de volumen, eficiencia, zonas y marca de tiros.
"""
import streamlit as st
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')

from modules.tiro_zonas import classify_shot, ZONES
from modules.shot_chart import (
    normalizar_tiros, generar_shot_chart_volumen,
    generar_shot_chart_scatter, generar_shot_chart_zonas
)
from modules.data_loader import _build_comp_cat_map
# generar_shot_chart_eficiencia disponible en modules.shot_chart para uso futuro


def render_view(df_tiros, df_equipos_stats, categoria_sel, alias_equipos, df_equipos_cat=None):
    """
    Renderiza la vista de mapa de tiro por equipo.
    """
    st.title("Mapa de Tiros Beta")

    if df_tiros.empty:
        st.warning("No hay datos de tiros disponibles.")
        return

    if df_equipos_cat is None or df_equipos_cat.empty:
        st.warning("No hay catálogo de equipos para cruzar.")
        return

    # ── Cruce: equipo_id → nombre; Categoría desde competicion_id del tiro ──
    # Los tiros ya traen competicion_id por registro — es la fuente correcta.
    _comp_cat = _build_comp_cat_map()
    eq_cat = df_equipos_cat[['equipo_id', 'nombre']].drop_duplicates(subset=['equipo_id'])
    eq_cat = eq_cat.rename(columns={'nombre': 'equipo_nombre'})
    df_t = df_tiros.merge(eq_cat, on='equipo_id', how='inner')

    if 'competicion_id' in df_t.columns:
        df_t['Categoria'] = (
            df_t['competicion_id']
            .apply(lambda c: _comp_cat.get(str(int(float(c)))) if pd.notna(c) else None)
        )
    else:
        df_t['Categoria'] = None

    if 'Categoria' not in df_t.columns or df_t['Categoria'].isna().all():
        st.warning("No se pudo determinar la categoría de los equipos.")
        return

    df_t['equipo_nombre'] = df_t['equipo_nombre'].replace(alias_equipos)
    df_t = df_t[df_t['Categoria'] == categoria_sel]

    if df_t.empty:
        st.warning(f"No hay tiros registrados para {categoria_sel}.")
        return

    df_t = normalizar_tiros(df_t)
    df_t = df_t[df_t['court_y'] <= 12.0]

    # ── Calcular equipo defensor para cada tiro ──
    # Cada partido tiene 2 equipos; para cada tiro, el defensor es el otro equipo
    _teams_game = df_t[['partido_id', 'equipo_nombre']].drop_duplicates()
    _cross = _teams_game.merge(_teams_game, on='partido_id', suffixes=('', '_opp'))
    _cross = _cross[_cross['equipo_nombre'] != _cross['equipo_nombre_opp']]
    _cross = _cross.drop_duplicates(subset=['partido_id', 'equipo_nombre'])
    df_t = df_t.merge(
        _cross[['partido_id', 'equipo_nombre', 'equipo_nombre_opp']].rename(
            columns={'equipo_nombre_opp': 'defending_team'}
        ),
        on=['partido_id', 'equipo_nombre'],
        how='left'
    )

    # ── Selector de equipo y modo (Ofensiva / Defensiva) ──
    equipos_disponibles = sorted(df_t['equipo_nombre'].unique())
    n_equipos = len(equipos_disponibles)

    col_sel, col_modo = st.columns([2, 1])
    with col_sel:
        equipo_sel = st.selectbox(
            "Equipo:",
            equipos_disponibles,
            key="shot_chart_team_select"
        )
    with col_modo:
        modo = st.radio(
            "Vista:",
            ["Ofensiva", "Defensiva"],
            key="shot_chart_mode",
            horizontal=True
        )

    es_defensiva = (modo == "Defensiva")

    if es_defensiva:
        # Tiros recibidos: tiros donde el defensor es el equipo seleccionado
        df_data = df_t[df_t['defending_team'] == equipo_sel].copy()
        group_col = 'defending_team'
    else:
        df_data = df_t[df_t['equipo_nombre'] == equipo_sel].copy()
        group_col = 'equipo_nombre'

    n_tiros_data = len(df_data)

    if n_tiros_data < 10:
        etiqueta = "recibidos" if es_defensiva else "registrados"
        st.info(f"{equipo_sel} tiene muy pocos tiros {etiqueta} ({n_tiros_data}). Se necesitan al menos 10.")
        return

    # ── 1. Resumen de volumen con rankings ──
    df_rank_src = df_t.dropna(subset=[group_col])
    vol_by_team = df_rank_src.groupby(group_col).agg(
        total=('r', 'count'),
        total_2pt=('actiontype', lambda x: (x == '2pt').sum()),
        total_3pt=('actiontype', lambda x: (x == '3pt').sum()),
    ).reset_index()

    vol_by_team['rank_total'] = vol_by_team['total'].rank(ascending=False, method='min').astype(int)
    vol_by_team['rank_2pt'] = vol_by_team['total_2pt'].rank(ascending=False, method='min').astype(int)
    vol_by_team['rank_3pt'] = vol_by_team['total_3pt'].rank(ascending=False, method='min').astype(int)

    eq_vol = vol_by_team[vol_by_team[group_col] == equipo_sel]
    if not eq_vol.empty:
        ev = eq_vol.iloc[0]
        n_2pt = int(ev['total_2pt'])
        n_3pt = int(ev['total_3pt'])
        made_2pt = int(df_data[df_data['actiontype'] == '2pt']['r'].sum())
        made_3pt = int(df_data[df_data['actiontype'] == '3pt']['r'].sum())
        pct_2pt = (made_2pt / n_2pt * 100) if n_2pt > 0 else 0
        pct_3pt = (made_3pt / n_3pt * 100) if n_3pt > 0 else 0
        made_total = made_2pt + made_3pt
        pct_total = (made_total / n_tiros_data * 100) if n_tiros_data > 0 else 0

        lbl_total = "Tiros recibidos" if es_defensiva else "Total tiros"
        lbl_2pt = "Dobles recibidos (2PT)" if es_defensiva else "Dobles (2PT)"
        lbl_3pt = "Triples recibidos (3PT)" if es_defensiva else "Triples (3PT)"

        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric(
                lbl_total,
                f"{made_total}/{n_tiros_data}  ({pct_total:.1f}%)",
                f"#{int(ev['rank_total'])} de {n_equipos}",
                delta_color="off"
            )
        with c2:
            st.metric(
                lbl_2pt,
                f"{made_2pt}/{n_2pt}  ({pct_2pt:.1f}%)",
                f"#{int(ev['rank_2pt'])} de {n_equipos}",
                delta_color="off"
            )
        with c3:
            st.metric(
                lbl_3pt,
                f"{made_3pt}/{n_3pt}  ({pct_3pt:.1f}%)",
                f"#{int(ev['rank_3pt'])} de {n_equipos}",
                delta_color="off"
            )

    st.divider()

    # ── 2. Gráficas: 1 arriba (zonas) + 2 abajo (volumen + scatter) ──
    titulo_chart = f"{equipo_sel} (Def)" if es_defensiva else equipo_sel

    if es_defensiva:
        st.caption("**Zonas** — FG% rival vs promedio de liga (rojo = rival arriba, azul = rival abajo)")
    else:
        st.caption("**Zonas** — FG% vs promedio de liga (rojo = arriba, azul = abajo)")
    fig_zonas = generar_shot_chart_zonas(df_data, titulo=titulo_chart, df_liga=df_t)
    st.pyplot(fig_zonas, use_container_width=False)

    col_vol, col_scatter = st.columns(2)

    with col_vol:
        cap_vol = "**Volumen** — De dónde le tiran" if es_defensiva else "**Volumen** — De dónde tira más"
        st.caption(cap_vol)
        fig_vol = generar_shot_chart_volumen(df_data, titulo=titulo_chart)
        st.pyplot(fig_vol, use_container_width=True)

    with col_scatter:
        cap_scat = "**Marca de tiros** — Rivales: Anotados / Fallados" if es_defensiva else "**Marca de tiros** — Anotados / Fallados"
        st.caption(cap_scat)
        fig_scatter = generar_shot_chart_scatter(df_data, titulo=titulo_chart)
        st.pyplot(fig_scatter, use_container_width=True)

    # ── Eficiencia hexbin (comentada para uso futuro) ──
    # col_eff_left, col_eff_right = st.columns(2)
    # with col_eff_left:
    #     st.caption("**Eficiencia** — FG% por zona (hexbin)")
    #     fig_eff = generar_shot_chart_eficiencia(df_equipo, titulo=equipo_sel)
    #     st.pyplot(fig_eff, use_container_width=True)

    # ── 3. Tabla por zona con rankings ──
    st.divider()
    st.subheader("Desglose por zona" + (" (Defensiva)" if es_defensiva else ""))

    # Clasificar tiros de TODOS los equipos en zonas
    df_zonas_all = df_t.copy()
    df_zonas_all['zona'] = df_zonas_all.apply(lambda row: classify_shot(row['x'], row['y']), axis=1)
    df_zonas_all = df_zonas_all.dropna(subset=['zona'])
    df_zonas_all['zona'] = df_zonas_all['zona'].astype(int)

    # Volumen por equipo y zona (para ranking) — usando group_col según modo
    df_zonas_rank = df_zonas_all.dropna(subset=[group_col])
    vol_eq_zona = df_zonas_rank.groupby([group_col, 'zona']).agg(
        intentos=('r', 'count')
    ).reset_index()

    # Stats del equipo seleccionado (ofensiva o defensiva)
    df_eq_zonas = df_zonas_all[df_zonas_all[group_col] == equipo_sel]
    zone_names = {z['num']: z['name'] for z in ZONES}

    eq_stats = df_eq_zonas.groupby('zona').agg(
        Anotados=('r', 'sum'),
        Intentados=('r', 'count')
    ).reset_index()
    eq_stats['Anotados'] = eq_stats['Anotados'].astype(int)
    eq_stats['FG%'] = np.where(
        eq_stats['Intentados'] > 0,
        (eq_stats['Anotados'] / eq_stats['Intentados'] * 100).round(1),
        0.0
    )

    # Ranking de volumen por zona
    ranks = []
    for _, row in eq_stats.iterrows():
        z = int(row['zona'])
        zona_vol = vol_eq_zona[vol_eq_zona['zona'] == z].copy()
        zona_vol['rank'] = zona_vol['intentos'].rank(ascending=False, method='min').astype(int)
        eq_rank = zona_vol[zona_vol[group_col] == equipo_sel]
        rank_str = f"#{int(eq_rank['rank'].iloc[0])} de {n_equipos}" if not eq_rank.empty else "—"
        ranks.append(rank_str)

    eq_stats['Ranking Vol.'] = ranks
    eq_stats['Zona'] = eq_stats['zona'].map(zone_names)
    eq_stats = eq_stats.sort_values('Intentados', ascending=False)

    st.dataframe(
        eq_stats[['Zona', 'Anotados', 'Intentados', 'FG%', 'Ranking Vol.']],
        hide_index=True,
        use_container_width=True,
        column_config={
            "FG%": st.column_config.NumberColumn("FG%", format="%.1f%%"),
        }
    )

    # ── 4. Tabla de subtipos (comentada por ahora) ──
    # st.divider()
    # st.subheader("Distribución por tipo de tiro")
    #
    # if not df_equipo.empty and 'subtype' in df_equipo.columns:
    #     resumen = (
    #         df_equipo.groupby('subtype')
    #         .agg(Intentos=('r', 'count'), Anotados=('r', 'sum'))
    #         .reset_index()
    #     )
    #     resumen['%'] = (resumen['Anotados'] / resumen['Intentos'] * 100).round(1)
    #     resumen = resumen.sort_values('Intentos', ascending=False)
    #     resumen.columns = ['Tipo de Tiro', 'Intentos', 'Anotados', '%']
    #     resumen['Anotados'] = resumen['Anotados'].astype(int)
    #
    #     st.dataframe(resumen, hide_index=True, use_container_width=True)
