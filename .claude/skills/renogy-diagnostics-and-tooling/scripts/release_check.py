#!/usr/bin/env python3
"""release_check.py — release consistency checks for ha-renogy-gateway.

Enforces the repo's release rule (CLAUDE.md): every version bump in
manifest.json needs a matching CHANGELOG.md entry, committed before the tag.
Read-only: only `git -C <repo> tag --list` is run. Pure stdlib, Python 3.10+.

Usage:
    python3 release_check.py <path-to-ha-renogy-gateway>

Checks:
    1. custom_components/*/manifest.json parses and has a version.
    2. hacs.json parses as JSON.
    3. CHANGELOG.md has a `## [<manifest version>]` heading.
    4. The newest CHANGELOG version >= the newest git tag (tags are vX.Y.Z).
    5. WARN if the manifest version is already tagged — the normal steady
       state right AFTER a release, but if you are preparing a release it
       means you forgot to bump the version.

Exit codes: 0 = all pass (warnings allowed), 1 = a check failed, 2 = bad usage.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

_HEADING = re.compile(r"^##\s*\[(\d+\.\d+\.\d+)\]", re.MULTILINE)
_TAG = re.compile(r"^v(\d+\.\d+\.\d+)$")

failures = 0
warnings = 0


def report(status: str, msg: str) -> None:
    global failures, warnings
    if status == "FAIL":
        failures += 1
    elif status == "WARN":
        warnings += 1
    print(f"{status:4s}  {msg}")


def vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.split("."))


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    repo = Path(sys.argv[1])
    if not repo.is_dir():
        print(f"ERROR: {repo} is not a directory", file=sys.stderr)
        return 2

    # 1. manifest.json
    manifests = sorted(repo.glob("custom_components/*/manifest.json"))
    version: str | None = None
    if not manifests:
        report("FAIL", "no custom_components/*/manifest.json found")
    else:
        try:
            manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
            version = manifest.get("version")
            if version and re.fullmatch(r"\d+\.\d+\.\d+", version):
                report("PASS", f"manifest.json parses; version {version}")
            else:
                report("FAIL", f"manifest.json version missing/malformed: {version!r}")
                version = None
        except json.JSONDecodeError as err:
            report("FAIL", f"manifest.json invalid JSON: {err}")

    # 2. hacs.json
    hacs = repo / "hacs.json"
    if hacs.is_file():
        try:
            json.loads(hacs.read_text(encoding="utf-8"))
            report("PASS", "hacs.json parses")
        except json.JSONDecodeError as err:
            report("FAIL", f"hacs.json invalid JSON: {err}")
    else:
        report("WARN", "hacs.json not found")

    # 3. changelog heading for manifest version
    changelog = repo / "CHANGELOG.md"
    cl_versions: list[str] = []
    if not changelog.is_file():
        report("FAIL", "CHANGELOG.md not found")
    else:
        cl_versions = _HEADING.findall(changelog.read_text(encoding="utf-8"))
        if not cl_versions:
            report("FAIL", "CHANGELOG.md has no '## [x.y.z]' headings")
        elif version and version in cl_versions:
            report("PASS", f"CHANGELOG.md has an entry for {version}")
        elif version:
            report(
                "FAIL",
                f"CHANGELOG.md has NO entry for manifest version {version} "
                "(repo rule: changelog before tag)",
            )

    # 4/5. git tags
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "tag", "--list"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as err:
        report("WARN", f"could not list git tags ({err}); tag checks skipped")
        out = ""

    tags = sorted(
        (m.group(1) for t in out.split() if (m := _TAG.match(t))), key=vtuple
    )
    if tags:
        latest_tag = tags[-1]
        if cl_versions:
            latest_cl = max(cl_versions, key=vtuple)
            if vtuple(latest_cl) >= vtuple(latest_tag):
                report(
                    "PASS",
                    f"newest changelog entry {latest_cl} >= newest tag v{latest_tag}",
                )
            else:
                report(
                    "FAIL",
                    f"newest changelog entry {latest_cl} is OLDER than newest "
                    f"tag v{latest_tag} — a tagged release has no changelog entry",
                )
        if version and version in tags:
            report(
                "WARN",
                f"manifest version {version} is already tagged (v{version}). "
                "Fine post-release; if preparing a release, bump the version.",
            )
        elif version:
            report("PASS", f"manifest version {version} not yet tagged (ready to release)")
    else:
        report("WARN", "no vX.Y.Z git tags found; tag checks skipped")

    print(f"\nresult: {failures} failed, {warnings} warning(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
