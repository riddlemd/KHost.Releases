#!/usr/bin/env python3
"""Checks a KHost catalog file the way a host will read it, then downloads every release to prove it.

    python3 tools/validate.py plugins.json            # shape, downloads, manifests, host range
    python3 tools/validate.py plugins.json --offline  # shape only

Standard library only, so CI needs nothing installed. Exits 1 on any error; a warning never fails.
"""
import hashlib
import io
import json
import re
import sys
import urllib.request
import uuid
import zipfile

SUPPORTED_SCHEMA = 1
KNOWN_RIDS = {"win", "macos", "linux"}
PLUGIN_API_URL = "https://raw.githubusercontent.com/riddlemd/KHost/main/src/KHost.Abstractions/Models/Plugins/PluginApi.cs"
USER_AGENT = "KHost.Releases-validate/1.0 (+https://github.com/riddlemd/KHost.Releases)"

errors = []
warnings = []


def error(where, message):
    errors.append(f"{where}: {message}")


def warn(where, message):
    warnings.append(f"{where}: {message}")


def parse_version(text):
    """KHost reads up to four dot-separated numbers; anything else sorts as unreadable."""
    parts = text.split(".")
    if not 1 <= len(parts) <= 4 or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts) + (0,) * (4 - len(parts))


def check_shape(catalog):
    if catalog.get("schemaVersion") != SUPPORTED_SCHEMA:
        # A host rejects the whole document on an unknown schema, so this empties every browse list.
        error("catalog", f"schemaVersion must be {SUPPORTED_SCHEMA}, is {catalog.get('schemaVersion')!r}")

    plugins = catalog.get("plugins")
    if not isinstance(plugins, list):
        error("catalog", "plugins must be a list")
        return []

    seen = set()
    for index, entry in enumerate(plugins):
        where = f"plugins[{index}] {entry.get('name', '?')}"
        try:
            plugin_id = uuid.UUID(str(entry.get("id")))
            if plugin_id.int == 0:
                raise ValueError
        except ValueError:
            error(where, f"id must be the plugin manifest's GUID, is {entry.get('id')!r}")
            plugin_id = None
        if plugin_id in seen:
            error(where, f"id {plugin_id} is listed twice")
        seen.add(plugin_id)

        if not str(entry.get("name", "")).strip():
            error(where, "name is empty")
        if not entry.get("repository", "").startswith("https://"):
            error(where, "repository must be an https URL")

        releases = entry.get("releases")
        if not isinstance(releases, list) or not releases:
            error(where, "needs at least one release")
            continue

        keys = set()
        for release in releases:
            rwhere = f"{where} v{release.get('version')}{'-' + release['rid'] if release.get('rid') else ''}"
            if parse_version(str(release.get("version", ""))) is None:
                error(rwhere, "version must be up to four dot-separated numbers")
            api = release.get("apiVersion")
            if not isinstance(api, int) or api < 1:
                error(rwhere, f"apiVersion must be a positive integer, is {api!r}")
            if not str(release.get("url", "")).startswith("https://"):
                error(rwhere, "url must be https")
            if not re.fullmatch(r"[0-9a-f]{64}", str(release.get("sha256", ""))):
                error(rwhere, "sha256 must be 64 lower-case hex characters")
            size = release.get("sizeBytes")
            if size is not None and (not isinstance(size, int) or size <= 0):
                error(rwhere, "sizeBytes must be a positive integer when present")
            rid = release.get("rid")
            if rid is not None and rid not in KNOWN_RIDS:
                error(rwhere, f"rid must be one of {sorted(KNOWN_RIDS)} or absent, is {rid!r}")
            if "isInstallable" in release:
                error(rwhere, "isInstallable is derived by the host and must not be written")
            key = (release.get("version"), rid)
            if key in keys:
                error(rwhere, "the same version and platform is listed twice")
            keys.add(key)
    return plugins


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def check_download(entry, release):
    rwhere = f"{entry.get('name')} v{release.get('version')}{'-' + release['rid'] if release.get('rid') else ''}"
    try:
        # Anonymous on purpose: a host sends no credentials, so a private asset is a 404 to it too.
        data = fetch(release["url"])
    except Exception as ex:
        error(rwhere, f"download failed: {ex}")
        return

    if hashlib.sha256(data).hexdigest() != release["sha256"]:
        error(rwhere, f"sha256 is {hashlib.sha256(data).hexdigest()}, the catalog says {release['sha256']}")
    if release.get("sizeBytes") is not None and len(data) != release["sizeBytes"]:
        error(rwhere, f"download is {len(data)} bytes, the catalog says {release['sizeBytes']}")

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        error(rwhere, "the download is not a zip")
        return

    names = archive.namelist()
    for name in names:
        if name.startswith("/") or "\\" in name or ".." in name.split("/"):
            error(rwhere, f"zip entry {name!r} escapes the plugin folder; a host refuses the whole zip")

    # A host takes manifest.json at the root, or inside one wrapping folder.
    roots = {n.split("/")[0] for n in names if n.strip("/")}
    prefix = ""
    if "manifest.json" not in names and len(roots) == 1:
        prefix = next(iter(roots)) + "/"
    if prefix + "manifest.json" not in names:
        error(rwhere, "no manifest.json at the zip's root or inside one wrapping folder")
        return

    try:
        manifest = json.loads(archive.read(prefix + "manifest.json").decode("utf-8-sig"))
    except Exception as ex:
        error(rwhere, f"manifest.json does not parse: {ex}")
        return

    if str(manifest.get("id", "")).lower() != str(entry.get("id", "")).lower():
        error(rwhere, f"manifest id {manifest.get('id')} is not the catalog's {entry.get('id')}")
    if manifest.get("version") != release.get("version"):
        error(rwhere, f"manifest version {manifest.get('version')} is not the catalog's {release.get('version')}")
    if manifest.get("apiVersion") != release.get("apiVersion"):
        error(rwhere, f"manifest apiVersion {manifest.get('apiVersion')} is not the catalog's {release.get('apiVersion')}")
    entry_assembly = manifest.get("entryAssembly", "")
    if not entry_assembly or prefix + entry_assembly not in names:
        error(rwhere, f"entryAssembly {entry_assembly!r} is not in the zip")
    if any(n.endswith(".pdb") for n in names):
        warn(rwhere, "ships a .pdb; release zips should not")


def host_api_range():
    """KHost main's (MinimumVersion, CurrentVersion); None when it cannot be read."""
    try:
        source = fetch(PLUGIN_API_URL).decode("utf-8")
    except Exception as ex:
        warn("host", f"could not read KHost's PluginApi.cs ({ex}); skipping the coverage check")
        return None
    current = re.search(r"CurrentVersion\s*=\s*(\d+)", source)
    minimum = re.search(r"MinimumVersion\s*=\s*(\d+)", source)
    if not current or not minimum:
        warn("host", "PluginApi.cs no longer declares CurrentVersion and MinimumVersion; update this check")
        return None
    return int(minimum.group(1)), int(current.group(1))


def check_coverage(plugins, api_range):
    minimum, current = api_range
    for entry in plugins:
        if not any(minimum <= r.get("apiVersion", 0) <= current for r in entry.get("releases", [])):
            warn(entry.get("name", "?"),
                 f"no release a current KHost can install (it runs plugin API {minimum}-{current})")


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    path, offline = argv[1], "--offline" in argv[2:]

    with open(path, encoding="utf-8") as handle:
        catalog = json.load(handle)

    plugins = check_shape(catalog)
    if not offline and not errors:
        for entry in plugins:
            for release in entry.get("releases", []):
                check_download(entry, release)
        if (api_range := host_api_range()) is not None:
            check_coverage(plugins, api_range)

    annotate = "--github" in argv[2:]
    for line in warnings:
        print(f"::warning::{line}" if annotate else f"warning: {line}")
    for line in errors:
        print(f"::error::{line}" if annotate else f"error: {line}")

    releases = sum(len(p.get("releases", [])) for p in plugins)
    print(f"{path}: {len(plugins)} plugins, {releases} releases, {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
