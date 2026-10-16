import zlib

import pytest
from pydantic import ValidationError

from studyhub_agent.contracts.knowledge import Corpus, KnowledgeScope, PageSpan, search_evidence
from studyhub_agent.knowledge.chunking import make_document
from studyhub_agent.knowledge.parsing import DocumentParseError, parse_document, scanned_page
from studyhub_agent.knowledge.retrieval import KnowledgeRetriever
from studyhub_agent.knowledge.store import upsert_document


def pdf_bytes(pages):
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    page_ids = []
    for text, scanned in pages:
        page_id, stream_id = len(objects) + 1, len(objects) + 2
        page_ids.append(page_id)
        image_id = len(objects) + 3
        resources = "/Font << /F1 3 0 R >> "
        if scanned:
            resources += f"/XObject << /Im0 {image_id} 0 R >> "
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 500 500] "
                f"/Resources << {resources} >> /Contents {stream_id} 0 R >>"
            ).encode()
        )
        stream = f"BT /F1 12 Tf 20 450 Td ({text}) Tj ET\n".encode()
        if scanned:
            stream += b"q 500 0 0 500 0 0 cm /Im0 Do Q\n"
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
        if scanned:
            data = zlib.compress(b"\xff\xff\xff" * 100)
            objects.append(
                (
                    f"<< /Type /XObject /Subtype /Image /Width 10 /Height 10 /ColorSpace /DeviceRGB "
                    f"/BitsPerComponent 8 /Filter /FlateDecode /Length {len(data)} >>\nstream\n"
                ).encode()
                + data
                + b"\nendstream"
            )
    objects[1] = (
        f"<< /Type /Pages /Count {len(page_ids)} /Kids [" + " ".join(f"{key} 0 R" for key in page_ids) + "] >>"
    ).encode()
    result, offsets = b"%PDF-1.4\n", [0]
    for index, value in enumerate(objects, 1):
        offsets.append(len(result))
        result += f"{index} 0 obj\n".encode() + value + b"\nendobj\n"
    xref = len(result)
    result += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    result += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    return result + f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()


class OCR:
    identity = "test-ocr@1"

    def __init__(self, text="Recognized scanned page"):
        self.text, self.calls = text, []

    def read(self, data):
        assert data.startswith(b"\x89PNG")
        self.calls.append(data)
        return self.text


@pytest.mark.parametrize("ratio,length,expected", [(1, 1000, True), (0, 1000, False), (0.2, 2, True), (0, 0, False)])
def test_page_routing_uses_image_coverage_not_only_text_length(ratio, length, expected):
    assert scanned_page(ratio, length) is expected


def test_real_pdf_native_and_scanned_pages_keep_page_citations(tmp_path):
    pytest.importorskip("pypdfium2")
    path = tmp_path / "mixed.pdf"
    path.write_bytes(pdf_bytes([("Native first page content", False), ("Misleading embedded OCR text", True)]))
    ocr = OCR()
    document = parse_document(path, "demo", ocr=ocr)
    assert len(ocr.calls) == 1
    assert "Native first page content" in document.text
    assert "Recognized scanned page" in document.text
    assert "Misleading embedded OCR text" not in document.text
    assert [row.method for row in document.pages] == ["native", "ocr"]
    corpus = upsert_document(Corpus(), document, child_size=64, parent_size=200)
    retriever = KnowledgeRetriever(corpus, KnowledgeScope(knowledge_base_ids=frozenset({"demo"})))
    sources = search_evidence(retriever.search("Recognized"))
    assert sources and any(row.page_end == 2 for row in sources)
    assert all(row.document_id == document.document_id and row.revision == document.revision for row in sources)


def test_scanned_page_ocr_failure_does_not_publish_partial_content(tmp_path):
    pytest.importorskip("pypdfium2")
    path = tmp_path / "scan.pdf"
    path.write_bytes(pdf_bytes([("Native text", False), ("Hidden bad layer", True)]))
    with pytest.raises(DocumentParseError, match="no usable OCR"):
        parse_document(path, "demo", ocr=OCR(""))


def test_image_document_uses_ocr_and_records_source_digest(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    path = tmp_path / "scan.png"
    Image.new("RGB", (32, 32), "white").save(path)
    document = parse_document(path, "demo", ocr=OCR())
    assert document.pages[0].page == 1 and document.pages[0].method == "ocr"
    assert document.source_sha256 and document.parser == "test-ocr@1"


def test_page_locator_changes_invalidate_revision_and_chunk_ids():
    pages = (PageSpan(page=1, start=0, end=4, method="native"), PageSpan(page=2, start=4, end=8, method="native"))
    one = make_document("demo", "notes.pdf", "abcdefgh", pages=pages)
    two = make_document(
        "demo",
        "notes.pdf",
        "abcdefgh",
        pages=(PageSpan(page=1, start=0, end=3, method="native"), PageSpan(page=2, start=3, end=8, method="native")),
    )
    assert one.revision != two.revision
    corpus = upsert_document(Corpus(), one)
    data = corpus.model_dump(mode="json")
    data["chunks"][0]["page_start"] = 2
    with pytest.raises(ValidationError):
        Corpus.model_validate(data)


def test_parent_index_is_materialized_and_parent_context_reaches_rag():
    document = make_document("demo", "notes.md", "# Topic\n" + "A paragraph explains projection and residuals.\n" * 20)
    corpus = upsert_document(Corpus(), document, child_size=64, parent_size=240)
    assert corpus.parents
    retriever = KnowledgeRetriever(corpus, KnowledgeScope(knowledge_base_ids=frozenset({"demo"})))
    result = retriever.search("projection", limit=2)
    assert len({row.evidence.parent_id for row in result.hits}) == len(result.hits)
    assert result.hits[0].context
    for hit in result.hits:
        parent = next(row for row in corpus.parents if row.parent_id == hit.evidence.parent_id)
        children = sorted((hit.evidence, *hit.context), key=lambda row: row.start)
        assert "".join(row.text for row in children) == parent.text
        assert retriever.read(parent.parent_id) == tuple(children)


def test_tampered_parent_context_rejected():
    corpus = upsert_document(Corpus(), make_document("demo", "notes", "Some source text"))
    data = corpus.model_dump(mode="json")
    data["parents"][0]["text"] = "different body!"
    with pytest.raises(ValidationError):
        Corpus.model_validate(data)


@pytest.mark.parametrize("suffix", [".exe", ".pdf", ".png"])
def test_invalid_sources_fail_without_guessing_content(tmp_path, suffix):
    path = tmp_path / ("invalid" + suffix)
    path.write_bytes(b"invalid input")
    with pytest.raises(DocumentParseError):
        parse_document(path, "demo", ocr=OCR())
