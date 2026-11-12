from datetime import datetime, timezone

import pytest

from src.scheduler import next_run


def test_next_run_uses_the_next_local_0630():
    now = datetime(2026, 11, 12, 4, 0, tzinfo=timezone.utc)

    scheduled = next_run(now)

    assert scheduled.isoformat() == "2026-11-12T06:30:00+01:00"


def test_next_run_moves_to_tomorrow_after_scheduled_time():
    now = datetime(2026, 11, 12, 6, 0, tzinfo=timezone.utc)

    scheduled = next_run(now)

    assert scheduled.isoformat() == "2026-11-13T06:30:00+01:00"


def test_next_run_rejects_invalid_time():
    with pytest.raises(ValueError):
        next_run(datetime.now(timezone.utc), hour=24)
