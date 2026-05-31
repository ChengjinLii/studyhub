from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class UserProfile:
    id: str
    school: str
    college: str
    major: str
    interests: tuple[str, ...]


@dataclass(frozen=True)
class RankableItem:
    id: str
    type: str
    title: str
    tags: tuple[str, ...]
    school: str | None
    college: str | None
    quality: float
    views: int
    likes: int
    downloads: int
    comments: int
    created_days_ago: int
    risk_score: int
    status: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class Contributor:
    id: str
    name: str
    valid_downloads: int
    favorites: int
    likes: int
    accepted_requests: int
    average_rating: float
    reports_upheld: int
    rejected_materials: int


@dataclass(frozen=True)
class RankedItem:
    item: RankableItem
    score: float
    components: dict[str, float]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.item.id,
            "type": self.item.type,
            "title": self.item.title,
            "score": round(self.score, 4),
            "components": {key: round(value, 4) for key, value in self.components.items()},
            "reasons": self.reasons,
        }


@dataclass(frozen=True)
class RankedContributor:
    contributor: Contributor
    score: float
    components: dict[str, float]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.contributor.id,
            "name": self.contributor.name,
            "score": round(self.score, 4),
            "components": {key: round(value, 4) for key, value in self.components.items()},
            "reasons": self.reasons,
        }


class ExplainableRanker:
    """Feature-scoring Top-N ranker inspired by LTR/recommender toolkits.

    It follows the shape used by systems such as OpenSearch LTR and LensKit:
    build numeric features, apply scenario-specific weights, sort by the final
    score, and keep per-feature explanations for debugging.
    """

    def rank_home_materials(self, items: list[RankableItem], user: UserProfile | None, *, top_k: int = 5) -> list[RankedItem]:
        weights = {
            "interest": 2.4,
            "quality": 2.0,
            "engagement": 1.4,
            "freshness": 1.0,
            "risk_penalty": -2.2,
            "status_penalty": -3.0,
        }
        return self._rank_items(items, user, weights=weights, top_k=top_k, allowed_types={"material", "column"})

    def rank_market_items(self, items: list[RankableItem], user: UserProfile | None, *, top_k: int = 5) -> list[RankedItem]:
        weights = {
            "interest": 1.8,
            "quality": 0.8,
            "engagement": 1.2,
            "freshness": 2.0,
            "risk_penalty": -1.4,
            "status_penalty": -4.0,
        }
        return self._rank_items(items, user, weights=weights, top_k=top_k, allowed_types={"market"})

    def rank_contributors(self, contributors: list[Contributor], *, top_k: int = 10) -> list[RankedContributor]:
        ranked: list[RankedContributor] = []
        for contributor in contributors:
            components = {
                "downloads": math.log1p(contributor.valid_downloads) * 3.0,
                "favorites": math.log1p(contributor.favorites) * 2.0,
                "likes": math.log1p(contributor.likes),
                "acceptedRequests": contributor.accepted_requests * 5.0,
                "rating": max(0.0, contributor.average_rating - 3.0) * 4.0,
                "riskPenalty": contributor.reports_upheld * -10.0 + contributor.rejected_materials * -5.0,
            }
            score = sum(components.values())
            reasons = _positive_reasons(
                [
                    (components["downloads"], "有效下载贡献高"),
                    (components["acceptedRequests"], "求购采纳次数高"),
                    (components["rating"], "评分表现好"),
                    (-components["riskPenalty"], "存在成立举报或驳回记录"),
                ]
            )
            ranked.append(RankedContributor(contributor=contributor, score=score, components=components, reasons=reasons))
        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[: max(1, top_k)]

    def _rank_items(
        self,
        items: list[RankableItem],
        user: UserProfile | None,
        *,
        weights: dict[str, float],
        top_k: int,
        allowed_types: set[str],
    ) -> list[RankedItem]:
        ranked: list[RankedItem] = []
        for item in items:
            if item.type not in allowed_types:
                continue
            features = self._item_features(item, user)
            components = {name: features[name] * weight for name, weight in weights.items()}
            score = sum(components.values())
            ranked.append(RankedItem(item=item, score=score, components=components, reasons=_item_reasons(item, features)))
        ranked.sort(key=lambda entry: entry.score, reverse=True)
        return ranked[: max(1, top_k)]

    def _item_features(self, item: RankableItem, user: UserProfile | None) -> dict[str, float]:
        tag_overlap = 0.0
        school_match = 0.0
        college_match = 0.0
        if user is not None:
            interest_set = {value.lower() for value in user.interests}
            item_tags = {value.lower() for value in item.tags}
            tag_overlap = len(interest_set & item_tags) / max(1, len(interest_set))
            school_match = 1.0 if item.school and item.school == user.school else 0.0
            college_match = 1.0 if item.college and item.college == user.college else 0.0
        interest = min(1.0, tag_overlap * 0.7 + school_match * 0.15 + college_match * 0.15)
        engagement = min(1.0, math.log1p(item.views + item.likes * 4 + item.downloads * 6 + item.comments * 3) / 8.0)
        freshness = 1.0 / (1.0 + item.created_days_ago / 14.0)
        risk_penalty = min(1.0, item.risk_score / 100.0)
        status_penalty = 0.0 if item.status in {"VISIBLE", "SALE"} else 1.0
        return {
            "interest": interest,
            "quality": max(0.0, min(1.0, item.quality)),
            "engagement": engagement,
            "freshness": freshness,
            "risk_penalty": risk_penalty,
            "status_penalty": status_penalty,
        }


def load_recommendation_fixture(raw: dict[str, Any]) -> tuple[UserProfile, list[RankableItem], list[Contributor]]:
    user_raw = raw["user"]
    user = UserProfile(
        id=str(user_raw["id"]),
        school=str(user_raw.get("school") or ""),
        college=str(user_raw.get("college") or ""),
        major=str(user_raw.get("major") or ""),
        interests=tuple(str(value) for value in user_raw.get("interests", [])),
    )
    items = [
        RankableItem(
            id=str(item["id"]),
            type=str(item["type"]),
            title=str(item["title"]),
            tags=tuple(str(value) for value in item.get("tags", [])),
            school=item.get("school"),
            college=item.get("college"),
            quality=float(item.get("quality") or 0.0),
            views=int(item.get("views") or 0),
            likes=int(item.get("likes") or 0),
            downloads=int(item.get("downloads") or 0),
            comments=int(item.get("comments") or 0),
            created_days_ago=_days_ago(str(item.get("createdAt") or raw["today"]), today=str(raw["today"])),
            risk_score=int(item.get("riskScore") or 0),
            status=str(item.get("status") or "VISIBLE"),
            metadata=dict(item.get("metadata") or {}),
        )
        for item in raw.get("items", [])
    ]
    contributors = [
        Contributor(
            id=str(item["id"]),
            name=str(item["name"]),
            valid_downloads=int(item.get("validDownloads") or 0),
            favorites=int(item.get("favorites") or 0),
            likes=int(item.get("likes") or 0),
            accepted_requests=int(item.get("acceptedRequests") or 0),
            average_rating=float(item.get("averageRating") or 0.0),
            reports_upheld=int(item.get("reportsUpheld") or 0),
            rejected_materials=int(item.get("rejectedMaterials") or 0),
        )
        for item in raw.get("contributors", [])
    ]
    return user, items, contributors


def _days_ago(value: str, *, today: str) -> int:
    return max(0, (date.fromisoformat(today) - date.fromisoformat(value)).days)


def _item_reasons(item: RankableItem, features: dict[str, float]) -> list[str]:
    reason_candidates = [
        (features["interest"], "与用户学校/学院/兴趣标签匹配"),
        (features["quality"], "内容质量分较高"),
        (features["engagement"], "浏览、下载、点赞或评论表现较好"),
        (features["freshness"], "发布时间较新"),
        (features["risk_penalty"], "存在内容风险惩罚"),
        (features["status_penalty"], f"状态为 {item.status}，排序降权"),
    ]
    return _positive_reasons(reason_candidates)


def _positive_reasons(reason_candidates: list[tuple[float, str]]) -> list[str]:
    return [reason for value, reason in reason_candidates if value > 0.05]
