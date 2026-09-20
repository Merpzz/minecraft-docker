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


class Settings(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.p = tempfile.TemporaryDirectory()
        self.addCleanup(self.d.cleanup); self.addCleanup(self.p.cleanup)
        for name, val in (("DATA", self.d.name), ("PERSIST_DIR", self.p.name)):
            m = mock.patch.object(mcctl, name, val); m.start(); self.addCleanup(m.stop)
        m = mock.patch.dict(os.environ, {}, clear=False); m.start(); self.addCleanup(m.stop)
        for k in ("OPS", "OP_LEVEL", "PERSIST", "SERVER_PORT"):
            os.environ.pop(k, None)

    def path(self, *a):
        return os.path.join(self.d.name, *a)

    def read(self, *a):
        with open(self.path(*a)) as f:
            return f.read()

    def write(self, name, text):
        with open(self.path(name), "w") as f:
            f.write(text)

    # -- port
    def test_port_created_and_replaced_keeping_other_lines(self):
        os.environ["SERVER_PORT"] = "25570"
        mcctl.apply_port()
        self.assertEqual(self.read("server.properties"), "server-port=25570\n")
        self.write("server.properties", "motd=Hi\n#server-port=1\nserver-port=25565\nfoo=bar=baz\n")
        mcctl.apply_port()
        self.assertEqual(self.read("server.properties"), "motd=Hi\n#server-port=1\nserver-port=25570\nfoo=bar=baz\n")

    def test_port_validation(self):
        for bad in ("0", "70000", "abc", "-1"):
            os.environ["SERVER_PORT"] = bad
            with self.assertRaises(mcctl.Fail):
                mcctl.apply_port()

    # -- ops
    def test_offline_uuid_matches_java_algorithm(self):
        import hashlib, uuid
        want = str(uuid.UUID(hex=hashlib.md5(b"OfflinePlayer:Steve").hexdigest(), version=3))
        self.assertEqual(mcctl.offline_uuid("Steve"), want)

    def test_ops_added_once_and_existing_kept(self):
        os.environ["OPS"] = "Alice, Bob,bad!name,Ghost"
        os.environ["OP_LEVEL"] = "3"
        self.write("ops.json", json.dumps([{"uuid": "u-bob", "name": "bob", "level": 1, "bypassesPlayerLimit": False}]))
        def fake(name):
            return None if name == "Ghost" else ("11111111-1111-1111-1111-111111111111", name)
        with mock.patch.object(mcctl, "mojang_uuid", side_effect=fake) as m:
            mcctl.apply_ops()
            self.assertEqual([c.args[0] for c in m.call_args_list], ["Alice", "Ghost"])  # Bob: no lookup
        ops = json.loads(self.read("ops.json"))
        self.assertEqual([(o["name"], o["level"]) for o in ops], [("bob", 1), ("Alice", 3)])
        with mock.patch.object(mcctl, "mojang_uuid", side_effect=AssertionError("no lookup on 2nd start")):
            os.environ["OPS"] = "Alice,Bob"
            mcctl.apply_ops()

    def test_ops_offline_mode_uses_offline_uuid_without_network(self):
        self.write("server.properties", "online-mode=false\n")
        os.environ["OPS"] = "Alice"
        with mock.patch.object(mcctl, "mojang_uuid", side_effect=AssertionError("no network")):
            mcctl.apply_ops()
        self.assertEqual(json.loads(self.read("ops.json"))[0]["uuid"], mcctl.offline_uuid("Alice"))

    def test_ops_lookup_failure_does_not_abort(self):
        os.environ["OPS"] = "Alice"
        with mock.patch.object(mcctl, "mojang_uuid", side_effect=mcctl.Fail("network down")):
            mcctl.apply_ops()
        self.assertFalse(os.path.exists(self.path("ops.json")))

    def test_broken_ops_json_is_backed_up(self):
        self.write("ops.json", "{not json")
        os.environ["OPS"] = "Alice"
        with mock.patch.object(mcctl, "mojang_uuid", return_value=("u", "Alice")):
            mcctl.apply_ops()
        self.assertEqual(len(json.loads(self.read("ops.json"))), 1)
        self.assertTrue(any(f.startswith("ops.json.broken-") for f in os.listdir(self.d.name)))

    # -- persist
    def test_persist_rejects_escaping_paths(self):
        for bad in ("../x", "/etc/passwd", "a/../../b"):
            os.environ["PERSIST"] = bad
            with self.assertRaises(mcctl.Fail):
                mcctl.persist_entries()

    def test_persist_moves_existing_data_and_links(self):
        os.makedirs(self.path("world")); self.write("world/level.dat", "L")
        self.write("server.properties", "motd=Hi\n")
        os.environ["PERSIST"] = "world,server.properties"
        with mock.patch.object(mcctl.os.path, "ismount", return_value=True):
            mcctl.apply_persist()
            mcctl.apply_persist()   # idempotent
        self.assertTrue(os.path.islink(self.path("world")))
        with open(os.path.join(self.p.name, "world", "level.dat")) as f:
            self.assertEqual(f.read(), "L")
        mcctl.set_property("server-port", "1234")   # written through the link
        with open(os.path.join(self.p.name, "server.properties")) as f:
            self.assertIn("server-port=1234", f.read())

    def test_persist_restores_after_reinstall(self):
        os.makedirs(os.path.join(self.p.name, "world")); 
        with open(os.path.join(self.p.name, "world", "level.dat"), "w") as f:
            f.write("OLD")
        os.environ["PERSIST"] = "world"
        with mock.patch.object(mcctl.os.path, "ismount", return_value=True):
            mcctl.apply_persist()
        self.assertEqual(self.read("world", "level.dat"), "OLD")

    def test_persist_conflict_keeps_local_copy_aside(self):
        os.makedirs(os.path.join(self.p.name, "world"))
        os.makedirs(self.path("world")); self.write("world/level.dat", "LOCAL")
        os.environ["PERSIST"] = "world"
        with mock.patch.object(mcctl.os.path, "ismount", return_value=True):
            mcctl.apply_persist()
        self.assertTrue(os.path.islink(self.path("world")))
        kept = [f for f in os.listdir(self.d.name) if f.startswith("world.local-")]
        self.assertEqual(len(kept), 1)
        with open(self.path(kept[0], "level.dat")) as f:
            self.assertEqual(f.read(), "LOCAL")

    def test_persist_precreates_known_files_only(self):
        os.environ["PERSIST"] = "whitelist.json,world,config/odd.json"
        with mock.patch.object(mcctl.os.path, "ismount", return_value=True):
            mcctl.apply_persist()
        self.assertEqual(self.read("whitelist.json"), "[]\n")
        self.assertTrue(os.path.isdir(self.path("world")))
        self.assertFalse(os.path.lexists(self.path("config", "odd.json")))   # unknown format: not guessed

    def test_persist_warns_when_not_a_mount(self):
        os.environ["PERSIST"] = "world"
        with mock.patch.object(mcctl, "log") as lg:
            mcctl.apply_persist()
        self.assertTrue(any("not a mounted volume" in c.args[0] for c in lg.call_args_list))


if __name__ == "__main__":
    unittest.main()
