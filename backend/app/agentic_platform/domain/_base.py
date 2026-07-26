from __future__ import annotations

from pydantic import BaseModel, ConfigDict


DOMAIN_SCHEMA_VERSION = "1.0"


class DomainModel(BaseModel):
    """Base class for durable agent-domain payloads.

    Rejecting unknown fields is intentional: persisted transitions and training
    exports must not silently change shape when a caller misspells a field.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
