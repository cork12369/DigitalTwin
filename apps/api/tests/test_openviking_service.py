import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.models import MemoryCard, ParticipantToken, RawEvent
from app.services.openviking_service import (
    OpenVikingClient,
    OpenVikingClientError,
    _card_document,
    _event_document,
    _source_from_uri,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300
        self.text = str(payload)

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def request(self, *_args, **_kwargs):
        return self.response


class OpenVikingServiceTests(unittest.TestCase):
    def test_card_document_uses_stable_card_uri_and_frontmatter(self):
        participant = ParticipantToken(id="token-1", label="Test", token_hash="hash")
        card = MemoryCard(
            id="card-1",
            token_id=participant.id,
            title="Prefers direct critique",
            body="They respond well to blunt, concrete feedback.",
            status="reviewed",
            priority="high",
            source_quote="Say it straight.",
            created_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
            updated_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
        )

        document = _card_document(participant, card)

        self.assertEqual(document.uri, "viking://resources/digitaltwin/tokens/token-1/cards/card-1.md")
        self.assertIn('source_type: "memory_card"', document.content)
        self.assertIn("# Memory Card: Prefers direct critique", document.content)

    def test_event_document_routes_replay_events_to_replay_uri(self):
        participant = ParticipantToken(id="token-1", label="Test", token_hash="hash")
        event = RawEvent(
            id="event-1",
            token_id=participant.id,
            event_type="scenario_step_answered",
            payload={
                "step_id": "twin_rank_1",
                "step_type": "twin_rank",
                "replay_scenario_id": "replay_1",
                "step_snapshot": {
                    "id": "twin_rank_1",
                    "type": "twin_rank",
                    "title": "Rank responses",
                    "prompt": "Which response sounds most like you?",
                    "options": ["A", "B", "C"],
                    "replay_scenario_id": "replay_1",
                },
                "answer": {"ranked_options": ["B", "A", "C"], "rejected_options": ["C"]},
            },
            created_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
        )

        document = _event_document(participant, event)

        self.assertIsNotNone(document)
        assert document is not None
        self.assertEqual(document.uri, "viking://resources/digitaltwin/tokens/token-1/replay/replay_1/event-1.md")
        self.assertIn('source_type: "replay_event"', document.content)
        self.assertIn("Ranked: B > A > C", document.content)

    def test_source_id_mapping_from_uri(self):
        self.assertEqual(
            _source_from_uri("viking://resources/digitaltwin/tokens/t/cards/card-1.md"),
            {"source_type": "memory_card", "source_id": "card-1"},
        )
        self.assertEqual(
            _source_from_uri("viking://resources/digitaltwin/tokens/t/replay/replay_1/event-1.md"),
            {"source_type": "replay_event", "source_id": "event-1"},
        )

    def test_client_unwraps_success_envelope(self):
        response = FakeResponse({"status": "success", "result": {"ok": True}})
        client = OpenVikingClient()
        client.base_url = "http://openviking"

        with patch("app.services.openviking_service.httpx.Client", return_value=FakeClient(response)):
            result = client._request("GET", "/api/v1/test")

        self.assertEqual(result, {"ok": True})

    def test_client_raises_error_envelope(self):
        response = FakeResponse(
            {"status": "error", "error": {"code": "UNAUTHORIZED", "message": "bad key"}},
            status_code=401,
        )
        client = OpenVikingClient()
        client.base_url = "http://openviking"

        with patch("app.services.openviking_service.httpx.Client", return_value=FakeClient(response)):
            with self.assertRaises(OpenVikingClientError) as context:
                client._request("GET", "/api/v1/test")

        self.assertEqual(context.exception.code, "UNAUTHORIZED")
        self.assertEqual(str(context.exception), "bad key")


if __name__ == "__main__":
    unittest.main()
