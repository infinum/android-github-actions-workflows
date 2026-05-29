#!/usr/bin/env python3
"""
Parse the textual output of `gradle :a:dependencies :b:dependencies ... :buildEnvironment`
into a JSON file that categorize-alert.py can consume.

Composite-build aware: when `--included-builds` is supplied, every project is
tagged with the build it belongs to and the parser computes reachability —
a BFS over intra-build and cross-build project references, seeded with the
root build's modules. Projects that no root-build module can reach (directly
or transitively) are tagged `reachable: false` so the categorizer can dismiss
alerts that only surface in those modules.

Output shape:
{
  "projects": {
    ":app": {
      "build": "root",
      "reachable": true,
      "configurations": {
        "debugCompileClasspath": {
          "allDeps": [
            {"id": "group:artifact:version",
             "topLevels": ["group:artifact:version", ...]}
          ]
        }
      }
    },
    ":android-common-android:sample": {
      "build": "android-common-android",
      "reachable": false,
      "configurations": {...}
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
# Hyphenated config names exist in AGP internals; allow '-' in the identifier.
CONFIG_HEADER = re.compile(r"^([_a-zA-Z][a-zA-Z0-9_-]*)(?:\s*-\s+.*)?(?:\s*\(n\))?$")
LEGEND_LINE = re.compile(r"^\([cnr*]\)\s")
SKIP_STATUSES = {"UP-TO-DATE", "SKIPPED", "NO-SOURCE"}

# Matches `project :path` and `... -> project :path` for cross-project references
# in the dep tree. Captures the colon-prefixed project path.
PROJECT_REF = re.compile(r"(?:^|-> )project\s+(:[^\s()]+)")


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
        # Distinguish substituted coord (-> project :X) from version conflict resolution.
        if "-> project " in content:
            return None
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


def parse_project_refs(content: str) -> list:
    """Return any `:path` project references mentioned in the tree-line content.
    Captures both `project :app` (intra-build) and `... -> project :build:m`
    (substituted cross-build)."""
    cleaned = content.strip()
    for marker in (" (*)", " (n)", " (c)"):
        if cleaned.endswith(marker):
            cleaned = cleaned[: -len(marker)].rstrip()
    return [m.group(1) for m in PROJECT_REF.finditer(cleaned)]


def load_lines(path: Optional[str]) -> list:
    if not path:
        return []
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(line)
    return out


def derive_build(project_path: str, included_builds: list, root_name: str) -> str:
    """`included_builds` are like `[':android-common-android', ':kotlin-plugins']`.
    Longest-prefix match wins (in case a build name is a prefix of another)."""
    for build in sorted(included_builds, key=len, reverse=True):
        if project_path == build or project_path.startswith(build + ":"):
            return build.lstrip(":")
    return root_name


def compute_reachability(known_projects: set, project_refs: dict,
                         included_builds: list, root_name: str) -> set:
    """BFS from every root-build project, following project references. Returns
    the set of reachable project paths. Root projects are always reachable."""
    seeds = {p for p in known_projects
             if derive_build(p, included_builds, root_name) == root_name}
    reachable = set(seeds)
    queue = list(seeds)
    while queue:
        p = queue.pop()
        for ref in project_refs.get(p, ()):
            if ref not in reachable:
                reachable.add(ref)
                queue.append(ref)
    return reachable


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, help="Path to gradle dependencies text output")
    ap.add_argument("--output", required=True, help="Path to write dep-config-map JSON")
    ap.add_argument(
        "--included-builds", required=False,
        help="Path to a text file listing included-build names (one per line, "
             "with leading `:`, e.g. `:android-common-android`). Optional; omit "
             "for single-build projects.",
    )
    ap.add_argument(
        "--root-build-name", default="root",
        help="Display name for the root build (used in JSON `build` tags). "
             "Default: `root`.",
    )
    args = ap.parse_args()

    included_builds = load_lines(args.included_builds)
    root_name = args.root_build_name

    result: dict = {"projects": {}, "buildscriptClasspath": {}}
    project_refs: dict = {}  # project_path -> set of referenced project paths
    known_projects: set = set()  # every project we've seen a :dependencies task for

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
                    if current_project not in (":", None):
                        known_projects.add(current_project)
                        # Ensure project entry exists for tagging even if all
                        # configurations end up empty.
                        result["projects"].setdefault(
                            current_project, {"configurations": {}}
                        )
                elif task == ":buildEnvironment":
                    current_task = task
                    current_project = ":"
                    in_buildscript = True
                else:
                    current_task = None
                continue

            if current_task is None:
                continue

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
                content = tm.group(2)
                coord = parse_dep_coord(content)

                # Track project references for reachability — independent of
                # depth, and only for project-config trees (not buildscript).
                if not in_buildscript and current_project is not None:
                    for ref in parse_project_refs(content):
                        project_refs.setdefault(current_project, set()).add(ref)

                if depth == 0:
                    current_top_level = coord

                if coord is None:
                    continue

                bucket = current_deps.setdefault(coord, set())
                if current_top_level is not None:
                    bucket.add(current_top_level)
                continue

            if stripped == "No dependencies":
                continue

            cm = CONFIG_HEADER.match(stripped)
            if cm:
                commit_config()
                current_config = cm.group(1)
                current_deps = {}
                current_top_level = None
                continue

    commit_config()

    # Reachability is BFS from root-build projects over project_refs edges.
    # `known_projects` is every project we ran `:dependencies` on; that's the
    # universe we want to mark. Refs to projects we did NOT analyze (rare —
    # happens if a module appears as a dep but not in modules.txt) get marked
    # reachable but don't end up in `result["projects"]`.
    if included_builds:
        reachable = compute_reachability(
            known_projects, project_refs, included_builds, root_name
        )
    else:
        # Single-build project: every project is trivially reachable.
        reachable = set(known_projects)

    # Drop configurations with no resolved deps, but keep the project entry
    # itself for tagging (so unreachable empty modules still appear).
    for proj_path in list(result["projects"].keys()):
        proj = result["projects"][proj_path]
        proj["configurations"] = {
            k: v for k, v in proj.get("configurations", {}).items() if v["allDeps"]
        }
        proj["build"] = derive_build(proj_path, included_builds, root_name)
        proj["reachable"] = proj_path in reachable if included_builds else True

    for proj_path in list(result["buildscriptClasspath"].keys()):
        if not result["buildscriptClasspath"][proj_path]["allDeps"]:
            del result["buildscriptClasspath"][proj_path]

    with open(args.output, "w") as out:
        json.dump(result, out)

    num_configs = sum(len(p.get("configurations", {})) for p in result["projects"].values())
    num_unreachable = sum(1 for p in result["projects"].values() if not p["reachable"])
    print(
        f"Parsed {num_configs} configurations across {len(result['projects'])} "
        f"projects ({num_unreachable} unreachable); "
        f"buildscript classpath entries: {len(result['buildscriptClasspath'])}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
