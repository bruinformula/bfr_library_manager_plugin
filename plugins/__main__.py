"""
BFR KiCad Library Manager - CLI Entry Point
Allows import from the command line without the GUI.
"""

import argparse
import sys
from pathlib import Path

# Ensure plugin directory is in path
plugin_dir = Path(__file__).resolve().parent
if str(plugin_dir) not in sys.path:
    sys.path.insert(0, str(plugin_dir))


def main():
    parser = argparse.ArgumentParser(
        description="BFR KiCad Library Manager - Import KiCad libraries from zip files"
    )
    parser.add_argument(
        "--zip", "-z",
        required=False,
        nargs="+",
        help="Path(s) to zip file(s) to import",
    )
    parser.add_argument(
        "--lib-path", "-l",
        required=True,
        help="Path to BFR library directory",
    )
    parser.add_argument(
        "--target", "-t",
        required=False,
        default="",
        help="Override target library (e.g., bfr_resistors). Default: auto-classify",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="Skip LCSC metadata enrichment",
    )
    parser.add_argument(
        "--no-master",
        action="store_true",
        help="Don't add to bfr_master",
    )
    parser.add_argument(
        "--consolidate",
        action="store_true",
        help="Consolidate all BFR libraries into bfr_master",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the GUI",
    )

    args = parser.parse_args()

    from bfr_backend import BFRBackend

    backend = BFRBackend(args.lib_path)
    backend.auto_enrich = not args.no_enrich
    backend.auto_master = not args.no_master
    backend.set_log_callback(print)

    if args.gui:
        import wx
        from bfr_gui import BFRLibraryManagerGUI
        app = wx.App()
        gui = BFRLibraryManagerGUI()
        gui.backend.set_lib_path(args.lib_path)
        gui.lib_path_ctrl.SetValue(args.lib_path)
        gui.settings_path.SetValue(args.lib_path)
        gui.ShowModal()
        gui.Destroy()
        return

    if args.consolidate:
        count, msg = backend.consolidate_master()
        print(msg)
        return

    if not args.zip:
        parser.error("--zip is required unless using --consolidate or --gui")

    for zip_path in args.zip:
        result = backend.import_zip(zip_path, target_override=args.target)
        if result.success:
            print(f"✓ Imported {result.component_name} → {result.target_library}")
        else:
            print(f"✗ Failed to import {zip_path}")
            for msg in result.messages:
                print(f"  {msg}")


if __name__ == "__main__":
    main()
