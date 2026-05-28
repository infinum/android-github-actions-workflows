#!/usr/bin/env python3
"""
Categorize a single Dependabot alert as dismissable or not under the
trusted-source model.

Reads:
  - alert JSON from stdin (one alert from the GitHub Dependabot alerts API)
  - dep-config-map JSON via --dep-map (produced by parse-gradle-deps.py)
  - dismiss-config.json via --config (trusted_sources, trusted_source_scopes,
    production_build_types, production_variants, currency_threshold)
  - trusted-currency JSON via --currency-map (produced by build-trusted-currency.py)

Writes a single tab-separated line to stdout:
  <decision>\t<reason>
where <decision> is "dismiss" or "skip". Exit code is always 0 unless inputs
are malformed.
"""
import argparse
import json
import re
import sys
from typing import Optional


CLASSPATH_SUFFIXES = ("CompileClasspath", "RuntimeClasspath")
CODEGEN_PREFIXES = (
    "hiltAnnotationProcessor",  # check before annotationProcessor
    "kotlinCompilerPluginClasspath",
    "annotationProcessor",
    "kapt",
    "ksp",
)
AGP_INTERNAL = re.compile(r"^_agp_internal_(.+)_(?:ksp|kapt)Classpath$")


def coord_of(versioned_id: str) -> str:
    parts = versioned_id.split(":")
    if len(parts) < 2:
        return versioned_id
    return f"{parts[0]}:{parts[1]}"


def matches_trusted_pattern(coord: str, patterns: list) -> bool:
    """coord is `group:artifact`. Pattern forms:
      `group.with.dots.*` matches the group exactly or any sub-group under it.
      `group:artifact` matches that exact coord.
    """
    group = coord.split(":")[0]
    for p in patterns:
        if p.endswith(".*"):
            prefix = p[:-2]
            if group == prefix or group.startswith(prefix + "."):
                return True
        elif p == coord:
            return True
    return False


def extract_classpath_variant(name: str) -> Optional[str]:
    """Returns variant prefix (possibly empty for Java main source set) when
    `name` ends with a classpath suffix; None otherwise."""
    for suffix in CLASSPATH_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return None


def extract_codegen_variant(name: str):
    """Returns (prefix_kind, variant) for codegen configs, or None. Variant ==
    '' means the unprefixed codegen (main source set)."""
    m = AGP_INTERNAL.match(name)
    if m:
        return ("agp_internal", m.group(1))
    for prefix in CODEGEN_PREFIXES:
        if name == prefix:
            return (prefix, "")
        if name.startswith(prefix):
            return (prefix, name[len(prefix):])
    return None


def is_production_variant(variant: str, prod_build_types: list, prod_variants: list) -> bool:
    # Empty variant = no flavor/build type prefix = Java main source set.
    if variant == "":
        return True
    if prod_variants:
        return variant in prod_variants
    for bt in prod_build_types:
        if variant == bt:
            return True
        if variant.endswith(bt.capitalize()):
            return True
    return False


def is_test_config(name: str) -> bool:
    if name.startswith("test"):
        return True
    if "AndroidTest" in name or "UnitTest" in name:
        return True
    return False


def apply_trusted_source_rule(occ: dict, pkg_name: str, config: dict, currency_map: dict):
    top_levels = occ.get("top_levels", [])
    if not top_levels:
        return ("unsafe", "no top-level attribution available")
    if any(coord_of(tl) == pkg_name for tl in top_levels):
        return ("unsafe", "directly declared as a top-level")

    untrusted = [tl for tl in top_levels
                 if not matches_trusted_pattern(coord_of(tl), config["trusted_sources"])]
    if untrusted:
        return (
            "unsafe",
            "brought in by non-trusted source(s): "
            + ", ".join(sorted({coord_of(tl) for tl in untrusted})),
        )

    not_current = [tl for tl in top_levels
                   if not currency_map.get(tl, {}).get("current")]
    if not_current:
        details = sorted({
            f"{coord_of(tl)} (latest: {currency_map.get(tl, {}).get('latest', 'unknown')})"
            for tl in not_current
        })
        return ("unsafe", "trusted source(s) not current: " + ", ".join(details))

    return (
        "safe",
        "all top-levels trusted+current: "
        + ", ".join(sorted({coord_of(tl) for tl in top_levels})),
    )


def categorize_occurrence(occ: dict, pkg_name: str, config: dict, currency_map: dict):
    name = occ["config"]
    via = occ.get("via", "project")
    scopes = config["trusted_source_scopes"]

    if is_test_config(name):
        return ("safe", f"test source set: {name}")

    if via == "buildscript":
        if "buildscript" in scopes:
            return apply_trusted_source_rule(occ, pkg_name, config, currency_map)
        return ("unsafe", f"buildscript classpath; trusted-source rule disabled: {name}")

    cp_variant = extract_classpath_variant(name)
    if cp_variant is not None:
        if is_production_variant(cp_variant,
                                 config["production_build_types"],
                                 config["production_variants"]):
            if "production" in scopes:
                return apply_trusted_source_rule(occ, pkg_name, config, currency_map)
            return ("unsafe", f"production classpath: {name}")
        return ("safe", f"non-production variant: {cp_variant} ({name})")

    codegen = extract_codegen_variant(name)
    if codegen is not None:
        _, variant = codegen
        if is_production_variant(variant,
                                 config["production_build_types"],
                                 config["production_variants"]):
            if "codegen-main" in scopes:
                return apply_trusted_source_rule(occ, pkg_name, config, currency_map)
            return ("unsafe", f"production codegen: {name}")
        return ("safe", f"codegen for non-production variant: {variant or '(main)'}")

    return ("safe", f"build-tooling configuration: {name}")


def find_occurrences(pkg_name: str, dep_map: dict) -> list:
    occurrences = []
    for proj_path, proj_data in dep_map.get("projects", {}).items():
        # Tags from composite-build-aware parser. Older single-build dep maps
        # don't set these; treat as root + reachable so existing behavior holds.
        build = proj_data.get("build", "root")
        reachable = proj_data.get("reachable", True)
        for config_name, config_data in proj_data.get("configurations", {}).items():
            for dep in config_data.get("allDeps", []):
                if coord_of(dep.get("id", "")) == pkg_name:
                    occurrences.append({
                        "project": proj_path,
                        "config": config_name,
                        "via": "project",
                        "build": build,
                        "reachable": reachable,
                        "top_levels": list(dep.get("topLevels", [])),
                    })
    for proj_path, bs_data in dep_map.get("buildscriptClasspath", {}).items():
        # The buildscript classpath always belongs to the root build and is
        # reachable by definition (it determines how the build itself runs).
        for dep in bs_data.get("allDeps", []):
            if coord_of(dep.get("id", "")) == pkg_name:
                occurrences.append({
                    "project": proj_path,
                    "config": "classpath",
                    "via": "buildscript",
                    "build": "root",
                    "reachable": True,
                    "top_levels": list(dep.get("topLevels", [])),
                })
    return occurrences


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dep-map", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--currency-map", required=True)
    args = parser.parse_args()

    try:
        alert = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"skip\tmalformed alert JSON: {exc}")
        sys.exit(0)

    pkg = alert.get("dependency", {}).get("package", {})
    if pkg.get("ecosystem") != "maven":
        print(f"skip\tnon-maven ecosystem: {pkg.get('ecosystem')!r}")
        return
    pkg_name = pkg.get("name", "")
    if not pkg_name:
        print("skip\tmissing dependency.package.name in alert")
        return

    with open(args.dep_map) as f:
        dep_map = json.load(f)
    with open(args.config) as f:
        config = json.load(f)
    with open(args.currency_map) as f:
        currency_map = json.load(f)

    occurrences = find_occurrences(pkg_name, dep_map)
    if not occurrences:
        print(f"skip\tno occurrence of {pkg_name} found in resolved dep graph")
        return

    # Split off occurrences in unreachable included-build modules. If every
    # occurrence is unreachable, dismiss with an explicit reason. If at least
    # one occurrence is in reachable code, the unreachable ones are ignored
    # (they can't introduce a vulnerability into the shipped APK on their own).
    reachable_occs = [o for o in occurrences if o.get("reachable", True)]
    unreachable_occs = [o for o in occurrences if not o.get("reachable", True)]

    if not reachable_occs:
        # `unreachable_occs` is occurrences of THIS package that landed in
        # unreachable modules. The listed paths are exactly the modules where
        # the vulnerable dependency lives — NOT a dump of every unreachable
        # module in the composite.
        modules = sorted({o["project"] for o in unreachable_occs})
        shown = ", ".join(modules[:6])
        more = "" if len(modules) <= 6 else f" (+{len(modules) - 6} more)"
        print(
            "dismiss\tdependency only used by unreachable included-build "
            f"module(s): {shown}{more}"
        )
        return

    verdicts = [
        categorize_occurrence(o, pkg_name, config, currency_map)
        for o in reachable_occs
    ]

    unsafe = [(o, v) for o, v in zip(reachable_occs, verdicts) if v[0] == "unsafe"]
    if unsafe:
        reasons = []
        for o, (_, reason) in unsafe[:5]:
            reasons.append(f"{o['project']}/{o['config']}: {reason}")
        more = "" if len(unsafe) <= 5 else f" (+{len(unsafe) - 5} more)"
        print(f"skip\t{'; '.join(reasons)}{more}")
        return

    safe_configs = sorted({o["config"] for o in reachable_occs})
    suffix = (
        f"; {len(unreachable_occs)} unreachable occurrence(s) ignored"
        if unreachable_occs else ""
    )
    print(
        f"dismiss\tall {len(reachable_occs)} reachable occurrence(s) safe; "
        f"configs: {', '.join(safe_configs)}{suffix}"
    )


if __name__ == "__main__":
    main()
