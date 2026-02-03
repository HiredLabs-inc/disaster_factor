# tests/polygon_coverage_analysis.py

import os
import requests
import json
from collections import defaultdict
from disaster_factor.core import _get_json, _extract_impact_export_url, _find_text_suffix
from bs4 import BeautifulSoup

def analyze_polygon_coverage():
    """Analyze polygon data coverage across GDACS disasters."""
    print("=" * 80)
    print("GDACS POLYGON DATA COVERAGE ANALYSIS")
    print("=" * 80)
    
    # Get RSS data to find recent events
    rss_url = "https://www.gdacs.org/XML/RSS.xml"
    resp = requests.get(rss_url, timeout=20)
    resp.raise_for_status()
    
    soup = BeautifulSoup(resp.content, features="xml")
    items = soup.find_all("item")
    
    print(f"Found {len(items)} total disasters in RSS feed")
    
    # Analyze all events (not just first 3)
    coverage_stats = {
        'total_disasters': 0,
        'disasters_with_polygons': 0,
        'disasters_with_shape_json': 0,
        'disasters_with_boundbox': 0,
        'disasters_with_shape_wkt': 0,
        'by_disaster_type': defaultdict(lambda: {
            'total': 0,
            'with_polygons': 0,
            'polygon_sources': defaultdict(int)
        }),
        'polygon_sources': defaultdict(int)
    }
    
    # Test each event for polygon data
    for i, item in enumerate(items):
        eventtype = _find_text_suffix(item, "eventtype")
        eventid = _find_text_suffix(item, "eventid")
        
        if not eventtype or not eventid:
            continue
        
        if eventtype == 'DR':  # Skip droughts for this analysis
            continue
            
        coverage_stats['total_disasters'] += 1
        coverage_stats['by_disaster_type'][eventtype]['total'] += 1
        
        print(f"\rAnalyzing disaster {i+1}/{len(items)}: {eventtype}-{eventid}", end="", flush=True)
        
        try:
            # Get event data
            eventdata_url = f"https://www.gdacs.org/gdacsapi/api/events/geteventdata?eventtype={eventtype}&eventid={eventid}"
            eventdata_json = _get_json(eventdata_url, timeout=10)
            impact_url = _extract_impact_export_url(eventdata_json)
            
            if impact_url:
                impact_json = _get_json(impact_url, timeout=10)
                
                # Check for polygon data in all aliases
                has_polygons = False
                polygon_sources = []
                
                datums = impact_json.get("datums", [])
                for block in datums:
                    if isinstance(block, dict):
                        alias = block.get("alias", "").strip().casefold()
                        records = block.get("datum", [])
                        
                        if isinstance(records, list):
                            for record in records:
                                if isinstance(record, dict):
                                    scalars = record.get("scalars", {})
                                    scalar_list = scalars.get("scalar", [])
                                    
                                    for scalar in scalar_list:
                                        if isinstance(scalar, dict):
                                            name = scalar.get("name", "")
                                            value = scalar.get("value", "")
                                            
                                            # Check for polygon data sources
                                            if name == "SHAPE_JSON" and value:
                                                has_polygons = True
                                                polygon_sources.append("SHAPE_JSON")
                                                coverage_stats['disasters_with_shape_json'] += 1
                                                coverage_stats['polygon_sources']["SHAPE_JSON"] += 1
                                                coverage_stats['by_disaster_type'][eventtype]['polygon_sources']["SHAPE_JSON"] += 1
                                                
                                            elif name == "boundiboxjson" and value:
                                                has_polygons = True
                                                polygon_sources.append("boundiboxjson")
                                                coverage_stats['disasters_with_boundbox'] += 1
                                                coverage_stats['polygon_sources']["boundiboxjson"] += 1
                                                coverage_stats['by_disaster_type'][eventtype]['polygon_sources']["boundiboxjson"] += 1
                                                
                                            elif name == "SHAPE" and value and value.startswith("POLYGON"):
                                                has_polygons = True
                                                polygon_sources.append("SHAPE_WKT")
                                                coverage_stats['disasters_with_shape_wkt'] += 1
                                                coverage_stats['polygon_sources']["SHAPE_WKT"] += 1
                                                coverage_stats['by_disaster_type'][eventtype]['polygon_sources']["SHAPE_WKT"] += 1
                
                if has_polygons:
                    coverage_stats['disasters_with_polygons'] += 1
                    coverage_stats['by_disaster_type'][eventtype]['with_polygons'] += 1
        
        except Exception as e:
            print(f"\nError analyzing {eventtype}-{eventid}: {e}")
            continue
    
    print(f"\n\n" + "=" * 60)
    print("COVERAGE ANALYSIS RESULTS")
    print("=" * 60)
    
    # Overall coverage
    total_disasters = coverage_stats['total_disasters']
    with_polygons = coverage_stats['disasters_with_polygons']
    coverage_percentage = (with_polygons / total_disasters * 100) if total_disasters > 0 else 0
    
    print(f"\nOVERALL POLYGON COVERAGE:")
    print(f"  Total disasters analyzed: {total_disasters}")
    print(f"  Disasters with polygon data: {with_polygons}")
    print(f"  Coverage percentage: {coverage_percentage:.1f}%")
    print(f"  1:{total_disasters/with_polygons:.1f} ratio (disasters:polygon disasters)")
    
    # Polygon source breakdown
    print(f"\nPOLYGON DATA SOURCES:")
    for source, count in coverage_stats['polygon_sources'].items():
        percentage = (count / total_disasters * 100) if total_disasters > 0 else 0
        print(f"  {source}: {count} disasters ({percentage:.1f}%)")
    
    # By disaster type
    print(f"\nCOVERAGE BY DISASTER TYPE:")
    print(f"{'TYPE':<8} | {'TOTAL':<8} | {'POLYGON':<8} | {'COVERAGE':<10} | {'RATIO'}")
    print(f"{'-'*8} | {'-'*8} | {'-'*8} | {'-'*10} | {'-'*6}")
    
    for disaster_type, stats in sorted(coverage_stats['by_disaster_type'].items()):
        total = stats['total']
        with_poly = stats['with_polygons']
        coverage_pct = (with_poly / total * 100) if total > 0 else 0
        ratio = f"1:{total/with_poly:.1f}" if with_poly > 0 else "N/A"
        
        print(f"{disaster_type:<8} | {total:<8} | {with_poly:<8} | {coverage_pct:<9.1f}% | {ratio}")
    
    # Detailed source breakdown by type
    print(f"\nDETAILED SOURCES BY DISASTER TYPE:")
    for disaster_type, stats in sorted(coverage_stats['by_disaster_type'].items()):
        if stats['polygon_sources']:
            print(f"\n{disaster_type}:")
            for source, count in stats['polygon_sources'].items():
                print(f"  {source}: {count}")
    
    # Save detailed results
    output_file = os.path.join(os.path.dirname(__file__), 'polygon_coverage_report.json')
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(coverage_stats, f, indent=2, default=str)
    
    print(f"\nDetailed analysis saved to: {output_file}")
    
    return coverage_stats

def generate_recommendations(coverage_stats):
    """Generate recommendations based on coverage analysis."""
    print("\n" + "=" * 60)
    print("COVERAGE ANALYSIS RECOMMENDATIONS")
    print("=" * 60)
    
    total_disasters = coverage_stats['total_disasters']
    with_polygons = coverage_stats['disasters_with_polygons']
    coverage_percentage = (with_polygons / total_disasters * 100) if total_disasters > 0 else 0
    
    print(f"\n📊 COVERAGE ASSESSMENT:")
    if coverage_percentage >= 90:
        print("  🟢 EXCELLENT: Near-complete polygon coverage")
        print("  ✅ Asset impact analysis will be highly reliable")
    elif coverage_percentage >= 75:
        print("  🟡 GOOD: Strong polygon coverage")
        print("  ⚠️  Some disasters will need alternative analysis")
    elif coverage_percentage >= 50:
        print("  🟠 MODERATE: Moderate polygon coverage")
        print("  ⚠️  Significant gap in disaster coverage")
    else:
        print("  🔴 POOR: Limited polygon coverage")
        print("  ❌ Asset impact analysis will have major gaps")
    
    print(f"\n🎯 STRATEGIC RECOMMENDATIONS:")
    
    # Analyze by disaster type
    weak_types = []
    strong_types = []
    
    for disaster_type, stats in coverage_stats['by_disaster_type'].items():
        coverage_pct = (stats['with_polygons'] / stats['total'] * 100) if stats['total'] > 0 else 0
        if coverage_pct < 50:
            weak_types.append(disaster_type)
        elif coverage_pct >= 80:
            strong_types.append(disaster_type)
    
    if strong_types:
        print(f"  ✅ PRIORITIZE these disaster types for polygon analysis:")
        for dt in strong_types:
            print(f"    - {dt} (high coverage)")
    
    if weak_types:
        print(f"  ⚠️  SUPPLEMENT polygon analysis for these types:")
        for dt in weak_types:
            print(f"    - {dt} (low coverage - consider proximity analysis)")
    
    # Source recommendations
    print(f"\n📋 DATA SOURCE STRATEGY:")
    sources = coverage_stats['polygon_sources']
    if sources.get("SHAPE_JSON", 0) > 0:
        print(f"  🎯 Primary: SHAPE_JSON ({sources['SHAPE_JSON']} disasters)")
    if sources.get("boundiboxjson", 0) > 0:
        print(f"  🛡️  Fallback: boundiboxjson ({sources['boundinboxjson']} disasters)")
    if sources.get("SHAPE_WKT", 0) > 0:
        print(f"  🔧 Backup: SHAPE_WKT ({sources['SHAPE_WKT']} disasters)")
    
    print(f"\n🚀 IMPLEMENTATION READINESS:")
    if coverage_percentage >= 75:
        print("  ✅ READY: Polygon-based asset impact analysis is production-ready")
        print("  📈 EXPECTED: Reliable coverage for most disaster scenarios")
    else:
        print("  ⚠️  HYBRID APPROACH NEEDED:")
        print("     - Use polygon analysis where available")
        print("     - Supplement with proximity analysis for gaps")
        print("     - Monitor coverage improvements over time")

if __name__ == "__main__":
    try:
        coverage_stats = analyze_polygon_coverage()
        generate_recommendations(coverage_stats)
        
        print("\n" + "=" * 80)
        print("POLYGON COVERAGE ANALYSIS COMPLETE")
        print("=" * 80)
        
    except Exception as e:
        print(f"Error during analysis: {e}")
        raise
