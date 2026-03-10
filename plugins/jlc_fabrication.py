"""
BFR KiCad Library Manager — JLCPCB Production File Generator
Generates Gerber, Excellon drill, BOM, and CPL files for JLCPCB.
Inspired by Bouni's kicad-jlcpcb-tools fabrication module.
"""

import csv
import logging
import math
import os
import re
import subprocess
import sys
from importlib import import_module
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

logger = logging.getLogger("bfr_plugin")


class JLCFabrication:
    """Generate JLCPCB-ready production files from the active KiCad board."""

    def __init__(self, board, corrections=None):
        self.board = board
        self.corrections = corrections or []
        self.path, self.filename = os.path.split(board.GetFileName())
        self.project_name = Path(self.filename).stem
        self.outputdir = os.path.join(self.path, "jlcpcb", "production_files")
        self.gerberdir = os.path.join(self.path, "jlcpcb", "gerber")
        Path(self.outputdir).mkdir(parents=True, exist_ok=True)
        Path(self.gerberdir).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Gerber Generation
    # ------------------------------------------------------------------
    def generate_gerber(self, layer_count=None):
        """Plot Gerber files for every relevant layer."""
        from pcbnew import (
            PLOT_CONTROLLER, PCB_PLOT_PARAMS, PLOT_FORMAT_GERBER,
            F_Cu, B_Cu, F_SilkS, B_SilkS, F_Mask, B_Mask,
            F_Paste, B_Paste, Edge_Cuts,
        )
        try:
            from pcbnew import DRILL_MARKS_NO_DRILL_SHAPE
            no_drill = DRILL_MARKS_NO_DRILL_SHAPE
        except ImportError:
            no_drill = PCB_PLOT_PARAMS.NO_DRILL_SHAPE

        pctl = PLOT_CONTROLLER(self.board)
        popt = pctl.GetPlotOptions()
        popt.SetOutputDirectory(self.gerberdir)
        popt.SetFormat(1)                        # Gerber format
        popt.SetPlotValue(True)
        popt.SetPlotReference(True)
        popt.SetSketchPadsOnFabLayers(False)
        popt.SetUseGerberProtelExtensions(False)
        popt.SetCreateGerberJobFile(False)
        popt.SetSubtractMaskFromSilk(True)
        popt.SetUseAuxOrigin(True)
        popt.SetUseGerberX2format(True)
        popt.SetIncludeGerberNetlistInfo(True)
        popt.SetDisableGerberMacros(False)
        popt.SetDrillMarksType(no_drill)
        popt.SetPlotFrameRef(False)

        # Clear old files
        for f in os.listdir(self.gerberdir):
            os.remove(os.path.join(self.gerberdir, f))

        if not layer_count:
            layer_count = self.board.GetCopperLayerCount()

        top  = [("CuTop", F_Cu, "Top layer"), ("SilkTop", F_SilkS, "Silk top"),
                ("MaskTop", F_Mask, "Mask top"), ("PasteTop", F_Paste, "Paste top")]
        bot  = [("CuBottom", B_Cu, "Bottom layer"), ("SilkBottom", B_SilkS, "Silk bottom"),
                ("MaskBottom", B_Mask, "Mask bottom"), ("EdgeCuts", Edge_Cuts, "Edges"),
                ("PasteBottom", B_Paste, "Paste bottom")]

        if layer_count == 1:
            plan = top + bot[-2:]
        elif layer_count == 2:
            plan = top + bot
        else:
            inner = [(f"CuIn{i}", getattr(import_module("pcbnew"), f"In{i}_Cu"),
                      f"Inner layer {i}") for i in range(1, layer_count - 1)]
            plan = top + inner + bot

        # JLC_ prefixed custom layers
        for lid in list(self.board.GetEnabledLayers().Seq()):
            name = str(self.board.GetLayerName(lid)).upper()
            if "JLC_" in name:
                plan.append((name, lid, name))

        for suffix, layer_id, desc in plan:
            popt.SetSkipPlotNPTH_Pads(layer_id <= B_Cu)
            pctl.SetLayer(layer_id)
            pctl.OpenPlotfile(suffix, PLOT_FORMAT_GERBER, desc)
            if not pctl.PlotLayer():
                logger.error("Error plotting %s", desc)
            logger.info("Plotted %s", desc)
        pctl.ClosePlot()
        logger.info("Gerber generation complete")

    # ------------------------------------------------------------------
    # Excellon Drill
    # ------------------------------------------------------------------
    def generate_excellon(self):
        """Generate Excellon drill files."""
        from pcbnew import EXCELLON_WRITER
        drl = EXCELLON_WRITER(self.board)
        offset = self.board.GetDesignSettings().GetAuxOrigin()
        drl.SetOptions(False, False, offset, False)
        drl.SetFormat(False)
        drl.CreateDrillandMapFilesSet(self.gerberdir, True, True)
        logger.info("Excellon drill generation complete")

    # ------------------------------------------------------------------
    # ZIP bundle
    # ------------------------------------------------------------------
    def zip_gerber_excellon(self) -> str:
        """Create GERBER-<project>.zip ready for JLCPCB upload. Returns path."""
        zipname = f"GERBER-{self.project_name}.zip"
        zippath = os.path.join(self.outputdir, zipname)
        with ZipFile(zippath, "w", compression=ZIP_DEFLATED, compresslevel=9) as zf:
            for fn in os.listdir(self.gerberdir):
                if fn.endswith(("gbr", "drl", "pdf")):
                    zf.write(os.path.join(self.gerberdir, fn), fn)
        logger.info("Created %s", zippath)
        return zippath

    # ------------------------------------------------------------------
    # BOM
    # ------------------------------------------------------------------
    def generate_bom(self, parts: list) -> str:
        """Generate BOM CSV. `parts` is a list of dicts from JLCStore.
        Returns the file path."""
        bomname = f"{self.project_name}_BOM_JLC.csv"
        bompath = os.path.join(self.outputdir, bomname)

        # Group by (value, footprint, lcsc)
        groups = {}
        for p in parts:
            if p.get("exclude_from_bom"):
                continue
            key = (p["value"], p["footprint"], p.get("lcsc", ""))
            groups.setdefault(key, []).append(p["reference"])

        with open(bompath, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #", "Quantity"])
            for (val, fp, lcsc), refs in sorted(groups.items()):
                w.writerow([val, ",".join(sorted(refs)), fp, lcsc, len(refs)])

        logger.info("BOM → %s (%d groups)", bompath, len(groups))
        return bompath

    # ------------------------------------------------------------------
    # CPL  (centroid / pick-and-place)
    # ------------------------------------------------------------------
    def generate_cpl(self, parts: list) -> str:
        """Generate CPL CSV. Returns the file path."""
        from pcbnew import ToMM
        cplname = f"{self.project_name}_CPL_JLC.csv"
        cplpath = os.path.join(self.outputdir, cplname)
        aux = self.board.GetDesignSettings().GetAuxOrigin()

        with open(cplpath, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Designator", "Val", "Package", "Mid X", "Mid Y", "Rotation", "Layer"])
            for fp in sorted(self.board.Footprints(), key=lambda x: x.GetReference()):
                ref = fp.GetReference()
                part = next((p for p in parts if p["reference"] == ref), None)
                if not part:
                    continue
                if part.get("exclude_from_pos"):
                    continue
                pos = self._get_position(fp)
                try:
                    pos = pos - aux
                except TypeError:
                    from pcbnew import VECTOR2I
                    x1, y1 = pos
                    x2, y2 = aux
                    pos = VECTOR2I(x1 - x2, y1 - y2)

                pos = self._fix_position(fp, pos)
                rotation = self._fix_rotation(fp)

                w.writerow([
                    ref,
                    part["value"],
                    part["footprint"],
                    ToMM(pos.x),
                    ToMM(pos.y) * -1,
                    rotation,
                    "top" if fp.GetLayer() == 0 else "bottom",
                ])

        logger.info("CPL → %s", cplpath)
        return cplpath

    # ------------------------------------------------------------------
    # Interactive HTML BOM
    # ------------------------------------------------------------------
    def generate_ibom(self):
        """Invoke the currently installed InteractiveHtmlBom plugin if available."""
        # Find InteractiveHtmlBom installation
        kicad_docs = Path(os.path.expanduser("~/Documents/KiCad"))
        possible_paths = [
            kicad_docs / "9.0" / "3rdparty" / "plugins" / "org_openscopeproject_InteractiveHtmlBom" / "generate_interactive_bom.py",
            kicad_docs / "8.0" / "3rdparty" / "plugins" / "org_openscopeproject_InteractiveHtmlBom" / "generate_interactive_bom.py",
            kicad_docs / "9.0" / "scripting" / "plugins" / "InteractiveHtmlBom" / "generate_interactive_bom.py",
            kicad_docs / "8.0" / "scripting" / "plugins" / "InteractiveHtmlBom" / "generate_interactive_bom.py",
        ]
        
        ibom_script = None
        for p in possible_paths:
            if p.exists():
                ibom_script = p
                break
                
        if not ibom_script:
            logger.warning("InteractiveHtmlBom plugin not found. Skipping iBOM generation.")
            return None
            
        logger.info(f"Found InteractiveHtmlBom at {ibom_script}")
        
        # We must run it using KiCad's Python executable
        kicad_python = sys.executable
        
        cmd = [
            kicad_python,
            str(ibom_script),
            "--no-browser",
            "--dest-dir", self.outputdir,
            "--name-format", f"{self.project_name}_iBOM",
            "--extra-fields", "LCSC",
            "--show-fabrication",
            self.board.GetFileName()
        ]
        
        try:
            logger.info(f"Running iBOM: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            logger.info("iBOM generation successful.")
            return os.path.join(self.outputdir, f"{self.project_name}_iBOM.html")
        except subprocess.CalledProcessError as e:
            logger.error(f"iBOM generation failed: {e.stderr}")
            return None

    # ------------------------------------------------------------------
    # Production bundle  (Gerber ZIP + BOM + CPL in one folder)
    # ------------------------------------------------------------------
    def generate_all(self, parts: list, layer_count=None) -> str:
        """One-click: generate everything. Returns the output directory."""
        self.generate_gerber(layer_count)
        self.generate_excellon()
        self.zip_gerber_excellon()
        self.generate_bom(parts)
        self.generate_cpl(parts)
        self.generate_ibom()
        return self.outputdir

    # ------------------------------------------------------------------
    # Rotation / Position Corrections (ported from Bouni)
    # ------------------------------------------------------------------
    def _get_position(self, footprint):
        try:
            pads = footprint.Pads()
            bbox = pads[0].GetBoundingBox()
            for pad in pads:
                bbox.Merge(pad.GetBoundingBox())
            return bbox.GetCenter()
        except Exception:
            return footprint.GetPosition()

    def _fix_rotation(self, footprint):
        try:
            rotation = footprint.GetOrientation().AsDegrees()
        except AttributeError:
            rotation = footprint.GetOrientation() / 10
        if footprint.GetLayer() != 0:
            rotation = (180 - rotation) % 360
        for regex, corr, _ in self.corrections:
            if re.search(regex, str(footprint.GetReference())):
                return (rotation + int(corr)) % 360
        for regex, corr, _ in self.corrections:
            if re.search(regex, str(footprint.GetValue())):
                return (rotation + int(corr)) % 360
        for regex, corr, _ in self.corrections:
            if re.search(regex, str(footprint.GetFPID().GetLibItemName())):
                return (rotation + int(corr)) % 360
        return rotation

    def _fix_position(self, footprint, position):
        from pcbnew import FromMM, wxPoint
        for regex, _, offset in self.corrections:
            target = None
            if re.search(regex, str(footprint.GetReference())):
                target = offset
            elif re.search(regex, str(footprint.GetValue())):
                target = offset
            elif re.search(regex, str(footprint.GetFPID().GetLibItemName())):
                target = offset
            if target and (target[0] != 0 or target[1] != 0):
                try:
                    rot = footprint.GetOrientation().AsDegrees()
                except AttributeError:
                    rot = footprint.GetOrientation() / 10
                if footprint.GetLayer() != 0:
                    rot = (180 - rot) % 360
                ox = FromMM(target[0]) * math.cos(math.radians(rot)) + FromMM(target[1]) * math.sin(math.radians(rot))
                oy = -FromMM(target[0]) * math.sin(math.radians(rot)) + FromMM(target[1]) * math.cos(math.radians(rot))
                if footprint.GetLayer() != 0:
                    ox = -ox
                return wxPoint(position.x + ox, position.y + oy)
        return position
