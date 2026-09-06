"""Module execution entry point for Disaster Factor.

Invoked when the package is run directly with ``python -m disaster_factor``.
Delegates immediately to the CLI entry point.
"""

from .cli import main

# Module Execution Path
# Runs when calling `python3 -m disaster_factor` in CLI
# This is the "Main" entrypoint
if __name__ == "__main__":
    raise SystemExit(main())
