from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass

ENVIRONMENTS = frozenset({"prod", "dev", "train", "eval"})
_PRINCIPAL_PATTERN = re.compile(r"^studyhub:user:[0-9a-f]{32}$")
_SESSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}$")
_NAMESPACE_PART_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    """Pseudonymous identity passed across the Agent runtime boundary."""

    principal_id: str
    session_id: str
    environment: str

    def __post_init__(self) -> None:
        if not _PRINCIPAL_PATTERN.fullmatch(self.principal_id):
            raise ValueError("principal_id must be a pseudonymous StudyHub principal")
        if not _SESSION_PATTERN.fullmatch(self.session_id):
            raise ValueError("session_id must be an opaque identifier with at least 8 characters")
        if self.environment not in ENVIRONMENTS:
            raise ValueError(f"unsupported environment: {self.environment}")

    @classmethod
    def from_raw_user_id(
        cls,
        raw_user_id: str | int,
        *,
        session_id: str,
        environment: str,
        identity_secret: str | bytes,
    ) -> AgentIdentity:
        """Map an internal user ID to a stable, non-reversible external principal."""

        raw = str(raw_user_id).strip()
        if not raw:
            raise ValueError("raw_user_id must not be empty")
        secret = identity_secret.encode("utf-8") if isinstance(identity_secret, str) else identity_secret
        if len(secret) < 16:
            raise ValueError("identity_secret must contain at least 16 bytes")
        digest = hmac.new(secret, raw.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
        return cls(
            principal_id=f"studyhub:user:{digest}",
            session_id=session_id,
            environment=environment,
        )

    @property
    def principal_hash(self) -> str:
        return self.principal_id.rsplit(":", 1)[-1]

    def personal_memory_namespace(
        self,
        *,
        task_id: str | None = None,
        case_id: str | None = None,
        seed: int | None = None,
    ) -> str:
        """Return the fixed memory namespace for the active environment."""

        if self.environment in {"prod", "dev"}:
            return f"{self.environment}:{self.principal_hash}"
        if seed is None or seed < 0:
            raise ValueError("train and eval namespaces require a non-negative seed")
        namespace_id = task_id if self.environment == "train" else case_id
        label = "task_id" if self.environment == "train" else "case_id"
        if not namespace_id or not _NAMESPACE_PART_PATTERN.fullmatch(namespace_id):
            raise ValueError(f"{self.environment} namespace requires a valid {label}")
        return f"{self.environment}:{namespace_id}:{seed}"
