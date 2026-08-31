"""
Node 05 — SCORE.

The node the reel's machine doesn't have, and the reason this is a testing
instrument instead of a posting robot.

Pulls performance back from Buffer, scores each case, and writes the ranked
long-form shortlist. Runs twice per post: at 72 hours and again at day 14,
because short-form has a long tail and day 14 frequently reorders the board.

Weighting is deliberate. Likes are the weakest signal available: a like means
"approve", a profile visit means "want more". Profile visits are what predict
whether a case can carry fifteen minutes.
"""

import json
import os
import pathlib
import datetime
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

TOKEN = os.environ["BUFFER_ACCESS_TOKEN"]

WEIGHTS = {
    "profile_visits_per_1k": 4,
    "saves_per_1k": 3,
    "shares_per_1k": 3,
    "question_comments": 5,
    "hold_rate": 2,
    "likes_per_1k": 0.5,
}


def buffer_stats(update_id):
    url = f"https://api.bufferapp.com/1/updates/{update_id}/interactions.json?access_token={TOKEN}"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"[score] stats unavailable for {update_id}: {e}")
        return {}


def score(metrics):
    return round(sum(metrics.get(k, 0) * w for k, w in WEIGHTS.items()), 2)


def age_days(iso):
    t = datetime.datetime.fromisoformat(iso.replace("Z", ""))
    return (datetime.datetime.utcnow() - t).days


def main():
    queue = json.loads((DATA / "queue.json").read_text())
    scores = json.loads((DATA / "scores.json").read_text())

    for pkg in queue:
        if pkg.get("status") != "scheduled":
            continue
        age = age_days(pkg["generated_at"])
        window = 3 if age >= 3 else None
        window = 14 if age >= 14 else window
        if window is None:
            continue
        if pkg.get("scored_at_day") == window:
            continue

        metrics = {}
        for uid in pkg.get("buffer_ids", []):
            raw = buffer_stats(uid)
            for k, v in raw.items():
                if isinstance(v, (int, float)):
                    metrics[k] = metrics.get(k, 0) + v

        s = score(metrics)
        pkg["scored_at_day"] = window
        scores.append(
            {
                "daily_no": pkg["daily_no"],
                "case_name": pkg["case_name"],
                "tier": pkg["tier"],
                "window_days": window,
                "metrics": metrics,
                "case_score": s,
                "the_unresolved_thing": pkg.get("the_unresolved_thing"),
            }
        )
        print(f"[score] DAILY {pkg['daily_no']} day{window} = {s}")

    (DATA / "queue.json").write_text(json.dumps(queue, indent=2))
    (DATA / "scores.json").write_text(json.dumps(scores, indent=2))

    # long-form shortlist: tier A only, rolling 30 days, best window per case
    best = {}
    for row in scores:
        if row["tier"] != "A":
            continue
        k = row["daily_no"]
        if k not in best or row["case_score"] > best[k]["case_score"]:
            best[k] = row

    ranked = sorted(best.values(), key=lambda r: -r["case_score"])[:10]
    (DATA / "shortlist.json").write_text(json.dumps(ranked, indent=2))

    print("\n=== LONG-FORM SHORTLIST ===")
    for i, r in enumerate(ranked, 1):
        print(f"{i}. {r['case_name']}  score {r['case_score']}")
        print(f"   unresolved: {r['the_unresolved_thing']}")


if __name__ == "__main__":
    main()
