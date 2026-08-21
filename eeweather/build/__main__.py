"""Packaged-data maintenance entry point.

``python -m eeweather.build`` refreshes the live parts of the packaged
data (GHCNh catalog, observation inventory, quality ratings, identity
rows for new stations) in place. ``python -m eeweather.build --migrate
OLD DESTDIR`` builds the packaged data files from a single-file
ghcn-keyed database. ``python -m eeweather.build --geography [YEAR]``
rebuilds the geography pack's places from Census primary sources.
"""
import argparse

from .geography import build_places
from .migrate import migrate
from .refresh import refresh



def main():
    parser = argparse.ArgumentParser(prog="python -m eeweather.build")
    parser.add_argument(
        "--migrate",
        nargs=2,
        metavar=("OLD", "DESTDIR"),
        help="build the packaged data files from a single-file db",
    )
    parser.add_argument(
        "--geography",
        nargs="?",
        const=True,
        metavar="YEAR",
        help="rebuild the geography pack's places from Census sources,"
        " optionally pinned to a vintage year",
    )
    args = parser.parse_args()

    if args.geography:
        year = None if args.geography is True else int(args.geography)
        counts = build_places(year=year)
    elif args.migrate:
        counts = migrate(args.migrate[0], args.migrate[1])
    else:
        counts = refresh()
    print(counts)


if __name__ == "__main__":
    main()
