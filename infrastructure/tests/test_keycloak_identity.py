"""The development IdP must emit the claims required by API JWT validation."""
import json
from pathlib import Path


def test_browser_client_emits_api_audience_without_a_dangling_client_reference():
    realm_path = Path(__file__).parents[1] / "docker/keycloak/enterpriseflow-realm.json"
    realm = json.loads(realm_path.read_text())
    clients = {client["clientId"]: client for client in realm["clients"]}
    browser = clients["enterpriseflow-web"]
    # Keycloak's basic scope supplies sub, which the API requires alongside aud.
    assert "basic" in browser["defaultClientScopes"]
    audiences = set()
    for mapper in browser["protocolMappers"]:
        if mapper["protocolMapper"] != "oidc-audience-mapper":
            continue
        config = mapper["config"]
        if config.get("access.token.claim") != "true":
            continue
        if config.get("included.client.audience") in clients:
            audiences.add(config["included.client.audience"])
        if config.get("included.custom.audience"):
            audiences.add(config["included.custom.audience"])
    assert "enterpriseflow-api" in audiences
    assert browser["attributes"]["pkce.code.challenge.method"] == "S256"
    assert browser["directAccessGrantsEnabled"] is False
