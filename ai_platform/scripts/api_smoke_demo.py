from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.router.query_understanding import LLMQueryUnderstandingRouter
from ai_platform.serving.embedding_provider import EmbeddingRequest, get_env_embedding_provider
from ai_platform.serving.llm_provider import ChatCompletionRequest, ChatMessage, get_env_chat_provider


def run_api_smoke(*, run_api: bool = False) -> dict[str, object]:
    chat_provider = get_env_chat_provider()
    embedding_provider = get_env_embedding_provider()
    configured = {
        "chatProviderConfigured": chat_provider is not None,
        "embeddingProviderConfigured": embedding_provider is not None,
    }
    if not run_api:
        return {
            **configured,
            "executed": False,
            "reason": "pass --run-api to call configured providers with sample-only data",
        }
    results: dict[str, object] = {**configured, "executed": True}
    if chat_provider:
        router_result = LLMQueryUnderstandingRouter(chat_provider).understand(
            "我两周后考通信原理，基础一般，想找速成资料和真题解析。"
        )
        ping = chat_provider.complete(
            ChatCompletionRequest(
                messages=[ChatMessage(role="user", content="只回复一个 JSON：{\"ok\": true}")],
                temperature=0.0,
                max_tokens=80,
                response_format={"type": "json_object"},
            )
        )
        results["chat"] = {
            "provider": ping.provider,
            "model": ping.model,
            "usage": ping.usage,
            "routerIntent": router_result.intent,
            "routerFallbackUsed": router_result.fallback_used,
        }
    if embedding_provider:
        embedding = embedding_provider.embed(EmbeddingRequest(texts=["通信原理期末复习", "数据结构实验报告"]))
        results["embedding"] = {
            "provider": embedding.provider,
            "dimensions": embedding.dimensions,
            "vectorCount": len(embedding.vectors),
        }
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run optional StudyHub AI provider smoke test with sample-only data.")
    parser.add_argument("--run-api", action="store_true", help="Actually call configured providers.")
    args = parser.parse_args()
    print(json.dumps(run_api_smoke(run_api=args.run_api), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
