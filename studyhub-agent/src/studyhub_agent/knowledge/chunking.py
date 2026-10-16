from __future__ import annotations

import bisect
import json
import re

from studyhub_agent.contracts.knowledge import Chunk, Document, digest

_HEADING = re.compile(r"(?m)^ {0,3}(#{1,6})[ \t]+([^\n]+)")
_PROTECTED = re.compile(
    r"(?m)^ {0,3}(?P<fence>`{3,}|~{3,})[^\n]*\n[\s\S]*?(?:^ {0,3}(?P=fence)[ \t]*(?:\n|$)|\Z)"
    r"|\$\$[\s\S]*?(?:\$\$|\Z)"
    r"|(?m:^[ \t]*\|[^\n]*(?:\n[ \t]*\|[^\n]*)*)"
)


def make_document(knowledge_base_id: str, source: str, text: str, *, title: str | None = None) -> Document:
    key = json.dumps([knowledge_base_id, source], ensure_ascii=False)
    return Document(
        document_id="d_" + digest(key)[:32],
        knowledge_base_id=knowledge_base_id,
        source=source,
        title=title or source,
        text=text,
        revision=digest(text),
    )


def chunk_document(document: Document, *, child_size: int = 600, parent_size: int = 2400) -> tuple[Chunk, ...]:
    if type(child_size) is not int or type(parent_size) is not int or not 64 <= child_size <= parent_size <= 12000:
        raise ValueError("chunk sizes must satisfy 64 <= child_size <= parent_size <= 12000")
    text = document.text
    protected = [(match.start(), match.end()) for match in _PROTECTED.finditer(text)]
    if any(end - start > 12000 for start, end in protected):
        raise ValueError("protected formula, table or code block exceeds 12000 characters")

    def inside(offset: int) -> tuple[int, int] | None:
        return next(((start, end) for start, end in protected if start < offset < end), None)

    boundaries = sorted({0, len(text), *(match.end() for match in re.finditer(r"\n|[。！？；]", text))})
    boundaries = [offset for offset in boundaries if inside(offset) is None]

    def split(start: int, end: int, size: int):
        while start < end:
            target = min(start + size, end)
            position = bisect.bisect_right(boundaries, target) - 1
            cut = min(boundaries[position], end)
            if cut <= start:
                block = inside(target)
                cut = block[0] if block and block[0] > start else block[1] if block else target
                cut = min(cut, end)
            yield start, cut
            start = cut

    sections: list[tuple[int, str]] = [(0, "")]
    headings: list[tuple[int, str]] = []
    for match in _HEADING.finditer(text):
        if inside(match.start()) is not None:
            continue
        level = len(match[1])
        headings = [(depth, title) for depth, title in headings if depth < level]
        headings.append((level, match[2].strip()))
        header = " / ".join(title for _, title in headings)
        if not _HEADING.sub("", text[sections[-1][0] : match.start()]).strip():
            sections[-1] = (sections[-1][0], header)
        else:
            sections.append((match.start(), header))

    chunks: list[Chunk] = []
    for index, (start, header) in enumerate(sections):
        end = sections[index + 1][0] if index + 1 < len(sections) else len(text)
        for parent_start, parent_end in split(start, end, parent_size):
            parent_id = "p_" + digest(f"{document.document_id}:{document.revision}:{parent_start}:{parent_end}")[:32]
            for child_start, child_end in split(parent_start, parent_end, child_size):
                body = text[child_start:child_end]
                key = json.dumps([document.document_id, document.revision, child_start, child_end, header])
                line_start = text.count("\n", 0, child_start) + 1
                chunks.append(
                    Chunk(
                        chunk_id="k_" + digest(key)[:32],
                        document_id=document.document_id,
                        revision=document.revision,
                        parent_id=parent_id,
                        ordinal=len(chunks),
                        start=child_start,
                        end=child_end,
                        line_start=line_start,
                        line_end=line_start + body.count("\n") - int(body.endswith("\n")),
                        context_header=header,
                        text=body,
                    )
                )
    return tuple(chunks)
