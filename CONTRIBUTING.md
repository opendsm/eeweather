Contributing
============

Guidelines
----------

* Make sure you follow PEP 008 style guide conventions. CI runs
  `ruff check eeweather tests` for logic errors.
* Adding a weather-data source: see `docs/adding-a-source.md`.
* Adding a variable to the vocabulary: see `docs/expanding-the-vocabulary.md`.
* Commit messages should start with a capital letter ("Updated models", not "updated models").
* Write new tests and run old tests! Make sure that % test coverage does not decrease.
* Contributions are reviewed by a maintainer before acceptance. To facilitate
  review, please make a [pull request](https://github.com/opendsm/eeweather/pulls/new)
  against `master` from a branch prefixed `feature/` (new features) or `fix/`
  (bug fixes), describe the change, and follow the checklist in the pull
  request template.
* Contributions that add new required dependencies to the library will be
  given a more thorough review to ensure that those dependency additions
  1) do not pose a security risk and 2) are absolutely necessary.

Contributor maintenance responsibility
--------------------------------------

Contributions of all kinds are encouraged, and we do not require contributors
to be responsible for ongoing support of patches they make. However, because
we accept "toss over the wall" contributions, contributions deemed by the
maintainers to be too difficult to maintain will not be accepted.

Testing
-------

Please write tests for all new features. Test coverage must not fall. The
floor is `fail_under` in `pyproject.toml`, and CI's coverage job checks it
with `tox -e coverage`. Run the suite locally with
`docker-compose run --rm test`.

License
-------

This project is licensed under [Apache 2.0](LICENSE).

Developer Certificate of Origin
-------------------------------

This project uses the
[Developer Certificate of Origin](https://developercertificate.org/). Sign off
every commit with `git commit -s`, which adds a `Signed-off-by` line with your
name and email. The DCO check on each pull request fails when a commit lacks
it.

Release process
---------------

Pre-release

1. create branch off of master named `feature/<examplefeature>` or `fix/<>` and make desired changes.
2. edit CHANGELOG.md with changes under a new section called `Development`
3. create, review, and merge PR for feature/examplefeature
4. repeat steps 1-3 if desired for other features as convenient, though preference is for frequent version bumps

Releasing

5. make a new branch called release/vX.X.X
6. bump version - edit `__version__.py` with the new version
7. Rename `Development` section with the new version in CHANGELOG.md
8. commit changes, create and merge the release PR
9. create a GitHub release with a tag called vX.X.X; the publish workflow
   builds and uploads the package to pypi

Updating the internal db
------------------------

The scheduled `refresh-registry` workflow updates the live parts of the
packaged registry (GHCNh station list, observation inventory, quality
ratings) monthly and opens a pull request; review its diff, run the test
suite (some registry pins move as the registry ages), update snapshots as
warranted, and merge. To run the refresh by hand:

```
python -m eeweather.build
pytest
```

Static content (zone geometries and assignments, places, archive
station lists, identifier mappings) is carried forward from previously
packaged data; `python -m eeweather.build --migrate OLD DESTDIR` builds
the per-ownership data files (identifiers, geography pack, one per
source) from a historical single-file database.
