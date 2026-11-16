import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from navic_tcp.fastapi_app import distance_km, idle_periods, stationary_periods, trip_distance_km, trip_groups


def point(device, minute, lat=13.0, lon=80.0, speed=0.0):
    return SimpleNamespace(device_id=device, timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc)+timedelta(minutes=minute), latitude=lat, longitude=lon, speed=speed, ignition=None)


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

    def test_demo_idle_and_stopped_same_position_fixes_are_finite(self):
        moving = point('demo', 0, lon=80.0, speed=32.0)
        idle = point('demo', 1, lon=80.0, speed=0.0)
        stopped = point('demo', 2, lon=80.0, speed=0.0)
        idle.ignition = True
        stopped.ignition = False
        self.assertEqual(distance_km(idle, stopped), 0)
        self.assertTrue(all(value == value and abs(value) != float('inf') for value in (trip_distance_km([moving, idle, stopped]),)))
        self.assertEqual(len(trip_groups([moving, idle, stopped])), 1)
        self.assertEqual(idle_periods([idle, stopped], minimum_minutes=0), [])

    def test_trip_groups_sort_out_of_order_and_keep_duplicate_times(self):
        late = point('demo', 40, lon=80.02, speed=35)
        early = point('demo', 0, lon=80.0, speed=30)
        duplicate = point('demo', 0, lon=80.0, speed=0)
        middle = point('demo', 2, lon=80.01, speed=0)
        groups = trip_groups([late, duplicate, middle, early])
        self.assertEqual([len(group) for group in groups], [3, 1])
        self.assertEqual([group[0].timestamp for group in groups], [early.timestamp, late.timestamp])

    def test_invalid_coordinates_and_nonfinite_speed_do_not_poison_distance(self):
        good = point('demo', 0)
        corrupt = point('demo', 1, lat=float('nan'), lon=float('inf'), speed=float('nan'))
        self.assertEqual(distance_km(good, corrupt), 0)
        self.assertEqual(trip_distance_km([good, corrupt]), 0)
        self.assertEqual(stationary_periods([good, corrupt]), [])


if __name__=='__main__': unittest.main()
