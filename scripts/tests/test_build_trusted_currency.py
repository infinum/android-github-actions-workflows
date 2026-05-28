"""Unit tests for build-trusted-currency.py. Stubs urllib so tests are offline."""
import io
import json
import pathlib
import sys
import tempfile
import unittest
from contextlib import contextmanager
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _helpers import load  # noqa: E402


btc = load("build-trusted-currency.py")


METADATA_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<metadata>
  <groupId>{group}</groupId>
  <artifactId>{artifact}</artifactId>
  <versioning>
    <versions>
{versions}
    </versions>
  </versioning>
</metadata>
"""


def meta(group, artifact, versions):
    body = "\n".join(f"      <version>{v}</version>" for v in versions)
    return METADATA_TEMPLATE.format(group=group, artifact=artifact, versions=body)


class FakeResponse:
    def __init__(self, body):
        self._body = body.encode("utf-8")
        self.status = 200

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@contextmanager
def stub_urlopen(url_to_body):
    """Stub urlopen to return canned bodies for matched URL substrings; raise
    URLError for unmatched URLs (simulating 404). Also disables retry sleeps
    so tests that exercise failure paths stay fast."""
    import urllib.error
    import urllib.request

    def fake_urlopen(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        for needle, body in url_to_body.items():
            if needle in url:
                if body is None:
                    raise urllib.error.URLError(f"stub: no body for {url}")
                return FakeResponse(body)
        raise urllib.error.URLError(f"stub: unmatched url {url}")

    with mock.patch.object(urllib.request, "urlopen", fake_urlopen), \
         mock.patch.object(btc.time, "sleep", lambda _: None):
        yield


class TestLatestStableFromMetadata(unittest.TestCase):
    def test_filters_prereleases(self):
        xml = meta("g", "a", ["1.0.0", "1.1.0-alpha01", "1.0.1", "1.1.0-rc1", "0.9.0-SNAPSHOT"])
        self.assertEqual(btc.latest_stable_from_metadata(xml), "1.0.1")

    def test_picks_natural_version_sorted_last(self):
        xml = meta("g", "a", ["10.0.0", "9.99.99", "2.0.0"])
        self.assertEqual(btc.latest_stable_from_metadata(xml), "10.0.0")

    def test_all_prerelease_returns_none(self):
        xml = meta("g", "a", ["1.0.0-alpha01", "1.0.0-rc1"])
        self.assertIsNone(btc.latest_stable_from_metadata(xml))

    def test_case_insensitive_prerelease_markers(self):
        xml = meta("g", "a", ["1.0.0-ALPHA01", "1.0.0", "1.0.0-RC.1"])
        self.assertEqual(btc.latest_stable_from_metadata(xml), "1.0.0")


class TestIsCurrent(unittest.TestCase):
    def test_latest_exact(self):
        self.assertTrue(btc.is_current("8.7.1", "8.7.1", "latest"))
        self.assertFalse(btc.is_current("8.7.0", "8.7.1", "latest"))

    def test_same_minor(self):
        self.assertTrue(btc.is_current("8.7.0", "8.7.1", "same-minor"))
        self.assertTrue(btc.is_current("8.7.5", "8.7.1", "same-minor"))
        self.assertFalse(btc.is_current("8.6.0", "8.7.1", "same-minor"))
        self.assertFalse(btc.is_current("9.0.0", "8.7.1", "same-minor"))


class TestFetchMetadataFallback(unittest.TestCase):
    def test_first_repo_wins(self):
        xml = meta("com.example", "lib", ["1.0.0"])
        with stub_urlopen({"dl.google.com": xml,
                           "plugins.gradle.org": meta("c", "l", ["9.9.9"])}):
            body = btc.fetch_metadata("com.example:lib")
        self.assertIn("<version>1.0.0</version>", body)

    def test_falls_through_to_central(self):
        xml = meta("com.example", "lib", ["3.0.0"])
        with stub_urlopen({"dl.google.com": None,
                           "plugins.gradle.org": None,
                           "repo1.maven.org": xml}):
            body = btc.fetch_metadata("com.example:lib")
        self.assertIn("<version>3.0.0</version>", body)

    def test_all_fail_returns_none(self):
        with stub_urlopen({}):
            self.assertIsNone(btc.fetch_metadata("com.example:lib"))

    def test_retries_after_transient_failure(self):
        """First call raises URLError; second call returns 200. The retry
        loop should recover on the second attempt instead of giving up."""
        import urllib.request
        xml = meta("com.example", "lib", ["1.0.0"])
        calls = {"count": 0}

        def flaky_urlopen(request, timeout=None):
            calls["count"] += 1
            if calls["count"] == 1:
                import urllib.error
                raise urllib.error.URLError("simulated transient failure")
            return FakeResponse(xml)

        with mock.patch.object(urllib.request, "urlopen", flaky_urlopen), \
             mock.patch.object(btc.time, "sleep", lambda _: None):
            body = btc.fetch_metadata("com.example:lib")
        self.assertIsNotNone(body)
        self.assertIn("<version>1.0.0</version>", body)
        self.assertEqual(calls["count"], 2, "should have retried once before succeeding")

    def test_does_not_retry_on_404(self):
        """A 4xx is a genuine miss; the retry loop should short-circuit and
        move to the next repo, not waste retries on a URL that will never work."""
        import urllib.error
        import urllib.request
        xml = meta("com.example", "lib", ["1.0.0"])
        calls = {"google": 0, "plugins": 0, "central": 0}

        def fake_urlopen(request, timeout=None):
            url = request.full_url
            if "dl.google.com" in url:
                calls["google"] += 1
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            if "plugins.gradle.org" in url:
                calls["plugins"] += 1
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            calls["central"] += 1
            return FakeResponse(xml)

        with mock.patch.object(urllib.request, "urlopen", fake_urlopen), \
             mock.patch.object(btc.time, "sleep", lambda _: None):
            body = btc.fetch_metadata("com.example:lib")
        self.assertIsNotNone(body)
        # Each 404 repo should be hit exactly once (no retry on 4xx).
        self.assertEqual(calls["google"], 1)
        self.assertEqual(calls["plugins"], 1)
        self.assertEqual(calls["central"], 1)


class TestCollectRelevantTopLevels(unittest.TestCase):
    def test_extracts_top_levels_for_alerted_packages(self):
        dep_map = {
            "projects": {
                ":app": {
                    "configurations": {
                        "debugCompileClasspath": {
                            "allDeps": [
                                {"id": "com.google.guava:guava:32.0",
                                 "topLevels": ["com.example:plugin:1.0"]},
                                {"id": "other:dep:1.0", "topLevels": []},
                            ]
                        }
                    }
                }
            },
            "buildscriptClasspath": {
                ":": {
                    "allDeps": [
                        {"id": "com.google.guava:guava:31.0",
                         "topLevels": ["com.android.tools.build:gradle:8.7.1"]},
                    ]
                }
            },
        }
        result = btc.collect_relevant_top_levels(dep_map, {"com.google.guava:guava"})
        self.assertEqual(result, {
            "com.example:plugin:1.0",
            "com.android.tools.build:gradle:8.7.1",
        })


class TestEndToEnd(unittest.TestCase):
    def test_full_run_with_stubbed_metadata(self):
        tmpdir = tempfile.mkdtemp()
        dep_map_path = pathlib.Path(tmpdir) / "dep.json"
        alerts_path = pathlib.Path(tmpdir) / "alerts.json"
        config_path = pathlib.Path(tmpdir) / "config.json"
        out_path = pathlib.Path(tmpdir) / "out.json"

        dep_map_path.write_text(json.dumps({
            "projects": {},
            "buildscriptClasspath": {
                ":": {
                    "allDeps": [
                        {"id": "com.google.guava:guava:32.0",
                         "topLevels": [
                             "com.android.tools.build:gradle:8.7.1",
                             "co.infinum:plugin:1.0",
                         ]},
                    ]
                }
            },
        }))
        alerts_path.write_text(json.dumps([
            {"dependency": {"package": {"ecosystem": "maven", "name": "com.google.guava:guava"}}}
        ]))
        config_path.write_text(json.dumps({
            "trusted_sources": ["com.android.*"],
            "trusted_source_scopes": ["buildscript"],
            "production_build_types": ["release"],
            "production_variants": [],
            "currency_threshold": "latest",
        }))

        argv_saved = sys.argv
        sys.argv = ["btc", "--dep-map", str(dep_map_path), "--alerts", str(alerts_path),
                    "--config", str(config_path), "--output", str(out_path)]
        try:
            with stub_urlopen({"com/android/tools/build/gradle":
                               meta("com.android.tools.build", "gradle", ["8.7.1", "8.8.0-alpha01"])}):
                # silence the warning emitted for untrusted top-levels (none filtered here);
                # capture stderr to keep the test output clean.
                with mock.patch.object(sys, "stderr", io.StringIO()):
                    btc.main()
        finally:
            sys.argv = argv_saved

        out = json.loads(out_path.read_text())
        # Only the trusted AGP top-level should appear; co.infinum:plugin filtered out.
        self.assertIn("com.android.tools.build:gradle:8.7.1", out)
        self.assertNotIn("co.infinum:plugin:1.0", out)
        self.assertTrue(out["com.android.tools.build:gradle:8.7.1"]["current"])
        self.assertEqual(out["com.android.tools.build:gradle:8.7.1"]["latest"], "8.7.1")


if __name__ == "__main__":
    unittest.main()
