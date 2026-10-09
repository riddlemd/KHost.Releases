# AGENTS.md

Data KHost hosts fetch at runtime, raw from `main`. See [README.md](README.md) for the format and how hosts choose a release.

## Rules

- **A merge to `main` is a production deploy** to every host, with no build in between. `plugins.json` is the plugins' trust root.
- **Releases only through KHost's `CatalogSync`** (run from a KHost checkout). Never type or paste a `sha256`, `sizeBytes` or `apiVersion`; `name`, `description` and `capabilities` may be edited by hand.
- **Never remove a release**: older hosts install them. Remove one only if its download is gone for good or it was listed by mistake, and say which in the commit.
- **Public repos only**: hosts fetch anonymously. Check `gh repo view <repo> --json visibility` first; a private plugin is never listed.
- **One file per kind of data, at the root.** A new kind needs a KHost change that reads it first.
- **A format change** (or `schemaVersion` bump) goes with the KHost release that reads it, and updates `tools/validate.py`.
- Keep the file as `CatalogSync` writes it (indentation, key order, `\u0027` escapes) so diffs stay one release wide.

## Before committing

`python3 tools/validate.py plugins.json` must report `0 errors`. A warning that a plugin has nothing KHost `main` can run means the plugin needs a rebuild, not a catalog edit.

Do not commit or push unless asked. Never force-push `main`.
