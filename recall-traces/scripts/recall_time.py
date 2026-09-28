from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class TimeWindow:
    start: datetime
    end: datetime

    def __post_init__(self):
        if self.start.utcoffset() is None or self.end.utcoffset() is None:
            raise ValueError('Time boundaries need explicit timezone offsets.')
        if self.start >= self.end:
            raise ValueError('Time window start must be before end.')

    @classmethod
    def parse(cls, start, end):
        return cls(datetime.fromisoformat(start), datetime.fromisoformat(end))

    @classmethod
    def past(cls, days):
        end = datetime.now(timezone.utc)
        return cls(end - timedelta(days=days), end)

    @classmethod
    def around(cls, time, seconds):
        point = datetime.fromisoformat(time)
        if seconds <= 0:
            raise ValueError('Seconds must be positive on each side of the time.')
        try:
            radius = timedelta(seconds=seconds)
            return cls(point - radius, point + radius)
        except OverflowError as error:
            raise ValueError('Time window exceeds the supported datetime range.') from error

    def contains(self, moment):
        return self.start <= moment < self.end

    def parameters(self):
        return {'start': self.start.isoformat(), 'end': self.end.isoformat()}
