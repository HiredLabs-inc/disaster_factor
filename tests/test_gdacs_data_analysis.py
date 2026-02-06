"""
Test to examine actual GDACS impact_json structure and coordinate semantics.
"""
import json
from disaster_factor.core import _get_json, _extract_impact_url, _extract_disaster_coordinates, _scalars_to_dict


def test_analyze_gdacs_impact_data():
    """Fetch real GDACS data and analyze what coordinates represent."""
    
    # Use a known event from your affected.csv
    # Event 1517494 (Japan earthquake) or 1517835 (Caribbean earthquake)
    eventtype = "EQ"
    eventid = "1517494"
    
    print(f"\n[ANALYSIS] Analyzing Event: {eventtype} {eventid}")
    
    try:
        # Fetch eventdata
        eventdata_url = (
            f"https://www.gdacs.org/gdacsapi/api/events/geteventdata"
            f"?eventtype={eventtype}&eventid={eventid}"
        )
        
        print(f"[ANALYSIS] Fetching eventdata from: {eventdata_url}")
        eventdata_json = _get_json(eventdata_url)
        
        # Extract impact URL
        impact_url = _extract_impact_url(eventdata_json)
        if not impact_url:
            print("[ANALYSIS] No impact URL found")
            return
        
        print(f"[ANALYSIS] Fetching impact data from: {impact_url}")
        impact_json = _get_json(impact_url)
        
        # Analyze the structure
        print(f"\n{'='*80}")
        print("IMPACT JSON STRUCTURE ANALYSIS")
        print(f"{'='*80}")
        
        # Check top-level keys
        print(f"\n[STRUCTURE] Top-level keys: {list(impact_json.keys())}")
        
        # Analyze datums
        datums = impact_json.get("datums", [])
        print(f"\n[STRUCTURE] Number of datum blocks: {len(datums)}")
        
        # Examine first few datum blocks in detail
        for idx, block in enumerate(datums[:5], 1):
            print(f"\n{'─'*80}")
            print(f"DATUM BLOCK #{idx}")
            print(f"{'─'*80}")
            
            if not isinstance(block, dict):
                print(f"  Type: {type(block)}")
                continue
            
            # Check for alias
            alias = block.get("alias", "")
            print(f"  Alias: '{alias}'")
            
            # Check for datum records
            records = block.get("datum", [])
            print(f"  Number of records: {len(records) if isinstance(records, list) else 'N/A'}")
            
            # Examine first record in detail
            if isinstance(records, list) and records:
                first_record = records[0]
                if isinstance(first_record, dict):
                    print(f"\n  First Record Structure:")
                    
                    # Get scalars
                    scalars_dict = _scalars_to_dict(first_record)
                    print(f"    Scalar fields: {list(scalars_dict.keys())}")
                    
                    # Look for coordinates
                    lat = lon = None
                    for name, value in scalars_dict.items():
                        name_lower = name.lower()
                        if 'lat' in name_lower:
                            lat = value
                            print(f"    Latitude field: {name} = {value}")
                        elif 'long' in name_lower or 'lon' in name_lower:
                            lon = value
                            print(f"    Longitude field: {name} = {value}")
                    
                    # Show other interesting fields
                    interesting_fields = ['city', 'country', 'name', 'location', 'place', 'admin']
                    for field in interesting_fields:
                        for name, value in scalars_dict.items():
                            if field in name.lower() and value:
                                print(f"    {name}: {value}")
        
        # Extract all coordinates
        print(f"\n{'='*80}")
        print("COORDINATE EXTRACTION ANALYSIS")
        print(f"{'='*80}")
        
        all_coords = _extract_disaster_coordinates(impact_json)
        print(f"\n[COORDINATES] Total coordinates extracted: {len(all_coords)}")
        
        if all_coords:
            print(f"\n[COORDINATES] First 10 coordinates:")
            for idx, coord in enumerate(all_coords[:10], 1):
                print(f"  {idx}. Lat: {coord['latitude']:.4f}, Lon: {coord['longitude']:.4f}")
            
            # Check for coordinate clustering
            if len(all_coords) > 1:
                from disaster_factor.core import _haversine_distance
                
                print(f"\n[COORDINATES] Distance analysis (first 5 coords):")
                for i in range(min(4, len(all_coords) - 1)):
                    coord1 = all_coords[i]
                    coord2 = all_coords[i + 1]
                    distance = _haversine_distance(
                        coord1['latitude'], coord1['longitude'],
                        coord2['latitude'], coord2['longitude']
                    )
                    print(f"  Coord {i+1} to Coord {i+2}: {distance:.2f} miles")
        
        # Save full impact_json for manual inspection
        output_file = "tests/data/sample_impact_json.json"
        with open(output_file, 'w') as f:
            json.dump(impact_json, f, indent=2)
        print(f"\n[ANALYSIS] Full impact_json saved to: {output_file}")
        
        print(f"\n{'='*80}")
        print("ANALYSIS COMPLETE")
        print(f"{'='*80}")
        
    except Exception as e:
        print(f"[ERROR] Analysis failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_analyze_gdacs_impact_data()
