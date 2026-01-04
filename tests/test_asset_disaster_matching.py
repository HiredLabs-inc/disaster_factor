import pytest
from disaster_factor.core import intel, _parse_impact_json_to_disasters, _extract_polygons_from_impact
from disaster_factor.core import _alias_analysis, _coordinate_analysis, _polygon_analysis

class TestAssetDisasterMatching:
    """Test assets in known GDACS disaster locations are detected correctly."""
    
    def test_martinique_earthquake_alias_matching(self):
        """Test Martinique assets match Dominica earthquake via alias method."""
        # Asset data
        cities = {"AST_CARIB_1": "Roseau", "AST_CARIB_2": "Le Lamentin"}
        countries = {"AST_CARIB_1": "Dominica", "AST_CARIB_2": "Martinique"}
        coordinates = {"AST_CARIB_1": (15.3010, -61.3880), "AST_CARIB_2": (14.6115, -61.0698)}
        assets_by_id = {
            "AST_CARIB_1": {"unique_id": "AST_CARIB_1", "type": "building"},
            "AST_CARIB_2": {"unique_id": "AST_CARIB_2", "type": "personnel"}
        }
        
        # Create disasters that should match
        disasters = [
            {"city": "Le Lamentin", "country": "Martinique", "eventid": "1517835", "type": "EQ"},
            {"city": "Roseau", "country": "Dominica", "eventid": "1517835", "type": "EQ"},
            {"city": "Canefield", "country": "Dominica", "eventid": "1517835", "type": "EQ"}
        ]
        
        # Test alias analysis directly
        result1 = _alias_analysis("le lamentin", "martinique", disasters)
        assert result1['impacted'] == True, "Le Lamentin asset should match Martinique disaster"
        
        result2 = _alias_analysis("roseau", "dominica", disasters)
        assert result2['impacted'] == True, "Roseau asset should match Dominica disaster"
    
    def test_sudan_flood_coordinate_matching(self):
        """Test Sudan assets match flood events via coordinate proximity."""
        asset_coords = (15.5007, 32.5599)  # Khartoum
        
        # Mock impact data with flood coordinates near Khartoum
        impact_data = {
            "1026577": {
                "impact_json": {
                    "datums": [
                        {
                            "datum": [
                                {
                                    "scalars": {
                                        "scalar": [
                                            {"name": "lat", "value": "15.084"},
                                            {"name": "long", "value": "32.559"}
                                        ]
                                    }
                                }
                            ]
                        }
                    ]
                }
            }
        }
        
        # Test coordinate analysis
        result = _coordinate_analysis(asset_coords, impact_data)
        assert result['impacted'] == True, "Khartoum asset should match nearby flood coordinates"
        assert result['location']['city'] != 'Unknown', "Should return valid location"
    
    def test_asset_disaster_integration(self):
        """End-to-end test: assets should be detected as impacted."""
        # Load test assets
        cities = {"AST_TEST_1": "Le Lamentin"}
        countries = {"AST_TEST_1": "Martinique"}
        coordinates = {"AST_TEST_1": (14.6115, -61.0698)}
        assets_by_id = {"AST_TEST_1": {"unique_id": "AST_TEST_1", "type": "building"}}
        
        # Create mock disasters
        disasters = [
            {"city": "Le Lamentin", "country": "Martinique", "eventid": "1517835", "type": "EQ"}
        ]
        
        # Mock impact data
        impact_data = {
            "1517835": {
                "impact_json": {},
                "eventtype": "EQ"
            }
        }
        
        # Step 1: Verify individual components work
        asset_city = (cities.get("AST_TEST_1") or "").strip().casefold()
        asset_country = (countries.get("AST_TEST_1") or "").strip().casefold()
        
        alias_result = _alias_analysis(asset_city, asset_country, disasters)
        assert alias_result['impacted'] == True, "Alias analysis should work"
        
        # Step 2: Test with minimal intel() data
        minimal_matches, _ = intel([], cities, countries, {}, {}, {})
        assert len(minimal_matches) == 0, "Empty data should return no matches"
        
        # Step 3: Test step by step - single asset, single disaster
        single_asset_data = {"AST_TEST_1": {"unique_id": "AST_TEST_1", "type": "building"}}
        single_city_data = {"AST_TEST_1": "Le Lamentin"}
        single_country_data = {"AST_TEST_1": "Martinique"}
        single_coord_data = {"AST_TEST_1": (14.6115, -61.0698)}
        
        matches, outreach = intel(disasters, single_city_data, single_country_data, 
                                single_coord_data, single_asset_data, impact_data)
        
        print(f"[TEST] Final matches: {matches}")
        print(f"[TEST] Match count: {len(matches)}")
        
        # Assertions
        assert len(matches) >= 1, f"Expected at least 1 match, got {len(matches)}"
        
        if len(matches) > 0:
            match = matches[0]
            print(f"[TEST] Match details: {match}")
            assert match['unique_id'] == "AST_TEST_1"
            assert match['impact_method'] == "ALIAS"
    
    def test_intel_data_flow(self):
        """Test intel() function data flow step by step."""
        # Minimal test case
        cities = {"TEST": "Le Lamentin"}
        countries = {"TEST": "Martinique"}
        coordinates = {"TEST": (14.6115, -61.0698)}
        assets_by_id = {"TEST": {"unique_id": "TEST", "type": "building"}}
        
        disasters = [{"city": "Le Lamentin", "country": "Martinique", "eventid": "test", "type": "EQ"}]
        impact_data = {"test": {"impact_json": {}, "eventtype": "EQ"}}
        
        # Step 1: Verify alias analysis works independently
        asset_city = (cities.get("TEST") or "").strip().casefold()
        asset_country = (countries.get("TEST") or "").strip().casefold()
        print(f"[TEST] Asset city/country: {asset_city}, {asset_country}")
        
        alias_result = _alias_analysis(asset_city, asset_country, disasters)
        print(f"[TEST] Alias result: {alias_result}")
        assert alias_result['impacted'] == True, "Alias analysis should work independently"
        
        # Step 2: Test intel() with minimal data - check for crashes
        try:
            minimal_matches, _ = intel([], cities, countries, {}, {}, {})
            print(f"[TEST] Minimal intel() works: {len(minimal_matches)} matches")
        except Exception as e:
            pytest.fail(f"intel() crashed with minimal data: {e}")
        
        # Step 3: Test intel() with disasters but no impact data
        try:
            disaster_only_matches, _ = intel(disasters, cities, countries, coordinates, assets_by_id, {})
            print(f"[TEST] Disaster-only intel() works: {len(disaster_only_matches)} matches")
        except Exception as e:
            pytest.fail(f"intel() crashed with disasters only: {e}")
        
        # Step 4: Test intel() with full data - this is the real test
        try:
            matches, _ = intel(disasters, cities, countries, coordinates, assets_by_id, impact_data)
            print(f"[TEST] Full intel() result: {matches}")
            print(f"[TEST] Full intel() count: {len(matches)}")
            
            # The key assertion - should find the alias match
            if len(matches) == 0:
                print(f"[TEST] FAILURE ANALYSIS:")
                print(f"[TEST] - Cities dict: {cities}")
                print(f"[TEST] - Countries dict: {countries}")
                print(f"[TEST] - Coordinates dict: {coordinates}")
                print(f"[TEST] - Assets dict: {assets_by_id}")
                print(f"[TEST] - Disasters: {disasters}")
                print(f"[TEST] - Impact data: {impact_data}")
                
                # Test each component individually
                print(f"[TEST] Testing components individually:")
                
                # Test asset data extraction
                for asset_id in assets_by_id.keys():
                    test_city = (cities.get(asset_id) or "").strip().casefold()
                    test_country = (countries.get(asset_id) or "").strip().casefold()
                    test_coords = coordinates.get(asset_id)
                    print(f"[TEST] Asset {asset_id}: city='{test_city}', country='{test_country}', coords={test_coords}")
                    
                    # Test alias analysis for this asset
                    test_alias = _alias_analysis(test_city, test_country, disasters)
                    print(f"[TEST] Alias analysis for {asset_id}: {test_alias}")
                    
                    # Test polygon analysis for this asset
                    if test_coords and impact_data:
                        test_polygon = _polygon_analysis(test_coords, impact_data)
                        print(f"[TEST] Polygon analysis for {asset_id}: {test_polygon}")
                    
                    # Test coordinate analysis for this asset
                    if test_coords and impact_data:
                        test_coord = _coordinate_analysis(test_coords, impact_data)
                        print(f"[TEST] Coordinate analysis for {asset_id}: {test_coord}")
            
            assert len(matches) >= 1, f"Expected at least 1 match, got {len(matches)}"
            
            # Verify match details
            if len(matches) > 0:
                match = matches[0]
                print(f"[TEST] Match verification: {match}")
                assert match['unique_id'] == "TEST"
                assert match['impact_method'] == "ALIAS"
                assert match['disaster_city'] == "Le Lamentin"
                assert match['disaster_country'] == "Martinique"
                
        except Exception as e:
            pytest.fail(f"intel() crashed with full data: {e}")
        
    def test_coordinate_distance_thresholds(self):
        """Test that distance thresholds work correctly."""
        # Asset at exact same coordinates as disaster
        asset_coords = (15.084, -60.547)  # Same as earthquake
        
        impact_data = {
            "1517835": {
                "impact_json": {
                    "datums": [
                        {
                            "datum": [
                                {
                                    "scalars": {
                                        "scalar": [
                                            {"name": "lat", "value": "15.084"},
                                            {"name": "long", "value": "-60.547"}
                                        ]
                                    }
                                }
                            ]
                        }
                    ]
                }
            }
        }
        
        result = _coordinate_analysis(asset_coords, impact_data)
        assert result['impacted'] == True, "Asset at same coordinates should match"
        assert result['distance'] < 1, "Distance should be very small"
    
    def test_case_insensitive_matching(self):
        """Test that city/country matching is case insensitive."""
        disasters = [
            {"city": "LE LAMENTIN", "country": "MARTINIQUE", "eventid": "test", "type": "EQ"},
            {"city": "le lamentin", "country": "martinique", "eventid": "test2", "type": "EQ"},
            {"city": "Le Lamentin", "country": "Martinique", "eventid": "test3", "type": "EQ"}
        ]
        
        # ADD DEBUG:
        for d in disasters:
            d_city = (d.get("city") or "").strip().casefold()
            d_country = (d.get("country") or "").strip().casefold()
            print(f"[DEBUG] Disaster city/country: {d_city}, {d_country}")

        # Test various case combinations
        result1 = _alias_analysis("LE LAMENTIN", "MARTINIQUE", disasters)
        result2 = _alias_analysis("le lamentin", "martinique", disasters)
        result3 = _alias_analysis("Le Lamentin", "Martinique", disasters)

        print(f"[DEBUG] Results: {result1}, {result2}, {result3}")
        
        assert all([r['impacted'] for r in [result1, result2, result3]]), "All case combinations should match"
    
    def test_no_false_positives(self):
        """Test that assets far from disasters don't match."""
        # Asset in Japan, disasters in Caribbean
        asset_coords = (35.6762, 139.6503)  # Tokyo
        
        disasters = [
            {"city": "Le Lamentin", "country": "Martinique", "eventid": "test", "type": "EQ"}
        ]
        
        # Alias should not match (different country)
        result = _alias_analysis("tokyo", "japan", disasters)
        assert result['impacted'] == False, "Tokyo asset should not match Caribbean disaster"
        
        # Coordinate should not match (too far)
        impact_data = {"test": {"impact_json": {}}}  # Empty impact data
        result = _coordinate_analysis(asset_coords, impact_data)
        assert result['impacted'] == False, "Tokyo asset should not match Caribbean coordinates"