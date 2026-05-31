from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.retrieval.semantic_search import InMemorySemanticSearch, SearchResult
from ai_platform.scripts.semantic_search_demo import DEFAULT_SAMPLE_PATH, load_documents
from ai_platform.serving.llm_provider import get_env_chat_provider
from ai_platform.tutoring.question_tutor import LLMQuestionTutor, MockQuestionTutor, QuestionTutorRequest


def run_question_tutor(
    question: str,
    *,
    user_answer: str = "",
    correct_answer: str = "",
    use_api: bool = False,
) -> dict[str, object]:
    searcher = InMemorySemanticSearch(load_documents(DEFAULT_SAMPLE_PATH))
    candidates = select_question_tutor_candidates(searcher.search(question, top_k=8, mode="hybrid"), question, top_k=3)
    provider = get_env_chat_provider() if use_api else None
    tutor = LLMQuestionTutor(provider) if provider else MockQuestionTutor()
    response = tutor.explain(
        QuestionTutorRequest(question=question, user_answer=user_answer, correct_answer=correct_answer),
        candidates=candidates,
    )
    return {"response": response.to_dict(), "candidates": [candidate.to_dict() for candidate in candidates]}


def select_question_tutor_candidates(candidates: list[SearchResult], question: str, *, top_k: int = 3) -> list[SearchResult]:
    terms = _question_terms(question)
    if not terms:
        return candidates[:top_k]
    scored: list[tuple[int, float, SearchResult]] = []
    for candidate in candidates:
        text = candidate.document.searchable_text
        lexical_hits = sum(1 for term in terms if term in text)
        if lexical_hits:
            scored.append((lexical_hits, candidate.score, candidate))
    if not scored:
        return candidates[:top_k]
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in scored[:top_k]]


def _question_terms(question: str) -> list[str]:
    mapping = {
        "链表": ["链表", "数据结构"],
        "二叉树": ["二叉树", "树", "数据结构"],
        "图算法": ["图算法", "最短路", "图", "数据结构"],
        "导数": ["导数", "微积分", "高等数学", "高数"],
        "积分": ["积分", "微积分", "高等数学", "高数"],
        "调制": ["调制", "通信原理", "通原"],
        "信道": ["信道", "通信原理", "通原"],
    }
    terms: list[str] = []
    for key, values in mapping.items():
        if key in question:
            terms.extend(values)
    if not terms:
        terms.extend(token for token in re.split(r"\s+", question) if len(token) >= 2)
    return list(dict.fromkeys(terms))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated StudyHub question tutor demo.")
    parser.add_argument("question", nargs="?", default="这道链表题为什么我写错了？")
    parser.add_argument("--user-answer", default="")
    parser.add_argument("--correct-answer", default="")
    parser.add_argument("--use-api", action="store_true", help="Use STUDYHUB_LLM_* env vars if configured.")
    args = parser.parse_args()
    print(
        json.dumps(
            run_question_tutor(
                args.question,
                user_answer=args.user_answer,
                correct_answer=args.correct_answer,
                use_api=args.use_api,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
