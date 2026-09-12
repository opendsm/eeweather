Contributing
============

Guidelines
----------

* Make sure you follow PEP 008 style guide conventions.
* Adding a weather-data source: see `docs/adding-a-source.md`.
* Adding a variable to the vocabulary: see `docs/expanding-the-vocabulary.md`.
* Commit messages should start with a capital letter ("Updated models", not "updated models").
* Write new tests and run old tests! Make sure that % test coverage does not decrease.

Release process
---------------

Pre-release

1. create branch off of master named `feature/<examplefeature>` or `bugfix/<>` and make desired changes.
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

The scheduled `refresh-geography` workflow rebuilds the geography
pack's ZCTA places from Census primary sources once a year and opens a
pull request the same way. To run it by hand:

```
pip install -e .[build]
python -m eeweather.build --geography        # or --geography 2025
pytest
```

Remaining static content (zone geometries, archive station lists,
identifier mappings) is carried forward from previously packaged data;
`python -m eeweather.build --migrate OLD DESTDIR` builds the
per-ownership data files (identifiers, geography pack, one per source)
from a historical single-file database.
