from fastapi.testclient import TestClient

from app.composition.hosted_api import build_hosted_api


def test_hosted_api_liveness_and_readiness_are_distinct() -> None:
    healthy = TestClient(build_hosted_api(object(), lambda: None))
    assert healthy.get("/healthz").json()["status"] == "ok"
    assert healthy.get("/readyz").json()["status"] == "ready"

    def unavailable() -> None:
        raise RuntimeError("database unavailable")

    not_ready = TestClient(
        build_hosted_api(object(), lambda: None, readiness_check=unavailable)
    )
    response = not_ready.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"detail": "Service unavailable"}
