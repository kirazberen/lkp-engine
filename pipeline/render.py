"""
Node 03 - DESIGN.

Renders carousel slides locally with Pillow. No image generation, no API cost.

Layout is measured, never assumed. Every text block is fitted to a declared
box by binary-searching the point size and re-wrapping on real glyph widths,
so copy can never overrun its zone or collide with the footer. The previous
version wrapped at a fixed character count at a fixed size and overlapped.

Zones (1080x1350, 4:5):
    y 100-154   case tab + watermark
    y 210-1090  content box, auto-fitted and vertically centred
    y 1150      hairline accent rule
    y 1175-1245 source line (optional, max 3 lines)
    y 1285      coordinate strip (left) + slide counter (right)
"""

import json
import pathlib
import re
import urllib.request

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "out"
FONTS = ROOT / "assets" / "fonts"

VOID = (7, 10, 14)
TEAL = (43, 232, 216)
AMBER = (255, 182, 39)
DANGER = (255, 59, 59)
FOG = (234, 240, 244)
MUTED = (120, 132, 143)

W, H = 1080, 1350
M = 80                      # safe margin
BOX_TOP, BOX_BOTTOM = 210, 1090
RULE_Y = 1150
SOURCE_Y = 1175
BASE_Y = 1285

# one accent per slide, chosen by slide kind
ACCENT = {
    "anomaly": AMBER,
    "correction": TEAL,
    "barrier": TEAL,
    "document": AMBER,
    "signal": AMBER,
    "rationalization": TEAL,
    "clock": DANGER,
    "names": FOG,
    "contradiction": AMBER,
    "outro": TEAL,
}


def font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


def wrap(draw, text, f, max_w):
    """Greedy wrap on measured glyph widths. Explicit newlines are preserved."""
    out = []
    for para in str(text).split("\n"):
        if not para.strip():
            out.append("")
            continue
        line = ""
        for word in para.split():
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=f) <= max_w or not line:
                line = trial
            else:
                out.append(line)
                line = word
        if line:
            out.append(line)
    return out


def fit(draw, text, font_name, box_w, box_h, hi, lo, leading=1.18):
    """Binary-search the largest point size whose wrapped block fits box_h."""
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        f = font(font_name, mid)
        lines = wrap(draw, text, f, box_w)
        line_h = int(mid * leading)
        if len(lines) * line_h <= box_h:
            best = (f, lines, line_h)
            lo = mid + 1
        else:
            hi = mid - 1
    if best is None:                       # pathological string, clamp
        f = font(font_name, lo if lo > 0 else 12)
        best = (f, wrap(draw, text, f, box_w), int((lo or 12) * leading))
    return best


def fetch(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "lkp-engine/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return Image.open(r).convert("RGB")
    except Exception as e:
        print(f"[render] asset fetch failed ({e}), using flat void")
        return None


def backdrop(url=None):
    img = Image.new("RGB", (W, H), VOID)
    if not url:
        return img
    src = fetch(url)
    if src is None:
        return img
    ratio = max(W / src.width, H / src.height)
    src = src.resize((int(src.width * ratio), int(src.height * ratio)))
    src = src.crop((0, 0, W, H))
    return Image.blend(src, Image.new("RGB", (W, H), VOID), 0.66)


def watermark(d):
    """Reticle mark + wordmark, top right. Drawn, not an asset file."""
    cx, cy, r = W - M - 22, 127, 22
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=TEAL, width=3)
    d.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=TEAL)
    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        d.line([cx + dx * (r - 2), cy + dy * (r - 2),
                cx + dx * (r + 11), cy + dy * (r + 11)], fill=TEAL, width=3)
    f = font("SpaceMono-Bold.ttf", 17)
    t = "LAST KNOWN POSITION"
    d.text((cx - r - 18 - d.textlength(t, font=f), cy - 9), t, font=f, fill=MUTED)


def draw_slide(s, idx, total, pkg, asset_url=None):
    kind = s.get("kind", "anomaly")
    accent = ACCENT.get(kind, AMBER)
    headline = str(s.get("headline") or "").strip()
    body = str(s.get("text") or "").strip()

    img = backdrop(asset_url)
    d = ImageDraw.Draw(img)

    # case tab, slide 1 only; section label thereafter
    if idx == 1:
        tab = f"DAILY {pkg.get('daily_no', '000')}"
        tf = font("SpaceMono-Bold.ttf", 30)
        tw = d.textlength(tab, font=tf)
        d.rectangle([M, 100, M + tw + 44, 154], fill=DANGER)
        d.text((M + 22, 111), tab, font=tf, fill=FOG)
    elif kind != "names":
        lf = font("SpaceMono-Bold.ttf", 22)
        d.text((M, 118), str(s.get("label", "")).upper()[:34], font=lf, fill=accent)

    watermark(d)

    box_w = W - 2 * M
    box_h = BOX_BOTTOM - BOX_TOP

    # measure both blocks first, then centre the whole thing vertically so
    # short copy does not leave a dead half-canvas above the rule.
    # headline ceiling is deliberately huge: a three-character number is the
    # hook and must dominate the frame.
    blocks, total_h = [], 0
    if headline:
        cap = int(box_h * (0.95 if not body else 0.60))
        hf, hlines, hlh = fit(d, headline.upper(), "Anton-Regular.ttf", box_w, cap, 260, 34, 1.10)
        blocks.append((hf, hlines, hlh, FOG))
        total_h += len(hlines) * hlh + (34 if body else 0)
    if body:
        avail = box_h - total_h
        bf_, blines, blh = fit(d, body, "Inter-Regular.ttf", box_w, avail, 46, 20, 1.42)
        blocks.append((bf_, blines, blh, MUTED if headline else FOG))
        total_h += len(blines) * blh

    y = BOX_TOP + max(0, (box_h - total_h) // 2)
    for i, (f, lines, lh, col) in enumerate(blocks):
        for ln in lines:
            d.text((M, y), ln, font=f, fill=col)
            y += lh
        if i == 0 and len(blocks) > 1:
            y += 34

    d.line([M, RULE_Y, W - M, RULE_Y], fill=accent, width=2)

    # source line, fitted so it can never reach the baseline row
    src = s.get("source") or (pkg.get("source_line") if idx == total else None)
    if src:
        f, lines, lh = fit(d, f"Source: {src}", "SpaceMono-Regular.ttf",
                           box_w, BASE_Y - 30 - SOURCE_Y, 22, 13, 1.34)
        sy = SOURCE_Y
        for ln in lines[:3]:
            d.text((M, sy), ln, font=f, fill=AMBER)
            sy += lh

    bf = font("SpaceMono-Regular.ttf", 26)
    if idx in (1, total) and pkg.get("coordinates"):
        d.text((M, BASE_Y), str(pkg["coordinates"]), font=bf, fill=TEAL)
    counter = f"{idx:02d} / {total:02d}"
    d.text((W - M - d.textlength(counter, font=bf), BASE_Y), counter, font=bf, fill=MUTED)

    return img


def render(package):
    slides = [s for s in (package.get("slides") or []) if isinstance(s, dict)]
    if not slides:
        print(f"[render] no slides (tier {package.get('tier')}) - skipping")
        return []

    daily_no = package.get("daily_no") or "000"
    slug = re.sub(r"[^a-z0-9]+", "-", str(package.get("case_name") or "untitled").lower()).strip("-")[:40] or "untitled"
    outdir = OUT / f"{daily_no}-{slug}"
    outdir.mkdir(parents=True, exist_ok=True)

    primary = next(
        (a["source_url"] for a in (package.get("assets") or [])
         if isinstance(a, dict) and a.get("primary") and a.get("rights") == "PD" and a.get("source_url")),
        None,
    )

    paths, total = [], len(slides)
    for i, s in enumerate(slides, 1):
        img = draw_slide(s, i, total, package, asset_url=primary if i == 1 else None)
        p = outdir / f"slide_{i:02d}.jpg"
        img.save(p, quality=93)
        paths.append(str(p.relative_to(ROOT)))
        print(f"[render] {p.relative_to(ROOT)}")
    return paths


def main():
    queue = json.loads((DATA / "queue.json").read_text())
    for pkg in queue:
        if pkg.get("status") == "pending_approval" and pkg.get("rendered") is None:
            pkg["rendered"] = render(pkg)
    (DATA / "queue.json").write_text(json.dumps(queue, indent=2))


if __name__ == "__main__":
    main()
