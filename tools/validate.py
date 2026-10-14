#!/usr/bin/env python3
"""Checks a KHost catalog file the way a host will read it, then downloads every release to prove it.

    python3 tools/validate.py plugins.json            # shape, downloads, manifests, contracts, host coverage
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
BUILD_PROPS_URL = "https://raw.githubusercontent.com/riddlemd/KHost/main/Directory.Build.props"
# Every release built against contracts 0.61 declares this; 1.x hosts run them, older hosts read only it.
LEGACY_API_VERSION = 8
LEGACY_CONTRACTS = (0, 61)
SEMVER = re.compile(
    r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?")
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


def parse_semver(text):
    """(major, minor, patch, prerelease identifiers or None) for a semantic version; None otherwise."""
    match = SEMVER.fullmatch(str(text).strip()) if text is not None else None
    if not match:
        return None
    prerelease = match.group(4)
    return int(match.group(1)), int(match.group(2)), int(match.group(3)), prerelease.split(".") if prerelease else None


def semver_key(version):
    """Sorts as semantic versioning orders: a prerelease before its release, numeric ids before others."""
    major, minor, patch, prerelease = version
    if prerelease is None:
        return (major, minor, patch, 1, ())
    ids = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in prerelease)
    return (major, minor, patch, 0, ids)


def format_semver(version):
    major, minor, patch, prerelease = version
    return f"{major}.{minor}.{patch}" + (f"-{'.'.join(prerelease)}" if prerelease else "")


def is_legacy(version):
    return version[:2] == LEGACY_CONTRACTS


def legacy_api_version_for(version):
    """What CatalogSync writes as apiVersion, so hosts predating contractsVersion refuse anything newer."""
    return LEGACY_API_VERSION if is_legacy(version) else LEGACY_API_VERSION + 1


def release_requirement(release):
    """The contracts a listed release needs, as a host reads it; None when a host cannot judge it."""
    if release.get("contractsVersion") is not None:
        return parse_semver(release["contractsVersion"])
    return (0, 61, 0, None) if release.get("apiVersion") == LEGACY_API_VERSION else None


def host_covers(host, required):
    """KHost's rule: same major (0.61.x counts as major 1) and no newer than the host."""
    same_line = required[0] == host[0] or (host[0] == 1 and is_legacy(required))
    return same_line and semver_key(required) <= semver_key(host)


def deps_requirement(archive, path):
    """The KHost.Abstractions version a plugin's .deps.json names; None when absent or unreadable."""
    try:
        deps = json.loads(archive.read(path).decode("utf-8-sig"))
    except (KeyError, ValueError, UnicodeDecodeError):
        return None
    libraries = deps.get("libraries") if isinstance(deps, dict) else None
    if not isinstance(libraries, dict):
        return None
    for name in libraries:
        if name.lower().startswith("khost.abstractions/"):
            return parse_semver(name.split("/", 1)[1])
    return None


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
            contracts = release.get("contractsVersion")
            if contracts is not None:
                if parse_semver(contracts) is None:
                    error(rwhere, f"contractsVersion must be a semantic version (Major.Minor.Patch), is {contracts!r}")
                elif api != legacy_api_version_for(parse_semver(contracts)):
                    error(rwhere, f"apiVersion must be {legacy_api_version_for(parse_semver(contracts))} "
                                  f"for contractsVersion {contracts}, is {api!r}")
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
    # A listing written before contractsVersion copied the manifest's number; a newer one derives it.
    if manifest.get("apiVersion") is not None and release.get("contractsVersion") is None \
            and manifest.get("apiVersion") != release.get("apiVersion"):
        error(rwhere, f"manifest apiVersion {manifest.get('apiVersion')} is not the catalog's {release.get('apiVersion')}")
    entry_assembly = manifest.get("entryAssembly", "")
    if not entry_assembly or prefix + entry_assembly not in names:
        error(rwhere, f"entryAssembly {entry_assembly!r} is not in the zip")
    else:
        deps_path = prefix + entry_assembly.rsplit(".", 1)[0] + ".deps.json"
        required = deps_requirement(archive, deps_path)
        if required is None and manifest.get("apiVersion") == LEGACY_API_VERSION:
            required = (0, 61, 0, None)
        listed = release.get("contractsVersion")
        if required is None:
            error(rwhere, f"{deps_path} names no KHost.Abstractions and the manifest has no apiVersion "
                          f"{LEGACY_API_VERSION}; a host refuses it")
        elif listed is not None and parse_semver(listed) is not None \
                and semver_key(parse_semver(listed)) != semver_key(required):
            error(rwhere, f"the zip needs contracts {format_semver(required)}, the catalog says {listed}")
    if any(n.endswith(".pdb") for n in names):
        warn(rwhere, "ships a .pdb; release zips should not")


def host_contracts():
    """KHost main's ContractsVersion when it is 1.0.0 or later; None while main still gates on PluginApi."""
    try:
        source = fetch(BUILD_PROPS_URL).decode("utf-8")
    except Exception as ex:
        warn("host", f"could not read KHost's Directory.Build.props ({ex}); trying PluginApi.cs")
        return None
    match = re.search(r"<ContractsVersion>\s*([^<]+?)\s*</ContractsVersion>", source)
    version = parse_semver(match.group(1)) if match else None
    return version if version is not None and version[0] >= 1 else None


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


def check_contracts_coverage(plugins, host):
    for entry in plugins:
        if not any((required := release_requirement(r)) is not None and host_covers(host, required)
                   for r in entry.get("releases", [])):
            warn(entry.get("name", "?"),
                 f"no release a current KHost can install (it has contracts {format_semver(host)})")


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
        if (host := host_contracts()) is not None:
            check_contracts_coverage(plugins, host)
        elif (api_range := host_api_range()) is not None:
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
