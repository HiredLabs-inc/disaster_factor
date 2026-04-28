#!/usr/bin/env python3
"""
Separate script to geocode assets.csv and add coordinates.

Run this script once to add latitude/longitude columns to your assets.csv file.
This keeps the main application fast with no runtime API dependencies.

Usage:
    python tests/data/geocode_assets.py
"""

import csv
import sys
import os
from pathlib import Path
import requests
from typing import Optional, Tuple

# Import the API key function from core
sys.path.append(str(Path(__file__).resolve().parents[2]))
from disaster_factor.core import _get_geocoding_api_key


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
            print(f"[GEOCODE] {city}, {country} → {location['lat']}, {location['lng']}")
            return location["lat"], location["lng"]
        else:
            print(f"[GEOCODE] No results for {city}, {country}: {data.get('status')}")
            return None
            
    except Exception as e:
        print(f"[GEOCODE] API error for {city}, {country}: {str(e)}")
        return None


def geocode_assets_csv():
    """Add coordinates to assets.csv file."""
    # Set up paths
    script_dir = Path(__file__).resolve().parent
    input_path = script_dir / "assets.csv"
    # TODO: Review for refactoring to Python object
    output_path = script_dir / "assets_geocoded.csv"
    
    if not input_path.exists():
        print(f"[ERROR] assets.csv not found at {input_path}")
        return
    
    print("[GEOCODE] Processing assets.csv...")
    print(f"[GEOCODE] Input: {input_path}")
    print(f"[GEOCODE] Output: {output_path}")
    
    # Read original assets
    assets = []
    with input_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        
        # Check if coordinates already exist
        if 'latitude' in reader.fieldnames and 'longitude' in reader.fieldnames:
            print("[GEOCODE] Assets already have coordinates! Checking for missing values...")
            fieldnames = reader.fieldnames
        else:
            print("[GEOCODE] Adding coordinate columns...")
            fieldnames = reader.fieldnames + ['latitude', 'longitude']
        
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
                    print(f"[GEOCODE] {i}: {city}, {country} → Already has coordinates")
                    assets.append(row)
                    continue
                except ValueError:
                    print(f"[GEOCODE] {i}: {city}, {country} → Invalid coordinates, re-geocoding")
            
            # Geocode if no valid coordinates
            print(f"[GEOCODE] {i}: {city}, {country}")
            coords = _forward_geocoding(city, country)
            
            if coords:
                row['latitude'] = str(coords[0])
                row['longitude'] = str(coords[1])
                print(f"[GEOCODE] ✓ Success: {coords}")
            else:
                row['latitude'] = ''
                row['longitude'] = ''
                print(f"[GEOCODE] ✗ Failed")
            
            assets.append(row)
    
    # Write geocoded assets
    with output_path.open(newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(assets)
    
    successful = len([a for a in assets if a.get('latitude') and a.get('longitude')])
    print(f"\n[GEOCODE] Complete!")
    print(f"[GEOCODE] Total assets: {len(assets)}")
    print(f"[GEOCODE] Successfully geocoded: {successful}")
    print(f"[GEOCODE] Failed: {len(assets) - successful}")
    print(f"[GEOCODE] Saved to: {output_path}")
    
    print(f"\n[GEOCODE] To use the geocoded assets:")
    print(f"[GEOCODE] cp {output_path} {input_path}")


if __name__ == "__main__":
    geocode_assets_csv()
