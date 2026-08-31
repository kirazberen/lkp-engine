# LKP ENGINE

Fully automated daily case pipeline for Last Known Position.

**Total infrastructure cost: $0. Total running cost: about $5/month.**

---

## WHY THIS SHAPE

The cheapest possible version isn't "n8n on a cheap VPS with Airtable". It's no servers and no database at all.

| Node | Conventional | Here | Cost |
|---|---|---|---|
| Scheduler | Make.com $9/mo, or n8n on a $5 VPS | **GitHub Actions cron** | $0 |
| Database | Airtable, 1,000-record cap | **The repo itself.** JSON files committed back each run. Free version history, free diffs, editable from your phone | $0 |
| Scraper | Apify $29/mo | **Deleted.** Government sites are free and have no anti-bot wall. The model searches them directly | $0 |
| Image gen | Nano Banana / Gemini API per image | **Pillow, rendered locally.** Your brand is type on near-black over real evidence. That's a typography job, not an image-generation job | $0 |
| Scheduler/poster | Metricool $25/mo | **Buffer free.** 3 channels, 10 queued each refilled as they publish, API access included | $0 |
| Research + copy | — | **Claude API.** The only real cost | ~$5/mo |

GitHub Actions free tier is 2,000 minutes/month on private repos. This uses about 60. Public repo is unlimited.

---

## COST MATH

Per post, roughly:

- Research sweep, Haiku 4.5 at $1/$5 per Mtok: ~40k in, 4k out = **$0.06**
- Web search tool, ~6 searches: **$0.06**
- Copy pass, Sonnet at $2/$10 per Mtok: ~15k in, 2k out = **$0.05**

**~$0.17/post → ~$5/month at one a day.**

Two notes. Sonnet 5's introductory $2/$10 rate runs through August 31 2026, then goes to $3/$15, which takes this to roughly $6/month. And a new API account gets $5 in free credits, so month one is free.

To halve it further: set `LKP_MODEL_WRITE=claude-haiku-4-5-20251001`. Quality drops on the copy but the research and verification are unaffected.

---

## SETUP

**1. Create the repo**
Push this folder to a new private GitHub repo.

**2. Fonts**
Download from Google Fonts into `assets/fonts/`: `Anton-Regular.ttf`, `Inter-Regular.ttf`, `SpaceMono-Regular.ttf`, `SpaceMono-Bold.ttf`. All four free. Commit them.

**3. Secrets** — repo Settings → Secrets and variables → Actions

| Secret | Where from |
|---|---|
| `ANTHROPIC_API_KEY` | platform.claude.com, no card needed for the $5 free credit |
| `BUFFER_ACCESS_TOKEN` | Buffer developer settings, free plan includes 1 API key |
| `BUFFER_PROFILE_IDS` | Comma-separated. Hit `/1/profiles.json` with your token to list them |

**4. Set a spend limit on the Anthropic key.** Do this on day one, not after.

**5. Enable Actions.** It runs itself from there.

---

## THE LOOP

```
14:00 UTC  research.py   next queued case → web search primary sources
                         → verification pass → copy → data/queue.json
           render.py     → slides into out/

  you      15 min/week   flip "pending_approval" → "approved" in
                         data/queue.json. GitHub's web editor works on mobile.

02:00 UTC  publish.py    approved posts → Buffer queue
           score.py      Buffer analytics → data/scores.json
                         → data/shortlist.json (long-form ranking)
```

### Why the approval gate stays

The reel this was modelled on says "0 humans, nobody approves it, nobody is home." Don't copy that part. On a channel whose entire moat is being right, one rumour promoted to a finding costs more than forty correct posts earn. Fifteen minutes a week. Filming was the bottleneck, not approving.

---

## THE VERIFICATION PASS

Every package carries three lists, and they ship with the post so you can see the working:

1. **commonly_wrong** — what popular retellings get wrong vs what the document says. This is free Tier C content, generated as a byproduct.
2. **investigators_disagree** — where two bodies reached different conclusions. This is not a problem to smooth over. It's the dramatic material and usually the ending.
3. **could_not_verify** — every item marked either ATTRIBUTE or CUT. No third option.

Plus the structural test: name in one sentence what the investigation could not settle. Fail it and the case is auto-demoted from Tier A. That single check is what keeps this from becoming a mystery channel.

---

## THE SCORER

Ranks cases for long-form promotion. Runs at day 3 and again at day 14, because short-form has a long tail and day 14 frequently reorders the board.

```
profile_visits_per_1k × 4
saves_per_1k          × 3
shares_per_1k         × 3
question_comments     × 5
hold_rate             × 2
likes_per_1k          × 0.5
```

Likes are weighted near zero on purpose. A like means "approve". A profile visit means "want more". Only the second one predicts whether a case can carry fifteen minutes.

`data/shortlist.json` is your episode order, decided by data instead of taste.

---

## FILES

```
pipeline/research.py   mine + verify + write   (the only node that costs money)
pipeline/render.py     slides, local, free
pipeline/publish.py    → Buffer
pipeline/score.py      ← Buffer, ranks for long-form
data/case_bank.json    the input queue, 10 cases seeded
data/queue.json        generated packages, approve here
data/scores.json       performance history
data/shortlist.json    long-form ranking, written by score.py
```

## KNOWN CHECKS BEFORE FIRST RUN

- **Verify the Buffer endpoint.** `publish.py` targets `/1/updates/create.json`. Buffer has kept that shape a long time but confirm against their current docs rather than trusting this file.
- **Buffer image posting.** Text posts go through the documented endpoint cleanly. Attaching the rendered slides may need their media upload flow. If it fights you, the slides are sitting in `out/` and take 30 seconds to attach by hand.
- **Run it manually first.** Actions tab → LKP daily → Run workflow, with a `case_hint`. Read the output before you let the cron touch anything.

---

## LICENSE

Source-available, **not** open source. Copyright (c) 2026 kirazberen, all rights
reserved.

You may read this repository. You may not use, copy, modify, redistribute, host,
or build on any part of it - including running the pipeline, reusing the prompts,
schema or case bank, reproducing the slide system, or using it as ML training
data - without prior written consent.

To request consent, open an issue. Silence is not consent.

Exception: the fonts in `assets/fonts/` are third-party works under the SIL Open
Font License 1.1 and keep their own terms. See [LICENSE](LICENSE) for the full
notice.
