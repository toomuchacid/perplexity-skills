#!/usr/bin/env python3
"""
validate_skill.py — SKILL.md validator for Perplexity Computer skills.

Validates SKILL.md files against the Agent Skills specification
(https://agentskills.io/specification), Perplexity Computer upload
constraints, and description-quality heuristics from Perplexity's
engineering guide ("Designing, Refining, and Maintaining Agent Skills").

Exit codes:
    0  all checks passed (warnings allowed unless --strict)
    1  one or more ERROR-severity findings (or warnings in --strict mode)
    2  usage error / unreadable input

Usage:
    python validate_skill.py path/to/SKILL.md
    python validate_skill.py path/to/skill-dir
    python validate_skill.py path/to/skills-root --recursive
    python validate_skill.py SKILL.md --strict --json report.json --tools-file tools.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

NAME_MAX = 64
DESC_MAX = 1024
COMPAT_MAX = 500
UPLOAD_MAX_BYTES = 10 * 1024 * 1024          # Perplexity Computer upload limit
BODY_LINE_RECOMMENDED_MAX = 500              # spec: keep SKILL.md under 500 lines
DESC_WORD_RECOMMENDED_MAX = 50               # Perplexity guide: target <= 50 words
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

SPEC_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
EXTENSION_FIELDS = {"depends", "disable-model-invocation"}  # Perplexity `depends:` + common client extensions

ERROR, WARN, INFO = "ERROR", "WARNING", "INFO"

# Tool names vary between agent implementations; treat unknowns as WARNING and
# maintain this registry (or pass --tools-file tools.json with a JSON list).
DEFAULT_KNOWN_TOOLS = {
    "load_skill", "search", "web_search", "fetch_url", "browse",
    "code_interpreter", "execute_python", "run_command", "bash", "Bash",
    "read_file", "write_file", "list_files", "create_file", "Read", "Write", "Grep", "Glob",
}


def find(check_id, severity, message):
    return {"check": check_id, "severity": severity, "message": message}


def coerce_scalar(val):
    v = val.strip()
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    low = v.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "~", ""):
        return None
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def mini_yaml_load(text):
    """Fallback parser for simple frontmatter when PyYAML is unavailable.
    Handles flat `key: value`, one-level nested maps, and `- item` lists."""
    data, lines, i = {}, text.split("\n"), 0
    while i < len(lines):
        raw = lines[i]; i += 1
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        if raw[0] in (" ", "\t"):
            raise ValueError(f"unexpected indentation at line {i}: {raw!r}")
        if ":" not in raw:
            raise ValueError(f"cannot parse line {i}: {raw!r}")
        key, _, val = raw.partition(":")
        key, val = key.strip(), val.strip()
        if val:
            data[key] = coerce_scalar(val)
            continue
        nested_map, nested_list = {}, []
        while i < len(lines) and lines[i].strip() and lines[i][0] in (" ", "\t"):
            sub = lines[i].strip(); i += 1
            if sub.startswith("- "):
                nested_list.append(coerce_scalar(sub[2:]))
            elif ":" in sub:
                k2, _, v2 = sub.partition(":")
                nested_map[k2.strip()] = coerce_scalar(v2)
            else:
                raise ValueError(f"cannot parse nested line {i}: {sub!r}")
        if nested_map and nested_list:
            raise ValueError(f"mixed map/list under key {key!r}")
        data[key] = nested_list if nested_list else (nested_map if nested_map else None)
    return data


def load_yaml(text):
    try:
        import yaml
        return yaml.safe_load(text), None
    except ImportError:
        try:
            return mini_yaml_load(text), "PyYAML not installed; used limited fallback parser (install pyyaml for full YAML support)"
        except ValueError as e:
            return None, f"YAML parse error (fallback parser): {e}"
    except Exception as e:
        return None, f"YAML parse error: {e}"


def extract_frontmatter(text):
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, text, "file must begin with a '---' frontmatter delimiter on line 1"
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1:]), None
    return None, text, "no closing '---' frontmatter delimiter found"


def base_tool(token):
    return token.split("(")[0].strip()


def validate_file(path, known_tools, check_dir_name=True):
    f = []
    path = Path(path)
    if not path.exists():
        return [find("F000", ERROR, f"path does not exist: {path}")], None
    if path.is_dir():
        candidate = path / "SKILL.md"
        if candidate.exists():
            path = candidate
        else:
            return [find("F001", ERROR, f"no SKILL.md in directory {path} (expected {candidate}); use --recursive to scan a skills root")], None
    if not path.is_file():
        return [find("F001", ERROR, f"not a file: {path}")], None

    size = path.stat().st_size
    if size == 0:
        return [find("F002", ERROR, "file is empty")], None
    if size > UPLOAD_MAX_BYTES:
        f.append(find("F003", ERROR, f"file is {size} bytes; Perplexity Computer upload limit is 10 MB"))
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        return [find("F004", ERROR, f"file is not valid UTF-8: {e}")], None

    fm_text, body, err = extract_frontmatter(text)
    if err:
        f.append(find("Y001", ERROR, err))
        return f, None
    if not fm_text.strip():
        f.append(find("Y002", ERROR, "frontmatter block is empty; 'name' and 'description' are required"))
        return f, None

    data, yaml_warn = load_yaml(fm_text)
    if yaml_warn and data is None:
        f.append(find("Y003", ERROR, yaml_warn))
        return f, None
    if yaml_warn:
        f.append(find("Y003", WARN, yaml_warn))
    if not isinstance(data, dict):
        f.append(find("Y004", ERROR, f"frontmatter must be a YAML mapping, got {type(data).__name__}"))
        return f, None

    for key in data:
        if key not in SPEC_FIELDS and key not in EXTENSION_FIELDS:
            f.append(find("Y005", WARN, f"non-standard frontmatter field {key!r}; spec fields are {sorted(SPEC_FIELDS)} — confirm your client supports it"))

    # --- name ---
    name = data.get("name")
    if name is None:
        f.append(find("N001", ERROR, "missing required field 'name'"))
    elif not isinstance(name, str):
        f.append(find("N002", ERROR, f"'name' must be a string, got {type(name).__name__} ({name!r}); quote it if needed"))
    else:
        if not name:
            f.append(find("N001", ERROR, "'name' is empty"))
        if len(name) > NAME_MAX:
            f.append(find("N003", ERROR, f"'name' is {len(name)} chars; max is {NAME_MAX}"))
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
            f.append(find("N004", ERROR, f"'name' {name!r} is invalid: {', '.join(detail) or 'format'}"))
        if check_dir_name and path.name == "SKILL.md" and path.parent.name not in ("", "."):
            if name != path.parent.name:
                f.append(find("N005", ERROR, f"'name' {name!r} must exactly match parent directory {path.parent.name!r}"))
        if path.name != "SKILL.md":
            f.append(find("N006", INFO, f"file is named {path.name!r}, not 'SKILL.md'; direct .md upload is allowed in Computer, but a skill directory must use SKILL.md"))

    # --- description ---
    desc = data.get("description")
    if desc is None:
        f.append(find("D001", ERROR, "missing required field 'description'"))
    elif not isinstance(desc, str):
        f.append(find("D002", ERROR, f"'description' must be a string, got {type(desc).__name__}"))
    else:
        if not desc.strip():
            f.append(find("D001", ERROR, "'description' is empty"))
        if len(desc) > DESC_MAX:
            f.append(find("D003", ERROR, f"'description' is {len(desc)} chars; max is {DESC_MAX}"))
        words = len(desc.split())
        if words > DESC_WORD_RECOMMENDED_MAX:
            f.append(find("D004", WARN, f"'description' is {words} words; Perplexity recommends <= {DESC_WORD_RECOMMENDED_MAX} (index costs ~100 tokens/skill in every session)"))
        if 0 < len(desc.strip()) < 20:
            f.append(find("D005", WARN, "'description' is very short (<20 chars); thin descriptions route unreliably"))
        low = desc.lower()
        if not any(p in low for p in ("use when", "load when", "use for", "use this")):
            f.append(find("D006", INFO, "description has no trigger phrase ('Use when...'/'Load when...'); Perplexity treats the description as a routing trigger, not documentation"))

    # --- allowed-tools ---
    tools = data.get("allowed-tools")
    if tools is not None:
        tokens = []
        if isinstance(tools, str):
            if not tools.strip():
                f.append(find("T001", WARN, "'allowed-tools' is an empty string; omit the field instead"))
            tokens = tools.split()
        elif isinstance(tools, list):
            f.append(find("T002", WARN, "'allowed-tools' is a YAML list; the spec defines a space-separated string — normalize for cross-client compatibility"))
            tokens = [str(t) for t in tools]
        else:
            f.append(find("T001", ERROR, f"'allowed-tools' must be a space-separated string, got {type(tools).__name__}"))
        for tok in tokens:
            bt = base_tool(tok)
            if not bt:
                f.append(find("T003", WARN, f"empty tool token in 'allowed-tools': {tok!r}"))
            elif bt not in known_tools:
                f.append(find("T004", WARN, f"tool {bt!r} not in known-tools registry; verify it matches a tool Perplexity Computer actually exposes (update DEFAULT_KNOWN_TOOLS or pass --tools-file)"))

    # --- optional fields ---
    compat = data.get("compatibility")
    if compat is not None:
        if not isinstance(compat, str):
            f.append(find("O001", ERROR, f"'compatibility' must be a string, got {type(compat).__name__}"))
        elif len(compat) > COMPAT_MAX:
            f.append(find("O002", ERROR, f"'compatibility' is {len(compat)} chars; max is {COMPAT_MAX}"))
    meta = data.get("metadata")
    if meta is not None:
        if not isinstance(meta, dict):
            f.append(find("O003", ERROR, f"'metadata' must be a map of string keys to string values, got {type(meta).__name__}"))
        else:
            for k, v in meta.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    f.append(find("O004", WARN, f"metadata entry {k!r}: {v!r} is not a string:string pair"))
    lic = data.get("license")
    if lic is not None and not isinstance(lic, str):
        f.append(find("O005", WARN, f"'license' should be a string, got {type(lic).__name__}"))

    # --- body ---
    body_lines = body.strip().split("\n") if body.strip() else []
    if not body.strip():
        f.append(find("B001", WARN, "markdown body is empty; the skill has no instructions to load"))
    elif len(body_lines) > BODY_LINE_RECOMMENDED_MAX:
        f.append(find("B002", WARN, f"body is {len(body_lines)} lines; spec recommends < {BODY_LINE_RECOMMENDED_MAX} — move detail to references/ for progressive disclosure"))
    est_tokens = len(body) // 4
    if est_tokens > 5000:
        f.append(find("B003", WARN, f"body is ~{est_tokens} tokens; Perplexity recommends <= 5000 once loaded"))

    return f, {"name": name if isinstance(name, str) else None, "path": str(path)}


def collect_targets(path, recursive):
    path = Path(path)
    if path.is_file():
        return [path]
    if (path / "SKILL.md").exists():
        return [path / "SKILL.md"]
    if recursive:
        found = sorted(path.rglob("SKILL.md"))
        return found
    return []


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate SKILL.md files for Perplexity Computer / Agent Skills spec.")
    ap.add_argument("paths", nargs="+", help="SKILL.md file(s), skill directory, or skills root")
    ap.add_argument("--recursive", action="store_true", help="scan directories recursively for SKILL.md files")
    ap.add_argument("--strict", action="store_true", help="treat WARNINGs as failures (exit 1)")
    ap.add_argument("--json", metavar="REPORT", help="write a JSON report to this path")
    ap.add_argument("--tools-file", help="JSON file with a list of known tool names for allowed-tools checks")
    ap.add_argument("--no-dir-check", action="store_true", help="skip the name-must-match-directory check")
    args = ap.parse_args(argv)

    known_tools = set(DEFAULT_KNOWN_TOOLS)
    if args.tools_file:
        try:
            known_tools = set(json.loads(Path(args.tools_file).read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as e:
            print(f"error: cannot load --tools-file: {e}", file=sys.stderr)
            return 2

    report, any_error, any_warn = {}, False, False
    for raw in args.paths:
        targets = collect_targets(raw, args.recursive)
        if not targets:
            print(f"error: no SKILL.md found at {raw} (use --recursive to scan a skills root)", file=sys.stderr)
            report[str(raw)] = [find("F001", ERROR, "no SKILL.md found")]
            any_error = True
            continue
        for t in targets:
            findings, _meta = validate_file(t, known_tools, check_dir_name=not args.no_dir_check)
            report[str(t)] = findings
            for x in findings:
                any_error |= x["severity"] == ERROR
                any_warn |= x["severity"] == WARN

    for target, findings in report.items():
        print(f"\n=== {target} ===")
        if not findings:
            print("  PASS — no findings")
        for x in sorted(findings, key=lambda r: (r["severity"] != ERROR, r["severity"] != WARN)):
            print(f"  [{x['severity']:7}] {x['check']}: {x['message']}")

    n_err = sum(1 for fs in report.values() for x in fs if x["severity"] == ERROR)
    n_warn = sum(1 for fs in report.values() for x in fs if x["severity"] == WARN)
    n_info = sum(1 for fs in report.values() for x in fs if x["severity"] == INFO)
    print(f"\nSummary: {len(report)} file(s), {n_err} error(s), {n_warn} warning(s), {n_info} info")

    if args.json:
        Path(args.json).write_text(json.dumps({"summary": {"files": len(report), "errors": n_err, "warnings": n_warn, "info": n_info}, "results": report}, indent=2), encoding="utf-8")

    if any_error or (args.strict and any_warn):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
