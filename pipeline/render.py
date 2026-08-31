"""
Node 03 — DESIGN.

Renders carousel slides locally with Pillow. No image generation, no API cost.

The brand is documents, coordinates and gauge readings on near-black. That is
a typography job, not an image-generation job. Real evidence gets composited
in from the PD asset URLs the research node found; everything else is type.
"""

import json
import pathlib
import re
import textwrap
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

W, H = 1080, 1350  # 4:5, the largest IG carousel canvas


def font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


def fetch(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "lkp-engine/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return Image.open(r).convert("RGB")
    except Exception as e:
        print(f"[render] asset fetch failed ({e}), using flat void")
        return None


def backdrop(url=None):
    """Evidence photo, heavily crushed, or flat void. Never a generated image."""
    img = Image.new("RGB", (W, H), VOID)
    if not url:
        return img
    src = fetch(url)
    if src is None:
        return img
    ratio = max(W / src.width, H / src.height)
    src = src.resize((int(src.width * ratio), int(src.height * ratio)))
    src = src.crop((0, 0, W, H))
    # crush to near-black so type stays readable
    return Image.blend(src, Image.new("RGB", (W, H), VOID), 0.62)


def draw_slide(n, text, headline=False, asset_url=None, source=None, coords=None, daily_no=None):
    img = backdrop(asset_url)
    d = ImageDraw.Draw(img)

    if headline:
        f = font("Anton-Regular.ttf", 96)
        wrapped = textwrap.fill(text.upper(), 16)
        d.multiline_text((70, 300), wrapped, font=f, fill=FOG, spacing=14)
        # red case tab
        d.rectangle([70, 200, 70 + 260, 200 + 54], fill=DANGER)
        d.text((92, 212), f"DAILY {daily_no}", font=font("SpaceMono-Bold.ttf", 30), fill=FOG)
    else:
        f = font("Inter-Regular.ttf", 46)
        wrapped = textwrap.fill(text, 34)
        d.multiline_text((70, 380), wrapped, font=f, fill=FOG, spacing=18)

    # coordinate strip, channel signature, every slide
    if coords:
        d.text((70, H - 90), coords, font=font("SpaceMono-Regular.ttf", 28), fill=TEAL)

    if source:
        s = textwrap.fill(f"Source: {source}", 60)
        d.multiline_text((70, H - 200), s, font=font("SpaceMono-Regular.ttf", 24), fill=AMBER, spacing=8)

    return img


def render(package):
    """Render a package's slides.

    Everything in `package` came from a model, so nothing here may assume a
    key exists or holds the documented type. A tier B package is a reel
    (vo_script + shot_list) and legitimately has no slides at all.
    """
    slides = [s for s in (package.get("slides") or []) if isinstance(s, dict)]
    if not slides:
        print(f"[render] no slides in package (tier {package.get('tier')}) - skipping")
        return []

    case_name = str(package.get("case_name") or "untitled")
    daily_no = package.get("daily_no") or "000"
    # model-authored text: strip anything that is not filesystem-safe, or a
    # case_name containing "/" or ":" breaks mkdir
    slug = re.sub(r"[^a-z0-9]+", "-", case_name.lower()).strip("-")[:40] or "untitled"
    outdir = OUT / f"{daily_no}-{slug}"
    outdir.mkdir(parents=True, exist_ok=True)

    primary = next(
        (
            a["source_url"]
            for a in (package.get("assets") or [])
            if isinstance(a, dict)
            and a.get("primary")
            and a.get("rights") == "PD"
            and a.get("source_url")
        ),
        None,
    )

    paths = []
    total = len(slides)
    for i, s in enumerate(slides, 1):
        # trust position over a model-supplied "n", which may be missing,
        # non-integer, or not sequential
        n = s["n"] if isinstance(s.get("n"), int) else i
        last = i == total
        img = draw_slide(
            n,
            str(s.get("text") or ""),
            headline=(n == 1),
            asset_url=primary if n == 1 else None,
            source=package.get("source_line") if last else None,
            coords=package.get("coordinates"),
            daily_no=daily_no,
        )
        p = outdir / f"slide_{n}.jpg"
        img.save(p, quality=92)
        # store repo-relative, not runner-absolute: publish.py turns these
        # into raw.githubusercontent.com URLs for Buffer
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
