"""Tests for filter criterion parsing and sender matching."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unimportant_gmail import (
    METADATA_BATCH_SIZE,
    fetch_message_metadata,
    is_sender_filtered,
    parse_from_criterion,
)


class FakeGetRequest:
    def __init__(self, message_id):
        self.message_id = message_id

    def execute(self):
        return {
            "id": self.message_id,
            "payload": {
                "headers": [
                    {"name": "From", "value": f"{self.message_id}@example.com"},
                    {"name": "Subject", "value": self.message_id},
                ]
            },
        }


class FakeMessages:
    def get(self, userId, id, format, metadataHeaders):
        return FakeGetRequest(id)


class FakeUsers:
    def messages(self):
        return FakeMessages()


class FakeBatch:
    def __init__(self, service, callback):
        self.service = service
        self.callback = callback
        self.requests = []

    def add(self, request, request_id):
        self.requests.append((request_id, request))

    def execute(self):
        self.service.batch_sizes.append(len(self.requests))
        for request_id, request in self.requests:
            self.callback(request_id, request.execute(), None)


class FakeService:
    def __init__(self):
        self.batch_sizes = []

    def users(self):
        return FakeUsers()

    def new_batch_http_request(self, callback):
        return FakeBatch(self, callback)


class FilterCriterionParsingTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(parse_from_criterion(""), (set(), set()))
        self.assertEqual(parse_from_criterion("    "), (set(), set()))

    def test_exact_email(self):
        self.assertEqual(parse_from_criterion("billing@example.com"), ({"billing@example.com"}, set()))

    def test_at_domain(self):
        self.assertEqual(parse_from_criterion("@example.com"), (set(), {"example.com"}))

    def test_bare_domain(self):
        self.assertEqual(parse_from_criterion("example.com"), (set(), {"example.com"}))

    def test_or_terms(self):
        self.assertEqual(parse_from_criterion("a@x.com OR b@y.com"), ({"a@x.com", "b@y.com"}, set()))
        self.assertEqual(parse_from_criterion("a@x.com or b@y.com"), ({"a@x.com", "b@y.com"}, set()))

    def test_grouping_and_quotes(self):
        self.assertEqual(parse_from_criterion("{a@x.com b@y.com}"), ({"a@x.com", "b@y.com"}, set()))
        self.assertEqual(parse_from_criterion("(a@x.com OR b@y.com)"), ({"a@x.com", "b@y.com"}, set()))
        self.assertEqual(parse_from_criterion('"someone@example.com"'), ({"someone@example.com"}, set()))
        self.assertEqual(parse_from_criterion("'someone@example.com'"), ({"someone@example.com"}, set()))

    def test_negative_terms(self):
        self.assertEqual(parse_from_criterion("-billing@example.com"), (set(), set()))

    def test_mixed(self):
        self.assertEqual(
            parse_from_criterion("@toast.com OR billing@example.com OR shop.com"),
            ({"billing@example.com"}, {"toast.com", "shop.com"}),
        )

    def test_case_normalization(self):
        self.assertEqual(parse_from_criterion("Billing@EXAMPLE.com"), ({"billing@example.com"}, set()))


class SenderMatchingTest(unittest.TestCase):
    def test_sender_matching_exact_only(self):
        exact = {"billing@example.com"}
        domains = set()
        self.assertTrue(is_sender_filtered("billing@example.com", exact, domains))
        self.assertFalse(is_sender_filtered("alerts@example.com", exact, domains))

    def test_sender_matching_domain(self):
        exact = set()
        domains = {"example.com"}
        self.assertTrue(is_sender_filtered("alerts@example.com", exact, domains))
        self.assertTrue(is_sender_filtered("billing+abc@example.com", exact, domains))
        self.assertFalse(is_sender_filtered("alerts@other.com", exact, domains))

    def test_sender_matching_both(self):
        exact = {"vip@partner.com"}
        domains = {"newsletter.com"}
        self.assertTrue(is_sender_filtered("vip@partner.com", exact, domains))
        self.assertTrue(is_sender_filtered("anyone@newsletter.com", exact, domains))
        self.assertFalse(is_sender_filtered("anyone@partner.com", exact, domains))


class MessageMetadataFetchTest(unittest.TestCase):
    def test_fetch_message_metadata_chunks_large_pages(self):
        svc = FakeService()
        message_ids = [f"m{i}" for i in range(METADATA_BATCH_SIZE + 1)]

        metadata = fetch_message_metadata(svc, message_ids)

        self.assertEqual([item["id"] for item in metadata], message_ids)
        self.assertEqual(svc.batch_sizes, [METADATA_BATCH_SIZE, 1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
