# tests/alias_discovery.py
"""
One-time GDACS alias discovery script.
Run this script to discover all available GDACS aliases and compare with current usage.
"""

import requests
from bs4 import BeautifulSoup
from disaster_factor.core import recon, _get_json, _extract_impact_export_url, _find_text_suffix


def discover_all_gdacs_aliases():
    """Discover ALL available aliases in GDACS data by examining raw impact JSON."""
    
    print("Discovering ALL GDACS aliases...")
    
    # Get raw impact data to discover all aliases
    rss_url = "https://www.gdacs.org/XML/RSS.xml"
    resp = requests.get(rss_url, timeout=20)
    resp.raise_for_status()
    
    soup = BeautifulSoup(resp.content, features="xml")
    items = soup.find_all("item")
    
    events = []
    for item in items:
        eventtype = _find_text_suffix(item, "eventtype")
        eventid = _find_text_suffix(item, "eventid")
        if not eventtype or not eventid:
            continue
        
        eventdata_url = (
            "https://www.gdacs.org/gdacsapi/api/events/geteventdata"
            f"?eventtype={eventtype}&eventid={eventid}"
        )
        events.append({"eventtype": eventtype, "eventid": eventid, "eventdata_url": eventdata_url})
    
    print(f"Found {len(events)} total events, performing EXHAUSTIVE search of all events...")
    
    # Discover aliases from raw impact data
    all_aliases = set()
    
    for idx, ev in enumerate(events):  # EXHAUSTIVE search of ALL events
        try:
            eventdata_json = _get_json(ev["eventdata_url"], timeout=20)
        except Exception as e:
            continue
        
        impact_url = _extract_impact_export_url(eventdata_json)
        if not impact_url:
            continue
        
        try:
            impact_json = _get_json(impact_url, timeout=20)
        except Exception as e:
            print(f"    Event {idx+1}: Failed to get impact JSON: {e}")
            continue
        
        # The key is 'datums'
        datums = impact_json.get("datums", [])
        
        for block in datums:
            if isinstance(block, dict):
                alias = block.get("alias")
                if isinstance(alias, str):
                    clean_alias = alias.strip().casefold()
                    all_aliases.add(clean_alias)
        
        if (idx + 1) % 10 == 0 or idx == len(events) - 1:
            print(f"  Processed {idx+1}/{len(events)} events, found {len(all_aliases)} aliases so far...")
    
    return sorted(all_aliases)


def get_current_aliases(disasters):
    """Get aliases currently being used in the disaster dataset."""
    
    current_aliases = set()
    for d in disasters:
        alias = d.get('alias_source', '')
        if alias:
            current_aliases.add(alias)
    
    return sorted(current_aliases)


def main():
    """Main discovery function - run this to get all alias information."""
    
    print("=" * 80)
    print("GDACS ALIAS DISCOVERY REPORT")
    print("=" * 80)
    
    # Discover ALL available aliases in GDACS
    all_gdacs_aliases = discover_all_gdacs_aliases()
    
    # Get current disaster data
    print("\nGetting current disaster data...")
    disasters, total_red = recon(debug=False)
    
    # Discover aliases currently in dataset
    current_aliases = get_current_aliases(disasters)
    
    # Calculate missing aliases
    missing_aliases = set(all_gdacs_aliases) - set(current_aliases)
    
    print("\n" + "=" * 80)
    print("DISCOVERY RESULTS")
    print("=" * 80)
    
    print(f"\nSUMMARY:")
    print(f"  Total GDACS aliases available: {len(all_gdacs_aliases)}")
    print(f"  Currently using aliases: {len(current_aliases)}")
    print(f"  Missing aliases not tested: {len(missing_aliases)}")
    
    print(f"\nALL GDACS ALIASES ({len(all_gdacs_aliases)}):")
    for i, alias in enumerate(all_gdacs_aliases, 1):
        print(f"  {i:2d}. {alias}")
    
    print(f"\nCURRENTLY USING ({len(current_aliases)}):")
    for i, alias in enumerate(current_aliases, 1):
        print(f"  {i:2d}. {alias}")
    
    print(f"\n❌ MISSING ALIASES ({len(missing_aliases)}):")
    for i, alias in enumerate(sorted(missing_aliases), 1):
        print(f"  {i:2d}. {alias}")
    
    print(f"\nFOR MANUAL PATCHING:")
    print(f"all_gdacs_aliases = {all_gdacs_aliases}")
    print(f"current_aliases = {current_aliases}")
    print(f"missing_aliases = {sorted(missing_aliases)}")
    
    print("\n" + "=" * 80)
    print("DISCOVERY COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
