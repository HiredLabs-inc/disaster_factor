"""Helper utilities for static file serving and geographic coordinate projection.

Provides functions to prepare and serve the dashboard static assets over a
local HTTP server, open the dashboard in a browser, and project geographic
coordinates to pixel positions using a Mercator projection.
"""

from importlib.resources import files
import logging
import webbrowser
import math
import tempfile
import threading
import time
import shutil
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from functools import partial
import json
from urllib.parse import urlparse, parse_qs
from typing import Optional

logger = logging.getLogger(__name__)

# One-time open guard to avoid duplicate tabs when invoked multiple times
_DASHBOARD_OPENED = False
# Strong reference to the server instance to prevent garbage collection
_httpd_instance: Optional[ThreadingHTTPServer] = None


def _find_static_source() -> Optional[Path]:
    """Find a static/ directory, preferring the development source tree.

    Searches in the following order:
        1. Source under current working directory: ``./src/disaster_factor/static``
        2. Source under the nearest ``pyproject.toml`` root:
           ``<root>/src/disaster_factor/static``
        3. Source alongside this module file (may be site-packages if installed).
        4. Installed package resources via ``importlib.resources``.

    Returns:
        Path to the static directory if found, or None if no location exists.
    """
    # 1) under CWD
    p2 = Path.cwd() / "src" / "disaster_factor" / "static"
    if p2.exists():
        return p2

    # 2) nearest pyproject root
    cur = Path.cwd()
    for parent in [cur, *cur.parents]:
        if (parent / "pyproject.toml").exists():
            p3 = parent / "src" / "disaster_factor" / "static"
            if p3.exists():
                return p3
            break

    # 3) alongside module (could be installed site-packages)
    p1 = Path(__file__).parent / "static"
    if p1.exists():
        return p1

    # 4) installed package resources
    try:
        return Path(files("disaster_factor").joinpath("static")._paths[0])  # type: ignore[attr-defined]
    except Exception:
        return None


def get_dashboard() -> str:
    """Read and return the dashboard HTML content.

    Prefers the local source tree during development. Falls back to the
    installed package resources if no source tree is found.

    Returns:
        The full HTML content of ``dashboard_2.html`` as a string.
    """
    # Prefer local source tree during development
    src = _find_static_source()
    if src and (src / "dashboard_2.html").exists():
        return (src / "dashboard_2.html").read_text(encoding="utf-8")

    dashboard_path = files("disaster_factor").joinpath("static", "dashboard_2.html")
    return dashboard_path.read_text(encoding="utf-8")


def open_dashboard_in_browser() -> Path:
    """Write the dashboard HTML to a temporary file and return its path.

    Does not auto-open a browser. The caller is responsible for opening
    the returned path if needed.

    Returns:
        Path to the temporary HTML file written to disk.
    """
    html = get_dashboard()
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write(html)
        tmp_path = Path(f.name)

    return tmp_path


def _copy_traversable_to_dir(trav, dest: Path) -> None:
    """Recursively copy an ``importlib.resources`` traversable to a directory.

    Args:
        trav: An ``importlib.resources`` traversable object representing a
            package resource directory.
        dest: Destination directory path. Created if it does not exist.
    """
    dest.mkdir(parents=True, exist_ok=True)
    for item in getattr(trav, 'iterdir', lambda: [])():
        if item.is_dir():
            _copy_traversable_to_dir(item, dest / item.name)
        elif item.is_file():
            with item.open("rb") as srcf, open(dest / item.name, "wb") as dstf:
                shutil.copyfileobj(srcf, dstf)


def _copy_tree(src: Path, dest: Path) -> None:
    """Recursively copy all files from src to dest, preserving structure.

    Silently does nothing if src is falsy or does not exist.

    Args:
        src: Source directory to copy from.
        dest: Destination directory to copy into. Intermediate directories
            are created as needed.
    """
    if not src or not src.exists():
        return
    for p in src.rglob('*'):
        if p.is_dir():
            continue
        rel = p.relative_to(src)
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, out)


# Python-side transform functions.
# Translates geocoordinates in lat/long into x/y pixels

def mercator(lat: float) -> float:
    """Return the Mercator projection y-value for a given latitude.

    Clamps latitude to avoid singularities at the poles.

    Args:
        lat: Latitude in degrees.

    Returns:
        The Mercator y-value as a float.
    """
    # prevent tan() overflow near the poles
    max_lat = 89.9999
    lat = max(-max_lat, min(max_lat, float(lat)))
    rad = math.radians(lat)
    return math.log(math.tan(math.pi / 4.0 + rad / 2.0))


def get_y(h: int, lat: float, lat_t: float, lat_b: float) -> float:
    """Compute the pixel Y coordinate for a latitude using Mercator projection.

    Handles pole clamping, ensures correct top/bottom ordering, and guards
    against zero-denominator cases.

    Args:
        h: Height of the image in pixels.
        lat: Latitude to project, in degrees.
        lat_t: Latitude at the top edge of the image, in degrees.
        lat_b: Latitude at the bottom edge of the image, in degrees.

    Returns:
        Pixel Y coordinate clamped to [0, h].
    """
    lat_t = float(lat_t)
    lat_b = float(lat_b)
    # Ensure ordering: lat_t should be the northern/top latitude (larger value)
    if lat_b > lat_t:
        lat_t, lat_b = lat_b, lat_t

    # Use mercator() helper which already clamps extreme latitudes
    m_top = mercator(lat_t)
    m_bottom = mercator(lat_b)
    denom = m_top - m_bottom
    if denom == 0:
        return float(h) / 2.0

    m_lat = mercator(lat)
    # y = 0 at top, y = h at bottom
    y = float(h) * (m_top - m_lat) / denom
    return max(0.0, min(float(h), y))


def get_x(lon: float, lon_c: float, w: int) -> float:
    """Compute the pixel X coordinate for a longitude.

    Normalizes the longitude delta to [-180, 180] to handle antimeridian
    wrapping, then maps to pixel coordinates with the center longitude at w/2.

    Args:
        lon: Longitude to project, in degrees.
        lon_c: Center longitude of the image, in degrees.
        w: Width of the image in pixels.

    Returns:
        Pixel X coordinate clamped to [0, w].
    """
    # normalize into [-180, 180)
    delta = (float(lon) - float(lon_c) + 180.0) % 360.0 - 180.0
    x = (delta / 360.0) * float(w) + (float(w) / 2.0)
    return max(0.0, min(float(w), x))


def transform_latlon_to_xy(lat: float, lon: float, config: dict, w: int, h: int) -> tuple[float, float]:
    """Map a lat/lon coordinate to pixel (x, y) for an image of size w x h.

    Uses a Mercator projection. Projection bounds and center longitude are
    read from config, with sensible defaults.

    Args:
        lat: Latitude in degrees.
        lon: Longitude in degrees.
        config: Dictionary of projection parameters. Recognised keys:
            - ``lat_t``: Latitude at the top of the image (default 90).
            - ``lat_b``: Latitude at the bottom of the image (default -90).
            - ``lon_c``: Center longitude of the image (default 0).
        w: Width of the image in pixels.
        h: Height of the image in pixels.

    Returns:
        A tuple (x, y) in pixel coordinates, with (0, 0) at the top-left.
        Both values are clamped to the image bounds.
    """
    lat_t = float(config.get('lat_t', 90.0))
    lat_b = float(config.get('lat_b', -90.0))
    lon_c = float(config.get('lon_c', 0.0))

    x = get_x(lon, lon_c, w)
    y = get_y(h, lat, lat_t, lat_b)

    # final clamp and return
    x = max(0.0, min(float(w), x))
    y = max(0.0, min(float(h), y))
    return (x, y)


def _prepare_static_files() -> Path:
    """Copy static assets to a temporary directory and prepare them for serving.

    Resolves the static source using ``_find_static_source()``, copies all
    files to a fresh temporary directory, ensures the dashboard HTML exists,
    and injects a cache-busting query string into the map.svg reference.

    Returns:
        Path to the ``static/`` subdirectory inside the temporary directory.
    """
    tmpd = Path(tempfile.mkdtemp())
    static_root = tmpd / "static"

    # Prefer live source static if present
    src_static = _find_static_source()
    if src_static is not None:
        logger.debug("Using static source: %s", src_static)
        _copy_tree(src_static, static_root)

    else:
        # Fallback: try importlib.resources
        try:
            static_trav = files("disaster_factor").joinpath("static")
            _copy_traversable_to_dir(static_trav, static_root)
            logger.debug("Using installed package static resources")
        except Exception as e:
            logger.debug("No static resources found: %s", e)
    logger.debug("Files in static_root (%s):", static_root)
    for f in static_root.rglob('*'):
        logger.debug("  %s", f.relative_to(static_root))
    # Ensure dashboard exists at minimum
    if not (static_root / "dashboard_2.html").exists():
        (static_root).mkdir(parents=True, exist_ok=True)
        (static_root / "dashboard_2.html").write_text(get_dashboard(), encoding="utf-8")

    # Inject a cache-busting query for map.svg in the temporary dashboard copy
    dash_file = static_root / "dashboard_2.html"
    try:
        dash_html = dash_file.read_text(encoding="utf-8")
        dash_html = dash_html.replace('src="map.svg"', f'src="map.svg?nocache={int(time.time())}"')
        dash_file.write_text(dash_html, encoding="utf-8")
    except Exception:
        pass

    # Diagnostic: report the map file that will be served
    map_path = static_root / "map.svg"
    if map_path.exists():
        try:
            size = map_path.stat().st_size
            preview = map_path.read_bytes()[:200]
            logger.debug("Serving static/map.svg from: %s", map_path)
            logger.debug("size=%d bytes; preview=%r...", size, preview[:80])
        except Exception as e:
            logger.debug("Could not read static/map.svg: %s", e)
    else:
        logger.debug("static/map.svg not found in temporary static tree.")

    return static_root


def serve_static(static_root: Path, port: int = 8000) -> ThreadingHTTPServer:
    """Start a local HTTP server to serve static files.

    Runs the server in a non-daemon background thread so it stays alive for
    the lifetime of the process. Supports dynamic ``points.json`` computation
    when requested with ``?w=<width>&h=<height>`` query parameters.

    Args:
        static_root: Path to the ``static/`` directory to serve. The parent
            of this directory becomes the server root.
        port: TCP port to bind to. Defaults to 8000.

    Returns:
        The running ``ThreadingHTTPServer`` instance. Call ``shutdown()`` on
        it to stop the server.
    """
    tmpd = static_root.parent

    # Create a custom handler that can compute points.json on-the-fly when
    # requested with query params ?w=...&h=...
    class _CustomHandler(SimpleHTTPRequestHandler):
        def translate_path(self, path):
            # Leverage parent implementation but serve from tmpd root
            # SimpleHTTPRequestHandler will call translate_path; override to
            # ensure it uses our tmpd as the root
            # We hack by temporarily swapping cwd for correct resolution
            cwd = Path.cwd()
            try:
                os_chdir = False
                # using str(tmpd) is fine because SimpleHTTPRequestHandler uses os.getcwd
                # but to keep things simple we'll call the parent with modified path
                return super().translate_path(path)
            finally:
                pass

        def do_GET(self):
            parsed = urlparse(self.path)
            # intercept the points.json request under /static/ or /points.json
            if parsed.path.endswith('/points.json'):
                qs = parse_qs(parsed.query)
                if 'w' in qs and 'h' in qs:
                    try:
                        w = int(qs.get('w', [0])[0])
                        h = int(qs.get('h', [0])[0])
                    except Exception:
                        w = 0
                        h = 0
                    # Try multiple candidate locations for points.json: the package-copied static_root
                    # and the server's served directory (self.directory)
                    candidates = [static_root / 'points.json']
                    try:
                        served_dir = Path(getattr(self, 'directory', '.'))
                        candidates.append(served_dir / 'points.json')
                    except Exception:
                        pass

                    for src_pts in candidates:
                        if not src_pts.exists():
                            continue
                        try:
                            base = json.loads(src_pts.read_text(encoding='utf-8'))
                            cfg = base.get('config', {})
                            pts = base.get('points', [])
                            out_pts = []

                            # Determine SVG user-space dimensions (if provided)
                            svg_w = float(cfg.get('svg_w', w))
                            svg_h = float(cfg.get('svg_h', h))

                            # Optional explicit linear mapping from projected SVG coords -> observed display coords
                            sx = cfg.get('sx')
                            ox = cfg.get('ox')
                            sy = cfg.get('sy')
                            oy = cfg.get('oy')

                            for pt in pts:
                                lat = float(pt.get('lat', 0))
                                lon = float(pt.get('lon', 0))
                                # project using SVG user-space dims
                                x_proj, y_proj = transform_latlon_to_xy(lat, lon, cfg, svg_w, svg_h)

                                # map projected coords to display pixels
                                if sx is not None and ox is not None and sy is not None and oy is not None:
                                    try:
                                        x = float(sx) * x_proj + float(ox)
                                        y = float(sy) * y_proj + float(oy)
                                    except Exception:
                                        x = x_proj * (float(w) / float(svg_w))
                                        y = y_proj * (float(h) / float(svg_h))
                                else:
                                    # fallback: simple scale from svg user-space to requested display size
                                    try:
                                        sx_f = float(w) / float(svg_w) if float(svg_w) != 0 else 1.0
                                        sy_f = float(h) / float(svg_h) if float(svg_h) != 0 else 1.0
                                        x = x_proj * sx_f
                                        y = y_proj * sy_f
                                    except Exception:
                                        x = x_proj
                                        y = y_proj

                                new = dict(pt)
                                new['x'] = x
                                new['y'] = y
                                out_pts.append(new)
                            out = {'config': cfg, 'points': out_pts}
                            # DEBUG: report candidate and sample
                            try:
                                sample = out_pts[0] if out_pts else None
                                logger.debug("Computed %d points from %s (w=%d,h=%d); sample=%s", len(out_pts), src_pts, w, h, sample)
                            except Exception:
                                pass
                            body = json.dumps(out).encode('utf-8')
                            self.send_response(200)
                            self.send_header('Content-Type', 'application/json')
                            self.send_header('Content-Length', str(len(body)))
                            self.end_headers()
                            self.wfile.write(body)
                            return
                        except Exception as e:
                            logger.exception("Error computing points.json (from %s):", src_pts)
            # default
            return super().do_GET()

    # Bind and serve from the temporary directory
    handler = partial(_CustomHandler, directory=str(tmpd))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)

    def _serve():
        httpd.serve_forever()

    thread = threading.Thread(target=_serve, daemon=False)
    thread.start()

    time.sleep(0.1)

    return httpd


def open_browser(port: int = 8000) -> None:
    """Open the dashboard in a new browser tab.

    Uses a module-level guard to prevent opening duplicate tabs if called
    multiple times within the same process.

    Args:
        port: Port on which the local server is running. Defaults to 8000.
    """
    url = f"http://127.0.0.1:{port}/static/dashboard_2.html"

    global _DASHBOARD_OPENED
    if not _DASHBOARD_OPENED:
        webbrowser.open_new_tab(url)
        _DASHBOARD_OPENED = True


def serve_static_and_open(port: int = 8000) -> ThreadingHTTPServer:
    """Prepare static files, start the HTTP server, and open the dashboard.

    Convenience wrapper that calls ``_prepare_static_files()``,
    ``serve_static()``, and ``open_browser()`` in sequence. Stores a strong
    reference to the server instance at module level to prevent garbage
    collection.

    Args:
        port: TCP port to bind to. Defaults to 8000.

    Returns:
        The running ``ThreadingHTTPServer`` instance. Call ``shutdown()`` on
        it to stop the server.
    """
    global _httpd_instance
    static_root = _prepare_static_files()
    _httpd_instance = serve_static(static_root, port)
    open_browser(port)
    return _httpd_instance

