#!/usr/bin/env python3
"""Regenerate the Minecraft version dropdown in the Unraid template and VERSIONS.md.

Fetches live data (Mojang, Fabric, Forge, NeoForge) via scripts/mcctl.py. Run by the
"Update version lists" GitHub workflow every week; can also be run by hand:

    python3 tools/gen_template.py
"""
import functools
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import mcctl  # noqa: E402

TEMPLATE = os.path.join(ROOT, "unraid-template", "minecraft-docker.xml")
VERSIONS_MD = os.path.join(ROOT, "VERSIONS.md")
OLDEST = "1.7.10"     # oldest release offered (older Forge/Java-6-era versions are not worth it)


def offered_versions(releases):
    """Releases newest first, cut off after OLDEST."""
    if OLDEST not in releases:
        return releases
    return releases[:releases.index(OLDEST) + 1]


def update_dropdown(xml, versions):
    """Put 'latest|v1|v2|...' into the Default attribute of the MC_VERSION entry."""
    options = "|".join(["latest"] + versions)
    pat = re.compile(r'(<Config Name="MC_VERSION"[^>]*?\bDefault=")[^"]*(")')
    if not pat.search(xml):
        raise SystemExit("MC_VERSION entry not found in the template")
    return pat.sub(lambda m: m.group(1) + options + m.group(2), xml, count=1)


def newest(vs):
    return max(vs, key=mcctl._vkey) if vs else None


def build_rows(versions, fabric_mc, fabric_loader, forge_by_mc, promos, neo_by_mc):
    rows = []
    for mc in versions:
        fab = fabric_loader if mc in fabric_mc else "-"
        fv = forge_by_mc.get(mc)
        if fv:
            rec = promos.get(f"{mc}-recommended")
            forge = f"{rec} (recommended)" if rec else f"{newest(fv)} (latest)"
        else:
            forge = "-"
        nv = neo_by_mc.get(mc)
        neo = "-"
        if nv:
            stable = [v for v in nv if not v.endswith("-beta")]
            neo = stable[-1] if stable else f"{nv[-1]} (beta)"
        rows.append((mc, fab, forge, neo))
    return rows


def render_md(rows, when):
    out = ["# Available versions", "",
           f"Generated {when} from Mojang, Fabric, Forge and NeoForge by `tools/gen_template.py`; "
           "updated weekly by GitHub Actions.", "",
           "The loader version shown is what you get when `LOADER_VERSION` is empty. "
           "`-` means that loader has no build for that Minecraft version. "
           "Exact versions: `mcctl loader <loader> <mc-version>`.", "",
           "| Minecraft | Fabric | Forge | NeoForge |", "|---|---|---|---|"]
    out += [f"| {mc} | {f} | {fo} | {n} |" for mc, f, fo, n in rows]
    return "\n".join(out) + "\n"


def main():
    import datetime
    # One network fetch per source instead of one per Minecraft version.
    for name in ("forge_all", "neo_all", "fabric_mc_versions", "mc_versions"):
        setattr(mcctl, name, functools.lru_cache(maxsize=None)(getattr(mcctl, name)))
    versions = offered_versions(mcctl.mc_versions())
    fabric_loader = next(e["version"] for e in mcctl.get_json(f"{mcctl.FABRIC_META}/loader") if e["stable"])
    promos = mcctl.get_json(mcctl.FORGE_PROMOS)["promos"]
    forge_by_mc = {}
    for full in mcctl.forge_all():
        forge_by_mc.setdefault(full.split("-")[0], []).append(mcctl.forge_short(full, full.split("-")[0]))
    neo_by_mc = {}
    for v in mcctl.neo_all():
        mc = mcctl.neo_to_mc(v)
        if mc:
            neo_by_mc.setdefault(mc, []).append(v)
    rows = build_rows(versions, set(mcctl.fabric_mc_versions()), fabric_loader, forge_by_mc, promos, neo_by_mc)

    with open(TEMPLATE) as f:
        xml = f.read()
    with open(TEMPLATE, "w") as f:
        f.write(update_dropdown(xml, versions))
    with open(VERSIONS_MD, "w") as f:
        f.write(render_md(rows, datetime.date.today().isoformat()))
    print(f"{len(versions)} versions ({versions[0]} .. {versions[-1]}) written")


if __name__ == "__main__":
    main()
