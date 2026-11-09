"""Synthetic DXF floor plans built with ezdxf (no client data). Units: millimetres.

A 6 × 4 m flat: 200 mm outer walls, a 100 mm partition at x = 3.0 m with an 800 mm door gap,
a 1200 mm window gap in the south facade. Left room "Dormitorio" with a 150 bed block rotated
90° against the west wall; right room "Baño" with a toilet block mirrored and rotated 90°
against the partition.
"""

import ezdxf

WALLS = [
    (0, 0, 1000, 200),
    (2200, 0, 6000, 200),
    (0, 3800, 6000, 4000),
    (0, 200, 200, 3800),
    (5800, 200, 6000, 3800),
    (3000, 200, 3100, 1000),
    (3000, 1800, 3100, 3800),
]


def rectangle(layout, x0, y0, x1, y1, layer):
    layout.add_lwpolyline(
        [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs={"layer": layer}
    )


def build(path, unknown=False, insunits=4, offset=(0, 0), copies=1, wall_layer="MUROS"):
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = insunits
    msp = doc.modelspace()

    door = doc.blocks.new("PUERTA_80")
    rectangle(door, 0, -100, 800, 0, "0")  # frame across the wall
    door.add_line((0, 0), (0, 800))  # leaf, open
    door.add_arc((0, 0), 800, 0, 90)  # swing

    window = doc.blocks.new("VENTANA_120")
    rectangle(window, 0, 0, 1200, 200, "0")
    window.add_line((0, 100), (1200, 100))

    bed = doc.blocks.new("CAMA_150")  # headboard at local +y, foot at local -y (the front)
    rectangle(bed, 0, 0, 1500, 2000, "0")
    rectangle(bed, 100, 1650, 1400, 1950, "0")  # pillows at the head

    toilet = doc.blocks.new("INODORO")  # cistern at local +y, bowl towards local -y
    rectangle(toilet, 0, 450, 400, 700, "0")
    toilet.add_ellipse((200, 230), major_axis=(0, 220), ratio=0.7)

    mystery = doc.blocks.new("XYZ123")
    rectangle(mystery, 0, 0, 600, 600, "0")
    mystery.add_circle((300, 300), 200)

    for copy in range(copies):
        dx, dy = offset[0] + copy * 20000, offset[1]
        for x0, y0, x1, y1 in WALLS:
            rectangle(msp, x0 + dx, y0 + dy, x1 + dx, y1 + dy, wall_layer)
        msp.add_blockref(
            "PUERTA_80", (3000 + dx, 1000 + dy), dxfattribs={"rotation": 90, "layer": "PUERTAS"}
        )
        msp.add_blockref("VENTANA_120", (1000 + dx, 0 + dy), dxfattribs={"layer": "VENTANAS"})
        msp.add_blockref(
            "CAMA_150", (2200 + dx, 1200 + dy), dxfattribs={"rotation": 90, "layer": "MOBILIARIO"}
        )
        msp.add_blockref(
            "INODORO",
            (3800 + dx, 3000 + dy),
            dxfattribs={"rotation": 90, "xscale": -1, "layer": "MOBILIARIO"},
        )
        msp.add_text("Dormitorio", dxfattribs={"insert": (1500 + dx, 3000 + dy), "height": 150})
        msp.add_mtext(
            "Baño\\PSup. 9.62 m2", dxfattribs={"insert": (4500 + dx, 1500 + dy), "char_height": 150}
        )
        msp.add_text(
            f"PLANTA {copy + 1}", dxfattribs={"insert": (2000 + dx, -800 + dy), "height": 200}
        )
        if unknown:
            msp.add_blockref("XYZ123", (5000 + dx, 600 + dy), dxfattribs={"layer": "MOBILIARIO"})
    msp.add_linear_dim(
        base=(0 + offset[0], -500 + offset[1]),
        p1=(0 + offset[0], 0 + offset[1]),
        p2=(6000 + offset[0], 0 + offset[1]),
        dxfattribs={"layer": "COTAS"},
    ).render()
    doc.saveas(path)
    return path
