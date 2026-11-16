# TCP integration

`navic_tcp/` is a root-level, standalone client/server application. Its wire
protocol remains newline-delimited JSON; the website integration adapts to it
without moving or duplicating that protocol.

The website backend can start its configured TCP receiver during FastAPI
startup. `backend/python_asyncio/tcp/tcp_receiver.py` handles the asynchronous
client side and forwards accepted telemetry into the existing storage and
live-update pipeline. The standalone server entry point remains
`navic_tcp.server_main` and the client/simulator is `navic_tcp.client_main`.

From the repository root, with backend dependencies installed:

```bash
python -m navic_tcp.server_main --host 127.0.0.1 --port 9000 --api-host 127.0.0.1 --api-port 8001
python -m navic_tcp.client_main --host 127.0.0.1 --port 9000 --devices 3 --count 10 --interval 1
```

The HTTP API on port 8001 is for the independent tracking application. The
website FastAPI service defaults to port 8000 and can embed its receiver.
Configure allowed device IDs/secrets before connecting production devices.
Tests in root `tests/` cover protocol parsing, server/client communication and
storage/API behavior; `backend/tests/test_backend_app.py` covers the website
bridge adapter.
