import pytest
from unittest.mock import patch, Mock
from disaster_factor.core import _reverse_geocode, _coordinate_analysis

class TestReverseGeocodeV4Beta:
    """Test reverse geocoding with Google V4 Beta API response structure."""
    
    def test_reverse_geocode_v4_beta_success(self):
        """Test successful reverse geocode with V4 Beta response structure."""
        # Mock V4 Beta API response structure
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "formattedAddress": "Sendai, Miyagi, Japan",
                    "addressComponents": [
                        {
                            "longText": "Sendai",
                            "shortText": "Sendai",
                            "types": ["locality", "political"]
                        },
                        {
                            "longText": "Miyagi",
                            "shortText": "Miyagi",
                            "types": ["administrative_area_level_1", "political"]
                        },
                        {
                            "longText": "Japan",
                            "shortText": "JP",
                            "types": ["country", "political"]
                        }
                    ]
                }
            ]
        }
        
        with patch('requests.get', return_value=mock_response):
            with patch('disaster_factor.core._get_geocoding_api_key', return_value='test_key'):
                result = _reverse_geocode(38.2682, 140.8694)
        
        print(f"[TEST] Result: {result}")
        assert result['city'] == 'Sendai', f"Expected 'Sendai', got '{result['city']}'"
        assert result['country'] == 'Japan', f"Expected 'Japan', got '{result['country']}'"
    
    def test_reverse_geocode_no_results(self):
        """Test reverse geocode when API returns no results."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        
        with patch('requests.get', return_value=mock_response):
            with patch('disaster_factor.core._get_geocoding_api_key', return_value='test_key'):
                result = _reverse_geocode(0.0, 0.0)
        
        assert result['city'] == 'Unknown'
        assert result['country'] == 'Unknown'
    
    def test_reverse_geocode_missing_locality(self):
        """Test reverse geocode when locality is missing but country exists."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "formattedAddress": "Rural Area, Japan",
                    "addressComponents": [
                        {
                            "longText": "Japan",
                            "shortText": "JP",
                            "types": ["country", "political"]
                        }
                    ]
                }
            ]
        }
        
        with patch('requests.get', return_value=mock_response):
            with patch('disaster_factor.core._get_geocoding_api_key', return_value='test_key'):
                result = _reverse_geocode(35.0, 135.0)
        
        # Should extract from formattedAddress
        assert result['city'] == 'Rural Area' or result['city'] == 'Unknown'
        assert result['country'] == 'Japan'
    
    def test_reverse_geocode_api_error(self):
        """Test reverse geocode handles API errors gracefully."""
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = Exception("API Error")
        
        with patch('requests.get', return_value=mock_response):
            with patch('disaster_factor.core._get_geocoding_api_key', return_value='test_key'):
                result = _reverse_geocode(38.2682, 140.8694)
        
        assert result['city'] == 'Unknown'
        assert result['country'] == 'Unknown'
    
    def test_coordinate_analysis_with_reverse_geocode(self):
        """Test coordinate analysis includes reverse geocoded location."""
        # Mock impact data with coordinates near Sendai
        impact_data = {
            "1517494": {
                "impact_json": {
                    "datums": [
                        {
                            "datum": [
                                {
                                    "scalars": {
                                        "scalar": [
                                            {"name": "lat", "value": "38.2682"},
                                            {"name": "long", "value": "140.8694"}
                                        ]
                                    }
                                }
                            ]
                        }
                    ]
                }
            }
        }
        
        # Mock reverse geocode response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "formattedAddress": "Sendai, Miyagi, Japan",
                    "addressComponents": [
                        {
                            "longText": "Sendai",
                            "shortText": "Sendai",
                            "types": ["locality", "political"]
                        },
                        {
                            "longText": "Japan",
                            "shortText": "JP",
                            "types": ["country", "political"]
                        }
                    ]
                }
            ]
        }
        
        asset_coords = (38.2682, 140.8694)  # Same location
        
        with patch('requests.get', return_value=mock_response):
            with patch('disaster_factor.core._get_geocoding_api_key', return_value='test_key'):
                result = _coordinate_analysis(asset_coords, impact_data)
        
        print(f"[TEST] Coordinate analysis result: {result}")
        
        assert result['impacted'] == True, "Asset should be impacted (distance = 0)"
        assert 'location' in result, "Result should include location"
        assert result['location']['city'] == 'Sendai', f"Expected 'Sendai', got '{result['location']['city']}'"
        assert result['location']['country'] == 'Japan', f"Expected 'Japan', got '{result['location']['country']}'"
    
    def test_live_reverse_geocode_api_call(self):
        """Live test with actual V4 Beta API (requires API key)."""
        # Skip if no API key available
        import os
        if not os.getenv("GOOGLE_GEOCODING_API_KEY"):
            pytest.skip("No API key available for live test")
        
        # Test with known coordinates (Tokyo)
        result = _reverse_geocode(35.6762, 139.6503)
        
        print(f"[LIVE TEST] Tokyo result: {result}")
        
        # Should get some location data (not Unknown)
        assert result['city'] != 'Unknown' or result['country'] != 'Unknown', \
            "Live API should return some location data"
    
    def test_v4_beta_url_format(self):
        """Verify V4 Beta API URL is correctly formatted."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"results": []}
        
        with patch('requests.get', return_value=mock_response) as mock_get:
            with patch('disaster_factor.core._get_geocoding_api_key', return_value='test_key'):
                _reverse_geocode(38.2682, 140.8694)
        
        # Verify URL format
        call_args = mock_get.call_args
        url = call_args[0][0]
        params = call_args[1]['params']
        
        print(f"[TEST] URL: {url}")
        print(f"[TEST] Params: {params}")
        
        assert "v4beta" in url, "Should use V4 Beta endpoint"
        assert "38.2682,140.8694" in url, "Should include coordinates in URL"
        assert params['key'] == 'test_key', "Should include API key in params"
        assert 'types' not in params, "Should not have duplicate 'types' key"

    def test_debug_live_api_response(self):
        """Debug test to see actual V4 Beta API response structure."""
        import os
        import requests
        
        # Skip if no API key available
        if not os.getenv("GOOGLE_GEOCODING_API_KEY"):
            pytest.skip("GOOGLE_GEOCODING_API_KEY not set - skipping live API test")
        
        # Test coordinates (Sendai, Japan - from your affected.csv)
        lat, lon = 38.2682, 140.8694
        
        # Patch requests.get to intercept and log the actual API call
        original_get = requests.get
        
        def debug_get(*args, **kwargs):
            print(f"\n[DEBUG] Calling: {args[0]}")
            print(f"[DEBUG] Params: {kwargs.get('params', {})}")
            
            response = original_get(*args, **kwargs)
            print(f"[DEBUG] Status: {response.status_code}")
            
            data = response.json()
            
            # Print the ENTIRE response structure
            import json
            print(f"\n[DEBUG] FULL API RESPONSE:")
            print(json.dumps(data, indent=2))
            
            # Check what we're actually getting
            if data.get('results'):
                result = data['results'][0]
                print(f"\n[DEBUG] First result keys: {result.keys()}")
                
                if 'address_components' in result:
                    print(f"[DEBUG] address_components (snake_case) found!")
                    for comp in result['address_components']:
                        print(f"  - {comp}")
                elif 'addressComponents' in result:
                    print(f"[DEBUG] addressComponents (camelCase) found!")
                    for comp in result['addressComponents']:
                        print(f"  - {comp}")
                else:
                    print(f"[DEBUG] NO address components found in result!")
            else:
                print(f"[DEBUG] No results in response!")
            
            return response
        
        with patch('requests.get', side_effect=debug_get):
            result = _reverse_geocode(lat, lon)
        
        print(f"\n[DEBUG] Final parsed result: {result}")
