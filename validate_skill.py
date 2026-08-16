#!/usr/bin/env python3
"""
Skill Validation — validate_skill.py (v2)

Validates SKILL.md files against the Agent Skills spec (agentskills.io) and
Perplexity Computer upload requirements. Companion to the skill-validator
checklist (skills/skill-validator/SKILL.md); each finding carries the check
code from that document.

Key classes:
    Finding: A single check result with code, severity, message, and line.
    SkillReport: Aggregated findings for one validated file.

Dependencies:
    - PyYAML (full frontmatter validation; falls back to a shallow parser)

Exit codes:
    0  all checks passed (warnings allowed unless --strict)
    1  one or more BLOCKER findings (or warnings in --strict mode)
    2  usage error / unreadable input

Usage:
    python validate_skill.py path/to/SKILL.md
    python validate_skill.py path/to/skill-dir
    python validate_skill.py path/to/skills-root --recursive
    python validate_skill.py skills/ --recursive --strict --json report.json
    python validate_skill.py SKILL.md --tools-file tools.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False

MAX_UPLOAD_BYTES = 10 * 1024 * 1024   # Perplexity Computer hard cap
MAX_DESCRIPTION_CHARS = 1024
TARGET_DESCRIPTION_WORDS = 50
MIN_DESCRIPTION_CHARS = 20
MAX_NAME_CHARS = 64
MAX_BODY_LINES = 500
MAX_BODY_TOKENS = 5000                # estimated as chars / 4
MAX_COMPATIBILITY_CHARS = 500
MAX_LICENSE_CHARS = 100

# One regex enforcing charset, no leading/trailing hyphen, no doubles (N004)
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

SPEC_FIELDS = {"name", "description", "license", "compatibility",
               "metadata", "allowed-tools"}
KNOWN_EXTENSIONS = {"depends", "disable-model-invocation"}  # Perplexity `depends:` + client extensions

TRIGGER_PHRASES = ("use when", "load when", "use for", "use this")

# Generic cross-client defaults; override with --tools-file for your client.
DEFAULT_KNOWN_TOOLS = {
    # Claude Code
    "Bash", "Read", "Write", "Edit", "Glob", "Grep", "Task", "TodoWrite",
    "WebSearch", "WebFetch", "NotebookEdit",
    # Agent Skills runtime
    "load_skill",
    # Perplexity-flavoured names
    "search", "web_search", "fetch_url", "browse",
    "code_interpreter", "execute_python", "run_command", "bash",
    "read_file", "write_file", "list_files", "create_file",
}

BLOCKER, WARN, INFO = "BLOCKER", "WARN", "INFO"


@dataclass
class Finding:
    code: str
    severity: str  # BLOCKER | WARN | INFO
    message: str
    line: int | None = None


@dataclass
class SkillReport:
    path: str
    findings: list[Finding] = field(default_factory=list)

    def add(self, code, severity, message, line=None):
        self.findings.append(Finding(code, severity, message, line))

    @property
    def blockers(self):
        return [f for f in self.findings if f.severity == BLOCKER]

    @property
    def warnings(self):
        return [f for f in self.findings if f.severity == WARN]

    @property
    def infos(self):
        return [f for f in self.findings if f.severity == INFO]


def split_frontmatter(text: str):
    """Return (frontmatter_text, body_text, close_line) or (None, text, None)."""
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text, None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1:]), i + 1
    return None, text, None


def parse_frontmatter(fm_text: str, report: SkillReport):
    """Parse frontmatter into a dict, recording Y-codes. None on hard failure."""
    if not fm_text.strip():
        report.add("Y002", BLOCKER, "Frontmatter block is empty")
        return None
    if HAVE_YAML:
        try:
            data = yaml.safe_load(fm_text)
        except yaml.YAMLError as exc:
            report.add("Y003", BLOCKER, f"Frontmatter is not valid YAML: {exc}")
            return None
    else:
        # Shallow fallback: enough to keep validating without PyYAML, but it
        # cannot catch nested-type errors, so full validation needs PyYAML.
        report.add("Y000", INFO,
                   "PyYAML not installed; shallow frontmatter parse only")
        data = {}
        for lineno, raw in enumerate(fm_text.splitlines(), start=2):
            if "\t" in raw:
                report.add("Y003", BLOCKER,
                           "Tab character in frontmatter (YAML forbids tabs)",
                           line=lineno)
                return None
            if raw.strip() and ":" in raw:
                key, _, value = raw.partition(":")
                data[key.strip()] = value.strip().strip('"').strip("'")
    if not isinstance(data, dict):
        report.add("Y004", BLOCKER, "Frontmatter must be a YAML mapping")
        return None
    return data


def check_name(data, path, report, check_dir_name=True):
    name = data.get("name")
    if name is None:
        report.add("N001", BLOCKER, "Missing required field: name")
        return
    if not isinstance(name, str) or not name.strip():
        report.add("N002", BLOCKER,
                   f"name must be a non-empty string, got {type(name).__name__} "
                   f"({name!r}); quote it if needed")
        return
    if not 1 <= len(name) <= MAX_NAME_CHARS:
        report.add("N003", BLOCKER,
                   f"name is {len(name)} chars; must be 1-{MAX_NAME_CHARS}")
    if not NAME_RE.match(name):
        detail = []
        if any(c.isupper() for c in name):
            detail.append("uppercase letters")
        if re.search(r"[^a-zA-Z0-9-]", name):
            detail.append("illegal characters (only a-z, 0-9, '-')")
        if name.startswith("-") or name.endswith("-"):
            detail.append("leading/trailing hyphen")
        if "--" in name:
            detail.append("consecutive hyphens")
        report.add("N004", BLOCKER,
                   f"name {name!r} must be lowercase a-z, 0-9, single hyphens "
                   f"({', '.join(detail) or 'invalid format'})")
    # N005 only applies to directory-packaged skills; bare .md is upload-only.
    if check_dir_name and path.name == "SKILL.md" and path.parent.name not in ("", "."):
        if name != path.parent.name:
            report.add("N005", BLOCKER,
                       f"name '{name}' does not match parent directory "
                       f"'{path.parent.name}'")


def check_description(data, report):
    desc = data.get("description")
    if desc is None:
        report.add("D001", BLOCKER, "Missing required field: description")
        return
    if not isinstance(desc, str) or not desc.strip():
        report.add("D002", BLOCKER, "description must be a non-empty string")
        return
    if len(desc) > MAX_DESCRIPTION_CHARS:
        report.add("D003", BLOCKER,
                   f"description is {len(desc)} chars; max "
                   f"{MAX_DESCRIPTION_CHARS}")
    words = len(desc.split())
    if words > TARGET_DESCRIPTION_WORDS:
        report.add("D004", WARN,
                   f"description is {words} words; target "
                   f"<= {TARGET_DESCRIPTION_WORDS} (routing index is "
                   f"~100 tokens/skill, paid every session)")
    if len(desc) < MIN_DESCRIPTION_CHARS:
        report.add("D005", WARN,
                   f"description is very thin ({len(desc)} chars); the model "
                   f"has little signal for routing")
    if not any(p in desc.lower() for p in TRIGGER_PHRASES):
        report.add("D006", WARN,
                   "description lacks a trigger phrase ('Use when...' / "
                   "'Load when...'); it should say when to load, not just "
                   "what the skill does")


def check_allowed_tools(data, report, known_tools):
    tools = data.get("allowed-tools")
    if tools is None:
        return
    if not isinstance(tools, str):
        report.add("T001", WARN,
                   "allowed-tools should be a space-separated string, not a "
                   "YAML list (spec form; normalize for portability)")
        if isinstance(tools, list):
            tools = " ".join(str(t) for t in tools)  # still check the names
        else:
            return
    tokens = tools.split()
    if not tokens:
        report.add("T002", WARN, "allowed-tools is present but empty")
        return
    stripped_any = False
    for token in tokens:
        base = token.split("(", 1)[0]  # drop scoping e.g. Bash(git:*)
        if base != token:
            stripped_any = True
        if not base:
            report.add("T003", WARN, f"empty tool token: {token!r}")
        elif base not in known_tools:
            report.add("T003", WARN,
                       f"tool '{base}' not in known-tools registry; pass "
                       f"--tools-file if your client exposes it")
    if stripped_any:
        report.add("T004", INFO,
                   "scoping prefixes like Bash(git:*) were stripped before "
                   "registry lookup")


def check_optional_fields(data, report):
    compat = data.get("compatibility")
    if compat is not None:
        if not isinstance(compat, str):
            report.add("O001", BLOCKER, "compatibility must be a string")
        elif len(compat) > MAX_COMPATIBILITY_CHARS:
            report.add("O002", BLOCKER,
                       f"compatibility is {len(compat)} chars; max "
                       f"{MAX_COMPATIBILITY_CHARS}")
    metadata = data.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, dict) or not all(
                isinstance(k, str) and isinstance(v, str)
                for k, v in metadata.items()):
            report.add("O003", WARN,
                       "metadata must be a map of string keys to string values")
        elif not metadata:
            report.add("O004", WARN, "metadata map is empty; remove it")
    license_ = data.get("license")
    if license_ is not None and (not isinstance(license_, str)
                                 or len(license_) > MAX_LICENSE_CHARS):
        report.add("O005", WARN,
                   "license should be a short string (name or bundled file)")


def check_body(body, report):
    if not body.strip():
        report.add("B001", WARN,
                   "Body is empty; after load the body is the only thing the "
                   "model sees (Perplexity strips frontmatter)")
        return
    n_lines = len(body.splitlines())
    if n_lines >= MAX_BODY_LINES:
        report.add("B002", WARN,
                   f"Body is {n_lines} lines; keep under {MAX_BODY_LINES} and "
                   f"move detail to references/")
    est_tokens = len(body) // 4  # ~4 chars/token heuristic
    if est_tokens >= MAX_BODY_TOKENS:
        report.add("B003", WARN,
                   f"Body is ~{est_tokens} tokens; keep under "
                   f"~{MAX_BODY_TOKENS}")


def validate_file(path: Path, known_tools: set, check_dir_name=True) -> SkillReport:
    report = SkillReport(path=str(path))

    if path.name != "SKILL.md":
        report.add("F001", INFO,
                   f"Bare .md filename ({path.name!r}) is acceptable for "
                   f"direct upload only; directory-packaged skills must use "
                   f"SKILL.md")

    try:
        raw = path.read_bytes()
    except OSError as exc:
        report.add("F000", BLOCKER, f"Cannot read file: {exc}")
        return report
    if not raw:
        report.add("F004", BLOCKER, "File is empty")
        return report
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        report.add("F002", BLOCKER, f"File is not valid UTF-8: {exc}")
        return report
    if len(raw) > MAX_UPLOAD_BYTES:
        report.add("F003", BLOCKER,
                   f"File is {len(raw)} bytes; upload cap is 10 MB")

    fm_text, body, _ = split_frontmatter(text)
    if fm_text is None:
        report.add("Y001", BLOCKER,
                   "File must begin with '---' on line 1, closed by a "
                   "second '---' (or '...')", line=1)
        check_body(body, report)
        return report

    data = parse_frontmatter(fm_text, report)
    if data is None:
        check_body(body, report)
        return report

    unknown = set(data) - SPEC_FIELDS - KNOWN_EXTENSIONS
    if unknown:
        report.add("Y005", WARN,
                   f"Non-spec frontmatter fields: {sorted(unknown)}; justify "
                   f"or remove")

    check_name(data, path, report, check_dir_name=check_dir_name)
    check_description(data, report)
    check_allowed_tools(data, report, known_tools)
    check_optional_fields(data, report)
    check_body(body, report)
    return report


def collect_targets(path: Path, recursive: bool) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        return []
    direct = path / "SKILL.md"
    if direct.is_file() and not recursive:
        return [direct]
    if recursive:
        return sorted(path.rglob("SKILL.md")) or sorted(path.rglob("*.md"))
    return []


def print_report(report: SkillReport):
    print(f"\n== {report.path}")
    if not report.findings:
        print("  PASS — no findings")
        return
    order = {BLOCKER: 0, WARN: 1, INFO: 2}
    for f in sorted(report.findings, key=lambda x: order.get(x.severity, 3)):
        loc = f":{f.line}" if f.line else ""
        print(f"  [{f.severity:7}] {f.code}{loc} {f.message}")
    print(f"  -> {len(report.blockers)} blocker(s), "
          f"{len(report.warnings)} warning(s), {len(report.infos)} info")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Validate SKILL.md files for Perplexity Computer.")
    ap.add_argument("paths", nargs="+",
                    help="SKILL.md file(s), skill directory, or repo root")
    ap.add_argument("--recursive", action="store_true",
                    help="Scan for skills under the given directories")
    ap.add_argument("--strict", action="store_true",
                    help="Treat warnings as failures (exit 1)")
    ap.add_argument("--json", metavar="OUT",
                    help="Write a JSON report to OUT")
    ap.add_argument("--tools-file", metavar="JSON",
                    help="JSON list of tool names exposed by your client")
    ap.add_argument("--no-dir-check", action="store_true",
                    help="Skip the name-must-match-directory check (N005)")
    args = ap.parse_args(argv)

    known_tools = set(DEFAULT_KNOWN_TOOLS)
    if args.tools_file:
        try:
            known_tools |= set(json.loads(
                Path(args.tools_file).read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"error: cannot load tools file: {exc}", file=sys.stderr)
            return 2

    reports: list[SkillReport] = []
    for raw_arg in args.paths:
        targets = collect_targets(Path(raw_arg), args.recursive)
        if not targets:
            print(f"error: no SKILL.md found at {raw_arg} "
                  f"(try --recursive for repos)", file=sys.stderr)
            missing = SkillReport(path=raw_arg)
            missing.add("F000", BLOCKER, "no SKILL.md found at this path")
            reports.append(missing)
            continue
        for t in targets:
            reports.append(validate_file(t, known_tools,
                                         check_dir_name=not args.no_dir_check))

    for r in reports:
        print_report(r)

    n_blockers = sum(len(r.blockers) for r in reports)
    n_warnings = sum(len(r.warnings) for r in reports)
    n_infos = sum(len(r.infos) for r in reports)
    print(f"\n{len(reports)} file(s): {n_blockers} blocker(s), "
          f"{n_warnings} warning(s), {n_infos} info")

    if args.json:
        payload = {
            "files": [{
                "path": r.path,
                "findings": [vars(f) for f in r.findings],
                "blockers": len(r.blockers),
                "warnings": len(r.warnings),
                "info": len(r.infos),
            } for r in reports],
            "summary": {"files": len(reports), "blockers": n_blockers,
                        "warnings": n_warnings, "info": n_infos},
        }
        Path(args.json).write_text(json.dumps(payload, indent=2),
                                   encoding="utf-8")

    if n_blockers or (args.strict and n_warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
