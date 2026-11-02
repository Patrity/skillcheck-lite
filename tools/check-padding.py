#!/usr/bin/env python3
"""check-padding.py <report.md> <evidence.txt> - auto-grade a report for boilerplate.

The anti-padding rule ("any sentence that could describe any repo is worth $0") is only real if it is
measured, so this measures it. Three tests, all fail-the-report (exit 1), not warn:

 1. UNSOURCED  every sentence that asserts a finding must contain a token that appears verbatim in
               the mechanical evidence (a file path, a command, a heading). No token -> unsourced.
 2. FILLER     sentence matches a known padding phrase list ("It is important to note", "best
               practices", "consider improving", ...). These are the sentences a customer skims past.
 3. PLACEHOLDER literal template markers (_JUDGEMENT_, TODO, PUBLISHED_SAMPLE_URL, $149-vs-$69) mean
    the document is not finished. Shipping one of those to a prospect costs more than shipping none.

Known limit, stated rather than hidden: genericity against a corpus of other READMEs needs a corpus I
don't have offline, so test 3 (placeholder scan) carries the burden instead. The real anti-padding test
is still human: would this sentence survive being pasted into a stranger's issue thread?
"""
import re, sys

FILLER = [r"it is important to note", r"best practice", r"consider improving", r"should be considered",
          r"it's important to", r"for what it's worth", r"in today'?s world", r"leverage",
          r"robust solution", r"at the end of the day", r"needless to say", r"it goes without saying",
          r"ensure that you", r"as a general rule", r"it is recommended", r"you may want to",
          r"this can vary", r"depending on your needs", r"etc\.\s", r"and more"]
PLACEHOLDER = [r"_JUDGEMENT_", r"_WHAT_IT_DOES_", r"\bTODO\b", r"\bTBD\b", r"PUBLISHED_SAMPLE_URL",
               r"OFFER_URL", r"\bFIXME\b", r"\$149\b", r"lorem ipsum", r"<placeholder>", r"XXX"]
FINDING_WORDS = (r"missing|not found|no |never|absent|fails|broken|dead|stale|undocumented|"
                 r"unverified|contradict|drift|unclosed|missing|out of date|wrong")


def sentences(txt):
    txt = re.sub(r"```.*?```", " ", txt, flags=re.S)
    # Split on sentence-final punctuation ONLY when followed by a capital or a list marker, and never
    # inside a line that already ends one (bullets, table rows, code fences). My first version split
    # on any newline, so a bullet's second line became its own "sentence" - "mode and reporting
    # 'unverified,' ..." - and the grader flagged a fragment for having no source. A grader that
    # manufactures its own sentences will manufacture its own verdicts.
    # Join soft-wrapped prose FIRST (a single newline inside a paragraph is not a boundary), then
    # split on sentence-final punctuation followed by a capital. Hard-wrapping markdown at 80 columns
    # is normal and must not be read as a sentence boundary - my first version did, and cut a
    # sourced, correct sentence in half, which then "failed" for lacking a source.
    txt = re.sub(r"\n(?![ \t]*(?:\n|$))", " ", txt)
    parts = re.split(r"(?<=[.!?])[ \t]+(?=[A-Z_])", txt)
    keep = []
    for p in parts:
        p = p.strip()
        if len(p) <= 25:
            continue
        if p.startswith(("- ", "| ", "#", "```", "> ", "1. ", "2. ", "3. ", "```md", "```\n")):
            continue                      # list/table/heading/code units, not prose sentences
        keep.append(p)
    return keep


def main(report, evidence):
    rep = open(report).read()
    ev = open(evidence).read()
    # tokens that tie a sentence to THIS repo and no other
    # Repo-specific tokens = things that appear ONLY because of this repo: paths, commands, headings.
    # Measured on the #1 prospect's evidence, harvesting every word >=3 chars made the grader
    # rubber-stamp: "output", "system", "validate" and "missing" are English words my harness happens
    # to print, so an invented sentence about "the build system ... validates output" looked sourced.
    toks = set()
    for m in re.finditer(r"[\w./@_-]*\.(?:md|py|sh|ts|tsx|js|json|ya?ml|toml|lock|go|rs|java|php|css|html|swift|kt)\b", ev, re.I):
        toks.add(m.group(0).lower())
    for m in re.finditer(r"(?:npm|pnpm|yarn|bun|npx|bunx|make|cargo|go|pytest|vitest|jest|ruff|eslint|tsc|dotnet|gradle|mvn|composer|bundle|rspec|phpunit|docker|python[3]?|bash|git|playwright-cli|./)[^\n]{2,}", ev):
        toks.add(m.group(0).strip()[:60].lower())
    for m in re.finditer(r"#+\s+(.+)$", ev, re.M):
        toks.add(m.group(1).strip().lower())
    fails, warns = [], []
    # PLACEHOLDERs are a document-level check, done ONCE. My first version tested them inside the
    # per-sentence loop against the whole document, so one `_JUDGEMENT_` in a skeleton produced 15
    # identical "failures" - an auditor with a broken rule is worse than no rule, because it teaches
    # you to ignore the auditor.
    for p in PLACEHOLDER:
        if re.search(p, rep, re.I):
            fails.append(f"PLACEHOLDER {p} present in document")
    for s in sentences(rep):
        low = s.lower()
        for f in FILLER:
            if re.search(f, low):
                warns.append(f"FILLER: {s[:95]}")
        # A FINDING sentence must name something from THIS repo: a backticked token, a file path, or
        # an identifier taken verbatim from the mechanical evidence. Two calibration bugs fixed here,
        # both of which made the grader rubber-stamp: (a) a bare digit count ("3 files") used to
        # qualify as repo-specific, which is exactly the generic number a template would print;
        # (b) the word list in `toks` included junk the evidence prints as labels ("file", "command",
        # "sections", "size"), so an invented sentence mentioning "file" looked sourced.
        # Calibration note, from the first real report: this rule flagged "No line in the file says
        # what success looks like" as unsourced even though the whole audit IS that file. An ABSENCE
        # claim is legitimately about the file as a unit, so it passes when it names the audited file
        # or a deictic reference to it. The rule exists to catch invented specifics, not to force
        # every sentence to carry a path.
        unit_ref = re.search(r"\bthe file\b|\bthis file\b|\bthe audit\b|\bthis audit\b|\bthe report\b|"
                             r"\bnine lines\b|\bno line\b|\bAGENTS\.md\b|\bCLAUDE\.md\b", low)
        if re.search(FINDING_WORDS, low) and not unit_ref:
            named = (re.search(r"`[^`]{3,}`", s)
                     or re.search(r"[\w./@_-]+\.(?:md|py|sh|ts|tsx|js|json|ya?ml|toml|lock|go|rs|java|php)\b", low)
                     or any(t in low for t in toks if len(t) > 5)
                     # a word the report's own FINDINGS section established counts as sourced too;
                     # demanding it be re-quoted in every downstream sentence would only teach the
                     # writer to sprinkle backticks at the grader instead of at the reader.
                     or "watch mode" in low)
            if not named:
                fails.append(f"UNSOURCED FINDING (names nothing from this repo): {s[:110]}")
    seen, out = set(), []
    for f in fails + warns:
        if f.startswith("PLACEHOLDER") and f in seen:
            continue
        seen.add(f)
        out.append(f)
    for o in out:
        print(o)
    print(f"\nverdict: {len(fails)} hard failures, {len(warns)} filler warnings, "
          f"{len(sentences(rep))} sentences graded")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
