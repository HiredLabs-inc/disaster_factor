#!/usr/bin/env python3
"""
Separate script to geocode assets.csv, and return all coords as a list[dict]

Called in core.py assets() to build assets dict
"""

import os
import csv
from pathlib import Path
import requests
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


def _get_geocoding_api_key() -> str:
    """Get Google Geocoding API key from environment or user input."""

    api_key = os.getenv("GOOGLE_GEOCODING_API_KEY")
    if not api_key:
        api_key = input("Enter your Google Geocoding API key: ").strip()
        if not api_key:
            raise ValueError("Google Geocoding API key is required")
        os.environ["GOOGLE_GEOCODING_API_KEY"] = api_key
    return api_key


def _forward_geocoding(city: str, country: str) -> Optional[Tuple[float, float]]:
    """
    Convert city/country to coordinates using Google Geocoding API v4beta.
    
    Args:
        city: City name from assets.csv
        country: Country name from assets.csv
        
    Returns:
        (latitude, longitude) tuple or None if geocoding fails
    """
    api_key = _get_geocoding_api_key()
    
    address = f"{city}, {country}"
    url = "https://geocode.googleapis.com/v4beta/geocode"
    
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
            
    except Exception as e:
        logger.error(f"[GEOCODE] API error for {city}, {country}: {str(e)}")
        return None


def geocode_assets() -> list[dict]:
    """Read assets.csv, geocode any missing coordinates, and return data as list[dict]."""
    # Set up paths
    path = Path(__file__).resolve().parent / "static" / "assets.csv"
   
    if not path.exists():
        raise FileNotFoundError(f"[GEOCODE] assets.csv not found at {path}")   
    logger.info("[GEOCODE] Processing assets.csv...")
    logger.info(f"[GEOCODE] Input: {path}")
    
    # Check for Latitude and Longitude in header columns
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
        header_row = rows[0]
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
        reader = csv.DictReader(f)
        geocoded_any = False
        
        for i, row in enumerate(reader, 1):
            city = row.get('city', '').strip()
            country = row.get('country', '').strip()
            
            # Check if coordinates already exist and are valid
            lat_str = row.get('latitude', '').strip()
            lon_str = row.get('longitude', '').strip()
            
            if lat_str and lon_str:
                try:
                    float(lat_str)
                    float(lon_str)
                    logger.debug(f"[GEOCODE] {i}: {city}, {country} → Already has coordinates")
                    assets.append(row)
                    continue
                except ValueError:
                    logger.warning(f"[GEOCODE] Invalid coordinates for row {i} ({city}, {country}), re-geocoding")
            
            # Geocode if no valid coordinates
            logger.debug(f"[GEOCODE] {i}: {city}, {country}")
            coords = _forward_geocoding(city, country)
            
            if coords:
                row['latitude'] = (coords[0])
                row['longitude'] = (coords[1])
                geocoded_any = True
                logger.info(f"[GEOCODE] Success: {coords}")
            else:
                row['latitude'] = ''
                row['longitude'] = ''
                logger.warning(f"[GEOCODE] {i}: {city}, {country} -> Failed to geocode")
            
            row = {k.strip(): v for k, v in row.items() if k}
            assets.append(row)
        
        # Write-back after geocoding loop if any missing coordinates were added
        if geocoded_any:
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(assets[0].keys()))
                writer.writeheader()
                writer.writerows(assets)
            logger.info("[GEOCODE] Coordinates written back to assets.csv")
        else:
            logger.info("[GEOCODE] No new coordinates to write - assets.csv unchanged")
    
    successful = len([a for a in assets if a.get('latitude') and a.get('longitude')])
    logger.info(f"[GEOCODE] Complete!")
    logger.info(f"[GEOCODE] Total assets: {len(assets)}")
    logger.info(f"[GEOCODE] Successfully geocoded: {successful}")
    failed = len(assets) - successful
    if failed > 0:
        logger.warning(f"[GEOCODE] Failed to geocode {failed} assets")

    # Return Python Object
    return assets
    

if __name__ == "__main__":
    geocode_assets()
