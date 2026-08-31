"""
Node 04 - POST.  Per-channel routing.

Buffer free tier, org 6a952155eb370bd724a858b3:
  Instagram  6a952a60065799be465c13d0   business
  TikTok     6a952c83065799be465c1afb
  X          6a953137065799be465c288a

Approval: by default only status == "approved" is sent. Set LKP_AUTO_APPROVE=1
to publish pending_approval packages unattended - the grounded() guard still
blocks anything the research pass failed to anchor to a primary document.

Per-channel behaviour, because these platforms are not the same:

  IG / TikTok - full caption, hashtags in the caption block, slides attached
                as a carousel via raw GitHub URLs.
  X           - a native thread, every item numbered Part N/N. No hashtags.
                No link in the body (an outbound link costs roughly 30-40% of
                reach); the link is the final thread item instead.
"""

import json
import os
import pathlib
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

TOKEN = os.environ["BUFFER_ACCESS_TOKEN"]

CHANNELS = {
    "instagram": os.environ.get("BUFFER_IG_ID", "6a952a60065799be465c13d0"),
    "tiktok": os.environ.get("BUFFER_TIKTOK_ID", "6a952c83065799be465c1afb"),
    "x": os.environ.get("BUFFER_X_ID", "6a953137065799be465c288a"),
}

CREATE = "https://api.bufferapp.com/1/updates/create.json"

# Slides are committed to the repo. Buffer needs a fetchable URL for media,
# and raw.githubusercontent.com only serves these without auth on a PUBLIC repo.
GH_REPO = os.environ.get("GH_REPO", "kirazberen/lkp-engine")
GH_BRANCH = os.environ.get("GH_BRANCH", "main")
RAW = f"https://raw.githubusercontent.com/{GH_REPO}/{GH_BRANCH}/"

YT = "https://www.youtube.com/@LastKnownPositionTV"
X_LIMIT = 280
PART_TAG = 12          # room for "Part 10/10\n\n"

# Set LKP_AUTO_APPROVE=1 to publish without flipping status by hand.
# The grounded() guard below still blocks anything the research pass failed
# to anchor to a primary document.
AUTO_APPROVE = os.environ.get("LKP_AUTO_APPROVE") == "1"


def grounded(pkg):
    """
    Minimum evidence bar for unattended publishing. Not a taste check - it only
    asks whether the research actually anchored itself to a document.
    """
    missing = []
    if not (pkg.get("docket_url") or "").startswith("http"):
        missing.append("docket_url")
    if not (pkg.get("source_line") or "").strip():
        missing.append("source_line")
    if not (pkg.get("caption") or "").strip():
        missing.append("caption")
    if not any(
        isinstance(a, dict) and a.get("rights") == "PD"
        for a in (pkg.get("assets") or [])
    ):
        missing.append("no PD asset")
    return missing


def publishable(pkg):
    status = pkg.get("status")
    if status == "approved":
        return True
    if AUTO_APPROVE and status == "pending_approval":
        missing = grounded(pkg)
        if missing:
            print(f"[publish] HELD DAILY {pkg.get('daily_no')} - ungrounded: {', '.join(missing)}")
            return False
        return True
    return False


def media_urls(pkg):
    """Repo-relative slide paths -> raw URLs Buffer can fetch."""
    out = []
    for rel in pkg.get("rendered") or []:
        rel = str(rel).lstrip("/")
        if rel.startswith("home/runner"):  # legacy absolute path, skip
            continue
        out.append(RAW + rel)
    return out


def push(text, profile_ids, media=None, thread=None):
    fields = [("text", text), ("access_token", TOKEN)]
    for pid in profile_ids:
        fields.append(("profile_ids[]", pid))
    for url in media or []:
        fields.append(("media[photo]", url))
    if thread:
        fields.append(("metadata", json.dumps({"twitter": {"thread": thread}})))
    req = urllib.request.Request(CREATE, data=urllib.parse.urlencode(fields).encode())
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def caption_ig_tiktok(pkg):
    """First line is the hook verbatim. IG and TikTok truncate after one line."""
    parts = [
        pkg.get("caption", ""),
        pkg.get("source_line", ""),
        f"DAILY {pkg['daily_no']} - {pkg.get('coordinates', '')}",
        " ".join(pkg.get("hashtags", [])),
    ]
    return "\n\n".join(p for p in parts if p).strip()


def x_thread(pkg):
    """
    Build the thread. Prefers the model's native x_post; falls back to slide
    copy. The link is always the final item, never the body.
    """
    items = []
    body = (pkg.get("x_post") or "").strip()
    if body:
        items.append(body)
    else:
        for s in pkg.get("slides", []):
            t = (s.get("text") or "").strip()
            if t:
                items.append(t)
        if pkg.get("source_line"):
            items.append(pkg["source_line"])

    items = [i[: X_LIMIT - PART_TAG - 1] for i in items if i][:5]
    if not items:
        return None, None
    items.append(pkg.get("x_reply") or f"Full case file: {YT}")

    # Number every item. Without this the reader cannot tell which tweet comes
    # first or that a thread exists at all.
    total = len(items)
    items = [f"Part {i}/{total}\n\n{t}" for i, t in enumerate(items, 1)]
    return items[0], [{"text": t} for t in items]


def main():
    queue = json.loads((DATA / "queue.json").read_text())
    sent = 0

    for pkg in queue:
        if not publishable(pkg):
            continue

        pkg.setdefault("buffer_ids", [])
        media = media_urls(pkg)

        try:
            if media:
                res = push(caption_ig_tiktok(pkg),
                           [CHANNELS["instagram"], CHANNELS["tiktok"]],
                           media=media)
                pkg["buffer_ids"] += [u.get("id") for u in res.get("updates", [])]
                print(f"[publish] DAILY {pkg['daily_no']} -> IG + TikTok ({len(media)} slides)")
            else:
                print(f"[publish] DAILY {pkg['daily_no']} -> no slides, skipping IG/TikTok")

            head, thread = x_thread(pkg)
            if thread:
                time.sleep(1)
                res_x = push(head, [CHANNELS["x"]], thread=thread)
                pkg["buffer_ids"] += [u.get("id") for u in res_x.get("updates", [])]
                print(f"[publish] DAILY {pkg['daily_no']} -> X ({len(thread)} items)")

            pkg["status"] = "scheduled"
            sent += 1

        except Exception as e:
            pkg["status"] = "publish_failed"
            pkg["error"] = str(e)
            print(f"[publish] FAILED DAILY {pkg['daily_no']}: {e}")

    (DATA / "queue.json").write_text(json.dumps(queue, indent=2))
    print(f"[publish] {sent} sent")


if __name__ == "__main__":
    main()
