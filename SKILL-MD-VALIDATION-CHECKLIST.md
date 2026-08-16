# SKILL.md Validation Checklist — Perplexity Computer

Companion to `validate_skill.py`. Severity: **BLOCKER** = must fix before upload,
**WARN** = fix unless justified, **INFO** = advisory.

Grounding: Agent Skills spec (agentskills.io/specification), Perplexity Computer
Skills help article, and Perplexity's engineering guide *Designing, Refining, and
Maintaining Agent Skills*.

---

## 1. Packaging & file hygiene

| # | Check | Severity | Auto check |
|---|-------|----------|-----------|
| 1.1 | File is named exactly `SKILL.md` inside a skill directory (bare `.md` is only acceptable for direct upload) | BLOCKER for directory skills | F-codes |
| 1.2 | File is UTF-8, non-empty | BLOCKER | F002/F004 |
| 1.3 | Upload size ≤ **10 MB** (`.zip` with SKILL.md at root, or bare `.md`) | BLOCKER | F003 |
| 1.4 | If zipped: `SKILL.md` sits at zip root, not nested in a folder | BLOCKER | manual |

## 2. YAML frontmatter syntax

| # | Check | Severity | Auto check |
|---|-------|----------|-----------|
| 2.1 | File begins with `---` on line 1, closed by a second `---` (or `...`) | BLOCKER | Y001 |
| 2.2 | Frontmatter parses as a YAML **mapping** (no tabs, no unquoted `:` in values) | BLOCKER | Y003/Y004 |
| 2.3 | Frontmatter is not empty | BLOCKER | Y002 |
| 2.4 | Only spec fields used: `name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools` — or a known extension you can justify (`depends` for Perplexity skill dependencies) | WARN | Y005 |

## 3. `name` constraints

| # | Check | Severity | Auto check |
|---|-------|----------|-----------|
| 3.1 | Present, string type, non-empty | BLOCKER | N001/N002 |
| 3.2 | **1–64 characters** | BLOCKER | N003 |
| 3.3 | Lowercase `a-z`, digits `0-9`, hyphens only — no uppercase, underscores, spaces | BLOCKER | N004 |
| 3.4 | Does not start or end with a hyphen | BLOCKER | N004 |
| 3.5 | No consecutive hyphens (`--`) | BLOCKER | N004 |
| 3.6 | **Exactly matches the parent directory name** | BLOCKER | N005 |

## 4. `description` — the routing trigger

Perplexity treats the description as a *routing trigger*, not documentation: it is
injected into the skill index (~100 tokens/skill, paid every session) and is the
only signal the model uses to decide whether to `load_skill()`.

| # | Check | Severity | Auto check |
|---|-------|----------|-----------|
| 4.1 | Present, string, non-empty | BLOCKER | D001/D002 |
| 4.2 | **≤ 1024 characters** | BLOCKER | D003 |
| 4.3 | Target **≤ 50 words** — dense and terse | WARN | D004 |
| 4.4 | Not extremely thin (≥ ~20 chars) | WARN | D005 |
| 4.5 | Contains a trigger phrase: "Use when…" / "Load when…" — says **when** to load, not just what it does | WARN | D006 |
| 4.6 | Includes 2–3 real user phrasings/keywords users actually say (e.g. "babysit", "watch CI") | WARN | eval prompts §8 |
| 4.7 | Does not overlap another skill's description boundary (off-target loads are the #1 failure mode) | WARN | eval prompts §8 |

## 5. `allowed-tools` mapping

| # | Check | Severity | Auto check |
|---|-------|----------|-----------|
| 5.1 | If present: **space-separated string**, e.g. `allowed-tools: Bash(git:*) Read` — not a YAML list (spec form; some clients accept lists, but normalize for portability) | WARN | T001/T002 |
| 5.2 | Every token maps to a tool the client actually exposes. Strip `(...)` scoping prefixes when mapping (e.g. `Bash(git:*)` → `Bash`) | WARN | T003/T004 |
| 5.3 | Principle of least privilege — list only tools the skill's instructions genuinely need | WARN | manual |
| 5.4 | Tool registry kept current: update `DEFAULT_KNOWN_TOOLS` in `validate_skill.py` or pass `--tools-file tools.json` | INFO | manual |

## 6. Optional fields

| # | Check | Severity | Auto check |
|---|-------|----------|-----------|
| 6.1 | `compatibility`: string, ≤ 500 chars; only include if the skill has real environment requirements | BLOCKER if violated | O001/O002 |
| 6.2 | `metadata`: map of string keys → string values; use reasonably unique key names | WARN | O003/O004 |
| 6.3 | `license`: short string (name or bundled file reference) | WARN | O005 |

## 7. Body / progressive disclosure

| # | Check | Severity | Auto check |
|---|-------|----------|-----------|
| 7.1 | Body is non-empty (it is the only thing the model sees after load — Perplexity strips frontmatter) | WARN | B001 |
| 7.2 | Body < 500 lines / ~5,000 tokens; move detail to `references/`, `scripts/`, `assets/` | WARN | B002/B003 |
| 7.3 | References use relative paths one level deep (`references/REFERENCE.md`) | INFO | manual |
| 7.4 | No step-by-step command railroads for things the model already knows — write intent, not shell transcripts | WARN | manual |
| 7.5 | Gotchas/negative examples present; every sentence passes "would the agent get this wrong without it?" | WARN | manual |

## 8. Automated evaluation prompts — trigger accuracy inside Perplexity Computer

Static checks cannot verify routing. Run these in a fresh Computer session per case.
Scoring: **precision** = skill loads only when it should; **recall** = it loads when
it must; **forbidden** = it never fires on adjacent-domain queries.

### Protocol

1. Upload/enable **only** the skill under test (plus controls in §8.4).
2. For each prompt: fresh session → send prompt verbatim → record whether the skill loaded (Computer shows `load_skill(name="...")` / "Using skill") and whether the output follows the skill's instructions.
3. Run the full battery **per orchestrator model** (Perplexity reports GPT vs Claude Opus vs Sonnet route Skills differently).
4. Pass bar: 5/5 positive recall, 5/5 negative precision, 0 forbidden loads, 3/3 boundary wins.

### 8.1 Positive triggers (skill SHOULD load)

| # | Prompt |
|---|--------|
| P1 | "Apply the documentation standards to this module I'm about to write." *(direct invocation)* |
| P2 | "Review this Python file — I want the docstrings and comments checked against our project conventions." |
| P3 | "Write a new module docstring for my detection pipeline following the house style." |
| P4 | "What documentation files do I need to produce for phase 2 of my project?" |
| P5 | Paraphrase of P2 in your own everyday wording (use a real phrase you have actually typed) |

### 8.2 Negative / boundary triggers (skill should NOT load)

| # | Prompt |
|---|--------|
| N1 | "Write a README.md for my repo." *(plain writing task — no conventions invoked)* |
| N2 | "Fix the bug in this function." *(code change without a documentation request)* |
| N3 | "What does this function do?" *(explanation, not documentation authoring)* |
| N4 | "Generate an API reference with Sphinx." *(adjacent doc task outside the skill's scope — adjust to your boundary)* |
| N5 | A query from your **closest neighbouring skill's** domain (fill in per your library) |

### 8.3 Judge rubric (paste output into a fresh session, or a second model)

```
You are grading whether an agent skill was routed and executed correctly.

SKILL UNDER TEST: <name>
SKILL DESCRIPTION: <description verbatim>
PROMPT GIVEN: <prompt>
EXPECTED: <LOAD | DO-NOT-LOAD>
OBSERVED BEHAVIOUR: <transcript summary: did load_skill fire? did output follow the skill body?>

Grade:
1. Routing correct? (yes/no) — did loading behaviour match EXPECTED?
2. If loaded: execution adherence (1–5) — did the output actually apply the skill's instructions?
3. If not loaded but should have: which description keywords were missing from the prompt?
4. If loaded but should not have: which description phrase over-matched?
Verdict: PASS / FAIL + one-line reason.
```

### 8.4 Contention check (action at a distance)

Adding a skill can degrade *other* skills' routing without touching them. With your
full skill library enabled, re-run each existing skill's top-2 positive prompts and
confirm no regressions.

### 8.5 Regression rule

Any change to `name` or `description` after ship **requires** re-running §8.1–§8.4
with results recorded (commit a short `evals/YYYY-MM-DD.md` alongside the skill).
Body-only gotcha additions do not require re-eval.

---

## CI usage

```bash
# validate all skills in a repo, fail the build on warnings
python validate_skill.py skills/ --recursive --strict

# JSON report for dashboards
python validate_skill.py skills/ --recursive --json report.json
```

Exit codes: `0` pass · `1` errors (or warnings in `--strict`) · `2` usage error.
