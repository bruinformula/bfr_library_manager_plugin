"""
BFR KiCad Library Manager - Library Router
Routes extracted components to the correct BFR library files on disk.
Supports SEPARATE paths for symbols (.kicad_sym) and footprints (.pretty/).
"""

import logging
import re
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger("bfr_plugin")


class LibraryRouter:
    """Routes components to the correct BFR library files."""

    def __init__(self, symbols_path: str, footprints_path: str = ""):
        """
        Args:
            symbols_path: Directory where .kicad_sym files are stored.
            footprints_path: Directory where .pretty/ folders are stored.
                             If empty, uses symbols_path.
        """
        self.symbols_base = Path(symbols_path)
        self.footprints_base = Path(footprints_path) if footprints_path else self.symbols_base

    def _ensure_dir(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)

    def _clean_name(self, name: str) -> str:
        invalid = '<>:"/\\|?* '
        name = name.strip()
        for char in invalid:
            name = name.replace(char, "_")
        return name

    def _read_or_create_sym_lib(self, lib_path: Path) -> str:
        if lib_path.exists():
            return lib_path.read_text(encoding="utf-8", errors="replace")
        else:
            return (
                '(kicad_symbol_lib\n'
                '  (version 20231120)\n'
                '  (generator "bfr_kicad_library_manager")\n'
                '  (generator_version "1.0")\n'
                ')\n'
            )

    def _extract_symbol_blocks(self, content: str) -> list:
        """Extract top-level (symbol ...) blocks from .kicad_sym. Returns [(name, block_text)]."""
        symbols = []
        depth = 0
        current_block = ""
        current_name = ""
        in_symbol = False
        i = 0

        while i < len(content):
            char = content[i]
            if char == '(':
                depth += 1
                if depth == 2:
                    rest = content[i:i+200]
                    match = re.match(r'\(symbol\s+"([^"]+)"', rest)
                    if match:
                        current_name = match.group(1)
                        in_symbol = True
                        current_block = ""
                if in_symbol and depth >= 2:
                    current_block += char
            elif char == ')':
                if in_symbol and depth >= 2:
                    current_block += char
                depth -= 1
                if depth == 1 and in_symbol:
                    symbols.append((current_name, current_block))
                    in_symbol = False
                    current_name = ""
                    current_block = ""
            elif in_symbol and depth >= 2:
                current_block += char
            i += 1

        return symbols

    def _symbol_exists_in_lib(self, lib_content: str, symbol_name: str) -> bool:
        pattern = re.compile(r'\(symbol\s+"' + re.escape(symbol_name) + r'"')
        return bool(pattern.search(lib_content))

    def save_symbol(self, sym_file_path: Path, target_lib: str,
                    overwrite: bool = True) -> tuple[bool, str]:
        """Save a symbol from source .kicad_sym file into the target BFR symbol library."""
        lib_path = self.symbols_base / f"{target_lib}.kicad_sym"
        self._ensure_dir(lib_path.parent)

        try:
            source_content = sym_file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return False, f"Failed to read source symbol: {e}"

        source_symbols = self._extract_symbol_blocks(source_content)
        if not source_symbols:
            return False, "No symbols found in source file"

        dest_content = self._read_or_create_sym_lib(lib_path)

        added = []
        for sym_name, sym_block in source_symbols:
            if self._symbol_exists_in_lib(dest_content, sym_name):
                if overwrite:
                    # Remove existing
                    all_syms = self._extract_symbol_blocks(dest_content)
                    remaining = [b for n, b in all_syms if n != sym_name]
                    header = (
                        '(kicad_symbol_lib\n'
                        '  (version 20231120)\n'
                        '  (generator "bfr_kicad_library_manager")\n'
                        '  (generator_version "1.0")\n'
                    )
                    dest_content = header
                    for b in remaining:
                        dest_content += f"  {b}\n"
                    dest_content += ")\n"
                else:
                    continue
            added.append(sym_name)

        if added:
            dest_content = dest_content.rstrip()
            if dest_content.endswith(")"):
                dest_content = dest_content[:-1]
            for sym_name, sym_block in source_symbols:
                if sym_name in added:
                    # Dynamically rewrite the Footprint property to link to the new BFR footprint library
                    fp_target = f"{target_lib}:{self._clean_name(sym_name)}"
                    fp_prop_pattern = re.compile(r'(\(property\s+"Footprint"\s+)"([^"]*)"')
                    if fp_prop_pattern.search(sym_block):
                        sym_block = fp_prop_pattern.sub(f'\\1"{fp_target}"', sym_block)
                    
                    dest_content += f"  {sym_block}\n"
            dest_content += ")\n"

            temp_path = lib_path.with_suffix(".tmp")
            try:
                temp_path.write_text(dest_content, encoding="utf-8")
                if lib_path.exists():
                    backup = lib_path.with_suffix(".kicad_sym.backup")
                    shutil.copy2(lib_path, backup)
                shutil.move(str(temp_path), str(lib_path))
            except Exception as e:
                if temp_path.exists():
                    temp_path.unlink()
                return False, f"Failed to write library: {e}"

        msg = f"Added {len(added)} symbol(s) to {target_lib}: {', '.join(added)}"
        logger.info(msg)
        return True, msg

    def save_symbol_from_legacy(self, lib_path: Path, target_lib: str,
                                 overwrite: bool = True) -> tuple[bool, str]:
        """Save a legacy .lib file."""
        dest_lib = self.symbols_base / f"{target_lib}.lib"
        try:
            shutil.copy2(lib_path, dest_lib)
            return True, f"Copied legacy library to {dest_lib.name}"
        except Exception as e:
            return False, f"Failed to copy legacy library: {e}"

    def save_footprint(self, footprint_path: Path, target_lib: str,
                       component_name: str = "") -> tuple[bool, str]:
        """Save a .kicad_mod file into the target .pretty directory (in footprints path)."""
        pretty_dir = self.footprints_base / f"{target_lib}.pretty"
        self._ensure_dir(pretty_dir)

        if component_name:
            dest_name = f"{self._clean_name(component_name)}.kicad_mod"
        else:
            dest_name = footprint_path.name

        dest_path = pretty_dir / dest_name

        try:
            content = footprint_path.read_text(encoding="utf-8", errors="replace")

            # Update 3D model path reference
            model_pattern = re.compile(r'(\(model\s+)"([^"]*)"')
            match = model_pattern.search(content)
            if match:
                old_path = match.group(2)
                model_filename = Path(old_path).name
                new_path = f"${{BFRFT}}/{target_lib}.3dshapes/{model_filename}"
                content = model_pattern.sub(f'\\1"{new_path}"', content)

            dest_path.write_text(content, encoding="utf-8")
            return True, f"Saved footprint {dest_name} to {target_lib}.pretty"
        except Exception as e:
            return False, f"Failed to save footprint: {e}"

    def save_3d_model(self, model_path: Path, target_lib: str) -> tuple[bool, str]:
        """Save 3D model to footprints path .3dshapes directory."""
        shapes_dir = self.footprints_base / f"{target_lib}.3dshapes"
        self._ensure_dir(shapes_dir)

        dest_path = shapes_dir / model_path.name
        try:
            shutil.copy2(model_path, dest_path)
            return True, f"Saved 3D model {model_path.name}"
        except Exception as e:
            return False, f"Failed to save 3D model: {e}"

    def add_properties_to_symbol(self, target_lib: str, symbol_name: str,
                                  properties: dict) -> tuple[bool, str]:
        """Add/update properties in a symbol."""
        lib_path = self.symbols_base / f"{target_lib}.kicad_sym"
        if not lib_path.exists():
            return False, f"Library {target_lib}.kicad_sym not found"

        content = lib_path.read_text(encoding="utf-8", errors="replace")

        for key, value in properties.items():
            prop_pattern = re.compile(
                r'(\(property\s+"' + re.escape(key) + r'"\s+)"[^"]*"'
            )
            if prop_pattern.search(content):
                content = prop_pattern.sub(f'\\1"{value}"', content, count=1)
            else:
                sym_start = content.find(f'(symbol "{symbol_name}"')
                if sym_start >= 0:
                    insert_point = content.find("(symbol ", sym_start + 1)
                    if insert_point < 0:
                        insert_point = content.find("\n    )", sym_start)
                    if insert_point > 0:
                        prop_line = (
                            f'    (property "{key}" "{value}"\n'
                            f'      (at 0 0 0)\n'
                            f'      (effects\n'
                            f'        (font\n'
                            f'          (size 1.27 1.27)\n'
                            f'        )\n'
                            f'        (hide yes)\n'
                            f'      )\n'
                            f'    )\n'
                        )
                        content = content[:insert_point] + prop_line + content[insert_point:]

        try:
            lib_path.write_text(content, encoding="utf-8")
            return True, f"Updated {len(properties)} properties for {symbol_name}"
        except Exception as e:
            return False, f"Failed to update properties: {e}"

    def list_symbols_in_lib(self, lib_name: str) -> list[str]:
        lib_path = self.symbols_base / f"{lib_name}.kicad_sym"
        if not lib_path.exists():
            return []
        content = lib_path.read_text(encoding="utf-8", errors="replace")
        symbols = self._extract_symbol_blocks(content)
        return [name for name, _ in symbols if "_0_" not in name and "_1_" not in name]

    def get_available_libraries(self) -> list[str]:
        """Get list of BFR libraries from BOTH symbol and footprint paths."""
        libs = set()
        for base in [self.symbols_base, self.footprints_base]:
            if base.exists():
                for f in base.iterdir():
                    if f.suffix == ".kicad_sym" and f.stem.startswith("bfr_"):
                        libs.add(f.stem)
                    elif f.suffix == ".pretty" and f.stem.startswith("bfr_"):
                        libs.add(f.stem)
        return sorted(libs)
