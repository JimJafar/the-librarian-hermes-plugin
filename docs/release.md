# Releasing the Hermes plugin

This is the per-repo release file. The full cross-family runbook
(branching strategy, semver rules, version-coordination across the
plugin family) lives in the monorepo at
[`the-librarian/docs/release-runbook.md`](https://github.com/JimJafar/the-librarian/blob/main/docs/release-runbook.md).
Read that first if you're new to releases here.

## When to cut a release

Any merged PR that's user-visible (provider behaviour change, gateway
hook change, install / config change, README claim change) earns a
release. Internal-only refactors, test-only changes, and CI-only
changes don't.

A coordinated cross-repo change ships at the **same MINOR version**
as the monorepo. PATCH numbers drift freely.

## Semver, the short version

- **MAJOR** — provider interface break, gateway hook signature break,
  removal of a public function in `librarian/`.
- **MINOR** — new provider method, new gateway hook, additive feature,
  new env var with a default.
- **PATCH** — bug fix, doc tweak, internal refactor, test-only change.

## Hermes specifics: no embedded version file

Hermes installs this plugin by cloning the repo into
`~/.hermes/plugins/the-librarian-hermes-plugin/` and discovering it by
directory structure. There's no `package.json`, no `setup.py`, no
embedded `version` field anywhere. **The release is purely a git tag +
GitHub release for traceability** — users update via
`hermes plugins update the-librarian-hermes-plugin`, which re-pulls the
latest commit on the default branch (not the tag).

That means the tag is for *us* (changelog anchor, release notes
correlation across the family), not for the install path.

## Steps

```sh
cd ~/code/the-librarian-hermes-plugin
git checkout main && git pull

# 1. Move CHANGELOG [Unreleased] entries under [vX.Y.Z] - YYYY-MM-DD.
NEW=<X.Y.Z>
$EDITOR CHANGELOG.md

# 2. Branch, commit, PR
git checkout -b release/v$NEW
git add CHANGELOG.md
git commit -m "chore(release): v$NEW"
git push -u origin release/v$NEW
gh pr create --title "chore(release): v$NEW"

# 3. After CI green + merge
git checkout main && git pull
git tag -a v$NEW -m "v$NEW"
git push origin v$NEW
gh release create v$NEW --title "v$NEW" --notes-from-tag
```
