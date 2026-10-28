from app import storage
from app.evaluations import REPORT_KEY, run_scheduled_evaluation


def test_scheduled_evaluation_is_offline_and_report_is_admin_only(client, monkeypatch):
    monkeypatch.setenv("RERANK_MODEL", "never-download-a-model-in-offline-evaluation")
    from app.core.config import get_settings
    get_settings.cache_clear()
    assert client.get("/api/v1/evaluations/latest", headers={"x-test-user": "admin"}).status_code == 404
    result = run_scheduled_evaluation.run()
    assert result["status"] == "completed"
    assert storage.get(REPORT_KEY)
    response = client.get("/api/v1/evaluations/latest", headers={"x-test-user": "admin"})
    assert response.status_code == 200
    report = response.json()
    assert report["legal_evidence_cases"] == 10
    assert report["legal_fabricated_quote_rejection_rate"] == 1
    assert report["live_model_extraction_accuracy"] is None
    assert report["cross_department_access_violations"] == 0
    assert client.get("/api/v1/evaluations/latest", headers={"x-test-user": "fin"}).status_code == 403
