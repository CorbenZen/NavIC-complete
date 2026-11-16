from __future__ import annotations

import argparse
import errno
import unittest
from unittest.mock import patch

from navic_tcp import server_main


def startup_args(api_port: int = 8001) -> argparse.Namespace:
    return argparse.Namespace(
        history_limit=100,
        registry="config/devices.json",
        host="127.0.0.1",
        port=9000,
        dedupe_limit=10000,
        api_host="127.0.0.1",
        api_port=api_port,
    )


class StartupErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_port_conflict_is_actionable_and_closes_tcp_listener(self) -> None:
        class FakeTcpServer:
            closed = False

            async def start(self):
                return None

            async def close(self):
                self.closed = True

        class FakeApiServer:
            async def start(self):
                raise OSError("error while attempting to bind on address ('127.0.0.1', 8001): address already in use")

        tcp = FakeTcpServer()
        with patch.object(server_main, "TelemetryServer", return_value=tcp), patch.object(
            server_main, "TrackingApiServer", return_value=FakeApiServer()
        ) as make_api:
            with self.assertRaisesRegex(
                server_main.StartupError,
                r"Could not start HTTP API at 127\.0\.0\.1:8001: address already in use",
            ):
                await server_main._run(startup_args())
        self.assertTrue(tcp.closed)
        self.assertEqual(make_api.call_args.args[1:], ("127.0.0.1", 8001))

    async def test_tcp_port_conflict_is_actionable(self) -> None:
        class FakeTcpServer:
            async def start(self):
                raise OSError(errno.EADDRINUSE, "Address already in use")

        with patch.object(server_main, "TelemetryServer", return_value=FakeTcpServer()):
            with self.assertRaisesRegex(
                server_main.StartupError,
                r"Could not start TCP server at 127\.0\.0\.1:9000: address already in use",
            ):
                await server_main._run(startup_args())


if __name__ == "__main__":
    unittest.main()
