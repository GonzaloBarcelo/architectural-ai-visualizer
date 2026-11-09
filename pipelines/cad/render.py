"""Local raster of a DXF region (no pyplot, thread-safe Agg canvas).

The review image covers exactly the plan's sheet so that sheet coordinates (centimetres, y
down) overlay it 1:1. An optional low-resolution labelled copy can accompany the AI call.
"""

import io
import logging

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

logging.getLogger("matplotlib").setLevel(logging.WARNING)


def render_region(doc, region, long_side=2400, labels=None, dpi=100):
    """PNG bytes of model space clipped to ``region`` (x0, y0, x1, y1 in drawing units)."""
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    x0, y0, x1, y1 = region
    width, height = x1 - x0, y1 - y0
    scale = long_side / max(width, height)
    w_px, h_px = max(1, round(width * scale)), max(1, round(height * scale))
    figure = Figure(figsize=(w_px / dpi, h_px / dpi), dpi=dpi)
    FigureCanvasAgg(figure)
    axes = figure.add_axes((0, 0, 1, 1))
    axes.set_axis_off()
    config = Configuration(
        background_policy=BackgroundPolicy.WHITE,
        color_policy=ColorPolicy.MONOCHROME_LIGHT_BG,
        min_lineweight=0.12,
    )

    def visible(entity):
        return entity.dxftype() not in {"PDFUNDERLAY", "DWFUNDERLAY", "DGNUNDERLAY", "VIEWPORT"}

    Frontend(RenderContext(doc), MatplotlibBackend(axes), config=config).draw_layout(
        doc.modelspace(), finalize=False, filter_func=visible
    )
    for text, x, y, colour in labels or []:
        axes.text(
            x,
            y,
            text,
            fontsize=7,
            color=colour,
            ha="center",
            va="center",
            bbox={
                "boxstyle": "square,pad=0.1",
                "fc": "white",
                "ec": colour,
                "lw": 0.4,
                "alpha": 0.8,
            },
        )
    axes.set_xlim(x0, x1)
    axes.set_ylim(y0, y1)
    axes.set_aspect("auto")
    axes.set_facecolor("white")
    figure.patch.set_facecolor("white")
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=dpi, facecolor="white")
    return buffer.getvalue()
