"""
Node 04 — POST.

Pushes approved posts into the Buffer queue. Buffer's free tier gives 3
channels, 10 queued posts per channel refilled as they publish, and API
access with 1 key. That covers one post a day across IG, TikTok and Shorts
at zero cost.

Only posts with status == "approved" are sent. Flip the status in
data/queue.json (or the GitHub web editor on your phone) to approve.
That is the 15-minutes-a-week human gate. Do not remove it.

NOTE: verify the endpoint against Buffer's current API docs before first run.
Buffer has kept the /1/updates/create.json shape for a long time but confirm
rather than trust this file.
"""

import json
import os
import pathlib
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

TOKEN = os.environ["BUFFER_ACCESS_TOKEN"]
PROFILE_IDS = [p for p in os.environ.get("BUFFER_PROFILE_IDS", "").split(",") if p]

CREATE = "https://api.bufferapp.com/1/updates/create.json"


def push(text, media_paths=None):
    fields = [("text", text), ("access_token", TOKEN)]
    for pid in PROFILE_IDS:
        fields.append(("profile_ids[]", pid))

    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(CREATE, data=data)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def build_caption(pkg):
    return "\n\n".join(
        [
            pkg["caption"],
            pkg["source_line"],
            f"DAILY {pkg['daily_no']} · {pkg.get('coordinates', '')}",
            " ".join(pkg.get("hashtags", [])),
        ]
    ).strip()


def main():
    queue = json.loads((DATA / "queue.json").read_text())
    sent = 0

    for pkg in queue:
        if pkg.get("status") != "approved":
            continue
        try:
            res = push(build_caption(pkg), pkg.get("rendered"))
            pkg["status"] = "scheduled"
            pkg["buffer_ids"] = [u.get("id") for u in res.get("updates", [])]
            sent += 1
            print(f"[publish] DAILY {pkg['daily_no']} queued to Buffer")
        except Exception as e:
            pkg["status"] = "publish_failed"
            pkg["error"] = str(e)
            print(f"[publish] FAILED DAILY {pkg['daily_no']}: {e}")

    (DATA / "queue.json").write_text(json.dumps(queue, indent=2))
    print(f"[publish] {sent} sent")


if __name__ == "__main__":
    main()
