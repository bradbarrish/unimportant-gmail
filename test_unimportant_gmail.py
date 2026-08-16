"""Tests for filter criterion parsing and sender matching."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unimportant_gmail import (
    collect_filter_targets,
    filter_criteria_for_senders,
    is_sender_filtered,
    parse_from_criterion,
    parse_query_criterion,
)

_failures = 0


def _expect(label, got, want):
    global _failures
    if got == want:
        print(f"  PASS  {label}")
    else:
        _failures += 1
        print(f"  FAIL  {label}")
        print(f"        got:  {got!r}")
        print(f"        want: {want!r}")


def test_empty():
    e, d = parse_from_criterion("")
    _expect("empty string -> empty sets", (e, d), (set(), set()))

    e, d = parse_from_criterion("    ")
    _expect("whitespace -> empty sets", (e, d), (set(), set()))


def test_exact_email():
    e, d = parse_from_criterion("billing@example.com")
    _expect("exact email -> only exact set", (e, d), ({"billing@example.com"}, set()))


def test_at_domain():
    e, d = parse_from_criterion("@example.com")
    _expect("@domain -> only domain set", (e, d), (set(), {"example.com"}))


def test_bare_domain():
    e, d = parse_from_criterion("example.com")
    _expect("bare domain -> only domain set", (e, d), (set(), {"example.com"}))


def test_or_uppercase():
    e, d = parse_from_criterion("a@x.com OR b@y.com")
    _expect("OR (uppercase)", (e, d), ({"a@x.com", "b@y.com"}, set()))


def test_or_lowercase():
    e, d = parse_from_criterion("a@x.com or b@y.com")
    _expect("OR (lowercase)", (e, d), ({"a@x.com", "b@y.com"}, set()))


def test_curly_braces():
    e, d = parse_from_criterion("{a@x.com b@y.com}")
    _expect("curly braces", (e, d), ({"a@x.com", "b@y.com"}, set()))


def test_parens_or():
    e, d = parse_from_criterion("(a@x.com OR b@y.com)")
    _expect("parens + OR", (e, d), ({"a@x.com", "b@y.com"}, set()))


def test_quoted_values():
    e, d = parse_from_criterion('"someone@example.com"')
    _expect("double-quoted", (e, d), ({"someone@example.com"}, set()))

    e, d = parse_from_criterion("'someone@example.com'")
    _expect("single-quoted", (e, d), ({"someone@example.com"}, set()))


def test_negative_terms():
    e, d = parse_from_criterion("-billing@example.com")
    _expect("negative -> dropped", (e, d), (set(), set()))


def test_mixed():
    e, d = parse_from_criterion("@toast.com OR billing@example.com OR shop.com")
    _expect(
        "mixed exact + @domain + bare-domain",
        (e, d),
        ({"billing@example.com"}, {"toast.com", "shop.com"}),
    )


def test_case_normalization():
    e, d = parse_from_criterion("Billing@EXAMPLE.com")
    _expect("case normalized -> lowercase", (e, d), ({"billing@example.com"}, set()))


def test_sender_matching_exact_only():
    # The high-severity bug: an exact-address filter must NOT cover other addresses at the same domain.
    exact = {"billing@example.com"}
    domains = set()
    _expect(
        "exact filter covers exact address",
        is_sender_filtered("billing@example.com", exact, domains),
        True,
    )
    _expect(
        "exact filter does NOT cover sibling address",
        is_sender_filtered("alerts@example.com", exact, domains),
        False,
    )


def test_sender_matching_domain():
    exact = set()
    domains = {"example.com"}
    _expect(
        "domain filter covers any address at that domain",
        is_sender_filtered("alerts@example.com", exact, domains),
        True,
    )
    _expect(
        "domain filter covers plus-addressed sender",
        is_sender_filtered("billing+abc@example.com", exact, domains),
        True,
    )
    _expect(
        "domain filter does not leak to other domains",
        is_sender_filtered("alerts@other.com", exact, domains),
        False,
    )


def test_sender_matching_both():
    exact = {"vip@partner.com"}
    domains = {"newsletter.com"}
    _expect(
        "exact wins for exact match",
        is_sender_filtered("vip@partner.com", exact, domains),
        True,
    )
    _expect(
        "domain match still works",
        is_sender_filtered("anyone@newsletter.com", exact, domains),
        True,
    )
    _expect(
        "no match at all",
        is_sender_filtered("anyone@partner.com", exact, domains),
        False,
    )


def test_query_from_terms():
    e, d = parse_query_criterion("{from:a@x.com from:b@y.com}")
    _expect("query grouped from terms", (e, d), ({"a@x.com", "b@y.com"}, set()))

    e, d = parse_query_criterion("from:(a@x.com OR b@y.com)")
    _expect("query from parens", (e, d), ({"a@x.com", "b@y.com"}, set()))

    e, d = parse_query_criterion("from:@example.com")
    _expect("query from domain", (e, d), (set(), {"example.com"}))


def test_query_ignores_unscoped_email():
    e, d = parse_query_criterion("a@x.com OR from:b@y.com")
    _expect("query ignores bare email body text", (e, d), ({"b@y.com"}, set()))


def test_collect_filter_targets_includes_query():
    filters = [
        {"criteria": {"from": "billing@example.com"}},
        {"criteria": {"query": "{from:a@x.com from:b@y.com}"}},
    ]
    e, d = collect_filter_targets(filters)
    _expect(
        "collect exact from and query criteria",
        (e, d),
        ({"billing@example.com", "a@x.com", "b@y.com"}, set()),
    )


def test_filter_criteria_for_senders():
    _expect(
        "single sender uses from criteria",
        filter_criteria_for_senders(["a@x.com"]),
        {"from": "a@x.com"},
    )
    _expect(
        "multiple senders use query criteria",
        filter_criteria_for_senders(["a@x.com", "b@y.com"]),
        {"query": "{from:a@x.com from:b@y.com}"},
    )


if __name__ == "__main__":
    print("Running tests...\n")
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(f"-- {name} --")
            fn()
    print()
    if _failures:
        print(f"{_failures} test assertion(s) failed.")
        sys.exit(1)
    print("All tests passed.")
