# AGENTS.md

**KHost.Releases**: data that KHost hosts fetch at runtime, raw from `main`. No code ships from here except the checks in `tools/` and `.github/`. Read [README.md](README.md) for the formats and the selection rule.

## What a change here does

- **A merge to `main` is live for every host at once.** There is no build, no release, no rollback beyond another commit. Treat every edit as a production deploy.
- `plugins.json` is the **trust root** for plugins, which run unsandboxed inside the host. Its hashes are what stop a swapped download from running.
- Changing `schemaVersion` makes every host that does not know the new value reject the whole file. Only do it together with a KHost release that reads it, and say so in the PR.

## Rules

- **Add or update a release only with KHost's sync tool** (`dotnet run --project tools/KHost.CatalogSync -- <owner/repo> [--tag vX] [--asset name.zip] [--rid win|macos|linux]`, run from a KHost checkout). It downloads anonymously, hashes, cross-checks GitHub's digest and reads the manifest through the host's own payload reader. Never type or paste a `sha256`, `sizeBytes` or `apiVersion`.
- **Never remove a release** to "clean up" or because a newer one exists. Hosts pick the newest release in their own plugin API range; an old entry is what an older host installs. Remove one only when its download is gone for good or it was listed by mistake, and say which in the commit.
- **Only public repos.** A host fetches anonymously, so a private repo's asset is a 404 to it. `gh repo view <repo> --json visibility` before listing anything. `KHost.Plugins.KaraFun` is private and is never listed.
- **`apiVersion` is what the build was built against**, copied from its manifest by the tool. Never edit it to make a release show up on a host; rebuild the plugin instead.
- **One file per kind of data, at the root, with its JSON Schema beside it** (`plugins.json` + `plugins.schema.json`). A new kind needs a KHost change that reads it first; do not add a file nothing fetches.
- **A format change touches three places**: KHost's model (the authority), `tools/validate.py`, and the `.schema.json`. Keep the `$schema` line first in each data file; KHost's sync tool preserves it.
- Presentation (`name`, `description`, `capabilities`) may be edited by hand. Everything under `releases` may not.
- Keep the file as the sync tool writes it (its indentation, key order and `'` escapes), so diffs stay one release wide.

## Before committing

```bash
python3 tools/validate.py plugins.json
```

It must end with `0 errors`. It downloads every release, so it needs the network; `--offline` checks only the shape. A warning that a plugin has no release KHost `main` can run means that plugin needs a rebuild and release, not a catalog edit.

## Commits

- One plugin release (or one platform build of it) per commit where practical, named for what a host gains: `List Chromecast 1.0.1 (plugin API 1)`.
- Do not commit or push unless asked. Never force-push `main`: hosts may have fetched any commit on it.

## Related

- KHost (the host, `PluginApi`, the sync tool, the installer): https://github.com/riddlemd/KHost. Its AGENTS.md "Plugin catalog and installs" section is the host-side half of these rules.
- Plugin repos: `riddlemd/KHost.Plugins.*`. Each release zip holds `manifest.json`, the entry assembly and its `.deps.json`; no `.pdb`, no KHost contract assemblies.
