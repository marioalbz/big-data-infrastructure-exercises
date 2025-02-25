from fastapi.testclient import TestClient
from bdi_api.app import app

def test_s4_download(client: TestClient) -> None:
    with client as client:
        response = client.post("/api/s4/aircraft/download?file_limit=1")
        assert not response.is_error, "Error at the S4 download endpoint"

def test_s4_prepare(client: TestClient) -> None:
    with client as client:
        response = client.post("/api/s4/aircraft/prepare")
        assert not response.is_error, "Error at the S4 prepare endpoint"

if __name__ == "__main__":
    client = TestClient(app)
    test_s4_download(client)
    test_s4_prepare(client)
    print("All tests passed.")
    