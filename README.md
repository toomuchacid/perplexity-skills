# perplexity-skills

Custom skills for [Perplexity Computer](https://www.perplexity.ai/help-center/en/articles/13914413-how-to-use-computer-skills.html), plus the tooling used to validate them and evaluate their trigger accuracy.

## Contents

- `skills/` — skill directories following the [Agent Skills spec](https://agentskills.io/specification) (`SKILL.md` per directory; `name` must match the directory name)
  - `skills/skill-validator/` — the SKILL.md validation checklist packaged as a loadable Computer skill (BLOCKER/WARN/INFO checks + trigger-accuracy eval prompts)
  - `skills/documentation-standards/` — documentation conventions for coding projects (docstrings, inline comments, docs/ folder structure)
- `validate_skill.py` — SKILL.md validator: YAML frontmatter syntax, name constraints (lowercase-hyphen, max 64 chars), description limits (max 1024 chars), `allowed-tools` mapping, Perplexity Computer packaging checks (10 MB upload, zip layout)
- `SKILL-MD-VALIDATION-CHECKLIST.md` — the human-readable companion checklist cross-referenced to the validator's check IDs

## Usage

```bash
# validate every skill in the repo, failing on warnings
python validate_skill.py skills/ --recursive --strict

# JSON report
python validate_skill.py skills/ --recursive --json report.json
```

Exit codes: `0` pass · `1` errors (or warnings with `--strict`) · `2` usage error.

## Workflow

1. Write or update a skill under `skills/<skill-name>/SKILL.md`.
2. Run the validator (`--strict` before committing).
3. For any `name`/`description` change, re-run the trigger-accuracy eval battery in `SKILL-MD-VALIDATION-CHECKLIST.md` section 8 inside Perplexity Computer and record results in `evals/`.
