"""Unit tests for sessions domain models."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from blueprint.agents.models.sessions import JobNotification

_VALID = {
    "session_id": "00000000-0000-0000-0000-000000000001",
    "job_id": "00000000-0000-0000-0000-000000000002",
    "job_type": "transcription",
    "created_at": "2024-01-01T00:00:00Z",
}


class TestJobNotification:
    def test_parses_and_types_ids(self) -> None:
        n = JobNotification.model_validate(_VALID)
        assert n.session_id == UUID("00000000-0000-0000-0000-000000000001")
        assert n.job_id == UUID("00000000-0000-0000-0000-000000000002")
        assert n.job_type == "transcription"

    def test_created_at_optional(self) -> None:
        data = {k: v for k, v in _VALID.items() if k != "created_at"}
        assert JobNotification.model_validate(data).created_at is None

    def test_missing_required_field_raises(self) -> None:
        data = {k: v for k, v in _VALID.items() if k != "job_id"}
        with pytest.raises(ValidationError):
            JobNotification.model_validate(data)

    def test_extra_keys_preserved_in_payload(self) -> None:
        n = JobNotification.model_validate({**_VALID, "priority": "high"})
        payload = n.payload()
        assert payload["priority"] == "high"
        assert payload["session_id"] == _VALID["session_id"]  # UUID serialised back to str
