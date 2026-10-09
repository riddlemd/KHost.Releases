# KHost.Releases

Data that [KHost](https://github.com/riddlemd/KHost) fetches at runtime, published apart from the app so it can change without a KHost release. One file per kind of data, at the root.

| File | What it is | Read by |
|---|---|---|
| [`plugins.json`](plugins.json) | Every published release of every listed plugin | A host's **Plugins → Available** tab |

## How hosts read it

- Raw from `main` (KHost's default `PluginCatalog:Url`), so **a merge to `main` is live for every host**. GitHub's raw CDN caches for about 5 minutes.
- Only when the Available tab opens. A failed fetch keeps the host's cached copy.
- Anonymously, so everything listed must download without signing in.

## `plugins.json`

KHost's `PluginCatalog` model is the format's authority; [`tools/validate.py`](tools/validate.py) checks what it and the installer require.

- `schemaVersion`: a value a host does not know makes it reject the whole file.
- Per plugin: `id` (the manifest's id), `name`, `author`, `description`, `repository`, `capabilities`.
- Per release: `version`, `apiVersion` (the plugin API it was **built against**), `url` (https zip), `sha256`, `sizeBytes`, and `rid` (`win`/`macos`/`linux`, absent when it runs anywhere).

A host runs plugin APIs from its `MinimumVersion` to its `CurrentVersion` and installs, per plugin, the highest `version` in that range for its platform. So **releases are never removed**: older hosts keep finding the newest build they can run.

Plugins run inside the host unsandboxed, so this file is their trust root. A host installs only an https download matching its `sha256`, refuses zips with escaping entries, and refuses a manifest whose id or API range does not fit.

## Adding a release

1. Publish the plugin's GitHub release: public repo, tag `vX.Y.Z` matching the manifest, zip attached.
2. From a KHost checkout:

   ```bash
   dotnet run --project tools/KHost.CatalogSync -- riddlemd/KHost.Plugins.Chromecast
   dotnet run --project tools/KHost.CatalogSync -- riddlemd/KHost.Plugins.Spotify --rid win --asset KHost.Plugins.Spotify-1.0.0-win.zip
   ```

   It downloads anonymously, hashes, cross-checks GitHub's digest and writes the entry from the manifest into this checkout (`--catalog <path>` otherwise; `--tag`, `--capabilities` as needed).
3. `python3 tools/validate.py plugins.json`, then commit.

Never type a hash, size or `apiVersion` by hand.

## Checks

`.github/workflows/validate.yml` runs `validate.py` on push, PR, weekly and on demand. It fails on a shape a host would reject, on any release whose anonymous download, hash or size is wrong, and on a zip whose manifest disagrees with its listing. It warns when a plugin has no release KHost `main` can run. `--offline` checks shape only.
