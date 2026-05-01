from __future__ import annotations

from fastapi.testclient import TestClient

from api import main as api_main


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(api_main, "_ensure_nightly_scheduler_running", lambda: None)
    return TestClient(api_main.app)


def test_health_contract(monkeypatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "cw2-api"}


def test_navigation_contract_contains_report_studio(monkeypatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/api/navigation")

    assert response.status_code == 200
    pages = response.json()
    assert isinstance(pages, list)
    assert {"id": "report_studio", "label": "Report Studio", "section": "delivery"} in pages


def test_version_contract_exposes_baseline_config(monkeypatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/api/version")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "cw2-api"
    assert payload["version"]
    assert payload["baseline_config"].endswith(".yaml")
    assert payload["generated_at"].endswith("Z")


def test_static_web_shell_is_served(monkeypatch) -> None:
    client = _client(monkeypatch)

    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Research Workbench" in response.text


def test_llm_model_list_rejects_non_http_url(monkeypatch) -> None:
    client = _client(monkeypatch)

    response = client.post(
        "/api/llm/models",
        json={
            "api_url": "file:///tmp/models.json",
            "api_key": "not-a-real-key",
            "request_format": "openai",
        },
    )

    assert response.status_code == 400
    assert "http or https" in response.json()["detail"]


def test_llm_url_helpers_fill_provider_endpoints() -> None:
    assert (
        api_main._request_url_for_format(
            "https://api.openai.com/v1",
            api_key="key",
            model="gpt-4.1-mini",
            request_format="openai_responses",
        )
        == "https://api.openai.com/v1/responses"
    )
    assert (
        api_main._model_list_url_for_format(
            "https://api.openai.com/v1/responses",
            api_key="key",
            request_format="openai_responses",
        )
        == "https://api.openai.com/v1/models"
    )
    gemini_url = api_main._request_url_for_format(
        "https://generativelanguage.googleapis.com/v1beta",
        api_key="gemini-key",
        model="gemini-1.5-pro",
        request_format="gemini_generate_content",
    )
    assert gemini_url == (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-1.5-pro:generateContent?key=gemini-key"
    )
