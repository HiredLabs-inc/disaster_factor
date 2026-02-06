"""Calibration helper to fit map transform parameters.

This script searches for lat_t, lat_b, lon_c that minimize the squared error
between observed SVG coordinates (cx,cy) and the projected coordinates from
lat/lon using the project's mercator-based transform.

Usage: run the module directly; it contains the three reference points and
viewBox height/width you provided and will print a best-fit result.
"""
from __future__ import annotations

from typing import Sequence, Tuple
import math
import argparse
import json
from pathlib import Path

# Import the project's projection helper
from disaster_factor.helpers import transform_latlon_to_xy


def _compute_scale_offset(x_proj: Sequence[float], x_obs: Sequence[float]) -> Tuple[float, float]:
    """Compute least-squares scale and offset to map x_proj -> x_obs.
    Solves x_obs = s * x_proj + o in least-squares sense.
    Returns (s, o). Handles degenerate var(x_proj)=0 by returning s=1,o=mean(obs)-mean(proj).
    """
    n = len(x_proj)
    if n == 0:
        return 1.0, 0.0
    mean_x = sum(x_proj) / n
    mean_obs = sum(x_obs) / n
    num = sum((xp - mean_x) * (xo - mean_obs) for xp, xo in zip(x_proj, x_obs))
    den = sum((xp - mean_x) ** 2 for xp in x_proj)
    if den == 0:
        s = 1.0
    else:
        s = num / den
    o = mean_obs - s * mean_x
    return s, o


def _mse_for_params_with_linear_map(params: Tuple[float, float, float], refs: Sequence[dict], svg_w: float, svg_h: float) -> Tuple[float, dict]:
    lat_t, lat_b, lon_c = params
    cfg = {'lat_t': lat_t, 'lat_b': lat_b, 'lon_c': lon_c}
    proj_x = []
    proj_y = []
    obs_x = []
    obs_y = []
    for r in refs:
        lat = float(r['lat'])
        lon = float(r['lon'])
        cx = float(r['cx'])
        cy = float(r['cy'])
        x, y = transform_latlon_to_xy(lat, lon, cfg, svg_w, svg_h)
        proj_x.append(x)
        proj_y.append(y)
        obs_x.append(cx)
        obs_y.append(cy)

    # compute optimal linear map for x and y
    sx, ox = _compute_scale_offset(proj_x, obs_x)
    sy, oy = _compute_scale_offset(proj_y, obs_y)

    # compute mse after mapping
    err = 0.0
    for xp, yp, xo, yo in zip(proj_x, proj_y, obs_x, obs_y):
        mx = sx * xp + ox
        my = sy * yp + oy
        err += (mx - xo) ** 2 + (my - yo) ** 2
    mse = err / max(1, len(refs))
    details = {'cfg': cfg, 'sx': sx, 'ox': ox, 'sy': sy, 'oy': oy}
    return mse, details


def calibrate(refs: Sequence[dict], svg_w: float, svg_h: float) -> Tuple[dict, float, dict]:
    """Find lat_t, lat_b, lon_c minimizing error for the given reference points.

    Uses a simple coarse-to-fine grid search (no external deps). For each
    candidate projection params we compute the best linear (scale+offset)
    mapping from projected SVG coordinates into the observed coords and
    evaluate MSE on the mapped points.
    """
    # initial search ranges
    lon_range = (-180.0, 180.0)
    lat_t_range = (0.0, 90.0)
    lat_b_range = (-90.0, 0.0)

    # start with coarse steps then refine
    steps = [10.0, 2.0, 0.5, 0.1]

    best = None
    best_params = (45.0, -45.0, 0.0)
    best_details = None
    for step in steps:
        best_local = None
        lat_t_start = max(lat_t_range[0], best_params[0] - 10.0) if best else lat_t_range[0]
        lat_t_end = min(lat_t_range[1], best_params[0] + 10.0) if best else lat_t_range[1]
        lat_b_start = max(lat_b_range[0], best_params[1] - 10.0) if best else lat_b_range[0]
        lat_b_end = min(lat_b_range[1], best_params[1] + 10.0) if best else lat_b_range[1]
        lon_start = max(lon_range[0], best_params[2] - 10.0) if best else lon_range[0]
        lon_end = min(lon_range[1], best_params[2] + 10.0) if best else lon_range[1]

        lat_t = lat_t_start
        while lat_t <= lat_t_end + 1e-9:
            lat_b = lat_b_start
            while lat_b <= lat_b_end + 1e-9:
                lon_c = lon_start
                while lon_c <= lon_end + 1e-9:
                    mse, details = _mse_for_params_with_linear_map((lat_t, lat_b, lon_c), refs, svg_w, svg_h)
                    if best_local is None or mse < best_local[0]:
                        best_local = (mse, (lat_t, lat_b, lon_c), details)
                    lon_c += step
                lat_b += step
            lat_t += step

        # adopt best from this pass and narrow search window
        if best_local is not None:
            best = best_local
            mse_val, (lt, lb, lc), details = best_local
            best_params = (lt, lb, lc)
            best_details = details
        else:
            break

    result_cfg = {'lat_t': float(best_params[0]), 'lat_b': float(best_params[1]), 'lon_c': float(best_params[2])}
    return result_cfg, float(best[0]) if best else (result_cfg, float('inf')), best_details


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Calibrate map transform parameters using reference points')
    parser.add_argument('--svg-w', type=float, default=681.838, help='SVG viewBox width (user coordinate width)')
    parser.add_argument('--svg-h', type=float, default=461.696, help='SVG viewBox height (user coordinate height)')
    parser.add_argument('--refs', type=Path, default=None, help='optional JSON file containing reference points with cx/cy')
    args = parser.parse_args()

    if args.refs and args.refs.exists():
        try:
            data = json.loads(args.refs.read_text(encoding='utf-8'))
            refs = data.get('points', [])
            # expect each ref to include cx/cy
        except Exception as e:
            raise SystemExit(f'Could not read refs file: {e}')
    else:
        # fallback: embedded reference points (use cx/cy observed values)
        refs = [
            {"lat": 48.86, "lon": 2.3522, "label": "Paris, FR", "severity": "red", "cx": 1151.9732649999999, "cy": 313.3545897541183},
            {"lat": 37.78, "lon": -122.42, "label": "San Francisco, US", "severity": "red", "cx": 612.3335, "cy": 388.2314130230286},
            {"lat": 39.9042, "lon": 116.4074, "label": "Beijing, CH", "severity": "red", "cx": 88.26200500000004, "cy": 374.87923138010893},
        ]

    cfg, err, details = calibrate(refs, args.svg_w, args.svg_h)
    print('Best-fit cfg (lat_t/lat_b/lon_c):', cfg)
    print('MSE:', err)
    print('Linear mapping details (sx,ox,sy,oy):', {k: details.get(k) for k in ('sx', 'ox', 'sy', 'oy')} if details else None)
    print('Note: The linear mapping maps projected SVG coords (using svg_w/svg_h) to observed cx/cy: cx = sx * x_proj + ox; cy = sy * y_proj + oy')
