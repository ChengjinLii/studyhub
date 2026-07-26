from __future__ import annotations

from collections.abc import Iterable

from .base import BaseSkill


class DuplicateSkillError(ValueError):
    """Raised when two implementations claim the same stable skill name."""


class UnknownSkillError(LookupError):
    """Raised before an unregistered capability can be executed."""


class SkillRegistry:
    def __init__(self, skills: Iterable[BaseSkill] = ()) -> None:
        self._skills: dict[str, BaseSkill] = {}
        for skill in skills:
            self.register(skill)

    def register(self, skill: BaseSkill) -> None:
        name = skill.spec.name
        if name in self._skills:
            raise DuplicateSkillError(f"duplicate skill registration: {name}")
        if skill.spec.input_model != skill.input_model.__name__:
            raise ValueError(f"{name} input model name does not match its implementation")
        if skill.spec.output_model != skill.output_model.__name__:
            raise ValueError(f"{name} output model name does not match its implementation")
        self._skills[name] = skill

    def get(self, name: str) -> BaseSkill:
        try:
            return self._skills[name]
        except KeyError as exc:
            raise UnknownSkillError(f"unknown skill: {name}") from exc

    def list(self) -> tuple[BaseSkill, ...]:
        return tuple(self._skills[name] for name in sorted(self._skills))

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._skills))


def build_default_skill_registry() -> SkillRegistry:
    from app.agentic_platform.deepresearch.skills import build_research_skills

    from .interaction import AskAdminSkill
    from .materials import (
        CompareMaterialsSkill,
        FindAnswerPagesSkill,
        FindQuestionPagesSkill,
        InspectMaterialsSkill,
        ReadPdfEvidenceSkill,
        SearchMaterialsSkill,
    )
    from .validation import CheckArtifactSkill, CheckConstraintsSkill, CheckEvidenceSkill

    return SkillRegistry(
        (
            SearchMaterialsSkill(),
            InspectMaterialsSkill(),
            ReadPdfEvidenceSkill(),
            FindQuestionPagesSkill(),
            FindAnswerPagesSkill(),
            CompareMaterialsSkill(),
            AskAdminSkill(),
            CheckConstraintsSkill(),
            CheckEvidenceSkill(),
            CheckArtifactSkill(),
            *build_research_skills(),
        )
    )
