"""
Módulo para generar mapas de tiro (shot charts) estilo densidad relativa.
Dibuja una media cancha FIBA con contornos KDE que muestran dónde un
jugador/equipo tira MÁS (rojo) o MENOS (gris) que el promedio de la liga.
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import Arc
from scipy.stats import gaussian_kde
import streamlit as st

# ── Dimensiones cancha FIBA (metros) ──────────────────────────────────
COURT_LENGTH = 28.0       # largo total
COURT_WIDTH  = 15.0       # ancho total
BASKET_FROM_ENDLINE = 1.575  # centro del aro al fondo
HOOP_RADIUS  = 0.225
BACKBOARD_WIDTH = 1.80
PAINT_WIDTH  = 4.90       # ancho de la zona/pintura
PAINT_LENGTH = 5.80       # largo de la zona (del fondo al tiro libre)
FT_CIRCLE_RADIUS = 1.80
THREE_PT_RADIUS  = 6.75   # radio del arco de 3 puntos
THREE_PT_CORNER_DIST = 0.90  # distancia mínima de la línea de 3 a la lateral
RESTRICTED_AREA_RADIUS = 1.25

# Posición del aro en sistema de coordenadas normalizado (0-100)
BASKET_X_NORM = 100.0 - (BASKET_FROM_ENDLINE / COURT_LENGTH) * 100.0  # ≈94.375


# ── Normalización de coordenadas ──────────────────────────────────────
def normalizar_tiros(df):
    """
    Normaliza las coordenadas de tiro para que todos apunten al mismo aro.
    Tiros con x < 50 se voltean (equipo atacaba el aro izquierdo).
    Retorna columnas 'court_x' (lateral, metros) y 'court_y' (dist. al aro, metros).
    """
    df = df.copy()

    # Detectar qué tiros necesitan voltearse (atacaban el aro izquierdo)
    mask_flip = df['x'] < 50

    x_norm = df['x'].copy()
    y_norm = df['y'].copy()

    x_norm[mask_flip] = 100.0 - x_norm[mask_flip]
    y_norm[mask_flip] = 100.0 - y_norm[mask_flip]

    # Convertir a coordenadas de cancha (metros) centradas en el aro
    # court_x: lateral (negativo = izquierda, positivo = derecha)
    # court_y: distancia desde el aro (positivo = más lejos)
    df['court_x'] = (y_norm - 50.0) * (COURT_WIDTH / 100.0)
    df['court_y'] = (BASKET_X_NORM - x_norm) * (COURT_LENGTH / 100.0)

    return df


# ── Dibujo de cancha FIBA ─────────────────────────────────────────────
def dibujar_cancha(ax, color_lineas='#333333', lw=0.8):
    """Dibuja media cancha FIBA en el Axes dado."""
    half_w = COURT_WIDTH / 2.0
    hoop_y = 0.0  # el aro está en y=0
    baseline_y = -BASKET_FROM_ENDLINE

    # Límites del fondo y laterales (media cancha)
    # Línea de fondo
    ax.plot([-half_w, half_w], [baseline_y, baseline_y], color=color_lineas, lw=lw)
    # Laterales (hasta un poco más allá de la línea de 3)
    max_y = THREE_PT_RADIUS + 3.0  # espacio extra arriba
    ax.plot([-half_w, -half_w], [baseline_y, max_y], color=color_lineas, lw=lw)
    ax.plot([half_w, half_w], [baseline_y, max_y], color=color_lineas, lw=lw)

    # Pintura / zona (rectángulo)
    paint_half_w = PAINT_WIDTH / 2.0
    paint_top = PAINT_LENGTH - BASKET_FROM_ENDLINE
    rect_paint = patches.Rectangle(
        (-paint_half_w, baseline_y), PAINT_WIDTH, PAINT_LENGTH,
        linewidth=lw, edgecolor=color_lineas, facecolor='none'
    )
    ax.add_patch(rect_paint)

    # Círculo del tiro libre (parte superior, sólida)
    ft_arc = Arc(
        (0, paint_top), FT_CIRCLE_RADIUS * 2, FT_CIRCLE_RADIUS * 2,
        angle=0, theta1=0, theta2=180,
        color=color_lineas, lw=lw
    )
    ax.add_patch(ft_arc)

    # Círculo del tiro libre (parte inferior, punteada)
    ft_arc_dash = Arc(
        (0, paint_top), FT_CIRCLE_RADIUS * 2, FT_CIRCLE_RADIUS * 2,
        angle=0, theta1=180, theta2=360,
        color=color_lineas, lw=lw, linestyle='dashed'
    )
    ax.add_patch(ft_arc_dash)

    # Aro
    aro = plt.Circle((0, hoop_y), HOOP_RADIUS, color=color_lineas, fill=False, lw=lw)
    ax.add_patch(aro)

    # Tablero
    ax.plot(
        [-BACKBOARD_WIDTH / 2, BACKBOARD_WIDTH / 2],
        [-HOOP_RADIUS * 2, -HOOP_RADIUS * 2],
        color=color_lineas, lw=lw * 1.5
    )

    # Zona restringida (semicírculo)
    restricted = Arc(
        (0, hoop_y), RESTRICTED_AREA_RADIUS * 2, RESTRICTED_AREA_RADIUS * 2,
        angle=0, theta1=0, theta2=180,
        color=color_lineas, lw=lw
    )
    ax.add_patch(restricted)

    # Línea de 3 puntos
    # Secciones rectas (corners) — desde el fondo hasta donde empieza el arco
    corner_line_y = np.sqrt(
        THREE_PT_RADIUS**2 - (half_w - THREE_PT_CORNER_DIST)**2
    ) if THREE_PT_RADIUS > (half_w - THREE_PT_CORNER_DIST) else 0

    three_x = half_w - THREE_PT_CORNER_DIST

    # Corner izquierdo
    ax.plot([-three_x, -three_x], [baseline_y, corner_line_y], color=color_lineas, lw=lw)
    # Corner derecho
    ax.plot([three_x, three_x], [baseline_y, corner_line_y], color=color_lineas, lw=lw)

    # Arco de 3 puntos
    theta_start = np.degrees(np.arcsin(corner_line_y / THREE_PT_RADIUS)) if THREE_PT_RADIUS > 0 else 0
    three_arc = Arc(
        (0, hoop_y), THREE_PT_RADIUS * 2, THREE_PT_RADIUS * 2,
        angle=90, theta1=-(90 - theta_start), theta2=(90 - theta_start),
        color=color_lineas, lw=lw
    )
    ax.add_patch(three_arc)

    # Configurar aspecto
    ax.set_xlim(-half_w - 0.5, half_w + 0.5)
    ax.set_ylim(baseline_y - 0.5, max_y)
    ax.set_aspect('equal')
    ax.axis('off')


# ── Cálculo de densidad KDE ───────────────────────────────────────────
def calcular_densidad_diferencial(df_sujeto, df_referencia, n_grid=150, bw=1.2):
    """
    Calcula la diferencia de densidad KDE entre un sujeto (jugador/equipo)
    y una referencia (liga/equipo).

    Retorna: (X_grid, Y_grid, Z_positivo, Z_negativo)
      - Z_positivo: donde el sujeto tira MÁS que la referencia
      - Z_negativo: donde el sujeto tira MENOS que la referencia
    """
    half_w = COURT_WIDTH / 2.0
    max_y = THREE_PT_RADIUS + 3.0
    baseline_y = -BASKET_FROM_ENDLINE

    # Grilla para evaluar la densidad
    x_grid = np.linspace(-half_w, half_w, n_grid)
    y_grid = np.linspace(baseline_y, max_y, n_grid)
    X, Y = np.meshgrid(x_grid, y_grid)
    positions = np.vstack([X.ravel(), Y.ravel()])

    # Datos del sujeto
    sx = df_sujeto['court_x'].values
    sy = df_sujeto['court_y'].values

    # Datos de la referencia
    rx = df_referencia['court_x'].values
    ry = df_referencia['court_y'].values

    # Necesitamos mínimo ~10 tiros para un KDE razonable
    if len(sx) < 10 or len(rx) < 10:
        return X, Y, np.zeros_like(X), np.zeros_like(X)

    try:
        kde_sujeto = gaussian_kde(np.vstack([sx, sy]), bw_method=bw)
        kde_referencia = gaussian_kde(np.vstack([rx, ry]), bw_method=bw)

        Z_sujeto = kde_sujeto(positions).reshape(X.shape)
        Z_referencia = kde_referencia(positions).reshape(X.shape)
    except Exception:
        return X, Y, np.zeros_like(X), np.zeros_like(X)

    # Diferencia
    Z_diff = Z_sujeto - Z_referencia

    # Separar positivos (tira más) y negativos (tira menos)
    Z_pos = np.where(Z_diff > 0, Z_diff, 0)
    Z_neg = np.where(Z_diff < 0, np.abs(Z_diff), 0)

    return X, Y, Z_pos, Z_neg


# ── Generación del chart completo ─────────────────────────────────────
def generar_shot_chart(df_sujeto, df_referencia, titulo="", n_grid=150, bw=1.2):
    """
    Genera un mapa de tiro con densidad relativa.

    Args:
        df_sujeto: DataFrame con tiros del sujeto (ya con court_x, court_y)
        df_referencia: DataFrame con tiros de referencia (ya con court_x, court_y)
        titulo: título del chart
        n_grid: resolución de la grilla KDE
        bw: bandwidth del KDE (mayor = más suave)

    Returns:
        matplotlib Figure
    """
    fig, ax = plt.subplots(figsize=(6, 6), facecolor='#FFFAF0')
    ax.set_facecolor('#FFFAF0')

    # Calcular densidad diferencial
    X, Y, Z_pos, Z_neg = calcular_densidad_diferencial(
        df_sujeto, df_referencia, n_grid=n_grid, bw=bw
    )

    # Umbral para no pintar ruido
    pos_mean = Z_pos[Z_pos > 0].mean() if np.any(Z_pos > 0) else 0
    neg_mean = Z_neg[Z_neg > 0].mean() if np.any(Z_neg > 0) else 0

    # Capa 1: donde tira MÁS (rojo)
    if pos_mean > 0:
        Z_pos_filtered = np.where(Z_pos >= pos_mean * 0.5, Z_pos, 0)
        # Contorno relleno
        ax.contourf(
            X, Y, np.sqrt(Z_pos_filtered),
            levels=8, cmap='Reds', alpha=0.7,
            extend='max'
        )
        # Líneas de contorno
        ax.contour(
            X, Y, np.sqrt(Z_pos_filtered),
            levels=4, colors=['#cc0000'], linewidths=0.3, alpha=0.5
        )

    # Capa 2: donde tira MENOS (gris)
    if neg_mean > 0:
        Z_neg_filtered = np.where(Z_neg >= neg_mean * 0.5, Z_neg, 0)
        ax.contourf(
            X, Y, np.sqrt(Z_neg_filtered),
            levels=8, cmap='Greys', alpha=0.4,
            extend='max'
        )
        ax.contour(
            X, Y, np.sqrt(Z_neg_filtered),
            levels=4, colors=['#888888'], linewidths=0.3, alpha=0.4
        )

    # Dibujar cancha encima
    dibujar_cancha(ax)

    # Título
    if titulo:
        ax.set_title(titulo, fontsize=14, fontweight='bold', pad=10)

    fig.tight_layout()
    return fig


def generar_shot_chart_volumen(df_tiros, titulo="", n_grid=120, bw=1.2):
    """
    Heatmap de volumen individual: dónde concentra más intentos de tiro.
    Usa KDE absoluto (sin comparar con referencia).
    """
    fig, ax = plt.subplots(figsize=(6, 6), facecolor='#FFFAF0')
    ax.set_facecolor('#FFFAF0')

    sx = df_tiros['court_x'].values
    sy = df_tiros['court_y'].values

    if len(sx) >= 5:
        half_w = COURT_WIDTH / 2.0
        max_y = THREE_PT_RADIUS + 3.0
        baseline_y = -BASKET_FROM_ENDLINE

        x_grid = np.linspace(-half_w, half_w, n_grid)
        y_grid = np.linspace(baseline_y, max_y, n_grid)
        X, Y = np.meshgrid(x_grid, y_grid)
        positions = np.vstack([X.ravel(), Y.ravel()])

        try:
            kde = gaussian_kde(np.vstack([sx, sy]), bw_method=bw)
            Z = kde(positions).reshape(X.shape)

            ax.contourf(
                X, Y, np.sqrt(Z),
                levels=10, cmap='YlOrRd', alpha=0.75,
                extend='max'
            )
            ax.contour(
                X, Y, np.sqrt(Z),
                levels=5, colors=['#cc3300'], linewidths=0.4, alpha=0.5
            )
        except Exception:
            pass

    dibujar_cancha(ax)

    if titulo:
        ax.set_title(f"{titulo} — Volumen", fontsize=14, fontweight='bold', pad=10)

    fig.tight_layout()
    return fig


def generar_shot_chart_eficiencia(df_tiros, titulo="", gridsize=8, min_tiros=3):
    """
    Mapa de eficiencia por zona usando hexbin.
    Cada hexágono muestra el FG% de esa zona, coloreado de azul (bajo) a rojo (alto).
    Solo muestra zonas con al menos min_tiros intentos.
    """
    from matplotlib.colors import Normalize

    fig, ax = plt.subplots(figsize=(6, 6), facecolor='#FFFAF0')
    ax.set_facecolor('#FFFAF0')

    dibujar_cancha(ax)

    if 'r' not in df_tiros.columns or len(df_tiros) < 5:
        if titulo:
            ax.set_title(f"{titulo} — Eficiencia", fontsize=14, fontweight='bold', pad=10)
        fig.tight_layout()
        return fig

    cx = df_tiros['court_x'].values
    cy = df_tiros['court_y'].values
    r = df_tiros['r'].values.astype(float)

    half_w = COURT_WIDTH / 2.0
    max_y = THREE_PT_RADIUS + 3.0
    baseline_y = -BASKET_FROM_ENDLINE

    # Hexbin con conteo para filtrar zonas con pocos tiros
    hb_count = ax.hexbin(
        cx, cy, gridsize=gridsize,
        extent=[-half_w, half_w, baseline_y, max_y],
        mincnt=1, reduce_C_function=np.size, C=r,
        alpha=0
    )
    # Hexbin con FG%
    hb_pct = ax.hexbin(
        cx, cy, C=r, gridsize=gridsize,
        extent=[-half_w, half_w, baseline_y, max_y],
        reduce_C_function=np.mean, mincnt=1,
        alpha=0
    )

    counts = hb_count.get_array()
    pcts = hb_pct.get_array()
    offsets = hb_pct.get_offsets()

    # Escala de colores: 0%=azul frio, 50%=blanco, 100%=rojo caliente
    norm = Normalize(vmin=0, vmax=1.0)
    cmap = plt.cm.RdYlBu_r  # rojo=alto, azul=bajo

    for i, (offset, pct, cnt) in enumerate(zip(offsets, pcts, counts)):
        if cnt < min_tiros:
            continue
        x_hex, y_hex = offset
        color = cmap(norm(pct))
        # Tamaño proporcional al volumen (entre 0.4 y 1.0 del máximo)
        size_factor = 0.4 + 0.6 * min(cnt / counts.max(), 1.0)
        hex_radius = (half_w * 2 / gridsize) * 0.55 * size_factor

        hexagon = plt.Polygon(
            _hex_vertices(x_hex, y_hex, hex_radius),
            facecolor=color, edgecolor='#444', linewidth=0.5,
            alpha=0.8, zorder=2
        )
        ax.add_patch(hexagon)

        # Texto con FG% y conteo
        fg_str = f"{pct * 100:.0f}%"
        cnt_str = f"{int(cnt)}"
        ax.text(x_hex, y_hex + 0.12, fg_str,
                ha='center', va='center', fontsize=7, fontweight='bold',
                color='white' if pct > 0.55 or pct < 0.25 else '#222', zorder=3)
        ax.text(x_hex, y_hex - 0.25, cnt_str,
                ha='center', va='center', fontsize=5.5,
                color='white' if pct > 0.55 or pct < 0.25 else '#555', zorder=3)

    # Redibujar cancha encima de los hexágonos
    dibujar_cancha(ax)

    if titulo:
        ax.set_title(f"{titulo} — Eficiencia", fontsize=14, fontweight='bold', pad=10)

    fig.tight_layout()
    return fig


def _hex_vertices(cx, cy, r):
    """Genera los 6 vértices de un hexágono centrado en (cx, cy) con radio r."""
    angles = np.linspace(0, 2 * np.pi, 7)[:-1] + np.pi / 6  # flat-top
    return [(cx + r * np.cos(a), cy + r * np.sin(a)) for a in angles]


def _smooth_arc_edges(court_coords, arc_radius=THREE_PT_RADIUS, tolerance=0.6, n_interp=25):
    """
    Reemplaza segmentos rectos que caen sobre el arco de 3 puntos
    con puntos interpolados sobre el arco real para que se vea suave.
    """
    smoothed = []
    n = len(court_coords)
    for i in range(n):
        x1, y1 = court_coords[i]
        x2, y2 = court_coords[(i + 1) % n]

        smoothed.append((x1, y1))

        d1 = np.sqrt(x1**2 + y1**2)
        d2 = np.sqrt(x2**2 + y2**2)

        # Ambos puntos cerca del arco y en el semicírculo superior
        if (abs(d1 - arc_radius) < tolerance and abs(d2 - arc_radius) < tolerance
                and y1 > 0.5 and y2 > 0.5):
            angle1 = np.arctan2(y1, x1)
            angle2 = np.arctan2(y2, x2)

            diff_a = angle2 - angle1
            if diff_a > np.pi:
                angle2 -= 2 * np.pi
            elif diff_a < -np.pi:
                angle2 += 2 * np.pi

            angles = np.linspace(angle1, angle2, n_interp + 2)[1:-1]
            for a in angles:
                smoothed.append((arc_radius * np.cos(a), arc_radius * np.sin(a)))

    return smoothed


# Offsets manuales para evitar solapamiento de etiquetas (en metros)
_LABEL_OFFSETS = {
    2: (0, 0.5),        # Paint: subir
    3: (0.3, -1.0),     # Mid Left: bajar
    4: (0, -0.5),       # Mid Center: bajar
    5: (-0.3, -1.0),    # Mid Right: bajar
    7: (0.3, 1.2),      # Triple Left: subir
    8: (0, 0.8),        # Triple Center: subir
    9: (-0.3, 1.2),     # Triple Right: subir
}

_ZONE_NAMES = {
    1: "Rim", 2: "Paint", 3: "Mid Left", 4: "Mid Center", 5: "Mid Right",
    6: "Corner Left", 7: "Triple Left", 8: "Triple Center",
    9: "Triple Right", 10: "Corner Right",
}


def _polygon_centroid(coords):
    """True geometric centroid of a closed polygon."""
    n = len(coords)
    if n < 3:
        return (sum(c[0] for c in coords) / n, sum(c[1] for c in coords) / n)
    A = 0.0
    Cx = 0.0
    Cy = 0.0
    for i in range(n):
        x0, y0 = coords[i]
        x1, y1 = coords[(i + 1) % n]
        cross = x0 * y1 - x1 * y0
        A += cross
        Cx += (x0 + x1) * cross
        Cy += (y0 + y1) * cross
    A *= 0.5
    if abs(A) < 1e-10:
        return (sum(c[0] for c in coords) / n, sum(c[1] for c in coords) / n)
    Cx /= (6.0 * A)
    Cy /= (6.0 * A)
    return (Cx, Cy)


def _build_court_zone_polygons(n_arc=30):
    """
    Build zone polygons in court coordinates (meters) aligned exactly
    with the court drawn by dibujar_cancha().
    Returns {zone_num: [(x, y), ...]}.
    """
    half_w = COURT_WIDTH / 2.0
    baseline = -BASKET_FROM_ENDLINE
    max_y = THREE_PT_RADIUS + 3.0

    paint_hw = PAINT_WIDTH / 2.0
    paint_top = PAINT_LENGTH - BASKET_FROM_ENDLINE

    three_x = half_w - THREE_PT_CORNER_DIST
    corner_y = np.sqrt(THREE_PT_RADIUS**2 - three_x**2)

    R = THREE_PT_RADIUS
    rim_r = 1.4
    rim_bottom = -HOOP_RADIUS * 2

    # Angles where the 3-pt arc meets the corner lines
    angle_right = np.arctan2(corner_y, three_x)
    angle_left = np.pi - angle_right
    # Divide arc into three equal sections
    arc_span = angle_left - angle_right
    angle_rc = angle_right + arc_span / 3.0   # right-center boundary
    angle_cl = angle_right + 2.0 * arc_span / 3.0  # center-left boundary

    def arc_pts(radius, a_start, a_end, n=n_arc):
        return [(radius * np.cos(a), radius * np.sin(a))
                for a in np.linspace(a_start, a_end, n)]

    # Where the radial division lines hit the top of the chart
    x_cl_top = max_y * np.cos(angle_cl) / np.sin(angle_cl)
    x_rc_top = max_y * np.cos(angle_rc) / np.sin(angle_rc)

    # 1 - Rim (semicircle around basket)
    z1 = [(rim_r, rim_bottom)] + arc_pts(rim_r, 0, np.pi) + [(-rim_r, rim_bottom)]

    # 2 - Paint
    z2 = [(-paint_hw, baseline), (paint_hw, baseline),
          (paint_hw, paint_top), (-paint_hw, paint_top)]

    # 3 - Mid Left (paint left → 3pt arc left portion → corner line)
    z3 = ([(-paint_hw, baseline), (-paint_hw, paint_top)]
          + arc_pts(R, angle_cl, angle_left)
          + [(-three_x, baseline)])

    # 4 - Mid Center (paint top → 3pt arc top portion)
    z4 = ([(-paint_hw, paint_top)]
          + arc_pts(R, angle_cl, angle_rc)
          + [(paint_hw, paint_top)])

    # 5 - Mid Right (paint right → 3pt arc right portion → corner line)
    z5 = ([(paint_hw, baseline), (paint_hw, paint_top)]
          + arc_pts(R, angle_rc, angle_right)
          + [(three_x, baseline)])

    # 6 - Corner Left
    z6 = [(-half_w, baseline), (-three_x, baseline),
          (-three_x, corner_y), (-half_w, corner_y)]

    # 7 - Triple Left (sideline → top → radial line → 3pt arc left)
    z7 = ([(-half_w, corner_y), (-half_w, max_y), (x_cl_top, max_y)]
          + arc_pts(R, angle_cl, angle_left))

    # 8 - Triple Center (between radial lines, above 3pt arc)
    z8 = ([(x_cl_top, max_y), (x_rc_top, max_y)]
          + arc_pts(R, angle_rc, angle_cl))

    # 9 - Triple Right (sideline → top → radial line → 3pt arc right)
    z9 = ([(half_w, corner_y), (half_w, max_y), (x_rc_top, max_y)]
          + arc_pts(R, angle_right, angle_rc)[::-1])

    # 10 - Corner Right
    z10 = [(three_x, baseline), (half_w, baseline),
           (half_w, corner_y), (three_x, corner_y)]

    return {1: z1, 2: z2, 3: z3, 4: z4, 5: z5,
            6: z6, 7: z7, 8: z8, 9: z9, 10: z10}


def generar_shot_chart_zonas(df_tiros, titulo="", df_liga=None):
    """
    Mapa de zonas predefinidas (10 zonas de tiro_zonas.py).
    Colorea cada zona por FG% relativo al promedio de liga (si se provee).
    Requiere columnas x, y (normalizadas 0-100) y r (1=anotado, 0=fallado).
    """
    from cron.tiro_zonas import classify_shot
    from matplotlib.colors import TwoSlopeNorm, Normalize

    fig, ax = plt.subplots(figsize=(6, 6), facecolor='#FFFAF0')
    ax.set_facecolor('#FFFAF0')

    # Clasificar tiros del equipo
    df = df_tiros.copy()
    df['zona'] = df.apply(lambda row: classify_shot(row['x'], row['y']), axis=1)
    df = df.dropna(subset=['zona'])
    df['zona'] = df['zona'].astype(int)

    stats = df.groupby('zona').agg(
        intentos=('r', 'count'),
        anotados=('r', 'sum')
    ).reset_index()
    stats['fg_pct'] = stats['anotados'] / stats['intentos']
    stats_dict = {int(row['zona']): row for _, row in stats.iterrows()}

    # Benchmark: promedios de liga por zona
    liga_pct_dict = {}
    if df_liga is not None and not df_liga.empty:
        df_l = df_liga.copy()
        df_l['zona'] = df_l.apply(lambda row: classify_shot(row['x'], row['y']), axis=1)
        df_l = df_l.dropna(subset=['zona'])
        df_l['zona'] = df_l['zona'].astype(int)
        liga_stats = df_l.groupby('zona').agg(
            intentos=('r', 'count'),
            anotados=('r', 'sum')
        ).reset_index()
        liga_stats['fg_pct'] = liga_stats['anotados'] / liga_stats['intentos']
        liga_pct_dict = {int(row['zona']): float(row['fg_pct']) for _, row in liga_stats.iterrows()}

    use_benchmark = len(liga_pct_dict) > 0

    if use_benchmark:
        cmap = plt.cm.RdYlBu_r
        norm = TwoSlopeNorm(vmin=-0.15, vcenter=0.0, vmax=0.15)
    else:
        cmap = plt.cm.RdYlBu_r
        norm = Normalize(vmin=0.2, vmax=0.6)

    court_zone_polys = _build_court_zone_polygons()

    for zone_num, court_coords in court_zone_polys.items():
        zone_name = _ZONE_NAMES[zone_num]

        if zone_num in stats_dict:
            s = stats_dict[zone_num]
            pct = float(s['fg_pct'])
            intentos = int(s['intentos'])
            anotados = int(s['anotados'])

            if use_benchmark:
                liga_pct = liga_pct_dict.get(zone_num, pct)
                diff = pct - liga_pct
                color = cmap(norm(diff))
            else:
                color = cmap(norm(pct))
                diff = 0
            alpha = 0.5
        else:
            pct = 0
            intentos = 0
            anotados = 0
            diff = 0
            color = '#e0e0e0'
            alpha = 0.25

        poly = plt.Polygon(
            court_coords, facecolor=color, edgecolor='#555',
            linewidth=0.6, alpha=alpha, zorder=1
        )
        ax.add_patch(poly)

        # Etiqueta en el centroide con offset manual
        centroid_x, centroid_y = _polygon_centroid(court_coords)

        dx, dy = _LABEL_OFFSETS.get(zone_num, (0, 0))
        centroid_x += dx
        centroid_y += dy

        if intentos > 0:
            if use_benchmark:
                sign = "+" if diff >= 0 else ""
                label = f"{zone_name}\n{anotados}/{intentos}\n{pct * 100:.0f}% ({sign}{diff * 100:.0f})"
            else:
                label = f"{zone_name}\n{anotados}/{intentos}\n{pct * 100:.0f}%"
        else:
            label = f"{zone_name}\n—"

        ax.text(
            centroid_x, centroid_y, label,
            ha='center', va='center', fontsize=7, fontweight='bold',
            color='#111', zorder=3
        )

    dibujar_cancha(ax)

    if titulo:
        ax.set_title(f"{titulo} — Zonas vs Liga", fontsize=14, fontweight='bold', pad=10)

    fig.tight_layout()
    return fig


def generar_shot_chart_scatter(df_tiros, titulo=""):
    """
    Genera un mapa de tiro tipo scatter: puntos verdes = anotados, rojos = fallados.
    Requiere columnas court_x, court_y y r (1=anotado, 0=fallado).
    """
    fig, ax = plt.subplots(figsize=(6, 6), facecolor='#FFFAF0')
    ax.set_facecolor('#FFFAF0')

    dibujar_cancha(ax)

    if 'r' in df_tiros.columns:
        df_made = df_tiros[df_tiros['r'] == 1]
        df_miss = df_tiros[df_tiros['r'] == 0]

        # Fallados primero (abajo), anotados encima
        ax.scatter(
            df_miss['court_x'], df_miss['court_y'],
            c='#e74c3c', marker='x', s=28, linewidths=0.8,
            alpha=0.6, label=f'Fallados ({len(df_miss)})', zorder=2
        )
        ax.scatter(
            df_made['court_x'], df_made['court_y'],
            c='#27ae60', marker='o', s=22, linewidths=0.5,
            alpha=0.7, label=f'Anotados ({len(df_made)})', zorder=3,
            edgecolors='#1a7a42'
        )

        ax.legend(loc='upper right', fontsize=8, framealpha=0.8)

    if titulo:
        ax.set_title(f"{titulo} — Tiros", fontsize=14, fontweight='bold', pad=10)

    fig.tight_layout()
    return fig


def generar_shot_chart_simple(df_tiros, titulo="", n_grid=150, bw=1.0):
    """
    Genera un mapa de tiro con solo densidad absoluta (sin comparar con referencia).
    Útil cuando no hay suficientes datos para comparación relativa.
    """
    fig, ax = plt.subplots(figsize=(6, 6), facecolor='#FFFAF0')
    ax.set_facecolor('#FFFAF0')

    sx = df_tiros['court_x'].values
    sy = df_tiros['court_y'].values

    if len(sx) >= 10:
        half_w = COURT_WIDTH / 2.0
        max_y = THREE_PT_RADIUS + 3.0
        baseline_y = -BASKET_FROM_ENDLINE

        x_grid = np.linspace(-half_w, half_w, n_grid)
        y_grid = np.linspace(baseline_y, max_y, n_grid)
        X, Y = np.meshgrid(x_grid, y_grid)
        positions = np.vstack([X.ravel(), Y.ravel()])

        try:
            kde = gaussian_kde(np.vstack([sx, sy]), bw_method=bw)
            Z = kde(positions).reshape(X.shape)

            ax.contourf(
                X, Y, np.sqrt(Z),
                levels=10, cmap='Reds', alpha=0.7,
                extend='max'
            )
            ax.contour(
                X, Y, np.sqrt(Z),
                levels=5, colors=['#cc0000'], linewidths=0.3, alpha=0.5
            )
        except Exception:
            pass

    # Dibujar cancha
    dibujar_cancha(ax)

    if titulo:
        ax.set_title(titulo, fontsize=14, fontweight='bold', pad=10)

    fig.tight_layout()
    return fig
