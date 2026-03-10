# BFR KiCad Library Manager

All-in-one KiCad plugin for library management and JLCPCB manufacturing integration.

## Features

- **Import** component ZIPs from Samacsys, Snapeda, UltraLibrarian, Octopart, EasyEDA/LCSC
- **Auto-classify** into organized `bfr_*` libraries (resistors, capacitors, ICs, etc.)
- **LCSC metadata enrichment** — auto-lookup part data from JLCPCB (no API key)
- **Sort Later** tab for organizing your `bfr_master` library
- **External library** bulk importer
- **Auto-Init** project library tables with one click

### ⚡ JLCPCB Production Bridge

- Live JLCPCB part search with detailed specs (voltage, power, tolerance, package)
- One-click LCSC assignment with automatic metadata autopopulation
- 🤖 **Auto-Assign LCSC** — cross-references all your MPNs against JLCPCB in one click
- **Select Alike** for bulk passive assignment
- Gerber, Drill, BOM, CPL generation
- **Interactive HTML BOM** integration (uses your installed InteractiveHtmlBom plugin)
- Schematic LCSC sync — writes LCSC numbers back to `.kicad_sch`

### 🏁 BFR Logo Stamp

Place the BFR logo on your board's silkscreen layer.

---

## Installation via KiCad Plugin Manager

1. Open **KiCad** → **Plugin and Content Manager**
2. Click **Manage Repositories** (bottom-left)
3. Click **+** to add a new repository:
   - **Name**: `BFR KiCad Repository`
   - **URL**: `https://raw.githubusercontent.com/bfracing/bfr-kicad-library-manager/main/repository/repository.json`
4. Click **Save**
5. Find **"BFR KiCad Library Manager"** in the plugin list
6. Click **Install** → **Apply Pending Changes**
7. Restart KiCad — the plugin appears under **Tools → External Plugins**

---

## Requirements

- KiCad 8.0 or later
- Python 3 (included with KiCad)
- Optional: [InteractiveHtmlBom](https://github.com/openscopeproject/InteractiveHtmlBom) plugin for iBOM generation

## License

MIT
