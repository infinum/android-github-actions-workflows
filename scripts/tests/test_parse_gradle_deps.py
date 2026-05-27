"""Unit tests for parse-gradle-deps.py — focused on topLevels attribution."""
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _helpers import load  # noqa: E402


parser = load("parse-gradle-deps.py")


FIXTURE = """\
> Task :app:dependencies

------------------------------------------------------------
Project ':app'
------------------------------------------------------------

debugCompileClasspath - Compile classpath for compilation 'debug'.
+--- com.example:lib-a:1.0
|    +--- com.example:shared:2.0
|    \\--- org.kotlin:stdlib:1.9
\\--- com.example:lib-b:1.0
     +--- com.example:shared:2.0 (*)
     \\--- org.example:other:3.0

releaseCompileClasspath - Compile classpath for compilation 'release'.
+--- project :feature
|    \\--- com.example:via-project:5.0
\\--- com.example:lib-a:1.0 (*)

testImplementation - test impl
+--- junit:junit:4.13
     \\--- org.hamcrest:hamcrest-core:1.3

_internal-unified-test-platform-android-test-plugin-host-emulator-control - A configuration to resolve the Unified Test Platform dependencies.
\\--- io.grpc:grpc-netty:1.69.1
     \\--- io.netty:netty-codec-http:4.1.110.Final

BUILD SUCCESSFUL in 1s

> Task :buildEnvironment

------------------------------------------------------------
Root project
------------------------------------------------------------

classpath
+--- com.android.tools.build:gradle:8.7.1
|    \\--- com.google.guava:guava:32.1.0
\\--- com.google.dagger:hilt-android-gradle-plugin:2.50.0
     \\--- com.google.guava:guava:31.0 -> 32.1.0

BUILD SUCCESSFUL in 1s
"""


class TestParser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp()
        in_path = pathlib.Path(cls.tmpdir) / "in.txt"
        out_path = pathlib.Path(cls.tmpdir) / "out.json"
        in_path.write_text(FIXTURE)
        import sys
        argv = sys.argv
        sys.argv = ["parse", "--input", str(in_path), "--output", str(out_path)]
        try:
            parser.main()
        finally:
            sys.argv = argv
        cls.out = json.loads(out_path.read_text())

    def _deps(self, project, config):
        return {d["id"]: d["topLevels"] for d in self.out["projects"][project]["configurations"][config]["allDeps"]}

    def _bs_deps(self, project=":"):
        return {d["id"]: d["topLevels"] for d in self.out["buildscriptClasspath"][project]["allDeps"]}

    def test_first_level_appears_in_its_own_top_levels(self):
        deps = self._deps(":app", "debugCompileClasspath")
        self.assertIn("com.example:lib-a:1.0", deps["com.example:lib-a:1.0"])
        self.assertIn("com.example:lib-b:1.0", deps["com.example:lib-b:1.0"])

    def test_transitive_does_not_appear_in_its_own_top_levels(self):
        deps = self._deps(":app", "debugCompileClasspath")
        self.assertNotIn("com.example:shared:2.0", deps["com.example:shared:2.0"])
        self.assertNotIn("org.kotlin:stdlib:1.9", deps["org.kotlin:stdlib:1.9"])

    def test_dep_brought_by_two_top_levels_lists_both(self):
        deps = self._deps(":app", "debugCompileClasspath")
        # shared:2.0 is brought in by both lib-a and lib-b
        self.assertEqual(
            sorted(deps["com.example:shared:2.0"]),
            ["com.example:lib-a:1.0", "com.example:lib-b:1.0"],
        )

    def test_project_top_level_does_not_attribute_transitives(self):
        deps = self._deps(":app", "releaseCompileClasspath")
        # via-project came in through project :feature → no Maven attribution
        self.assertEqual(deps["com.example:via-project:5.0"], [])
        # but lib-a (declared directly at depth 0) still gets itself
        self.assertEqual(deps["com.example:lib-a:1.0"], ["com.example:lib-a:1.0"])

    def test_versioned_topLevels_use_resolved_versions(self):
        deps = self._deps(":app", "debugCompileClasspath")
        # other:3.0 is direct under lib-b; ensure resolved version is used
        self.assertEqual(deps["org.example:other:3.0"], ["com.example:lib-b:1.0"])

    def test_buildscript_attributed_to_plugin_top_levels(self):
        deps = self._bs_deps()
        self.assertEqual(
            sorted(deps["com.google.guava:guava:32.1.0"]),
            sorted([
                "com.android.tools.build:gradle:8.7.1",
                "com.google.dagger:hilt-android-gradle-plugin:2.50.0",
            ]),
        )
        # Plugins themselves directly declared
        self.assertIn("com.android.tools.build:gradle:8.7.1",
                      deps["com.android.tools.build:gradle:8.7.1"])

    def test_buildscript_separated_from_project_configs(self):
        self.assertIn(":", self.out["buildscriptClasspath"])
        self.assertGreater(len(self.out["buildscriptClasspath"][":"]["allDeps"]), 0)
        # No project should have a `classpath` configuration (it belongs to buildscript)
        for proj in self.out["projects"].values():
            self.assertNotIn("classpath", proj["configurations"])

    def test_test_configurations_captured(self):
        # testImplementation is `(n)`-marked in real output but our fixture has no (n);
        # we just verify the test source set config is captured and attribution works.
        deps = self._deps(":app", "testImplementation")
        self.assertEqual(deps["junit:junit:4.13"], ["junit:junit:4.13"])
        self.assertEqual(deps["org.hamcrest:hamcrest-core:1.3"], ["junit:junit:4.13"])

    def test_hyphenated_configuration_names_are_captured(self):
        deps = self._deps(
            ":app",
            "_internal-unified-test-platform-android-test-plugin-host-emulator-control",
        )
        self.assertEqual(
            deps["io.netty:netty-codec-http:4.1.110.Final"],
            ["io.grpc:grpc-netty:1.69.1"],
        )


if __name__ == "__main__":
    unittest.main()
