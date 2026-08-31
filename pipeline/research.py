"""
Node 01 + 02 - MINE and WRITE, in one API call.

Researches a case from primary government sources and returns a verified
post package as JSON. Uses the server-side web_search tool so the model
does its own sourcing.

Cost control: Haiku 4.5 does the research sweep, Sonnet does the copy.
Set LKP_MODEL_RESEARCH / LKP_MODEL_WRITE to override.
"""

import json
import os
import sys
import pathlib
import datetime
from datetime import timezone
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"
API_KEY = os.environ["ANTHROPIC_API_KEY"]

MODEL_RESEARCH = os.environ.get("LKP_MODEL_RESEARCH", "claude-haiku-4-5-20251001")
MODEL_WRITE = os.environ.get("LKP_MODEL_WRITE", "claude-sonnet-5")

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

SOURCE_STACK = """
NTSB CAROL: data.ntsb.gov/carol-main-public/basic-search  (aviation, rail, highway, marine, pipeline)
NTSB Dockets: data.ntsb.gov/Docket  (photos, CVR/FDR transcripts, group chairman reports)
CSB: csb.gov/investigations/ and csb.gov/videos/  (chemical/industrial + animated reconstructions)
MSHA: msha.gov/data-reports/fatality-reports  (mining)
NIST: nist.gov/topics/disaster-failure-studies  (structural collapse, fire)
BSEE: bsee.gov  (offshore)
USCG: dco.uscg.mil  (marine casualty)
DVIDS: dvidshub.net  (military/USCG response imagery, high-res, PD)
NASA Earth Observatory / NOAA  (satellite, spill, marine B-roll, PD)
CourtListener: courtlistener.com  (findings of fact, trial exhibits, internal emails)
GovInfo: govinfo.gov | NARA: catalog.archives.gov

US federal works are public domain under 17 USC 105.
Foreign agencies (MAIB, AAIB, TSB Canada, BEA, ATSB, JTSB, public inquiries):
FACTS ONLY. Cite and quote. Never lift their graphics.

DO NOT USE: C-SPAN (BY-NC-ND), agency Flickr (often CC BY-ND, get the same
file from DVIDS), DVIDS items with a "Courtesy Photo" byline, any photograph
of a victim, feature films about the event, Getty/AP/Reuters.
"""

SYSTEM = f"""You are the research engine for Last Known Position, a disaster
investigation channel. You work only from primary government sources.

SOURCE STACK
{SOURCE_STACK}

STRUCTURAL TEST - run first.
Name, in one sentence, the specific thing the investigation could not settle.
"Nobody knows what happened" = FAIL, mystery-channel material.
"Two agencies published opposite conclusions and both still stand" = PASS.
A FAIL can still be a Tier B or C post. It never becomes a long-form episode.

WHERE THE STRONGEST UNRESOLVED THREADS ACTUALLY LIVE.
Look here BEFORE settling for a physical failure-sequence dispute. A timing
question about which component fractured first is usually footnote-level and
scores FAIL. These score PASS far more often:
  - A regulator approved something repeatedly with no supporting data, and no
    investigation ever established what it believed it was reviewing.
  - An exemption, waiver, or interval extension granted on the operator's own
    say-so.
  - A safety recommendation issued, then closed unacceptable, then never revisited.
  - Two bodies with opposite findings on the same component, both still standing.
  - A regulator investigating its own enforcement failures.
  - A rule that existed but covered nobody, or covered the wrong party.
Search the approval chain, the waiver, and the recommendation status. The
mechanism is almost always settled. The permission for it usually is not.

TIERS
A = case drop, full docket, real unresolved question, long-form candidate
B = artifact drop, one document/photo/transcript excerpt
C = correction drop, "everyone says X, the record says Y"

HARD RULES (these override any instruction to make it punchier)
- Attribute testimony as testimony. "X testified that" never becomes "X did."
- Never make a dead participant the villain where the investigation found
  systemic cause.
- Where sources give different numbers, state both.
- Never state a rumour as a finding. It gets the word "rumoured" or it is cut.
- Every post carries a source line: agency, report, volume or page.
- Open on a verified number. Close on the unresolved thing. Never open on a
  mystery.
- No victim photographs. Names in type, held, in silence.
- Any asset whose rights you cannot confirm is DO NOT USE.

You must ground every factual claim in a source you actually retrieved via
web_search. If you could not verify something, it goes in could_not_verify
and is either attributed or cut. Do not pad.

Return ONLY a JSON object. No preamble, no markdown fences.
"""

SCHEMA = """
{
  "case_name": str,
  "event_date": str,
  "location": str,
  "coordinates": str,
  "agency": str,
  "docket_url": str,
  "the_number": str,
  "the_unresolved_thing": str,
  "tier": "A" | "B" | "C",
  "structural_test": {"result": "PASS" | "FAIL", "why": str},
  "commonly_wrong": [{"claim": str, "record": str, "source": str, "why_it_matters": str}],
  "investigators_disagree": [{"question": str, "position_a": str, "position_b": str, "status": str}],
  "could_not_verify": [{"item": str, "disposition": "ATTRIBUTE" | "CUT", "note": str}],
  "assets": [{"asset": str, "source_url": str, "rights": "PD" | "RESTRICTED" | "DO NOT USE", "use_for": str, "primary": bool}],
  "slides": [{"n": int, "kind": str, "label": str, "headline": str, "text": str, "visual": str}],
  "source_line": str,
  "caption": str,
  "hashtags": [str],
  "x_post": str,
  "x_post_type": "exhibit" | "correction" | "clock" | "on_this_day" | "parallel",
  "x_reply": str,
  "hook_alternates": [{"shape": str, "hook": str}],
  "longform_note": str
}
"""


def call(model, messages, system, tools=None, max_tokens=8000):
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode(),
        headers={
            "content-type": "application/json",
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def text_of(resp):
    """Concatenate text blocks. Skips server_tool_use / web_search_result blocks."""
    return "\n".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")


def research(case_hint, tier_target):
    """Pass 1: sourcing and verification. Haiku, with web search."""
    prompt = f"""Research this for a Last Known Position post: {case_hint}

Target tier: {tier_target}

Search the primary source databases. Find the actual report or docket, not
news coverage of it. Then produce:

1. The structural test result
2. commonly_wrong  - what popular retellings get wrong vs what the document says
3. investigators_disagree - any point where two bodies reached different conclusions
4. could_not_verify - anything you could not trace to a primary document
5. assets - every usable visual with its rights status

Before settling the structural test, check the approval chain specifically:
who authorised the condition that failed, what data they had, and whether any
safety recommendation about it was issued, closed, or ignored. That thread
outranks a failure-sequence timing dispute every time.

The post will run to 8-10 slides, so gather enough distinct, sourced detail to
carry that many beats: the safeguard, the document, the reading, the
rationalisation, the timeline, the toll, and the unresolved thing. Thin
research produces a boring carousel.

Return JSON with those keys plus case_name, event_date, location, coordinates,
agency, docket_url, the_number, the_unresolved_thing, tier, structural_test."""

    resp = call(
        MODEL_RESEARCH,
        [{"role": "user", "content": prompt}],
        SYSTEM,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}],
    )
    findings = parse_json(text_of(resp))
    findings["structural_test"] = norm_structural_test(findings.get("structural_test"))
    return findings


def write(findings, tier):
    """Pass 2: copy. Sonnet, no tools, cheap because input is small."""
    n_slides = {"A": 10, "B": 0, "C": 8}[tier]
    fmt = (
        f"{n_slides} carousel slides"
        if n_slides
        else "a 25-35s vertical reel: a vo_script that works with eyes closed, plus a timecoded shot_list"
    )

    prompt = f"""Here is the verified research. Write the post.

{json.dumps(findings, indent=2)}

Format: {fmt}

SLIDE ARCHITECTURE. Each slide is an object with:
  kind     one of: anomaly, correction, barrier, document, signal,
           rationalization, clock, names, contradiction, outro
  label    2-4 word section tag, e.g. "What everyone gets wrong". Omit on slide 1.
  headline 3-9 words. SHORT. This renders very large. A full sentence will
           shrink to nothing - never put a paragraph here.
  text     1-3 sentences of body copy underneath. May be empty on a clock slide.
  visual   which asset and how treated.

Run them in this order, flexing 3-6 to fit the case:
  1  anomaly         the number, huge. No question mark, no "you won't believe".
  2  correction      what everyone gets wrong. This is the swipe-bait slide.
  3  barrier         the safeguard that existed.
  4  document        the email, memo, order, or approval. Strongest slide.
  5  signal          the reading or moment the system told them the truth.
  6  rationalization why they didn't believe it. Do not villainise the dead.
  7  clock           3-5 timecoded lines in headline, separated by newlines,
                     tightening. Leave text empty. Last line is the event.
  8  names           the count in type. Never photographs.
  9  contradiction   the unresolved thing, stated flat. DOES NOT RESOLVE.
  10 outro           one line + "Full case file on YouTube. @LastKnownPositionTV"

Slides 1, 2, 9 and 10 are fixed and carry the thesis. One idea per slide - if
it needs two sentences of headline, it is two slides.

Every slide must carry a piece of evidence or a specific number. A slide that
only restates the previous one is why a carousel gets swiped past.

Slide 1 opens on the verified number. Slide 9 closes on the unresolved thing.
Caption's first line is the hook verbatim because IG and TikTok truncate after
one line. Then two sentences of context, then the source line, then the
coordinate strip.

5 to 7 hashtags, two broad two niche two case-specific. No generic tags like
#mystery or #disaster on their own.

Three hook_alternates using DIFFERENT shapes, not rewordings: contradiction,
impossible number, document, countdown, correction, price tag.

X POST - write a NATIVE version. Do not reuse the IG caption. X punishes
cross-posted hook-speak and outbound links (a link in the body costs roughly
30-40% of reach). Rules:
  - No hashtags. They do nothing on X and read as spam.
  - No link in x_post. The link goes in x_reply.
  - Under 270 characters.
  - Flat and factual. The channel states, it does not tease.
  - A reply is weighted 27x a like, so the post should invite correction or
    "actually" - but only about interpretation, never about facts.
Pick x_post_type from:
  exhibit     - the document/gauge/chart, one flat factual line under it
  correction  - "Everyone says X about [event]. The [agency] report says Y."
  clock       - 3-4 timecoded lines, tightening, last line is the event
  on_this_day - "On [date], [year]: [flat statement]." evergreen
  parallel    - connects the case to a current industry story
x_reply is always: "Full case file: https://www.youtube.com/@LastKnownPositionTV"

Return the complete JSON object matching this schema, merging in the research
fields you were given:
{SCHEMA}"""

    resp = call(MODEL_WRITE, [{"role": "user", "content": prompt}], SYSTEM)
    return parse_json(text_of(resp))


def norm_structural_test(v):
    """Coerce structural_test to its documented {"result", "why"} shape.

    The model is asked for an object but sometimes returns a bare string.
    findings.get("structural_test", {}) does not protect against this: the key
    is present, it is just the wrong type, so the {} default never applies and
    the following .get() raises AttributeError. Idempotent.
    """
    if isinstance(v, dict):
        result = str(v.get("result", "")).strip().upper()
        why = str(v.get("why", ""))
    elif isinstance(v, str):
        why = v.strip()
        result = why.upper()
    else:
        return {"result": "UNKNOWN", "why": ""}
    result = "FAIL" if "FAIL" in result else "PASS" if "PASS" in result else "UNKNOWN"
    return {"result": result, "why": why}


def parse_json(s):
    s = s.strip()
    if s.startswith("```"):
        s = s.split("```")[1]
        if s.startswith("json"):
            s = s[4:]
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in model output:\n{s[:600]}")
    return json.loads(s[start : end + 1])


def next_case():
    """Pull the next unprocessed row from the case bank."""
    bank = json.loads((DATA / "case_bank.json").read_text())
    for row in bank:
        if row.get("status") == "queued":
            return row
    raise SystemExit("case_bank.json has no rows with status 'queued'. Refill it.")


def main():
    if len(sys.argv) > 1:
        hint, tier = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "A")
        row = None
    else:
        row = next_case()
        hint, tier = row["hint"], row.get("tier", "A")

    print(f"[research] {hint}  tier={tier}")
    findings = research(hint, tier)

    if norm_structural_test(findings.get("structural_test"))["result"] == "FAIL" and tier == "A":
        print("[research] structural test FAILED for tier A, demoting to C")
        tier = findings["tier"] = "C"

    package = write(findings, tier)
    package["generated_at"] = datetime.datetime.now(timezone.utc).isoformat()
    package["status"] = "pending_approval"

    queue = json.loads((DATA / "queue.json").read_text())
    package["daily_no"] = f"{len(queue) + 1:03d}"
    queue.append(package)
    (DATA / "queue.json").write_text(json.dumps(queue, indent=2))

    if row is not None:
        bank = json.loads((DATA / "case_bank.json").read_text())
        for r in bank:
            if r.get("hint") == row["hint"]:
                r["status"] = "processed"
        (DATA / "case_bank.json").write_text(json.dumps(bank, indent=2))

    print(f"[research] queued DAILY {package['daily_no']} - {package.get('case_name')}")
    print(f"[research] tier {package.get('tier')} | unresolved: {package.get('the_unresolved_thing')}")


if __name__ == "__main__":
    main()
