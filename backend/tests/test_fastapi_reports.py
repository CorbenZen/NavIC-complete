import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from navic_tcp import fastapi_app as api
from navic_tcp.db import Base
from navic_tcp.models import (
    Alert,
    Bus,
    DeviceGeofenceState,
    Driver,
    Geofence,
    LocationHistory,
    Route,
    TrackingDevice,
)
from navic_tcp.registry import DeviceRegistry


class FastApiReportTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.factory=sessionmaker(bind=self.engine,autoflush=False,expire_on_commit=False)
        self.patch=patch.object(api,'SessionLocal',self.factory);self.patch.start()
        with self.factory() as db:
            driver=Driver(name='Test Driver',email='driver@example.invalid',license_number='TEST-LIC')
            bus=Bus(vehicle_id='TEST-01',registration_number='TEST-01',driver=driver)
            device=TrackingDevice(device_id='TEST_DEVICE',bus=bus)
            db.add(bus);db.flush()
            start=datetime.now(timezone.utc)-timedelta(minutes=6)
            for ix in range(4):
                db.add(LocationHistory(device_id=device.device_id,message_id=f'00000000-0000-0000-0000-{ix+1:012d}',timestamp=start+timedelta(minutes=ix*2),latitude=13.0,longitude=80.0+ix*.001,speed=0,course=0,simulated=False))
            db.commit()

    def tearDown(self):
        self.patch.stop();self.engine.dispose()

    def test_dashboard_counts_database_vehicles_without_duplicate_history_count(self):
        result=api.dashboard_stats()
        self.assertEqual(result['all'],1)
        self.assertEqual(result['stopped'],1)
        self.assertEqual(result['out_of_network'],0)
        self.assertEqual(result['total_drivers'],1)

    def test_stoppage_report_measures_duration_not_single_low_speed_fixes(self):
        result=api.report_data('stoppage',limit=20,offset=0)
        self.assertEqual(result['count'],1)
        self.assertEqual(result['data'][0]['duration_minutes'],6)

    def test_kilometres_use_geodesic_segments(self):
        result=api.report_data('km',limit=20,offset=0)
        self.assertGreater(result['data'][0]['distance_km'],0)
        self.assertEqual(result['data'][0]['records'],4)

    def test_idle_is_explicitly_unsupported_without_ignition(self):
        result=api.report_data('idle',limit=20,offset=0)
        self.assertEqual(result['data'],[])
        self.assertFalse(result['rules']['supported'])

    def test_bad_report_and_date_range_return_client_errors(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as bad:api.report_data('not-a-report',limit=10,offset=0)
        self.assertEqual(bad.exception.status_code,404)
        with self.assertRaises(HTTPException) as date:api.report_data('history',start_date=datetime(2026,2,1),end_date=datetime(2026,1,1),limit=10,offset=0)
        self.assertEqual(date.exception.status_code,422)

    def test_mixed_timezone_date_ranges_compare_as_utc(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as reversed_range:
            api.report_data(
                'history',
                start_date=datetime(2026, 1, 1, 1, tzinfo=timezone(timedelta(hours=-2))),
                end_date=datetime(2026, 1, 1),
                limit=10,
                offset=0,
            )
        self.assertEqual(reversed_range.exception.status_code, 422)
        result = api.report_data(
            'history',
            start_date=datetime(2025, 12, 31, 22),
            end_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
            limit=10,
            offset=0,
        )
        self.assertGreaterEqual(result['count'], 0)

    def test_server_error_handler_logs_traceback_and_returns_reference(self):
        from starlette.requests import Request

        from backend.python_fastapi.application.main import app as web_app

        request = Request({
            'type': 'http',
            'http_version': '1.1',
            'method': 'GET',
            'scheme': 'http',
            'path': '/_test/error',
            'raw_path': b'/_test/error',
            'query_string': b'',
            'headers': [],
            'client': ('127.0.0.1', 1),
            'server': ('127.0.0.1', 8000),
        })
        handler = web_app.exception_handlers[Exception]
        with self.assertLogs('navic.backend', level='ERROR') as captured:
            try:
                raise RuntimeError('private traceback detail')
            except RuntimeError as error:
                response = asyncio.run(handler(request, error))

        payload = json.loads(response.body)
        reference_id = payload['reference_id']
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers['x-error-reference'], reference_id)
        self.assertRegex(reference_id, r'^[0-9a-f]{8}$')
        self.assertNotIn('private traceback detail', response.body.decode())
        log_text = '\n'.join(captured.output)
        self.assertIn(reference_id, log_text)
        self.assertIn('private traceback detail', log_text)
        self.assertIn('Traceback', log_text)

    def test_simulator_fix_patterns_are_safe_for_trip_and_all_report_calculations(self):
        """Exercise moving, idle, stopped, duplicate-time, out-of-order, and long-gap demo fixes."""
        base = datetime.now(timezone.utc) - timedelta(hours=3)
        fixtures = [
            (4, 13.004, 80.004, 34.0, True),  # inserted first; sorts after the earlier points
            (0, 13.000, 80.000, 32.0, True),
            (1, 13.000, 80.000, 0.0, True),   # idle at an unchanged location
            (1, 13.000, 80.000, 0.0, False),  # equal timestamp, stopped at the same location
            (2, 13.001, 80.001, 29.0, True),
            (45, 13.020, 80.020, 35.0, True), # >30-minute gap starts a new trip
        ]
        with self.factory() as db:
            for index, (minutes, latitude, longitude, speed, ignition) in enumerate(fixtures):
                db.add(LocationHistory(
                    device_id='TEST_DEVICE',
                    message_id=f'00000000-0000-0000-0000-{1000 + index:012d}',
                    timestamp=base + timedelta(minutes=minutes),
                    latitude=latitude,
                    longitude=longitude,
                    speed=speed,
                    course=0.0,
                    ignition=ignition,
                    simulated=True,
                    data_source='simulator',
                ))
            db.commit()

        trips = api.report_endpoint('trip', limit=100, offset=0, user={'role': 'admin'})
        simulated = [trip for trip in trips['data'] if trip.get('simulated')]
        self.assertEqual(len(simulated), 2)
        self.assertTrue(all(trip['data_sources'] == ['simulator'] for trip in simulated))
        for report_type in sorted(api.REPORT_TYPES):
            result = api.report_endpoint(report_type, limit=100, offset=0, user={'role': 'admin'})
            json.dumps(result, allow_nan=False)

    def test_degenerate_trip_endpoints_return_serializable_results(self):
        result = api.list_trips(limit=100, offset=0, user={'role': 'admin'})
        json.dumps(result, allow_nan=False)

    def test_vehicle_and_driver_crud_use_existing_database(self):
        driver_post=next(r.endpoint for r in api.app.routes if getattr(r,'path',None)=='/drivers' and 'POST' in getattr(r,'methods',set()))
        driver=driver_post(api.DriverIn(name='New Driver',email='new@example.invalid',phone='5550100',license_number='NEW-LIC'),{'id':1})
        bus=api.create_bus(api.BusIn(vehicle_id='NEW-01',registration_number='NEW-01',driver_id=driver.id),{'id':1})
        with self.factory() as db:
            saved=db.get(Bus,bus.id)
            self.assertEqual(saved.driver.email,'new@example.invalid')

    def test_bus_api_serializes_actual_driver_route_and_device_relationships(self):
        with self.factory() as db:
            driver=db.scalar(select(Driver));bus=db.scalar(select(Bus));device=db.scalar(select(TrackingDevice))
            route=Route(name='North Route',identifier='NORTH',start_point='Campus',destination='North Gate');db.add(route);db.flush()
            bus.driver_id=driver.id;bus.route_id=route.id;device.bus_id=bus.id;db.commit();bus_id=bus.id
        row=next(item for item in api.buses({'role':'admin'}) if item.id==bus_id)
        self.assertEqual((row.driver_id,row.driver_name),(driver.id,driver.name))
        self.assertEqual((row.route_id,row.route_name),(route.id,'North Route'))
        self.assertEqual(row.device_id,'TEST_DEVICE')
        self.assertEqual((row.bus_identifier,row.registration),(row.vehicle_id,row.registration_number))

    def test_bus_crud_assigns_and_clears_real_route_and_device_records(self):
        with self.factory() as db:
            driver=db.scalar(select(Driver));route=Route(name='South Route',identifier='SOUTH');db.add(route);db.flush()
            device=db.scalar(select(TrackingDevice));driver_id,route_id,device_id=driver.id,route.id,device.device_id;db.commit()
        created=api.create_bus(api.BusIn(vehicle_id='REL-01',registration_number='REL-01',driver_id=driver_id,route_id=route_id,device_id=device_id),{'role':'admin'})
        self.assertEqual((created.driver_name,created.route_name,created.device_id),('Test Driver','South Route',device_id))
        updated=api.update_bus(created.id,api.BusIn(vehicle_id='REL-01',registration_number='REL-01',driver_id=None,route_id=None,device_id=None),{'role':'admin'})
        self.assertEqual((updated.driver_name,updated.route_name,updated.device_id),('Unassigned','Unassigned',None))
        api.delete_bus(created.id,{'role':'admin'})

    def test_development_auth_never_creates_a_synthetic_admin(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as unauthorized:
            api.current_user(None)
        self.assertEqual(unauthorized.exception.status_code,401)
        with self.assertRaises(HTTPException) as forbidden:
            api.management_user({'role':'student'})
        self.assertEqual(forbidden.exception.status_code,403)

    def test_demo_bypass_requires_both_development_mode_and_explicit_flag(self):
        from unittest.mock import patch
        with patch.dict('os.environ', {'DEMO_AUTH_BYPASS': 'true'}), patch.object(api, 'DEVELOPMENT_MODE', False):
            self.assertFalse(api.demo_auth_bypass_enabled())
        with patch.dict('os.environ', {'DEMO_AUTH_BYPASS': 'true'}), patch.object(api, 'DEVELOPMENT_MODE', True):
            self.assertTrue(api.demo_auth_bypass_enabled())
        old = api.DEMO_AUTH_BYPASS
        try:
            api.DEMO_AUTH_BYPASS = True
            self.assertEqual(api.current_user(None)['username'], 'demo')
        finally:
            api.DEMO_AUTH_BYPASS = old

    def test_device_crud_updates_and_removes_tcp_registration(self):
        old=api.registry;api.registry=DeviceRegistry([])
        try:
            with self.factory() as db:bus_id=db.scalar(select(Bus.id))
            made=api.create_device(api.DeviceIn(device_id='CRUD_DEVICE',device_type='IVTD',identifier_type='serial',bus_id=bus_id),{'id':1})
            self.assertIn('CRUD_DEVICE',api.registry.device_ids)
            changed=api.update_device(made.id,api.DeviceIn(device_id='CRUD_DEVICE_2',device_type='IVTD',identifier_type='serial',bus_id=bus_id),{'id':1})
            self.assertEqual(changed.device_id,'CRUD_DEVICE_2')
            self.assertNotIn('CRUD_DEVICE',api.registry.device_ids)
            self.assertIn('CRUD_DEVICE_2',api.registry.device_ids)
            api.delete_device(made.id,{'id':1})
            self.assertNotIn('CRUD_DEVICE_2',api.registry.device_ids)
        finally:api.registry=old

    def test_alert_can_be_marked_read(self):
        with self.factory() as db:
            row=Alert(event_type='overspeed',message='test alert',device_id='TEST_DEVICE',is_read=False);db.add(row);db.commit();alert_id=row.id
        self.assertTrue(api.mark_alert_read(alert_id,{'id':1})['is_read'])

    def test_offline_alert_uses_stale_fix_rule_and_cooldown(self):
        now=datetime.now(timezone.utc)
        with self.factory() as db:
            points=db.scalars(select(LocationHistory).where(LocationHistory.device_id=='TEST_DEVICE')).all()
            for index,point in enumerate(points):point.timestamp=now-timedelta(minutes=7+index)
            db.commit()
            self.assertEqual(api.create_offline_alerts(db,now),1)
            self.assertEqual(api.create_offline_alerts(db,now+timedelta(minutes=10)),0)
            self.assertEqual(api.create_offline_alerts(db,now+timedelta(minutes=31)),1)
            self.assertEqual(db.query(Alert).filter(Alert.event_type=='device_offline').count(),2)

    def test_tcp_registry_contains_database_devices_after_sync(self):
        old=api.registry;test_registry=DeviceRegistry([])
        try:
            api.ensure_registry(test_registry)
            self.assertIn('TEST_DEVICE',test_registry.device_ids)
        finally: api.registry=old

    def test_accepted_telemetry_persists_and_broadcasts(self):
        from unittest.mock import AsyncMock
        async def run():
            sender=AsyncMock();original=api.hub.publish;api.hub.publish=sender
            try:
                msg={'device_id':'TEST_DEVICE','message_id':'00000000-0000-0000-0000-999999999999','timestamp':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'latitude':13.1,'longitude':80.2,'speed':12,'course':90,'simulated':False}
                await api.on_telemetry(msg);sender.assert_awaited_once()
                self.assertEqual(api.devices()['devices'][0]['latest']['message_id'],msg['message_id'])
            finally:api.hub.publish=original
        asyncio.run(run())

    def test_gnss_metadata_is_persisted_and_broadcast(self):
        from unittest.mock import AsyncMock
        async def run():
            sender=AsyncMock();original=api.hub.publish;api.hub.publish=sender
            try:
                msg={'device_id':'TEST_DEVICE','message_id':'00000000-0000-0000-0000-999999999997','timestamp':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'latitude':13.1,'longitude':80.2,'speed':12,'course':90,'simulated':False,'gnss':{'fix_valid':True,'altitude_m':45.5,'satellites_in_view':9,'satellites_used':6,'hdop':0.8,'constellations':['gps','navic'],'satellites':[{'constellation':'navic','satellite_id':1,'cn0_db_hz':38}]}}
                await api.on_telemetry(msg)
                self.assertEqual(sender.await_args.args[0]['gnss']['constellations'],['gps','navic'])
            finally:api.hub.publish=original
        asyncio.run(run())
        with self.factory() as db:
            point=db.scalar(select(LocationHistory).where(LocationHistory.message_id=='00000000-0000-0000-0000-999999999997'))
            self.assertEqual(point.fix_valid,True);self.assertEqual(point.satellites_used,6);self.assertEqual(point.gnss_metadata['satellites'][0]['constellation'],'navic')
        device=api.devices()['devices'][0]
        self.assertEqual(device['latest']['gnss']['constellations'],['gps','navic'])
        self.assertEqual(device['gnss_compatibility']['navic'],'unsupported_or_unverified')

    def test_telemetry_generates_overspeed_and_geofence_alerts(self):
        with self.factory() as db:
            fence=Geofence(name='Campus Test',latitude=13.0,longitude=80.0,radius_m=100,active=True)
            db.add(fence);db.flush();db.add(DeviceGeofenceState(device_id='TEST_DEVICE',geofence_id=fence.id,inside=False,consecutive_inside=0,consecutive_outside=1));db.commit()
        async def run():
            from unittest.mock import AsyncMock
            sender=AsyncMock();old=api.hub.publish;api.hub.publish=sender
            try:
                # First fix inside geofence (consecutive_inside=1)
                msg1={'device_id':'TEST_DEVICE','message_id':'00000000-0000-0000-0000-999999999998','timestamp':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'latitude':13.0,'longitude':80.0,'speed':100,'course':90,'simulated':False}
                await api.on_telemetry(msg1)
                # Second fix inside geofence (consecutive_inside=2 -> triggers entry)
                msg2={'device_id':'TEST_DEVICE','message_id':'00000000-0000-0000-0000-999999999999','timestamp':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),'latitude':13.0,'longitude':80.0,'speed':100,'course':90,'simulated':False}
                await api.on_telemetry(msg2)
            finally:api.hub.publish=old
        asyncio.run(run())
        with self.factory() as db:
            types=set(db.query(Alert.event_type).all())
            self.assertIn(('overspeed',),types);self.assertIn(('geofence_entry',),types)


if __name__=='__main__':unittest.main()
