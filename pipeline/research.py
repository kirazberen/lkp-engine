"""
Node 01 + 02 — MINE and WRITE, in one API call.

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

STRUCTURAL TEST — run first.
Name, in one sentence, the specific thing the investigation could not settle.
"Nobody knows what happened" = FAIL, mystery-channel material.
"Two agencies published opposite conclusions and both still stand" = PASS.
A FAIL can still be a Tier B or C post. It never becomes a long-form episode.

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
  "slides": [{"n": int, "text": str, "visual": str}],
  "source_line": str,
  "caption": str,
  "hashtags": [str],
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
2. commonly_wrong  — what popular retellings get wrong vs what the document says
3. investigators_disagree — any point where two bodies reached different conclusions
4. could_not_verify — anything you could not trace to a primary document
5. assets — every usable visual with its rights status

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
    n_slides = {"A": 5, "B": 0, "C": 3}[tier]
    fmt = (
        f"{n_slides} carousel slides"
        if n_slides
        else "a 25-35s vertical reel: a vo_script that works with eyes closed, plus a timecoded shot_list"
    )

    prompt = f"""Here is the verified research. Write the post.

{json.dumps(findings, indent=2)}

Format: {fmt}

Slide 1 / the first 3 seconds opens on the verified number. The last slide
closes on the unresolved thing. Caption's first line is the hook verbatim
because IG and TikTok truncate after one line. Then two sentences of context,
then the source line, then the coordinate strip.

5 to 7 hashtags, two broad two niche two case-specific.

Three hook_alternates using DIFFERENT shapes, not rewordings: contradiction,
impossible number, document, countdown, correction, price tag.

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
    package["generated_at"] = datetime.datetime.utcnow().isoformat() + "Z"
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

    print(f"[research] queued DAILY {package['daily_no']} — {package.get('case_name')}")
    print(f"[research] tier {package.get('tier')} | unresolved: {package.get('the_unresolved_thing')}")


if __name__ == "__main__":
    main()
