import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from navic_tcp.fastapi_app import distance_km, stationary_periods


def point(device, minute, lat=13.0, lon=80.0, speed=0.0):
    return SimpleNamespace(device_id=device, timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc)+timedelta(minutes=minute), latitude=lat, longitude=lon, speed=speed)


class ReportingServiceTests(unittest.TestCase):
    def test_haversine_distance_is_in_kilometres(self):
        a=point('d',0,0,0); b=point('d',0,0,1)
        self.assertAlmostEqual(distance_km(a,b),111.19,delta=.2)

    def test_stationary_period_requires_elapsed_duration(self):
        found=stationary_periods([point('d',0),point('d',2),point('d',6)])
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]['duration_minutes'],6)

    def test_stationary_period_breaks_on_gap_and_movement(self):
        found=stationary_periods([point('d',0),point('d',1),point('d',10),point('d',11,speed=8)])
        self.assertEqual(found,[])

    def test_stationary_period_keeps_devices_separate(self):
        found=stationary_periods([point('a',0),point('b',6)])
        self.assertEqual(found,[])


if __name__=='__main__': unittest.main()
