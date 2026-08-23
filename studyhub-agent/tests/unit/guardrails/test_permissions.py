import asyncio

from studyhub_agent.guardrails.permissions import PermissionContext


def test_acl_filters_before_chunks_reach_the_caller(knowledge, permissions) -> None:
    results = asyncio.run(knowledge.search("通信原理 付费题库", limit=10, permissions=permissions))

    assert results
    assert all(result.material_id != 130 for result in results)
    assert all(result.material_id != 202 for result in results)
    assert "未公开模拟题" not in " ".join(result.text for result in results)


def test_paid_owner_and_admin_entitlements_are_explicit(knowledge, identity) -> None:
    paid = PermissionContext(principal_id=identity.principal_id, purchased_material_ids=frozenset({130}))
    owner = PermissionContext(
        principal_id="studyhub:user:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        owned_material_ids=frozenset({202}),
    )
    admin = PermissionContext(principal_id=identity.principal_id, is_admin=True)

    assert asyncio.run(knowledge.read("material:130:p8:c2", permissions=paid)) is not None
    assert asyncio.run(knowledge.read("material:202:p6:c0", permissions=owner)) is not None
    assert asyncio.run(knowledge.read("material:202:p6:c0", permissions=admin)) is not None
    assert asyncio.run(knowledge.read("material:130:p8:c2", permissions=admin)) is not None
