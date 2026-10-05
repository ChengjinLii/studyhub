import pytest

from studyhub_agent.architectures.citations import check_citations, parse_citations


def test_parse_citations_deduplicates_in_first_seen_order() -> None:
    assert parse_citations("[101:2] [102：1] [101:2] [101:1]") == ((101, 2), (102, 1), (101, 1))


@pytest.mark.parametrize("text", ["普通回答", "[abc:1]", "[101]", "[101:页]", "[١٠١:١]"])
def test_non_citations_are_not_parsed(text) -> None:
    assert parse_citations(text) == ()


def test_citation_report_tracks_unread_pages_not_just_materials() -> None:
    report = check_citations("[101:1] [101:2] [102:1]", frozenset({(101, 1)}))
    assert report.ok is False
    assert report.cited == ((101, 1), (101, 2), (102, 1))
    assert report.unread == ((101, 2), (102, 1))
    assert report.missing is False


def test_missing_citations_only_when_pages_were_read() -> None:
    assert check_citations("answer", frozenset()).ok
    report = check_citations("answer", frozenset({(101, 1)}))
    assert report.missing and not report.ok
    assert check_citations("answer [101:1]", frozenset({(101, 1)})).ok


def test_unread_citation_is_rejected_even_if_no_page_was_read() -> None:
    assert check_citations("[101:1]", frozenset()).unread == ((101, 1),)


@pytest.mark.parametrize("text", ["[" + "1" * 5000 + ":1]", "[101:" + "1" * 5000 + "]", "[" + "0" * 21 + "101:1]"])
def test_oversized_citation_numbers_fail_without_int_or_json_conversion_errors(text) -> None:
    assert parse_citations(text) == ()
    report = check_citations(text, frozenset())
    assert report.invalid is True and report.ok is False
