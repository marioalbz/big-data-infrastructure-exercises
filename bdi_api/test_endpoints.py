import pytest
from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

def test_aircraft_endpoint_success():
    response = client.get("/api/s8/aircraft")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
    assert len(response.json()) > 0
    assert response.json()[0]["icao"] == "a07ffd"
    assert response.json()[0]["registration"] == "N131MB"
    assert "registration" in response.json()[0]
    assert "type" in response.json()[0]

def test_co2_endpoint_success():
    response = client.get("/api/s8/aircraft/a835af/co2")
    assert response.status_code == 200
    assert response.json()["icao"] == "a835af"
    assert response.json()["hours_flown"] == 12.2
    assert response.json()["co2"] == 1.5

def test_co2_endpoint_invalid_icao():
    response = client.get("/api/s8/aircraft/invalid_icao/co2")
    assert response.status_code == 404
    assert "detail" in response.json()