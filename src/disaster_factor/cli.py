import argparse
import sys
from pathlib import Path

from . import __version__
from .core import track_disasters


def _default_prog() -> str:
    # Derive a sensible display name from the invoked script/module
    return Path(sys.argv[0]).name or "python"


def _cmd_track(args: argparse.Namespace) -> int:
    track_disasters(debug=getattr(args, "debug", False))
    return 0


def _build_parser(prog: str | None = None) -> argparse.ArgumentParser:
    prog = prog or _default_prog()
    parser = argparse.ArgumentParser(prog=prog, description=(__doc__ or ""))
    parser.add_argument(
        "--version",
        action="version",
        version=f"{prog} {__version__}",
        help="Show version and exit",
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest="command")
    sp_track = subparsers.add_parser("track", help="Track current disasters")
    sp_track.add_argument(
        "--debug",
        action="store_true",
        help=(
            "Run in debug mode: skip launching the web UI server and just write "
            "affected.csv, prelim.csv, and points.json plus console output."
        ),
    )
    sp_track.set_defaults(func=_cmd_track)

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    parser = _build_parser()

    if not argv:
        parser.print_help()
        return 0

    args = parser.parse_args(argv)
    if hasattr(args, "func"):
        return int(args.func(args) or 0)

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
