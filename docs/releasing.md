# Releasing FloatNote

Releases are built and published by GitHub Actions (`.github/workflows/release.yml`) when you push a version tag.

1. Update the version in `src/floatnote/__init__.py` (`__version__ = "1.1.0"`).
2. Add a `## [1.1.0] - YYYY-MM-DD` section at the top of `CHANGELOG.md` (and the link at the bottom). This text becomes the release notes.
3. Run the tests: `.venv/bin/pytest -q`, and go through [desktop-test-checklist.md](desktop-test-checklist.md) on the desktops you can (at least the one the change is about).
4. Commit, then tag and push:

   ```bash
   git commit -am "Release 1.1.0"
   git tag v1.1.0
   git push origin main v1.1.0
   ```

The workflow then:

- runs the tests and checks `install.sh`,
- stops if the tag doesn't match `__version__` or the changelog has no section for it,
- builds `floatnote-<version>.tar.gz` (source + `install.sh`), a Python wheel, the Debian/Ubuntu/Mint package `floatnote_<version>_all.deb` (`packaging/build-deb.sh`), the Fedora/openSUSE package `floatnote-<version>-1.noarch.rpm` (`packaging/build-rpm.sh`, in a Fedora container), stable-named copies `floatnote.tar.gz`, `floatnote.deb` and `floatnote.rpm` (for the `releases/latest/download/` links in the README) and `SHA256SUMS`,
- creates the GitHub Release with those files and the changelog section as notes.

If a release fails, fix the problem, delete the tag (`git tag -d v1.1.0 && git push origin :refs/tags/v1.1.0`) and tag again.
