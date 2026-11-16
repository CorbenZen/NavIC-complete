import unittest

from sqlalchemy import create_engine, inspect, text

from navic_tcp.client import simulated_telemetry
from navic_tcp.nmea import NmeaDecoder, NmeaError
from navic_tcp.protocol import MessageError, decode_telemetry
from navic_tcp.schema import ensure_bus_route_schema, ensure_gnss_schema


def sentence(body):
    checksum=0
    for char in body:checksum^=ord(char)
    return f'${body}*{checksum:02X}'


class NmeaDecoderTests(unittest.TestCase):
    def test_gps_gga_reports_fix_altitude_used_satellites_and_hdop(self):
        result=NmeaDecoder().feed(sentence('GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,'))
        self.assertTrue(result['fix_valid'])
        self.assertAlmostEqual(result['latitude'],48.1173,places=4)
        self.assertAlmostEqual(result['longitude'],11.516666,places=4)
        self.assertEqual(result['satellites_used'],8)
        self.assertAlmostEqual(result['altitude_m'],545.4)
        self.assertEqual(result['hdop'],0.9)
        self.assertIsNone(result['timestamp'])
        self.assertEqual(result['time_utc'],'12:35:19.000Z')
        self.assertEqual(result['constellations'],['gps'])

    def test_navic_talker_gsv_reports_view_and_signal_without_claiming_fix(self):
        result=NmeaDecoder().feed(sentence('GIGSV,1,1,01,01,40,083,42,1'))
        self.assertEqual(result['satellites_in_view'],1)
        self.assertEqual(result['satellites'][0]['constellation'],'navic')
        self.assertEqual(result['satellites'][0]['cn0_db_hz'],42)
        self.assertIsNone(result['fix_valid'])

    def test_gns_mode_reports_only_constellations_present_in_receiver_mode(self):
        result=NmeaDecoder().feed(sentence('GNGNS,123519,4807.038,N,01131.000,E,ADANNN,08,0.9,545.4,46.9,,'))
        self.assertTrue(result['fix_valid'])
        self.assertEqual(result['constellations'],[])
        self.assertEqual(result['mode_indicator'],'ADANNN')
        self.assertEqual(result['satellites_used'],8)

    def test_rmc_and_vtg_parse_utc_speed_and_course(self):
        decoder=NmeaDecoder()
        result=decoder.feed(sentence('GNRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W'))
        self.assertEqual(result['timestamp'],'1994-03-23T12:35:19.000Z')
        self.assertAlmostEqual(result['speed_kmh'],22.4*1.852)
        self.assertEqual(result['course'],84.4)
        result=decoder.feed(sentence('GNVTG,054.7,T,034.4,M,005.5,N,010.2,K,A'))
        self.assertEqual(result['course'],54.7)
        self.assertEqual(result['speed_kmh'],10.2)

    def test_gsa_pdop_and_system_id_6_identifies_navic(self):
        result=NmeaDecoder().feed(sentence('GNGSA,A,3,,,,,,,,,,,,,1.8,1.0,1.5,6'))
        self.assertEqual(result['pdop'],1.8)
        self.assertEqual(result['constellations'],['navic'])

    def test_missing_satellite_sentences_remain_unavailable(self):
        result=NmeaDecoder().feed(sentence('GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,'))
        self.assertIsNone(result['satellites_in_view'])
        self.assertEqual(result['satellites'],[])

    def test_invalid_fix_and_invalid_coordinates_are_not_presented_as_valid(self):
        result=NmeaDecoder().feed(sentence('GPGGA,123519,,,,,0,00,99.9,,,,,,'))
        self.assertFalse(result['fix_valid'])
        with self.assertRaises(NmeaError):
            NmeaDecoder().feed(sentence('GPGGA,123519,9100.000,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,'))

    def test_bad_checksum_is_rejected(self):
        with self.assertRaises(NmeaError):NmeaDecoder().feed('$GPGGA,123519,,,,,0,00,99.9,,,,,,*00')

    def test_existing_gps_json_without_gnss_metadata_remains_valid(self):
        packet=simulated_telemetry('SIM-IMEI-000000000001',1)
        parsed=decode_telemetry(__import__('json').dumps(packet).encode())
        self.assertNotIn('gnss',parsed)

    def test_json_metadata_is_validated_and_invalid_fix_rejected(self):
        import json
        packet=simulated_telemetry('SIM-IMEI-000000000001',1)
        packet['gnss']={'fix_valid':True,'satellites_in_view':7,'satellites_used':4,'hdop':0.8,'constellations':['gps','navic'],'satellites':[{'constellation':'navic','satellite_id':1,'cn0_db_hz':37}]}
        self.assertEqual(decode_telemetry(json.dumps(packet).encode())['gnss']['constellations'],['gps','navic'])
        packet['gnss']['fix_valid']=False
        with self.assertRaises(MessageError) as error:decode_telemetry(json.dumps(packet).encode())
        self.assertEqual(error.exception.code,'no_fix')
        packet['gnss']={'constellations':['india']}
        with self.assertRaises(MessageError):decode_telemetry(json.dumps(packet).encode())

    def test_nmea_metadata_can_be_carried_by_existing_json_protocol(self):
        import json
        decoder=NmeaDecoder()
        decoder.feed(sentence('GIGSV,1,1,01,01,40,083,42,1'))
        packet=simulated_telemetry('SIM-IMEI-000000000001',1)
        packet['gnss']=decoder.protocol_metadata()
        parsed=decode_telemetry(json.dumps(packet).encode())
        satellite=parsed['gnss']['satellites'][0]
        self.assertEqual(satellite['constellation'],'navic')
        self.assertEqual(satellite['signal_id'],'1')

    def test_additive_migration_preserves_existing_location_rows(self):
        engine=create_engine('sqlite://')
        try:
            with engine.begin() as connection:
                connection.execute(text('CREATE TABLE location_history (id INTEGER PRIMARY KEY, latitude FLOAT)'))
                connection.execute(text('INSERT INTO location_history (id, latitude) VALUES (1, 13.05)'))
            ensure_gnss_schema(engine)
            columns={c['name'] for c in inspect(engine).get_columns('location_history')}
            self.assertTrue({'altitude_m','fix_valid','satellites_in_view','satellites_used','pdop','hdop','vdop','gnss_metadata'}<=columns)
            with engine.connect() as connection:self.assertEqual(connection.execute(text('SELECT latitude FROM location_history WHERE id=1')).scalar(),13.05)
        finally:engine.dispose()

    def test_bus_route_migration_preserves_existing_bus_rows(self):
        engine=create_engine('sqlite://')
        try:
            with engine.begin() as connection:
                connection.execute(text('CREATE TABLE routes (id INTEGER PRIMARY KEY)'))
                connection.execute(text('CREATE TABLE buses (id INTEGER PRIMARY KEY, vehicle_id VARCHAR(64))'))
                connection.execute(text("INSERT INTO buses (id, vehicle_id) VALUES (1, 'KEEP-ME')"))
            ensure_bus_route_schema(engine)
            self.assertIn('route_id',{c['name'] for c in inspect(engine).get_columns('buses')})
            with engine.connect() as connection:self.assertEqual(connection.execute(text('SELECT vehicle_id FROM buses WHERE id=1')).scalar(),'KEEP-ME')
        finally:engine.dispose()


if __name__=='__main__':unittest.main()
