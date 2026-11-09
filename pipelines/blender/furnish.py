"""Parametric, explicitly illustrative furniture; no external assets or invented provenance."""


def furnish(data, floors, prism, material):
    finishes = data.get("finishes") or {}

    def finish(key, name, color, roughness):
        f = finishes.get(key)
        if f:
            return material(f"Interior / {f['name']} proposal", tuple(f["color"]), f["roughness"])
        return material(name, color, roughness)

    oak = finish("furniture_wood", "Interior / oak proposal", (0.32, 0.18, 0.08), 0.6)
    fabric = finish("upholstery", "Interior / linen proposal", (0.62, 0.57, 0.46), 0.9)
    ceramic = finish("ceramic", "Interior / ceramic proposal", (0.83, 0.83, 0.79), 0.25)
    for item in data.get("furniture", []):
        xs = [p[0] for p in item["polygon"]]
        ys = [p[1] for p in item["polygon"]]
        x, y = min(xs), min(ys)
        w, d = max(xs) - x, max(ys) - y
        h = item["height"]
        z = next(f["elevation"] for f in data["floors"] if f["id"] == item["floor_id"])
        kind = item["name"].split(" / ")[0]
        parts = []

        def piece(
            name,
            a,
            b,
            c,
            e,
            bottom,
            height,
            mat,
            item=item,
            x=x,
            y=y,
            w=w,
            d=d,
            z=z,
            h=h,
            parts=parts,
        ):
            obj = prism(
                item["id"] + " / " + name,
                [
                    (x + a * w, y + b * d),
                    (x + c * w, y + b * d),
                    (x + c * w, y + e * d),
                    (x + a * w, y + e * d),
                ],
                z + bottom * h,
                height * h,
                floors[item["floor_id"]],
                mat,
            )
            obj["presentation_id"] = item["id"]
            obj["floor_id"] = item["floor_id"]
            obj["kind"] = "furniture"
            obj["verification_status"] = "inferred"
            obj["source_sha256"] = data["source"]["sha256"]
            parts.append(obj)

        if kind == "table":
            for a, b in [(0, 0), (0.9, 0), (0, 0.9), (0.9, 0.9)]:
                piece("leg", a, b, a + 0.1, b + 0.1, 0, 0.94, oak)
            piece("top", 0, 0, 1, 1, 0.94, 0.06, oak)
        elif kind == "chair":
            # Seat at ~0.45 m of a 0.85 m chair, with a backrest on the far edge.
            for a, b in [(0.05, 0.05), (0.83, 0.05), (0.05, 0.83), (0.83, 0.83)]:
                piece("leg", a, b, a + 0.12, b + 0.12, 0, 0.5, oak)
            piece("seat", 0, 0, 1, 1, 0.5, 0.06, fabric)
            piece("back", 0, 0.88, 1, 1, 0.56, 0.44, oak)
        elif kind == "bed":
            piece("frame", 0, 0, 1, 1, 0, 0.35, oak)
            piece("mattress", 0.03, 0.03, 0.97, 0.97, 0.35, 0.45, fabric)
            piece("headboard", 0, 0.94, 1, 1, 0.3, 0.7, oak)
            for a in [0.05, 0.52]:
                piece("pillow", a, 0.72, a + 0.4, 0.9, 0.8, 0.16, fabric)
        elif kind == "sofa":
            piece("base", 0, 0, 1, 1, 0, 0.35, oak)
            piece("seat", 0.1, 0.05, 0.9, 0.8, 0.35, 0.2, fabric)
            piece("back", 0, 0.8, 1, 1, 0.35, 0.65, fabric)
            for a in [0, 0.9]:
                piece("arm", a, 0, a + 0.1, 1, 0.35, 0.5, fabric)
        else:
            piece("body", 0, 0, 1, 1, 0, 0.94, ceramic if kind == "sanitary" else oak)
            piece("top", 0, 0, 1, 1, 0.94, 0.06, ceramic)
