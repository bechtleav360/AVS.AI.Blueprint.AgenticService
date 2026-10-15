"""DTO: the payload of a ``reading.recorded`` event."""

from pydantic import BaseModel


class ReadingRecorded(BaseModel):
    """One sensor reading, as a site publishes it."""

    sensor_id: str
    value: float
