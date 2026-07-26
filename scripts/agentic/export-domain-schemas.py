#!/usr/bin/env python3
"""Print the complete versioned Pydantic JSON Schema bundle for PR2 contracts."""

from __future__ import annotations

import json

from app.agentic_platform.domain.artifact import ArtifactRef
from app.agentic_platform.domain.decision import AgentDecision
from app.agentic_platform.domain.state import AgentTaskState, StateDelta
from app.agentic_platform.domain.transition import AgentTransitionEvent


def main() -> None:
    models = (ArtifactRef, AgentDecision, AgentTaskState, StateDelta, AgentTransitionEvent)
    bundle = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "contract_version": "1.0",
        "schemas": {model.__name__: model.model_json_schema() for model in models},
    }
    print(json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
