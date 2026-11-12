from __future__ import annotations

import os
import time
from datetime import datetime, time as datetime_time, timedelta, timezone
from zoneinfo import ZoneInfo

from src.pipeline import configure_logging, run_daily_pipeline


def next_run(
    now: datetime,
    *,
    timezone_name: str = "Europe/Paris",
    hour: int = 6,
    minute: int = 30,
) -> datetime:
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("L'heure de planification est invalide")
    zone = ZoneInfo(timezone_name)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local_now = now.astimezone(zone)
    scheduled_time = datetime_time(hour=hour, minute=minute)
    scheduled = datetime.combine(
        local_now.date(),
        scheduled_time,
        tzinfo=zone,
    )
    if scheduled <= local_now:
        scheduled = datetime.combine(
            local_now.date() + timedelta(days=1),
            scheduled_time,
            tzinfo=zone,
        )
    return scheduled


def main() -> None:
    timezone_name = os.environ.get(
        "SCHEDULE_TIMEZONE",
        "Europe/Paris",
    )
    hour = int(os.environ.get("SCHEDULE_HOUR", "6"))
    minute = int(os.environ.get("SCHEDULE_MINUTE", "30"))
    logger = configure_logging()

    while True:
        target = next_run(
            datetime.now(timezone.utc),
            timezone_name=timezone_name,
            hour=hour,
            minute=minute,
        )
        delay = max(
            0.0,
            (target - datetime.now(target.tzinfo)).total_seconds(),
        )
        logger.info(
            "next_pipeline_run_scheduled",
            extra={
                "details": {
                    "scheduled_at": target.isoformat(),
                    "timezone": timezone_name,
                    "delay_seconds": int(delay),
                }
            },
        )
        time.sleep(delay)
        result = run_daily_pipeline()
        if result["failed_sources"]:
            logger.error(
                "scheduled_pipeline_has_failures",
                extra={
                    "details": {
                        "failed_sources": result["failed_sources"],
                    }
                },
            )


if __name__ == "__main__":
    main()
