"""
BFR KiCad Library Manager — Schematic LCSC Export
Writes LCSC part numbers from the JLC store back into the .kicad_sch file(s).
Supports KiCad 8/9 format (v8+ regex-based approach adapted from Bouni).
"""

import logging
import os
import re

logger = logging.getLogger("bfr_plugin")


class JLCSchematicExport:
    """Inject LCSC part numbers into KiCad schematic files."""

    def __init__(self, store):
        """
        Args:
            store: JLCStore instance (or anything with .read_all() -> list of dicts).
        """
        self.store = store

    def export(self, schematic_path: str) -> int:
        """
        Write LCSC numbers from the store into the schematic.
        Returns the number of parts updated/added.
        """
        if not os.path.isfile(schematic_path):
            logger.error("Schematic file not found: %s", schematic_path)
            return 0

        store_parts = self.store.read_all()
        count = self._update_schematic(schematic_path, store_parts, set())
        return count

    # ------------------------------------------------------------------
    # KiCad 8/9 format  (property on one line, (at ...) on the next)
    # ------------------------------------------------------------------
    def _update_schematic(self, path: str, store_parts: list, visited: set) -> int:
        """Process a single .kicad_sch file, recursing into sub-sheets."""
        if path in visited:
            return 0
        visited.add(path)

        logger.info("Syncing LCSC → %s", path)

        prop_rx = re.compile(r'\(property\s+"(.*)"\s"(.*)"')
        at_rx   = re.compile(r"\(at\s(-?\d+(?:.\d+)?\s-?\d+(?:.\d+)?)\s\d+\)")
        pin_rx  = re.compile(r'\(pin\s+"(.*)"')
        sheet_rx = re.compile(r'\(property\s+"Sheetfile"\s"(.*)"')

        with open(path, encoding="utf-8") as f:
            lines = f.readlines()

        part_section = False
        last_loc = ""
        last_lcsc = ""
        new_lcsc = ""
        last_ref = ""

        updated = 0
        newlines = []

        for i in range(len(lines) - 1):
            in_line  = lines[i].rstrip()
            in_line2 = lines[i + 1].rstrip()
            out_line = in_line

            if "(symbol" in in_line and "(lib_id" in in_line2:
                part_section = True

            m  = prop_rx.search(in_line)
            m2 = at_rx.search(in_line2)

            if m and m2 and part_section:
                key = m.group(1)

                if key in {"LCSC", "LCSC_PN", "JLC_PN"}:
                    value = m.group(2)
                    last_lcsc = value
                    if new_lcsc and new_lcsc != last_lcsc:
                        logger.info("Updating %s → %s on %s", last_lcsc, new_lcsc, last_ref)
                        out_line = out_line.replace(
                            f'"{last_lcsc}"', f'"{new_lcsc}"'
                        )
                        last_lcsc = new_lcsc
                        updated += 1

                if key == "Reference":
                    last_loc = m2.group(1)
                    value = m.group(2)
                    last_ref = value
                    new_lcsc = ""
                    for part in store_parts:
                        if value == part["reference"]:
                            new_lcsc = part.get("lcsc", "")
                            break

                # Recurse into sub-sheets
                sm = sheet_rx.search(in_line)
                if sm:
                    sub_file = sm.group(1)
                    sub_path = os.path.join(os.path.dirname(path), sub_file)
                    if os.path.isfile(sub_path):
                        updated += self._update_schematic(sub_path, store_parts, visited)

            # If we hit the pin section without finding an LCSC property, inject one
            m3 = pin_rx.search(in_line)
            if m3 and part_section:
                if not last_lcsc and new_lcsc and last_loc:
                    logger.info("Adding LCSC %s to %s", new_lcsc, last_ref)
                    newlines.append(f'\t\t(property "LCSC" "{new_lcsc}"')
                    newlines.append(f"\t\t\t(at {last_loc} 0)")
                    newlines.append("\t\t\t(effects")
                    newlines.append("\t\t\t\t(font")
                    newlines.append("\t\t\t\t\t(size 1.27 1.27)")
                    newlines.append("\t\t\t\t)")
                    newlines.append("\t\t\t\t(hide yes)")
                    newlines.append("\t\t\t)")
                    newlines.append("\t\t)")
                    updated += 1
                last_loc = ""
                last_lcsc = ""
                new_lcsc = ""
                last_ref = ""

            newlines.append(out_line)

        # Append the last line
        if lines:
            newlines.append(lines[-1].rstrip())

        # Write back (backup old)
        backup = path + "_old"
        if os.path.exists(backup):
            os.remove(backup)
        os.rename(path, backup)
        with open(path, "w", encoding="utf-8") as f:
            for line in newlines:
                f.write(line + "\n")

        logger.info("Schematic sync complete for %s (%d updates)", path, updated)
        return updated
