from __future__ import annotations

from studyhub_agent.contracts.episode import Principal


def can_read(principal: Principal, *, material_id: int, access_scope: str, owner_id: str | None) -> bool:
    if principal.is_admin:
        return True
    if access_scope in {"public", "free"}:
        return True
    if access_scope == "paid":
        return material_id in principal.purchased_material_ids
    if access_scope == "owner":
        return material_id in principal.owned_material_ids or bool(owner_id and owner_id == principal.principal_id)
    return False
