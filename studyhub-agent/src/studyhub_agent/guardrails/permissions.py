from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, TypeVar


class ScopedResource(Protocol):
    material_id: int
    access_scope: str
    owner_id: str | None


ResourceT = TypeVar("ResourceT", bound=ScopedResource)


@dataclass(frozen=True, slots=True)
class PermissionContext:
    principal_id: str
    purchased_material_ids: frozenset[int] = field(default_factory=frozenset)
    owned_material_ids: frozenset[int] = field(default_factory=frozenset)
    is_admin: bool = False

    def can_read(self, resource: ScopedResource) -> bool:
        if self.is_admin:
            return True
        if resource.access_scope in {"public", "free"}:
            return True
        if resource.access_scope == "paid":
            return resource.material_id in self.purchased_material_ids
        if resource.access_scope == "owner":
            return resource.material_id in self.owned_material_ids or bool(
                resource.owner_id and resource.owner_id == self.principal_id
            )
        return False

    def filter_visible(self, resources: list[ResourceT]) -> list[ResourceT]:
        return [resource for resource in resources if self.can_read(resource)]
