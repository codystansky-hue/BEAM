"""
pdf_parser.py — Material datasheet scraper.

Extracts fiber and resin mechanical properties from manufacturer PDFs.
All returned values are in SI base units (Pa, kg/m³, m/m/K).
"""

import re
import io
import logging

log = logging.getLogger(__name__)


# ---------------------------------------------------------------
# Unit converters → SI base units
# ---------------------------------------------------------------
def _num(s: str) -> float:
    """Parse a number string, stripping commas."""
    return float(str(s).replace(",", "").strip())


def _to_pa(val: float, unit: str) -> float:
    u = unit.strip().upper()
    if u == "GPA":                   return val * 1e9
    if u == "MPA":                   return val * 1e6
    if u in ("KSI", "KIP/IN2"):      return val * 6.89476e6
    if u in ("MSI", "MPSI"):         return val * 6.89476e9
    if u == "PSI":                   return val * 6894.76
    return val * 1e9  # fallback: assume GPa


def _to_kg_m3(val: float, unit: str) -> float:
    u = unit.lower()
    if "g/cm" in u or "g/cc" in u:  return val * 1e3
    if "kg/m" in u:                  return val
    if "lb/in" in u:                 return val * 27679.9
    return val * 1e3  # fallback: assume g/cm³


def _to_m_m_k(val: float, unit_str: str) -> float:
    """Convert CTE value (ppm/°C or ppm/°F) to m/m/K."""
    u = unit_str.lower()
    if "f" in u:          # ppm/°F → ppm/°C
        val = val * 9.0 / 5.0
    return val * 1e-6     # ppm → m/m/K


# ---------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------
def _extract_text(source) -> str:
    """Extract all text from a PDF (file path str or raw bytes)."""
    try:
        import pdfplumber
    except ImportError:
        log.error("pdfplumber not installed — run: pip install pdfplumber")
        return ""
    try:
        if isinstance(source, (bytes, bytearray)):
            source = io.BytesIO(source)
        with pdfplumber.open(source) as pdf:
            parts = [page.extract_text() or "" for page in pdf.pages]
        raw = " ".join(parts)
        return re.sub(r"\s+", " ", raw).strip()
    except Exception as e:
        log.error("PDF text extraction failed: %s", e)
        return ""


# ---------------------------------------------------------------
# Type detection
# ---------------------------------------------------------------
def _detect_type(text: str) -> str:
    tl = text.lower()
    fiber_score = (
        10 * ("carbon fiber" in tl)
        + 5  * ("glass fiber" in tl or "basalt fiber" in tl)
        + 4  * ("filament" in tl)
        + 3  * ("fiber properties" in tl)
        + 2  * ("tow" in tl)
    )
    resin_score = (
        10 * ("resin properties" in tl)
        + 6  * ("cyanate ester" in tl)
        + 5  * ("epoxy resin" in tl or "epoxy system" in tl)
        + 3  * ("resin system" in tl)
        + 3  * ("cure cycle" in tl)
        + 2  * ("outgassing" in tl)
    )
    if fiber_score > resin_score:   return "fiber"
    if resin_score > fiber_score:   return "resin"
    return "unknown"


def _guess_name(text: str, source) -> str:
    """Extract product name from the beginning of the PDF text."""
    head = text[:120]
    # Split on common page-structure words that follow the product name
    for delim in [" Product", " Description", " Carbon", " Data Sheet",
                  " Technical", " Material", "®", "™"]:
        if delim.lower() in head.lower():
            idx = head.lower().index(delim.lower())
            head = head[:idx]
            break
    name = re.sub(r"[®™©°º]", "", head).strip()[:50]
    if len(name) > 2:
        return name
    # Fallback: filename
    if isinstance(source, str):
        import os
        return os.path.splitext(os.path.basename(source))[0]
    return "Unknown"


# ---------------------------------------------------------------
# Fiber parser
# ---------------------------------------------------------------
def _parse_fiber(text: str, warnings: list) -> dict:
    props = {}

    # Isolate the fiber-properties section to avoid matching composite-level data.
    # Fiber datasheets (e.g. Hexcel IM7) separate "Typical Fiber Properties" from
    # "Typical HexPly Composite Properties" — parse only the fiber block when present.
    fiber_sec_m = re.search(
        r"(?i)(Typical\s+Fiber\s+Properties.+?)"
        r"(?=Typical\s+Hex|Yarn/Tow|Certification|Carbon\s+Fiber\s+Cert)",
        text,
    )
    fiber_text = fiber_sec_m.group(0) if fiber_sec_m else text

    # Tensile Modulus → E11_t
    # Datasheets often show two columns: "40.0 Msi  276 GPa"
    # Use .*? (not [^0-9]*?) to cross any parenthetical like "(Chord 6000-1000)".
    m = re.search(r"(?i)tensile\s+modulus.*?(\d[\d,.]+)\s*Msi\s+([\d,.]+)\s*GPa", fiber_text)
    if m:
        props["E11_t"] = _num(m.group(2)) * 1e9   # prefer the SI column (GPa)
    else:
        m = re.search(r"(?i)tensile\s+modulus.*?(\d[\d,.]+)\s*GPa", fiber_text)
        if m:
            props["E11_t"] = _num(m.group(1)) * 1e9
        else:
            m = re.search(r"(?i)tensile\s+modulus.*?(\d[\d,.]+)\s*Msi", fiber_text)
            if m:
                props["E11_t"] = _to_pa(_num(m.group(1)), "Msi")
            else:
                warnings.append("Tensile Modulus not found.")

    # Assume E11_c = E11_t unless a separate compressive modulus is listed
    if "E11_t" in props:
        m2 = re.search(r"(?i)compress(?:ive|ion)\s+modulus.*?(\d[\d,.]+)\s*(GPa|Msi)", fiber_text)
        props["E11_c"] = _to_pa(_num(m2.group(1)), m2.group(2)) if m2 else props["E11_t"]

    # Tensile Strength → Xt
    # IM7 shows "6K ... 5,516 MPa  12K ... 5,654 MPa".
    # Collect ALL MPa values in the fiber section and take the max.
    mpa_vals = [_num(x) for x in re.findall(r"(\d[\d,.]+)\s*MPa", fiber_text)]
    if mpa_vals:
        props["Xt"] = max(mpa_vals) * 1e6
    else:
        m = re.search(r"(?i)tensile\s+strength.*?(\d[\d,.]+)\s*ksi", fiber_text)
        if m:
            props["Xt"] = _to_pa(_num(m.group(1)), "ksi")
        else:
            warnings.append("Tensile Strength not found.")

    # Density (prefer g/cm³ SI column)
    # IM7: "Density 0.0643 lb/in3 1.78 g/cm3"
    m = re.search(r"(?i)density.*?(\d[\d,.]+)\s*g/cm", fiber_text)
    if m:
        props["density"] = _num(m.group(1)) * 1e3
    else:
        m = re.search(r"(?i)density.*?(\d[\d,.]+)\s*lb/in", fiber_text)
        if m:
            props["density"] = _num(m.group(1)) * 27679.9
        else:
            warnings.append("Density not found.")

    # CTE (axial) → cte11
    # IM7: "Coefficient of Thermal Expansion -0.36 ppm/ºF -0.64 ppm/ºC"
    # CTE is often on a different page/section; always search full text.
    # Prefer SI column (ppm/°C). Try two-column pattern first.
    m = re.search(
        r"(?i)(?:thermal\s+expansion|CTE).*?(-?\d[\d,.]*)\s*ppm/[^\s]*[Ff].*?(-?\d[\d,.]*)\s*ppm",
        text,
    )
    if m:
        props["cte11"] = _num(m.group(2)) * 1e-6
    else:
        m = re.search(r"(?i)(?:thermal\s+expansion|CTE)[^-\d]*(-?\d[\d,.]*)\s*ppm/[^\s]*[CcKk]", text)
        if m:
            props["cte11"] = _num(m.group(1)) * 1e-6
        else:
            m = re.search(r"(?i)(?:thermal\s+expansion|CTE)[^-\d]*(-?\d[\d,.]*)\s*ppm/[^\s]*[Ff]", text)
            if m:
                props["cte11"] = _to_m_m_k(_num(m.group(1)), "ppm/F")
            else:
                warnings.append("CTE not found (cte11 set to 0).")
                props["cte11"] = 0.0

    # cte22 (transverse) — almost never listed in fiber datasheets
    props.setdefault("cte22", 0.0)

    # Filament diameter (informational, stored as private key)
    m = re.search(r"(?i)filament\s+diameter[^0-9]*(\d[\d,.]*)\s*micron", text)
    if m:
        props["_filament_dia_um"] = _num(m.group(1))

    return props


# ---------------------------------------------------------------
# Resin parser
# ---------------------------------------------------------------
def _parse_resin(text: str, warnings: list) -> dict:
    props = {}

    # Tensile Modulus → E_t
    # PMT-F6: "Tension Modulus 0.56 Msi"
    m = re.search(r"(?i)tens(?:ile|ion)\s+modulus[^0-9]*?(\d[\d,.]*)\s*(GPa|Msi)", text)
    if m:
        props["E_t"] = _to_pa(_num(m.group(1)), m.group(2))
    else:
        warnings.append("Tensile Modulus not found.")

    # Compressive Modulus → E_c
    # PMT-F6: "Compression Modulus 0.66 Msi"
    m = re.search(r"(?i)compress(?:ive|ion)\s+modulus[^0-9]*?(\d[\d,.]*)\s*(GPa|Msi)", text)
    if m:
        props["E_c"] = _to_pa(_num(m.group(1)), m.group(2))
    else:
        props["E_c"] = props.get("E_t", 0.0)   # fallback: assume E_c = E_t
        if "E_t" in props:
            warnings.append("Compressive Modulus not found; using E_t.")

    # Tensile Strength → Xt
    # PMT-F6: "Tension Strength 8.23 Ksi"
    m = re.search(r"(?i)tens(?:ile|ion)\s+strength[^0-9]*?(\d[\d,.]*)\s*(MPa|ksi|Ksi|KSI)", text)
    if m:
        props["Xt"] = _to_pa(_num(m.group(1)), m.group(2))
    else:
        warnings.append("Tensile Strength not found.")

    # Compressive Strength → Xc
    # PMT-F6: "Compression Strength 21.5 Ksi"
    m = re.search(r"(?i)compress(?:ive|ion)\s+strength[^0-9]*?(\d[\d,.]*)\s*(MPa|ksi|Ksi|KSI)", text)
    if m:
        props["Xc"] = _to_pa(_num(m.group(1)), m.group(2))
    else:
        warnings.append("Compressive Strength not found.")

    # Shear Strength → S
    # Look for neat-resin shear first; avoid composite short-beam shear values
    m = re.search(r"(?i)(?:resin|matrix|neat)[^\n]*shear\s+strength[^0-9]*?(\d[\d,.]*)\s*(MPa|ksi|Ksi|KSI)", text)
    if not m:
        # Interlaminar / in-plane shear of the neat resin (not composite SBSS)
        m = re.search(r"(?i)shear\s+strength[^0-9]*?(\d[\d,.]*)\s*(MPa|ksi|Ksi|KSI)", text)
    if m:
        props["S"] = _to_pa(_num(m.group(1)), m.group(2))
    else:
        warnings.append("Shear Strength not found.")

    # Density
    # PMT-F6: "Density 1.19 g/cm³"
    m = re.search(r"(?i)density[^0-9]*?(\d[\d,.]*)\s*g/cm", text)
    if m:
        props["density"] = _num(m.group(1)) * 1e3
    else:
        m = re.search(r"(?i)density[^0-9]*?(\d[\d,.]*)\s*kg/m", text)
        if m:
            props["density"] = _num(m.group(1))
        else:
            warnings.append("Density not found.")

    # Poisson's ratio → nu (rarely in resin datasheets)
    m = re.search(r"(?i)poisson[^0-9]*?(\d[\d,.]*)", text)
    if m:
        props["nu"] = _num(m.group(1))

    # CTE → cte
    m = re.search(
        r"(?i)(?:thermal\s+expansion|CTE|coefficient\s+of\s+thermal)[^-\d]*(-?\d[\d,.]*)\s*ppm/[^\s]*[CcKk]",
        text,
    )
    if m:
        props["cte"] = _num(m.group(1)) * 1e-6
    else:
        m = re.search(
            r"(?i)(?:thermal\s+expansion|CTE|coefficient\s+of\s+thermal)[^-\d]*(-?\d[\d,.]*)\s*ppm/[^\s]*[Ff]",
            text,
        )
        if m:
            props["cte"] = _to_m_m_k(_num(m.group(1)), "ppm/F")
        else:
            warnings.append("CTE not found.")

    return props


# ---------------------------------------------------------------
# Public API
# ---------------------------------------------------------------
def parse_material_datasheet(source) -> dict:
    """
    Parse a composite material manufacturer PDF datasheet.

    Args:
        source: file path (str) or raw PDF bytes

    Returns dict with SI-unit values and meta keys:
      _type       : "fiber" | "resin" | "unknown"
      _summary    : human-readable string of what was extracted
      _warnings   : list of missing/fallback field notices

    Fiber keys (SI): E11_t, E11_c, E22, G12, nu12, density, Xt, Xc, cte11, cte22
    Resin keys (SI): E_t, E_c, nu, density, S, Xt, Xc, cte
    """
    text = _extract_text(source)
    if not text:
        return {
            "_type": "unknown",
            "_summary": "Could not extract text from PDF.",
            "_warnings": ["PDF text extraction failed."],
        }

    mat_type = _detect_type(text)
    name = _guess_name(text, source)
    warnings = []

    if mat_type == "fiber":
        props = _parse_fiber(text, warnings)
    elif mat_type == "resin":
        props = _parse_resin(text, warnings)
    else:
        props = {}
        warnings.append("Could not determine material type — check that the PDF is a fiber or resin datasheet.")

    props["name"] = name
    props["_type"] = mat_type
    props["_warnings"] = warnings

    # Human-readable summary
    SI_DISPLAY = {
        "E11_t": ("GPa", 1e-9), "E11_c": ("GPa", 1e-9),
        "E22":   ("GPa", 1e-9), "G12":   ("GPa", 1e-9),
        "E_t":   ("GPa", 1e-9), "E_c":   ("GPa", 1e-9),
        "Xt":    ("MPa", 1e-6), "Xc":    ("MPa", 1e-6),
        "S":     ("MPa", 1e-6),
        "density": ("kg/m³", 1.0),
        "cte11": ("µm/m/K", 1e6), "cte22": ("µm/m/K", 1e6),
        "cte":   ("µm/m/K", 1e6),
        "nu12":  ("", 1.0), "nu": ("", 1.0),
    }
    lines = [f"Type: {mat_type.upper()}   Name: {name}"]
    for k, (unit, scale) in SI_DISPLAY.items():
        if k in props and not k.startswith("_"):
            lines.append(f"  {k} = {props[k] * scale:.4g} {unit}")
    if warnings:
        lines.append("Note: " + " | ".join(warnings))
    props["_summary"] = "\n".join(lines)

    return props
