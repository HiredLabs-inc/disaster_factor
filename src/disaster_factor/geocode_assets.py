#!/usr/bin/env python3
"""Geocode assets from assets.csv and return their coordinates.

Reads assets.csv from the package static directory, geocodes any rows missing
latitude/longitude using the Google Geocoding API, writes coordinates back to
the file, and returns all asset data as a list of dicts.

Called by ``core.py`` via ``assets()`` to build the assets dictionary.
"""

import os
import csv
from pathlib import Path
import requests
from typing import Optional, Tuple
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
logging.getLogger("urllib3").setLevel(logging.WARNING)


def _get_geocoding_api_key() -> str:
    """Read the Google Geocoding API key from the environment.

    Raises:
        ValueError: If ``GOOGLE_GEOCODING_API_KEY`` is not set in the
            environment or a loaded ``.env`` file.

    Returns:
        The API key string.
    """
    api_key = os.getenv("GOOGLE_GEOCODING_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_GEOCODING_API_KEY is not set. Add it to your .env file.")
    return api_key


def _forward_geocoding(city: str, country: str) -> Optional[Tuple[float, float]]:
    """Convert a city and country name to geographic coordinates.

    Uses the Google Geocoding API. Returns the highest-confidence result
    when multiple matches are found.

    Args:
        city: City name as read from assets.csv.
        country: Country name as read from assets.csv.

    Returns:
        A ``(latitude, longitude)`` tuple if geocoding succeeds, or ``None``
        if the API returns no results or an error occurs.
    """
    api_key = _get_geocoding_api_key()
    
    address = f"{city}, {country}"
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    
    params = {
        "address": address,
        "key": api_key
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") == "OK" and data.get("results"):
            # Use the first (highest confidence) result
            location = data["results"][0]["geometry"]["location"]
            logger.info(f"[GEOCODE] {city}, {country} → {location['lat']}, {location['lng']}")
            return location["lat"], location["lng"]
        else:
            logger.warning(f"[GEOCODE] No results for {city}, {country}: {data.get('status')}")
            return None
        
    except requests.HTTPError as e:
        logger.error(f"[GEOCODE] API error for {city}, {country}: HTTP {e.response.status_code}")
        return None
    except Exception as e:
        logger.error(f"[GEOCODE] API error for {city}, {country}: {type(e).__name__}")
        return None


def geocode_assets() -> list[dict]:
    """Read assets.csv, geocode missing coordinates, and return all asset data.

    Reads the CSV from the package static directory. If latitude/longitude
    columns are absent they are added. Rows that already have valid coordinates
    are passed through unchanged. Rows missing coordinates are geocoded via
    ``_forward_geocoding()``. Any newly geocoded coordinates are written back
    to assets.csv before returning.

    Raises:
        FileNotFoundError: If assets.csv does not exist at the expected path.

    Returns:
        A list of dicts, one per asset row, with ``latitude`` and ``longitude``
        keys populated where geocoding succeeded. Rows that could not be
        geocoded have empty strings for those keys.
    """
    # Set up paths
    path = Path(__file__).resolve().parent / "static" / "assets.csv"
   
    if not path.exists():
        raise FileNotFoundError(f"[GEOCODE] assets.csv not found at {path}")   
    logger.info("[GEOCODE] Processing assets.csv...")
    logger.info(f"[GEOCODE] Input: {path}")
    
    # Check for Latitude and Longitude in header columns
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
        header_row = [h.strip().lower() for h in rows[0]]
        headers = "latitude" in header_row and "longitude" in header_row
    
    # Write-in missing columns if needed
    if not headers:
        rows[0].extend(["latitude", "longitude"])
        for row in rows[1:]:
            row.extend(["", ""])
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(rows)
    
    assets = []

    # Builds assets list and fills in any missing coordinates
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, skipinitialspace=True)
        reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]
        geocoded_count = 0
        
        for i, row in enumerate(reader, 1):
            city = row.get('city', '').strip()
            country = row.get('country', '').strip()
            
            # Check if coordinates already exist and are valid
            lat_str = (row.get('latitude') or '').strip()
            lon_str = (row.get('longitude') or '').strip()
            
            if lat_str and lon_str:
                try:
                    row["latitude"] = float(lat_str)
                    row["longitude"] = float(lon_str)
                    logger.debug(f"[GEOCODE] {i}: {city}, {country} → Already has coordinates")
                    assets.append(row)
                    continue
                except ValueError:
                    logger.warning(f"[GEOCODE] Invalid coordinates for row {i} ({city}, {country}), re-geocoding")
            
            if not city or not country:
                logger.warning(f"[GEOCODE] {i}: missing city or country, skipping")
                continue

            # Geocode if no valid coordinates
            logger.debug(f"[GEOCODE] {i}: {city}, {country}")
            coords = _forward_geocoding(city, country)
            
            if coords:
                row['latitude'] = round((coords[0]), 3)
                row['longitude'] = round((coords[1]), 3)
                geocoded_count += 1
                logger.info(f"[GEOCODE] Success: {row['latitude']}, {row['longitude']}")
            else:
                row['latitude'] = ''
                row['longitude'] = ''
                logger.warning(f"[GEOCODE] {i}: {city}, {country} -> Failed to geocode")
            
            assets.append(row)
        
        # Write-back after geocoding loop if any missing coordinates were added
        if geocoded_count > 0:
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(assets[0].keys()))
                writer.writeheader()
                writer.writerows(assets)
            logger.info("[GEOCODE] Coordinates written back to assets.csv")
        else:
            logger.info("[GEOCODE] No new coordinates to write - assets.csv unchanged")
    
    successful = sum(1 for a in assets if a.get("latitude") not in (None, "") and a.get("longitude") not in (None, ""))
    failed = len(assets) - successful
    logger.info(f"[GEOCODE] Complete!")
    logger.info(f"[GEOCODE] Total assets: {len(assets)}")
    logger.info(f"[GEOCODE] Already had coordinates: {successful - geocoded_count}")
    logger.info(f"[GEOCODE] Newly geocoded: {geocoded_count}")
    if failed > 0:
        logger.warning(f"[GEOCODE] Failed to geocode {failed} assets")

    # Return Python Object
    return assets
    

if __name__ == "__main__":
    geocode_assets()
