# KHost.Releases

Data that [KHost](https://github.com/riddlemd/KHost) fetches at runtime, published separately from the app so it can change without a KHost release.

| File | What it is | Who reads it |
|---|---|---|
| [`plugins.json`](plugins.json) | The plugin catalog: every published release of every listed plugin | A host's **Plugins → Available** tab, each time it opens |
| [`plugins.schema.json`](plugins.schema.json) | JSON Schema for `plugins.json`, named by its `$schema` line | Editors, for completion and inline errors |

One file per kind of data, at the root, each with its schema beside it. A new kind gets both files and its own section here.

The schemas help editors; they are not the authority. A host reads these files into its own model (KHost's `Abstractions`), and `tools/validate.py` checks what that model and the installer actually require. A format change updates all three. A plugin's own `manifest.json` schema stays in KHost (`src/KHost.Abstractions/Models/Plugins/manifest.schema.json`), because it changes with the plugin API, not with this data.

## How a host reads it

- Raw from `main`: `https://raw.githubusercontent.com/riddlemd/KHost.Releases/main/plugins.json`, the default `PluginCatalog:Url` in KHost's `appsettings.json`. **A merge to `main` is live for every host immediately**; there is no build in between.
- Fetched only when the Available tab opens, never at startup. A failed fetch keeps the host's cached copy and shows the error.
- Anonymous: hosts send no credentials, so everything listed must be downloadable without signing in. A private repo's release is a 404 to a host.

## `plugins.json`

```json
{
  "schemaVersion": 1,
  "plugins": [
    {
      "id": "c7a41e92-3d58-4b06-8f13-6ad9c25e7b40",
      "name": "Chromecast",
      "author": "KHost",
      "description": "Sends the song to a Chromecast receiver on the local network.",
      "repository": "https://github.com/riddlemd/KHost.Plugins.Chromecast",
      "capabilities": ["Display provider"],
      "releases": [
        {
          "version": "1.0.0",
          "apiVersion": 1,
          "url": "https://github.com/riddlemd/KHost.Plugins.Chromecast/releases/download/v1.0.0/KHost.Plugins.Chromecast-1.0.0.zip",
          "sha256": "…64 hex…",
          "sizeBytes": 1197569
        }
      ]
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `schemaVersion` | The document format. A host that does not know the value rejects the **whole** file, so changing it empties every host's Available tab until hosts update. |
| `id` | The plugin's `manifest.json` id. How a host matches a listing to an installed plugin. |
| `name`, `author`, `description`, `repository`, `capabilities` | What the Available tab shows. Presentation lives here, not in the plugin's manifest. |
| `releases[].version` | The plugin's own version (up to four numbers). |
| `releases[].apiVersion` | The KHost plugin API the build was **built against** (its manifest's `apiVersion`). |
| `releases[].url` | An https download of the release zip. |
| `releases[].sha256` | Hex SHA-256 of that zip, computed from an anonymous download. A host refuses a download that does not match. |
| `releases[].sizeBytes` | The zip's size, for the progress bar. |
| `releases[].rid` | `win`, `macos` or `linux` for a build that only runs there; absent for a build that runs anywhere (the goal). |

### Which release a host installs

A host runs plugins built against any plugin API from its `MinimumVersion` to its `CurrentVersion` (both in KHost's `PluginApi`). It picks, per plugin, the **highest `version`** whose `apiVersion` is in that range, then the release for its own platform over a neutral one. A plugin with nothing in range shows as not compatible, with the reason.

So releases are **never removed**. An older host keeps finding the newest build it can run; a newer host finds the newest build overall. A release only leaves the file if its download is gone for good, or it was listed by mistake.

### Trust

The catalog is KHost's trust root for plugins: a plugin runs inside the host with the host's access, unsandboxed. A host installs only an https download whose SHA-256 matches this file, checks every zip entry for path escapes before writing any, and refuses a manifest whose id differs from the listing or whose `apiVersion` is outside its range. So a wrong hash here breaks installs, and a wrong URL with a matching hash is the one thing review must catch.

## Adding or updating a release

1. Publish the plugin's GitHub release first (public repo, zip attached, tag `vX.Y.Z` matching the manifest's `version`).
2. From a KHost checkout, run its sync tool. It downloads the zip anonymously, hashes it, cross-checks GitHub's own digest, unpacks it through the host's payload reader and writes the entry from the manifest:

   ```bash
   dotnet run --project tools/KHost.CatalogSync -- riddlemd/KHost.Plugins.Chromecast
   dotnet run --project tools/KHost.CatalogSync -- riddlemd/KHost.Plugins.Spotify --rid win --asset KHost.Plugins.Spotify-1.0.0-win.zip
   ```

   It writes to `KHost.Releases/main/plugins.json` beside the KHost checkout (or pass `--catalog <path>`). `--tag` picks a release other than the latest; `--capabilities "a,b"` sets them for a plugin's first listing.
3. Run the checks locally, then open a PR (or push to `main`):

   ```bash
   python3 tools/validate.py plugins.json
   ```

Never type a hash by hand. Never copy GitHub's digest into the file: the sync tool computes the hash from its own download and only cross-checks GitHub's.

## Checks

`.github/workflows/validate.yml` runs [`tools/validate.py`](tools/validate.py) on every push and PR, weekly (an asset can vanish long after its entry merged), and on demand. It fails on:

- a shape a host would reject or misread: unknown `schemaVersion`, a missing or repeated id, no releases, a version a host cannot parse, a non-https URL, a malformed hash, an unknown `rid`, the same version and platform twice, or a written `isInstallable` (the host derives it);
- any release whose anonymous download fails, or whose SHA-256 or size differs from the file;
- a zip with an escaping entry, no `manifest.json` (at its root or in one wrapping folder), an entry assembly the zip lacks, or a manifest whose id, version or `apiVersion` differs from the listing.

It warns when a listed plugin has no release that KHost `main` can run (read from KHost's `PluginApi.cs`), and when a zip carries a `.pdb`.

`--offline` runs only the shape checks.
