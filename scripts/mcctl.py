#!/usr/bin/env python3
"""mcctl - version lookup and installer for the custom Minecraft container.

Supports vanilla, Fabric, Forge and NeoForge. All version lists are fetched
live, so nothing here needs updating when new Minecraft versions appear.

Usage:
  mcctl mc [--snapshots]              list Minecraft versions
  mcctl loaders <loader>              list Minecraft versions a loader supports
  mcctl loader <loader> <mc>          list loader versions for a Minecraft version
  mcctl resolve <loader> <mc> [ver]   print the resolved "mc loader-version java"
  mcctl install                       install according to MC_VERSION/LOADER/LOADER_VERSION
  mcctl launch-cmd                    print the java command line for the installed server
  mcctl prepare                       apply SERVER_PORT, OPS and PERSIST to the server folder
  mcctl check-mods                    warn about mods that do not match the loader
"""
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import zipfile

DATA = os.environ.get("DATA_DIR", "/data")
STATE_FILE = os.path.join(DATA, ".mcctl-state.json")
JAVA_ROOT = os.environ.get("JAVA_ROOT", "/opt/java")

MOJANG_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
FABRIC_META = "https://meta.fabricmc.net/v2/versions"
FORGE_META = "https://maven.minecraftforge.net/net/minecraftforge/forge/maven-metadata.xml"
FORGE_PROMOS = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
FORGE_MAVEN = "https://maven.minecraftforge.net/net/minecraftforge/forge"
NEO_VERSIONS = "https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge"
NEO_MAVEN = "https://maven.neoforged.net/releases/net/neoforged/neoforge"

LOADERS = ("vanilla", "fabric", "forge", "neoforge")


class Fail(Exception):
    pass


def log(msg):
    print(f"[mcctl] {msg}", file=sys.stderr, flush=True)


def http(url, retries=3):
    last = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "custom-minecraft-docker/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
    raise Fail(f"Could not fetch {url}: {last}")


def get_json(url):
    return json.loads(http(url))


def download(url, dest):
    log(f"Downloading {url}")
    tmp = dest + ".part"
    with open(tmp, "wb") as f:
        f.write(http(url))
    os.replace(tmp, dest)


# --------------------------------------------------------------------------- #
# Minecraft (Mojang)
# --------------------------------------------------------------------------- #
_manifest = None


def manifest():
    global _manifest
    if _manifest is None:
        _manifest = get_json(MOJANG_MANIFEST)
    return _manifest


def mc_versions(snapshots=False):
    """Newest first."""
    return [v["id"] for v in manifest()["versions"] if snapshots or v["type"] == "release"]


def resolve_mc(mc):
    m = manifest()
    if mc in ("", "latest"):
        return m["latest"]["release"]
    if mc == "latest-snapshot":
        return m["latest"]["snapshot"]
    if mc not in {v["id"] for v in m["versions"]}:
        raise Fail(f"Unknown Minecraft version '{mc}'. Run: mcctl mc")
    return mc


def mc_meta(mc):
    entry = next(v for v in manifest()["versions"] if v["id"] == mc)
    return get_json(entry["url"])


# --------------------------------------------------------------------------- #
# Fabric
# --------------------------------------------------------------------------- #
def fabric_loader_versions(mc):
    """[(version, stable)] newest first."""
    data = get_json(f"{FABRIC_META}/loader/{mc}")
    return [(e["loader"]["version"], e["loader"]["stable"]) for e in data]


def fabric_mc_versions():
    return [e["version"] for e in get_json(f"{FABRIC_META}/game") if e["stable"]]


def fabric_installer_version():
    for e in get_json(f"{FABRIC_META}/installer"):
        if e["stable"]:
            return e["version"]
    raise Fail("No stable Fabric installer found")


# --------------------------------------------------------------------------- #
# Forge
# --------------------------------------------------------------------------- #
def forge_all():
    """Full version strings as in Maven, e.g. '1.21.1-52.1.0' (oldest first)."""
    root = ET.fromstring(http(FORGE_META))
    return [v.text for v in root.iter("version")]


def _vkey(v):
    return [int(p) if p.isdigit() else 0 for p in re.split(r"[.\-]", v)]


def forge_loader_versions(mc):
    """[full maven version] newest first."""
    pre = mc + "-"
    vs = [v for v in forge_all() if v.startswith(pre)]
    out, seen = [], set()
    for v in sorted(vs, key=_vkey, reverse=True):
        if forge_short(v, mc) not in seen:   # some old builds are listed twice
            seen.add(forge_short(v, mc))
            out.append(v)
    return out


def forge_short(full, mc):
    """'1.7.10-10.13.4.1614-1.7.10' -> '10.13.4.1614'."""
    s = full[len(mc) + 1:]
    return s.split("-")[0]


def forge_mc_versions():
    seen, out = set(), []
    for v in reversed(forge_all()):
        mc = v.split("-")[0]
        if mc not in seen:
            seen.add(mc)
            out.append(mc)
    known = {x: i for i, x in enumerate(mc_versions(snapshots=True))}
    return sorted(out, key=lambda x: known.get(x, 10**6))


# --------------------------------------------------------------------------- #
# NeoForge
#   1.x.y      -> x.y.<build>      (1.21.1 -> 21.1.x, 1.21 -> 21.0.x)
#   26.a[.b]   -> 26.a.b.<build>   (26.2 -> 26.2.0.x, 26.1.2 -> 26.1.2.x)
# Suffix -beta marks unstable builds.
# --------------------------------------------------------------------------- #
def neo_prefix(mc):
    p = mc.split(".")
    if p[0] == "1":
        if len(p) < 2 or not p[1].isdigit() or int(p[1]) < 20:
            raise Fail(f"NeoForge does not support Minecraft {mc} (it starts at 1.20.2)")
        return f"{p[1]}.{p[2] if len(p) > 2 else 0}."
    if p[0].isdigit() and int(p[0]) >= 26:
        return f"{p[0]}.{p[1]}.{p[2] if len(p) > 2 else 0}."
    raise Fail(f"NeoForge does not support Minecraft {mc}")


def neo_to_mc(v):
    f = v.split("-")[0].split(".")
    if f[0] == "1" or int(f[0]) < 20:
        return None
    if int(f[0]) >= 26:
        return f"{f[0]}.{f[1]}" + (f".{f[2]}" if f[2] != "0" else "")
    return f"1.{f[0]}" + (f".{f[1]}" if f[1] != "0" else "")


def neo_all():
    vs = get_json(NEO_VERSIONS)["versions"]
    return [v for v in vs if re.fullmatch(r"\d+(\.\d+)*(-beta)?", v)]


def neo_loader_versions(mc):
    """Newest first (API order is chronological)."""
    pre = neo_prefix(mc)
    return [v for v in reversed(neo_all()) if v.startswith(pre)]


def neo_mc_versions():
    seen, out = set(), []
    for v in reversed(neo_all()):
        mc = neo_to_mc(v)
        if mc and mc not in seen:
            seen.add(mc)
            out.append(mc)
    return out


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #
def loader_versions(loader, mc):
    """Returns [(version, label)] newest first, label e.g. 'stable', 'beta'."""
    if loader == "fabric":
        return [(v, "stable" if s else "unstable") for v, s in fabric_loader_versions(mc)]
    if loader == "forge":
        promos = get_json(FORGE_PROMOS)["promos"]
        rec, lat = promos.get(f"{mc}-recommended"), promos.get(f"{mc}-latest")
        out = []
        for full in forge_loader_versions(mc):
            short = forge_short(full, mc)
            tag = "recommended" if short == rec else ("latest" if short == lat else "")
            out.append((short, tag))
        return out
    if loader == "neoforge":
        return [(v, "beta" if v.endswith("-beta") else "stable") for v in neo_loader_versions(mc)]
    if loader == "vanilla":
        return []
    raise Fail(f"Unknown loader '{loader}' (use: {', '.join(LOADERS)})")


def resolve_loader_version(loader, mc, want):
    """Turn 'latest'/'recommended'/exact into an exact version string."""
    if loader == "vanilla":
        return ""
    vs = loader_versions(loader, mc)
    if not vs:
        raise Fail(f"{loader} has no builds for Minecraft {mc}. Run: mcctl loaders {loader}")
    names = [v for v, _ in vs]
    want = (want or "").strip()
    if want in ("", "latest", "recommended"):
        if loader == "forge":
            promo = "recommended" if want in ("", "recommended") else "latest"
            for v, tag in vs:
                if tag == promo:
                    return v
            for v, tag in vs:  # no recommended build: fall back to latest
                if tag in ("latest", "recommended"):
                    return v
            return names[0]
        stable = [v for v, lab in vs if lab == "stable"]
        if stable:
            return stable[0]
        log(f"No stable {loader} build for {mc}; using newest pre-release {names[0]}")
        return names[0]
    if want not in names:
        raise Fail(f"{loader} {want} does not exist for Minecraft {mc}. "
                   f"Run: mcctl loader {loader} {mc}")
    return want


def pick_java(required):
    """Smallest installed Java >= required."""
    have = sorted(int(d) for d in os.listdir(JAVA_ROOT) if d.isdigit()) if os.path.isdir(JAVA_ROOT) else []
    for j in have:
        if j >= required:
            return j
    raise Fail(f"Minecraft needs Java {required}, but only {have or 'none'} installed")


def java_bin(major):
    return os.path.join(JAVA_ROOT, str(major), "bin", "java")


def resolve_all():
    loader = os.environ.get("LOADER", "vanilla").strip().lower()
    if loader not in LOADERS:
        raise Fail(f"LOADER must be one of {', '.join(LOADERS)} (got '{loader}')")
    mc = resolve_mc(os.environ.get("MC_VERSION", "latest").strip())
    lv = resolve_loader_version(loader, mc, os.environ.get("LOADER_VERSION", ""))
    java = int(os.environ["JAVA_VERSION"]) if os.environ.get("JAVA_VERSION") else \
        pick_java(mc_meta(mc).get("javaVersion", {}).get("majorVersion", 8))
    return loader, mc, lv, java


# --------------------------------------------------------------------------- #
# Install
# --------------------------------------------------------------------------- #
CLEAN_PATHS = ["libraries", "run.sh", "run.bat", "server.jar", "fabric-server-launch.jar",
               "fabric-server-launcher.properties", ".fabric", "forge-*.jar", "minecraft_server*.jar",
               "user_jvm_args.txt", "installer.jar", "installer.log", "*.installer.log",
               "server-launch.properties"]


def clean_install():
    for pat in CLEAN_PATHS:
        for p in glob.glob(os.path.join(DATA, pat)):
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)


def run_installer(java, jar, args):
    cmd = [java_bin(java), "-jar", jar] + args
    log("Running " + " ".join(cmd))
    r = subprocess.run(cmd, cwd=DATA)
    if r.returncode != 0:
        raise Fail(f"Installer failed (exit {r.returncode}); see output above")


def requested():
    return {"loader": os.environ.get("LOADER", "vanilla").strip().lower(),
            "mc": os.environ.get("MC_VERSION", "latest").strip(),
            "loader_version": os.environ.get("LOADER_VERSION", "").strip()}


def install():
    """Install (or keep) the server. 'latest' is resolved once and then pinned:
    an upgrade only happens when the requested settings change or UPDATE=true,
    so a restart never silently upgrades a world to a newer Minecraft version."""
    req = requested()
    state = None
    if os.path.exists(STATE_FILE):
        try:
            state = json.load(open(STATE_FILE))
        except ValueError:
            pass
    update = os.environ.get("UPDATE", "").lower() in ("1", "true", "yes")
    if state and state.get("requested") == req and not update and launch_cmd_or_none(state):
        log(f"Already installed: {describe(state)} (set UPDATE=true to re-resolve 'latest')")
        return state

    loader, mc, lv, java = resolve_all()
    want = {"loader": loader, "mc": mc, "loader_version": lv, "java": java, "requested": req}
    if state and {k: state.get(k) for k in want if k != "requested"} == \
            {k: want[k] for k in want if k != "requested"} and launch_cmd_or_none(state):
        json.dump(want, open(STATE_FILE, "w"))
        log(f"Already installed: {describe(want)}")
        return want
    if state:
        log(f"Version changed ({describe(state)} -> {describe(want)}); replacing server files "
            "(world, mods, config are kept)")
    clean_install()
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)   # files are gone; do not trust the old state if we fail below
    log(f"Installing {describe(want)}")

    if loader == "vanilla":
        url = mc_meta(mc)["downloads"]["server"]["url"]
        download(url, os.path.join(DATA, "server.jar"))
    elif loader == "fabric":
        url = f"{FABRIC_META}/loader/{mc}/{lv}/{fabric_installer_version()}/server/jar"
        download(url, os.path.join(DATA, "fabric-server-launch.jar"))
    elif loader == "forge":
        full = next(f for f in forge_loader_versions(mc) if forge_short(f, mc) == lv)
        inst = os.path.join(DATA, "installer.jar")
        download(f"{FORGE_MAVEN}/{full}/forge-{full}-installer.jar", inst)
        run_installer(java, inst, ["--installServer"])
        os.remove(inst)
    elif loader == "neoforge":
        inst = os.path.join(DATA, "installer.jar")
        download(f"{NEO_MAVEN}/{lv}/neoforge-{lv}-installer.jar", inst)
        run_installer(java, inst, ["--installServer"])
        os.remove(inst)

    if not launch_cmd_or_none(want):
        raise Fail("Install finished but no launchable server files were found")
    json.dump(want, open(STATE_FILE, "w"))
    log("Install complete")
    return want


def describe(s):
    return f"{s['loader']} MC {s['mc']}" + (f" {s['loader_version']}" if s["loader_version"] else "") + \
        f" (Java {s['java']})"


# --------------------------------------------------------------------------- #
# Launch
# --------------------------------------------------------------------------- #
def launch_cmd_or_none(state):
    """Returns the launch arguments *after* the JVM flags, or None."""
    loader = state["loader"]
    if loader == "vanilla":
        return ["-jar", "server.jar", "nogui"] if os.path.exists(f"{DATA}/server.jar") else None
    if loader == "fabric":
        return ["-jar", "fabric-server-launch.jar", "nogui"] \
            if os.path.exists(f"{DATA}/fabric-server-launch.jar") else None
    # Forge / NeoForge >= 1.17 use an args file, older Forge a plain jar.
    args = sorted(glob.glob(f"{DATA}/libraries/net/*/*/*/unix_args.txt"))
    if args:
        return ["@" + os.path.relpath(args[0], DATA), "nogui"]
    jars = [j for j in glob.glob(f"{DATA}/forge-*.jar") if "installer" not in j]
    if jars:
        return ["-jar", os.path.basename(sorted(jars)[0]), "nogui"]
    return None


def cmd_launch():
    state = json.load(open(STATE_FILE))
    args = launch_cmd_or_none(state)
    if not args:
        raise Fail("Server is not installed")
    # One argument per line so the shell wrapper can read it safely.
    print(java_bin(state["java"]))
    for a in args:
        print(a)


# --------------------------------------------------------------------------- #
# Mod sanity check
# --------------------------------------------------------------------------- #
def jar_loaders(path):
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
    except zipfile.BadZipFile:
        return None
    found = set()
    if "fabric.mod.json" in names:
        found.add("fabric")
    if "META-INF/neoforge.mods.toml" in names:
        found.add("neoforge")
    if "META-INF/mods.toml" in names:
        found.update(("forge", "neoforge"))   # NeoForge 1.20.x still reads mods.toml
    if "mcmod.info" in names:
        found.add("forge")
    return found


def check_mods():
    loader = os.environ.get("LOADER", "vanilla").lower()
    mods = sorted(glob.glob(os.path.join(DATA, "mods", "*.jar")))
    if not mods:
        return
    if loader == "vanilla":
        log(f"WARNING: {len(mods)} jar(s) in mods/ but LOADER=vanilla - they will be ignored")
        return
    for m in mods:
        found = jar_loaders(m)
        name = os.path.basename(m)
        if found is None:
            log(f"WARNING: {name} is not a valid jar/zip file")
        elif found and loader not in found:
            log(f"WARNING: {name} looks like a {'/'.join(sorted(found))} mod, "
                f"but the server runs {loader} - it will probably not load")


# --------------------------------------------------------------------------- #
# Server settings: port, operators, persistent paths
# --------------------------------------------------------------------------- #
PERSIST_DIR = os.environ.get("PERSIST_DIR", "/persist")
MOJANG_PROFILE = "https://api.mojang.com/users/profiles/minecraft"

# Files the vanilla server itself keeps as JSON lists; safe to pre-create as "[]".
JSON_LISTS = ("ops.json", "whitelist.json", "banned-players.json", "banned-ips.json", "usercache.json")


def props_path():
    return os.path.join(DATA, "server.properties")


def read_property(key, default=None):
    try:
        with open(props_path()) as f:
            for line in f:
                k, sep, v = line.rstrip("\n").partition("=")
                if sep and k.strip() == key:
                    return v.strip()
    except FileNotFoundError:
        pass
    return default


def set_property(key, value):
    """Set key=value in server.properties, keeping every other line as is.
    Writes in place (no rename) so a symlink into PERSIST_DIR stays intact."""
    lines, found = [], False
    try:
        with open(props_path()) as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        pass
    for i, line in enumerate(lines):
        if line.partition("=")[0].strip() == key and not line.lstrip().startswith("#"):
            lines[i], found = f"{key}={value}", True
    if not found:
        lines.append(f"{key}={value}")
    with open(props_path(), "w") as f:
        f.write("\n".join(lines) + "\n")


def apply_port():
    raw = os.environ.get("SERVER_PORT", "25565").strip() or "25565"
    if not raw.isdigit() or not 1 <= int(raw) <= 65535:
        raise Fail(f"SERVER_PORT must be 1-65535 (got '{raw}')")
    set_property("server-port", raw)
    log(f"Server port: {raw}")


def offline_uuid(name):
    """UUID of a player on an online-mode=false server (same as Java's nameUUIDFromBytes)."""
    h = bytearray(hashlib.md5(f"OfflinePlayer:{name}".encode()).digest())
    h[6] = (h[6] & 0x0F) | 0x30
    h[8] = (h[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(h)))


def mojang_uuid(name):
    """UUID and correctly-cased name from Mojang, or None if the player does not exist."""
    try:
        req = urllib.request.Request(f"{MOJANG_PROFILE}/{name}", headers={"User-Agent": "custom-minecraft-docker/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read()
        if not body:
            return None
        d = json.loads(body)
        return str(uuid.UUID(hex=d["id"])), d["name"]
    except urllib.error.HTTPError as e:
        if e.code in (204, 404):
            return None
        raise Fail(f"Mojang lookup for '{name}' failed: HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as e:
        raise Fail(f"Mojang lookup for '{name}' failed: {e}")


def apply_ops():
    """Make sure every player in OPS is in ops.json. Only adds: ops given in-game
    stay, and removing a name from OPS does not de-op it (use /deop)."""
    names = [n for n in re.split(r"[,\s]+", os.environ.get("OPS", "").strip()) if n]
    if not names:
        return
    level = os.environ.get("OP_LEVEL", "4").strip() or "4"
    if level not in ("1", "2", "3", "4"):
        raise Fail(f"OP_LEVEL must be 1-4 (got '{level}')")
    path = os.path.join(DATA, "ops.json")
    ops = []
    try:
        with open(path) as f:
            ops = json.load(f)
        if not isinstance(ops, list):
            raise ValueError("not a list")
    except FileNotFoundError:
        pass
    except ValueError as e:
        backup = f"{path}.broken-{int(time.time())}"
        shutil.copy(path, backup)
        log(f"WARNING: ops.json was unreadable ({e}); saved a copy as {os.path.basename(backup)}")
        ops = []
    online = read_property("online-mode", "true").lower() != "false"
    by_name = {o.get("name", "").lower(): o for o in ops}
    changed = False
    for name in names:
        if not re.fullmatch(r"[A-Za-z0-9_]{1,16}", name):
            log(f"WARNING: '{name}' is not a valid Minecraft username - skipped")
            continue
        entry = by_name.get(name.lower())
        if not online:
            uid = offline_uuid(name)
            if entry and entry.get("uuid") == uid:
                continue
        elif entry:
            continue              # already op; no lookup needed (works offline too)
        else:
            try:
                found = mojang_uuid(name)
            except Fail as e:
                log(f"WARNING: {e} - '{name}' not added")
                continue
            if not found:
                log(f"WARNING: no Minecraft player named '{name}' - skipped")
                continue
            uid, name = found
        if entry:
            entry["uuid"] = uid
        else:
            ops.append({"uuid": uid, "name": name, "level": int(level), "bypassesPlayerLimit": False})
            log(f"Added operator {name} (level {level})")
        changed = True
    if changed:
        with open(path, "w") as f:
            json.dump(ops, f, indent=2)


def persist_entries():
    out = []
    for e in re.split(r"[,\s]+", os.environ.get("PERSIST", "").strip()):
        if not e:
            continue
        norm = os.path.normpath(e.strip("/")) if not e.startswith("/") else None
        if norm is None or norm == "." or norm.startswith(".."):
            raise Fail(f"PERSIST entries must be paths inside the server folder (got '{e}')")
        out.append(norm)
    return out


def persist_one(rel):
    """Make DATA/rel a symlink to PERSIST_DIR/rel, moving existing data over."""
    src, dst = os.path.join(DATA, rel), os.path.join(PERSIST_DIR, rel)
    if os.path.islink(src) and os.path.realpath(src) == os.path.realpath(dst):
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    os.makedirs(os.path.dirname(src), exist_ok=True)
    local = os.path.lexists(src) and not os.path.islink(src)
    if os.path.lexists(dst):
        if local:      # both exist: the persistent copy wins, the local one is kept aside
            keep = f"{src}.local-{int(time.time())}"
            os.rename(src, keep)
            log(f"WARNING: {rel} existed both locally and in persist; using the persist copy, "
                f"local one kept as {os.path.basename(keep)}")
        elif os.path.islink(src):
            os.remove(src)
    else:
        if local:
            shutil.move(src, dst)
        else:
            if os.path.islink(src):
                os.remove(src)
            base = os.path.basename(rel)
            if base in JSON_LISTS:
                with open(dst, "w") as f:
                    f.write("[]\n")
            elif base.endswith((".properties", ".txt")):
                open(dst, "w").close()
            elif "." not in base:
                os.makedirs(dst)
            else:
                log(f"{rel} does not exist yet; it will be moved to persist on a later start")
                return
    os.symlink(dst, src)
    log(f"Persistent: {rel} -> {dst}")


def apply_persist():
    entries = persist_entries()
    if not entries:
        return
    if not os.path.ismount(PERSIST_DIR):
        log(f"WARNING: {PERSIST_DIR} is not a mounted volume - PERSIST data lives inside the "
            "container and is lost when it is removed. Mount a host folder there (see docker-compose.yml).")
    for rel in entries:
        persist_one(rel)


def prepare():
    apply_persist()   # first, so server.properties/ops.json edits go to the persistent copies
    apply_port()
    apply_ops()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    c, a = argv[1], argv[2:]
    if c == "mc":
        for v in mc_versions("--snapshots" in a):
            print(v)
    elif c == "loaders":
        if not a or a[0] not in LOADERS[1:]:
            raise Fail("Usage: mcctl loaders <fabric|forge|neoforge>")
        fn = {"fabric": fabric_mc_versions, "forge": forge_mc_versions, "neoforge": neo_mc_versions}[a[0]]
        for v in fn():
            print(v)
    elif c == "loader":
        if len(a) < 2:
            raise Fail("Usage: mcctl loader <fabric|forge|neoforge> <mc-version>")
        mc = resolve_mc(a[1])
        vs = loader_versions(a[0], mc)
        if not vs:
            raise Fail(f"No {a[0]} builds for Minecraft {mc}")
        for v, lab in vs:
            print(f"{v}\t{lab}" if lab else v)
    elif c == "resolve":
        if len(a) < 2:
            raise Fail("Usage: mcctl resolve <loader> <mc-version> [loader-version]")
        mc = resolve_mc(a[1])
        lv = resolve_loader_version(a[0], mc, a[2] if len(a) > 2 else "")
        need = mc_meta(mc).get("javaVersion", {}).get("majorVersion", 8)
        print(mc, lv or "-", f"java>={need}")
    elif c == "install":
        install()
    elif c == "launch-cmd":
        cmd_launch()
    elif c == "prepare":
        prepare()
    elif c == "check-mods":
        check_mods()
    else:
        raise Fail(f"Unknown command '{c}'. Try: mcctl help")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Fail as e:
        print(f"[mcctl] ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except BrokenPipeError:
        sys.exit(0)
