"""Geometry fidelity of an AI-enhanced render against its Blender original.

Structure, not colour: the comparison runs on contrast-normalised greyscale at a fixed working
width. Components (each 0..1, higher is better):

- edge_recall: share of the original's Canny edges that still have an edge nearby in the
  enhanced image (added texture does not count against it; moved or removed lines do);
- structure: the structure term of SSIM (local correlation, independent of brightness and
  contrast), weighted towards textured windows;
- line_support: share of the original's long straight lines (walls, openings, furniture
  edges) that are still traced in the enhanced image;
- mask_recall: when the Blender class mask is available, edges along the silhouettes of
  furniture and openings, relative to how many the original itself shows.

Plus alignment: global and worst-tile translation (phase correlation of gradient images), in
percent of the image width. A view passes when the weighted score reaches THRESHOLD and no
tile has drifted more than MAX_SHIFT. Thresholds are calibrated on real runs (see
docs/IMPLEMENTATION_STATUS.md).
"""

import cv2
import numpy as np
from PIL import Image

WIDTH = 640
TOLERANCE = 3  # px at WIDTH: ~0.5 % of the image width
THRESHOLD = 0.62
MAX_SHIFT = 1.5  # % of the image width, worst tile
WEIGHTS = {"edge_recall": 0.35, "structure": 0.25, "line_support": 0.25, "mask_recall": 0.15}

FLEXIBLE_PREFIXES = ("gpt-image-2", "chatgpt-image")
FIXED_SIZES = [(1024, 1024), (1536, 1024), (1024, 1536)]
MIN_PIXELS, MAX_PIXELS, MAX_EDGE, MAX_STABLE = 655_360, 8_294_400, 3840, 2560 * 1440


# --- Canvas: aspect-preserving fit, pad, and exact crop back ----------------------------------


def canvas_plan(width, height, model):
    """How to fit a WxH render into a size the model accepts, without stretching.

    Returns {canvas: [W, H], scale, content: [x, y, w, h], flexible}. The content box is the
    scaled render inside the canvas; the rest is padding, cropped away afterwards.
    """
    flexible = model.startswith(FLEXIBLE_PREFIXES)
    if flexible:
        pixels = width * height
        scale = 1.0
        if pixels > MAX_STABLE:
            scale = (MAX_STABLE / pixels) ** 0.5
        elif pixels < MIN_PIXELS:
            scale = (MIN_PIXELS / pixels) ** 0.5
        w, h = max(16, round(width * scale)), max(16, round(height * scale))
        if (w, h) != (width, height):
            scale = w / width
            h = round(height * scale)
        cw, ch = -(-w // 16) * 16, -(-h // 16) * 16
        # Aspect ratio must stay within 3:1.
        cw, ch = max(cw, -(-ch // 3 // 16) * 16), max(ch, -(-cw // 3 // 16) * 16)
        cw, ch = min(cw, MAX_EDGE), min(ch, MAX_EDGE)
    else:
        aspect = width / height
        cw, ch = min(FIXED_SIZES, key=lambda s: abs(np.log(s[0] / s[1] / aspect)))
        scale = min(cw / width, ch / height)
        w, h = min(cw, round(width * scale)), min(ch, round(height * scale))
    x, y = (cw - w) // 2, (ch - h) // 2
    return {"canvas": [cw, ch], "scale": scale, "content": [x, y, w, h], "flexible": flexible}


def pad(image, plan):
    """Scaled render centred on the canvas; padding mirrors the edges (no hard frame)."""
    x, y, w, h = plan["content"]
    cw, ch = plan["canvas"]
    rgb = image.convert("RGB")
    if rgb.size != (w, h):
        rgb = rgb.resize((w, h), Image.LANCZOS)
    a = np.asarray(rgb)
    out = np.pad(a, ((y, ch - h - y), (x, cw - w - x), (0, 0)), mode="symmetric")
    return Image.fromarray(out)


def crop(image, plan, size):
    """Inverse of pad: content box back at the render's size. Returns (image, resampled?)."""
    cw, ch = plan["canvas"]
    x, y, w, h = plan["content"]
    resampled = False
    rgb = image.convert("RGB")
    if rgb.size != (cw, ch):
        rgb = rgb.resize((cw, ch), Image.LANCZOS)
        resampled = True
    rgb = rgb.crop((x, y, x + w, y + h))
    if rgb.size != tuple(size):
        rgb = rgb.resize(tuple(size), Image.LANCZOS)
        resampled = True
    return rgb, resampled


# --- Structural comparison ---------------------------------------------------------------------


def _grey(image, width=WIDTH):
    g = np.asarray(image.convert("L"), dtype=np.uint8)
    h = round(g.shape[0] * width / g.shape[1])
    g = cv2.resize(g, (width, h), interpolation=cv2.INTER_AREA)
    g = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(g)
    return cv2.GaussianBlur(g, (0, 0), 1.2)


def _edges(grey, low, high):
    return cv2.Canny(grey, low, high, L2gradient=True) > 0


def _thresholds(grey):
    """Canny thresholds from the original's gradient distribution (reused for the enhanced)."""
    high = max(60.0, float(np.percentile(_gradient(grey), 92)))
    return 0.4 * high, high


def _near(edges):
    """Distance (px) from every pixel to the nearest edge pixel."""
    return cv2.distanceTransform((~edges).astype(np.uint8), cv2.DIST_L2, 3)


def structure_term(a, b, sigma=3.0):
    """Mean SSIM structure term s = (σab + C) / (σa σb + C), weighted by local texture of a."""
    a, b = a.astype(np.float64), b.astype(np.float64)

    def blur(x):
        return cv2.GaussianBlur(x, (0, 0), sigma)

    ma, mb = blur(a), blur(b)
    va = np.maximum(blur(a * a) - ma * ma, 0)
    vb = np.maximum(blur(b * b) - mb * mb, 0)
    cov = blur(a * b) - ma * mb
    c = (0.03 * 255) ** 2 / 2
    s = (cov + c) / (np.sqrt(va * vb) + c)
    weight = np.sqrt(va)
    weight[weight < 2.0] = 0  # flat areas carry no structure
    if weight.sum() == 0:
        return 1.0
    return float(np.clip((s * weight).sum() / weight.sum(), 0, 1))


def _gradient(grey):
    gx = cv2.Sobel(grey.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(grey.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)
    return cv2.magnitude(gx, gy)


def shifts(a, b, edges=None, grid=3):
    """(global shift %, worst tile shift %) between two greyscale images, by phase correlation.

    Only tiles where the original has real structure (edges) are measured: flat walls with
    added texture give meaningless correlation peaks.
    """
    ga, gb = _gradient(a), _gradient(b)
    width = a.shape[1]

    def shift(x, y):
        if x.std() < 1 or y.std() < 1:
            return None
        window = cv2.createHanningWindow(x.shape[::-1], cv2.CV_32F)
        (dx, dy), response = cv2.phaseCorrelate(x, y, window)
        return None if response < 0.08 else float(np.hypot(dx, dy))

    overall = shift(ga, gb) or 0.0
    worst = 0.0
    h, w = a.shape
    for i in range(grid):
        for j in range(grid):
            ys = slice(i * h // grid, (i + 1) * h // grid)
            xs = slice(j * w // grid, (j + 1) * w // grid)
            if edges is not None and edges[ys, xs].mean() < 0.01:
                continue
            value = shift(ga[ys, xs], gb[ys, xs])
            if value is not None:
                worst = max(worst, value)
    return 100 * overall / width, 100 * worst / width


def line_support(edges_a, near_b, width):
    lines = cv2.HoughLinesP(
        edges_a.astype(np.uint8) * 255,
        1,
        np.pi / 180,
        threshold=60,
        minLineLength=int(width * 0.08),
        maxLineGap=4,
    )
    if lines is None:
        return 1.0, 0
    supported = 0
    lines = lines[:, 0, :][:200]
    for x0, y0, x1, y1 in lines:
        n = max(2, int(np.hypot(x1 - x0, y1 - y0)))
        xs = np.clip(np.linspace(x0, x1, n).round().astype(int), 0, near_b.shape[1] - 1)
        ys = np.clip(np.linspace(y0, y1, n).round().astype(int), 0, near_b.shape[0] - 1)
        if (near_b[ys, xs] <= TOLERANCE).mean() >= 0.6:
            supported += 1
    return supported / len(lines), len(lines)


def mask_boundaries(mask, shape):
    """Silhouette pixels of furniture (blue) and openings (green) in the Blender class mask."""
    m = np.asarray(mask.convert("RGB"))
    m = cv2.resize(m, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
    out = np.zeros(shape, bool)
    for channel in (1, 2):
        region = (m[:, :, channel] > 127).astype(np.uint8)
        if region.any():
            out |= cv2.morphologyEx(region, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) > 0
    return out


def compare(original, enhanced, mask=None, threshold=THRESHOLD, max_shift=MAX_SHIFT):
    """Fidelity report of `enhanced` against `original` (PIL images, any size)."""
    a = _grey(original)
    b = _grey(
        enhanced.resize(original.size, Image.LANCZOS)
        if enhanced.size != original.size
        else enhanced
    )
    low, high = _thresholds(a)
    ea, eb = _edges(a, low, high), _edges(b, low, high)
    near_a, near_b = _near(ea), _near(eb)
    recall = float((near_b[ea] <= TOLERANCE).mean()) if ea.any() else 1.0
    lines, count = line_support(ea, near_b, a.shape[1])
    parts = {
        "edge_recall": recall,
        "structure": structure_term(a, b),
        "line_support": lines,
    }
    if mask is not None:
        border = mask_boundaries(mask, a.shape)
        if border.sum() > 50:
            ref = float((near_a[border] <= TOLERANCE).mean())
            got = float((near_b[border] <= TOLERANCE).mean())
            parts["mask_recall"] = min(1.0, got / ref) if ref > 0.05 else 1.0
    weights = {k: WEIGHTS[k] for k in parts}
    score = sum(parts[k] * w for k, w in weights.items()) / sum(weights.values())
    shift_global, shift_tile = shifts(a, b, ea)
    passed = score >= threshold and shift_tile <= max_shift
    reasons = []
    if score < threshold:
        reasons.append(f"puntuación {score:.2f} < {threshold:.2f}")
    if shift_tile > max_shift:
        reasons.append(f"desplazamiento local {shift_tile:.1f} % > {max_shift:.1f} %")
    return {
        "score": round(score, 3),
        "passed": bool(passed),
        "components": {k: round(v, 3) for k, v in parts.items()},
        "shift_percent": round(shift_global, 2),
        "tile_shift_percent": round(shift_tile, 2),
        "lines": count,
        "threshold": threshold,
        "max_shift_percent": max_shift,
        "mask": mask is not None,
        "reasons": reasons,
    }
