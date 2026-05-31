from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable
from typing import Protocol


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]")


class EmbeddingProvider(Protocol):
    dimensions: int

    def embed_query(self, text: str) -> list[float]:
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...


class MockEmbeddingProvider:
    """Deterministic local embedding model for isolated semantic-search smoke tests.

    This is not a production embedding model. It uses hashed lexical features plus a
    tiny synonym map so the retrieval pipeline can be exercised without API keys,
    external network calls, or production data.
    """

    def __init__(self, dimensions: int = 128) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.dimensions = dimensions

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in expand_tokens(tokenize(text)):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            weight = 1.0 + min(len(token), 8) / 16.0
            vector[bucket] += sign * weight
        return normalize(vector)


def tokenize(text: str) -> list[str]:
    raw_tokens = [match.group(0).lower() for match in TOKEN_PATTERN.finditer(text or "")]
    tokens: list[str] = []
    chinese_run: list[str] = []
    for token in raw_tokens:
        if len(token) == 1 and "\u4e00" <= token <= "\u9fff":
            chinese_run.append(token)
            tokens.append(token)
            continue
        tokens.extend(_flush_chinese_run(chinese_run))
        chinese_run = []
        tokens.append(token)
    tokens.extend(_flush_chinese_run(chinese_run))
    return tokens


def _flush_chinese_run(chars: list[str]) -> list[str]:
    if len(chars) < 2:
        return []
    return ["".join(chars[index : index + 2]) for index in range(len(chars) - 1)]


def expand_tokens(tokens: Iterable[str]) -> list[str]:
    expanded: list[str] = []
    for token in tokens:
        expanded.append(token)
        expanded.extend(SYNONYMS.get(token, ()))
    return expanded


def normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("vectors must have the same dimensions")
    return sum(a * b for a, b in zip(left, right, strict=True))


SYNONYMS: dict[str, tuple[str, ...]] = {
    "通信": ("通原", "信号", "电子信息"),
    "原理": ("基础", "理论"),
    "复习": ("备考", "期末", "考试", "重点"),
    "资料": ("笔记", "讲义", "课件", "文档"),
    "试卷": ("真题", "历年", "卷子"),
    "高数": ("数学", "微积分", "期末"),
    "数据结构": ("算法", "链表", "树", "图"),
    "计算机": ("计科", "软件", "编程"),
    "求购": ("寻找", "需要", "悬赏"),
    "经验": ("攻略", "心得", "分享"),
    "考研": ("备考", "复试", "上岸"),
    "英语": ("六级", "四级", "cet"),
    "通原": ("通信", "原理"),
    "备考": ("复习", "考试", "期末"),
    "真题": ("试卷", "历年"),
    "笔记": ("资料", "讲义"),
    "心得": ("经验", "攻略"),
}
