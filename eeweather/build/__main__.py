"""Packaged-data maintenance entry point.

``python -m eeweather.build`` refreshes the live parts of the packaged
data (GHCNh catalog, observation inventory, quality ratings, identity
rows for new stations) in place. ``python -m eeweather.build --migrate
OLD DESTDIR`` builds the packaged data files from a single-file
ghcn-keyed database.
"""
import argparse

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
    args = parser.parse_args()

    if args.migrate:
        counts = migrate(args.migrate[0], args.migrate[1])
    else:
        counts = refresh()
    print(counts)


if __name__ == "__main__":
    main()
