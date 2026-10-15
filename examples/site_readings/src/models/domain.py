"""Domain models: what ReadingService works with."""

from pydantic import BaseModel


class Reading(BaseModel):
    """One sensor reading."""

    sensor_id: str
    value: float


class Alert(BaseModel):
    """A reading above the threshold that applies to the run."""

    sensor_id: str
    value: float
    threshold: float
    site: str
