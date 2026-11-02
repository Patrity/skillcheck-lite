# Bugs that paid for themselves

- `^\.cursorrules\.md$` never matches `.cursorrules` (no extension). An auditor who cannot see a file reports
  "no instruction files found" while the customer's rules file sits in the repo.
- A command regex without a shape test harvests `/docs`, `bundles`, `going` — fake commands in a paid report.
- Normalise `npm|pnpm|bun run X` to one form or one script appears three times and buries the real finding.
- Do not report root-level scripts as "undocumented" for every nested skill file: 31 copies of the same line is
  noise, and noise costs trust in the findings that are real.
- `cargo fmt` rewrites files; `cargo fmt --check` does not. `prettier --write` is not read-only. Safety lists
  must be whitelists.
- Prose that is hard-wrapped at 80 columns is not a sentence boundary. A padding-grader that splits on newlines
  manufactures the sentences it then punishes.
