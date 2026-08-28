"""Personal Memory KG tests (§37 MEMORY group).

The Student Model authority boundary is structural here: the personal KG
can never store authoritative facts (write-time rejection), MODEL_INFERRED
memories are always distinguishable/confirmable/deletable, and retrieval
permission is enforced at the DATA layer (disabled memories never come
back from list_retrievable, whatever the policy wants).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from mathtutor.application.personal_memory_service import PersonalMemoryService
from mathtutor.domain.memory import (
    FORBIDDEN_MEMORY_TYPES,
    assert_memory_writable,
    confirm_inference,
)
from mathtutor.repositories.memory_repository import (
    InMemoryMemoryRepository,
    MemoryRepository,
)

pytestmark = pytest.mark.asyncio

_STUDENT_A = "student-a"
_STUDENT_B = "student-b"


@pytest.fixture()
def repo() -> InMemoryMemoryRepository:
    return InMemoryMemoryRepository()


def service(repository: MemoryRepository) -> PersonalMemoryService:
    return PersonalMemoryService(repository)


async def test_explicit_memory_roundtrip(repo):
    svc = service(repo)
    node = await svc.add_explicit(
        _STUDENT_A,
        memory_type="learning_preference",
        subject="数学",
        predicate="偏好节奏",
        object_json={"pace": "慢一点"},
    )
    assert node.source_type == "USER_EXPLICIT"
    assert node.retrieval_enabled is True
    listed = await svc.list(_STUDENT_A)
    assert [n.memory_id for n in listed] == [node.memory_id]


async def test_inference_confirmable_and_idempotent(repo):
    svc = service(repo)
    inferred = await svc.add_inference(
        _STUDENT_A, subject="几何", predicate="推测", object_json={"guess": "喜欢图形"}
    )
    assert inferred.source_type == "MODEL_INFERRED"  # distinguishable
    assert inferred.memory_type == "ai_inference"

    confirmed = await svc.confirm(_STUDENT_A, inferred.memory_id)
    assert confirmed.source_type == "USER_CONFIRMED"
    again = await svc.confirm(_STUDENT_A, inferred.memory_id)  # idempotent
    assert again.source_type == "USER_CONFIRMED"


async def test_confirm_user_explicit_raises(repo):
    svc = service(repo)
    node = await svc.add_explicit(
        _STUDENT_A,
        memory_type="user_note",
        subject="备注",
        predicate="记",
        object_json={"note": "x"},
    )
    with pytest.raises(ValueError):
        await svc.confirm(_STUDENT_A, node.memory_id)


async def test_forbidden_memory_types_rejected_at_domain():
    for forbidden in sorted(FORBIDDEN_MEMORY_TYPES):
        with pytest.raises(ValueError):
            assert_memory_writable(forbidden, "USER_EXPLICIT")
    with pytest.raises(ValueError):
        assert_memory_writable("user_note", "NOT_A_SOURCE")


async def test_service_rejects_forbidden_type(repo):
    svc = service(repo)
    with pytest.raises(ValueError):
        await svc.add_explicit(
            _STUDENT_A,
            memory_type="mastery",
            subject="数学",
            predicate="掌握",
            object_json={"skill": "x", "value": 0.9},
        )
    # Nothing was stored.
    assert await svc.list(_STUDENT_A) == []


async def test_retrieval_permission_enforced_at_data_layer(repo):
    svc = service(repo)
    visible = await svc.add_explicit(
        _STUDENT_A,
        memory_type="learning_goal",
        subject="目标",
        predicate="想",
        object_json={"goal": "提高"},
    )
    hidden = await svc.add_explicit(
        _STUDENT_A,
        memory_type="user_note",
        subject="秘密",
        predicate="记",
        object_json={"note": "不要给 AI"},
    )
    await svc.set_retrieval_enabled(_STUDENT_A, hidden.memory_id, False)

    retrievable = await svc.list_retrievable(_STUDENT_A)
    assert [n.memory_id for n in retrievable] == [visible.memory_id]
    # Full list (user view) still shows both.
    assert len(await svc.list(_STUDENT_A)) == 2


async def test_delete_is_soft_and_removes_from_retrieval(repo):
    svc = service(repo)
    node = await svc.add_explicit(
        _STUDENT_A,
        memory_type="interest",
        subject="兴趣",
        predicate="喜欢",
        object_json={"topic": "方程"},
    )
    assert await svc.delete(_STUDENT_A, node.memory_id) is True
    assert await svc.delete(_STUDENT_A, node.memory_id) is False  # already deleted
    assert await svc.list(_STUDENT_A) == []
    assert await svc.list_retrievable(_STUDENT_A) == []


async def test_owner_isolation(repo):
    svc = service(repo)
    node_a = await svc.add_explicit(
        _STUDENT_A,
        memory_type="user_note",
        subject="A",
        predicate="有",
        object_json={"note": "A 的记忆"},
    )
    assert await svc.list(_STUDENT_B) == []
    assert await svc.list_retrievable(_STUDENT_B) == []
    with pytest.raises(ValueError):
        await svc.confirm(_STUDENT_B, node_a.memory_id)  # not found for B
    assert await svc.delete(_STUDENT_B, node_a.memory_id) is False


async def test_edges_owner_scoped(repo):
    svc = service(repo)
    a = await svc.add_explicit(
        _STUDENT_A, memory_type="interest", subject="几何", predicate="喜欢", object_json={}
    )
    b = await svc.add_explicit(
        _STUDENT_A, memory_type="learning_goal", subject="方程", predicate="想", object_json={}
    )
    edge = await svc.relate(
        _STUDENT_A, source_node_id=a.memory_id, relation="related_to", target_node_id=b.memory_id
    )
    assert edge.relation == "related_to"
    assert len(await svc.list_edges(_STUDENT_A)) == 1
    assert await svc.list_edges(_STUDENT_B) == []


async def test_confirm_inference_domain_guard():
    from mathtutor.domain.memory import PersonalMemoryNode

    node = PersonalMemoryNode(
        student_id=pytest.importorskip("uuid").UUID(int=1),
        memory_type="ai_inference",
        subject="s",
        predicate="p",
        object_json={},
        source_type="USER_EXPLICIT",
    )
    with pytest.raises(ValueError):
        confirm_inference(node)  # USER_EXPLICIT needs no confirmation


# ------------------------------------------------------------ SQLite roundtrip


@pytest_asyncio.fixture()
async def db(tmp_path: Path):
    from mathtutor.infrastructure import create_db_engine
    from mathtutor.infrastructure.schema import metadata

    engine = create_db_engine(tmp_path / "math_tutor.db")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


async def test_sqlite_memory_roundtrip(db):
    from mathtutor.repositories.sqlite_knowledge import SQLiteMemoryRepository

    sqlite_repo = SQLiteMemoryRepository(db)
    svc = service(sqlite_repo)
    node = await svc.add_explicit(
        _STUDENT_A,
        memory_type="expression_preference",
        subject="称呼",
        predicate="用",
        object_json={"name": "同学"},
    )
    reloaded = await sqlite_repo.get_node(_STUDENT_A, node.memory_id)
    assert reloaded is not None
    assert reloaded.object_json == {"name": "同学"}
    assert reloaded.source_type == "USER_EXPLICIT"

    await svc.set_retrieval_enabled(_STUDENT_A, node.memory_id, False)
    assert await sqlite_repo.list_retrievable(_STUDENT_A) == []
    assert len(await sqlite_repo.list_nodes(_STUDENT_A)) == 1

    assert await svc.delete(_STUDENT_A, node.memory_id) is True
    assert await sqlite_repo.get_node(_STUDENT_A, node.memory_id) is None
    assert (
        await sqlite_repo.get_node(_STUDENT_A, node.memory_id, include_deleted=True)
    ).deleted_at is not None
