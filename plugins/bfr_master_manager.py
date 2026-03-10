"""
BFR KiCad Library Manager - Master Library Manager
Supports SEPARATE symbol and footprint library paths.
"""

import logging
import re
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger("bfr_plugin")


class MasterManager:
    """Manages the bfr_master consolidation library."""

    def __init__(self, symbols_path: str, footprints_path: str = ""):
        self.symbols_base = Path(symbols_path)
        self.footprints_base = Path(footprints_path) if footprints_path else self.symbols_base
        self.master_sym = self.symbols_base / "bfr_master.kicad_sym"
        self.master_pretty = self.footprints_base / "bfr_master.pretty"

    def _ensure_dirs(self):
        self.symbols_base.mkdir(parents=True, exist_ok=True)
        self.footprints_base.mkdir(parents=True, exist_ok=True)
        self.master_pretty.mkdir(parents=True, exist_ok=True)

    def _read_or_create_lib(self, path: Path) -> str:
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")
        return (
            '(kicad_symbol_lib\n'
            '  (version 20231120)\n'
            '  (generator "bfr_kicad_library_manager")\n'
            '  (generator_version "1.0")\n'
            ')\n'
        )

    def _extract_symbol_blocks(self, content: str) -> list:
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

    def consolidate_all(self) -> tuple[int, str]:
        """Merge all bfr_*.kicad_sym into bfr_master. Copy all footprints too."""
        self._ensure_dirs()

        master_content = self._read_or_create_lib(self.master_sym)
        existing_names = set(
            name for name, _ in self._extract_symbol_blocks(master_content)
        )

        added_count = 0

        for sym_file in sorted(self.symbols_base.glob("bfr_*.kicad_sym")):
            if sym_file.stem == "bfr_master":
                continue

            lib_content = sym_file.read_text(encoding="utf-8", errors="replace")
            symbols = self._extract_symbol_blocks(lib_content)

            for name, block in symbols:
                if name not in existing_names:
                    master_content = master_content.rstrip()
                    if master_content.endswith(")"):
                        master_content = master_content[:-1]
                    master_content += f"  {block}\n)\n"
                    existing_names.add(name)
                    added_count += 1

        # Copy footprints from all .pretty dirs
        for pretty_dir in sorted(self.footprints_base.glob("bfr_*.pretty")):
            if pretty_dir.stem == "bfr_master":
                continue
            if pretty_dir.is_dir():
                for mod_file in pretty_dir.glob("*.kicad_mod"):
                    dest = self.master_pretty / mod_file.name
                    if not dest.exists():
                        shutil.copy2(mod_file, dest)

        self.master_sym.write_text(master_content, encoding="utf-8")
        msg = f"Consolidated {added_count} symbols into bfr_master"
        return added_count, msg

    def import_external_libs(self, ext_path: Path, lib_names: list[str]) -> tuple[int, int, str]:
        """Import specific external libraries into bfr_master."""
        self._ensure_dirs()
        master_content = self._read_or_create_lib(self.master_sym)
        existing_names = set(
            name for name, _ in self._extract_symbol_blocks(master_content)
        )

        added_sym = 0
        added_fp = 0

        for lib in lib_names:
            sym_file = ext_path / f"{lib}.kicad_sym"
            if sym_file.exists():
                lib_content = sym_file.read_text(encoding="utf-8", errors="replace")
                symbols = self._extract_symbol_blocks(lib_content)
                for name, block in symbols:
                    if name not in existing_names:
                        master_content = master_content.rstrip()
                        if master_content.endswith(")"):
                            master_content = master_content[:-1]
                        master_content += f"  {block}\n)\n"
                        existing_names.add(name)
                        added_sym += 1

            pretty_dir = ext_path / f"{lib}.pretty"
            if pretty_dir.is_dir():
                for mod_file in pretty_dir.glob("*.kicad_mod"):
                    dest = self.master_pretty / mod_file.name
                    if not dest.exists():
                        shutil.copy2(mod_file, dest)
                        added_fp += 1

        self.master_sym.write_text(master_content, encoding="utf-8")
        msg = f"Imported {added_sym} symbols and {added_fp} footprints from external libraries."
        return added_sym, added_fp, msg

    def get_all_libraries(self) -> list[str]:
        """Returns all valid BFR libraries in the symbols path."""
        libs = []
        if self.symbols_base.exists():
            for f in self.symbols_base.iterdir():
                if f.suffix == ".kicad_sym":
                    name = f.stem
                    # Strictly filter out purely non-BFR libraries, 
                    # as well as backup files or ones containing emails/dates (e.g. "bfr_utilities (tony.wang@...)")
                    if name.startswith("bfr_") and "(" not in name and "@" not in name:
                        libs.append(name)
        return sorted(libs)

    def list_symbols_in_lib(self, lib_name: str) -> list[str]:
        """List all symbols in a specific library."""
        lib_path = self.symbols_base / f"{lib_name}.kicad_sym"
        if not lib_path.exists():
            return []
        content = lib_path.read_text(encoding="utf-8", errors="replace")
        symbols = self._extract_symbol_blocks(content)
        return [name for name, _ in symbols if "_0_" not in name and "_1_" not in name]

    def move_symbol(self, symbol_name: str, from_lib: str, to_lib: str) -> tuple[bool, str]:
        """Move a symbol between libraries."""
        from_path = self.symbols_base / f"{from_lib}.kicad_sym"
        to_path = self.symbols_base / f"{to_lib}.kicad_sym"

        if not from_path.exists():
            return False, f"Source library {from_lib} not found"

        from_content = from_path.read_text(encoding="utf-8", errors="replace")
        symbols = self._extract_symbol_blocks(from_content)

        symbol_blocks = [(n, b) for n, b in symbols if n == symbol_name or n.startswith(f"{symbol_name}_")]
        if not symbol_blocks:
            return False, f"Symbol '{symbol_name}' not found in {from_lib}"

        # Add to destination
        to_content = self._read_or_create_lib(to_path)
        to_content = to_content.rstrip()
        if to_content.endswith(")"):
            to_content = to_content[:-1]
        for name, block in symbol_blocks:
            to_content += f"  {block}\n"
        to_content += ")\n"

        # Remove from source (skip if bfr_master)
        if from_lib != "bfr_master":
            remaining = [(n, b) for n, b in symbols if not (n == symbol_name or n.startswith(f"{symbol_name}_"))]
            header = (
                '(kicad_symbol_lib\n'
                '  (version 20231120)\n'
                '  (generator "bfr_kicad_library_manager")\n'
                '  (generator_version "1.0")\n'
            )
            from_content = header
            for name, block in remaining:
                from_content += f"  {block}\n"
            from_content += ")\n"
            from_path.write_text(from_content, encoding="utf-8")

        to_path.write_text(to_content, encoding="utf-8")

        # Move footprints
        from_pretty = self.footprints_base / f"{from_lib}.pretty"
        to_pretty = self.footprints_base / f"{to_lib}.pretty"
        to_pretty.mkdir(parents=True, exist_ok=True)

        if from_pretty.exists():
            for mod_file in from_pretty.glob("*.kicad_mod"):
                fp_name = mod_file.stem.lower().replace("-", "_").replace(" ", "_")
                sym_clean = symbol_name.lower().replace("-", "_").replace(" ", "_")
                if fp_name == sym_clean or sym_clean in fp_name or fp_name in sym_clean:
                    dest = to_pretty / mod_file.name
                    shutil.copy2(mod_file, dest)
                    if from_lib != "bfr_master":
                        mod_file.unlink()

        return True, f"Moved '{symbol_name}' from {from_lib} to {to_lib}"
