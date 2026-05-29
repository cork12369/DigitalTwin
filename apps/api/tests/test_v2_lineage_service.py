import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import ExperimentVariant, MemoryCard, MemoryCardPillarLink, ParticipantToken, RawEvent, SubagentVerdict
from app.services.v2_lineage_service import (
    DEFAULT_DELTA_W_MATRIX,
    SubagentResponsePayload,
    SubagentVerdictPayload,
    apply_subagent_response,
    band_for_ece,
    calculate_delta_w,
    calibration_metrics,
    fit_temperature,
    record_holdout_prediction,
    relevant_cards_for_event,
)


class V2LineageServiceTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.participant = ParticipantToken(id="token-1", label="Pookie", token_hash="hash", calibration_band="unmeasured")
        self.variant = ExperimentVariant(
            id="variant-1",
            label="v2_default",
            delta_w_matrix=DEFAULT_DELTA_W_MATRIX,
            subagent_model_id="deepseek/deepseek-v4-pro",
            subagent_reasoning_effort="high",
            compaction_model_id="deepseek/deepseek-v4-pro",
            prompt_template_hash="hash",
            target_accuracy_band={"min": 0.7},
        )
        self.participant.active_experiment_variant_id = self.variant.id
        self.db.add_all([self.variant, self.participant])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _card(self, card_id: str, card_type: str = "disposition", pillar_key: str = "situation_framing") -> MemoryCard:
        card = MemoryCard(
            id=card_id,
            token_id=self.participant.id,
            title=f"{card_type} card",
            body="prefers direct reversible action under pressure",
            status="reviewed",
            priority="medium",
            card_type=card_type,
            seed_source="profile",
        )
        self.db.add(card)
        self.db.flush()
        if pillar_key:
            self.db.add(MemoryCardPillarLink(card_id=card.id, pillar_key=pillar_key, weight=1.0))
        self.db.commit()
        return card

    def _event(self, step_type: str = "triad", holdout: bool = False, answer_mode: str = "binary") -> RawEvent:
        event = RawEvent(
            id=f"event-{step_type}-{holdout}-{answer_mode}",
            token_id=self.participant.id,
            event_type=f"{step_type}_answered",
            answer_mode=answer_mode,
            holdout_slot=holdout,
            holdout_partition="test" if holdout else None,
            payload={
                "step_id": "adaptive_q_1",
                "step_type": step_type,
                "answer_mode": answer_mode,
                "answer": {"selected_index": 0, "selected_option": "Take direct reversible action"},
                "step_snapshot": {
                    "id": "adaptive_q_1",
                    "type": step_type,
                    "title": "Pressure",
                    "prompt": "What do you do?",
                    "options": ["Take direct reversible action", "Delay for more review", "Delegate"],
                },
            },
        )
        self.db.add(event)
        self.db.commit()
        return event

    def test_delta_calculation_scales_by_polarity_confidence_and_spectrum(self):
        self.assertEqual(calculate_delta_w("duel", "reinforce", 0.80), 0.4)
        self.assertEqual(calculate_delta_w("duel", "contradict", 0.80), -0.52)
        self.assertEqual(calculate_delta_w("duel", "reinforce", 0.39), 0.0)
        self.assertEqual(calculate_delta_w("duel", "reinforce", 0.80, spectrum_position=-0.5), -0.2)

    def test_type_relevance_and_biographical_immutability(self):
        disposition = self._card("card-disposition", "disposition")
        stylistic = self._card("card-stylistic", "stylistic")
        event = self._event("triad")

        relevant = relevant_cards_for_event(self.db, self.participant, event)
        self.assertIn(disposition.id, {card.id for card in relevant})
        self.assertNotIn(stylistic.id, {card.id for card in relevant})
        self.assertEqual(calculate_delta_w("triad", "reinforce", 0.9, card_type="biographical"), 0.0)

    def test_apply_response_caps_moved_cards_at_four(self):
        cards = [self._card(f"card-{index}", "disposition") for index in range(5)]
        event = self._event("triad")
        payload = SubagentResponsePayload(
            verdicts=[
                SubagentVerdictPayload(
                    card_id=card.id,
                    polarity="reinforce",
                    confidence=0.95 - index * 0.01,
                    rationale="test",
                )
                for index, card in enumerate(cards)
            ]
        )

        rows = apply_subagent_response(self.db, self.participant, event, self.variant, payload)
        self.db.commit()

        self.assertEqual(len(rows), 4)
        self.assertEqual(self.db.query(SubagentVerdict).filter(SubagentVerdict.raw_event_id == event.id).count(), 4)

    def test_holdout_prediction_does_not_create_verdicts_or_weight_updates(self):
        card = self._card("card-holdout", "disposition")
        link = card.pillar_links[0]
        event = self._event("triad", holdout=True)

        prediction = record_holdout_prediction(self.db, self.participant, event)
        self.db.commit()
        self.db.refresh(link)

        self.assertIsNotNone(prediction)
        self.assertEqual(self.db.query(SubagentVerdict).filter(SubagentVerdict.raw_event_id == event.id).count(), 0)
        self.assertEqual(link.update_count, 0)
        self.assertEqual(link.cumulative_delta_w, 0.0)

    def test_calibration_metrics_and_bands(self):
        green = [
            {"distribution": {"0": 0.99, "1": 0.01}, "actual_label": "0"},
            {"distribution": {"0": 0.99, "1": 0.01}, "actual_label": "0"},
        ]
        amber = [{"distribution": {"0": 0.93, "1": 0.07}, "actual_label": "0"}]
        red = [{"distribution": {"0": 0.70, "1": 0.30}, "actual_label": "0"}]

        self.assertEqual(band_for_ece(calibration_metrics(green)["ece"]), "green")
        self.assertEqual(band_for_ece(calibration_metrics(amber)["ece"]), "amber")
        self.assertEqual(band_for_ece(calibration_metrics(red)["ece"]), "red")
        self.assertGreater(fit_temperature(red), 0)


if __name__ == "__main__":
    unittest.main()
