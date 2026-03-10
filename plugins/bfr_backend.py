"""
BFR KiCad Library Manager - Backend Orchestration
Supports SEPARATE symbol and footprint library paths.
"""

import logging
import shutil
from pathlib import Path
from typing import Callable, Optional

from .zip_extractor import ComponentData, extract_component, cleanup_component
from .bfr_classifier import classify_from_component_data, ClassificationResult
from .bfr_metadata import enrich_component
from .bfr_library_router import LibraryRouter
from .bfr_master_manager import MasterManager

logger = logging.getLogger("bfr_plugin")


class ImportResult:
    """Result of a single component import."""

    def __init__(self):
        self.success = False
        self.component_name = ""
        self.target_library = ""
        self.classification: Optional[ClassificationResult] = None
        self.messages: list[str] = []
        self.enriched_properties: dict = {}

    def add_msg(self, msg: str):
        self.messages.append(msg)
        logger.info(msg)


class BFRBackend:
    """Main backend for the BFR KiCad Library Manager."""

    BFR_LIBRARIES = [
        "bfr_amplifiers",
        "bfr_capacitors",
        "bfr_connectors",
        "bfr_crystals",
        "bfr_diodes",
        "bfr_inductors",
        "bfr_microcontrollers",
        "bfr_potentiometers",
        "bfr_power_ics",
        "bfr_power_symbols",
        "bfr_resistors",
        "bfr_sensors",
        "bfr_transformers",
        "bfr_transistors",
        "bfr_utilities",
        "bfr_logos",
        "bfr_misc",
        "bfr_master",
    ]

    def __init__(self, symbols_path: str = "", footprints_path: str = ""):
        self.symbols_path = symbols_path
        self.footprints_path = footprints_path or symbols_path
        self.router: Optional[LibraryRouter] = None
        self.master: Optional[MasterManager] = None
        self.auto_enrich = True
        self.auto_master = True
        self._log_callback: Optional[Callable[[str], None]] = None

        if symbols_path:
            self.set_paths(symbols_path, footprints_path or symbols_path)

    def set_paths(self, symbols_path: str, footprints_path: str = ""):
        """Set library paths and initialize router/master."""
        self.symbols_path = symbols_path
        self.footprints_path = footprints_path or symbols_path

        Path(self.symbols_path).mkdir(parents=True, exist_ok=True)
        Path(self.footprints_path).mkdir(parents=True, exist_ok=True)

        self.router = LibraryRouter(self.symbols_path, self.footprints_path)
        self.master = MasterManager(self.symbols_path, self.footprints_path)

    def set_log_callback(self, callback: Callable[[str], None]):
        self._log_callback = callback

    def _log(self, msg: str):
        logger.info(msg)
        if self._log_callback:
            self._log_callback(msg)

    def import_zip(self, zip_path: str, target_override: str = "") -> ImportResult:
        """Import a component from a zip file."""
        result = ImportResult()
        zip_file = Path(zip_path)

        if not zip_file.exists():
            result.add_msg(f"Error: File not found: {zip_path}")
            return result

        if not self.router:
            result.add_msg("Error: Library paths not configured")
            return result

        self._log(f"━━━ Importing {zip_file.name} ━━━")

        # Step 1: Extract
        try:
            component = extract_component(zip_file)
            result.component_name = component.name
            self._log(f"✓ Extracted: {component.name} (source: {component.source.name})")
        except Exception as e:
            result.add_msg(f"Error extracting zip: {e}")
            return result

        try:
            # Step 2: Classify
            if target_override:
                from .bfr_classifier import ClassificationResult as CR
                classification = CR(
                    library=target_override,
                    confidence=1.0,
                    is_passive=target_override in ("bfr_resistors", "bfr_capacitors", "bfr_inductors"),
                    reason=f"User override: {target_override}",
                )
            else:
                classification = classify_from_component_data(component)

            result.classification = classification
            result.target_library = classification.library
            self._log(
                f"✓ Classified: {classification.library} "
                f"({classification.confidence:.0%}, {classification.reason})"
            )

            if classification.is_passive and component.value:
                self._log(f"  Passive value: {component.value}")

            # Step 3: LCSC enrichment
            enriched = {}
            if self.auto_enrich:
                try:
                    self._log("⟳ Looking up LCSC metadata...")
                    enriched = enrich_component(component)
                    result.enriched_properties = enriched
                    if enriched:
                        self._log(f"✓ Found: {', '.join(enriched.keys())}")
                    else:
                        self._log("  No additional metadata found")
                except Exception as e:
                    self._log(f"  Metadata lookup failed: {e}")

            # Step 4: Save to target library
            target = classification.library

            if component.symbol_path:
                if component.symbol_path.suffix == ".kicad_sym":
                    ok, msg = self.router.save_symbol(component.symbol_path, target)
                else:
                    ok, msg = self.router.save_symbol_from_legacy(component.symbol_path, target)
                self._log(f"{'✓' if ok else '✗'} Symbol: {msg}")
                if ok and enriched:
                    self.router.add_properties_to_symbol(target, component.name, enriched)
            else:
                self._log("  No symbol file in zip")

            if component.footprint_path:
                ok, msg = self.router.save_footprint(component.footprint_path, target, component.name)
                self._log(f"{'✓' if ok else '✗'} Footprint: {msg}")
            else:
                self._log("  No footprint file in zip")

            if component.model_path:
                ok, msg = self.router.save_3d_model(component.model_path, target)
                self._log(f"{'✓' if ok else '✗'} 3D Model: {msg}")
            else:
                self._log("  No 3D model found in zip")
                
            # Step 5: Master copy (optional)
            if self.auto_master and target != "bfr_master":
                if component.symbol_path:
                    if component.symbol_path.suffix == ".kicad_sym":
                        self.router.save_symbol(component.symbol_path, "bfr_master")
                    else:
                        self.router.save_symbol_from_legacy(component.symbol_path, "bfr_master")
                if component.footprint_path:
                    self.router.save_footprint(component.footprint_path, "bfr_master", component.name)
                if component.model_path:
                    self.router.save_3d_model(component.model_path, "bfr_master")
                self._log("✓ Also added to bfr_master")

            result.success = True
            self._log(f"━━━ Done: {component.name} → {target} ━━━\n")

        finally:
            cleanup_component(component)

        return result

    def import_multiple_zips(self, zip_paths: list[str]) -> list[ImportResult]:
        results = []
        for i, path in enumerate(zip_paths, 1):
            self._log(f"[{i}/{len(zip_paths)}] Processing...")
            results.append(self.import_zip(path))
        return results

    def consolidate_master(self) -> tuple[int, str]:
        if not self.master:
            return 0, "Paths not configured"
        self._log("Consolidating all libraries into bfr_master...")
        count, msg = self.master.consolidate_all()
        self._log(f"✓ {msg}")
        return count, msg

    def sort_component(self, symbol_name: str, from_lib: str, to_lib: str) -> tuple[bool, str]:
        if not self.master:
            return False, "Paths not configured"
        self._log(f"Moving '{symbol_name}': {from_lib} → {to_lib}...")
        ok, msg = self.master.move_symbol(symbol_name, from_lib, to_lib)
        self._log(f"{'✓' if ok else '✗'} {msg}")
        return ok, msg

    def get_all_libraries(self) -> list[str]:
        if self.master:
            return self.master.get_all_libraries()
        return []

    def get_symbols_in_library(self, lib_name: str) -> list[str]:
        if self.master:
            return self.master.list_symbols_in_lib(lib_name)
        return []

    def get_target_libraries(self) -> list[str]:
        libs = self.get_all_libraries()
        if libs:
            return [lib for lib in libs if lib not in ("bfr_master", "bfr_misc")]
        return [lib for lib in self.BFR_LIBRARIES if lib not in ("bfr_master", "bfr_misc")]

    def list_external_libraries(self, ext_path: str) -> list[str]:
        p = Path(ext_path)
        if not p.is_dir():
            return []
        
        libs = set()
        for f in p.glob("*.kicad_sym"):
            libs.add(f.stem)
        for d in p.glob("*.pretty"):
            if d.is_dir():
                libs.add(d.stem)
        return sorted(list(libs))

    def import_external_libraries(self, ext_path: str, lib_names: list[str]) -> tuple[int, int, str]:
        if not self.master:
            return 0, 0, "Paths not configured"
        self._log(f"Merging {len(lib_names)} external libraries from {ext_path}...")
        syms, fps, msg = self.master.import_external_libs(Path(ext_path), lib_names)
        self._log(f"✓ {msg}")
        return syms, fps, msg
