# Disaster Factor

Business Continuity Disaster Tracker.

## Requirements
- Python >= 3.10

## Installation

Using Poetry (recommended):
```bash
poetry install
```

Using pip:
```bash
python -m venv .venv
. .venv/bin/activate
pip install .
```

## Usage

Run via module (works in both Poetry and pip installs):
```bash
python -m disaster_factor --version
python -m disaster_factor track
```

If you add a console script entry point later, the installed command will mirror the same subcommands.

## Contributing

Set up a dev environment and run tests:
```bash
# with Poetry
deactivate 2>/dev/null || true
poetry install --with dev
poetry run pytest -q

# or with pip
python -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
pytest -q
```

## License

MIT License. See `LICENSE`.
