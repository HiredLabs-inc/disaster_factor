# tests/compare_geographic_approaches.py

import csv
import os
from collections import defaultdict, Counter

def load_csv_data(filename, exclude_dr=True):
    """Load CSV data and return structured data."""
    data = []
    with open(filename, 'r', encoding='utf-8') as file:
        reader = csv.reader(file)
        
        # Skip header sections until we reach detailed results
        for row in reader:
            if len(row) > 0 and 'DETAILED' in row[0] and 'RESULTS' in row[0]:
                # Read the header row
                header = next(reader)
                break
        
        # Read data rows
        for row in reader:
            if len(row) >= 6:  # Ensure we have enough columns
                # Filter out DR disasters if requested
                if exclude_dr and len(row) > 0 and row[0].strip() == 'DR':
                    continue
                data.append(row)
    
    return data

def extract_eventids(csv_file, eventtype_col=0, eventid_col=1):
    """Extract unique EVENTIDs from CSV file (excluding DR disasters)."""
    eventids = set()
    data = load_csv_data(csv_file, exclude_dr=True)
    
    for row in data:
        if len(row) > max(eventtype_col, eventid_col):
            eventtype = row[eventtype_col].strip()
            eventid = row[eventid_col].strip()
            if eventtype and eventid and eventid.isdigit():
                eventids.add((eventtype, eventid))
    
    return eventids

def analyze_coverage():
    """Analyze coverage and overlap between datasets (excluding DR disasters)."""
    print("=" * 80)
    print("COMPREHENSIVE GEOGRAPHIC DATA QUALITY COMPARISON (EXCLUDING DR DISASTERS)")
    print("=" * 80)
    
    # Load both datasets (excluding DR disasters)
    print("Loading datasets (excluding DR disasters)...")
    alias_data = load_csv_data('tests/alias_analysis.csv', exclude_dr=True)
    coord_data = load_csv_data('tests/coord_analysis.csv', exclude_dr=True)
    
    print(f"Alias analysis: {len(alias_data)} records")
    print(f"Coordinate analysis: {len(coord_data)} records")
    
    # Extract event IDs
    alias_events = extract_eventids('tests/alias_analysis.csv')
    coord_events = extract_eventids('tests/coord_analysis.csv')
    
    print(f"Alias unique events: {len(alias_events)}")
    print(f"Coordinate unique events: {len(coord_events)}")
    
    # Find overlap
    common_events = alias_events & coord_events
    alias_only = alias_events - coord_events
    coord_only = coord_events - alias_events
    
    print(f"Common events: {len(common_events)}")
    print(f"Alias-only events: {len(alias_only)}")
    print(f"Coordinate-only events: {len(coord_only)}")
    
    # Coverage percentages
    alias_coverage = len(common_events) / len(alias_events) * 100 if alias_events else 0
    coord_coverage = len(common_events) / len(coord_events) * 100 if coord_events else 0
    
    print(f"\nCoverage Analysis:")
    print(f"  Alias method: {alias_coverage:.1f}% of events also in coordinate analysis")
    print(f"  Coordinate method: {coord_coverage:.1f}% of events also in alias analysis")
    
    return alias_data, coord_data, common_events, alias_only, coord_only

def analyze_by_country(alias_data, coord_data, common_events):
    """Analyze city-level accuracy by country (key metric: accurate city identification per country)."""
    print("\n" + "=" * 60)
    print("CITY-LEVEL ACCURACY ANALYSIS BY COUNTRY")
    print("=" * 60)
    
    # Group by country and track city-level accuracy
    alias_by_country = defaultdict(list)
    coord_by_country = defaultdict(list)
    
    # Also track unique cities found per country
    alias_cities_by_country = defaultdict(set)
    coord_cities_by_country = defaultdict(set)
    
    for row in alias_data:
        if len(row) >= 7:
            eventtype = row[0].strip()
            eventid = row[1].strip()
            country = row[3].strip()  # Country column
            city = row[4].strip()    # City column
            is_valid = row[5].strip() in ('True', '1')
            if (eventtype, eventid) in common_events and country:
                alias_by_country[country].append(is_valid)
                if city and is_valid:  # Only count verified cities
                    alias_cities_by_country[country].add(city)
    
    for row in coord_data:
        if len(row) >= 8:
            eventtype = row[0].strip()
            eventid = row[1].strip()
            country = row[4].strip()  # Country column
            city = row[8].strip()    # City column (from reverse geocoding)
            is_valid = row[6].strip() in ('True', '1')
            if (eventtype, eventid) in common_events and country:
                coord_by_country[country].append(is_valid)
                if city and is_valid:  # Only count verified cities
                    coord_cities_by_country[country].add(city)
    
    # Get countries with sufficient data (at least 5 records in either dataset)
    all_countries = set(alias_by_country.keys()) | set(coord_by_country.keys())
    significant_countries = {
        country for country in all_countries 
        if len(alias_by_country.get(country, [])) >= 5 or len(coord_by_country.get(country, [])) >= 5
    }
    
    # Compare by country
    print(f"{'COUNTRY':<25} | {'ALIAS':<8} | {'ALIAS%':<8} | {'COORD':<8} | {'COORD%':<8} | {'WINNER':<8} | {'ALIAS_CITIES':<12} | {'COORD_CITIES':<12}")
    print(f"{'-'*25} | {'-'*8} | {'-'*8} | {'-'*8} | {'-'*8} | {'-'*8} | {'-'*12} | {'-'*12}")
    
    country_results = []
    for country in sorted(significant_countries):
        alias_valid = sum(alias_by_country.get(country, []))
        alias_total = len(alias_by_country.get(country, []))
        coord_valid = sum(coord_by_country.get(country, []))
        coord_total = len(coord_by_country.get(country, []))
        
        alias_pct = (alias_valid / alias_total * 100) if alias_total > 0 else 0
        coord_pct = (coord_valid / coord_total * 100) if coord_total > 0 else 0
        
        winner = "ALIAS" if alias_pct > coord_pct else "COORD" if coord_pct > alias_pct else "TIE"
        
        alias_unique_cities = len(alias_cities_by_country.get(country, set()))
        coord_unique_cities = len(coord_cities_by_country.get(country, set()))
        
        print(f"{country:<25} | {alias_valid:<8} | {alias_pct:<7.1f}% | {coord_valid:<8} | {coord_pct:<7.1f}% | {winner:<8} | {alias_unique_cities:<12} | {coord_unique_cities:<12}")
        
        country_results.append({
            'country': country,
            'alias_pct': alias_pct,
            'coord_pct': coord_pct,
            'winner': winner,
            'alias_total': alias_total,
            'coord_total': coord_total,
            'alias_cities': alias_unique_cities,
            'coord_cities': coord_unique_cities
        })
    
    # Summary statistics
    alias_wins = sum(1 for r in country_results if r['winner'] == 'ALIAS')
    coord_wins = sum(1 for r in country_results if r['winner'] == 'COORD')
    ties = sum(1 for r in country_results if r['winner'] == 'TIE')
    
    print(f"\nCity-Level Performance Summary:")
    print(f"  Countries analyzed: {len(country_results)}")
    print(f"  Countries where alias finds more accurate cities: {alias_wins} ({alias_wins/len(country_results)*100:.1f}%)")
    print(f"  Countries where coordinates find more accurate cities: {coord_wins} ({coord_wins/len(country_results)*100:.1f}%)")
    print(f"  Countries with equal performance: {ties} ({ties/len(country_results)*100:.1f}%)")
    
    # City coverage analysis
    total_alias_cities = sum(r['alias_cities'] for r in country_results)
    total_coord_cities = sum(r['coord_cities'] for r in country_results)
    
    print(f"\nUnique City Discovery:")
    print(f"  Total unique cities found by alias method: {total_alias_cities}")
    print(f"  Total unique cities found by coordinate method: {total_coord_cities}")
    print(f"  City coverage advantage: {'ALIAS' if total_alias_cities > total_coord_cities else 'COORD'}")
    
    # Find countries with biggest differences
    biggest_diff = max(country_results, key=lambda x: abs(x['alias_pct'] - x['coord_pct']))
    print(f"\nLargest city accuracy gap: {biggest_diff['country']} ({biggest_diff['winner']} wins by {abs(biggest_diff['alias_pct'] - biggest_diff['coord_pct']):.1f}%)")
    
    return country_results

def analyze_geographic_precision(alias_data, coord_data, common_events):
    """Analyze geographic precision and granularity."""
    print("\n" + "=" * 60)
    print("GEOGRAPHIC PRECISION ANALYSIS")
    print("=" * 60)
    
    # Count records per event (granularity)
    alias_records_per_event = defaultdict(int)
    coord_records_per_event = defaultdict(int)
    
    for row in alias_data:
        if len(row) >= 7:
            eventtype = row[0].strip()
            eventid = row[1].strip()
            if (eventtype, eventid) in common_events:
                alias_records_per_event[(eventtype, eventid)] += 1
    
    for row in coord_data:
        if len(row) >= 8:
            eventtype = row[0].strip()
            eventid = row[1].strip()
            if (eventtype, eventid) in common_events:
                coord_records_per_event[(eventtype, eventid)] += 1
    
    # Calculate averages
    alias_avg_records = sum(alias_records_per_event.values()) / len(alias_records_per_event) if alias_records_per_event else 0
    coord_avg_records = sum(coord_records_per_event.values()) / len(coord_records_per_event) if coord_records_per_event else 0
    
    print(f"Granularity (records per event):")
    print(f"  Alias method: {alias_avg_records:.1f} records per event")
    print(f"  Coordinate method: {coord_avg_records:.1f} records per event")
    print(f"  Precision advantage: {'COORDINATE' if coord_avg_records > alias_avg_records else 'ALIAS'}")
    
    # Location type analysis for coordinates
    coord_sources = defaultdict(int)
    for row in coord_data:
        if len(row) >= 8:
            source = row[2].strip()  # SOURCE column
            coord_sources[source] += 1
    
    print(f"\nCoordinate source distribution:")
    for source, count in sorted(coord_sources.items(), key=lambda x: x[1], reverse=True):
        print(f"  {source}: {count} records")

def analyze_complementary_strengths(alias_data, coord_data, common_events):
    """Analyze where each method excels."""
    print("\n" + "=" * 60)
    print("COMPLEMENTARY STRENGTHS ANALYSIS")
    print("=" * 60)
    
    # Find events where one method succeeds and other fails
    alias_success = set()
    coord_success = set()
    
    for row in alias_data:
        if len(row) >= 7:
            eventtype = row[0].strip()
            eventid = row[1].strip()
            is_valid = row[5].strip() in ('True', '1')
            if (eventtype, eventid) in common_events and is_valid:
                alias_success.add((eventtype, eventid))
    
    for row in coord_data:
        if len(row) >= 8:
            eventtype = row[0].strip()
            eventid = row[1].strip()
            is_valid = row[6].strip() in ('True', '1')
            if (eventtype, eventid) in common_events and is_valid:
                coord_success.add((eventtype, eventid))
    
    # Find exclusive successes
    alias_only_success = alias_success - coord_success
    coord_only_success = coord_success - alias_success
    both_success = alias_success & coord_success
    
    print(f"Success patterns on common events:")
    print(f"  Both methods succeed: {len(both_success)} events")
    print(f"  Only alias succeeds: {len(alias_only_success)} events")
    print(f"  Only coordinate succeeds: {len(coord_only_success)} events")
    print(f"  Neither succeeds: {len(common_events) - len(both_success) - len(alias_only_success) - len(coord_only_success)} events")
    
    # Calculate combined coverage potential
    combined_success = alias_success | coord_success
    combined_coverage = len(combined_success) / len(common_events) * 100 if common_events else 0
    
    alias_coverage = len(alias_success) / len(common_events) * 100 if common_events else 0
    coord_coverage = len(coord_success) / len(common_events) * 100 if common_events else 0
    
    print(f"\nCoverage on common events:")
    print(f"  Alias method: {alias_coverage:.1f}%")
    print(f"  Coordinate method: {coord_coverage:.1f}%")
    print(f"  Combined potential: {combined_coverage:.1f}%")
    print(f"  Improvement over best single method: {combined_coverage - max(alias_coverage, coord_coverage):.1f}%")

def generate_recommendations(alias_data, coord_data, common_events, country_results):
    """Generate strategic recommendations based on country-level analysis."""
    print("\n" + "=" * 60)
    print("STRATEGIC RECOMMENDATIONS (COUNTRY-LEVEL)")
    print("=" * 60)
    
    # Calculate overall success rates
    alias_success_rate = sum(1 for row in alias_data if len(row) >= 7 and row[5].strip() in ('True', '1') and (row[0].strip(), row[1].strip()) in common_events) / len(common_events) * 100 if common_events else 0
    coord_success_rate = sum(1 for row in coord_data if len(row) >= 8 and row[6].strip() in ('True', '1') and (row[0].strip(), row[1].strip()) in common_events) / len(common_events) * 100 if common_events else 0
    
    print("DATA QUALITY ASSESSMENT:")
    print(f"  Alias method accuracy: {alias_success_rate:.1f}%")
    print(f"  Coordinate method accuracy: {coord_success_rate:.1f}%")
    
    # Country-level insights
    alias_wins = sum(1 for r in country_results if r['winner'] == 'ALIAS')
    coord_wins = sum(1 for r in country_results if r['winner'] == 'COORD')
    ties = sum(1 for r in country_results if r['winner'] == 'TIE')
    
    print(f"\nCOUNTRY-LEVEL PERFORMANCE:")
    print(f"  Countries where alias wins: {alias_wins}/{len(country_results)} ({alias_wins/len(country_results)*100:.1f}%)")
    print(f"  Countries where coordinate wins: {coord_wins}/{len(country_results)} ({coord_wins/len(country_results)*100:.1f}%)")
    print(f"  Countries with tie performance: {ties}/{len(country_results)} ({ties/len(country_results)*100:.1f}%)")
    
    # Find countries where coordinates significantly outperform
    coord_superior = [r for r in country_results if r['winner'] == 'COORD' and r['coord_pct'] > r['alias_pct'] + 10]
    alias_superior = [r for r in country_results if r['winner'] == 'ALIAS' and r['alias_pct'] > r['coord_pct'] + 10]
    
    print("\nRECOMMENDATIONS:")
    
    if alias_wins > coord_wins * 2:
        print("  🎯 PRIMARY: Use alias method for country-level disaster location")
        print("  📊 SUPPLEMENTAL: Use coordinate method for specific countries")
        if coord_superior:
            print(f"  🌍 Consider coordinates for: {', '.join([c['country'] for c in coord_superior[:3]])}")
    elif coord_wins > alias_wins * 2:
        print("  🎯 PRIMARY: Use coordinate method for country-level disaster location")
        print("  📊 SUPPLEMENTAL: Use alias method for specific countries")
        if alias_superior:
            print(f"  🌍 Consider aliases for: {', '.join([c['country'] for c in alias_superior[:3]])}")
    else:
        print("  � HYBRID: Country-specific method selection")
        print("  � Use alias for {alias_wins} countries, coordinates for {coord_wins} countries")
    
    print("\nIMPLEMENTATION STRATEGY:")
    print("  1. Implement country-based method selection")
    print("  2. Use alias method as default for new countries")
    print("  3. Apply coordinate method where proven superior")
    print("  4. Monitor country-level performance over time")

def write_comparison_report(country_results):
    """Write detailed country-level comparison report to CSV."""
    print("\n" + "=" * 60)
    print("GENERATING COUNTRY-LEVEL COMPARISON REPORT")
    print("=" * 60)
    
    # Create comprehensive comparison data
    report_data = []
    
    # Load and process data
    alias_data = load_csv_data('tests/alias_analysis.csv', exclude_dr=True)
    coord_data = load_csv_data('tests/coord_analysis.csv', exclude_dr=True)
    
    # Add summary statistics
    report_data.append(['COUNTRY-LEVEL GEOGRAPHIC COMPARISON REPORT (EXCLUDING DR DISASTERS)'])
    report_data.append([])
    report_data.append(['SUMMARY STATISTICS'])
    report_data.append(['Metric', 'Alias Method', 'Coordinate Method'])
    report_data.append(['Total Records', len(alias_data), len(coord_data)])
    report_data.append(['City Verification Rate', 
                      f"{sum(1 for row in alias_data if len(row) >= 7 and row[5].strip() in ('True', '1')) / len(alias_data) * 100:.1f}%",
                      f"{sum(1 for row in coord_data if len(row) >= 8 and row[6].strip() in ('True', '1')) / len(coord_data) * 100:.1f}%"])
    report_data.append([])
    
    # Add country-level results
    report_data.append(['COUNTRY-LEVEL PERFORMANCE'])
    report_data.append(['Country', 'Alias Success Rate', 'Coordinate Success Rate', 'Winner', 'Alias Total', 'Coordinate Total'])
    
    for result in sorted(country_results, key=lambda x: x['alias_pct'], reverse=True):
        report_data.append([
            result['country'],
            f"{result['alias_pct']:.1f}%",
            f"{result['coord_pct']:.1f}%",
            result['winner'],
            result['alias_total'],
            result['coord_total']
        ])
    
    # Add country-specific recommendations
    alias_wins = sum(1 for r in country_results if r['winner'] == 'ALIAS')
    coord_wins = sum(1 for r in country_results if r['winner'] == 'COORD')
    
    report_data.append([])
    report_data.append(['COUNTRY-SPECIFIC RECOMMENDATIONS'])
    report_data.append(['Countries where alias method is superior', alias_wins])
    report_data.append(['Countries where coordinate method is superior', coord_wins])
    
    # Write report
    report_file = os.path.join(os.path.dirname(__file__), 'country_geographic_comparison_report.csv')
    with open(report_file, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        for row in report_data:
            writer.writerow(row)
    
    print(f"Country-level detailed report written to: {report_file}")

def main():
    """Main comparison analysis function."""
    try:
        # Run comprehensive analysis
        alias_data, coord_data, common_events, alias_only, coord_only = analyze_coverage()
        country_results = analyze_by_country(alias_data, coord_data, common_events)
        analyze_geographic_precision(alias_data, coord_data, common_events)
        analyze_complementary_strengths(alias_data, coord_data, common_events)
        generate_recommendations(alias_data, coord_data, common_events, country_results)
        write_comparison_report(country_results)
        
        print("\n" + "=" * 80)
        print("COUNTRY-LEVEL GEOGRAPHIC DATA QUALITY COMPARISON COMPLETE")
        print("=" * 80)
        
    except Exception as e:
        print(f"Error during analysis: {e}")
        raise

if __name__ == "__main__":
    main()
