from importlib.resources import files
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

# One-time open guard to avoid duplicate tabs when invoked multiple times
_DASHBOARD_OPENED = False
# Strong reference to the server instance to prevent garbage collection
_httpd_instance: Optional[ThreadingHTTPServer] = None


def _find_static_source() -> Optional[Path]:
    """Find a static/ directory for development first; fall back to installed resources.

    Preferred order (dev-first):
    1) Source under current working directory: ./src/disaster_factor/static
    2) Source under nearest pyproject.toml root: <root>/src/disaster_factor/static
    3) Source alongside this module (may be site-packages if installed)
    4) Installed package resources (importlib.resources)
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


def get_dashboard():
    # Prefer local source tree during development
    src = _find_static_source()
    if src and (src / "dashboard_2.html").exists():
        return (src / "dashboard_2.html").read_text(encoding="utf-8")

    dashboard_path = files("disaster_factor").joinpath("static", "dashboard_2.html")
    return dashboard_path.read_text(encoding="utf-8")


def open_dashboard_in_browser() -> Path:
    """Write the dashboard HTML to a temporary file and return its path.

    This no longer auto-opens a browser to avoid duplicate tabs alongside the
    HTTP-served version. Callers can open the returned path if needed.
    """
    html = get_dashboard()
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write(html)
        tmp_path = Path(f.name)

    return tmp_path


def _copy_traversable_to_dir(trav, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for item in getattr(trav, 'iterdir', lambda: [])():
        if item.is_dir():
            _copy_traversable_to_dir(item, dest / item.name)
        elif item.is_file():
            with item.open("rb") as srcf, open(dest / item.name, "wb") as dstf:
                shutil.copyfileobj(srcf, dstf)


def _copy_tree(src: Path, dest: Path) -> None:
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
    """Return the Mercator 'y' value for a latitude in degrees.

    Clamp latitude to avoid singularities at the poles.
    """
    # prevent tan() overflow near the poles
    max_lat = 89.9999
    lat = max(-max_lat, min(max_lat, float(lat)))
    rad = math.radians(lat)
    return math.log(math.tan(math.pi / 4.0 + rad / 2.0))


def get_y(h: int, lat: float, lat_t: float, lat_b: float) -> float:
    """Compute pixel Y for given latitude using a Mercator projection.

    Ensures lat_t is the top (greater) and lat_b is the bottom (smaller),
    clamps latitudes to avoid pole singularities, handles zero denominators,
    and clamps output to [0,h].
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
    """Compute pixel X for given longitude and center longitude lon_c.

    Normalize longitude delta to [-180,180] to handle antimeridian wrap,
    then map to pixel coordinates with center at w/2.
    """
    # normalize into [-180, 180)
    delta = (float(lon) - float(lon_c) + 180.0) % 360.0 - 180.0
    x = (delta / 360.0) * float(w) + (float(w) / 2.0)
    return max(0.0, min(float(w), x))


def transform_latlon_to_xy(lat: float, lon: float, config: dict, w: int, h: int) -> tuple[float, float]:
    """Map lat/lon -> x/y pixels for an image of size w x h.

    Defaults: mercator projection with optional config values:
      config['lat_t'] : latitude at the top of the image (default 90)
      config['lat_b'] : latitude at the bottom of the image (default -90)
      config['lon_c'] : center longitude of the image (default 0)

    Returns (x, y) where (0,0) is the top-left of the image. Values are
    clamped to the image bounds.
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
    """Prepare static files for serving.

    Copies static files to a temporary directory, ensures the dashboard exists,
    and injects cache-busting queries. Returns the path to the temporary static_root.
    """
    tmpd = Path(tempfile.mkdtemp())
    static_root = tmpd / "static"

    # Prefer live source static if present
    src_static = _find_static_source()
    if src_static is not None:
        print(f"DEBUG: Using static source: {src_static}")
        _copy_tree(src_static, static_root)

    else:
        # Fallback: try importlib.resources
        try:
            static_trav = files("disaster_factor").joinpath("static")
            _copy_traversable_to_dir(static_trav, static_root)
            print("DEBUG: Using installed package static resources")
        except Exception as e:
            print(f"DEBUG: No static resources found: {e}")
    print(f"DEBUG: Files in static_root ({static_root}):")
    for f in static_root.rglob('*'):
        print(f"  {f.relative_to(static_root)}")
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
            print(f"DEBUG: Serving static/map.svg from: {map_path}")
            print(f"DEBUG: size={size} bytes; preview={preview[:80]!r}...")
        except Exception as e:
            print(f"DEBUG: Could not read static/map.svg: {e}")
    else:
        print("DEBUG: static/map.svg not found in temporary static tree.")

    return static_root


def serve_static(static_root: Path, port: int = 8000) -> ThreadingHTTPServer:
    """Start an HTTP server serving static files from static_root.

    The server runs in a daemon thread and supports dynamic points.json computation.
    Returns the ThreadingHTTPServer instance.
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
                                print(f"DEBUG: Computed {len(out_pts)} points from {src_pts} (w={w},h={h}); sample={sample}")
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
                            import traceback
                            print("DEBUG: Error computing points.json (from", src_pts, "):")
                            traceback.print_exc()
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

    Uses a global guard to prevent opening duplicate tabs when invoked
    multiple times within the same process.
    """
    url = f"http://127.0.0.1:{port}/static/dashboard_2.html"

    global _DASHBOARD_OPENED
    if not _DASHBOARD_OPENED:
        webbrowser.open_new_tab(url)
        _DASHBOARD_OPENED = True


def serve_static_and_open(port: int = 8000) -> ThreadingHTTPServer:
    """Serve the package `static` files (recursively) and open the dashboard URL.

    Convenience wrapper that combines static file preparation, server startup,
    and browser opening. Returns the HTTPServer instance (caller can call
    `shutdown()` when done).
    """
    global _httpd_instance
    static_root = _prepare_static_files()
    _httpd_instance = serve_static(static_root, port)
    open_browser(port)
    return _httpd_instance

