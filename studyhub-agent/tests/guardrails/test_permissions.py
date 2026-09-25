import pytest

from studyhub_agent.contracts.episode import Principal
from studyhub_agent.guardrails.permissions import can_read

USER = Principal(
    principal_id="u-1", purchased_material_ids=frozenset({7}), owned_material_ids=frozenset({9})
)


@pytest.mark.parametrize(
    ("material_id", "scope", "owner", "expected"),
    [
        (1, "public", None, True),
        (7, "paid", None, True),
        (8, "paid", None, False),
        (9, "owner", None, True),
        (10, "owner", "u-1", True),
        (11, "owner", "u-2", False),
        (12, "unknown", None, False),
    ],
)
def test_can_read(material_id, scope, owner, expected) -> None:
    assert can_read(USER, material_id=material_id, access_scope=scope, owner_id=owner) is expected


def test_admin_reads_everything() -> None:
    admin = Principal(principal_id="a", is_admin=True)
    assert can_read(admin, material_id=11, access_scope="owner", owner_id="u-2")
