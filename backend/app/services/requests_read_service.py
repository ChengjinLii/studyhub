from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.repos.read_api_repo import ReadApiRepository
from app.services.read_support import clamp_limit, has_role, parse_iso_datetime


class RequestsReadService:
    def __init__(self, repo: ReadApiRepository) -> None:
        self.repo = repo

    def list_requests(self, viewer_id: int | None, *, sort: str | None, limit: int | None) -> list[dict[str, Any]]:
        seed = self.repo.load_seed()
        items = [self._to_request_item(item, viewer_id, None) for item in seed.get("requests", []) if item.get("status") != "REMOVED"]
        normalized = (sort or "latest").lower()
        if normalized == "hot":
            items.sort(key=lambda item: (-(item.get("fundedAmount") or 0), -(item.get("responseCount") or 0), -parse_iso_datetime(item.get("createdAt")).timestamp()))
        else:
            items.sort(key=lambda item: -parse_iso_datetime(item.get("createdAt")).timestamp())
        safe_limit = clamp_limit(limit, max_value=100)
        return items[:safe_limit] if safe_limit else items

    def list_leaderboard(self, viewer_id: int | None, *, limit: int | None) -> list[dict[str, Any]]:
        items = self.list_requests(viewer_id, sort="hot", limit=limit)
        return items

    def get_detail(self, viewer_id: int, viewer_role_mask: int | None, request_id: int) -> dict[str, Any]:
        source = self._find_request(request_id)
        return self._to_request_item(source, viewer_id, viewer_role_mask)

    def get_responses(self, viewer_id: int, viewer_role_mask: int | None, request_id: int) -> list[dict[str, Any]]:
        self._find_request(request_id)
        seed = self.repo.load_seed()
        items = list((seed.get("requestResponses") or {}).get(str(request_id), []))
        items.sort(key=lambda item: -parse_iso_datetime(item.get("updatedAt") or item.get("createdAt")).timestamp())
        return items

    def get_contributions(self, viewer_id: int, viewer_role_mask: int | None, request_id: int) -> list[dict[str, Any]]:
        self._find_request(request_id)
        seed = self.repo.load_seed()
        items = list((seed.get("requestContributions") or {}).get(str(request_id), []))
        items.sort(key=lambda item: -parse_iso_datetime(item.get("createdAt")).timestamp())
        return items

    def _find_request(self, request_id: int) -> dict[str, Any]:
        seed = self.repo.load_seed()
        item = next((entry for entry in seed.get("requests", []) if int(entry["id"]) == request_id), None)
        if item is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="求购不存在")
        return item

    def _to_request_item(self, item: dict[str, Any], viewer_id: int | None, viewer_role_mask: int | None) -> dict[str, Any]:
        is_owner = viewer_id is not None and int(item.get("requesterId", 0)) == viewer_id
        can_manage_all = has_role(viewer_role_mask, 8) or has_role(viewer_role_mask, 16)
        anonymous = bool(item.get("anonymous"))
        requester_name = item.get("requesterName")
        if anonymous and not is_owner and not can_manage_all:
            requester_name = None
        responded_user_ids = {int(value) for value in item.get("respondedUserIds", [])}
        return {
            "id": item["id"],
            "course": item.get("course"),
            "keyword": item.get("keyword"),
            "school": item.get("school"),
            "college": item.get("college"),
            "major": item.get("major"),
            "budget": item.get("budget"),
            "fundedAmount": item.get("fundedAmount"),
            "contributionCount": item.get("contributionCount"),
            "deadline": item.get("deadline"),
            "urgencyTier": item.get("urgencyTier"),
            "creatorFloor": item.get("creatorFloor"),
            "previewRequirement": item.get("previewRequirement"),
            "anonymous": anonymous,
            "requesterName": requester_name,
            "responseCount": item.get("responseCount", 0),
            "responded": viewer_id in responded_user_ids if viewer_id is not None else False,
            "owner": is_owner,
            "acceptedResponseId": item.get("acceptedResponseId"),
            "status": item.get("status"),
            "createdAt": item.get("createdAt"),
        }
