"""Tiny read-only HTTP/1.1 JSON API for the in-memory tracking store."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from urllib.parse import parse_qs, unquote, urlsplit

from .store import TelemetryStore

LOG = logging.getLogger("navic_tcp.api")
MAX_HTTP_HEADER_BYTES = 8 * 1024
DEFAULT_HISTORY_LIMIT = 25
MAX_HISTORY_LIMIT = 100


class TrackingApiServer:
    def __init__(self, store: TelemetryStore, host: str = "127.0.0.1", port: int = 8001):
        self.store = store
        self.host = host
        self.port = port
        self._server: asyncio.Server | None = None
        self._writers: set[asyncio.StreamWriter] = set()

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port,
            limit=MAX_HTTP_HEADER_BYTES,
        )
        sockets = self._server.sockets or []
        if sockets:
            bound_host, bound_port = sockets[0].getsockname()[:2]
            LOG.info("HTTP API listening host=%s port=%s", bound_host, bound_port)

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        writers = list(self._writers)
        for writer in writers:
            writer.close()
        if writers:
            await asyncio.gather(*(writer.wait_closed() for writer in writers), return_exceptions=True)
        LOG.info("HTTP API stopped")

    def dispatch(self, method: str, target: str) -> tuple[int, dict]:
        if method != "GET":
            return 405, {"error": {"code": "method_not_allowed", "message": "only GET is supported"}}
        try:
            parsed = urlsplit(target)
            query = parse_qs(parsed.query, max_num_fields=10)
        except ValueError:
            return 400, {"error": {"code": "invalid_request", "message": "request target is invalid"}}

        if parsed.path == "/health":
            return 200, {"status": "ok", "devices": self.store.device_count}
        if parsed.path == "/devices":
            return 200, {"devices": self.store.list_devices()}

        segments = parsed.path.split("/")
        if len(segments) in (3, 4) and segments[1] == "devices" and segments[2]:
            device_id = unquote(segments[2])
            if len(segments) == 3:
                state = self.store.get_device(device_id)
                if state is None:
                    return 404, {"error": {"code": "device_not_found", "message": "device was not found"}}
                return 200, state
            if segments[3] == "history":
                requested = query.get("limit", [str(DEFAULT_HISTORY_LIMIT)])[0]
                try:
                    limit = int(requested)
                except ValueError:
                    return 400, {"error": {"code": "invalid_limit", "message": "limit must be an integer from 1 to 100"}}
                if not 1 <= limit <= MAX_HISTORY_LIMIT:
                    return 400, {"error": {"code": "invalid_limit", "message": "limit must be an integer from 1 to 100"}}
                history = self.store.get_history(device_id, limit)
                if history is None:
                    return 404, {"error": {"code": "device_not_found", "message": "device was not found"}}
                return 200, {"device_id": device_id, "limit": limit, "history": history}

        return 404, {"error": {"code": "not_found", "message": "endpoint was not found"}}

    @staticmethod
    def _response_bytes(status: int, payload: dict) -> bytes:
        reasons = {
            200: "OK",
            400: "Bad Request",
            404: "Not Found",
            405: "Method Not Allowed",
            431: "Request Header Fields Too Large",
        }
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        headers = (
            f"HTTP/1.1 {status} {reasons[status]}\r\n"
            "Content-Type: application/json; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "Cache-Control: no-store\r\n"
            "\r\n"
        ).encode("ascii")
        return headers + body

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.add(writer)
        peer = writer.get_extra_info("peername")
        try:
            try:
                raw = await reader.readuntil(b"\r\n\r\n")
                if len(raw) > MAX_HTTP_HEADER_BYTES:
                    status, payload = 431, {"error": {"code": "headers_too_large", "message": "request headers exceed 8192 bytes"}}
                else:
                    status, payload = self._parse_and_dispatch(raw)
            except asyncio.LimitOverrunError:
                status, payload = 431, {"error": {"code": "headers_too_large", "message": "request headers exceed 8192 bytes"}}
            except asyncio.IncompleteReadError:
                status, payload = 400, {"error": {"code": "invalid_request", "message": "incomplete HTTP request headers"}}
            writer.write(self._response_bytes(status, payload))
            await writer.drain()
            LOG.info("HTTP request peer=%s status=%s", peer, status)
        except (ConnectionError, OSError):
            LOG.info("HTTP client disconnected peer=%s", peer)
        finally:
            self._writers.discard(writer)
            writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()

    def _parse_and_dispatch(self, raw: bytes) -> tuple[int, dict]:
        try:
            lines = raw.decode("ascii").split("\r\n")
        except UnicodeDecodeError:
            return 400, {"error": {"code": "invalid_request", "message": "HTTP headers must be ASCII"}}
        request = lines[0].split(" ")
        if len(request) != 3 or request[2] not in {"HTTP/1.0", "HTTP/1.1"}:
            return 400, {"error": {"code": "invalid_request", "message": "malformed HTTP request line"}}
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if not line:
                break
            if ":" not in line:
                return 400, {"error": {"code": "invalid_request", "message": "malformed HTTP header"}}
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        if headers.get("transfer-encoding", "").lower() not in ("", "identity"):
            return 400, {"error": {"code": "unsupported_body", "message": "request bodies are not supported"}}
        if headers.get("content-length", "0") not in ("", "0"):
            return 400, {"error": {"code": "unsupported_body", "message": "request bodies are not supported"}}
        return self.dispatch(request[0], request[1])
