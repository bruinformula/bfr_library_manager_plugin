"""
BFR KiCad Library Manager — JLC Project Store
Reads all footprints from the active board, stores LCSC assignments in a
lightweight JSON file (no SQLite dependency), and provides helpers for
the BOM/CPL/search workflow.
"""

import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger("bfr_plugin")


def _get_valid_footprints(board):
    """Return footprints with sane references (skip REF**, kibuzzard, etc.)."""
    fps = []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if re.match(r"[\w\d-]+", ref) and len(ref) < 20:
            fps.append(fp)
    return fps


def _get_lcsc_value(fp):
    """Extract an existing LCSC number from a footprint's fields."""
    try:
        for field in fp.GetFields():
            if re.match(r"lcsc|jlc", field.GetName(), re.IGNORECASE) and re.match(
                r"^C\d+$", field.GetText()
            ):
                return field.GetText()
    except AttributeError:
        for key, value in fp.GetProperties().items():
            if re.match(r"lcsc|jlc", key, re.IGNORECASE) and re.match(r"^C\d+$", value):
                return value
    return ""


def _set_lcsc_value(fp, lcsc: str):
    """Write an LCSC part number to a footprint field."""
    lcsc_field = None
    try:
        for field in fp.GetFields():
            if re.match(r"lcsc|jlc", field.GetName(), re.IGNORECASE):
                lcsc_field = field
    except AttributeError:
        pass

    if lcsc_field:
        fp.SetField(lcsc_field.GetName(), lcsc)
    else:
        fp.SetField("LCSC", lcsc)
        field = fp.GetFieldByName("LCSC")
        if field:
            field.SetVisible(False)


def _set_field_value(fp, field_name: str, value: str):
    """Write an arbitrary field to a footprint, creating it if needed.
    Only writes if the field is currently empty or does not exist."""
    existing = fp.GetFieldByName(field_name)
    if existing:
        if existing.GetText().strip():
            return  # Don't overwrite existing data
        fp.SetField(field_name, value)
    else:
        fp.SetField(field_name, value)
        new_field = fp.GetFieldByName(field_name)
        if new_field:
            new_field.SetVisible(False)


def _get_exclude_from_bom(fp):
    val = fp.GetAttributes()
    return bool(val & (1 << 3))


def _get_exclude_from_pos(fp):
    val = fp.GetAttributes()
    return bool(val & (1 << 2))


class JLCStore:
    """Lightweight JSON-backed store for LCSC part assignments."""

    def __init__(self, board):
        self.board = board
        board_path = board.GetFileName()
        self.project_path = os.path.dirname(board_path)
        self.project_name = Path(board_path).stem
        self.datadir = os.path.join(self.project_path, "jlcpcb")
        self.dbfile = os.path.join(self.datadir, "bfr_jlc_parts.json")
        Path(self.datadir).mkdir(parents=True, exist_ok=True)

        self.parts = {}  # reference -> dict
        self._load()
        self.sync_from_board()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load(self):
        if os.path.isfile(self.dbfile):
            try:
                with open(self.dbfile, encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.parts = {p["reference"]: p for p in data}
                    elif isinstance(data, dict):
                        self.parts = data
            except Exception as e:
                logger.warning("Failed to load JLC store: %s", e)

    def save(self):
        with open(self.dbfile, "w", encoding="utf-8") as f:
            json.dump(list(self.parts.values()), f, indent=2)

    # ------------------------------------------------------------------
    # Board sync
    # ------------------------------------------------------------------
    def sync_from_board(self):
        """Read all footprints from the active board, merge with stored data."""
        board_refs = set()
        for fp in _get_valid_footprints(self.board):
            ref = fp.GetReference()
            board_refs.add(ref)
            board_part = {
                "reference": ref,
                "value": fp.GetValue(),
                "footprint": str(fp.GetFPID().GetLibItemName()),
                "lcsc": _get_lcsc_value(fp),
                "exclude_from_bom": _get_exclude_from_bom(fp),
                "exclude_from_pos": _get_exclude_from_pos(fp),
            }
            existing = self.parts.get(ref)
            if not existing:
                self.parts[ref] = board_part
            else:
                # Board takes precedence for val/fp/bom/pos, keep stored LCSC if board has none
                existing["value"] = board_part["value"]
                existing["footprint"] = board_part["footprint"]
                existing["exclude_from_bom"] = board_part["exclude_from_bom"]
                existing["exclude_from_pos"] = board_part["exclude_from_pos"]
                if board_part["lcsc"] and not existing.get("lcsc"):
                    existing["lcsc"] = board_part["lcsc"]

        # Remove parts no longer on the board
        for ref in list(self.parts.keys()):
            if ref not in board_refs:
                del self.parts[ref]

        self.save()

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    def read_all(self) -> list:
        """Return all parts sorted by reference."""
        return sorted(self.parts.values(), key=lambda p: p["reference"])

    def get_part(self, ref: str) -> dict:
        return self.parts.get(ref, {})

    def set_lcsc(self, ref: str, lcsc: str):
        if ref in self.parts:
            self.parts[ref]["lcsc"] = lcsc
            # Also write back to the board footprint
            fp = self.board.FindFootprintByReference(ref)
            if fp:
                _set_lcsc_value(fp, lcsc)
            self.save()

    def remove_lcsc(self, ref: str):
        self.set_lcsc(ref, "")

    def set_fields_for_ref(self, ref: str, fields: dict):
        """Write arbitrary metadata fields to a footprint (e.g., MPN, Manufacturer, Voltage).
        Only writes fields that are currently empty on the footprint."""
        fp = self.board.FindFootprintByReference(ref)
        if not fp:
            return
        for key, value in fields.items():
            if key and value:
                _set_field_value(fp, key, str(value))

    def set_lcsc_for_alike(self, ref: str, lcsc: str) -> list:
        """Set LCSC for all parts that share the same value + footprint as `ref`.
        Returns list of affected references."""
        target = self.parts.get(ref)
        if not target:
            return []
        affected = []
        for p in self.parts.values():
            if p["value"] == target["value"] and p["footprint"] == target["footprint"]:
                p["lcsc"] = lcsc
                fp = self.board.FindFootprintByReference(p["reference"])
                if fp:
                    _set_lcsc_value(fp, lcsc)
                affected.append(p["reference"])
        self.save()
        return affected

    def read_bom_parts(self) -> list:
        """Return parts grouped by (value, footprint, lcsc) for BOM export."""
        groups = {}
        for p in self.parts.values():
            if p.get("exclude_from_bom"):
                continue
            key = (p["value"], p["footprint"], p.get("lcsc", ""))
            groups.setdefault(key, []).append(p["reference"])
        result = []
        for (val, fp, lcsc), refs in sorted(groups.items()):
            result.append({
                "value": val,
                "refs": ",".join(sorted(refs)),
                "footprint": fp,
                "lcsc": lcsc,
            })
        return result
