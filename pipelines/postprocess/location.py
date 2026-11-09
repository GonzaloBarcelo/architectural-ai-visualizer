"""Project location read deterministically from the drawing's own text (never invented).

Sources, in order of trust: a labelled address in the title block ("Dirección:",
"Emplazamiento:", "Situación:"…), an unlabelled address line with a street prefix, street names
written on the plan, and finally the filename (e.g. ``MAD_OlivoVerde``). Region,
country, latitude and climate are *derived* from the Spanish postal code or a known city and
are marked as such. The location only steers light, vegetation and the view through windows of
the AI enhancement; it never changes the building.
"""

import re
import unicodedata
from pathlib import Path

FALLBACK = "residencia mediterránea en España"

# Spanish postal-code prefix → (province, autonomous community, approx. latitude, climate).
PROVINCES = {
    "01": ("Álava", "País Vasco", 42.85, "atlantic"),
    "02": ("Albacete", "Castilla-La Mancha", 38.99, "continental"),
    "03": ("Alicante", "Comunitat Valenciana", 38.35, "mediterranean_coast"),
    "04": ("Almería", "Andalucía", 36.84, "mediterranean_coast"),
    "05": ("Ávila", "Castilla y León", 40.66, "continental"),
    "06": ("Badajoz", "Extremadura", 38.88, "continental"),
    "07": ("Illes Balears", "Illes Balears", 39.57, "mediterranean_coast"),
    "08": ("Barcelona", "Cataluña", 41.39, "mediterranean_coast"),
    "09": ("Burgos", "Castilla y León", 42.34, "continental"),
    "10": ("Cáceres", "Extremadura", 39.47, "continental"),
    "11": ("Cádiz", "Andalucía", 36.53, "south"),
    "12": ("Castellón", "Comunitat Valenciana", 39.99, "mediterranean_coast"),
    "13": ("Ciudad Real", "Castilla-La Mancha", 38.99, "continental"),
    "14": ("Córdoba", "Andalucía", 37.89, "south"),
    "15": ("A Coruña", "Galicia", 43.36, "atlantic"),
    "16": ("Cuenca", "Castilla-La Mancha", 40.07, "continental"),
    "17": ("Girona", "Cataluña", 41.98, "mediterranean_coast"),
    "18": ("Granada", "Andalucía", 37.18, "south"),
    "19": ("Guadalajara", "Castilla-La Mancha", 40.63, "continental"),
    "20": ("Gipuzkoa", "País Vasco", 43.32, "atlantic"),
    "21": ("Huelva", "Andalucía", 37.26, "south"),
    "22": ("Huesca", "Aragón", 42.14, "continental"),
    "23": ("Jaén", "Andalucía", 37.78, "south"),
    "24": ("León", "Castilla y León", 42.60, "continental"),
    "25": ("Lleida", "Cataluña", 41.62, "continental"),
    "26": ("La Rioja", "La Rioja", 42.47, "continental"),
    "27": ("Lugo", "Galicia", 43.01, "atlantic"),
    "28": ("Madrid", "Comunidad de Madrid", 40.42, "continental"),
    "29": ("Málaga", "Andalucía", 36.72, "mediterranean_coast"),
    "30": ("Murcia", "Región de Murcia", 37.99, "mediterranean_coast"),
    "31": ("Navarra", "Navarra", 42.81, "continental"),
    "32": ("Ourense", "Galicia", 42.34, "atlantic"),
    "33": ("Asturias", "Principado de Asturias", 43.36, "atlantic"),
    "34": ("Palencia", "Castilla y León", 42.01, "continental"),
    "35": ("Las Palmas", "Canarias", 28.12, "subtropical"),
    "36": ("Pontevedra", "Galicia", 42.43, "atlantic"),
    "37": ("Salamanca", "Castilla y León", 40.97, "continental"),
    "38": ("Santa Cruz de Tenerife", "Canarias", 28.46, "subtropical"),
    "39": ("Cantabria", "Cantabria", 43.46, "atlantic"),
    "40": ("Segovia", "Castilla y León", 40.95, "continental"),
    "41": ("Sevilla", "Andalucía", 37.39, "south"),
    "42": ("Soria", "Castilla y León", 41.76, "continental"),
    "43": ("Tarragona", "Cataluña", 41.12, "mediterranean_coast"),
    "44": ("Teruel", "Aragón", 40.34, "continental"),
    "45": ("Toledo", "Castilla-La Mancha", 39.86, "continental"),
    "46": ("Valencia", "Comunitat Valenciana", 39.47, "mediterranean_coast"),
    "47": ("Valladolid", "Castilla y León", 41.65, "continental"),
    "48": ("Bizkaia", "País Vasco", 43.26, "atlantic"),
    "49": ("Zamora", "Castilla y León", 41.50, "continental"),
    "50": ("Zaragoza", "Aragón", 41.65, "continental"),
    "51": ("Ceuta", "Ceuta", 35.89, "mediterranean_coast"),
    "52": ("Melilla", "Melilla", 35.29, "mediterranean_coast"),
}
# City names (normalised) → postal prefix, for addresses without a postal code.
CITIES = {
    **{k: p for p, (k, *_rest) in PROVINCES.items()},
    "Bilbao": "48",
    "Vigo": "36",
    "Gijón": "33",
    "Oviedo": "33",
    "Santander": "39",
    "Pamplona": "31",
    "Iruña": "31",
    "Vitoria": "01",
    "Vitoria-Gasteiz": "01",
    "San Sebastián": "20",
    "Donostia": "20",
    "Palma": "07",
    "Palma de Mallorca": "07",
    "Ibiza": "07",
    "Eivissa": "07",
    "Marbella": "29",
    "Estepona": "29",
    "Elche": "03",
    "Benidorm": "03",
    "Cartagena": "30",
    "Jerez de la Frontera": "11",
    "Algeciras": "11",
    "Santiago de Compostela": "15",
    "Logroño": "26",
    "Alcalá de Henares": "28",
    "Getafe": "28",
    "Móstoles": "28",
    "Pozuelo de Alarcón": "28",
    "Majadahonda": "28",
    "Las Rozas": "28",
    "Alcobendas": "28",
    "Leganés": "28",
    "Sabadell": "08",
    "Terrassa": "08",
    "Badalona": "08",
    "L'Hospitalet de Llobregat": "08",
    "Sitges": "08",
    "Reus": "43",
    "Gandia": "46",
    "Dénia": "03",
    "Jávea": "03",
    "Xàbia": "03",
}
# Studio filename prefixes (IATA-style city codes).
CITY_CODES = {
    "MAD": "Madrid",
    "BCN": "Barcelona",
    "VLC": "Valencia",
    "VAL": "Valencia",
    "SVQ": "Sevilla",
    "SEV": "Sevilla",
    "AGP": "Málaga",
    "MLG": "Málaga",
    "BIO": "Bilbao",
    "BIL": "Bilbao",
    "ZAZ": "Zaragoza",
    "ZGZ": "Zaragoza",
    "PMI": "Palma",
    "ALC": "Alicante",
    "MJV": "Murcia",
    "MUR": "Murcia",
    "SDR": "Santander",
    "OVD": "Oviedo",
    "VGO": "Vigo",
    "LPA": "Las Palmas",
    "GRX": "Granada",
    "IBZ": "Ibiza",
    "SCQ": "Santiago de Compostela",
}

LABEL = re.compile(
    r"^\s*(direcci[oó]n|emplazamiento|situaci[oó]n|ubicaci[oó]n|localizaci[oó]n|"
    r"domicilio|adre[cç]a|address|location|site)\b\s*(?:de la obra|de obra|del proyecto)?"
    r"\s*[:.\-]?\s*(.*)$",
    re.IGNORECASE,
)
STREET = re.compile(
    r"^\s*(c/|c\.|cl\.?|calle|carrer|avda\.?|avd\.?|av\.|avenida|avinguda|paseo|p[ºo°]\.?|"
    r"passeig|plaza|pza\.?|pl\.|pla[cç]a|ronda|camino|cam[ií]|ctra\.?|carretera|"
    r"traves[ií]a|glorieta|urb\.?|urbanizaci[oó]n|partida|pol[ií]gono|r[uú]a|rambla|"
    r"cuesta|costanilla|bulevar|v[ií]a)(?=[\s/.]|$)\s*",
    re.IGNORECASE,
)
PREFIX_NAMES = {
    "c/": "Calle",
    "c.": "Calle",
    "cl": "Calle",
    "cl.": "Calle",
    "avda": "Avenida",
    "avda.": "Avenida",
    "avd": "Avenida",
    "avd.": "Avenida",
    "av.": "Avenida",
    "pº": "Paseo",
    "po": "Paseo",
    "p°": "Paseo",
    "pº.": "Paseo",
    "pza": "Plaza",
    "pza.": "Plaza",
    "pl.": "Plaza",
    "ctra": "Carretera",
    "ctra.": "Carretera",
    "urb": "Urbanización",
    "urb.": "Urbanización",
}
RURAL = {"Camino", "Partida", "Polígono", "Carretera", "Urbanización", "Camí"}
POSTAL = re.compile(r"(?<![\d.,])((?:0[1-9]|[1-4]\d|5[0-2])\d{3})(?![\d.,]\d)")
CADASTRAL = re.compile(r"\b\d{7}[A-Z]{2}\d{4}[A-Z]\d{4}[A-Z]{2}\b")
SMALL_WORDS = {"de", "del", "la", "las", "los", "el", "y", "i", "d'", "en", "a"}


def _fold(text):
    return "".join(
        c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn"
    )


FOLDED_CITIES = {_fold(k): (k, v) for k, v in CITIES.items()}


def _title(text, leading=False):
    """Title case keeping Spanish particles lower case (also first, after a street prefix)."""
    words = text.strip().split()
    out = []
    for i, w in enumerate(words):
        low = w.lower()
        small = low in SMALL_WORDS and (i or leading)
        out.append(low if small else low[:1].upper() + low[1:])
    return " ".join(out)


def street_name(line):
    """'C/ Del Olivo, 12, 2ºB' → 'Calle del Olivo' (None if no prefix)."""
    m = STREET.match(line)
    if not m:
        return None
    prefix = m.group(1).lower()
    name = PREFIX_NAMES.get(prefix, _title(prefix))
    rest = re.split(r",|\s\d|\bn[ºo°]\b|\(", line[m.end() :], maxsplit=1)[0].strip(" .-/")
    if len(rest) < 3 or not re.search(r"[A-Za-zÀ-ÿ]{3}", rest):
        return None
    if rest.isupper():
        rest = _title(rest, leading=True)
    return f"{name} {rest}"


def city_in(text):
    """(city, postal code or None) found in free text, from the postal code or a known name."""
    postal = None
    for m in POSTAL.finditer(text):
        postal = m.group(1)
        before = text[: m.start()].rstrip(" (,-")
        after = text[m.end() :].lstrip(" )-,.")
        for chunk in (re.split(r"[,(\n]", before)[-1], re.split(r"[,(\n.]", after)[0]):
            name = chunk.strip(" .,-")
            if name and not re.search(r"\d", name) and len(name) >= 3:
                return _title(name) if name.isupper() else name, postal
    folded = _fold(text)
    best = None
    for key, (name, _) in FOLDED_CITIES.items():
        hit = re.search(rf"(?<![a-z]){re.escape(key)}(?![a-z])", folded)
        if hit and (best is None or len(key) > len(_fold(best))):
            best = name
    if best:
        return best, postal
    if postal:
        return PROVINCES[postal[:2]][0], postal
    return None, None


def province(city=None, postal=None):
    if postal and postal[:2] in PROVINCES:
        return postal[:2]
    if city:
        hit = FOLDED_CITIES.get(_fold(city))
        if hit:
            return hit[1]
    return None


def _address(lines):
    """Parse up to four address lines into (street, city, postal, text)."""
    kept = []
    for line in lines[:4]:
        if line.rstrip().endswith(":") or LABEL.match(line):
            break
        kept.append(line.strip())
    text = ", ".join(x.rstrip(" .") for x in kept if x)
    street = next((s for s in (street_name(x) for x in kept) if s), None)
    city, postal = city_in("\n".join(kept))
    return street, city, postal, text


def candidates(entries):
    """Address candidates with a confidence, from text entries {text, source}."""
    found = []
    for entry in entries:
        lines = [x.strip() for x in str(entry["text"]).splitlines() if x.strip()]
        labelled = False
        for i, line in enumerate(lines):
            m = LABEL.match(line)
            if not m:
                continue
            rest = ([m.group(2)] if m.group(2).strip() else []) + lines[i + 1 :]
            street, city, postal, text = _address(rest)
            if not text:
                continue
            labelled = True
            conf = 0.95 if (city or postal) and street else 0.85 if city or postal else 0.7
            found.append(
                {
                    "street": street,
                    "city": city,
                    "postal_code": postal,
                    "text": text,
                    "confidence": conf,
                    "method": "Dirección rotulada en el cajetín",
                    "source": entry["source"],
                    "rank": 3,
                }
            )
        if labelled:
            continue
        for i, line in enumerate(lines):
            street = street_name(line)
            if not street:
                continue
            block = "\n".join(lines[i : i + 3])
            city, postal = city_in(block) if POSTAL.search(block) else (None, None)
            on_plan = line.isupper() and not re.search(r"\d", line)
            found.append(
                {
                    "street": street,
                    "city": city,
                    "postal_code": postal,
                    "text": ", ".join(x.rstrip(" .") for x in lines[i : i + (2 if city else 1)]),
                    "confidence": 0.8 if city else 0.5,
                    "method": "Calle rotulada en el plano" if on_plan else "Línea de dirección",
                    "source": entry["source"],
                    "rank": 2 if city else 1,
                }
            )
    return found


def from_filename(filename):
    """Weak hint from the file name: city code prefix and a CamelCase street name."""
    stem = Path(filename or "").stem
    parts = re.split(r"[_\-\s]+", stem)
    city = next((CITY_CODES[p.upper()] for p in parts if p.upper() in CITY_CODES), None)
    street = None
    for p in parts:
        words = re.findall(r"[A-ZÁÉÍÓÚÑ][a-záéíóúñü]+", p)
        if len(words) >= 2 and "".join(words) == p:
            street = "Calle " + _title(" ".join(words))
            break
    if not city and not street:
        return None
    return {
        "street": street,
        "city": city,
        "postal_code": None,
        "text": ", ".join(x for x in (street, city) if x),
        "confidence": 0.4 if city and street else 0.3,
        "method": "Nombre del archivo",
        "source": {
            "kind": "filename",
            "value": Path(filename).name[:200],
            "label": "nombre del archivo",
        },
        "rank": 0,
    }


def complete(best, others, all_text=""):
    """Fill derived fields (region, country, latitude, climate) and the status."""
    loc = dict(best)
    loc.pop("rank", None)
    derived = []
    if not loc.get("city"):
        for other in others:
            if other.get("city") and other is not best:
                loc["city"], loc["postal_code"] = other["city"], other.get("postal_code")
                loc["confidence"] = round(min(loc["confidence"], other["confidence"]) * 0.9, 2)
                loc["city_source"] = other["source"]
                break
    code = province(loc.get("city"), loc.get("postal_code"))
    spanish = (
        bool(code)
        or bool(CADASTRAL.search(all_text))
        or bool(loc.get("street") and STREET.match(loc["street"]))
    )
    loc["region"] = loc["province"] = loc["latitude"] = loc["climate"] = None
    if code:
        name, region, lat, climate = PROVINCES[code]
        loc.update(province=name, region=region, latitude=lat, climate=climate)
        derived += ["province", "region", "latitude", "climate"]
    loc["country"] = "España" if spanish else None
    if spanish:
        derived.append("country")
    loc["derived"] = derived
    first = (loc.get("street") or "").split(" ")[0]
    loc["setting"] = "rural" if first in RURAL else "urban" if loc.get("street") else None
    loc["status"] = "verified" if best["source"].get("kind") in ("pdf", "dwg") else "inferred"
    loc["confidence"] = round(float(loc["confidence"]), 2)
    return loc


def locate(entries, filename=None):
    """Best location from text entries [{text, source}] plus the filename; never invented."""
    found = candidates(entries)
    hint = from_filename(filename)
    streets = sorted({c["street"] for c in found if c["method"] == "Calle rotulada en el plano"})
    all_text = "\n".join(str(e["text"]) for e in entries)
    ordered = sorted(found, key=lambda c: (c["rank"], c["confidence"]), reverse=True)
    if not ordered and not hint:
        return missing(nearby_streets=streets)
    best = ordered[0] if ordered else hint
    others = ordered[1:] + ([hint] if hint and hint is not best else [])
    loc = complete(best, others, all_text)
    cities = {_fold(c["city"]) for c in found if c.get("city")}
    if len(cities) > 1:
        loc["confidence"] = round(loc["confidence"] * 0.7, 2)
        loc["alternatives"] = sorted({c["text"] for c in found if c.get("city")})[:5]
    loc["nearby_streets"] = [s for s in streets if s != loc.get("street")][:6]
    return loc


def missing(**extra):
    return {
        "status": "missing",
        "text": "",
        "street": None,
        "city": None,
        "postal_code": None,
        "province": None,
        "region": None,
        "country": None,
        "latitude": None,
        "climate": None,
        "setting": None,
        "source": None,
        "confidence": 0.0,
        "method": None,
        "derived": [],
        **extra,
    }


def user_location(text, previous=None):
    """The user's own text from the review. Empty text → missing (fallback at approval)."""
    text = re.sub(r"\s+", " ", (text or "").strip())[:300]
    if not text:
        return missing(cleared_by_user=True)
    street = next((s for s in (street_name(p) for p in text.split(",")) if s), None)
    city, postal = city_in(text.replace(",", "\n"))
    best = {
        "street": street,
        "city": city,
        "postal_code": postal,
        "text": text,
        "confidence": 1.0,
        "method": "Indicada en la revisión",
        "source": {"kind": "user", "label": "indicada por el usuario"},
        "rank": 4,
    }
    loc = complete(best, [])
    loc["status"] = "user"
    if previous and previous.get("source") and previous.get("status") != "user":
        loc["detected"] = {k: previous.get(k) for k in ("text", "source", "confidence")}
    return loc


def pdf_entries(raw):
    entries = []
    for page in raw.get("pages", []):
        for i, block in enumerate(page.get("text_blocks", [])):
            if len(block) < 5 or not isinstance(block[4], str):
                continue
            entries.append(
                {
                    "text": block[4],
                    "source": {
                        "kind": "pdf",
                        "page": page["page"],
                        "block": i,
                        "bbox": [round(float(v), 1) for v in block[:4]],
                        "label": f"página {page['page']}, bloque de texto {i}",
                    },
                }
            )
    return entries


def from_pdf(raw, filename=None):
    return locate(pdf_entries(raw), filename)


def dxf_entries(path):
    """TEXT/MTEXT and block attributes from model space and every paper-space layout."""
    from pipelines.cad.read import load, text_of

    doc = load(path)
    entries = []
    for layout in doc.layouts:
        for e in layout:
            kind = e.dxftype()
            if kind in ("TEXT", "MTEXT"):
                items = [(e, text_of(e))]
            elif kind == "INSERT":
                items = [(a, a.dxf.text) for a in getattr(e, "attribs", [])]
            else:
                continue
            for source, value in items:
                if value and value.strip():
                    entries.append(
                        {
                            "text": value.replace("\\P", "\n"),
                            "source": {
                                "kind": "dwg",
                                "handle": source.dxf.handle,
                                "layer": e.dxf.layer,
                                "layout": layout.name,
                                "label": f"entidad {source.dxftype()} {source.dxf.handle} "
                                f"({layout.name})",
                            },
                        }
                    )
    # Title blocks often split one address over consecutive TEXT entities: also offer the
    # entities that follow an address label as one entry.
    for i, entry in enumerate(entries):
        if LABEL.match(entry["text"].splitlines()[0]) and len(entry["text"].splitlines()) == 1:
            joined = "\n".join(e["text"] for e in entries[i : i + 4])
            entries.append({"text": joined, "source": entry["source"]})
    return entries


def from_dxf(path, filename=None):
    return locate(dxf_entries(path), filename)


def describe(location):
    """(short place description for prompts, fallback used?) — street, city, region, country."""
    loc = location or {}
    if loc.get("status") == "missing" or not (loc.get("city") or loc.get("text")):
        return FALLBACK, True
    parts = []
    for key in ("street", "city", "region", "country"):
        value = loc.get(key)
        if value and value not in parts:
            parts.append(value)
    if not parts:
        parts = [loc["text"]]
    return ", ".join(parts), False
