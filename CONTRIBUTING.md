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
  request template. CI runs the tests on every pull request.
* Contributions that add new required dependencies to the library will be
  given a more thorough review to ensure that those dependency additions
  1) do not pose a security risk and 2) are absolutely necessary.

Author responsibility
---------------------

AI tools (e.g., coding assistants and large language models) may be used for
any part of a contribution, including code, tests, documentation, and pull
request descriptions. Their use does not need to be disclosed, and the project
does not ask which tools were used. The author is responsible for all of the
contribution, however it was produced, and the rules below apply to every
contribution in the same way.

* You are responsible for everything you submit. Understand each change well
  enough to explain it in review. Maintainers may close a pull request whose
  author cannot, because review depends on the author answering questions
  about the change.
* Your `Signed-off-by` line certifies, under the Developer Certificate of
  Origin, that you have the right to submit every part of the contribution,
  including any part you did not write by hand.
* Statements in a pull request description are yours. Claim only what you
  have checked (e.g., that the suite passes on a platform or that returned
  values are unchanged), and say what you left unchecked.
* Do not change, skip, or loosen an existing test or snapshot to make a
  failing test pass. When a pull request changes an existing test or
  snapshot, its description explains why.
* Bug reports include a short, self-contained snippet that reproduces the
  problem, as the bug report template asks. Report security problems
  privately as [SECURITY.md](SECURITY.md) describes, never in a public issue.

Contributor maintenance responsibility
--------------------------------------

Contributions of all kinds are encouraged, and we do not require contributors
to be responsible for ongoing support of patches they make. However, because
we accept "toss over the wall" contributions, contributions deemed by the
maintainers to be too difficult to maintain will not be accepted.

Testing
-------

Please write tests for all new features, and pair each bug fix with a
regression test that fails without the fix.

Test coverage must not fall. The floor is `fail_under` in `pyproject.toml`,
and CI's coverage job checks it with `tox -e coverage`.

Tests are run using the following commands (flags are passed to the py.test
executable):

```
docker-compose run --rm test                         # run all tests

# cheat sheet of variations
docker-compose run --rm test tests/test_location.py  # run a specific suite
docker-compose run --rm test -k ghcnh                # filter for tests with `ghcnh` in the name
```

Test configuration can be found in `pyproject.toml` (`[tool.pytest.ini_options]`), `tox.ini`, and `tests/conftest.py`.

When writing tests using py.test fixtures, place fixtures as close as possible
to the test functions or classes that call them.

General Discussion
------------------

Discussions for this project take place on the
[opendsm@lists.lfenergy.org](https://lists.lfenergy.org/g/opendsm/)
mailing list.

License
-------

This project is licensed under [Apache 2.0](LICENSE).

Every source file must carry the following license header at the top, after
any shebang or encoding line:

``` python
# SPDX-FileCopyrightText: Contributors to the OpenDSM project
# SPDX-License-Identifier: Apache-2.0
```

The header carries no year, so it never needs updating. Keep the notices of
any third-party code a file adapts, and add that code's license to the
identifier line (e.g., `Apache-2.0 AND MIT`).

Developer Certificate of Origin
-------------------------------

This project uses the
[Developer Certificate of Origin](https://developercertificate.org/). Sign off
every commit with `git commit -s`, which adds a `Signed-off-by` line with your
name and email. The DCO check on each pull request fails when a commit lacks
it. The text of the certificate is copied below:

```
Developer Certificate of Origin
Version 1.1

Copyright (C) 2004, 2006 The Linux Foundation and its contributors.
1 Letterman Drive
Suite D4700
San Francisco, CA, 94129

Everyone is permitted to copy and distribute verbatim copies of this
license document, but changing it is not allowed.


Developer's Certificate of Origin 1.1

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I
    have the right to submit it under the open source license
    indicated in the file; or

(b) The contribution is based upon previous work that, to the best
    of my knowledge, is covered under an appropriate open source
    license and I have the right under that license to submit that
    work with modifications, whether created in whole or in part
    by me, under the same open source license (unless I am
    permitted to submit under a different license), as indicated
    in the file; or

(c) The contribution was provided directly to me by some other
    person who certified (a), (b) or (c) and I have not modified
    it.

(d) I understand and agree that this project and the contribution
    are public and that a record of the contribution (including all
    personal information I submit with it, including my sign-off) is
    maintained indefinitely and may be redistributed consistent with
    this project or the open source license(s) involved.
```

Charter
-------

eeweather is developed under the charter of the OpenDSM project, which can be
found in [CHARTER](https://github.com/opendsm/opendsm/blob/master/CHARTER.md)
in the opendsm repository and contains the following sections:

1. Mission and Scope of the Project
2. Technical Steering Committee
3. TSC Voting
4. Compliance with Policies
5. Community Assets
6. General Rules and Operations
7. Intellectual Property Policy
8. Amendments

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

Other resources
---------------

- [README](README.md): basic project information shown on the PyPI project page.
- [MAINTAINERS](https://github.com/opendsm/opendsm/blob/master/MAINTAINERS.md): an ordered list of OpenDSM project maintainers.
- [LICENSE](LICENSE): Apache 2.0.
- [CHARTER](https://github.com/opendsm/opendsm/blob/master/CHARTER.md): open source project charter.
- [CODE_OF_CONDUCT](CODE_OF_CONDUCT.md): code of conduct for contributors.
- [SECURITY](SECURITY.md): how to report a vulnerability.
