#!/usr/bin/env python3
"""analyse.py <repo_dir> - produce the evidence base for a written agent-readiness audit.

This is deliberately NOT a checker. A checker says "this is wrong"; an audit has to say what an
agent will DO differently, which needs the actual content in front of me. So this script does the
mechanical reading (inventory, size, structure, command extraction, cross-file contradiction
detection) and prints quotable evidence. The judgement layer is a human/agent reading its output.

Design rule: every probe reports either EVIDENCE or "not found" - never a silent skip. A probe
that finds nothing and says nothing is how an audit invents a clean bill of health (I have now been
burned twice by empty output being mistaken for a finding, once for the absence of one).
"""
import os, re, sys, json, subprocess, datetime, collections

FIXTURE = re.compile(r"(^|/)(tests?|fixtures?|testdata|samples?|examples?)(/|$)", re.I)

# Names that have NO extension are matched separately: `^\.cursorrules\.md$` never matches the
# real file `.cursorrules`, so my first version could tell a prospect "no instruction files found"
# while their rules file sat in the repo. Verify with: any-instruction() below.
INSTRUCTION = re.compile(r"^(AGENTS|CLAUDE|GEMINI|QWEN|IFLOW|\.cursorrules|\.clinerules)\.md$", re.I)
EXTLESS   = re.compile(r"^\.?(cursorrules|clinerules|cursorignore|windsurfrules)$", re.I)
MORE_PATHS = re.compile(r"(^|/)(\.cursor/rules/.*\.mdc|\.claude/commands/.*\.md|\.github/copilot-instructions\.md|opencode\.json|\.claude/settings\.json|\.mcp\.json|mcp\.json)$")


def is_instruction(name, relpath=""):
    return bool(INSTRUCTION.match(name) or EXTLESS.match(name) or MORE_PATHS.search("/" + relpath.replace(os.sep, "/")))
SKILL = re.compile(r"^skill\.md$", re.I)
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "vendor", "dist", "build"}
HEAD = re.compile(r"^(#{1,6})\s+(.*)$")
# Three capture families, in order of trust:
#   (a) a fenced code block -> any non-# line is a command (fences are an explicit "this is code"
#       signal from the author, so trusting them avoids re-implementing shell tokenising in regex);
#   (b) a line whose FIRST token is a known runner;
#   (c) backticked text whose first token is a known runner.
# Anything else is prose and must not be reported as a command.
RUNNER = r"(?:npm|pnpm|yarn|bunx?|npx|make|cargo|go|pytest|vitest|jest|ruff|eslint|prettier|tsc|dotnet|gradle|mvn|composer|bundle|rspec|phpunit|swift|docker|python[3]?|bash|sh|curl|git|playwright-cli|./)"
FENCE = re.compile(r"```[a-zA-Z0-9_+-]*\n(.*?)```", re.S)
BARE = re.compile(r"^[ \t]*(" + RUNNER + r"[^\n]*)$", re.M)
INLINE = re.compile(r"`[^`\n]{3,80}`")
# (a) a known runner as the FIRST token, with its args; (b) a ./script or make target. Anything else
# (prose words beginning with "go", paths like /docs) is not a command and must not be reported as
# one - my first version listed "/docs" and "going" as commands, which would have put fake advice
# in a paid report.

VERB = re.compile(r"\b(run|execute|build|test|lint|format|check|verify|install|deploy)\b", re.I)
NEG = re.compile(r"\b(do not|don't|never|avoid|never edit|do not edit|forbidden|deprecated|careful|warning|gotcha|note:)\b", re.I)
TIME = re.compile(r"\b(slow|takes? about|minutes?|hours?|seconds?|expensive|CI time)\b", re.I)


def walk(root):
    out = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for f in fns:
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, root)
            if is_instruction(f, rel) or SKILL.match(f):
                out.append(p)
    return sorted(out)


def read(p):
    try:
        return open(p, encoding="utf-8").read()
    except Exception as e:
        return ""


def commands(txt):
    """Commands an agent could actually paste. See RUNNER/FENCE/BARE/INLINE for why each source is trusted."""
    found = set()
    for block in FENCE.findall(txt):
        for line in block.splitlines():
            l = line.strip()
            if l and not l.startswith("#") and not l.startswith("$"):
                # strip the trailing comment, then the line's first 2 columns as the command.
                # A fenced block often carries "# what this does" on the same line, and shipping
                # that comment inside a customer's "paste-ready fix" would look amateurish.
                l = re.split(r"\s{2,}#(?!\!)", l)[0].rstrip()
                if l:
                    found.add(l[:110])
    def clean(l):
        # One cleaner for every source. Without it the fenced path and the line-anchored path
        # disagree about the same line and the command list carries the same command twice -
        # once clean, once with its "# what this does" comment welded on.
        l = re.split(r"\s{2,}#(?!\!)", l.strip())[0].rstrip()
        return l[:110]

    for m in BARE.finditer(txt):
        c = clean(m.group(1))
        if c:
            found.add(c)
    for m in INLINE.finditer(txt):
        inner = m.group(0).strip("`").strip()
        if re.match("^" + RUNNER + r"(\s|$)", inner):
            found.add(clean(inner))
    # Drop path-like and prose-like entries. My first two versions listed `/docs`, `/skills`,
    # `/skill/nuxt` and even the bare word `bundles` as "commands" - which would have put fake
    # advice into a PAID report. A path has no space and starts with / or contains a file
    # extension; neither is something you paste into a shell to do work.
    def is_cmd(c):
        # Reject anything that is not plausibly ONE shell command. My earlier versions leaked
        # markdown list fragments ("/`, `/skills` (search + tag chip), ..."), prose ("shared by every
        # session on the machine..."), and bare wrappers ("bash -lc") into a list a customer would
        # read as "commands your file documents" - which is the kind of noise that makes a maintainer
        # stop trusting the findings that ARE real.
        if c.startswith(("/", "./")) and " " not in c: return False
        if c.count("`") or c.count(",") > 1 or "(" in c and ")" in c and not c.startswith(("bun", "npm", "pnpm", "go")):
            if not re.search(r"(eval|exec|run|test|build|lint|check|fmt|serve|start|snapshot|open|click|fill)", c):
                return False
        if len(c.split()) == 1 and not re.match("^(make|docker|cargo|pytest|tsc|eslint|ruff|knip|jest|vitest|rspec|phpunit|playwright-cli|swift|bundle|composer)$", c):
            return False            # a wrapper alone ("bash -lc") is not a command an agent can act on
        if c.endswith((".", "…", " ...", "…`")) or "…" in c: return False
        if re.search(r"\.(md|py|ts|js|json|yaml|yml|png|sh)$", c) and " " not in c: return False
        return bool(re.match("^" + RUNNER, c)) or c.startswith(("./", "make "))
    ok = sorted({c for c in found if is_cmd(c)})
    return ok


REF = re.compile(r"(?<![\w.*?<>/-])([\w./@-]+\.(?:md|py|sh|ts|tsx|js|json|ya?ml|toml|lock))(?![\w-])")
TEMPLATE = re.compile(r"[<>$*{}]|\.\.\.|^/|~")
SECRETISH = re.compile(r"\b[A-Z][A-Z0-9_]{3,}=\S{12,}|\b[a-zA-Z0-9+/]{28,}={0,2}\b|\bsk-[A-Za-z0-9]{16,}\b")


def resolve_refs(txt, root, rel):
    """Do the paths this file promises actually exist? A dead reference is worse than a missing one:
    an agent follows it, finds nothing, and either gives up or invents a path. Template paths
    (`<lib>-docs/fetch.py`) and absolute paths are excluded - they are not defects, and reporting
    them as if they were is exactly the padding I am trying to price out."""
    base = os.path.dirname(os.path.join(root, rel))
    missing, checked = [], 0
    for m in REF.finditer(txt):
        tgt = m.group(1)
        # A glob fragment (`*.test.ts`, `**/__tests__/**/*.test.ts`) is not a path claim, and calling
        # it a dead reference is a FALSE finding in a paid report - on my #1 prospect's 9-line file a
        # naive regex did exactly that. Templates, globs and bare extensions are skipped.
        if TEMPLATE.search(tgt) or "*" in tgt or tgt.startswith(".") and "/" not in tgt:
            continue
        checked += 1
        cands = [os.path.join(root, tgt), os.path.join(base, tgt),
                 os.path.join(root, tgt.lstrip("./"))]
        if not any(os.path.exists(c) for c in cands):
            ln = txt[:m.start()].count("\n") + 1
            missing.append((ln, tgt))
    return missing, checked


def secrets(txt):
    """Return SHAPES only. The value itself is never printed - publishing a customer's real token
    inside a public sample audit would be a worse incident than the defect we are selling."""
    return sorted({m.group(0)[:6] + "…" + m.group(0)[-3:] for m in SECRETISH.finditer(txt)})


def probe(p, root):
    txt = read(p)
    rel = os.path.relpath(p, root)
    lines = txt.splitlines()
    d = {"path": rel, "kind": "SKILL.md" if SKILL.match(os.path.basename(p)) else "instruction",
         "last_touch": "",
         "bytes": len(txt.encode()), "words": len(txt.split()), "lines": len(lines),
         "headings": [f"{len(h[1])}#{h[2].strip()}" for h in map(HEAD.match, lines) if h],
         "long_lines": [i + 1 for i, l in enumerate(lines) if len(l) > 200],
         "commands": commands(txt)[:25],
         "fenced_blocks": len(FENCE.findall(txt)),
         "dead_refs": [], "refs_checked": 0, "secretish": [],
         "doc_not_runnable": [], "runnable_not_doc": [], "stack": [],
         "inline_cmds": len(re.findall(r"`[^`]{3,60}`", txt)),
         "code_blocks": txt.count("```") // 2,
         "verdict_words": bool(re.search(r"\b(exit code|fail|pass|success|green|must pass)\b", txt, re.I)),
         "negatives": len(NEG.findall(txt)), "timing": len(TIME.findall(txt)),
         "env_secrets": bool(re.search(r"\b(env|\.env|secret|token|api[_ -]?key|credential)", txt, re.I)),
         "branch_pr": bool(re.search(r"\b(branch|pull request|PR|commit|merge)\b", txt, re.I)),
         "points_elsewhere": bool(re.search(r"\.(md|yaml|yml|json)\b", txt)),
         "fence_imbalance": txt.count("```") % 2 != 0}
    d["dead_refs"], d["refs_checked"] = resolve_refs(txt, root, d["path"])
    d["secretish"] = secrets(txt)
    d["doc_not_runnable"], d["runnable_not_doc"], d["stack"] = drift(txt, root, d["path"])
    # FIXTURES ARE NOT DEFECTS. This is the exact mistake that inflated my first report on Tony's own
    # repo: a test fixture is invalid ON PURPOSE, and reporting it as a problem is how an auditor
    # loses the room. They are counted, listed separately, and excluded from the finding totals.
    d["fixture"] = bool(FIXTURE.search(d["path"].replace(os.sep, "/")))
    # STALENESS: not "when was this file last edited" (harmless) but "has the code it describes moved
    # since I was last told the truth about it". That is the drift an agent silently absorbs.
    git = GIT_()
    self_ts = git.last_touch(d["path"])
    d["last_touch"] = datetime.datetime.utcfromtimestamp(self_ts).strftime("%Y-%m-%d") if self_ts else "unknown"
    stale = []
    for _ln, ref in d["dead_refs"]:
        pass
    for m in REF.finditer(txt):
        tgt = m.group(1)
        if TEMPLATE.search(tgt) or "*" in tgt:
            continue
        if any(os.path.exists(os.path.join(root, c)) for c in (tgt, os.path.join(os.path.dirname(d["path"]), tgt))):
            rts = git.last_touch(tgt)
            if self_ts and rts and rts > self_ts:
                stale.append((tgt, datetime.datetime.utcfromtimestamp(rts).strftime("%Y-%m-%d")))
    d["stale_refs"] = sorted(set(stale))
    d["repo_last"] = (datetime.datetime.utcfromtimestamp(git.repo_last()).strftime("%Y-%m-%d")
                      if git.repo_last() else "unknown")
    return d, txt


MANAGERS = ("npm", "pnpm", "bun", "yarn")


def norm(c):
    """Fold `<manager> run <script>` to one canonical form so a repo whose file says `bun run build`
    and a package.json defining `build` are recognised as the SAME command. Without this, one script
    appeared as three 'runnable but undocumented' entries (npm/pnpm/bun prefixes) - noise that would
    bury the only real finding in the list."""
    parts = c.split()
    if len(parts) >= 3 and parts[0] in MANAGERS and parts[1] == "run":
        return f"run {parts[2]}"
    if len(parts) >= 2 and parts[0] in MANAGERS and parts[1] != "run":
        return f"{parts[0]} {parts[1]}"
    return c


_CTX = {}


def set_context(git):
    """probe() needs the repo's git history; passing it explicitly everywhere would mean changing
    every call site, and a module global that is never set is exactly the bug that bit me when
    make-report.py imported probe() directly. So: set it, or build it lazily - never read None."""
    _CTX["git"] = git


def GIT_():
    g = _CTX.get("git")
    if g is None:
        raise RuntimeError("call set_context(Git(root)) before probe()")
    return g


class Git:
    """Run git ONCE per repo and answer from memory.

    Shelling out per file is not laziness, it is a product constraint: my earlier per-file API calls
    hit GitHub's rate limit on Tony's own account, and a repo like shopsys has 62 instruction files.
    An audit that costs 62 subprocess calls per repo does not scale to the price we are charging.
    """

    def __init__(self, root):
        self.root = root
        self._log = None

    def log(self):
        if self._log is None:
            try:
                self._log = subprocess.run(["git", "-C", self.root, "log", "--name-only",
                                           "--pretty=format:C\t%at", "--no-merges"],
                                           capture_output=True, text=True, timeout=60).stdout
            except Exception:
                self._log = ""
        return self._log

    def touched(self, path):
        return {int(t) for t in re.findall(r"^C\t(\d+)$", self.log(), re.M)
                if path in self.log()} if False else None

    def last_touch(self, path):
        """Last commit unix-time touching `path` (exact match, so quotes/globs are not miscounted)."""
        latest = 0
        for block in re.split(r"^C\t", self.log(), flags=re.M):
            lines = block.strip().splitlines()
            if not lines:
                continue
            ts = int(lines[0]) if lines[0].isdigit() else 0
            if any(l.strip() == path for l in lines[1:]):
                latest = max(latest, ts)
        return latest

    def repo_last(self):
        ts = re.findall(r"^C\t(\d+)$", self.log(), re.M)
        return max(map(int, ts)) if ts else 0


def reality(root):
    """Ground truth for what can actually be RUN: package.json scripts, Makefile targets, and the
    tech declared by manifest files. Comparing an instruction file's commands to this is how drift is
    caught. It replaces grepping English words like 'lint': a repo can have a lint script and no
    mention of the word, or the reverse, and my first sample audit made exactly that mistake."""
    scripts, targets, tech = set(), set(), set()
    try:
        pj = json.load(open(os.path.join(root, "package.json")))
        scripts |= {f"run {k}" for k in (pj.get("scripts") or {})}
        tech.add("node/package.json")
    except Exception:
        pass
    for mf in ("Makefile", "makefile", "GNUmakefile"):
        fp = os.path.join(root, mf)
        if os.path.exists(fp):
            targets |= {m.group(1) for m in re.finditer(r"^([A-Za-z0-9_.-]+):", open(fp).read(), re.M)}
            tech.add("make")
    for f, name in (("go.mod", "go"), ("Cargo.toml", "rust/cargo"), ("pyproject.toml", "python"),
                    ("pom.xml", "java/maven"), ("build.gradle", "java/gradle"), ("composer.json", "php/composer"),
                    ("Gemfile", "ruby/bundler")):
        if os.path.exists(os.path.join(root, f)):
            tech.add(name)
    return scripts, targets, tech


def root_commands(root):
    """Commands named in the repo's ROOT instruction file (the one an agent reads first). A skill file
    deeper in the tree is not obliged to repeat `npm run lint`, so reporting root-level scripts as
    'undocumented' for every one of 31 nested files is noise - and noise is what makes a customer stop
    reading the findings that ARE real. Measured on Patrity/skills, my first version printed the same
    six scripts 31 times.
    """
    for cand in ("AGENTS.md", "CLAUDE.md", ".cursorrules", ".github/copilot-instructions.md"):
        p = os.path.join(root, cand)
        if os.path.exists(p):
            try:
                return {norm(c) for c in commands(open(p, encoding="utf-8").read())}
            except Exception:
                return set()
    return set()


def drift(txt, root, rel):
    scripts, targets, tech = reality(root)
    documented = {norm(c) for c in commands(txt)}
    doc_not_runnable, runnable_not_doc = [], []
    for c in sorted(documented):
        if c.startswith("run ") and c not in scripts:
            doc_not_runnable.append(c)
        elif c.startswith("make ") and c[5:] not in targets:
            doc_not_runnable.append(c)
    coverage = documented | root_commands(root) if rel != "AGENTS.md" else documented
    for s in sorted(scripts):
        if re.search(r"(test|build|lint|check|verify|typecheck)", s, re.I) and s not in coverage:
            runnable_not_doc.append(s)
    # `runnable_not_doc` is the finding an agent feels most: a command that exists, matters
    # (test/build/lint), and is nowhere in the instructions. It is a MEASUREMENT, not an opinion -
    # which is exactly the kind of finding the report should lead with.
    return doc_not_runnable, sorted(set(runnable_not_doc))[:12], sorted(tech)


def cross(files: dict, exclude_fixtures=True):
    """Contradictions across files in ONE repo - the class of defect no single-file linter can see."""
    out = []
    test_cmds = {}
    for d, _txt in files.values():
        for c in d["commands"]:
            if d.get("fixture"):
                continue
            if re.search(r"\b(test|pytest|vitest|jest|rspec|phpunit|cargo test|go test|make test)\b", c, re.I):
                test_cmds.setdefault(c, []).append(d["path"])
    for c, where in test_cmds.items():
        if len(where) > 1:
            # Not a contradiction - two files may legitimately document the same command. Calling a
            # duplicate a "conflict" in a paid report would be the kind of inflated finding that
            # makes a maintainer stop trusting the rest of it.
            out.append(f"DUPLICATED command `{c}` documented in {len(where)} files: {', '.join(where)} "
                       f"(harmless today, but the copies drift)")
    real = [(d["words"], d["path"]) for d, _ in files.values() if not (exclude_fixtures and d.get("fixture"))]
    sizes = sorted(real or [(d["words"], d["path"]) for d, _ in files.values()], reverse=True)
    if len(sizes) > 1 and sizes[0][0] > 3 * sizes[-1][0]:
        out.append(f"IMBALANCE `{sizes[0][1]}` ({sizes[0][0]} words) vs `{sizes[-1][1]}` "
                   f"({sizes[-1][0]} words): an agent given both will follow the longer one unless told otherwise")
    return out


def main(root):
    set_context(Git(root))
    paths = walk(root)
    if not paths:
        print("NO INSTRUCTION FILES FOUND (note: absence of files, not absence of problems)")
        return
    # separate fixtures so the finding counts below describe the SHIPPED code, not the test corpus
    fixture_paths = [p for p in paths if FIXTURE.search(os.path.relpath(p, root).replace(os.sep, "/"))]
    files = {p: probe(p, root) for p in paths}
    print(f"# mechanical evidence: {len(paths)} instruction file(s)\n")
    for p, (d, txt) in files.items():
        print(f"## {d['path']}  [{d['kind']}]")
        print(f"   size: {d['words']} words / {d['lines']} lines / {d['bytes']} bytes")
        print(f"   sections ({len(d['headings'])}): {'; '.join(d['headings'][:14]) or 'NONE - flat file, no headings'}")
        print(f"   commands found ({len(d['commands'])}): {', '.join(d['commands'][:12]) or 'NONE'}")
        print(f"   verification language: {'yes' if d['verdict_words'] else 'NO - tells how to run, not how to know it worked'}")
        print(f"   prohibitions/gotchas: {d['negatives']} marker(s)" + ("  <-- highest-value section, absent" if d['negatives'] == 0 else ""))
        print(f"   cost/time guidance: {d['timing']} mention(s)")
        print(f"   env/secrets mentioned: {'yes' if d['env_secrets'] else 'no'}")
        print(f"   branch/PR workflow: {'yes' if d['branch_pr'] else 'no'}")
        print(f"   defers to other files: {'yes' if d['points_elsewhere'] else 'no'}")
        if d['long_lines']:
            print(f"   lines >200 chars: {len(d['long_lines'])} (at {', '.join(map(str, d['long_lines'][:6]))})")
        if d["refs_checked"]:
            print(f"   file references it names: {d['refs_checked']} checked, "
              f"{len(d['dead_refs'])} unresolved by the probe (NOT auto-failures: build outputs like "
              f"`dist/cli.js`, filenames quoted inside prose, and files under a subdir all look dead "
              f"to a path probe and must be confirmed by hand before they are reported)")
            for ln, tgt in d["dead_refs"][:6]:
                print(f"     UNRESOLVED line {ln} -> {tgt}  (checked repo root and this file's dir)")
        if d["doc_not_runnable"] or d["runnable_not_doc"]:
            for c in d["doc_not_runnable"][:5]:
                print(f"   DOCUMENTED BUT NOT RUNNABLE: `{c}` - no such script/target in the repo")
            if d["runnable_not_doc"]:
                print(f"   RUNNABLE BUT UNDOCUMENTED (agent cannot know these exist): "
                      f"{', '.join('`'+s+'`' for s in d['runnable_not_doc'][:8])}")
        if d["stack"]:
            print(f"   stack detected from manifest files: {', '.join(d['stack'])}")
        if d["fixture"]:
            print("   [FIXTURE - excluded from finding totals, invalid on purpose]")
        print(f"   last commit touching this file: {d['last_touch']}   (repo last commit: {d['repo_last']})")
        if d["stale_refs"]:
            print(f"   STALE: the code this file describes changed AFTER the file was last edited:")
            for tgt, when in d["stale_refs"][:8]:
                print(f"     STALE REF {tgt} changed {when} - after this file was touched {d['last_touch']}")
        if d["secretish"]:
            print(f"   secret-shaped strings: {len(d['secretish'])} (values redacted: "
                  f"{', '.join(d['secretish'][:4])})")
        if d['fence_imbalance']:
            print("   UNCLOSED CODE FENCE - everything after it can be swallowed as code by a renderer/parser")
        print()
    if fixture_paths:
        print("\n## Fixtures excluded from the finding totals: " + str(len(fixture_paths)))
        for p in fixture_paths:
            print(f"   - {os.path.relpath(p, root)}  (invalid on purpose; audited separately on request)")
    for line in cross(files):
        print("* " + line)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
