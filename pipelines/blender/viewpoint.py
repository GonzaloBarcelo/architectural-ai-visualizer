"""Pure-Python interior viewpoint search (no bpy), so it can be tested outside Blender.

The camera is placed inside the largest room, clear of walls and furniture, looking in the
direction with the most open depth. It never adds or changes architecture.
"""

import math


def area(polygon):
    return (
        abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(polygon, polygon[1:] + polygon[:1]))) / 2
    )


def inside(point, polygon):
    x, y = point
    result = False
    for (x0, y0), (x1, y1) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            result = not result
    return result


def edges(polygons):
    return [(a, b) for p in polygons for a, b in zip(p, p[1:] + p[:1])]


def segment_distance(point, a, b):
    (px, py), (ax, ay), (bx, by) = point, a, b
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    t = 0 if length == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / length))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def ray(origin, angle, segments, limit=15.0):
    ox, oy = origin
    dx, dy = math.cos(angle), math.sin(angle)
    best = limit
    for (ax, ay), (bx, by) in segments:
        ex, ey = bx - ax, by - ay
        denominator = dx * ey - dy * ex
        if abs(denominator) < 1e-12:
            continue
        t = ((ax - ox) * ey - (ay - oy) * ex) / denominator
        u = ((ax - ox) * dy - (ay - oy) * dx) / denominator
        if 1e-6 < t < best and -1e-9 <= u <= 1 + 1e-9:
            best = t
    return best


FOV = math.radians(70)


def best_view(rooms, walls, furniture=(), clearance=0.45, fov=FOV, tall=(), focus=None):
    """Return ((x, y), angle) for the most open view from inside the largest room.

    Walls and tall furniture (wardrobes, shelving, wall units) block sight lines; low
    furniture right in front of the lens is penalised so it does not fill the foreground.
    """
    if not rooms:
        return None
    room = max(rooms, key=area)
    # The room's own outline bounds the view: a camera frames its room, not the next one.
    blocking = edges(walls) + edges(tall) + edges([room])
    low = edges(furniture)
    obstacles = blocking + low
    xs, ys = [p[0] for p in room], [p[1] for p in room]
    step = max(0.2, min(max(xs) - min(xs), max(ys) - min(ys)) / 12)
    candidates = []
    y = min(ys) + step / 2
    while y < max(ys):
        x = min(xs) + step / 2
        while x < max(xs):
            if (
                inside((x, y), room)
                and not any(inside((x, y), f) for f in [*furniture, *tall])
                and all(segment_distance((x, y), a, b) >= clearance for a, b in obstacles)
            ):
                candidates.append((x, y))
            x += step
        y += step
    if not candidates:
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        candidates = [(cx, cy)]
    best = None
    offsets = [fov * (i / 8 - 0.5) for i in range(9)]
    for point in candidates:
        for k in range(36):
            angle = 2 * math.pi * k / 36
            depths = [ray(point, angle + o, blocking) for o in offsets]
            # Favour deep, evenly open views; a near wall in the centre ruins the image.
            score = sum(depths) / len(depths) + 0.5 * min(depths) + 0.5 * depths[4]
            near = min(ray(point, angle + o, low, limit=1.4) for o in offsets[2:7])
            if near < 1.4:
                score -= 8 * (1.4 - near)
            if focus:
                # Frame the room's hero piece (bed, sofa, vanity) near the image centre.
                fx = sum(p[0] for p in focus) / len(focus) - point[0]
                fy = sum(p[1] for p in focus) / len(focus) - point[1]
                off = abs((math.atan2(fy, fx) - angle + math.pi) % (2 * math.pi) - math.pi)
                distance = math.hypot(fx, fy)
                # Stand on the piece's front side (foot of the bed, facing the sofa or vanity):
                # footprints are ordered back-left, back-right, front-right, front-left.
                front = True
                if len(focus) == 4:
                    bx, by = (focus[0][0] + focus[1][0]) / 2, (focus[0][1] + focus[1][1]) / 2
                    gx, gy = (focus[2][0] + focus[3][0]) / 2, (focus[2][1] + focus[3][1]) / 2
                    front = (point[0] - gx) * (gx - bx) + (point[1] - gy) * (gy - by) > 0
                if off < fov * 0.3 and distance > 1.2 and front:
                    score += 6 + min(distance, 4) * 0.5
            if best is None or score > best[0]:
                best = (score, point, angle)
    return best[1], best[2]
