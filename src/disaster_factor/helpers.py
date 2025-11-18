from importlib.resources import files
import webbrowser
import tempfile
import threading
import time
import shutil
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from functools import partial

# One-time open guard to avoid duplicate tabs when invoked multiple times
_DASHBOARD_OPENED = False


def _find_static_source() -> Path | None:
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


def serve_static_and_open(port: int = 8000):
    """Serve the package `static` files (recursively) and open the dashboard URL.

    Returns the HTTPServer instance (caller can call `shutdown()` when done).
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

    handler = partial(SimpleHTTPRequestHandler, directory=str(tmpd))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)

    def _serve():
        httpd.serve_forever()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()

    time.sleep(0.1)
    url = f"http://127.0.0.1:{port}/static/dashboard_2.html"

    global _DASHBOARD_OPENED
    if not _DASHBOARD_OPENED:
        webbrowser.open_new_tab(url)
        _DASHBOARD_OPENED = True

    return httpd
