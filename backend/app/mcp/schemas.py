from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class McpPublicBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class McpPublicMaterial(McpPublicBase):
    id: int | str | None = None
    title: str | None = None
    description: str | None = None
    school: str | None = None
    college: str | None = None
    major: str | None = None
    tags: list[str] = Field(default_factory=list)
    free: bool = False
    downloadCount: int = 0
    ratingAvg: float | int = 0
    ratingCount: int = 0
    previewManifest: Any | None = None
    previewWatermarkEnabled: bool | None = None
    previewSource: str | None = None


class McpPublicRequest(McpPublicBase):
    id: int | str | None = None
    course: str | None = None
    keyword: str | None = None
    school: str | None = None
    college: str | None = None
    major: str | None = None
    budget: int | float | None = None
    fundedAmount: int | float | None = None
    responseCount: int = 0
    status: str | None = None
    createdAt: str | None = None


class McpPublicMarket(McpPublicBase):
    id: int | str | None = None
    title: str | None = None
    description: str | None = None
    school: str | None = None
    category: str | None = None
    price: int | float | None = None
    wantCount: int = 0
    status: str | None = None


class McpSearchResult(McpPublicBase):
    id: str
    title: str
    url: str
    metadata: dict[str, Any]


class McpFetchMetadata(McpPublicBase):
    type: Literal["material", "request", "market"]
    public: dict[str, Any]


class McpFetchResource(McpPublicBase):
    id: str
    title: str
    text: str
    url: str
    metadata: McpFetchMetadata


class McpContributor(McpPublicBase):
    userId: int
    username: str | None = None
    downloads: int = 0
    roleMask: int = 0


def validate_public_material(payload: dict[str, Any]) -> dict[str, Any]:
    return McpPublicMaterial.model_validate(payload).model_dump()


def validate_public_request(payload: dict[str, Any]) -> dict[str, Any]:
    return McpPublicRequest.model_validate(payload).model_dump()


def validate_public_market(payload: dict[str, Any]) -> dict[str, Any]:
    return McpPublicMarket.model_validate(payload).model_dump()


def validate_search_result(payload: dict[str, Any]) -> dict[str, Any]:
    return McpSearchResult.model_validate(payload).model_dump()


def validate_contributor(payload: dict[str, Any]) -> dict[str, Any]:
    return McpContributor.model_validate(payload).model_dump()


def validate_fetch_resource(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return McpFetchResource.model_validate(payload).model_dump()
    public = metadata.get("public")
    resource_type = metadata.get("type")
    if isinstance(public, dict) and resource_type == "material":
        public = validate_public_material(public)
    elif isinstance(public, dict) and resource_type == "request":
        public = validate_public_request(public)
    elif isinstance(public, dict) and resource_type == "market":
        public = validate_public_market(public)
    payload = {**payload, "metadata": {**metadata, "public": public}}
    return McpFetchResource.model_validate(payload).model_dump()
