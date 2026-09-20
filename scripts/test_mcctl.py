"""Offline tests for mcctl (network calls are mocked). Run: python3 -m unittest scripts/test_mcctl.py"""
import json
import os
import tempfile
import unittest
import zipfile
from unittest import mock

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
import mcctl  # noqa: E402

NEO = ["20.4.0-beta", "20.4.250", "21.0.0-beta", "21.0.167", "21.1.1", "21.1.250", "21.11.45",
       "26.1.2.109", "26.2.0.0-beta", "26.2.0.88", "26.3.0.7-beta"]
FORGE = ["1.7.10-10.13.4.1614-1.7.10", "1.7.10-10.13.4.1614", "1.21-51.0.33", "1.21.1-52.0.1",
         "1.21.1-52.1.0", "1.21.1-52.1.10", "26.2-65.1.3"]
PROMOS = {"promos": {"1.21.1-recommended": "52.1.0", "1.21.1-latest": "52.1.10", "26.2-latest": "65.1.3",
                     "1.7.10-recommended": "10.13.4.1614"}}


class NeoForge(unittest.TestCase):
    def test_prefix(self):
        for mc, pre in [("1.21.1", "21.1."), ("1.21", "21.0."), ("1.20.4", "20.4."), ("1.21.11", "21.11."),
                        ("26.2", "26.2.0."), ("26.1.2", "26.1.2.")]:
            self.assertEqual(mcctl.neo_prefix(mc), pre)
        with self.assertRaises(mcctl.Fail):
            mcctl.neo_prefix("1.16.5")   # no such prefix scheme: 16.x is not NeoForge

    def test_to_mc(self):
        for v, mc in [("21.1.250", "1.21.1"), ("21.0.167", "1.21"), ("21.11.45", "1.21.11"),
                      ("26.2.0.88", "26.2"), ("26.1.2.109", "26.1.2"), ("26.3.0.7-beta", "26.3")]:
            self.assertEqual(mcctl.neo_to_mc(v), mc)

    def test_no_prefix_collision(self):
        with mock.patch.object(mcctl, "get_json", return_value={"versions": NEO}):
            self.assertEqual(mcctl.neo_loader_versions("1.21.1"), ["21.1.250", "21.1.1"])
            self.assertNotIn("21.11.45", mcctl.neo_loader_versions("1.21.1"))

    def test_stable_preferred_beta_fallback(self):
        with mock.patch.object(mcctl, "get_json", return_value={"versions": NEO}):
            self.assertEqual(mcctl.resolve_loader_version("neoforge", "1.21.1", ""), "21.1.250")
            self.assertEqual(mcctl.resolve_loader_version("neoforge", "26.2", "latest"), "26.2.0.88")
            self.assertEqual(mcctl.resolve_loader_version("neoforge", "26.3", ""), "26.3.0.7-beta")
            with self.assertRaises(mcctl.Fail):
                mcctl.resolve_loader_version("neoforge", "1.21.1", "21.1.999")


class Forge(unittest.TestCase):
    def setUp(self):
        xml = "<metadata><versioning><versions>" + "".join(f"<version>{v}</version>" for v in FORGE) + \
              "</versions></versioning></metadata>"
        def fake_http(url, retries=3):
            return xml.encode()
        p1 = mock.patch.object(mcctl, "http", fake_http)
        p2 = mock.patch.object(mcctl, "get_json", return_value=PROMOS)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)

    def test_short_and_dedupe(self):
        self.assertEqual(mcctl.forge_short("1.7.10-10.13.4.1614-1.7.10", "1.7.10"), "10.13.4.1614")
        self.assertEqual(len(mcctl.forge_loader_versions("1.7.10")), 1)

    def test_no_prefix_collision(self):
        self.assertEqual([mcctl.forge_short(v, "1.21") for v in mcctl.forge_loader_versions("1.21")], ["51.0.33"])

    def test_recommended_then_latest(self):
        self.assertEqual(mcctl.resolve_loader_version("forge", "1.21.1", ""), "52.1.0")
        self.assertEqual(mcctl.resolve_loader_version("forge", "1.21.1", "latest"), "52.1.10")
        self.assertEqual(mcctl.resolve_loader_version("forge", "26.2", ""), "65.1.3")  # no recommended
        self.assertEqual(mcctl.resolve_loader_version("forge", "1.21.1", "52.0.1"), "52.0.1")
        with self.assertRaises(mcctl.Fail):
            mcctl.resolve_loader_version("forge", "1.21.1", "1.2.3")


class Mods(unittest.TestCase):
    def jar(self, d, name, files):
        p = os.path.join(d, name)
        with zipfile.ZipFile(p, "w") as z:
            for f in files:
                z.writestr(f, "x")
        return p

    def test_jar_detection(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(mcctl.jar_loaders(self.jar(d, "a.jar", ["fabric.mod.json"])), {"fabric"})
            self.assertEqual(mcctl.jar_loaders(self.jar(d, "b.jar", ["META-INF/neoforge.mods.toml"])), {"neoforge"})
            self.assertEqual(mcctl.jar_loaders(self.jar(d, "c.jar", ["META-INF/mods.toml"])), {"forge", "neoforge"})
            with open(os.path.join(d, "bad.jar"), "w") as f:
                f.write("junk")
            self.assertIsNone(mcctl.jar_loaders(os.path.join(d, "bad.jar")))


class Install(unittest.TestCase):
    def test_latest_is_pinned_across_restarts(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(mcctl, "DATA", d), \
                mock.patch.object(mcctl, "STATE_FILE", os.path.join(d, ".mcctl-state.json")):
            with open(os.path.join(d, "server.jar"), "w") as f:
                f.write("x")
            state = {"loader": "vanilla", "mc": "1.20.4", "loader_version": "", "java": 17,
                     "requested": {"loader": "vanilla", "mc": "latest", "loader_version": ""}}
            with open(mcctl.STATE_FILE, "w") as f:
                json.dump(state, f)
            env = {"LOADER": "vanilla", "MC_VERSION": "latest", "LOADER_VERSION": ""}
            with mock.patch.dict(os.environ, env), \
                    mock.patch.object(mcctl, "resolve_all", side_effect=AssertionError("must not hit network")):
                self.assertEqual(mcctl.install()["mc"], "1.20.4")   # newer "latest" ignored
                with mock.patch.dict(os.environ, {"UPDATE": "true"}):
                    with self.assertRaises(AssertionError):          # UPDATE=true re-resolves
                        mcctl.install()

    def test_launch_cmd(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(mcctl, "DATA", d):
            self.assertIsNone(mcctl.launch_cmd_or_none({"loader": "forge"}))
            a = os.path.join(d, "libraries/net/neoforged/neoforge/21.1.1")
            os.makedirs(a)
            open(os.path.join(a, "unix_args.txt"), "w").write("x")
            self.assertEqual(mcctl.launch_cmd_or_none({"loader": "neoforge"}),
                             ["@libraries/net/neoforged/neoforge/21.1.1/unix_args.txt", "nogui"])
            os.remove(os.path.join(a, "unix_args.txt"))
            open(os.path.join(d, "forge-1.12.2-14.23.5.2859.jar"), "w").write("x")
            open(os.path.join(d, "forge-1.12.2-installer.jar"), "w").write("x")
            self.assertEqual(mcctl.launch_cmd_or_none({"loader": "forge"}),
                             ["-jar", "forge-1.12.2-14.23.5.2859.jar", "nogui"])

    def test_pick_java(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(mcctl, "JAVA_ROOT", d):
            for j in ("8", "17", "21", "25", "openjdk"):
                os.makedirs(os.path.join(d, j))
            self.assertEqual([mcctl.pick_java(n) for n in (8, 16, 17, 21, 25)], [8, 17, 17, 21, 25])
            with self.assertRaises(mcctl.Fail):
                mcctl.pick_java(26)


if __name__ == "__main__":
    unittest.main()
