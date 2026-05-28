"""Unit tests for categorize-alert.py — exercises the 12 cases from the handoff
plus the helper functions, by calling `categorize_occurrence` directly."""
import io
import json
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _helpers import load  # noqa: E402


cat = load("categorize-alert.py")


DEFAULT_CONFIG = {
    "trusted_sources": [
        "com.android.*",
        "androidx.*",
        "org.jetbrains.kotlin.*",
        "org.jetbrains.*",
        "com.google.*",
    ],
    "trusted_source_scopes": ["buildscript"],
    "production_build_types": ["release"],
    "production_variants": [],
    "currency_threshold": "latest",
}


def occ(config, via, top_levels):
    return {"project": ":app", "config": config, "via": via, "top_levels": top_levels}


def merge_config(**over):
    out = {k: list(v) if isinstance(v, list) else v for k, v in DEFAULT_CONFIG.items()}
    out.update(over)
    return out


class TestHelpers(unittest.TestCase):
    def test_matches_trusted_pattern_wildcard(self):
        patterns = ["com.android.*"]
        self.assertTrue(cat.matches_trusted_pattern("com.android:foo", patterns))
        self.assertTrue(cat.matches_trusted_pattern("com.android.tools.build:gradle", patterns))
        self.assertFalse(cat.matches_trusted_pattern("com.androidx:foo", patterns))
        self.assertFalse(cat.matches_trusted_pattern("com.other:foo", patterns))

    def test_matches_trusted_pattern_exact(self):
        patterns = ["com.example:special"]
        self.assertTrue(cat.matches_trusted_pattern("com.example:special", patterns))
        self.assertFalse(cat.matches_trusted_pattern("com.example:other", patterns))

    def test_extract_classpath_variant(self):
        self.assertEqual(cat.extract_classpath_variant("debugCompileClasspath"), "debug")
        self.assertEqual(cat.extract_classpath_variant("devReleaseRuntimeClasspath"), "devRelease")
        self.assertEqual(cat.extract_classpath_variant("CompileClasspath"), "")
        self.assertIsNone(cat.extract_classpath_variant("implementation"))

    def test_extract_codegen_variant(self):
        self.assertEqual(cat.extract_codegen_variant("kapt"), ("kapt", ""))
        self.assertEqual(cat.extract_codegen_variant("kspDevDebug"), ("ksp", "DevDebug"))
        self.assertEqual(cat.extract_codegen_variant("hiltAnnotationProcessorProdRelease"),
                         ("hiltAnnotationProcessor", "ProdRelease"))
        # AGP internal beats prefix-based detection
        self.assertEqual(cat.extract_codegen_variant("_agp_internal_devDebug_kspClasspath"),
                         ("agp_internal", "devDebug"))
        self.assertIsNone(cat.extract_codegen_variant("implementation"))

    def test_is_production_variant_build_types(self):
        self.assertTrue(cat.is_production_variant("release", ["release"], []))
        self.assertTrue(cat.is_production_variant("devRelease", ["release"], []))
        self.assertTrue(cat.is_production_variant("prodRelease", ["release"], []))
        self.assertFalse(cat.is_production_variant("debug", ["release"], []))
        self.assertFalse(cat.is_production_variant("devDebug", ["release"], []))
        self.assertTrue(cat.is_production_variant("", ["release"], []))  # Java main source set

    def test_is_production_variant_explicit_override(self):
        self.assertTrue(cat.is_production_variant("special", ["release"], ["special"]))
        self.assertFalse(cat.is_production_variant("release", ["release"], ["special"]))


class TestHandoffTwelveCases(unittest.TestCase):
    """The 12 confirmed test cases from the handoff."""

    def test_case01_guava_via_current_agp_only_dismiss(self):
        # buildscript transitive of AGP only, AGP current
        o = occ("classpath", "buildscript", ["com.android.tools.build:gradle:8.7.1"])
        currency = {"com.android.tools.build:gradle:8.7.1": {"current": True, "latest": "8.7.1"}}
        verdict, reason = cat.categorize_occurrence(o, "com.google.guava:guava", DEFAULT_CONFIG, currency)
        self.assertEqual(verdict, "safe", reason)

    def test_case02_guava_via_stale_agp_only_skip(self):
        o = occ("classpath", "buildscript", ["com.android.tools.build:gradle:8.7.1"])
        currency = {"com.android.tools.build:gradle:8.7.1": {"current": False, "latest": "8.8.0"}}
        verdict, reason = cat.categorize_occurrence(o, "com.google.guava:guava", DEFAULT_CONFIG, currency)
        self.assertEqual(verdict, "unsafe", reason)
        self.assertIn("not current", reason)

    def test_case03_guava_via_untrusted_only_skip(self):
        o = occ("classpath", "buildscript", ["co.infinum.foo:plugin:1.0"])
        currency = {}
        verdict, reason = cat.categorize_occurrence(o, "com.google.guava:guava", DEFAULT_CONFIG, currency)
        self.assertEqual(verdict, "unsafe", reason)
        self.assertIn("non-trusted", reason)

    def test_case04_guava_via_current_agp_and_untrusted_skip(self):
        o = occ("classpath", "buildscript", [
            "com.android.tools.build:gradle:8.7.1",
            "co.infinum.foo:plugin:1.0",
        ])
        currency = {"com.android.tools.build:gradle:8.7.1": {"current": True, "latest": "8.7.1"}}
        verdict, reason = cat.categorize_occurrence(o, "com.google.guava:guava", DEFAULT_CONFIG, currency)
        self.assertEqual(verdict, "unsafe", reason)

    def test_case05_guava_via_current_agp_and_current_hilt_dismiss(self):
        o = occ("classpath", "buildscript", [
            "com.android.tools.build:gradle:8.7.1",
            "com.google.dagger:hilt-android-gradle-plugin:2.50.0",
        ])
        currency = {
            "com.android.tools.build:gradle:8.7.1": {"current": True, "latest": "8.7.1"},
            "com.google.dagger:hilt-android-gradle-plugin:2.50.0": {"current": True, "latest": "2.50.0"},
        }
        verdict, reason = cat.categorize_occurrence(o, "com.google.guava:guava", DEFAULT_CONFIG, currency)
        self.assertEqual(verdict, "safe", reason)

    def test_case06_guava_via_current_agp_and_stale_hilt_skip(self):
        o = occ("classpath", "buildscript", [
            "com.android.tools.build:gradle:8.7.1",
            "com.google.dagger:hilt-android-gradle-plugin:2.50.0",
        ])
        currency = {
            "com.android.tools.build:gradle:8.7.1": {"current": True, "latest": "8.7.1"},
            "com.google.dagger:hilt-android-gradle-plugin:2.50.0": {"current": False, "latest": "2.51.0"},
        }
        verdict, reason = cat.categorize_occurrence(o, "com.google.guava:guava", DEFAULT_CONFIG, currency)
        self.assertEqual(verdict, "unsafe", reason)
        self.assertIn("not current", reason)

    def test_case07_agp_directly_declared_skip(self):
        o = occ("classpath", "buildscript", ["com.android.tools.build:gradle:8.7.1"])
        currency = {"com.android.tools.build:gradle:8.7.1": {"current": True, "latest": "8.7.1"}}
        verdict, reason = cat.categorize_occurrence(
            o, "com.android.tools.build:gradle", DEFAULT_CONFIG, currency)
        self.assertEqual(verdict, "unsafe", reason)
        self.assertIn("directly declared", reason)

    def test_case08_hilt_plugin_directly_declared_skip(self):
        o = occ("classpath", "buildscript", ["com.google.dagger:hilt-android-gradle-plugin:2.50.0"])
        currency = {"com.google.dagger:hilt-android-gradle-plugin:2.50.0": {"current": True, "latest": "2.50.0"}}
        verdict, reason = cat.categorize_occurrence(
            o, "com.google.dagger:hilt-android-gradle-plugin", DEFAULT_CONFIG, currency)
        self.assertEqual(verdict, "unsafe", reason)
        self.assertIn("directly declared", reason)

    def test_case09_production_occ_overrides_safe_buildscript_skip(self):
        # The categorizer is per-occurrence; aggregation happens in main(). This test
        # confirms that a production occurrence (with default scopes) is unsafe even
        # if the buildscript occurrence would be safe.
        prod_occ = occ("prodReleaseRuntimeClasspath", "project",
                       ["androidx.appcompat:appcompat:1.6.1"])
        verdict, _ = cat.categorize_occurrence(
            prod_occ, "com.google.guava:guava", DEFAULT_CONFIG, {})
        self.assertEqual(verdict, "unsafe")  # production not in trusted_source_scopes

    def test_case10_hamcrest_via_junit_in_testimpl_dismiss(self):
        o = occ("testImplementation", "project", ["junit:junit:4.13"])
        verdict, reason = cat.categorize_occurrence(
            o, "org.hamcrest:hamcrest-core", DEFAULT_CONFIG, {})
        self.assertEqual(verdict, "safe", reason)
        self.assertIn("test", reason)

    def test_case11_non_production_variant_dismiss(self):
        o = occ("devDebugCompileClasspath", "project", ["some.dep:thing:1.0"])
        verdict, reason = cat.categorize_occurrence(o, "vuln:vuln", DEFAULT_CONFIG, {})
        self.assertEqual(verdict, "safe", reason)
        self.assertIn("non-production", reason)

    def test_case12_production_via_trusted_default_scopes_skip(self):
        # Default scopes only include buildscript; production occurrences are unsafe.
        o = occ("prodReleaseRuntimeClasspath", "project", ["androidx.appcompat:appcompat:1.6.1"])
        currency = {"androidx.appcompat:appcompat:1.6.1": {"current": True, "latest": "1.6.1"}}
        verdict, reason = cat.categorize_occurrence(o, "com.google.guava:guava", DEFAULT_CONFIG, currency)
        self.assertEqual(verdict, "unsafe", reason)
        self.assertIn("production", reason)


class TestProductionScopeOptIn(unittest.TestCase):
    def test_production_with_scope_and_trusted_current_dismiss(self):
        cfg = merge_config(trusted_source_scopes=["buildscript", "production"])
        o = occ("prodReleaseRuntimeClasspath", "project", ["androidx.appcompat:appcompat:1.6.1"])
        currency = {"androidx.appcompat:appcompat:1.6.1": {"current": True, "latest": "1.6.1"}}
        verdict, reason = cat.categorize_occurrence(o, "com.google.guava:guava", cfg, currency)
        self.assertEqual(verdict, "safe", reason)

    def test_codegen_for_production_default_unsafe(self):
        o = occ("kaptProdRelease", "project", ["com.google.dagger:hilt-android:2.50.0"])
        verdict, _ = cat.categorize_occurrence(o, "com.google.guava:guava", DEFAULT_CONFIG, {})
        self.assertEqual(verdict, "unsafe")

    def test_codegen_for_non_production_safe(self):
        o = occ("kaptDevDebug", "project", ["com.google.dagger:hilt-android:2.50.0"])
        verdict, reason = cat.categorize_occurrence(o, "com.google.guava:guava", DEFAULT_CONFIG, {})
        self.assertEqual(verdict, "safe", reason)


class TestNoAttribution(unittest.TestCase):
    def test_empty_top_levels_in_trusted_rule_is_unsafe(self):
        o = occ("classpath", "buildscript", [])
        verdict, reason = cat.categorize_occurrence(
            o, "com.google.guava:guava", DEFAULT_CONFIG, {})
        self.assertEqual(verdict, "unsafe", reason)
        self.assertIn("no top-level", reason)


# --- End-to-end tests of main() for the unreachable verdict --------------

def _run_main(dep_map: dict, alert: dict, config: dict = None, currency: dict = None) -> str:
    """Invoke categorize-alert.py's main() with the given inputs; returns stdout."""
    if config is None:
        config = DEFAULT_CONFIG
    if currency is None:
        currency = {}
    tmpdir = tempfile.mkdtemp()
    dep_map_path = pathlib.Path(tmpdir) / "dep.json"
    config_path = pathlib.Path(tmpdir) / "config.json"
    currency_path = pathlib.Path(tmpdir) / "currency.json"
    dep_map_path.write_text(json.dumps(dep_map))
    config_path.write_text(json.dumps(config))
    currency_path.write_text(json.dumps(currency))

    argv_saved = sys.argv
    stdin_saved = sys.stdin
    sys.argv = [
        "categorize",
        "--dep-map", str(dep_map_path),
        "--config", str(config_path),
        "--currency-map", str(currency_path),
    ]
    sys.stdin = io.StringIO(json.dumps(alert))
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            cat.main()
    finally:
        sys.argv = argv_saved
        sys.stdin = stdin_saved
    return buf.getvalue()


def _maven_alert(pkg_name: str) -> dict:
    return {
        "number": 1,
        "dependency": {"package": {"ecosystem": "maven", "name": pkg_name}},
        "security_advisory": {"severity": "low"},
    }


def _project_entry(build: str, reachable: bool, configs: dict) -> dict:
    return {"build": build, "reachable": reachable, "configurations": configs}


class TestUnreachableVerdict(unittest.TestCase):
    def test_dismiss_when_only_in_unreachable_modules(self):
        # The vuln coord appears only in `:foreign:sample`, marked unreachable.
        dep_map = {
            "projects": {
                ":foreign:sample": _project_entry(
                    "foreign", False,
                    {"debugCompileClasspath": {"allDeps": [
                        {"id": "com.vuln:vuln:1.0", "topLevels": ["com.vuln:vuln:1.0"]}
                    ]}}
                ),
            },
            "buildscriptClasspath": {},
        }
        out = _run_main(dep_map, _maven_alert("com.vuln:vuln"))
        self.assertTrue(out.startswith("dismiss\t"), out)
        self.assertIn("unreachable", out.lower())
        self.assertIn(":foreign:sample", out)

    def test_skip_when_present_in_a_reachable_production_classpath(self):
        # Same vuln also appears in a reachable production runtime classpath —
        # should fall back to the existing categorizer verdict (skip).
        dep_map = {
            "projects": {
                ":app": _project_entry(
                    "root", True,
                    {"releaseRuntimeClasspath": {"allDeps": [
                        {"id": "com.vuln:vuln:1.0", "topLevels": ["com.vuln:vuln:1.0"]}
                    ]}}
                ),
                ":foreign:sample": _project_entry(
                    "foreign", False,
                    {"debugCompileClasspath": {"allDeps": [
                        {"id": "com.vuln:vuln:1.0", "topLevels": ["com.vuln:vuln:1.0"]}
                    ]}}
                ),
            },
            "buildscriptClasspath": {},
        }
        out = _run_main(dep_map, _maven_alert("com.vuln:vuln"))
        self.assertTrue(out.startswith("skip\t"), out)
        # Reason should mention the reachable production occurrence, not the sample.
        self.assertIn(":app", out)
        self.assertNotIn(":foreign:sample", out)

    def test_dismiss_with_count_when_mixed_reachable_safe_and_unreachable(self):
        # Reachable occurrence is in a safe (test) configuration; unreachable
        # occurrence elsewhere. Should dismiss based on reachable safe verdict
        # and note the ignored unreachable count.
        dep_map = {
            "projects": {
                ":app": _project_entry(
                    "root", True,
                    {"testImplementation": {"allDeps": [
                        {"id": "com.vuln:vuln:1.0", "topLevels": ["junit:junit:4.13"]}
                    ]}}
                ),
                ":foreign:sample": _project_entry(
                    "foreign", False,
                    {"debugCompileClasspath": {"allDeps": [
                        {"id": "com.vuln:vuln:1.0", "topLevels": ["com.vuln:vuln:1.0"]}
                    ]}}
                ),
            },
            "buildscriptClasspath": {},
        }
        out = _run_main(dep_map, _maven_alert("com.vuln:vuln"))
        self.assertTrue(out.startswith("dismiss\t"), out)
        self.assertIn("unreachable", out.lower())
        self.assertIn("ignored", out.lower())

    def test_dismiss_dedupes_module_list(self):
        # Same vuln in two configs of the same unreachable module — the verdict
        # should list the module once, not twice.
        dep_map = {
            "projects": {
                ":foreign:sample": _project_entry(
                    "foreign", False,
                    {
                        "debugCompileClasspath": {"allDeps": [
                            {"id": "com.vuln:vuln:1.0",
                             "topLevels": ["com.vuln:vuln:1.0"]}
                        ]},
                        "debugRuntimeClasspath": {"allDeps": [
                            {"id": "com.vuln:vuln:1.0",
                             "topLevels": ["com.vuln:vuln:1.0"]}
                        ]},
                    },
                ),
            },
            "buildscriptClasspath": {},
        }
        out = _run_main(dep_map, _maven_alert("com.vuln:vuln"))
        self.assertTrue(out.startswith("dismiss\t"), out)
        # :foreign:sample appears exactly once in the reason text
        self.assertEqual(out.count(":foreign:sample"), 1, out)


if __name__ == "__main__":
    unittest.main()
