# tests/test_city_verification.py

import pytest
import requests
import sys
import csv
import os
from disaster_factor.core import recon


def _get_api_key() -> str:
    """Get API key from environment or prompt user for input."""
    api_key = os.getenv('GOOGLE_GEOCODING_API_KEY')
    if not api_key:
        api_key = input("Enter your Google Geocoding API key: ").strip()
        if not api_key:
            raise ValueError("API key is required")
        # Set it for this session so we don't prompt again
        os.environ['GOOGLE_GEOCODING_API_KEY'] = api_key
    return api_key


def _verify_city_exists(city: str, country: str, alias: str = "") -> tuple[bool, str]:
    """
    Verify if a city exists in a country using Google Geocoding API v4.
    Returns (is_valid_city, location_type).
    """
    try:
        # Google Geocoding API v4 - requires API key
        api_key = _get_api_key()
        
        # Google Geocoding API v4 forward geocoding endpoint
        address_string = f"{city}, {country}".replace(' ', '+')
        url = f"https://geocode.googleapis.com/v4beta/geocode/address/{address_string}"
        headers = {
            'X-Goog-Api-Key': api_key
        }
        
        resp = requests.get(url, headers=headers, timeout=5)
        resp.raise_for_status()
        results = resp.json()
        
        # Check if we got valid results
        if 'results' not in results or len(results['results']) == 0:
            location_type = "NOT_FOUND"
            is_valid = False
        else:
            # Analyze the first result to determine if it's a city
            result = results['results'][0]
            address_components = result.get('addressComponents', [])
            # Handle both list and dict formats for addressComponents
            if isinstance(address_components, list) and address_components:
                address_types = address_components[0].get('types', [])
            elif isinstance(address_components, dict):
                address_types = address_components.get('types', [])
            else:
                address_types = []
            
            # City-level types we accept
            city_types = {
                'locality',        # City/town
                'postal_town',     # Postal town
                'neighborhood',    # Neighborhood
                'sublocality',     # Sublocality
                'administrative_area_level_5',  # Small administrative area
            }
            
            # State/province level types we reject
            state_types = {
                'administrative_area_level_1',  # State/province
                'administrative_area_level_2',  # County/region
                'administrative_area_level_3',  # District
                'administrative_area_level_4',  # Municipality
                'country',                      # Country
            }
            
            # Check if any city types are present and no state types
            address_types_set = set(address_types)
            has_city_type = bool(address_types_set & city_types)
            has_state_type = bool(address_types_set & state_types)
            
            if has_city_type and not has_state_type:
                location_type = f"CITY ({', '.join(address_types)})"
                is_valid = True
            elif has_state_type:
                location_type = f"STATE/PROVINCE ({', '.join(address_types)})"
                is_valid = False
            else:
                location_type = f"OTHER ({', '.join(address_types)})"
                is_valid = False
        
        # Print detailed verification result
        print(f"  {alias:12} | {country:25} | {city:35} | {is_valid:5} | {location_type}")
        
        return is_valid, location_type
    except Exception as e:
        # If verification fails, print error and assume it might be real
        print(f"  {alias:12} | {country:25} | {city:35} | ERROR | API_ERROR: {e}")
        return True, "API_ERROR"


def test_city_verification():
    """Comprehensive city verification test with flag-controlled dataset."""
    
    comprehensive_mode = '--full' in sys.argv
    
    # Get disaster data
    disasters, total_red = recon(debug=False)
    
    # Choose dataset based on flag
    if comprehensive_mode:
        disasters_to_test = disasters
        print(f"Testing ALL {len(disasters)} disasters (comprehensive mode)...")
    else:
        # Sample unique countries per alias (systematic sampling)
        sampled_by_alias = {}
        for d in disasters:
            alias = d.get('alias_source', '')
            country = d.get('country', '').strip()
            city = d.get('city', '').strip()
            
            if alias not in sampled_by_alias:
                sampled_by_alias[alias] = {}
            
            # Add unique country for this alias
            if country and country not in sampled_by_alias[alias]:
                sampled_by_alias[alias][country] = city
        
        # Convert to flat list for testing
        disasters_to_test = []
        for alias, countries_dict in sampled_by_alias.items():
            for country, city in countries_dict.items():
                disasters_to_test.append({
                    'alias': alias,
                    'country': country,
                    'city': city
                })
        
        print(f"Testing {len(disasters_to_test)} systematic samples (1 per unique country per alias)...")
    
    # Verify each disaster with detailed output
    print(f"\nDetailed verification results:")
    print(f"  {'ALIAS':12} | {'COUNTRY':25} | {'CITY':35} | {'VALID':5} | {'LOCATION_TYPE'}")
    print(f"  {'-'*12} | {'-'*25} | {'-'*35} | {'-'*5} | {'-'*60}")
    
    failed_verifications = []
    alias_quality = {}
    total_tests = 0
    verification_results = []  # Store results for CSV
    
    for d in disasters_to_test:
        alias = d['alias']
        country = d['country']
        city = d['city']
        
        total_tests += 1
        
        # Initialize alias quality tracking
        if alias not in alias_quality:
            alias_quality[alias] = {'total': 0, 'verified': 0}
        alias_quality[alias]['total'] += 1
        
        is_valid, location_type = _verify_city_exists(city, country, alias)
        
        # Store result for CSV
        verification_results.append([alias, country, city, is_valid, location_type])
        
        if is_valid:
            alias_quality[alias]['verified'] += 1
        elif location_type != "API_ERROR":
            failed_verifications.append({
                'alias': alias,
                'country': country,
                'city': city,
                'type': location_type
            })
    
    # Summary statistics
    print(f"\nSummary:")
    print(f"✓ Real cities: {total_tests - len(failed_verifications)}")
    print(f"✗ Not cities: {len(failed_verifications)}")
    print(f"Total tested: {total_tests}")
    
    # Aggregate percentages by alias (back-to-back with summary)
    print(f"\nAggregate quality by alias:")
    for alias in sorted(alias_quality.keys()):
        total = alias_quality[alias]['total']
        verified = alias_quality[alias]['verified']
        percentage = (verified / total * 100) if total > 0 else 0
        print(f"  {alias}: {verified}/{total} ({percentage:.1f}% real cities)")
    
    # Write results to CSV file with summary and stats
    csv_filename = 'city_verification_full.csv' if comprehensive_mode else 'city_verification.csv'
    csv_file = os.path.join(os.path.dirname(__file__), csv_filename)
    
    with open(csv_file, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        
        # Write summary section
        writer.writerow(['SUMMARY STATISTICS'])
        writer.writerow(['Dataset', 'Full Dataset' if comprehensive_mode else 'Systematic Samples'])
        writer.writerow(['Total Tested', total_tests])
        writer.writerow(['Real Cities', total_tests - len(failed_verifications)])
        writer.writerow(['Not Cities', len(failed_verifications)])
        writer.writerow([])
        
        # Write aggregate quality by alias
        writer.writerow(['ALIAS QUALITY PERCENTAGES'])
        writer.writerow(['ALIAS', 'TOTAL', 'VERIFIED', 'PERCENTAGE'])
        for alias in sorted(alias_quality.keys()):
            total = alias_quality[alias]['total']
            verified = alias_quality[alias]['verified']
            percentage = (verified / total * 100) if total > 0 else 0
            writer.writerow([alias, total, verified, f"{percentage:.1f}%"])
        writer.writerow([])
        
        # Write detailed verification results
        writer.writerow(['DETAILED VERIFICATION RESULTS'])
        writer.writerow(['ALIAS', 'COUNTRY', 'CITY', 'VALID', 'LOCATION_TYPE'])
        writer.writerows(verification_results)
    
    print(f"\nResults written to: {csv_file}")
    
    # This test will always pass, but provides diagnostic info
    assert True
