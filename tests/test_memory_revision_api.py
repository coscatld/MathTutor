"""Public memory CAS receipts, owner isolation and independent retrieval control."""
from mathtutor.api.product_state import get_product_state
from test_tutor_p0 import client_at

MEMORY = "/api/v2/math-tutor/desktop/memory"


def create(client):
    response = client.post(MEMORY, json={"memory_type":"user_note", "subject":"我", "predicate":"内容", "object_json":{"value":"original synthetic note"}})
    assert response.status_code == 200, response.text
    return response.json()


def test_edit_conflict_returns_latest_public_projection_without_overwriting(tmp_path):
    with client_at(tmp_path / "edit.db") as client:
        original = create(client)
        route = f"{MEMORY}/{original['memory_id']}"
        first = client.put(route, json={"expected_updated_at":original["updated_at"],"object_json":{"value":"first edit"}})
        assert first.status_code == 200, first.text
        latest = first.json()
        assert latest["updated_at"] != original["updated_at"]
        second = client.put(route, json={"expected_updated_at":original["updated_at"],"object_json":{"value":"stale edit"}})
        assert second.status_code == 409
        assert second.json()["code"] == "memory_conflict"
        assert second.json()["latest"] == latest
        assert "student_id" not in second.json()["latest"]
        assert client.get(MEMORY).json() == [latest]


def test_retrieval_toggle_and_edit_use_their_own_fields_and_versions(tmp_path):
    with client_at(tmp_path / "toggle.db") as client:
        original = create(client)
        route = f"{MEMORY}/{original['memory_id']}"
        disabled = client.patch(route + "/retrieval", json={"enabled":False,"expected_updated_at":original["updated_at"]}).json()
        assert disabled["retrieval_enabled"] is False
        refused = client.put(route, json={"expected_updated_at":original["updated_at"],"object_json":{"value":"draft"}})
        assert refused.status_code == 409 and refused.json()["latest"] == disabled
        updated = client.put(route, json={"expected_updated_at":disabled["updated_at"],"object_json":{"value":"reviewed draft"},"retrieval_enabled":True,"source_type":"USER_CONFIRMED"})
        assert updated.status_code == 200, updated.text
        assert updated.json()["retrieval_enabled"] is False
        assert updated.json()["source_type"] == "USER_EXPLICIT"
        old_toggle = client.patch(route + "/retrieval", json={"enabled":True,"expected_updated_at":disabled["updated_at"]})
        assert old_toggle.status_code == 409
        assert old_toggle.json()["latest"]["retrieval_enabled"] is False


def test_confirmation_cannot_approve_new_content_and_does_not_enable_retrieval(tmp_path):
    with client_at(tmp_path / "confirm.db") as client:
        async def seed():
            return await get_product_state().personal_memory.add_inference("local-admin", subject="表达",predicate="偏好",object_json={"value":"synthetic inference"})
        node = client.portal.call(seed)
        original = client.get(MEMORY).json()[0]
        route = f"{MEMORY}/{node.memory_id}"
        edited = client.put(route,json={"expected_updated_at":original["updated_at"],"object_json":{"value":"changed inference"}}).json()
        refused = client.post(route+"/confirm",json={"expected_updated_at":original["updated_at"]})
        assert refused.status_code == 409 and refused.json()["latest"] == edited
        disabled = client.patch(route+"/retrieval",json={"expected_updated_at":edited["updated_at"],"enabled":False}).json()
        confirmed = client.post(route+"/confirm",json={"expected_updated_at":disabled["updated_at"]})
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["source_type"] == "USER_CONFIRMED" and confirmed.json()["retrieval_enabled"] is False
        assert confirmed.json()["object_json"] == edited["object_json"]
        assert client.post(route+"/confirm",json={"expected_updated_at":original["updated_at"]}).json() == confirmed.json()


def test_deleted_or_other_owner_memory_has_no_conflict_payload(tmp_path):
    with client_at(tmp_path / "isolation.db") as client:
        original = create(client)
        route = f"{MEMORY}/{original['memory_id']}"
        assert client.delete(route).status_code == 200
        for method,suffix,body in [("PUT","",{"object_json":{"value":"deleted"}}),("POST","/confirm",{}),("PATCH","/retrieval",{"enabled":True})]:
            response = client.request(method,route+suffix,json={**body,"expected_updated_at":original["updated_at"]})
            assert response.status_code == 404 and "latest" not in response.json()
        async def other():
            return await get_product_state().personal_memory.add_inference("other-owner",subject="other",predicate="private",object_json={"value":"other-owner-content"})
        node = client.portal.call(other)
        for method,suffix,body in [("PUT","",{"object_json":{"value":"forged"}}),("POST","/confirm",{}),("PATCH","/retrieval",{"enabled":False})]:
            response=client.request(method,f"{MEMORY}/{node.memory_id}"+suffix,json={**body,"expected_updated_at":original["updated_at"]})
            assert response.status_code == 404 and "other-owner-content" not in response.text and "latest" not in response.json()


def test_legacy_edit_without_version_still_cannot_change_disabled_permission(tmp_path):
    with client_at(tmp_path / "legacy.db") as client:
        original=create(client)
        route=f"{MEMORY}/{original['memory_id']}"
        assert client.patch(route+"/retrieval",json={"enabled":False}).json()["retrieval_enabled"] is False
        result=client.put(route,json={"object_json":{"value":"legacy edit"},"retrieval_enabled":True})
        assert result.status_code==200 and result.json()["retrieval_enabled"] is False
        assert client.put(route,json={"expected_updated_at":"not-a-date"}).status_code==422
