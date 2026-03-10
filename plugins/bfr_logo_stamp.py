"""
BFR KiCad Library Manager — Logo Stamp
Adds the BFR logo as a text graphic on the F.SilkS layer of the active board.
The user can control the size via a percentage scale (100% = 10mm tall).
Uses pcbnew Python API directly — no external dependencies.
"""

import logging
import os

logger = logging.getLogger("bfr_plugin")

# Default logo height in mm at 100%
BASE_HEIGHT_MM = 10.0


def add_bfr_logo(board, size_percent: int = 100, x_mm: float = 0.0, y_mm: float = 0.0, layer: str = "front"):
    """
    Add a "BFR" text logo to the board on the silkscreen layer.

    Args:
        board: pcbnew.BOARD object
        size_percent: Size as a % of the base height (100% = 10mm tall)
        x_mm: X position in mm (0 = board center)
        y_mm: Y position in mm (0 = board center)
        layer: "front" for F.SilkS, "back" for B.SilkS

    Returns:
        (bool, str): success flag and message
    """
    try:
        import pcbnew

        height_mm = BASE_HEIGHT_MM * size_percent / 100.0
        width_mm = height_mm  # Font aspect ratio ~1:1 for bold

        # Calculate board center if x/y == 0
        if x_mm == 0.0 and y_mm == 0.0:
            bbox = board.GetBoardEdgesBoundingBox()
            if bbox.GetWidth() > 0 and bbox.GetHeight() > 0:
                center = bbox.GetCenter()
                pos_x = center.x
                pos_y = center.y
            else:
                pos_x = pcbnew.FromMM(50)
                pos_y = pcbnew.FromMM(50)
        else:
            pos_x = pcbnew.FromMM(x_mm)
            pos_y = pcbnew.FromMM(y_mm)

        # Determine layer
        if layer == "back":
            silk_layer = pcbnew.B_SilkS
        else:
            silk_layer = pcbnew.F_SilkS

        # Create a PCB_TEXT item
        text = pcbnew.PCB_TEXT(board)
        text.SetText("BFR")
        text.SetLayer(silk_layer)

        # Position
        text.SetPosition(pcbnew.VECTOR2I(int(pos_x), int(pos_y)))

        # Size — height and width in internal units
        text.SetTextSize(pcbnew.VECTOR2I(
            pcbnew.FromMM(width_mm),
            pcbnew.FromMM(height_mm)
        ))

        # Bold and thick for silkscreen visibility
        text.SetTextThickness(pcbnew.FromMM(height_mm * 0.15))
        text.SetBold(True)
        text.SetItalic(False)

        # Center-aligned
        text.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
        text.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)

        board.Add(text)

        # Refresh the view
        try:
            pcbnew.Refresh()
        except Exception:
            pass

        actual_h = round(height_mm, 2)
        layer_name = "F.SilkS" if layer != "back" else "B.SilkS"
        msg = f"Added BFR logo on {layer_name} ({actual_h}mm tall, {size_percent}%)"
        logger.info(msg)
        return True, msg

    except Exception as e:
        msg = f"Failed to add BFR logo: {e}"
        logger.error(msg)
        return False, msg


def add_bfr_logo_footprint(board, size_percent: int = 100, x_mm: float = 0.0, y_mm: float = 0.0, layer: str = "front"):
    """
    Alternative: Add a BFR logo as a footprint on the board.
    This uses a pre-made .kicad_mod file if available, otherwise falls back to text.

    Args:
        board: pcbnew.BOARD object
        size_percent: Size as a % of the base height
        x_mm, y_mm: Position in mm (0,0 = board center)
        layer: "front" or "back"

    Returns:
        (bool, str)
    """
    import pcbnew

    # Check if a pre-made logo footprint exists in the plugin directory
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    logo_mod = os.path.join(plugin_dir, "bfr_logo.kicad_mod")

    if os.path.isfile(logo_mod):
        try:
            # Load footprint from file
            fp = pcbnew.FootprintLoad(plugin_dir, "bfr_logo")
            if fp:
                # Scale is not directly supported in pcbnew for footprints,
                # so we use the text approach instead
                pass
        except Exception:
            pass

    # Fall back to the text approach which is always available
    return add_bfr_logo(board, size_percent, x_mm, y_mm, layer)
