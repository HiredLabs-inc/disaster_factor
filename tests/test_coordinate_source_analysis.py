# tests/test_coordinate_source_analysis.py

import os
import sys
import csv
import requests
import time
from disaster_factor.core import recon, _get_json, _extract_impact_export_url, _find_text_suffix
from bs4 import BeautifulSoup
from tests.alias_discovery import discover_all_gdacs_aliases


def _get_api_key() -> str:
    """Get Google Geocoding API key from environment."""
    api_key = os.getenv("GOOGLE_GEOCODING_API_KEY")
    if not api_key:
        api_key = input("Enter your Google Geocoding API key: ").strip()
        os.environ["GOOGLE_GEOCODING_API_KEY"] = api_key
    return api_key


def _reverse_geocode_with_language(lat: str, long: str, language_code: str, api_key: str):
    """Helper function to geocode with specific language."""
    url = f"https://geocode.googleapis.com/v4beta/geocode/location/{lat},{long}?languageCode={language_code}"
    headers = {'X-Goog-Api-Key': api_key}
    
    resp = requests.get(url, headers=headers, timeout=5)
    results = resp.json()
    
    if not results.get('results'):
        return None
    
    # Find the best result with actual address components (not just plus_code)
    best_result = None
    best_priority = 999
    
    for result in results['results']:
        components = result.get('addressComponents', [])
        result_types = set(result.get('types', []))
        
        # Skip results with only plus codes
        if len(components) == 1 and 'plus_code' in components[0].get('types', []):
            continue
        
        # Determine priority (lower is better)
        priority = 999
        if result_types.intersection({'locality', 'neighborhood'}):
            priority = 1  # Best: city-level
        elif result_types.intersection({'administrative_area_level_2', 'administrative_area_level_3'}):
            priority = 2  # Good: county/district
        elif result_types.intersection({'administrative_area_level_1'}):
            priority = 3  # OK: state/province
        elif result_types.intersection({'country'}):
            priority = 4  # Fallback: country only
        
        if priority < best_priority:
            best_result = result
            best_priority = priority
    
    return best_result


def _reverse_geocode(lat: str, long: str, request_count: list = [0]) -> tuple[bool, str, str, str]:
    """Reverse geocode coordinates to determine if they return city-level data."""
    try:
        api_key = _get_api_key()
        
        # Rate limiting: 3,000 requests per minute = 50 requests per second
        # Using 45 requests per second to stay safely within limits
        if request_count[0] > 0 and request_count[0] % 45 == 0:
            print(f"  Rate limit pause: processed {request_count[0]} requests...")
            time.sleep(0.8)  # Brief pause every 45 requests
        
        request_count[0] += 1
        
        # Try multiple language codes in order of preference
        language_codes = ['en', 'zh-TW', 'zh-CN', 'ja', 'ko']  # English, Traditional Chinese, Simplified Chinese, Japanese, Korean
        best_result = None
        
        for lang in language_codes:
            best_result = _reverse_geocode_with_language(lat, long, lang, api_key)
            if best_result:
                # Check if we got English names for ALL components (except country)
                components = best_result.get('addressComponents', [])
                all_english = all(
                    component.get('longText', '').isascii() or component.get('types', []) == ['country', 'political']
                    for component in components
                    if component.get('longText', '') != ''
                )
                
                if all_english:
                    break  # Found all English result
                elif lang == 'en':
                    break  # English didn't work, keep original language
        
        if not best_result:
            return False, "NO_RESULTS", "", ""
        
        # Process the best result we found
        address_components = best_result.get('addressComponents', [])
        address_types = set(best_result.get('types', []))
        city_name = ""
        state_name = ""
        
        # Process the found address components
        for component in address_components:
            comp_types = set(component.get('types', []))
            original_name = component.get('longText', '')
            
            # Keep original language intact - no translation of suffixes
            
            # Extract city name (for city-level results)
            if not city_name and comp_types.intersection({'locality', 'neighborhood', 'sublocality', 'sublocality_level_1', 'sublocality_level_2', 'colloquial_area'}):
                city_name = original_name
            
            # Extract state name
            if not state_name and comp_types.intersection({'administrative_area_level_1'}):
                state_name = original_name
            
            # For non-city results, capture the actual location name
            if not city_name and not comp_types.intersection({'country', 'postal_code', 'plus_code'}):
                # Use the most specific administrative level as the "city" name for analysis
                if comp_types.intersection({'administrative_area_level_2', 'administrative_area_level_3'}):
                    city_name = original_name
                elif not city_name and comp_types.intersection({'administrative_area_level_1'}):
                    city_name = original_name
        
        # Determine the locality level being used
        locality_level = "UNKNOWN"
        if 'locality' in address_types:
            locality_level = "LOCALITY"
        elif 'neighborhood' in address_types:
            locality_level = "NEIGHBORHOOD"
        elif 'sublocality' in address_types:
            locality_level = "SUBLOCALITY"
        elif 'sublocality_level_1' in address_types:
            locality_level = "SUBLOCALITY_LEVEL_1"
        elif 'sublocality_level_2' in address_types:
            locality_level = "SUBLOCALITY_LEVEL_2"
        elif 'colloquial_area' in address_types:
            locality_level = "COLLOQUIAL_AREA"
        elif 'administrative_area_level_3' in address_types:
            locality_level = "ADMIN_LEVEL_3"
        elif 'administrative_area_level_2' in address_types:
            locality_level = "ADMIN_LEVEL_2"
        elif 'administrative_area_level_1' in address_types:
            locality_level = "ADMIN_LEVEL_1"
        elif 'country' in address_types:
            locality_level = "COUNTRY"
        elif 'plus_code' in address_types:
            locality_level = "PLUS_CODE"
        
        # Check for city-level types
        city_types = {'locality', 'neighborhood', 'sublocality', 'sublocality_level_1', 'sublocality_level_2', 'colloquial_area'}
        if city_types.intersection(address_types):
            return True, "CITY_LEVEL", city_name, state_name
        else:
            return False, f"NON_CITY: {sorted(address_types)[:3]}", city_name, state_name
    except Exception as e:
        return False, f"ERROR: {str(e)[:50]}", "", ""


def test_coordinate_source_analysis():
    """Comprehensive analysis of GDACS coordinate sources and reverse geocoding quality."""
    
    print("=" * 80)
    print("GDACS COMPREHENSIVE COORDINATE SOURCE ANALYSIS")
    print("=" * 80)
    
    # Get comprehensive alias list for complete analysis
    print("Discovering all GDACS aliases...")
    all_gdacs_aliases = discover_all_gdacs_aliases()
    print(f"Found {len(all_gdacs_aliases)} total aliases: {all_gdacs_aliases}")
    
    # Get raw RSS data to track coordinate sources
    rss_url = "https://www.gdacs.org/XML/RSS.xml"
    resp = requests.get(rss_url, timeout=20)
    resp.raise_for_status()
    
    soup = BeautifulSoup(resp.content, features="xml")
    items = soup.find_all("item")
    
    coordinate_sources = []
    
    print(f"\nAnalyzing {len(items)} GDACS events for coordinate sources...")
    
    for idx, item in enumerate(items, start=1):
        if idx % 20 == 0:
            print(f"  Processed {idx}/{len(items)} events...")
        
        # Extract event info
        eventtype = _find_text_suffix(item, "eventtype")
        eventid = _find_text_suffix(item, "eventid")
        alertlevel = _find_text_suffix(item, "alertlevel")
        
        if not eventtype or not eventid:
            continue
        
        # Check RSS coordinates
        rss_coords = {}
        geo_point = item.find("geo:Point")
        if geo_point:
            lat_elem = geo_point.find("geo:lat")
            long_elem = geo_point.find("geo:long")
            if lat_elem and long_elem:
                rss_coords = {
                    'source': 'RSS_GEO_POINT',
                    'latitude': lat_elem.text,
                    'longitude': long_elem.text
                }
        
        # Get event data for coordinate extraction
        eventdata_url = f"https://www.gdacs.org/gdacsapi/api/events/geteventdata?eventtype={eventtype}&eventid={eventid}"
        
        try:
            eventdata_json = _get_json(eventdata_url, timeout=20)
            impact_url = _extract_impact_export_url(eventdata_json)
            
            if impact_url:
                impact_json = _get_json(impact_url, timeout=20)
                
                # Extract coordinates from impact data
                datums = impact_json.get("datums", [])
                for block in datums:
                    if isinstance(block, dict):
                        alias = block.get("alias", "").strip().casefold()
                        records = block.get("datum", [])
                        
                        if isinstance(records, list):
                            for record in records:  # Process ALL records per alias for comprehensive analysis
                                if isinstance(record, dict):
                                    scalars = record.get("scalars", {})
                                    scalar_list = scalars.get("scalar", [])
                                    
                                    if isinstance(scalar_list, list):
                                        lat_val = None
                                        long_val = None
                                        
                                        for scalar in scalar_list:
                                            if isinstance(scalar, dict):
                                                name = scalar.get("name", "").lower()
                                                value = scalar.get("value", "")
                                                
                                                if 'lat' in name and value:
                                                    lat_val = value
                                                elif 'long' in name and value:
                                                    long_val = value
                                                elif 'lon' in name and value:
                                                    long_val = value
                                        
                                        if lat_val and long_val:
                                            coordinate_sources.append({
                                                'eventtype': eventtype,
                                                'eventid': eventid,
                                                'alertlevel': alertlevel,
                                                'source': f'IMPACT_{alias.upper()}',
                                                'latitude': lat_val,
                                                'longitude': long_val,
                                                'alias': alias
                                            })
        
        except Exception as e:
            continue
        
        # Add RSS coordinates if found
        if rss_coords:
            coordinate_sources.append({
                'eventtype': eventtype,
                'eventid': eventid,
                'alertlevel': alertlevel,
                'source': rss_coords['source'],
                'latitude': rss_coords['latitude'],
                'longitude': rss_coords['longitude'],
                'alias': 'rss'
            })
    
    print(f"\nFound {len(coordinate_sources)} total coordinate sources")
    
    # Analyze coordinate source distribution
    source_counts = {}
    for coord in coordinate_sources:
        source = coord['source']
        source_counts[source] = source_counts.get(source, 0) + 1
    
    print(f"\nCOORDINATE SOURCES DISTRIBUTION:")
    for source, count in sorted(source_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {source:20}: {count:4} coordinates")
    
    # Reverse geocode coordinates
    print(f"\nReverse geocoding coordinates...")
    reverse_results = []
    
    for idx, coord in enumerate(coordinate_sources):
        if idx % 10 == 0:
            print(f"  Reverse geocoded {idx}/{len(coordinate_sources)}...")
        
        is_city, result_type, city_name, state_name = _reverse_geocode(coord['latitude'], coord['longitude'])
        
        reverse_results.append({
            **coord,
            'is_city': is_city,
            'result_type': result_type,
            'city_name': city_name,
            'state_name': state_name
        })
    
    # Analyze results by source
    print(f"\nREVERSE GEOCODING RESULTS BY SOURCE:")
    source_analysis = {}
    
    for result in reverse_results:
        source = result['source']
        if source not in source_analysis:
            source_analysis[source] = {'total': 0, 'city_returns': 0, 'non_city_returns': 0}
        
        source_analysis[source]['total'] += 1
        if result['is_city']:
            source_analysis[source]['city_returns'] += 1
        else:
            source_analysis[source]['non_city_returns'] += 1
    
    print(f"  {'SOURCE':20} | {'TOTAL':8} | {'CITY':8} | {'NON_CITY':8} | {'CITY%':8}")
    print(f"  {'-'*20} | {'-'*8} | {'-'*8} | {'-'*8} | {'-'*8}")
    
    for source in sorted(source_analysis.keys()):
        stats = source_analysis[source]
        city_pct = (stats['city_returns'] / stats['total'] * 100) if stats['total'] > 0 else 0
        print(f"  {source:20} | {stats['total']:8} | {stats['city_returns']:8} | {stats['non_city_returns']:8} | {city_pct:7.1f}%")
    
    # Summary statistics
    total_coords = len(reverse_results)
    total_city_returns = sum(1 for r in reverse_results if r['is_city'])
    total_non_city = total_coords - total_city_returns
    
    print(f"\nSUMMARY:")
    print(f"  Total coordinates found: {total_coords}")
    print(f"  City-level returns: {total_city_returns} ({total_city_returns/total_coords*100:.1f}%)")
    print(f"  Non-city returns: {total_non_city} ({total_non_city/total_coords*100:.1f}%)")
    print(f"  Unique coordinate sources: {len(source_counts)}")
    
    # Write results to CSV
    csv_file = os.path.join(os.path.dirname(__file__), 'coord_analysis.csv')
    with open(csv_file, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(['COORDINATE SOURCE ANALYSIS'])
        writer.writerow(['Total Coordinates', total_coords])
        writer.writerow(['City Returns', total_city_returns])
        writer.writerow([])
        writer.writerow(['SOURCE ANALYSIS'])
        writer.writerow(['SOURCE', 'TOTAL', 'CITY_RETURNS', 'NON_CITY_RETURNS', 'CITY_PERCENTAGE'])
        for source in sorted(source_analysis.keys()):
            stats = source_analysis[source]
            city_pct = (stats['city_returns'] / stats['total'] * 100) if stats['total'] > 0 else 0
            writer.writerow([source, stats['total'], stats['city_returns'], stats['non_city_returns'], f"{city_pct:.1f}%"])
        writer.writerow([])
        writer.writerow(['DETAILED RESULTS'])
        writer.writerow(['EVENTTYPE', 'EVENTID', 'SOURCE', 'ALIAS', 'LATITUDE', 'LONGITUDE', 'IS_CITY', 'RESULT_TYPE', 'CITY_NAME', 'STATE_NAME'])
        for result in reverse_results:
            writer.writerow([
                result['eventtype'], result['eventid'],
                result['source'], result['alias'], result['latitude'], result['longitude'],
                result['is_city'], result['result_type'], result['city_name'], result['state_name']
            ])
    
    print(f"\nDetailed analysis written to: {csv_file}")
    print(f"\n" + "=" * 80)
    print("COORDINATE SOURCE ANALYSIS COMPLETE")
    print("=" * 80)
    
    assert True
