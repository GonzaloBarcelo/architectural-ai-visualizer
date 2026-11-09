"""CAD naming conventions in one place: layer patterns, block synonyms and hatch finishes.

Names are matched after normalisation: accents removed, upper case (``a.secció`` → ``A.SECCIO``).
Patterns are regular expressions searched anywhere in the normalised name. Spanish, Catalan and
AIA/English conventions are included; add an office's own names here.
"""

import re
import unicodedata
from difflib import SequenceMatcher

# Layers whose cut geometry (solid hatches, closed outlines, parallel line pairs) are walls.
WALL_LAYERS = [
    r"\bMUROS?\b",
    r"TABIQU",
    r"A[-_ ]WALL",
    r"\bWALLS?\b",
    r"CERRAMIENT",
    r"FABRICA",
    r"SECCI",  # sección / secció: the cut walls of a plan
    r"\bPARED",
    r"\bPARETS?\b",
    r"TANCAMENT",
    r"\bPILAR",
    r"A[-_ ]COLS",
]
DOOR_LAYERS = [r"PUERTA", r"\bPORTES?\b", r"A[-_ ]DOOR", r"\bDOORS?\b"]
WINDOW_LAYERS = [r"VENTANA", r"FINESTR", r"A[-_ ]GLAZ", r"WINDOW", r"VIDRIER"]
# Joinery layers hold both doors and windows: evidence of an opening, not of its kind.
CARPENTRY_LAYERS = [r"CARPINTER", r"FUSTERI", r"A[-_ ]OPEN", r"JOINERY"]
FURNITURE_LAYERS = [
    r"MOBL",
    r"MOBIL",
    r"MUEBLE",
    r"A[-_ ]FURN",
    r"FURN",
    r"EQUIP",
    r"SANITARI",
    r"A[-_ ]FLOR",
    r"APARAT",
]
# Layers never read as architecture or furniture (texts on them still name rooms).
IGNORED_LAYERS = [
    r"COTA",
    r"\bDIM",
    r"HABITABILIDAD",
    r"CAJETIN",
    r"A[-_ ]ANNO",
    r"DEFPOINTS",
    r"VIEWPORT",
    r"\bEJES?\b",
    r"REJILLA",
    r"DEMOLI",  # demolished walls must never be read as walls
    r"NOPLOT",
]

# Block names. A door/window block in a wall gap gives the opening kind directly.
DOOR_BLOCKS = [r"PUERTA", r"\bPORTA\b", r"DOOR", r"BALCONERA"]
WINDOW_BLOCKS = [r"VENTANA", r"FINESTRA", r"WINDOW"]
SLIDING = [r"CORREDER", r"CORREDIS", r"SLIDING", r"\bSLIDE"]
POCKET = [r"POCKET", r"CASONETO", r"EMPOTRAD", r"\bKRONA"]
FIXED = [r"\bFIJ[OA]", r"FIXED", r"\bFIXE"]
# Blocks that are annotation, never furniture.
ANNOTATION_BLOCKS = [
    r"^DIM\b",
    r"COTA",
    r"NORTE",
    r"\bNORD\b",
    r"NORTH",
    r"CAJETIN",
    r"TITLE",
    r"HABITAB",
    r"SIMBOL",
    r"FLECHA",
    r"ARROW",
    r"LEYENDA",
    r"\bEJE\b",
]

# Block name / attribute synonym table → FurnitureKind. "bed" resolves by width below.
BLOCK_SYNONYMS = [
    (r"MESITA|MESA DE NOCHE|TAULETA DE NIT|NIGHTSTAND|BEDSIDE", "nightstand"),
    (r"\bCAMA|\bLLIT|\bBED\b|LITERA", "bed"),
    (r"INODORO|\bWC\b|\bVATER|\bINODOR|TOILET|\bLAVATORY", "toilet"),
    (r"\bBIDE?T?\b", "bidet"),
    (r"LAVABO|RENTAMANS|WASHBASIN|\bBASIN|VANITY", "washbasin"),
    (r"DUCHA|DUTXA|SHOWER|PLATO DE DUCHA", "shower"),
    (r"BANERA|BANYERA|BATHTUB|\bBATH\b|\bTUB\b", "bathtub"),
    (r"BUTACA|SILLON|ARMCHAIR|\bBUTACA", "armchair"),
    (r"\bSOFA|\bCHAISE|COUCH", "sofa"),
    (r"MESA (DE )?CENTRO|MESA BAJA|COFFEE", "coffee_table"),
    (r"MESA AUXILIAR|SIDE ?TABLE", "side_table"),
    (r"COMEDOR|DINING", "dining_set"),
    (r"\bMESA\b|\bTAULA\b|\bTABLE\b", "dining_table"),
    (r"TABURETE|TAMBORET|\bSTOOL", "stool"),
    (r"\bSILLA|CADIRA|\bCHAIR", "chair"),
    (r"ARMARIO|\bARMARI\b|WARDROBE|CLOSET|ROPERO", "wardrobe"),
    (r"COMODA|CALAIXERA|DRESSER|CAJONERA", "dresser"),
    (r"ESCRITORIO|\bDESK", "desk"),
    (r"ESTANTERIA|LIBRERIA|PRESTATGERIA|SHELF|SHELV|BOOKCASE", "shelving"),
    (r"NEVERA|FRIGO|FRIDGE|REFRIG", "fridge"),
    (r"LAVADORA|RENTADORA|WASHING|SECADORA|DRYER", "washing_machine"),
    (r"\bISLA\b|\bILLA\b|ISLAND", "kitchen_island"),
    (r"COCINA|ENCIMERA|\bCUINA|KITCHEN|COUNTER|FREGADERO|VITRO|\bHORNO", "kitchen_counter"),
    (r"ALFOMBRA|CATIFA|\bRUG\b|CARPET", "rug"),
    (r"MUEBLE TV|\bTV\b|TELEVIS", "tv_unit"),
    (r"APARADOR|SIDEBOARD|BUFET", "sideboard"),
    (r"MACETA|\bTESTO\b|\bPLANTS?\b|\bPOT\b", "plant"),
    (r"LAMPARA|\bLAMP\b", "floor_lamp"),
]
# Beds at least this wide (m, shorter side) are double beds.
DOUBLE_BED_WIDTH = 1.2

# Floor hatch pattern → finish. Unlisted patterns are asked to the AI, otherwise "unknown".
HATCH_FINISHES = {
    "tile": [r"ANSI37", r"^NET\b", r"GRID", r"SQUARE", r"TILE", r"BALDOS", r"GRES", r"AR-B816"],
    "wood": [r"WOOD", r"PARQ", r"MADERA", r"FUSTA", r"AR-PARQ", r"AR-HBONE"],
    "stone": [r"MARBLE", r"MARMOL", r"PIEDRA", r"STONE", r"\bPEDRA"],
}

# Geometric limits (metres).
WALL_MAX_MEAN_WIDTH = 0.6  # solid hatches / closed outlines thinner than this are walls
PATTERN_WALL_MAX_MEAN_WIDTH = 0.45  # patterned hatches on wall layers (floors are wider)
WALL_LINE_PAIR = (0.05, 0.6)  # parallel line pair spacing read as a wall
GAP_WIDTH = (0.45, 3.6)  # opening widths searched between facing wall ends
GAP_DEPTH = (0.07, 0.7)  # wall thickness at an opening (partitions are ≥ 7 cm)
PLAN_CLUSTER_DISTANCE = 1.5  # walls closer than this belong to the same drawing
PLAN_MARGIN = 1.5  # metres drawn around the plan in the review image


def normalise(name):
    text = unicodedata.normalize("NFKD", str(name or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).upper()


def matches(name, patterns):
    value = normalise(name)
    return any(re.search(p, value) for p in patterns)


# Whole words for typo-tolerant layer names (e.g. "a.venatana" → VENTANA, "a.mobel" → MOBLE).
LAYER_WORDS = {
    "ignored": ["COTAS", "CAJETIN", "HABITABILIDAD", "DEMOLICION", "DEMOLICIO"],
    "wall": [
        "MUROS",
        "TABIQUES",
        "TABIQUERIA",
        "SECCION",
        "SECCIO",
        "CERRAMIENTO",
        "PARED",
        "PAREDES",
        "FABRICA",
        "PILARES",
    ],
    "door": ["PUERTA", "PUERTAS", "PORTES"],
    "window": ["VENTANA", "VENTANAS", "FINESTRA", "FINESTRES"],
    "carpentry": ["CARPINTERIA", "CARPINTERIAS", "FUSTERIA"],
    "furniture": [
        "MOBLE",
        "MOBLES",
        "MUEBLE",
        "MUEBLES",
        "MOBILIARIO",
        "MOBILIARI",
        "SANITARIOS",
        "SANITARIS",
        "EQUIPAMIENTO",
    ],
}
NEAR_SPELLING = 0.8  # SequenceMatcher ratio for a layer word of 5+ letters
ROLE_PATTERNS = [
    ("ignored", IGNORED_LAYERS),
    ("wall", WALL_LAYERS),
    ("door", DOOR_LAYERS),
    ("window", WINDOW_LAYERS),
    ("carpentry", CARPENTRY_LAYERS),
    ("furniture", FURNITURE_LAYERS),
]


def layer_match(layer):
    """(role, how): how is "nombre" for a listed pattern, "parecido a «WORD»" for a near
    spelling, or (None, None) when the layer name says nothing."""
    for role, patterns in ROLE_PATTERNS:
        if matches(layer, patterns):
            return role, "nombre"
    best = (0.0, None, None)
    for token in re.findall(r"[A-Z0-9]+", normalise(layer)):
        if len(token) < 5:
            continue
        for role, words in LAYER_WORDS.items():
            for word in words:
                ratio = SequenceMatcher(None, token, word).ratio()
                if ratio >= NEAR_SPELLING and ratio > best[0]:
                    best = (ratio, role, word)
    if best[1]:
        return best[1], f"parecido a «{best[2]}»"
    return None, None


def layer_role(layer):
    """'ignored' | 'wall' | 'door' | 'window' | 'carpentry' | 'furniture' | None."""
    return layer_match(layer)[0]


def furniture_kind(texts, width):
    """Kind from block name/attribute texts via the synonym table, or None if unknown."""
    for text in texts:
        value = normalise(text).replace("_", " ").replace("-", " ")
        for pattern, kind in BLOCK_SYNONYMS:
            if re.search(pattern, value):
                if kind == "bed":
                    return "bed_double" if width >= DOUBLE_BED_WIDTH else "bed_single"
                return kind
    return None


def hatch_finish(pattern):
    for finish, patterns in HATCH_FINISHES.items():
        if matches(pattern, patterns):
            return finish
    return None
