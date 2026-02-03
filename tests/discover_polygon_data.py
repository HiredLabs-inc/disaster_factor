# tests/discover_polygon_data.py

import os
import requests
import json
from disaster_factor.core import _get_json, _extract_impact_export_url, _find_text_suffix
from bs4 import BeautifulSoup

def discover_polygon_aliases():
    """Discover all available aliases and look for polygon/geometry data."""
    print("=" * 80)
    print("DISCOVERING GDACS POLYGON/GEOMETRY DATA")
    print("=" * 80)
    
    # Get RSS data to find recent events
    rss_url = "https://www.gdacs.org/XML/RSS.xml"
    resp = requests.get(rss_url, timeout=20)
    resp.raise_for_status()
    
    soup = BeautifulSoup(resp.content, features="xml")
    items = soup.find_all("item")
    
    # Test a few recent events for polygon data
    test_events = []
    for item in items[:3]:  # Test first 3 events
        eventtype = _find_text_suffix(item, "eventtype")
        eventid = _find_text_suffix(item, "eventid")
        
        if eventtype and eventid:
            test_events.append((eventtype, eventid))
    
    print(f"Testing {len(test_events)} events for polygon data...")
    
    all_aliases = set()
    polygon_aliases = []
    geometry_data = []
    
    for eventtype, eventid in test_events:
        print(f"\nAnalyzing {eventtype}-{eventid}...")
        
        try:
            # Get event data
            eventdata_url = f"https://www.gdacs.org/gdacsapi/api/events/geteventdata?eventtype={eventtype}&eventid={eventid}"
            eventdata_json = _get_json(eventdata_url, timeout=20)
            impact_url = _extract_impact_export_url(eventdata_json)
            
            if impact_url:
                impact_json = _get_json(impact_url, timeout=20)
                
                # Extract all available aliases
                datums = impact_json.get("datums", [])
                for block in datums:
                    if isinstance(block, dict):
                        alias = block.get("alias", "").strip().casefold()
                        if alias:
                            all_aliases.add(alias)
                            
                            # Look for polygon/geometry related aliases
                            if any(keyword in alias for keyword in ['polygon', 'geometry', 'shape', 'boundary', 'area', 'extent', 'footprint']):
                                polygon_aliases.append(alias)
                                print(f"  🎯 Found polygon-related alias: {alias}")
                            
                            # Check if this alias contains coordinate data that might be polygons
                            records = block.get("datum", [])
                            if isinstance(records, list) and records:
                                for record in records[:2]:  # Check first 2 records
                                    if isinstance(record, dict):
                                        scalars = record.get("scalars", {})
                                        scalar_list = scalars.get("scalar", [])
                                        
                                        # Look for multiple coordinate pairs (indicating polygons)
                                        coord_count = 0
                                        for scalar in scalar_list:
                                            if isinstance(scalar, dict):
                                                name = scalar.get("name", "").lower()
                                                if any(coord in name for coord in ['lat', 'long', 'lon', 'x', 'y']):
                                                    coord_count += 1
                                        
                                        if coord_count > 2:  # More than 2 coordinates suggests polygon
                                            geometry_data.append({
                                                'alias': alias,
                                                'eventtype': eventtype,
                                                'eventid': eventid,
                                                'coord_count': coord_count,
                                                'sample_record': record
                                            })
                                            print(f"  📍 Potential geometry data in {alias}: {coord_count} coordinates")
        
        except Exception as e:
            print(f"  Error processing {eventtype}-{eventid}: {e}")
            continue
    
    print(f"\n" + "=" * 60)
    print("DISCOVERY RESULTS")
    print("=" * 60)
    
    print(f"\nTotal aliases discovered: {len(all_aliases)}")
    print("All aliases:")
    for alias in sorted(all_aliases):
        print(f"  {alias}")
    
    if polygon_aliases:
        print(f"\n🎯 Polygon-related aliases found:")
        for alias in polygon_aliases:
            print(f"  {alias}")
    else:
        print(f"\n❌ No explicit polygon aliases found")
    
    if geometry_data:
        print(f"\n📍 Potential geometry data in aliases:")
        for data in geometry_data:
            print(f"  {data['alias']} ({data['eventtype']}-{data['eventid']}): {data['coord_count']} coordinates")
    else:
        print(f"\n❌ No multi-coordinate geometry data found")
    
    # Save detailed analysis
    output_file = os.path.join(os.path.dirname(__file__), 'polygon_discovery_results.json')
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'all_aliases': sorted(list(all_aliases)),
            'polygon_aliases': polygon_aliases,
            'geometry_data': geometry_data
        }, f, indent=2)
    
    print(f"\nDetailed results saved to: {output_file}")
    
    return all_aliases, polygon_aliases, geometry_data

def analyze_asset_impact():
    """Demonstrate how to use polygon data for asset impact analysis."""
    print("\n" + "=" * 60)
    print("ASSET IMPACT ANALYSIS FRAMEWORK")
    print("=" * 60)
    
    print("""
🎯 ASSET IMPACT ANALYSIS STRATEGY:

1. 📍 Asset Definition:
   - Company assets with lat/long coordinates
   - Facilities, offices, infrastructure
   - Supply chain locations

2. 🌍 Disaster Polygon Data:
   - GDACS impact area polygons
   - Buffer zones around affected areas
   - Multi-level severity zones

3. 🔍 Impact Detection Methods:
   
   A) Point-in-Polygon Test:
      - Check if asset coordinates fall within disaster polygon
      - Most accurate for direct impact assessment
   
   B) Distance-Based Analysis:
      - Calculate distance from asset to polygon boundary
      - Define impact thresholds (e.g., within 50km = high impact)
   
   C) Buffer Analysis:
      - Create buffer zones around disaster polygons
      - Assess assets in different risk zones

4. 📊 Impact Scoring:
   - Direct impact: Asset inside polygon
   - Proximity impact: Asset within X km of polygon
   - Severity levels based on disaster type and distance

5. 🚀 Implementation Approach:
   - Use shapely library for geometric operations
   - Real-time monitoring of GDACS alerts
   - Automated impact notifications
   - Integration with asset management systems

💡 NEXT STEPS:
1. Confirm polygon data availability in GDACS
2. Develop asset impact detection algorithm
3. Create real-time monitoring system
4. Build impact reporting dashboard
""")

if __name__ == "__main__":
    try:
        all_aliases, polygon_aliases, geometry_data = discover_polygon_aliases()
        analyze_asset_impact()
        
        print("\n" + "=" * 80)
        print("POLYGON DATA DISCOVERY COMPLETE")
        print("=" * 80)
        
    except Exception as e:
        print(f"Error during discovery: {e}")
        raise
