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
import re
import random
import time
import urllib.request
import urllib.error

API_URL = "https://api.anthropic.com/v1/messages"
API_KEY = os.environ["ANTHROPIC_API_KEY"]

MODEL_RESEARCH = os.environ.get("LKP_MODEL_RESEARCH", "claude-haiku-4-5-20251001")
MODEL_WRITE = os.environ.get("LKP_MODEL_WRITE", "claude-sonnet-5")
# times to ask the model to repair unparseable JSON before giving up
JSON_RETRIES = int(os.environ.get("LKP_JSON_RETRIES", "2"))
# transient API failures (429/529/network) before giving up
API_RETRIES = int(os.environ.get("LKP_API_RETRIES", "4"))
API_BACKOFF_CAP = float(os.environ.get("LKP_API_BACKOFF_CAP", "60"))

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

VOICE - the copy must not read as machine-written.
These override style preferences but never the HARD RULES above. None of them
licenses inventing a detail to make a line land better. If a sentence needs a
fact you do not have, write the shorter version instead. An invented specific
is a worse failure than a flat sentence.

- No em dashes or en dashes anywhere. Use a period, a comma, a colon, or
  parentheses. This is the single most reliable tell there is.
- No negative parallelism. Not "not just X, it is Y", not "it is not about X,
  it is about Y", and no clipped negation tacked on the end, as in "no
  warning" or "no second chance".
- Do not force ideas into threes. Use two, or four, or one.
- Do not end a sentence with a participle clause that fakes depth:
  "highlighting the failure", "underscoring the risk", "reflecting a broader
  pattern". Cut it, or make it a real sentence with a subject.
- No significance puffery: stands as, serves as, is a testament to, marks a
  pivotal moment, a stark reminder, a turning point, cemented its place, left
  an indelible mark, forever changed.
- Use is, are, has. Not serves as, boasts, features, represents.
- Do not use these words: delve, crucial, pivotal, underscore, showcase,
  tapestry, testament, vibrant, intricate, enduring, foster, garner, realm,
  landscape and navigate in their figurative senses, grim reminder, chilling,
  harrowing, tragic irony, fatal flaw.
- No aphorism formulas: "X is the Y of Z", "the anatomy of X", "the price of
  X", "the architecture of X".
- Do not stack short dramatic fragments to manufacture tension. One short
  sentence for emphasis is fine. Four in a row is a tell.
- No rhetorical openers: "Here is the thing", "Make no mistake", "Let that
  sink in", "Honestly", "The real question is".
- No closing uplift, no lesson-learned summary, no send-off. End on the last
  concrete fact. Slide 9 already carries the ending.
- Straight quotes only, never curly. No emoji anywhere, including the caption.
- Vary sentence length deliberately. Real writing alternates short and long.
  An even mid-length cadence is what generated text sounds like.
- Prefer the specific over the summarised: a part number, a gauge reading, a
  time on a clock, the exact wording of a memo. Keep numbers exactly as the
  source gives them and never round one for rhythm.

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


RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}


def _backoff(attempt, retry_after=None):
    """Exponential backoff with jitter, honouring Retry-After when the API sends it."""
    if retry_after:
        try:
            return min(float(retry_after), API_BACKOFF_CAP)
        except (TypeError, ValueError):
            pass
    base = min(API_BACKOFF_CAP, 2.0 ** attempt)
    # half fixed, half jittered: retries stay spread out without collapsing to ~0
    return base / 2 + random.random() * base / 2


def call(model, messages, system, tools=None, max_tokens=8000):
    """POST to the Messages API, retrying transient failures with bounded backoff.

    429 and 529 are routine on a busy account, and a bare urlopen turns either
    into an unhandled HTTPError that kills the whole run. Retries are capped by
    LKP_API_RETRIES so a hard outage still fails instead of spinning.
    """
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    if tools:
        body["tools"] = tools
    data = json.dumps(body).encode()

    for attempt in range(API_RETRIES + 1):
        req = urllib.request.Request(
            API_URL,
            data=data,
            headers={
                "content-type": "application/json",
                "x-api-key": API_KEY,
                "anthropic-version": "2023-06-01",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code not in RETRYABLE_STATUS or attempt == API_RETRIES:
                # Surface the API's own error body. Without this a 400 is an
                # opaque "HTTP Error 400: Bad Request" with no reason attached.
                try:
                    detail = e.read().decode("utf-8", "replace")[:500]
                except Exception:
                    detail = ""
                raise RuntimeError(f"Anthropic API {e.code}: {detail}") from e
            delay = _backoff(attempt, e.headers.get("retry-after"))
            reason = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == API_RETRIES:
                raise
            delay = _backoff(attempt)
            reason = type(e).__name__
        print(
            f"[api] {reason}, retrying in {delay:.1f}s "
            f"({attempt + 1}/{API_RETRIES})",
            file=sys.stderr,
        )
        time.sleep(delay)

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

    findings = call_json(
        MODEL_RESEARCH,
        prompt,
        SYSTEM,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}],
        label="research",
    )
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

    return call_json(MODEL_WRITE, prompt, SYSTEM, label="write")


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


def _extract_json(s):
    """Isolate the JSON object in a model reply."""
    s = s.strip()
    if s.startswith("```"):
        parts = s.split("```")
        if len(parts) > 1:
            s = parts[1]
        s = s.lstrip()
        if s[:4].lower() == "json":
            s = s[4:]
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in model output:\n{s[:600]}")
    return s[start : end + 1]


def _repair_json(s):
    """Undo the two ways models most often bend JSON.

    1. A raw newline/tab inside a string literal, which json rejects.
    2. A trailing comma before a closing brace or bracket.

    Both passes track whether they are inside a string literal, so a comma or
    a brace that merely appears inside prose is never touched. An unescaped
    quote inside a string is deliberately NOT repaired: fixing it means
    guessing where the string was meant to end, and guessing wrong silently
    corrupts the copy. That case is left to the retry path.
    """
    chars, comma_at, in_str, esc = [], [], False, False
    for ch in s:
        if esc:
            chars.append(ch)
            esc = False
        elif ch == "\\":
            chars.append(ch)
            esc = True
        elif ch == '"':
            in_str = not in_str
            chars.append(ch)
        elif in_str:
            chars.append({"\n": "\\n", "\r": "\\r", "\t": "\\t"}.get(ch, ch))
        else:
            if ch == ",":
                comma_at.append(len(chars))
            chars.append(ch)

    drop = set()
    for i in comma_at:
        j = i + 1
        while j < len(chars) and chars[j].isspace():
            j += 1
        if j < len(chars) and chars[j] in "}]":
            drop.add(i)
    return "".join(c for k, c in enumerate(chars) if k not in drop)


def parse_json(s):
    """Extract and parse the model's JSON, repairing what is safely repairable."""
    frag = _extract_json(s)
    err = None
    for candidate in (frag, _repair_json(frag)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as e:
            err = e
    # Print the offending region. Without this the bad output dies with the
    # process and the next failure is exactly as blind as this one was.
    lo, hi = max(0, err.pos - 300), min(len(frag), err.pos + 300)
    print(
        f"[parse] JSON invalid at line {err.lineno} col {err.colno} "
        f"(char {err.pos}): {err.msg}",
        file=sys.stderr,
    )
    print(f"[parse] ...{frag[lo:hi]}...", file=sys.stderr)
    raise err


def call_json(model, prompt, system, tools=None, label="call"):
    """call() + parse_json, retrying when the model returns unparseable JSON.

    Attempt 1 is the real request. Each retry is a cheap no-tool turn that
    hands the bad text back and asks for the corrected object - no tools, so
    a tool_use block is never replayed without its matching tool_result.
    """
    resp = call(model, [{"role": "user", "content": prompt}], system, tools=tools)
    text = text_of(resp)
    for attempt in range(1, JSON_RETRIES + 1):
        try:
            return parse_json(text)
        except (ValueError, json.JSONDecodeError) as e:
            print(f"[{label}] unparseable JSON ({e}); repair {attempt}/{JSON_RETRIES}")
            fix = (
                "The text below was meant to be one JSON object but does not "
                f"parse: {e}\n\nReturn ONLY the corrected JSON object - no "
                "prose, no code fence, no commentary.\n\n" + text[:12000]
            )
            resp = call(model, [{"role": "user", "content": fix}], system)
            text = text_of(resp)
    return parse_json(text)

def next_case():
    """Pull the next unprocessed row from the case bank."""
    bank = json.loads((DATA / "case_bank.json").read_text())
    for row in bank:
        if row.get("status") == "queued":
            return row
    raise SystemExit("case_bank.json has no rows with status 'queued'. Refill it.")


EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF\U0000FE00-\U0000FE0F\U0001F900-\U0001F9FF\U000024C2\U0000203C]"
)


def scrub_typography(value):
    """Strip the typographic tells the prompt asks for but cannot guarantee.

    Purely mechanical and meaning-preserving: it never rewrites wording. The
    prompt is a request, and a model under pressure to be vivid will reach for
    an em dash anyway, so the three highest-confidence signals are enforced
    here instead of hoped for.

    Recurses through the package so nested slides and hook_alternates are
    covered, not just the top-level strings.
    """
    if isinstance(value, dict):
        return {k: scrub_typography(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_typography(v) for v in value]
    if not isinstance(value, str):
        return value

    s = value
    # curly punctuation -> straight
    s = (
        s.replace("“", '"').replace("”", '"')
        .replace("‘", "'").replace("’", "'")
        .replace("…", "...")
    )
    # an en dash between digits is a numeric range, not an aside: 1980-1990
    s = re.sub(r"(?<=\d)\s*[–—]\s*(?=\d)", "-", s)
    # any remaining em/en dash is an aside; a comma preserves the reading
    s = re.sub(r"\s*[–—]\s*", ", ", s)
    # double hyphen used the same way
    s = re.sub(r"\s+--\s+", ", ", s)
    s = EMOJI.sub("", s)
    # collapse whatever whitespace the substitutions left behind
    s = re.sub(r" {2,}", " ", s)
    s = re.sub(r" ([,.;:!?])", r"\1", s)
    return s.strip()


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
    package = scrub_typography(package)
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
