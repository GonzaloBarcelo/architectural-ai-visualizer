"""Local DWG → DXF conversion. ODA File Converter is preferred; LibreDWG dwg2dxf is accepted.

DWG is a closed binary format, so the drawing is converted on this machine and then read as DXF
with ezdxf. No cloud converter is ever used.
"""

import os
import plistlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

MISSING = (
    "No hay un conversor DWG→DXF instalado en este equipo. Instala ODA File Converter "
    "(recomendado) o LibreDWG (macOS: «brew install libredwg») y vuelve a subir el plano; "
    "también puedes exportar el plano a DXF desde tu programa de CAD y subir el .dxf. "
    "Consulta docs/USER_GUIDE.md."
)
ODA_PATHS = [
    "/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter",
    str(Path.home() / "Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter"),
    "/usr/bin/ODAFileConverter",
    "/usr/local/bin/ODAFileConverter",
]
LIBREDWG_PATHS = ["/opt/homebrew/bin/dwg2dxf", "/usr/local/bin/dwg2dxf", "/usr/bin/dwg2dxf"]


class ConverterMissing(RuntimeError):
    pass


def _existing(paths):
    return next((p for p in paths if p and Path(p).is_file() and os.access(p, os.X_OK)), None)


def _oda_version(path):
    for parent in Path(path).parents:
        info = parent / "Info.plist"
        if parent.name == "Contents" and info.is_file():
            try:
                return plistlib.loads(info.read_bytes()).get("CFBundleShortVersionString")
            except (OSError, ValueError):
                return None
    return None


def find_converter():
    """{'name', 'path', 'version'} of the preferred available converter, or None."""
    oda = _existing([os.getenv("ODA_FILE_CONVERTER"), shutil.which("ODAFileConverter"), *ODA_PATHS])
    if oda:
        return {"name": "ODA File Converter", "path": oda, "version": _oda_version(oda)}
    libre = _existing([os.getenv("DWG2DXF"), shutil.which("dwg2dxf"), *LIBREDWG_PATHS])
    if libre:
        version = None
        try:
            out = subprocess.run(
                [libre, "--version"], capture_output=True, text=True, timeout=20, check=False
            )
            found = re.search(r"(\d+\.\d+(?:\.\d+)?)", out.stdout + out.stderr)
            version = found[1] if found else None
        except (OSError, subprocess.SubprocessError):
            version = None
        return {"name": "LibreDWG dwg2dxf", "path": libre, "version": version}
    return None


def label(converter):
    if not converter:
        return None
    return f"{converter['name']} {converter.get('version') or '(versión desconocida)'}".strip()


def convert(dwg, output_dir, converter=None, timeout=300):
    """Convert ``dwg`` to ``output_dir/source.dxf``; returns (dxf path, converter record)."""
    converter = converter or find_converter()
    if not converter:
        raise ConverterMissing(MISSING)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "source.dxf"
    target.unlink(missing_ok=True)
    log = output_dir / "dwg-conversion.log"
    with tempfile.TemporaryDirectory(prefix="aav-dwg-") as temp:
        temp = Path(temp)
        if converter["name"].startswith("ODA"):
            source, out = temp / "in", temp / "out"
            source.mkdir()
            out.mkdir()
            shutil.copy2(dwg, source / "plan.dwg")
            command = [converter["path"], str(source), str(out), "ACAD2018", "DXF", "0", "1"]
            produced = out / "plan.dxf"
        else:
            produced = temp / "plan.dxf"
            command = [converter["path"], "-y", "-o", str(produced), str(dwg)]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout, check=False
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("La conversión del DWG ha superado el tiempo máximo.") from exc
        log.write_text((result.stdout or "")[-20000:] + (result.stderr or "")[-20000:])
        if not produced.is_file() or produced.stat().st_size == 0:
            raise RuntimeError(
                f"{converter['name']} no pudo convertir el DWG (código {result.returncode}). "
                "Prueba a guardarlo como DXF desde tu programa de CAD."
            )
        shutil.move(str(produced), target)
    return target, {k: converter.get(k) for k in ("name", "version")}
