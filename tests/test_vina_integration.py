import pytest
from starlette.testclient import TestClient
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health_check(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json().get("ok") is True


def test_root_redirect(client):
    res = client.get("/", follow_redirects=False)
    assert res.status_code in (301, 302, 307)
    assert "/mobi/scanner.html" in res.headers.get("location", "")


def test_mobi_scanner_html_served(client):
    res = client.get("/mobi/scanner.html")
    assert res.status_code == 200
    assert "Свое вино" in res.text or "<!DOCTYPE html>" in res.text


def test_catalog_endpoint(client):
    res = client.get("/api/catalog?limit=5")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert len(data["items"]) > 0


def test_wine_full_sommelier_endpoint(client):
    slug = "loco-cimbali-blanc-de-neige-shardone-beloe-suhoe-131"
    res = client.get(f"/api/v2/wine/{slug}/full-sommelier")
    assert res.status_code == 200
    data = res.json()
    assert "wine" in data
    assert "organoleptic" in data
    assert data["organoleptic"]["acidity"] > 0


def test_wine_set_endpoint(client):
    slug = "loco-cimbali-blanc-de-neige-shardone-beloe-suhoe-131"
    res = client.get(f"/api/v2/wine-set?wine_slug={slug}&count=4")
    assert res.status_code == 200
    data = res.json()
    assert len(data.get("items", [])) == 4


def test_nearby_stores_endpoint(client):
    slug = "loco-cimbali-blanc-de-neige-shardone-beloe-suhoe-131"
    res = client.get(f"/api/map/nearby-stores?slug={slug}&lat=44.6&lon=33.5")
    assert res.status_code == 200
    data = res.json()
    assert len(data.get("stores", [])) == 5


def test_sommelier_ask_toast_endpoint(client):
    slug = "loco-cimbali-blanc-de-neige-shardone-beloe-suhoe-131"
    res = client.post(
        "/api/v2/sommelier/ask",
        json={"wine_slug": slug, "occasion": "friends", "question": "Тост"}
    )
    assert res.status_code == 200
    data = res.json()
    assert "toast" in data
    assert len(data["toast"]["toast_text"]) > 10


def test_missing_wine_reporting_and_dashboard(client):
    rep_res = client.post(
        "/api/missing-wines/report",
        json={"source": "test_suite", "query_text": "Вино Инкерман"}
    )
    assert rep_res.status_code == 200
    data = rep_res.json()
    assert data["success"] is True
    assert "req_" in data["id"]

    dash_res = client.get("/api/admin/dashboard/missing-wines")
    assert dash_res.status_code == 200
