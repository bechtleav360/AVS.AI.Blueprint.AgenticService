"""Unit tests for AgentOutput and AnalysisRequest validators."""

import pytest
from pydantic import ValidationError

from blueprint.agents.models.result import AgentOutput, AnalysisRequest, Evidence


def _evidence(confidence: float, label: str = "e") -> Evidence:
    return Evidence(type=label, source="src", value="v", confidence=confidence)


# ---------------------------------------------------------------------------
# Evidence.confidence constraints
# ---------------------------------------------------------------------------


class TestEvidenceConfidence:
    def test_zero_confidence_is_valid(self) -> None:
        e = _evidence(0.0)
        assert e.confidence == 0.0

    def test_one_confidence_is_valid(self) -> None:
        e = _evidence(1.0)
        assert e.confidence == 1.0

    def test_below_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            _evidence(-0.1)

    def test_above_one_raises(self) -> None:
        with pytest.raises(ValidationError):
            _evidence(1.1)


# ---------------------------------------------------------------------------
# AgentOutput.sort_evidence_by_confidence
# ---------------------------------------------------------------------------


class TestSortEvidenceByConfidence:
    def _output(self, evidence: list[Evidence]) -> AgentOutput:
        return AgentOutput(resource_id="r", status="ok", confidence=1.0, evidence=evidence)

    def test_empty_evidence_list_stays_empty(self) -> None:
        output = self._output([])
        assert output.evidence == []

    def test_single_item_unchanged(self) -> None:
        e = _evidence(0.7)
        output = self._output([e])
        assert output.evidence == [e]

    def test_multiple_items_sorted_descending(self) -> None:
        low = _evidence(0.2, "low")
        mid = _evidence(0.5, "mid")
        high = _evidence(0.9, "high")
        output = self._output([low, mid, high])
        assert output.evidence[0].confidence == 0.9
        assert output.evidence[1].confidence == 0.5
        assert output.evidence[2].confidence == 0.2

    def test_already_sorted_input_unchanged(self) -> None:
        items = [_evidence(0.9), _evidence(0.5), _evidence(0.1)]
        output = self._output(items)
        confidences = [e.confidence for e in output.evidence]
        assert confidences == sorted(confidences, reverse=True)


# ---------------------------------------------------------------------------
# AnalysisRequest.check_resource_or_id_provided
# ---------------------------------------------------------------------------


class TestAnalysisRequestValidator:
    def test_only_resource_id_is_valid(self) -> None:
        req = AnalysisRequest(resource_id="res-1")
        assert req.resource_id == "res-1"

    def test_only_resource_dict_is_valid(self) -> None:
        req = AnalysisRequest(resource={"id": "res-1"})
        assert req.resource == {"id": "res-1"}

    def test_neither_field_raises(self) -> None:
        with pytest.raises(ValidationError, match="Either 'resource_id' or 'resource'"):
            AnalysisRequest()

    def test_both_fields_raises(self) -> None:
        with pytest.raises(ValidationError, match="not both"):
            AnalysisRequest(resource_id="r", resource={"id": "r"})
