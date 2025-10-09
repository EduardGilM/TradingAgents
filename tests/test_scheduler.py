import unittest
from datetime import datetime, time

import pytz

from tradingagents.scheduler import parse_schedule_times, next_run_after


class SchedulerUtilsTest(unittest.TestCase):
    def test_parse_schedule_times(self):
        result = parse_schedule_times("09:00, 15:30, 06:45")
        self.assertEqual(result, [time(6, 45), time(9, 0), time(15, 30)])

    def test_next_run_after_same_day(self):
        tz = pytz.timezone("Europe/Madrid")
        now = tz.localize(datetime(2025, 9, 30, 8, 0))
        run_time = time(9, 30)
        next_run = next_run_after(now, run_time, tz)
        self.assertEqual(next_run, tz.localize(datetime(2025, 9, 30, 9, 30)))

    def test_next_run_after_next_day(self):
        tz = pytz.timezone("Europe/Madrid")
        now = tz.localize(datetime(2025, 9, 30, 20, 0))
        run_time = time(9, 30)
        next_run = next_run_after(now, run_time, tz)
        self.assertEqual(next_run, tz.localize(datetime(2025, 10, 1, 9, 30)))


if __name__ == "__main__":
    unittest.main()
