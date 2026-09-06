"""Disaster Factor package.

Exposes the package version via ``__version__``, sourced from installed
package metadata. Falls back to ``"0+unknown"`` in editable installs
where metadata may not yet be available.
"""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("disaster_factor")
except PackageNotFoundError:
    # Fallback for editable installs before metadata is available
    __version__ = "0+unknown"

__all__ = ["__version__"]
