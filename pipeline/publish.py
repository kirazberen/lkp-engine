"""
Node 04 - POST.  Per-channel routing.

Buffer free tier, org 6a952155eb370bd724a858b3:
  Instagram  6a952a60065799be465c13d0   business
  TikTok     6a952c83065799be465c1afb
  X          6a953137065799be465c288a

Approval: by default only status == "approved" is sent. Set LKP_AUTO_APPROVE=1
to publish pending_approval packages unattended - the grounded() guard still
blocks anything the research pass failed to anchor to a primary document.

This node is self-sufficient: if a publishable package has no slides yet it
renders them, commits and pushes them, waits for raw.githubusercontent to
actually serve them, then posts. It does not depend on the workflow's render
step having run first.

Outcome is written back into data/queue.json - status becomes "scheduled" or
"publish_failed" with the error text - so the result of every run is readable
from the repo without needing the Actions log.

Set "skip_channels": ["x"] on a package to suppress a channel it already has.
"""

import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import render as R

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

TOKEN = os.environ["BUFFER_ACCESS_TOKEN"]

CHANNELS = {
    "instagram": os.environ.get("BUFFER_IG_ID", "6a952a60065799be465c13d0"),
    "tiktok": os.environ.get("BUFFER_TIKTOK_ID", "6a952c83065799be465c1afb"),
    "x": os.environ.get("BUFFER_X_ID", "6a953137065799be465c288a"),
}

CREATE = "https://api.bufferapp.com/1/updates/create.json"

GH_REPO = os.environ.get("GH_REPO", "kirazberen/lkp-engine")
GH_BRANCH = os.environ.get("GH_BRANCH", "main")
RAW = f"https://raw.githubusercontent.com/{GH_REPO}/{GH_BRANCH}/"

YT = "https://www.youtube.com/@LastKnownPositionTV"
X_LIMIT = 280
PART_TAG = 12

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
    """Repo-relative slide paths -> raw URLs Buffer can fetch.

    Older packages stored runner-absolute paths. Recover the repo-relative tail
    rather than dropping them, or those posts silently lose their carousel.
    """
    out = []
    for rel in pkg.get("rendered") or []:
        rel = str(rel).replace("\\", "/")
        if "/out/" in rel:
            rel = "out/" + rel.split("/out/", 1)[1]
        rel = rel.lstrip("/")
        if not rel.startswith("out/"):
            print(f"[publish] unusable slide path, skipping: {rel}")
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
    """Prefers the model's native x_post; falls back to slide copy."""
    items = []
    body = (pkg.get("x_post") or "").strip()
    if body:
        items.append(body)
    else:
        for s in pkg.get("slides", []):
            t = (s.get("headline") or s.get("text") or "").strip()
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


def ensure_rendered(queue):
    """
    Render any publishable package that has no slides yet, then commit and push
    so raw.githubusercontent serves them BEFORE Buffer is asked to fetch them.
    Buffer validates media at create time, so the commit cannot wait for the
    workflow's own commit step at the end of the job.
    """
    made = False
    for pkg in queue:
        if publishable(pkg) and not (pkg.get("rendered") or []):
            print(f"[publish] rendering DAILY {pkg.get('daily_no')} on demand")
            pkg["rendered"] = R.render(pkg)
            made = made or bool(pkg["rendered"])

    if not made:
        return

    (DATA / "queue.json").write_text(json.dumps(queue, indent=2))
    try:
        subprocess.run(["git", "config", "user.name", "lkp-engine"], check=True)
        subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)
        subprocess.run(["git", "add", "out", "data"], check=True)
        subprocess.run(["git", "commit", "-m", "lkp: slides for publish"], check=True)
        subprocess.run(["git", "push"], check=True)
        print("[publish] slides committed and pushed")
    except subprocess.CalledProcessError as e:
        print(f"[publish] commit/push failed ({e}); Buffer cannot fetch media")
        return

    # Do not guess at CDN propagation. Poll until raw actually serves the new
    # blobs, because Buffer validates media at create time and a 404 there
    # marks the whole package publish_failed.
    probe = next((u for pkg in queue for u in media_urls(pkg)), None)
    if probe:
        wait_for_raw(probe)


def wait_for_raw(url, timeout=300, interval=10):
    """Block until raw.githubusercontent serves url, or timeout."""
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            req = urllib.request.Request(url, method="HEAD",
                                         headers={"User-Agent": "lkp-engine/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status == 200:
                    print(f"[publish] raw serving slides after {attempt} probe(s)")
                    time.sleep(5)   # cushion for the remaining blobs
                    return True
        except Exception:
            pass
        print(f"[publish] waiting on raw propagation, probe {attempt}")
        time.sleep(interval)
    print("[publish] raw never served the slide within timeout; posting anyway")
    return False


def main():
    queue = json.loads((DATA / "queue.json").read_text())
    ensure_rendered(queue)
    sent = 0

    for pkg in queue:
        if not publishable(pkg):
            continue

        pkg.setdefault("buffer_ids", [])
        media = media_urls(pkg)
        skip = set(pkg.get("skip_channels") or [])

        try:
            if media and not {"instagram", "tiktok"} <= skip:
                res = push(caption_ig_tiktok(pkg),
                           [CHANNELS["instagram"], CHANNELS["tiktok"]],
                           media=media)
                pkg["buffer_ids"] += [u.get("id") for u in res.get("updates", [])]
                print(f"[publish] DAILY {pkg['daily_no']} -> IG + TikTok ({len(media)} slides)")
            else:
                print(f"[publish] DAILY {pkg['daily_no']} -> no slides, skipping IG/TikTok")

            head, thread = x_thread(pkg)
            if thread and "x" not in skip:
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
