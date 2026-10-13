### Your checklist for this pull request

Please review the [guidelines for contributing](../CONTRIBUTING.md) to this repository.

- [ ] Make sure you are requesting to **pull a feature/fix branch** (right side). Don't request your master!
- [ ] Make sure tests pass (`docker-compose run --rm test`) and coverage has not fallen (CI's coverage job runs `tox -e coverage`).
- [ ] Update the [CHANGELOG.md](../CHANGELOG.md) to describe your changes in a bulleted list under the "Development" section at the top of the changelog. If this section does not exist, create it.
- [ ] Make sure code style follows PEP 008 using `docker-compose run --rm blacken`.
- [ ] Make sure `ruff check eeweather tests` passes (CI runs the same check).
- [ ] Make sure that new public functions and classes have [numpy-style docstrings](https://numpydoc.readthedocs.io/en/latest/format.html) and are documented in [docs/api.md](../docs/api.md).
- [ ] Make sure that all git commits have the "Signed-off-by" message for
  the Developer Certificate of Origin. When you're making a commit, just add
  the `-s/--signoff` flag (e.g., `git commit -s`).

### Description

\<description of pull request (suggestion: start by copying from your changelog update and elaborate if necessary.)>
