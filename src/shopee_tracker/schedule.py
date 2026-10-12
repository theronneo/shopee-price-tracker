"""Daily checks at noon in Singapore, independent of the computer's timezone."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

SINGAPORE = ZoneInfo("Asia/Singapore")


def next_noon(timestamp: int) -> int:
    """Return the first Singapore noon strictly after the supplied timestamp."""
    now = datetime.fromtimestamp(timestamp, SINGAPORE)
    noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
    if noon <= now:
        noon += timedelta(days=1)
    return int(noon.timestamp())
