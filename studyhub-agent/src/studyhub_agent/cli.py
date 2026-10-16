from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from contextlib import ExitStack
from pathlib import Path

import httpx

from studyhub_agent.architectures.knowledge_verify import KnowledgeVerifyArchitecture
from studyhub_agent.contracts.episode import EpisodeSpec, KnowledgePrincipal, Termination
from studyhub_agent.contracts.knowledge import Corpus, KnowledgeScope
from studyhub_agent.contracts.knowledge_prompts import KNOWLEDGE_PROMPTS, KNOWLEDGE_SYSTEM_KEY
from studyhub_agent.environments.knowledge import KnowledgeEnvironment
from studyhub_agent.knowledge.parsing import TesseractOCR, parse_document
from studyhub_agent.knowledge.providers import HttpEmbedder, HttpReranker, KnowledgeBackendError
from studyhub_agent.knowledge.retrieval import KnowledgeRetriever
from studyhub_agent.knowledge.store import delete_document, load_corpus, save_corpus, upsert_document
from studyhub_agent.knowledge.wiki import (
    HeadingExtractor,
    HttpWikiExtractor,
    WikiIndex,
    load_wiki,
    save_wiki,
    update_wiki,
)
from studyhub_agent.runtime.openai_client import OpenAICompatPolicyClient
from studyhub_agent.runtime.policy import PolicyInfraError
from studyhub_agent.runtime.rag import RagPipeline
from studyhub_agent.runtime.runner import EpisodeRunner
from studyhub_agent.runtime.tokenizer import HFTokenizer, token_counter


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="StudyHub 独立知识库、RAG 与 Agent")
    parser.add_argument("--corpus", type=Path, default=Path(".knowledge/corpus.json"), help="独立知识快照路径")
    parser.add_argument("--kb", default="demo", help="本次运行的知识库范围")
    parser.add_argument("--embedding-endpoint", help="显式指定 embedding 完整 HTTP 端点")
    parser.add_argument("--embedding-model", help="embedding 模型标识，建议包含版本")
    parser.add_argument("--rerank-endpoint", help="显式指定 rerank 完整 HTTP 端点")
    parser.add_argument("--rerank-model", help="rerank 模型标识，建议包含版本")
    parser.add_argument("--wiki", type=Path, help="可选 Wiki 快照，作为额外召回通道")
    commands = parser.add_subparsers(dest="command", required=True)
    index = commands.add_parser("index", help="原子导入或更新本地 Markdown/TXT、PDF 与图片文档")
    index.add_argument("files", nargs="+", type=Path)
    index.add_argument("--chunk-size", type=int, default=600)
    index.add_argument("--parent-size", type=int, default=2400)
    index.add_argument("--ocr-languages", default="chi_sim+eng")
    delete = commands.add_parser("delete", help="删除当前知识库中的文档与父子索引")
    delete.add_argument("id")
    wiki = commands.add_parser("wiki-build", help="Map 抽取、Reduce 聚合并增量发布 Wiki")
    wiki.add_argument("--output", type=Path, default=Path(".knowledge/wiki.json"))
    wiki.add_argument("--extractive", action="store_true", help="显式使用离线标题抽取基线")
    wiki.add_argument("--model-endpoint", help="OpenAI 兼容的完整 chat/completions 端点")
    wiki.add_argument("--model")
    wiki_search = commands.add_parser("wiki-search", help="按当前知识范围检索 Wiki 与来源")
    wiki_search.add_argument("query")
    wiki_search.add_argument("--limit", type=int, default=5)
    search = commands.add_parser("search", help="检索正文并展示版本化证据")
    search.add_argument("query")
    search.add_argument("--mode", choices=("keyword", "semantic", "hybrid"), default="hybrid")
    search.add_argument("--limit", type=int, default=5)
    read = commands.add_parser("read", help="按文档或片段阅读")
    read.add_argument("id")
    read.add_argument("--offset", type=int, default=0)
    read.add_argument("--limit", type=int, default=5)
    read.add_argument("--context", type=int, default=0)
    commands.add_parser("list", help="列出当前知识库的文档")
    ask = commands.add_parser("ask", help="使用显式配置的模型进行 RAG 或多步 Agent 问答")
    ask.add_argument("query")
    ask.add_argument("--mode", choices=("rag", "agent"), default="rag")
    ask.add_argument("--model-url", required=True, help="模型服务根地址，不含 /v1")
    ask.add_argument("--model", required=True)
    ask.add_argument("--model-dir", required=True, type=Path, help="本地 tokenizer 目录，用于真实 token 预算")
    return parser


def _emit(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _run(args: argparse.Namespace, stack: ExitStack) -> int:
    if not args.kb.strip():
        raise ValueError("knowledge base must not be empty")
    for kind in ("embedding", "rerank"):
        if bool(getattr(args, f"{kind}_endpoint")) != bool(getattr(args, f"{kind}_model")):
            raise ValueError(f"{kind} endpoint and model must be configured together")
    if args.command == "index":
        corpus = load_corpus(args.corpus) if args.corpus.exists() else Corpus()
        for path in args.files:
            document = parse_document(path, args.kb, ocr=TesseractOCR(args.ocr_languages))
            corpus = upsert_document(corpus, document, child_size=args.chunk_size, parent_size=args.parent_size)
        save_corpus(args.corpus, corpus)
        _emit(
            {
                "corpus_fingerprint": corpus.fingerprint,
                "documents": len(corpus.documents),
                "chunks": len(corpus.chunks),
                "parents": len(corpus.parents),
            }
        )
        return 0
    corpus = load_corpus(args.corpus)
    scope = KnowledgeScope(knowledge_base_ids=frozenset({args.kb}))
    if args.command == "delete":
        if not any(row.document_id == args.id and scope.allows(row) for row in corpus.documents):
            raise ValueError("document_not_found")
        corpus = delete_document(corpus, args.id)
        save_corpus(args.corpus, corpus)
        _emit({"deleted": args.id, "corpus_fingerprint": corpus.fingerprint})
        return 0
    if args.command == "wiki-build":
        if args.extractive and (args.model_endpoint or args.model):
            raise ValueError("choose extractive baseline or a model endpoint, not both")
        if not args.extractive and not (args.model_endpoint and args.model):
            raise ValueError("wiki-build requires model endpoint and model, or --extractive")
        extractor = (
            HeadingExtractor()
            if args.extractive
            else HttpWikiExtractor(
                args.model_endpoint, args.model, api_key=os.getenv("STUDYHUB_KNOWLEDGE_MODEL_API_KEY")
            )
        )
        if isinstance(extractor, HttpWikiExtractor):
            stack.callback(extractor.close)
        previous = load_wiki(args.output) if args.output.exists() else None
        update = update_wiki(corpus, scope, extractor, previous)
        save_wiki(args.output, update.snapshot)
        _emit(
            {
                "pages": len(update.snapshot.pages),
                "mapped_chunks": update.mapped_chunks,
                "reused_chunks": update.reused_chunks,
                "updated_pages": update.updated_pages,
                "deleted_pages": update.deleted_pages,
                "extractor": extractor.identity,
            }
        )
        return 0
    wiki_snapshot = load_wiki(args.wiki) if args.wiki else None
    if args.command == "wiki-search":
        if wiki_snapshot is None:
            raise ValueError("wiki-search requires --wiki")
        pages = WikiIndex(corpus, scope, wiki_snapshot).search(args.query, args.limit)
        _emit({"pages": [row.model_dump(mode="json") for row in pages]})
        return 0
    providers = {}
    api_key = os.getenv("STUDYHUB_KNOWLEDGE_MODEL_API_KEY")
    for kind, cls, key in (("embedding", HttpEmbedder, "embedder"), ("rerank", HttpReranker, "reranker")):
        if endpoint := getattr(args, f"{kind}_endpoint"):
            provider = cls(endpoint, getattr(args, f"{kind}_model"), api_key=api_key)
            stack.callback(provider.close)
            providers[key] = provider
    retriever = KnowledgeRetriever(corpus, scope, wiki=wiki_snapshot, **providers)
    if args.command == "search":
        _emit(retriever.search(args.query, mode=args.mode, limit=args.limit).model_dump(mode="json"))
        return 0
    if args.command == "read":
        evidence = retriever.read(args.id, offset=args.offset, limit=args.limit, context=args.context)
        _emit({"evidence": [row.model_dump() | {"citation": row.citation} for row in evidence]})
        return 0
    if args.command == "list":
        _emit(
            {
                "documents": [
                    {key: getattr(row, key) for key in ("document_id", "title", "revision", "knowledge_base_id")}
                    for row in retriever.documents.values()
                ]
            }
        )
        return 0
    tokenizer = HFTokenizer.from_model_dir(args.model_dir)
    counter = token_counter(tokenizer)
    client = stack.enter_context(httpx.Client(timeout=120, trust_env=False))
    policy = OpenAICompatPolicyClient(args.model_url, args.model, api_key=api_key, tokenizer=tokenizer, client=client)
    if args.mode == "rag":
        result = RagPipeline(retriever).run(
            args.query, policy, count_tokens=lambda messages: counter(messages, (), False)
        )
        _emit(
            {
                **result.model_dump(mode="json"),
                "retrieval": retriever.configuration,
                "model": args.model,
                "tokenizer_revision": tokenizer.revision,
            }
        )
        return 0 if result.status in {"answered", "no_evidence"} else 2
    environment = KnowledgeEnvironment(retriever)
    spec = EpisodeSpec(
        episode_id=str(uuid.uuid4()),
        task_id="knowledge-question",
        user_message=args.query,
        principal=KnowledgePrincipal(principal_id="local"),
        system_prompt=KNOWLEDGE_SYSTEM_KEY,
        tool_names=tuple(tool.name for tool in environment.tool_specs()),
        metadata={"corpus_fingerprint": corpus.fingerprint},
    )
    runner = EpisodeRunner(prompts=KNOWLEDGE_PROMPTS, tokenizer_revision=tokenizer.revision, count_tokens=counter)
    episode = runner.run(
        spec, environment, policy, architecture=KnowledgeVerifyArchitecture(), models={"small": args.model}
    )
    _emit(episode.model_dump(mode="json"))
    return 0 if episode.termination == Termination.FINAL_ANSWER else 2


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        with ExitStack() as stack:
            return _run(args, stack)
    except (OSError, ValueError, KnowledgeBackendError, PolicyInfraError) as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
