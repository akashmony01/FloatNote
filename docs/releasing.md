# Releasing FloatNote

Releases are built and published by GitHub Actions (`.github/workflows/release.yml`) when you push a version tag.

1. Update the version in `src/floatnote/__init__.py` (`__version__ = "1.1.0"`).
2. Add a `## [1.1.0] - YYYY-MM-DD` section at the top of `CHANGELOG.md` (and the link at the bottom). This text becomes the release notes.
3. Run the tests: `.venv/bin/pytest -q`.
4. Commit, then tag and push:

   ```bash
   git commit -am "Release 1.1.0"
   git tag v1.1.0
   git push origin main v1.1.0
   ```

The workflow then:

- runs the tests and checks `install.sh`,
- stops if the tag doesn't match `__version__` or the changelog has no section for it,
- builds `floatnote-<version>.tar.gz` (source + `install.sh`), a stable-named copy `floatnote.tar.gz`, a Python wheel and `SHA256SUMS`,
- creates the GitHub Release with those files and the changelog section as notes.

If a release fails, fix the problem, delete the tag (`git tag -d v1.1.0 && git push origin :refs/tags/v1.1.0`) and tag again.
