"""
BFR KiCad Library Manager - wxPython GUI
Supports SEPARATE symbol and footprint library paths.
Fixed dialog lifecycle to prevent KiCad bricking.
"""

import json
import logging
import os
import sys
from pathlib import Path
from threading import Thread
from typing import Optional

import wx
import wx.adv
import wx.dataview

logger = logging.getLogger("bfr_plugin")

try:
    from .bfr_backend import BFRBackend
except ImportError:
    from bfr_backend import BFRBackend


class FileDropTarget(wx.FileDropTarget):
    """Drop target for ZIP files."""

    def __init__(self, callback):
        wx.FileDropTarget.__init__(self)
        self.callback = callback

    def OnDropFiles(self, x, y, filenames):
        zip_files = [f for f in filenames if f.lower().endswith(".zip")]
        if zip_files:
            self.callback(zip_files)
            return True
        return False


class BFRLibraryManagerGUI(wx.Dialog):
    """Main GUI for BFR KiCad Library Manager."""

    TITLE = "BFR KiCad Library Manager"
    SIZE = (750, 700)

    def __init__(self, parent=None):
        wx.Dialog.__init__(
            self, parent,
            id=wx.ID_ANY,
            title=self.TITLE,
            size=self.SIZE,
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )

        self.SetMinSize((650, 550))

        # Initialize backend
        self.backend = BFRBackend()
        self.backend.set_log_callback(self._append_log)

        # Settings
        self.settings_file = Path.home() / ".bfr_kicad_manager_settings.json"
        self.settings = self._load_settings()

        self._build_ui()
        self._bind_events()
        
        # Populate dynamic UI elements (like the Override dropdown) on startup
        wx.CallAfter(self._refresh_sort_list)
        
        self.Centre()

    def _load_settings(self) -> dict:
        default_sym = str(Path.home() / "KiCad" / "bfr_symbols")
        default_fp = str(Path.home() / "KiCad" / "bfr_footprints")
        defaults = {
            "sym_path": default_sym,
            "fp_path": default_fp,
            "auto_enrich": True,
            "auto_master": True,
        }
        if self.settings_file.exists():
            try:
                with open(self.settings_file, "r") as f:
                    defaults.update(json.load(f))
            except Exception as e:
                logger.warning(f"Failed to load settings: {e}")
        return defaults

    def _save_settings(self):
        try:
            with open(self.settings_file, "w") as f:
                json.dump(self.settings, f, indent=4)
        except Exception as e:
            logger.warning(f"Failed to save settings: {e}")

    def _build_ui(self):
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Title banner
        title_panel = wx.Panel(self)
        title_panel.SetBackgroundColour(wx.Colour(40, 44, 52))
        title_sizer = wx.BoxSizer(wx.VERTICAL)

        title_label = wx.StaticText(title_panel, label="BFR KiCad Library Manager")
        title_font = wx.Font(16, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        title_label.SetFont(title_font)
        title_label.SetForegroundColour(wx.Colour(97, 175, 239))
        title_sizer.Add(title_label, 0, wx.ALL | wx.ALIGN_CENTER, 8)

        subtitle = wx.StaticText(title_panel, label="Import • Classify • Enrich • Organize")
        subtitle.SetForegroundColour(wx.Colour(150, 150, 170))
        title_sizer.Add(subtitle, 0, wx.BOTTOM | wx.ALIGN_CENTER, 8)

        title_panel.SetSizer(title_sizer)
        main_sizer.Add(title_panel, 0, wx.EXPAND)

        # Notebook
        self.notebook = wx.Notebook(self)
        self.import_panel = self._build_import_tab(self.notebook)
        self.notebook.AddPage(self.import_panel, "Import")

        self.sort_panel = self._build_sort_tab(self.notebook)
        self.notebook.AddPage(self.sort_panel, "Sort Later")

        self.external_panel = self._build_external_tab(self.notebook)
        self.notebook.AddPage(self.external_panel, "External Libs")

        self.jlcpcb_panel = self._build_jlcpcb_tab(self.notebook)
        self.notebook.AddPage(self.jlcpcb_panel, "⚡ JLCPCB")

        self.settings_panel = self._build_settings_tab(self.notebook)
        self.notebook.AddPage(self.settings_panel, "Settings")

        main_sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 5)

        # Status bar
        self.status_bar = wx.StaticText(self, label="Ready")
        self.status_bar.SetForegroundColour(wx.Colour(100, 100, 120))
        main_sizer.Add(self.status_bar, 0, wx.EXPAND | wx.ALL, 5)

        self.SetSizer(main_sizer)

    # ─── Import Tab ──────────────────────────────────────────

    def _build_import_tab(self, parent):
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Symbols path
        sym_sizer = wx.BoxSizer(wx.HORIZONTAL)
        sym_sizer.Add(wx.StaticText(panel, label="Symbols Path:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.sym_path_ctrl = wx.TextCtrl(panel, value=self.settings.get("sym_path", ""))
        sym_sizer.Add(self.sym_path_ctrl, 1, wx.EXPAND | wx.RIGHT, 5)
        sym_browse = wx.Button(panel, label="Browse...")
        sym_browse.Bind(wx.EVT_BUTTON, lambda e: self._browse_path(self.sym_path_ctrl))
        sym_sizer.Add(sym_browse, 0)
        sizer.Add(sym_sizer, 0, wx.EXPAND | wx.ALL, 8)

        # Footprints path
        fp_sizer = wx.BoxSizer(wx.HORIZONTAL)
        fp_sizer.Add(wx.StaticText(panel, label="Footprints Path:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.fp_path_ctrl = wx.TextCtrl(panel, value=self.settings.get("fp_path", ""))
        fp_sizer.Add(self.fp_path_ctrl, 1, wx.EXPAND | wx.RIGHT, 5)
        fp_browse = wx.Button(panel, label="Browse...")
        fp_browse.Bind(wx.EVT_BUTTON, lambda e: self._browse_path(self.fp_path_ctrl))
        fp_sizer.Add(fp_browse, 0)
        sizer.Add(fp_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # Drop zone
        drop_panel = wx.Panel(panel)
        drop_panel.SetBackgroundColour(wx.Colour(45, 50, 60))
        drop_panel.SetMinSize((-1, 80))
        drop_sizer = wx.BoxSizer(wx.VERTICAL)
        drop_sizer.AddStretchSpacer()

        drop_label = wx.StaticText(drop_panel, label="Drag & Drop ZIP files here", style=wx.ALIGN_CENTER)
        drop_font = wx.Font(13, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        drop_label.SetFont(drop_font)
        drop_label.SetForegroundColour(wx.Colour(97, 175, 239))
        drop_sizer.Add(drop_label, 0, wx.ALIGN_CENTER | wx.ALL, 5)

        drop_hint = wx.StaticText(drop_panel, label="Samacsys, Snapeda, UltraLibrarian, Octopart, EasyEDA/LCSC", style=wx.ALIGN_CENTER)
        drop_hint.SetForegroundColour(wx.Colour(120, 120, 140))
        drop_sizer.Add(drop_hint, 0, wx.ALIGN_CENTER | wx.BOTTOM, 5)

        drop_sizer.AddStretchSpacer()
        drop_panel.SetSizer(drop_sizer)
        dt = FileDropTarget(self._on_files_dropped)
        drop_panel.SetDropTarget(dt)
        sizer.Add(drop_panel, 0, wx.EXPAND | wx.ALL, 8)

        # Controls row
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        select_btn = wx.Button(panel, label="Select ZIP File(s)...")
        select_btn.Bind(wx.EVT_BUTTON, self._on_select_files)
        btn_sizer.Add(select_btn, 0, wx.RIGHT, 10)

        btn_sizer.Add(wx.StaticText(panel, label="Override:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.target_override = wx.Choice(panel, choices=["Auto-classify"] + self.backend.get_target_libraries())
        self.target_override.SetSelection(0)
        btn_sizer.Add(self.target_override, 0)
        sizer.Add(btn_sizer, 0, wx.ALL, 8)

        # Log area
        self.log_text = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL | wx.TE_RICH2)
        self.log_text.SetBackgroundColour(wx.Colour(30, 33, 39))
        self.log_text.SetForegroundColour(wx.Colour(171, 178, 191))
        log_font = wx.Font(10, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
        self.log_text.SetFont(log_font)
        dt2 = FileDropTarget(self._on_files_dropped)
        self.log_text.SetDropTarget(dt2)
        sizer.Add(self.log_text, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        panel.SetSizer(sizer)
        return panel

    # ─── Sort Tab ────────────────────────────────────────────

    def _build_sort_tab(self, parent):
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)

        src_sizer = wx.BoxSizer(wx.HORIZONTAL)
        src_sizer.Add(wx.StaticText(panel, label="Source:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.sort_source = wx.Choice(panel, choices=[])
        self.sort_source.Bind(wx.EVT_CHOICE, self._on_sort_source_change)
        src_sizer.Add(self.sort_source, 0, wx.RIGHT, 10)

        refresh_btn = wx.Button(panel, label="Refresh")
        refresh_btn.Bind(wx.EVT_BUTTON, self._on_refresh_sort_list)
        src_sizer.Add(refresh_btn, 0, wx.RIGHT, 10)

        consolidate_btn = wx.Button(panel, label="Consolidate All -> bfr_master")
        consolidate_btn.Bind(wx.EVT_BUTTON, self._on_consolidate)
        src_sizer.Add(consolidate_btn, 0)
        sizer.Add(src_sizer, 0, wx.EXPAND | wx.ALL, 10)

        self.sort_list = wx.ListBox(panel, style=wx.LB_MULTIPLE | wx.LB_HSCROLL)
        sizer.Add(self.sort_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        move_sizer = wx.BoxSizer(wx.HORIZONTAL)
        move_sizer.Add(wx.StaticText(panel, label="Move to:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.sort_target = wx.Choice(panel, choices=[])
        move_sizer.Add(self.sort_target, 1, wx.RIGHT, 10)

        move_btn = wx.Button(panel, label="Move Selected")
        move_btn.Bind(wx.EVT_BUTTON, self._on_move_component)
        move_sizer.Add(move_btn, 0)
        sizer.Add(move_sizer, 0, wx.EXPAND | wx.ALL, 10)

        panel.SetSizer(sizer)
        
        # Populate initial list if possible
        wx.CallAfter(self._refresh_sort_list)
        return panel

    # ─── External Libs Tab ───────────────────────────────────

    def _build_external_tab(self, parent):
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        path_sizer = wx.BoxSizer(wx.HORIZONTAL)
        path_sizer.Add(wx.StaticText(panel, label="External Library Path:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.ext_path_ctrl = wx.TextCtrl(panel)
        path_sizer.Add(self.ext_path_ctrl, 1, wx.EXPAND | wx.RIGHT, 5)
        browse_btn = wx.Button(panel, label="Browse...")
        browse_btn.Bind(wx.EVT_BUTTON, self._on_browse_ext)
        path_sizer.Add(browse_btn, 0, wx.RIGHT, 5)
        load_btn = wx.Button(panel, label="Scan Folder")
        load_btn.Bind(wx.EVT_BUTTON, self._on_scan_ext)
        path_sizer.Add(load_btn, 0)
        
        sizer.Add(path_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        self.ext_list = wx.CheckListBox(panel, style=wx.LB_HSCROLL)
        sizer.Add(self.ext_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        sel_all = wx.Button(panel, label="Select All")
        sel_all.Bind(wx.EVT_BUTTON, lambda e: self._set_all_ext_checked(True))
        sel_none = wx.Button(panel, label="Select None")
        sel_none.Bind(wx.EVT_BUTTON, lambda e: self._set_all_ext_checked(False))
        
        import_btn = wx.Button(panel, label="Import Checked to bfr_master")
        import_btn.Bind(wx.EVT_BUTTON, self._on_import_ext)
        
        btn_sizer.Add(sel_all, 0, wx.RIGHT, 5)
        btn_sizer.Add(sel_none, 0, wx.RIGHT, 10)
        btn_sizer.Add(import_btn, 0)
        sizer.Add(btn_sizer, 0, wx.ALL, 10)
        
        info = wx.StaticText(panel, label="Select a folder containing .kicad_sym or .pretty libraries.\nChecked libraries will be read, and all their components (symbols & footprints) will be appended into bfr_master.")
        info.SetForegroundColour(wx.Colour(130, 130, 150))
        sizer.Add(info, 0, wx.ALL, 10)
        
        panel.SetSizer(sizer)
        return panel

    # ─── Settings Tab ────────────────────────────────────────

    def _build_settings_tab(self, parent):
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(wx.StaticText(panel, label="Symbols Directory:"), 0, wx.LEFT | wx.TOP, 10)
        s1 = wx.BoxSizer(wx.HORIZONTAL)
        self.settings_sym = wx.TextCtrl(panel, value=self.settings.get("sym_path", ""))
        s1.Add(self.settings_sym, 1, wx.EXPAND | wx.RIGHT, 5)
        b1 = wx.Button(panel, label="Browse...")
        b1.Bind(wx.EVT_BUTTON, lambda e: self._browse_path(self.settings_sym))
        s1.Add(b1, 0)
        sizer.Add(s1, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        sizer.Add(wx.StaticText(panel, label="Footprints Directory:"), 0, wx.LEFT | wx.TOP, 10)
        s2 = wx.BoxSizer(wx.HORIZONTAL)
        self.settings_fp = wx.TextCtrl(panel, value=self.settings.get("fp_path", ""))
        s2.Add(self.settings_fp, 1, wx.EXPAND | wx.RIGHT, 5)
        b2 = wx.Button(panel, label="Browse...")
        b2.Bind(wx.EVT_BUTTON, lambda e: self._browse_path(self.settings_fp))
        s2.Add(b2, 0)
        sizer.Add(s2, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        sizer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.ALL, 10)

        self.auto_enrich_cb = wx.CheckBox(panel, label="Auto-lookup LCSC/JLCPCB metadata on import")
        self.auto_enrich_cb.SetValue(self.settings.get("auto_enrich", True))
        sizer.Add(self.auto_enrich_cb, 0, wx.ALL, 10)

        self.auto_master_cb = wx.CheckBox(panel, label="Always add to bfr_master on import")
        self.auto_master_cb.SetValue(self.settings.get("auto_master", True))
        sizer.Add(self.auto_master_cb, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        sizer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.ALL, 10)

        save_btn = wx.Button(panel, label="Save Settings")
        save_btn.Bind(wx.EVT_BUTTON, self._on_save_settings)
        
        init_btn = wx.Button(panel, label="Initialize Current Project Libraries")
        init_btn.Bind(wx.EVT_BUTTON, self._on_init_project)
        
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        btn_sizer.Add(save_btn, 0, wx.RIGHT, 10)
        btn_sizer.Add(init_btn, 0)
        sizer.Add(btn_sizer, 0, wx.ALL, 10)

        info = wx.StaticText(panel, label=(
            "BFR KiCad Library Manager v1.0\n\n"
            "Supported: Samacsys, Snapeda, UltraLibrarian, Octopart, EasyEDA/LCSC\n"
            "LCSC metadata via JLCPCB API (no API key needed)\n"
        ))
        info.SetForegroundColour(wx.Colour(130, 130, 150))
        sizer.Add(info, 0, wx.ALL, 10)

        # ── BFR Logo Stamp ──
        sizer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.ALL, 5)

        logo_hdr = wx.StaticText(panel, label="🏁 BFR Logo Stamp")
        logo_hdr_font = wx.Font(11, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        logo_hdr.SetFont(logo_hdr_font)
        logo_hdr.SetForegroundColour(wx.Colour(97, 175, 239))
        sizer.Add(logo_hdr, 0, wx.LEFT | wx.TOP, 10)

        logo_desc = wx.StaticText(panel, label="Place the BFR logo on the silkscreen layer of the active board.")
        logo_desc.SetForegroundColour(wx.Colour(150, 150, 170))
        sizer.Add(logo_desc, 0, wx.LEFT | wx.BOTTOM, 10)

        logo_ctrl_sizer = wx.BoxSizer(wx.HORIZONTAL)

        logo_ctrl_sizer.Add(wx.StaticText(panel, label="Size %:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.logo_size_spin = wx.SpinCtrl(panel, value="100", min=10, max=500, initial=100, size=(70, -1))
        self.logo_size_spin.SetToolTip("100% = 10mm tall. Adjust to scale proportionally.")
        logo_ctrl_sizer.Add(self.logo_size_spin, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)

        logo_ctrl_sizer.Add(wx.StaticText(panel, label="Layer:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.logo_layer_choice = wx.Choice(panel, choices=["Front (F.SilkS)", "Back (B.SilkS)"])
        self.logo_layer_choice.SetSelection(0)
        logo_ctrl_sizer.Add(self.logo_layer_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)

        logo_stamp_btn = wx.Button(panel, label="🏁 Stamp BFR Logo")
        logo_stamp_btn.SetToolTip("Add the BFR logo to the active board's silkscreen")
        logo_stamp_btn.Bind(wx.EVT_BUTTON, self._on_stamp_logo)
        logo_ctrl_sizer.Add(logo_stamp_btn, 0, wx.ALIGN_CENTER_VERTICAL)

        sizer.Add(logo_ctrl_sizer, 0, wx.ALL, 10)

        panel.SetSizer(sizer)
        return panel

    # ─── JLCPCB Tab ──────────────────────────────────────────

    def _build_jlcpcb_tab(self, parent):
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Header
        hdr = wx.StaticText(panel, label="⚡ JLCPCB Production Bridge")
        hdr_font = wx.Font(13, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        hdr.SetFont(hdr_font)
        hdr.SetForegroundColour(wx.Colour(97, 175, 239))
        sizer.Add(hdr, 0, wx.ALL, 8)

        desc = wx.StaticText(panel, label="Assign LCSC parts, generate Gerbers/BOM/CPL, and sync to schematic — all in one click.")
        desc.SetForegroundColour(wx.Colour(150, 150, 170))
        sizer.Add(desc, 0, wx.LEFT | wx.BOTTOM, 8)

        # ── Footprint List (DataViewListCtrl) ──
        self.jlc_list = wx.dataview.DataViewListCtrl(panel, style=wx.BORDER_THEME | wx.dataview.DV_ROW_LINES | wx.dataview.DV_MULTIPLE)
        self.jlc_list.AppendTextColumn("Ref", width=60)
        self.jlc_list.AppendTextColumn("Value", width=140)
        self.jlc_list.AppendTextColumn("Footprint", width=180)
        self.jlc_list.AppendTextColumn("LCSC", width=90)
        self.jlc_list.AppendTextColumn("BOM", width=50)
        self.jlc_list.AppendTextColumn("POS", width=50)
        sizer.Add(self.jlc_list, 1, wx.EXPAND | wx.ALL, 5)

        # ── Search & Assign row ──
        assign_sizer = wx.BoxSizer(wx.HORIZONTAL)
        assign_sizer.Add(wx.StaticText(panel, label="LCSC #:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.jlc_lcsc_input = wx.TextCtrl(panel, size=(120, -1))
        self.jlc_lcsc_input.SetHint("C485162")
        assign_sizer.Add(self.jlc_lcsc_input, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)

        btn_assign = wx.Button(panel, label="Assign")
        btn_assign.SetToolTip("Assign this LCSC number to the selected footprint(s)")
        btn_assign.Bind(wx.EVT_BUTTON, self._on_jlc_assign)
        assign_sizer.Add(btn_assign, 0, wx.RIGHT, 4)

        btn_remove = wx.Button(panel, label="Remove")
        btn_remove.SetToolTip("Remove LCSC number from selected footprint(s)")
        btn_remove.Bind(wx.EVT_BUTTON, self._on_jlc_remove)
        assign_sizer.Add(btn_remove, 0, wx.RIGHT, 4)

        btn_alike = wx.Button(panel, label="Select Alike")
        btn_alike.SetToolTip("Assign the same LCSC to all parts sharing value + footprint")
        btn_alike.Bind(wx.EVT_BUTTON, self._on_jlc_select_alike)
        assign_sizer.Add(btn_alike, 0, wx.RIGHT, 4)

        assign_sizer.AddStretchSpacer()

        btn_search = wx.Button(panel, label="🔍 Search JLCPCB")
        btn_search.SetToolTip("Search the live JLCPCB database by MPN or keyword")
        btn_search.Bind(wx.EVT_BUTTON, self._on_jlc_search)
        assign_sizer.Add(btn_search, 0)

        sizer.Add(assign_sizer, 0, wx.EXPAND | wx.ALL, 5)

        # ── Live search input ──
        search_sizer = wx.BoxSizer(wx.HORIZONTAL)
        search_sizer.Add(wx.StaticText(panel, label="Search:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self.jlc_search_input = wx.TextCtrl(panel, size=(250, -1), style=wx.TE_PROCESS_ENTER)
        self.jlc_search_input.SetHint("Type MPN or keyword, e.g. 10k 0603")
        self.jlc_search_input.Bind(wx.EVT_TEXT_ENTER, self._on_jlc_search)
        search_sizer.Add(self.jlc_search_input, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)

        self.jlc_search_results = wx.dataview.DataViewListCtrl(panel, style=wx.BORDER_THEME | wx.dataview.DV_ROW_LINES | wx.dataview.DV_SINGLE)
        self.jlc_search_results.AppendTextColumn("LCSC", width=80)
        self.jlc_search_results.AppendTextColumn("MPN", width=120)
        self.jlc_search_results.AppendTextColumn("Package", width=80)
        self.jlc_search_results.AppendTextColumn("Details", width=300)
        self.jlc_search_results.AppendTextColumn("Stock", width=60)
        self.jlc_search_results.SetMinSize((-1, 150))
        
        sizer.Add(search_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)
        sizer.Add(self.jlc_search_results, 0, wx.EXPAND | wx.ALL, 5)

        # ── Action buttons ──
        action_sizer = wx.BoxSizer(wx.HORIZONTAL)

        btn_refresh = wx.Button(panel, label="↻ Refresh Board")
        btn_refresh.SetToolTip("Re-read all footprints from the active PCB")
        btn_refresh.Bind(wx.EVT_BUTTON, self._on_jlc_refresh)
        action_sizer.Add(btn_refresh, 0, wx.RIGHT, 8)

        btn_auto = wx.Button(panel, label="🤖 Auto-Assign LCSC")
        btn_auto.SetToolTip("Auto-fill empty LCSC numbers by searching each part's MPN on JLCPCB")
        btn_auto.Bind(wx.EVT_BUTTON, self._on_jlc_auto_assign)
        action_sizer.Add(btn_auto, 0, wx.RIGHT, 8)

        btn_generate = wx.Button(panel, label="📦 Generate Production Files")
        btn_generate.SetToolTip("Generate Gerbers, Drill, BOM, CPL and ZIP for JLCPCB")
        btn_generate.Bind(wx.EVT_BUTTON, self._on_jlc_generate)
        action_sizer.Add(btn_generate, 0, wx.RIGHT, 8)

        btn_schematic = wx.Button(panel, label="📋 Sync LCSC → Schematic")
        btn_schematic.SetToolTip("Write all LCSC assignments back into the .kicad_sch file")
        btn_schematic.Bind(wx.EVT_BUTTON, self._on_jlc_sync_schematic)
        action_sizer.Add(btn_schematic, 0)

        sizer.Add(action_sizer, 0, wx.ALL, 5)

        panel.SetSizer(sizer)

        # State
        self._jlc_store = None
        self._jlc_search_cache = []  # list of (lcsc, mpn, desc, package, stock, price)

        return panel

    # ─── JLCPCB Event Handlers ───────────────────────────────

    def _get_jlc_store(self):
        """Lazy-init the JLC store (requires pcbnew)."""
        if self._jlc_store is None:
            try:
                import pcbnew
                board = pcbnew.GetBoard()
                if board is None:
                    wx.MessageBox("No board is open. Please open a PCB file first.", "No Board", wx.OK | wx.ICON_WARNING)
                    return None
                try:
                    from .jlc_store import JLCStore
                except ImportError:
                    from jlc_store import JLCStore
                self._jlc_store = JLCStore(board)
            except Exception as e:
                wx.MessageBox(f"Failed to read board: {e}", "Error", wx.OK | wx.ICON_ERROR)
                return None
        return self._jlc_store

    def _on_jlc_refresh(self, event):
        """Refresh the footprint list from the active board."""
        self._jlc_store = None  # force re-init
        store = self._get_jlc_store()
        if not store:
            return
        self.jlc_list.DeleteAllItems()
        for p in store.read_all():
            self.jlc_list.AppendItem([
                p["reference"],
                p["value"],
                p["footprint"],
                p.get("lcsc", ""),
                "✗" if p.get("exclude_from_bom") else "✓",
                "✗" if p.get("exclude_from_pos") else "✓",
            ])
        self.status_bar.SetLabel(f"JLCPCB: Loaded {len(store.read_all())} parts from board")

    def _get_selected_jlc_refs(self) -> list:
        """Get the reference designators of all selected rows in the JLC list."""
        refs = []
        for i in range(self.jlc_list.GetItemCount()):
            if self.jlc_list.IsRowSelected(i):
                refs.append(self.jlc_list.GetTextValue(i, 0))
        return refs

    def _on_jlc_assign(self, event):
        lcsc = self.jlc_lcsc_input.GetValue().strip().upper()
        if not lcsc:
            wx.MessageBox("Enter an LCSC part number (e.g. C485162).", "Missing", wx.OK | wx.ICON_WARNING)
            return
        if not lcsc.startswith("C"):
            lcsc = f"C{lcsc}"
        store = self._get_jlc_store()
        if not store:
            return
        refs = self._get_selected_jlc_refs()
        if not refs:
            wx.MessageBox("Select one or more parts in the list first.", "No Selection", wx.OK | wx.ICON_WARNING)
            return
        for ref in refs:
            store.set_lcsc(ref, lcsc)
        
        # Pull metadata from JLCPCB and autopopulate empty fields on the footprint
        self._enrich_footprint_from_lcsc(store, lcsc, refs)
        
        self._on_jlc_refresh(None)
        self.status_bar.SetLabel(f"Assigned {lcsc} to {len(refs)} part(s) + metadata")

    def _enrich_footprint_from_lcsc(self, store, lcsc: str, refs: list):
        """Fetch metadata for an LCSC part and write it to all given footprints."""
        try:
            try:
                from .bfr_metadata import lookup_lcsc
            except ImportError:
                from bfr_metadata import lookup_lcsc
            meta = lookup_lcsc(lcsc)
            if not meta:
                return
            fields = {}
            if meta.mpn:
                fields["MPN"] = meta.mpn
            if meta.manufacturer:
                fields["Manufacturer"] = meta.manufacturer
            if meta.description:
                fields["Description"] = meta.description
            if meta.datasheet_url:
                fields["Datasheet"] = meta.datasheet_url
            if meta.package:
                fields["Package"] = meta.package
            # Add all extra electrical attributes (Voltage, Power, Tolerance, etc.)
            for attr_key, attr_val in meta.extra_attributes.items():
                fields[attr_key] = attr_val
            if fields:
                for ref in refs:
                    store.set_fields_for_ref(ref, fields)
                logger.info(f"Enriched {len(refs)} parts with {len(fields)} fields from {lcsc}")
        except Exception as e:
            logger.warning(f"Metadata enrichment failed for {lcsc}: {e}")

    def _on_jlc_auto_assign(self, event):
        """Auto-assign LCSC numbers to all parts that have an empty LCSC field.
        Cross-references each part's value (MPN) against the JLCPCB database."""
        store = self._get_jlc_store()
        if not store:
            return

        parts = store.read_all()
        empty_parts = [p for p in parts if not p.get("lcsc")]
        if not empty_parts:
            wx.MessageBox("All parts already have LCSC numbers assigned!", "Nothing to do", wx.OK | wx.ICON_INFORMATION)
            return

        dlg = wx.MessageBox(
            f"This will search JLCPCB for {len(empty_parts)} parts without LCSC numbers.\n"
            f"It uses the Value field as the MPN to search.\n\n"
            f"This may take a moment. Continue?",
            "Auto-Assign LCSC", wx.YES_NO | wx.ICON_QUESTION
        )
        if dlg != wx.YES:
            return

        self.status_bar.SetLabel(f"Auto-assigning LCSC for {len(empty_parts)} parts...")
        wx.Yield()

        def auto_assign_thread():
            try:
                try:
                    from .bfr_metadata import search_lcsc_by_mpn
                except ImportError:
                    from bfr_metadata import search_lcsc_by_mpn

                assigned = 0
                failed = 0
                for i, part in enumerate(empty_parts, 1):
                    ref = part["reference"]
                    # Use Value as MPN search term (most common approach)
                    mpn = part.get("value", "").strip()
                    if not mpn or len(mpn) < 3:
                        failed += 1
                        continue

                    wx.CallAfter(self.status_bar.SetLabel,
                                 f"[{i}/{len(empty_parts)}] Searching '{mpn}' for {ref}...")

                    meta = search_lcsc_by_mpn(mpn)
                    if meta and meta.lcsc_part:
                        store.set_lcsc(ref, meta.lcsc_part)
                        # Also enrich metadata
                        fields = {}
                        if meta.mpn:
                            fields["MPN"] = meta.mpn
                        if meta.manufacturer:
                            fields["Manufacturer"] = meta.manufacturer
                        if meta.description:
                            fields["Description"] = meta.description
                        if meta.datasheet_url:
                            fields["Datasheet"] = meta.datasheet_url
                        if meta.package:
                            fields["Package"] = meta.package
                        for attr_key, attr_val in meta.extra_attributes.items():
                            fields[attr_key] = attr_val
                        if fields:
                            store.set_fields_for_ref(ref, fields)
                        assigned += 1
                        wx.CallAfter(self._append_log,
                                     f"✓ {ref} ({mpn}) → {meta.lcsc_part}")
                    else:
                        failed += 1
                        wx.CallAfter(self._append_log,
                                     f"✗ {ref} ({mpn}) — no match found")

                wx.CallAfter(self._on_jlc_refresh, None)
                wx.CallAfter(self.status_bar.SetLabel,
                             f"Auto-assign complete: {assigned} assigned, {failed} not found")
                wx.CallAfter(wx.MessageBox,
                             f"Auto-Assign Complete!\n\n"
                             f"Assigned: {assigned}\n"
                             f"Not found: {failed}",
                             "Auto-Assign Results", wx.OK | wx.ICON_INFORMATION)
            except Exception as e:
                logger.exception("Auto-assign error:")
                wx.CallAfter(self.status_bar.SetLabel, f"Auto-assign failed: {e}")

        Thread(target=auto_assign_thread, daemon=True).start()

    def _on_jlc_remove(self, event):
        store = self._get_jlc_store()
        if not store:
            return
        refs = self._get_selected_jlc_refs()
        for ref in refs:
            store.remove_lcsc(ref)
        self._on_jlc_refresh(None)
        self.status_bar.SetLabel(f"Removed LCSC from {len(refs)} part(s)")

    def _on_jlc_select_alike(self, event):
        lcsc = self.jlc_lcsc_input.GetValue().strip().upper()
        if not lcsc:
            wx.MessageBox("Enter an LCSC part number first.", "Missing", wx.OK | wx.ICON_WARNING)
            return
        if not lcsc.startswith("C"):
            lcsc = f"C{lcsc}"
        store = self._get_jlc_store()
        if not store:
            return
        refs = self._get_selected_jlc_refs()
        if not refs:
            wx.MessageBox("Select a part first — all alike parts will be matched.", "No Selection", wx.OK | wx.ICON_WARNING)
            return
        affected = store.set_lcsc_for_alike(refs[0], lcsc)
        self._on_jlc_refresh(None)
        self.status_bar.SetLabel(f"Assigned {lcsc} to {len(affected)} alike part(s): {', '.join(affected)}")

    def _on_jlc_search(self, event):
        """Search the live JLCPCB database."""
        keyword = self.jlc_search_input.GetValue().strip()
        if not keyword:
            wx.MessageBox("Type a search keyword first.", "Missing", wx.OK | wx.ICON_WARNING)
            return
        self.status_bar.SetLabel(f"Searching JLCPCB for '{keyword}'...")
        self.jlc_search_results.DeleteAllItems()
        wx.Yield()

        try:
            from .bfr_metadata import _make_request
        except ImportError:
            from bfr_metadata import _make_request

        url = "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
        payload = {"keyword": keyword, "currentPage": 1, "pageSize": 20}
        data = _make_request(url, payload=payload)

        self._jlc_search_cache = []
        if data and data.get("data") and data["data"].get("componentPageInfo"):
            records = data["data"]["componentPageInfo"].get("list", [])
            for r in records:
                lcsc = r.get("componentCode", "")
                mpn  = r.get("componentModelEn", "")
                
                # Parse attributes for detailed specs (resistance, voltage, power, tolerance)
                details = []
                attrs = r.get("attributes", [])
                for attr in attrs:
                    # e.g., "Resistance", "Power(Watts)", "Voltage-Supply(Max)", "Tolerance"
                    name_en = attr.get("attribute_name_en", "")
                    val = attr.get("attribute_value_name", "")
                    if val and name_en not in ("Type", "Operating Temperature"):
                        details.append(val)
                
                desc = ", ".join(details)
                if not desc:
                    desc = r.get("describe", "")[:80]
                    
                pkg  = r.get("componentSpecificationEn", "")
                stock = str(r.get("stockCount", 0))
                
                self._jlc_search_cache.append(lcsc)
                self.jlc_search_results.AppendItem([lcsc, mpn, pkg, desc, stock])
                
            self.status_bar.SetLabel(f"Found {len(records)} results for '{keyword}'")
        else:
            self.status_bar.SetLabel(f"No results for '{keyword}'")

        # Allow double-click to auto-fill LCSC input
        self.jlc_search_results.Bind(wx.dataview.EVT_DATAVIEW_ITEM_ACTIVATED, self._on_jlc_search_select)

    def _on_jlc_search_select(self, event):
        item = event.GetItem()
        row = self.jlc_search_results.ItemToRow(item)
        if 0 <= row < len(self._jlc_search_cache):
            lcsc = self._jlc_search_cache[row]
            self.jlc_lcsc_input.SetValue(lcsc)
            self.status_bar.SetLabel(f"Selected {lcsc} — now select footprint(s) and click Assign")

    def _on_jlc_generate(self, event):
        """Generate all JLCPCB production files."""
        store = self._get_jlc_store()
        if not store:
            return
        self.status_bar.SetLabel("Generating production files...")
        wx.Yield()
        try:
            import pcbnew
            try:
                from .jlc_fabrication import JLCFabrication
            except ImportError:
                from jlc_fabrication import JLCFabrication
            board = pcbnew.GetBoard()
            fab = JLCFabrication(board)
            outdir = fab.generate_all(store.read_all())
            wx.MessageBox(
                f"Production files generated!\n\n"
                f"Output: {outdir}\n\n"
                f"Files:\n"
                f"  • GERBER-{store.project_name}.zip\n"
                f"  • {store.project_name}_BOM_JLC.csv\n"
                f"  • {store.project_name}_CPL_JLC.csv\n"
                f"  • {store.project_name}_iBOM.html (if plugin installed)",
                "JLCPCB Export Complete", wx.OK | wx.ICON_INFORMATION
            )
            self.status_bar.SetLabel(f"Production files → {outdir}")
        except Exception as e:
            wx.MessageBox(f"Error generating files: {e}", "Error", wx.OK | wx.ICON_ERROR)
            self.status_bar.SetLabel("Production file generation failed")

    def _on_jlc_sync_schematic(self, event):
        """Export LCSC assignments to the schematic file."""
        store = self._get_jlc_store()
        if not store:
            return
        try:
            import pcbnew
            board_file = pcbnew.GetBoard().GetFileName()
            sch_file = board_file.replace(".kicad_pcb", ".kicad_sch")
            if not os.path.isfile(sch_file):
                wx.MessageBox(f"Schematic not found at:\n{sch_file}", "Not Found", wx.OK | wx.ICON_WARNING)
                return
            try:
                from .jlc_schematic_export import JLCSchematicExport
            except ImportError:
                from jlc_schematic_export import JLCSchematicExport
            exporter = JLCSchematicExport(store)
            count = exporter.export(sch_file)
            wx.MessageBox(
                f"Synced {count} LCSC number(s) to schematic.\n\n"
                f"File: {sch_file}\n\n"
                f"A backup was saved as {sch_file}_old",
                "Schematic Sync Complete", wx.OK | wx.ICON_INFORMATION
            )
            self.status_bar.SetLabel(f"Synced {count} LCSC → schematic")
        except Exception as e:
            wx.MessageBox(f"Error: {e}", "Schematic Sync Failed", wx.OK | wx.ICON_ERROR)

    def _on_stamp_logo(self, event):
        """Stamp the BFR logo on the active board's silkscreen layer."""
        try:
            import pcbnew
            board = pcbnew.GetBoard()
            if board is None:
                wx.MessageBox("No board is open. Please open a PCB file first.", "No Board", wx.OK | wx.ICON_WARNING)
                return

            size_pct = self.logo_size_spin.GetValue()
            layer = "front" if self.logo_layer_choice.GetSelection() == 0 else "back"

            try:
                from .bfr_logo_stamp import add_bfr_logo
            except ImportError:
                from bfr_logo_stamp import add_bfr_logo

            ok, msg = add_bfr_logo(board, size_percent=size_pct, layer=layer)
            if ok:
                wx.MessageBox(msg, "Logo Stamped", wx.OK | wx.ICON_INFORMATION)
                self.status_bar.SetLabel(msg)
            else:
                wx.MessageBox(msg, "Error", wx.OK | wx.ICON_ERROR)
        except Exception as e:
            wx.MessageBox(f"Error: {e}", "Logo Stamp Failed", wx.OK | wx.ICON_ERROR)

    # ─── Events ──────────────────────────────────────────────

    def _bind_events(self):
        self.Bind(wx.EVT_CLOSE, self._on_close)

    def _on_close(self, event):
        """CRITICAL: Proper cleanup to prevent KiCad from bricking."""
        # Save settings on close as well, just in case
        self._sync_paths()
        self.settings["sym_path"] = self.sym_path_ctrl.GetValue().strip()
        self.settings["fp_path"] = self.fp_path_ctrl.GetValue().strip()
        self.settings["auto_enrich"] = self.auto_enrich_cb.GetValue()
        self.settings["auto_master"] = self.auto_master_cb.GetValue()
        self._save_settings()
        self.EndModal(wx.ID_OK)

    def _append_log(self, msg: str):
        if wx.IsMainThread():
            self.log_text.AppendText(msg + "\n")
        else:
            wx.CallAfter(self.log_text.AppendText, msg + "\n")

    def _browse_path(self, text_ctrl):
        dlg = wx.DirDialog(self, "Select Directory", defaultPath=text_ctrl.GetValue())
        if dlg.ShowModal() == wx.ID_OK:
            text_ctrl.SetValue(dlg.GetPath())
            self._sync_paths()
            self._refresh_sort_list()
        dlg.Destroy()

    def _sync_paths(self):
        """Sync paths from import tab to backend."""
        sym = self.sym_path_ctrl.GetValue().strip()
        fp = self.fp_path_ctrl.GetValue().strip()
        if sym:
            self.backend.set_paths(sym, fp or sym)

    def _on_save_settings(self, event):
        sym = self.settings_sym.GetValue().strip()
        fp = self.settings_fp.GetValue().strip()
        if sym:
            self.sym_path_ctrl.SetValue(sym)
            self.fp_path_ctrl.SetValue(fp or sym)
            self.backend.set_paths(sym, fp or sym)
            self.settings["sym_path"] = sym
            self.settings["fp_path"] = fp or sym
            
        self.backend.auto_enrich = self.auto_enrich_cb.GetValue()
        self.backend.auto_master = self.auto_master_cb.GetValue()
        
        self.settings["auto_enrich"] = self.backend.auto_enrich
        self.settings["auto_master"] = self.backend.auto_master
        
        self._save_settings()
        self._refresh_sort_list()
        self._append_log("Settings saved permanently.")

    def _on_init_project(self, event):
        try:
            import pcbnew
            board = pcbnew.GetBoard()
            board_path = board.GetFileName()
        except Exception as e:
            wx.MessageBox(f"Could not communicate with KiCad.\n\nError: {e}", "Error", wx.OK | wx.ICON_ERROR)
            return

        if not board_path:
            wx.MessageBox("No board file found. Please open an active PCB file in the project first.", "Error", wx.OK | wx.ICON_WARNING)
            return

        prj_dir = Path(board_path).parent
        sym_table = prj_dir / "sym-lib-table"
        fp_table = prj_dir / "fp-lib-table"
        
        self._sync_paths()
        libs = self.backend.get_all_libraries()
        
        # Issue 2 Fix: Strictly filter only "bfr_" libraries. Ignore emails, dates, or other random libs.
        bfr_libs = [lib for lib in libs if lib.startswith("bfr_")]
        
        if not bfr_libs:
            wx.MessageBox("No libraries starting with 'bfr_' found in your symbols path.", "Error", wx.OK | wx.ICON_WARNING)
            return

        added_sym = 0
        added_fp = 0
        
        # 1. Update sym-lib-table
        sym_content = "(sym_lib_table\n)\n"
        if sym_table.exists():
            sym_content = sym_table.read_text(encoding="utf-8")
        
        sym_path_base = Path(self.sym_path_ctrl.GetValue().strip())
        for lib in bfr_libs:
            # Only add if we don't already have it
            if f'(name "{lib}")' not in sym_content:
                # Optionally check if the file actually exists to be safe
                if (sym_path_base / f"{lib}.kicad_sym").exists():
                    uri = f"${{BFRSYM}}/{lib}.kicad_sym"
                    idx = sym_content.rfind(')')
                    if idx != -1:
                        entry = f'  (lib (name "{lib}")(type "KiCad")(uri "{uri}")(options "")(descr ""))\n'
                        sym_content = sym_content[:idx] + entry + sym_content[idx:]
                        added_sym += 1

        if added_sym > 0:
            sym_table.write_text(sym_content, encoding="utf-8")
        
        # 2. Update fp-lib-table
        fp_content = "(fp_lib_table\n)\n"
        if fp_table.exists():
            fp_content = fp_table.read_text(encoding="utf-8")
            
        fp_dir_base = Path(self.fp_path_ctrl.GetValue().strip())
        for lib in bfr_libs:
            if f'(name "{lib}")' not in fp_content:
                # Issue 1 Fix: Box Drive crashed because we were aggressively running mkdir() on
                # 15+ folders sequentially over a cloud NAS. Just assume the folder will exist
                # or check if it exists instead of forcing directory creation.
                uri = f"${{BFRFT}}/{lib}.pretty"
                idx = fp_content.rfind(')')
                if idx != -1:
                    entry = f'  (lib (name "{lib}")(type "KiCad")(uri "{uri}")(options "")(descr ""))\n'
                    fp_content = fp_content[:idx] + entry + fp_content[idx:]
                    added_fp += 1
                    
        if added_fp > 0:
            fp_table.write_text(fp_content, encoding="utf-8")

        # Issue 3 Fix: The user must be explicitly told to reopen the project or KiCad won't show them.
        msg = (
            f"Initialized Project Libraries!\n\n"
            f"Project: {prj_dir.name}\n"
            f"Added {added_sym} symbol libraries.\n"
            f"Added {added_fp} footprint libraries.\n\n"
            f"IMPORTANT: KiCad only reads these tables when the project loads. "
            f"You MUST close and reopen this KiCad Project for the libraries to appear in your tables."
        )
        wx.MessageBox(msg, "Success - Restart Required", wx.OK | wx.ICON_INFORMATION)

    def _on_select_files(self, event):
        dlg = wx.FileDialog(self, "Select ZIP file(s)", wildcard="ZIP files (*.zip)|*.zip", style=wx.FD_OPEN | wx.FD_MULTIPLE)
        if dlg.ShowModal() == wx.ID_OK:
            self._do_import(dlg.GetPaths())
        dlg.Destroy()

    def _on_files_dropped(self, filenames):
        self._do_import(filenames)

    def _do_import(self, zip_paths: list):
        self._sync_paths()
        self.backend.auto_enrich = self.auto_enrich_cb.GetValue()
        self.backend.auto_master = self.auto_master_cb.GetValue()

        override = ""
        sel = self.target_override.GetSelection()
        if sel > 0:
            override = self.target_override.GetString(sel)

        self.status_bar.SetLabel(f"Importing {len(zip_paths)} file(s)...")

        def import_thread():
            try:
                for i, zpath in enumerate(zip_paths, 1):
                    wx.CallAfter(self.status_bar.SetLabel, f"[{i}/{len(zip_paths)}] {Path(zpath).name}")
                    self.backend.import_zip(zpath, target_override=override)
                wx.CallAfter(self.status_bar.SetLabel, f"Done — imported {len(zip_paths)} file(s)")
            except Exception as e:
                logger.exception("Import error:")
                wx.CallAfter(self._append_log, f"\nFATAL ERROR during import: {e}\nCheck the terminal/log for details.")
                wx.CallAfter(self.status_bar.SetLabel, f"Import failed: {e}")

        Thread(target=import_thread, daemon=True).start()

    def _on_sort_source_change(self, event):
        self._refresh_sort_list()

    def _on_refresh_sort_list(self, event):
        self._refresh_sort_list()

    def _refresh_sort_list(self):
        self._sync_paths()
        
        # Update dropdown choices
        libs = self.backend.get_all_libraries()
        
        # Update override dropdown in Import tab
        override_sel = self.target_override.GetStringSelection()
        override_choices = ["Auto-classify"] + self.backend.get_target_libraries()
        self.target_override.SetItems(override_choices)
        if override_sel in override_choices:
            self.target_override.SetStringSelection(override_sel)
        else:
            self.target_override.SetSelection(0)
        
        # Save current selections
        src_sel = self.sort_source.GetStringSelection()
        tgt_sel = self.sort_target.GetStringSelection()
        
        self.sort_source.SetItems(libs)
        self.sort_target.SetItems(libs)
        
        # Restore selections or defaults
        if src_sel in libs:
            self.sort_source.SetStringSelection(src_sel)
        elif libs:
            self.sort_source.SetStringSelection("bfr_master") if "bfr_master" in libs else self.sort_source.SetSelection(0)
                
        if tgt_sel in libs:
            self.sort_target.SetStringSelection(tgt_sel)
        elif libs:
            self.sort_target.SetSelection(0)

        self.sort_list.Clear()
        source = self.sort_source.GetStringSelection()
        if source:
            symbols = self.backend.get_symbols_in_library(source)
            for sym in symbols:
                self.sort_list.Append(sym)
            self.status_bar.SetLabel(f"{len(symbols)} components in {source}")
        else:
            self.status_bar.SetLabel("No libraries found in path")

    def _on_consolidate(self, event):
        self._sync_paths()
        count, msg = self.backend.consolidate_master()
        wx.MessageBox(msg, "Consolidation Complete", wx.OK | wx.ICON_INFORMATION)
        self._refresh_sort_list()

    def _on_move_component(self, event):
        selections = self.sort_list.GetSelections()
        if not selections:
            wx.MessageBox("Select one or more components first.", "No Selection", wx.OK | wx.ICON_WARNING)
            return

        from_lib = self.sort_source.GetStringSelection()
        to_lib = self.sort_target.GetStringSelection()

        if not to_lib:
            wx.MessageBox("Select a target library.", "No Target", wx.OK | wx.ICON_WARNING)
            return

        success_count = 0
        error_msgs = []

        for sel in selections:
            symbol_name = self.sort_list.GetString(sel)
            ok, msg = self.backend.sort_component(symbol_name, from_lib, to_lib)
            if ok:
                success_count += 1
            else:
                error_msgs.append(msg)

        if error_msgs:
            wx.MessageBox(f"Moved {success_count} components.\nErrors:\n" + "\n".join(error_msgs), "Partial Success", wx.OK | wx.ICON_WARNING)
        else:
            wx.MessageBox(f"Successfully moved {success_count} components.", "Moved", wx.OK | wx.ICON_INFORMATION)
            
        self._refresh_sort_list()

    def _on_browse_ext(self, event):
        dlg = wx.DirDialog(self, "Select External Library Folder", defaultPath=self.ext_path_ctrl.GetValue())
        if dlg.ShowModal() == wx.ID_OK:
            self.ext_path_ctrl.SetValue(dlg.GetPath())
            self._on_scan_ext(None)
        dlg.Destroy()
        
    def _on_scan_ext(self, event):
        path = self.ext_path_ctrl.GetValue().strip()
        libs = self.backend.list_external_libraries(path)
        self.ext_list.Clear()
        if libs:
            self.ext_list.AppendItems(libs)
            self._set_all_ext_checked(True)
            self.status_bar.SetLabel(f"Found {len(libs)} external libraries")
        else:
            self.status_bar.SetLabel("No .kicad_sym or .pretty files found in directory")
            
    def _set_all_ext_checked(self, state: bool):
        for i in range(self.ext_list.GetCount()):
            self.ext_list.Check(i, state)

    def _on_import_ext(self, event):
        path = self.ext_path_ctrl.GetValue().strip()
        checked = [self.ext_list.GetString(i) for i in range(self.ext_list.GetCount()) if self.ext_list.IsChecked(i)]
        
        if not path or not checked:
            wx.MessageBox("Select a folder and check at least one library.", "Missing Selection", wx.OK | wx.ICON_WARNING)
            return
            
        syms, fps, msg = self.backend.import_external_libraries(path, checked)
        wx.MessageBox(f"Success!\n\nImported {syms} symbols and {fps} footprints into bfr_master.", "Import Complete", wx.OK | wx.ICON_INFORMATION)
        self._refresh_sort_list()


def run_standalone():
    app = wx.App()
    frame = BFRLibraryManagerGUI()
    frame.ShowModal()
    frame.Destroy()
    app.MainLoop()


if __name__ == "__main__":
    run_standalone()
