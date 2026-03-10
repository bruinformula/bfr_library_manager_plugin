"""
BFR KiCad Library Manager - KiCad Plugin Entry Point
Registers the plugin with KiCad's PCB Editor via pcbnew.ActionPlugin.
"""

import logging
import sys
from pathlib import Path

# Setup plugin directory
plugin_dir = Path(__file__).resolve().parent

# Ensure plugin dir is in path
if str(plugin_dir) not in sys.path:
    sys.path.insert(0, str(plugin_dir))

# Setup logging
logger = logging.getLogger("bfr_plugin")
log_file = plugin_dir / "bfr_plugin.log"


def setup_logging():
    """Configure logging for the plugin."""
    global logger
    try:
        logger = logging.getLogger("bfr_plugin")
        logger.setLevel(logging.DEBUG)

        # Clear existing handlers
        for h in logger.handlers[:]:
            h.close()
            logger.removeHandler(h)

        # File handler
        fh = logging.FileHandler(str(log_file), mode="w", encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s]: %(message)s"
        ))
        logger.addHandler(fh)

        logger.info("BFR KiCad Library Manager plugin initialized")
        return True
    except Exception as e:
        print(f"BFR Plugin logging setup failed: {e}")
        return False


# Try to import pcbnew (only available inside KiCad)
try:
    import pcbnew
    INSIDE_KICAD = True
except ImportError:
    INSIDE_KICAD = False
    print("BFR Plugin: pcbnew not available (running outside KiCad)")

try:
    import wx
    HAS_WX = True
except ImportError:
    HAS_WX = False
    print("BFR Plugin: wx not available")


if INSIDE_KICAD and HAS_WX:

    class ActionBFRPlugin(pcbnew.ActionPlugin):
        """KiCad Action Plugin for BFR Library Manager."""

        def defaults(self):
            self.name = "BFR KiCad Library Manager"
            self.category = "Library Management"
            self.description = (
                "Import component libraries from zip files with auto-classification, "
                "LCSC metadata enrichment, and library organization"
            )
            self.show_toolbar_button = True

            icon_path = plugin_dir / "icon.png"
            if icon_path.exists():
                self.icon_file_name = str(icon_path)
                self.dark_icon_file_name = str(icon_path)

        def Run(self):
            """Launch the BFR Library Manager GUI."""
            try:
                setup_logging()
                logger.info("BFR Plugin started")

                from .bfr_gui import BFRLibraryManagerGUI

                # CRITICAL: Use proper parent window from KiCad to avoid bricking.
                # Get the PCB editor window as parent.
                parent_window = None
                try:
                    parent_window = wx.FindWindowByName("PcbFrame")
                    if parent_window is None:
                        parent_window = wx.GetTopLevelWindows()[0] if wx.GetTopLevelWindows() else None
                except Exception:
                    pass

                gui = BFRLibraryManagerGUI(parent=parent_window)
                gui.ShowModal()
                gui.Destroy()

                logger.info("BFR Plugin stopped")

            except Exception as e:
                logger.exception("BFR Plugin error")
                try:
                    wx.MessageBox(
                        f"BFR Plugin Error:\n\n{str(e)}\n\nCheck log: {log_file}",
                        "BFR Plugin Error",
                        wx.OK | wx.ICON_ERROR,
                    )
                except Exception:
                    print(f"BFR Plugin Error: {e}")

    # Register the plugin
    ActionBFRPlugin().register()

elif not INSIDE_KICAD:
    # Allow standalone execution for testing
    def main():
        """Run standalone for testing."""
        setup_logging()
        from bfr_gui import BFRLibraryManagerGUI
        app = wx.App()
        gui = BFRLibraryManagerGUI()
        gui.ShowModal()
        gui.Destroy()

    if __name__ == "__main__":
        main()
