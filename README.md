# skillcheck-lite — what an auditor actually measures

Two scripts, no dependencies beyond Python 3, that answer one question: **are the files you gave your AI agent
telling it the truth?**

I sell a $69 agent-readiness audit. These are the mechanical halves of it, published because an auditor who
won't show their instruments is asking for trust they haven't earned. The judgement — which finding will
actually cost you an afternoon, and what to write instead — is the part I sell, and it is deliberately **not**
in this repo.

## `tools/analyze.py <repo>` — measurement, not vibes

Finds instruction files wherever they actually live (this matters more than it sounds: `.cursorrules` has no
extension, and a regex assuming `.md` finds **1 of 6** rule locations in a typical multi-tool repo). Then, per
file:

- **Commands an agent could paste**, extracted from fenced blocks, line-anchored blocks and backticks, with
  trailing `# comments` stripped and path-like junk rejected (`/docs`, `going`, `<lib>-docs/fetch.py`).
- **Verification language** — does it ever say how to know the work *worked*, or only how to run it?
- **Drift against reality** — compared against `package.json` scripts and Makefile targets, not against my
  opinion: *documented but not runnable* (the file lies) and *runnable but undocumented* (an agent cannot know
  it exists; my favourite real finding was a `test` script that is watch mode and never exits).
- **Referenced paths** — reported as *unresolved by the probe*, never as "dead", because build outputs
  (`dist/cli.js`) and filenames quoted in prose look identical to a genuine dead reference. A human confirms
  each one; pretending otherwise is how an audit gets padded.
- **Staleness** — is the code newer than the document describing it? Git is parsed **once per repo**, because
  60 instruction files × 60 `git log` calls is not an audit, it's a rate-limit incident.
- **Fixtures are excluded from finding totals** (`test/`, `fixtures/`, `examples/`). They are invalid *on
  purpose*. A report that scolds a test corpus loses the room.

## `tools/replay.py <repo>` — run the safe ones

Executes a **whitelisted** subset of the commands your file asserts, under a timeout, so the report contains a
fact neither of us invented. The whitelist is the product: `test:integration` sounds safe and on one repo I
audited, that exact command *deletes database rows* by its own documentation. Excluded by name: migrations,
seeds, installs, dev servers, watchers, anything `--fix` or `--write`. Unexecuted commands are printed as
`SKIPPED` with a reason — **an unexecuted command is never reported as a pass.**

## What I do NOT claim

These scripts do not produce an audit. They produce evidence; `check-padding.py` exists because I found myself
writing sentences that could have been written about any repository, and a sentence like that is worth $0.
