import pytest

from studyhub_agent.guardrails.budget import BudgetExceeded, BudgetState
from studyhub_agent.guardrails.citation import validate_citations
from studyhub_agent.guardrails.privacy import sanitize_output


def test_budget_counts_steps_tools_and_duplicates_without_routing() -> None:
    budget = BudgetState(max_steps=4, max_tool_calls=2)
    budget.record_model_step()
    budget.authorize_tool("knowledge_search", "same")
    budget.authorize_tool("knowledge_search", "same")

    assert budget.steps == 1
    assert budget.tool_calls == 2
    assert budget.duplicate_tool_calls == 1
    with pytest.raises(BudgetExceeded):
        budget.authorize_tool("web_search", "new")


def test_citation_validation_only_accepts_visible_sources() -> None:
    text = "结论一。[source:material:128:p12:c3] 结论二。[source:material:130:p8:c2]"
    validation = validate_citations(text, {"material:128:p12:c3"})

    assert validation.cited == ("material:128:p12:c3", "material:130:p8:c2")
    assert validation.invalid == ("material:130:p8:c2",)


def test_output_privacy_removes_identity_fields_and_emails() -> None:
    value = sanitize_output(
        {
            "title": "公开资料",
            "email": "private@example.com",
            "nested": {"raw_user_id": 294, "text": "contact private@example.com"},
        }
    )

    assert "email" not in value
    assert "raw_user_id" not in value["nested"]
    assert value["nested"]["text"] == "contact [redacted-email]"
