#!/usr/bin/env python3
"""replay.py <repo_dir> [--timeout 20] - actually RUN the safe commands an instruction file asserts.

Why this exists: everything else in the audit is reading. Reading can be hallucinated, so a reader can
always be accused of it (rightly, sometimes). Running one command produces a fact neither of us invented,
which is the only kind of finding that cannot be argued with at $69.

Safety is the whole design, not a footnote:
  * ONLY commands whose first token is a known runner AND that match a safe suffix (--version/--help/
    --check/dry-run/lint/typecheck/test:*) are eligible. Anything that could deploy, migrate, push,
    install, or wipe a database is skipped. This matters on the prospect I am pitching: his own
    AGENTS.md says `test:integration` DELETES ROWS and needs approval first. A tool that ran that in a
    stranger's checkout would have been a worse incident than the defect we are selling.
  * Never `npm install` / no network installs, ever: a repo's postinstall can execute arbitrary code on
    my box, and a sandboxed agent on the operator's account should not be executing strangers' scripts.
  * Hard timeout per command, output capped, cwd pinned to the repo, no shell expansion of user text
    (shlex), and no command runs unless it was extracted from an instruction FILE.
"""
import json, os, re, shlex, subprocess, sys

# Read-only by intent, not by name: `cargo fmt --check` and `cargo clippy` inspect without writing,
# whereas bare `cargo fmt` REWRITES files. So mutating subcommands are listed separately and win.
MUTATE = re.compile(r"(^cargo fmt$|\bfmt\b(?! --check)|--write|--save-default|-i\b|--fix\b|:fix|--write-undefined|prettier(?! --check))")
# A test/lint runner is read-only in the sense that matters (it does not deploy, migrate, or rewrite),
# so it is matched by RUNNER TOKEN, not by flag spelling - the first version required a flag and so
# skipped `pytest -q`, `cargo test --workspace`, `dotnet test`, `swift test`, `phpunit` and
# `npx vitest run`, i.e. it refused to check almost every real project's most important command.
TESTY = re.compile(r"(\btest\b|\bvitest\b|\bjest\b|\bpytest\b|\bphpunit\b|\brspec\b|vitest run|cargo test|go test|swift test|dotnet test)", re.I)
SAFE = re.compile(r"(--version|-V|--help|-h|--check|:check|dry-?run|lint|typecheck|--noEmit|clippy"
                  r"|fmt --check|format:check|\btsc\b|\bknip\b|\beslint\b|\bmypy\b|\bruff\b|r?i?pyright|tsc$)", re.I)
# `integration` / `e2e` / `smoke` are here because an integration suite may touch a REAL database or
# a live browser. My #1 prospect's own AGENTS.md says exactly that about `bun run test:integration`:
# "the server tests delete rows in their setup; confirm an isolated disposable database and obtain
# approval first". My first version classified that command as safe because it merely said "test" -
# the single most dangerous bug in this file, and the reason the safety list is a whitelist.
AVOID = re.compile(r"(deploy|migrate|push|publish|release|reset|seed|clean|rollback|db:|install|postinstall"
                   r"|start$|dev$|watch|--fix\b|:fix|generate|integration|\be2e\b|playwright|selenium|live|prod)", re.I)
DANGEROUS_CHARS = re.compile(r"[<>|&;$`*?]|&&|\|\|")
RUNNER = re.compile(r"^(npm|pnpm|yarn|bun|bunx|npx|make|cargo|go|pytest|vitest|jest|eslint|tsc|dotnet|gradle|mvn|composer|bundle|rspec|phpunit|docker|python[3]?|ruby|swift|./)")


def eligible(cmd):
    if MUTATE.search(cmd):
        return False, "rewrites files (mutating subcommand)"
    if not RUNNER.match(cmd) or DANGEROUS_CHARS.search(cmd):
        return False, "not a plain safe command"
    if AVOID.search(cmd):
        return False, "could mutate state, deploy, or run forever"
    if not (SAFE.search(cmd) or TESTY.search(cmd)):
        return False, "not a recognised read-only check or test runner"
    if " install" in cmd:
        return False, "installs dependencies (arbitrary postinstall code on my box)"
    return True, ""


def main(root, timeout=20):
    import analyze
    analyze.set_context(analyze.Git(root))
    rows = []
    seen = set()
    for p in analyze.walk(root):
        d, _txt = analyze.probe(p, root)
        if d.get("fixture"):
            continue
        for c in d["commands"]:
            if c in seen:
                continue
            seen.add(c)
            ok, why = eligible(c)
            if not ok:
                rows.append((c, "SKIPPED", why, d["path"]))
                continue
            try:
                argv = shlex.split(c)
                r = subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=timeout)
                first = (r.stdout or r.stderr).strip().splitlines()
                rows.append((c, "RAN ok" if r.returncode == 0 else f"EXIT {r.returncode}",
                             (first[0][:110] if first else "(no output)"), d["path"]))
            except subprocess.TimeoutExpired:
                # THE finding my own sample audit found by reading: a command that never exits.
                # Here it is measured, not asserted.
                rows.append((c, f"TIMEOUT >{timeout}s", "does not exit on its own - a blocking command "
                             "an agent must not be told to 'just run'", d["path"]))
            except FileNotFoundError:
                # Recorded, not hidden: "not installed on MY box" is a statement about my box, not a
                # defect in his repo. Reporting a missing binary as a finding would be exactly the
                # kind of overclaim this product is supposed to be immune to.

                rows.append((c, "BINARY MISSING", argv[0] + " not installed here", d["path"]))
            except Exception as e:
                rows.append((c, "ERROR", f"{type(e).__name__}: {e}", d["path"]))
    print(f"# replay: {len(seen)} command(s) considered, "
          f"{sum(1 for r in rows if r[1].startswith('RAN') or r[1].startswith('EXIT'))} executed\n")
    print("| command | result | first line | documented in |")
    print("|---|---|---|---|")
    for c, res, out, where in rows:
        print(f"| `{c}` | {res} | {out[:80]} | `{where}` |")
    print("\n*Not executed commands are listed as SKIPPED with the reason. An unexecuted command is not a "
          "pass, and it is never reported as one.*")


if __name__ == "__main__":
    t = 20
    if "--timeout" in sys.argv:
        t = int(sys.argv[sys.argv.index("--timeout") + 1])
    main(sys.argv[1] if len(sys.argv) > 1 else ".", t)
