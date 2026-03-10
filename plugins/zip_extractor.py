"""
BFR KiCad Library Manager - Zip Extraction Engine
Extracts symbols, footprints, and 3D models from component zip files.
Supports: Octopart, Samacsys, UltraLibrarian, Snapeda, EasyEDA/LCSC.
Adapted from Import-LIB-KiCad-Plugin by Steffen-W.
"""

import logging
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger("bfr_plugin")


class SourceType(Enum):
    """Component zip source types."""
    OCTOPART = auto()
    SAMACSYS = auto()
    ULTRALIBRARIAN = auto()
    SNAPEDA = auto()
    EASYEDA = auto()
    UNKNOWN = auto()
    PARTIAL = auto()


@dataclass
class ComponentData:
    """Extracted component data from a zip file."""
    name: str = ""
    source: SourceType = SourceType.UNKNOWN
    # Raw file paths (temporary, valid during extraction)
    symbol_path: Optional[Path] = None
    footprint_path: Optional[Path] = None
    model_path: Optional[Path] = None
    # Symbol metadata extracted from .kicad_sym / .lib
    description: str = ""
    keywords: list = field(default_factory=list)
    datasheet: str = ""
    value: str = ""
    reference: str = ""
    manufacturer: str = ""
    mpn: str = ""  # Manufacturer Part Number
    properties: dict = field(default_factory=dict)
    # Temp directory (caller must clean up)
    _temp_dir: Optional[Path] = None


def find_in_zip(root: zipfile.Path, suffix: str) -> Optional[zipfile.Path]:
    """Recursively search for the first file ending with suffix in a zip."""
    try:
        for item in root.iterdir():
            if item.is_file() and item.name.lower().endswith(suffix.lower()):
                return item
            if item.is_dir():
                result = find_in_zip(item, suffix)
                if result:
                    return result
    except Exception:
        pass
    return None


def find_dir_in_zip(root: zipfile.Path, name: str) -> Optional[zipfile.Path]:
    """Find a directory by name in a zip."""
    try:
        for item in root.iterdir():
            if item.is_dir() and item.name.lower() == name.lower():
                return item
            if item.is_dir():
                result = find_dir_in_zip(item, name)
                if result:
                    return result
    except Exception:
        pass
    return None


def identify_source(zf: zipfile.ZipFile) -> SourceType:
    """Identify the source of a component zip file using namelist to avoid closed file errors."""
    names = [n for n in zf.namelist()]
    names_lower = [n.lower() for n in names]
    names_str = " ".join(names_lower)

    # Octopart: has device.lib + device.dcm
    if any("device.dcm" in n for n in names_lower) and any("device.lib" in n for n in names_lower):
        return SourceType.OCTOPART

    # Samacsys: has a KiCad/ directory
    if any("KiCad/" in n for n in names):
        return SourceType.SAMACSYS

    # UltraLibrarian: has a KiCAD/ directory
    if any("KiCAD/" in n for n in names):
        return SourceType.ULTRALIBRARIAN

    # EasyEDA: filenames often contain easyeda or lcsc patterns
    if "easyeda" in names_str or "lcsc" in names_str:
        return SourceType.EASYEDA

    # Snapeda: has .kicad_sym or .lib at root level or anywhere really
    if any(n.endswith(".kicad_sym") for n in names_lower) or any(n.endswith(".lib") for n in names_lower):
        return SourceType.SNAPEDA

    return SourceType.UNKNOWN


def extract_zip_to_temp(zip_path: Path) -> tuple[Path, SourceType]:
    """
    Extract a zip file to a temporary directory and identify its source.
    Returns (temp_dir, source_type).
    Caller is responsible for cleaning up temp_dir.
    """
    if not zipfile.is_zipfile(zip_path):
        raise ValueError(f"{zip_path} is not a valid zip file")

    temp_dir = Path(tempfile.mkdtemp(prefix="bfr_import_"))

    with zipfile.ZipFile(zip_path) as zf:
        source = identify_source(zf)
        zf.extractall(temp_dir)

    return temp_dir, source


def _find_file(directory: Path, suffix: str) -> Optional[Path]:
    """Recursively find a file with the given suffix in directory."""
    for p in directory.rglob(f"*{suffix}"):
        if p.is_file():
            return p
    return None


def _find_dir(directory: Path, suffix: str) -> Optional[Path]:
    """Find a directory ending with suffix."""
    for p in directory.rglob(f"*{suffix}"):
        if p.is_dir():
            return p
    return None


def _find_kicad_mod(directory: Path) -> Optional[Path]:
    """Find a .kicad_mod file, checking inside .pretty dirs too."""
    # Check inside .pretty directories first
    for pretty_dir in directory.rglob("*.pretty"):
        if pretty_dir.is_dir():
            for mod_file in pretty_dir.glob("*.kicad_mod"):
                return mod_file
    # Direct search
    return _find_file(directory, ".kicad_mod")


def _parse_kicad_sym_metadata(sym_path: Path) -> dict:
    """
    Parse a .kicad_sym file for metadata using text parsing.
    Returns dict with: name, description, keywords, datasheet, value, reference, properties.
    """
    metadata = {
        "name": "",
        "description": "",
        "keywords": [],
        "datasheet": "",
        "value": "",
        "reference": "",
        "manufacturer": "",
        "mpn": "",
        "properties": {},
    }

    try:
        content = sym_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.error(f"Failed to read symbol file {sym_path}: {e}")
        return metadata

    import re

    # Extract symbol name
    sym_match = re.search(r'\(symbol\s+"([^"]+)"', content)
    if sym_match:
        metadata["name"] = sym_match.group(1)

    # Extract properties
    # KiCad 7+ format: (property "Key" "Value" ...)
    prop_pattern = re.compile(r'\(property\s+"([^"]+)"\s+"([^"]*)"')
    for match in prop_pattern.finditer(content):
        key, value = match.group(1), match.group(2)
        metadata["properties"][key] = value

        key_lower = key.lower()
        if key_lower == "reference":
            metadata["reference"] = value
        elif key_lower == "value":
            metadata["value"] = value
            if not metadata["name"]:
                metadata["name"] = value
        elif key_lower == "datasheet":
            metadata["datasheet"] = value
        elif key_lower == "description" or key == "ki_description":
            metadata["description"] = value
        elif key_lower == "ki_keywords" or key_lower == "keywords":
            metadata["keywords"] = [k.strip() for k in value.split(",") if k.strip()]
            if not metadata["keywords"]:
                metadata["keywords"] = [k.strip() for k in value.split() if k.strip()]
        elif key_lower in ("manufacturer", "mfr"):
            metadata["manufacturer"] = value
        elif key_lower in ("mpn", "manufacturer_part_number", "mfr_part_number", "manf#"):
            metadata["mpn"] = value

    return metadata


def _parse_lib_metadata(lib_path: Path) -> dict:
    """Parse legacy .lib file for basic metadata."""
    metadata = {
        "name": "",
        "description": "",
        "keywords": [],
        "datasheet": "",
        "value": "",
        "reference": "",
        "manufacturer": "",
        "mpn": "",
        "properties": {},
    }

    try:
        content = lib_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return metadata

    import re

    # DEF line: DEF part_name reference ...
    def_match = re.search(r"^DEF\s+(\S+)\s+(\S+)", content, re.MULTILINE)
    if def_match:
        metadata["name"] = def_match.group(1)
        metadata["reference"] = def_match.group(2)
        metadata["value"] = def_match.group(1)

    # F fields
    f_pattern = re.compile(r'^F(\d+)\s+"([^"]*)"', re.MULTILINE)
    for match in f_pattern.finditer(content):
        field_num = int(match.group(1))
        field_val = match.group(2)
        if field_num == 0:
            metadata["reference"] = field_val
        elif field_num == 1:
            metadata["value"] = field_val
        elif field_num == 3:
            metadata["datasheet"] = field_val

    # Keywords
    kw_match = re.search(r"^KEYWORDS?\s+(.+)$", content, re.MULTILINE | re.IGNORECASE)
    if kw_match:
        metadata["keywords"] = [k.strip() for k in kw_match.group(1).split() if k.strip()]

    # Description
    desc_match = re.search(r'^D\s+(.+)$', content, re.MULTILINE)
    if desc_match:
        metadata["description"] = desc_match.group(1).strip()

    return metadata


def extract_component(zip_path: Path) -> ComponentData:
    """
    Main extraction function. Extracts a zip file and returns ComponentData.
    The ComponentData._temp_dir must be cleaned up by the caller when done.
    """
    logger.info(f"Extracting component from {zip_path.name}")

    temp_dir, source = extract_zip_to_temp(zip_path)
    component = ComponentData(source=source, _temp_dir=temp_dir)
    component.name = zip_path.stem  # Default name from filename

    # Find files based on source type
    if source == SourceType.SAMACSYS:
        kicad_dir = _find_dir(temp_dir, "KiCad")
        search_dir = kicad_dir or temp_dir
        component.symbol_path = _find_file(search_dir, ".kicad_sym") or _find_file(search_dir, ".lib")
        component.footprint_path = _find_kicad_mod(search_dir)

    elif source == SourceType.ULTRALIBRARIAN:
        kicad_dir = _find_dir(temp_dir, "KiCAD")
        search_dir = kicad_dir or temp_dir
        component.symbol_path = _find_file(search_dir, ".kicad_sym") or _find_file(search_dir, ".lib")
        component.footprint_path = _find_kicad_mod(search_dir)

    elif source == SourceType.OCTOPART:
        component.symbol_path = _find_file(temp_dir, "device.lib")
        component.footprint_path = _find_kicad_mod(temp_dir)

    else:
        # Snapeda, EasyEDA, Unknown - generic search
        component.symbol_path = _find_file(temp_dir, ".kicad_sym") or _find_file(temp_dir, ".lib")
        component.footprint_path = _find_kicad_mod(temp_dir)

    # Find 3D model (all sources)
    component.model_path = (
        _find_file(temp_dir, ".step") or
        _find_file(temp_dir, ".stp") or
        _find_file(temp_dir, ".wrl")
    )

    # Parse metadata from symbol file
    if component.symbol_path:
        if component.symbol_path.suffix == ".kicad_sym":
            meta = _parse_kicad_sym_metadata(component.symbol_path)
        else:
            meta = _parse_lib_metadata(component.symbol_path)

        if meta["name"]:
            component.name = meta["name"]
        component.description = meta["description"]
        component.keywords = meta["keywords"]
        component.datasheet = meta["datasheet"]
        component.value = meta["value"]
        component.reference = meta["reference"]
        component.manufacturer = meta["manufacturer"]
        component.mpn = meta["mpn"]
        component.properties = meta["properties"]

    logger.info(f"Extracted: name={component.name}, source={source.name}, "
                f"symbol={'✓' if component.symbol_path else '✗'}, "
                f"footprint={'✓' if component.footprint_path else '✗'}, "
                f"model={'✓' if component.model_path else '✗'}")

    return component


def cleanup_component(component: ComponentData):
    """Clean up temporary files for a component."""
    if component._temp_dir and component._temp_dir.exists():
        try:
            shutil.rmtree(component._temp_dir)
        except Exception as e:
            logger.warning(f"Failed to clean up temp dir: {e}")
