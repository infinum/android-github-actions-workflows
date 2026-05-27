#!/usr/bin/env python3
"""
Parse the textual output of `gradle :a:dependencies :b:dependencies ... :buildEnvironment`
into a JSON file that categorize-alert.py can consume.

Output shape:
{
  "projects": {
    ":app": {
      "configurations": {
        "debugCompileClasspath": {
          "allDeps": [
            {"id": "group:artifact:version",
             "topLevels": ["group:artifact:version", ...]}
          ]
        }
      }
    }
  },
  "buildscriptClasspath": {
    ":": { "allDeps": [...] }
  }
}

`topLevels` lists the depth-0 ancestors that brought this dep into the
configuration. A dep is "directly declared" iff its own `group:artifact` is one
of the `group:artifact`s in its `topLevels`. Chains routed through `project ...`
nodes contribute nothing — those entries have no Maven coord to attribute. If a
dep is only reachable via project chains, its `topLevels` ends up empty.
"""

import argparse
import json
import re
import sys
from typing import Optional


TASK_HEADER = re.compile(r"^> Task (\S+)(?:\s+.*)?$")
TREE_LINE = re.compile(r"^([ |+\\]+)--- (.+)$")
# A configuration header line: name [- description] [(n)]
# Examples we need to match:
#   debugCompileClasspath - Compile classpath for compilation 'debug'.
#   testImplementation - Implementation only dependencies for source set 'test'. (n)
#   classpath
#   _agp_internal_devDebugAndroidTest_kspClasspath
#   _internal-unified-test-platform-android-test-plugin-host-emulator-control - ...
# Hyphenated config names exist in AGP internals; allow '-' in the identifier.
CONFIG_HEADER = re.compile(r"^([_a-zA-Z][a-zA-Z0-9_-]*)(?:\s*-\s+.*)?(?:\s*\(n\))?$")
LEGEND_LINE = re.compile(r"^\([cnr*]\)\s")
SKIP_STATUSES = {"UP-TO-DATE", "SKIPPED", "NO-SOURCE"}


def parse_dep_coord(content: str) -> Optional[str]:
    """
    Convert a tree-line dependency description into 'group:artifact:version',
    using the resolved version when Gradle reports one. Returns None for
    project deps, dependency constraints, and unparseable lines.
    """
    content = content.strip()
    if content.startswith("project "):
        return None
    if content.endswith("(c)"):
        return None
    for marker in (" (*)", " (n)"):
        if content.endswith(marker):
            content = content[: -len(marker)].rstrip()
    if " -> " in content:
        coord_part, resolved = content.rsplit(" -> ", 1)
        resolved = resolved.strip()
        bits = coord_part.split(":")
        if len(bits) < 2:
            return None
        return f"{bits[0]}:{bits[1]}:{resolved}"
    bits = content.split(":")
    if len(bits) < 3:
        return None
    return ":".join(bits[:3])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, help="Path to gradle dependencies text output")
    ap.add_argument("--output", required=True, help="Path to write dep-config-map JSON")
    args = ap.parse_args()

    result: dict = {"projects": {}, "buildscriptClasspath": {}}

    current_task: Optional[str] = None
    in_buildscript = False
    current_project: Optional[str] = None
    current_config: Optional[str] = None
    current_deps: dict = {}  # coord -> set of versioned top-level coords
    current_top_level: Optional[str] = None

    def commit_config():
        nonlocal current_config, current_deps, current_top_level
        if current_config is None:
            return
        if in_buildscript:
            bucket = result["buildscriptClasspath"].setdefault(
                current_project or ":", {"allDeps": []}
            )
        else:
            proj = result["projects"].setdefault(
                current_project or ":", {"configurations": {}}
            )
            bucket = proj["configurations"].setdefault(
                current_config, {"allDeps": []}
            )
        existing_by_id = {d["id"]: d for d in bucket["allDeps"]}
        for coord, tls in current_deps.items():
            if coord in existing_by_id:
                merged = set(existing_by_id[coord]["topLevels"]) | tls
                existing_by_id[coord]["topLevels"] = sorted(merged)
            else:
                entry = {"id": coord, "topLevels": sorted(tls)}
                bucket["allDeps"].append(entry)
                existing_by_id[coord] = entry
        current_config = None
        current_deps = {}
        current_top_level = None

    with open(args.input) as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")
            stripped = line.strip()

            m = TASK_HEADER.match(line)
            if m:
                commit_config()
                task = m.group(1)
                # Pull the status suffix back out of the full line, if any.
                rest = line[len("> Task ") + len(task):].strip()
                status = rest.split()[0] if rest else None

                current_config = None
                current_deps = {}
                current_top_level = None

                if status in SKIP_STATUSES:
                    current_task = None
                    continue

                if task.endswith(":dependencies"):
                    current_task = task
                    current_project = task[: -len(":dependencies")] or ":"
                    in_buildscript = False
                elif task == ":buildEnvironment":
                    current_task = task
                    current_project = ":"
                    in_buildscript = True
                else:
                    current_task = None
                continue

            if current_task is None:
                continue

            # Section delimiters and headers we don't care about
            if (
                stripped.startswith("-------")
                or stripped.startswith("Project '")
                or stripped.startswith("Root project '")
                or stripped.startswith("Location:")
                or stripped.startswith("A web-based")
                or stripped.startswith("Deprecated Gradle features")
            ):
                continue
            if stripped.startswith("BUILD "):
                commit_config()
                current_task = None
                continue
            if LEGEND_LINE.match(stripped):
                continue

            if not stripped:
                commit_config()
                continue

            tm = TREE_LINE.match(line)
            if tm:
                if current_config is None:
                    continue
                prefix = tm.group(1)
                depth = (len(prefix) - 1) // 5
                coord = parse_dep_coord(tm.group(2))

                if depth == 0:
                    # New top-level entry; reset attribution. Project deps and
                    # constraints set this to None (no Maven coord to attribute).
                    current_top_level = coord

                if coord is None:
                    continue

                bucket = current_deps.setdefault(coord, set())
                if current_top_level is not None:
                    bucket.add(current_top_level)
                continue

            if stripped == "No dependencies":
                # Configuration exists but empty; will be filtered later.
                continue

            cm = CONFIG_HEADER.match(stripped)
            if cm:
                commit_config()
                current_config = cm.group(1)
                current_deps = {}
                current_top_level = None
                continue
            # Anything else: silently skip.

    commit_config()

    # Drop configurations with no resolved deps to keep the JSON lean.
    for proj_path in list(result["projects"].keys()):
        proj = result["projects"][proj_path]
        proj["configurations"] = {
            k: v for k, v in proj["configurations"].items() if v["allDeps"]
        }
        if not proj["configurations"]:
            del result["projects"][proj_path]
    for proj_path in list(result["buildscriptClasspath"].keys()):
        if not result["buildscriptClasspath"][proj_path]["allDeps"]:
            del result["buildscriptClasspath"][proj_path]

    with open(args.output, "w") as out:
        json.dump(result, out)

    num_configs = sum(len(p["configurations"]) for p in result["projects"].values())
    print(
        f"Parsed {num_configs} configurations across {len(result['projects'])} projects; "
        f"buildscript classpath entries: {len(result['buildscriptClasspath'])}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
