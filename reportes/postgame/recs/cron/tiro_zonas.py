"""
Clasificador de zonas de tiro.
Determina la zona (1-10) a partir de coordenadas normalizadas (x, y) en rango 0-100.

Zonas:
  1 - Rim            6 - Corner Left
  2 - Paint          7 - Triple Left
  3 - Mid Left       8 - Triple Center
  4 - Mid Center     9 - Triple Right
  5 - Mid Right     10 - Corner Right
"""

from typing import List, Optional

# Dimensiones de la imagen de referencia en píxeles
IMAGE_WIDTH = 891
IMAGE_HEIGHT = 532

# Definición de zonas con sus polígonos (coordenadas en píxeles)
ZONES = [
    {"num": 1, "name": "Rim", "coords": [[38,218],[53,219],[68,223],[80,232],[91,246],[95,270],[90,286],[83,296],[71,308],[56,314],[38,314]]},
    {"num": 2, "name": "Paint", "coords": [[7,354],[183,352],[183,182],[5,179]]},
    {"num": 3, "name": "Mid Left", "coords": [[5,177],[186,180],[239,159],[234,146],[228,133],[212,110],[195,93],[179,79],[158,64],[141,56],[121,47],[100,39],[5,41]]},
    {"num": 4, "name": "Mid Center", "coords": [[183,183],[239,160],[249,179],[254,195],[259,216],[262,235],[265,257],[264,284],[260,310],[254,337],[247,357],[241,374],[184,352]]},
    {"num": 5, "name": "Mid Right", "coords": [[5,355],[185,354],[238,374],[232,389],[225,403],[216,418],[205,431],[186,449],[166,464],[148,475],[127,484],[98,493],[5,492]]},
    {"num": 6, "name": "Corner Left", "coords": [[5,40],[99,40],[99,1],[5,1]]},
    {"num": 7, "name": "Triple Left", "coords": [[100,39],[100,0],[444,3],[445,76],[241,156],[236,144],[226,127],[220,116],[208,101],[197,90],[180,76],[164,65],[148,57],[137,51],[116,43]]},
    {"num": 8, "name": "Triple Center", "coords": [[240,159],[445,78],[444,458],[241,374],[251,354],[258,331],[263,304],[266,277],[267,254],[263,226],[258,199],[253,181],[247,169]]},
    {"num": 9, "name": "Triple Right", "coords": [[445,527],[97,527],[99,495],[118,488],[134,485],[150,476],[170,465],[186,452],[204,436],[218,419],[231,400],[240,382],[241,375],[444,459]]},
    {"num": 10, "name": "Corner Right", "coords": [[5,495],[98,494],[97,530],[4,528]]}
]


def _is_point_in_polygon(x: float, y: float, polygon: List[List[float]]) -> bool:
    """Determina si un punto está dentro de un polígono usando ray casting."""
    inside = False
    n = len(polygon)
    p1x, p1y = polygon[0]

    for i in range(1, n + 1):
        p2x, p2y = polygon[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y

    return inside


def _transform_coordinates(x_normalized: float, y_normalized: float) -> tuple:
    """Transforma coordenadas normalizadas (0-100) a píxeles."""
    if x_normalized >= 50:
        x_pixels = ((100 - x_normalized) / 100) * IMAGE_WIDTH
    else:
        x_pixels = (x_normalized / 100) * IMAGE_WIDTH

    y_pixels = (y_normalized / 100) * IMAGE_HEIGHT
    return x_pixels, y_pixels


def classify_shot(x_normalized: float, y_normalized: float) -> Optional[int]:
    """
    Clasifica un tiro y retorna el número de zona (1-10).
    Retorna None si las coordenadas no caen en ninguna zona definida.

    Args:
        x_normalized: coordenada X normalizada (0-100)
        y_normalized: coordenada Y normalizada (0-100)
    """
    x_pixels, y_pixels = _transform_coordinates(x_normalized, y_normalized)

    for zone in ZONES:
        if _is_point_in_polygon(x_pixels, y_pixels, zone["coords"]):
            return zone["num"]

    return None
