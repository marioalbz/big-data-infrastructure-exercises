from fastapi.testclient import TestClient
from bdi_api.app import app
import pytest
from unittest import mock
from bdi_api.s7.exercise import get_aircraft_statistics, connect_to_database  # Import the function
from fastapi import HTTPException

@pytest.fixture(scope="function")
def client():
    with TestClient(app) as test_client:
        test_client.post("/api/s7/aircraft/prepare")
        yield test_client

def test_s7_prepare(client: TestClient) -> None:
    response = client.post("/api/s7/aircraft/prepare")
    assert response.status_code == 200, f"Prepare endpoint failed: {response.text}"
    assert response.json().get("status") == "success"
    assert "Aircraft data saved successfully" in response.json().get("message")

def test_s7_list_aircraft(client: TestClient) -> None:
    response = client.get("/api/s7/aircraft/")
    assert response.status_code == 200, f"List aircraft endpoint failed: {response.text}"
    aircraft_list = response.json()
    assert isinstance(aircraft_list, list), "Response should be a list of aircraft"
    if aircraft_list:
        sample_aircraft = aircraft_list[0]
        assert "icao" in sample_aircraft
        assert "registration" in sample_aircraft
        assert "type" in sample_aircraft

def test_s7_get_aircraft_positions(client: TestClient) -> None:
    test_icao = "a65800"  # Replace with a known ICAO if needed
    response = client.get(f"/api/s7/aircraft/{test_icao}/positions")
    assert response.status_code == 200, f"Get positions endpoint failed: {response.text}"
    positions = response.json()
    assert isinstance(positions, list), "Response should be a list of positions"
    if positions:
        sample_position = positions[0]
        assert "timestamp" in sample_position
        assert "lat" in sample_position
        assert "lon" in sample_position

def test_s7_get_aircraft_stats(client: TestClient) -> None:
    test_icao = "a65800"  # Replace with a known ICAO if needed
    response = client.get(f"/api/s7/aircraft/{test_icao}/stats")
    assert response.status_code == 200, f"Get stats endpoint failed: {response.text}"
    stats = response.json()
    assert "max_altitude_baro" in stats
    assert "max_ground_speed" in stats
    assert "had_emergency" in stats
    assert stats["max_altitude_baro"] is not None, "Max altitude should not be None if data exists"

def test_s7_get_aircraft_stats_not_found(client: TestClient) -> None:
    non_existent_icao = "NONEXIST"
    response = client.get(f"/api/s7/aircraft/{non_existent_icao}/stats")
    print(f"Response status code: {response.status_code}")
    print(f"Response text: {response.text}")
    assert response.status_code == 404, f"Expected 404 for non-existent ICAO, got: {response.status_code}"
    assert "No data found" in response.json().get("detail", "")

def test_s7_get_aircraft_stats_not_found_isolated():
    non_existent_icao = "NONEXIST"

    # Mock the connect_to_database function and its return values
    with mock.patch("bdi_api.s7.exercise.connect_to_database") as mock_connect:
        mock_conn = mock.Mock()
        mock_cur = mock.Mock()

        # Make the mock cursor support the context manager protocol
        mock_cur.__enter__ = mock.Mock(return_value=mock_cur)
        mock_cur.__exit__ = mock.Mock(return_value=False)

        mock_conn.cursor.return_value = mock_cur
        mock_connect.return_value = mock_conn

        # Simulate no data found for the ICAO
        mock_cur.fetchone.return_value = None

        # Make the mock connection support the context manager protocol
        mock_conn.__enter__ = mock.Mock(return_value=mock_conn)
        mock_conn.__exit__ = mock.Mock(return_value=False)

        # Call the function directly (we need to handle the HTTPException)
        with pytest.raises(HTTPException) as excinfo:
            get_aircraft_statistics(icao=non_existent_icao)

        assert excinfo.value.status_code == 404
        assert "No data found" in excinfo.value.detail