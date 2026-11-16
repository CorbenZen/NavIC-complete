# Telemetry guide

The independent TCP server accepts the existing line-delimited JSON telemetry
protocol. `navic_tcp/protocol.py` frames messages, `navic_tcp/nmea.py` parses
supported NMEA input, and `navic_tcp/server.py` validates and stores accepted
positions through the shared models and database. Keep this protocol stable
for existing device clients.

The website backend can start an embedded receiver through its lifespan. Its
configuration and bridge are in `backend/python_asyncio/tcp/tcp_receiver.py`;
the receiver forwards validated telemetry into the same persistence and
WebSocket broadcast path. The frontend `FleetContext` combines API polling
with the `/ws/locations` stream; `frontend/javascript-services/websocket.js` handles
reconnection.

The independent server and simulator can also be run using the commands in
`docs/TCP_INTEGRATION.md`. Configure device credentials and allowed devices
through the root `.env` and `config/devices.json`. Use
`config/devices.demo.json` only for local demonstrations.

Telemetry fields describe the received GNSS fix and its provenance. The app
does not infer that a receiver is using India's NavIC constellation unless the
device integration supplies verifiable constellation metadata.
