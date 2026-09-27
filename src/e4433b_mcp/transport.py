"""AR488 0.55.22 transport, including its 128-byte serial parser boundary."""

from __future__ import annotations

import fcntl
import hashlib
import logging
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import serial
from serial.tools import list_ports

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    port: str | None = None
    address: int = 30
    expected_serial: str | None = None
    baud: int = 115200
    reset_wait: float = 3.0
    timeout: float = 6.0

    def __post_init__(self):
        if not 0 <= self.address <= 30:
            raise ValueError("GPIB address must be 0–30")

    @classmethod
    def from_env(cls):
        return cls(port=os.getenv("E4433B_PORT") or None,
                   address=int(os.getenv("E4433B_ADDRESS", "30")),
                   expected_serial=os.getenv("E4433B_SERIAL") or None)


def available_adapters():
    """Enumerate USB serial candidates without opening any port."""
    return [{"port": p.device, "description": p.description, "vid": p.vid,
             "pid": p.pid, "serial_number": p.serial_number}
            for p in list_ports.comports() if p.vid is not None]


def choose_port(configured: str | None):
    if configured:
        return configured
    matches = [p["port"] for p in available_adapters()
               if (p["vid"], p["pid"]) == (0x1A86, 0x7523)]
    if len(matches) != 1:
        raise ConnectionError("Expected one CH340 adapter; found " + str(matches) +
                              ". Connect it or set E4433B_PORT explicitly.")
    return matches[0]


class AR488:
    """One persistent connection, one transaction at a time, no automatic write retries.

    The process lock is held until disconnect. A second MCP client gets an
    actionable error instead of interleaving its serial commands with ours.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.lock = threading.RLock()
        self.serial = None
        self._lease = None
        self.port = None
        self.identity = None
        self.adapter_version = None

    @contextmanager
    def transaction(self):
        with self.lock:
            try:
                self.connect()
                yield self
            except (serial.SerialException, OSError, TimeoutError, ConnectionError):
                # A delayed/partial response must never become the next query's reply.
                self.close()
                raise

    def connect(self):
        if self.serial is not None:
            return
        self.port = choose_port(self.settings.port)
        # tty/callout aliases on macOS must share the same lease.
        key = os.path.realpath(self.port).replace("/dev/tty.", "/dev/cu.")
        digest = hashlib.sha256(key.encode()).hexdigest()[:20]
        lease_path = Path(tempfile.gettempdir()) / f"e4433b-{os.getuid()}-{digest}.lock"
        self._lease = lease_path.open("a+")
        try:
            try:
                fcntl.flock(self._lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ConnectionError("Adapter is in use by another E4433B MCP client. "
                                      "Call disconnect there, or close that client.") from exc
            self.serial = serial.Serial(self.port, self.settings.baud, timeout=0.1,
                                        write_timeout=5, exclusive=True)
            time.sleep(self.settings.reset_wait)
            self.serial.reset_input_buffer()
            self._adapter("++ver real")
            self.adapter_version = self._line().decode("ascii").strip()
            if not self.adapter_version.startswith("AR488 GPIB controller"):
                raise ConnectionError(f"Not the expected AR488 adapter: {self.adapter_version!r}")
            log.info("Adapter responded on %s: %s", self.port, self.adapter_version)
            for cmd in ["++mode 1", f"++addr {self.settings.address}", "++auto 0",
                        "++idn 0", "++eoi 1", "++eos 0", "++eot_enable 0",
                        "++read_tmo_ms 3000"]:
                self._adapter(cmd)
            self.identity = self.query("*IDN?")
            parts = [p.strip() for p in self.identity.split(",")]
            if len(parts) < 4 or parts[1].upper() not in {"ESG-D4000B", "E4433B"}:
                raise ConnectionError(f"Expected E4433B/ESG-D4000B, received {self.identity!r}")
            if self.settings.expected_serial and parts[2] != self.settings.expected_serial:
                raise ConnectionError(f"Wrong instrument serial number: {parts[2]}")
            log.info("Connected to %s on %s", self.identity, self.port)
        except BaseException:
            self.close()
            raise

    def close(self):
        with self.lock:
            try:
                if self.serial is not None:
                    self.serial.close()
            finally:
                self.serial = None
                self.identity = None
                if self._lease is not None:
                    self._lease.close()
                    self._lease = None

    def _adapter(self, command: str):
        self.serial.write(command.encode("ascii") + b"\n")
        self.serial.flush()
        time.sleep(0.015)

    def _line(self):
        data = bytearray()
        deadline = time.monotonic() + self.settings.timeout
        while time.monotonic() < deadline and len(data) < 65536:
            data.extend(self.serial.read_until(b"\n"))
            if data.endswith(b"\n"):
                return bytes(data)
        raise TimeoutError(f"No complete reply from GPIB address {self.settings.address}; "
                           f"received {bytes(data[:120])!r}. No command was retried.")

    def _sync(self):
        self._adapter("++ver real")
        try:
            reply = self._line()
        except TimeoutError as exc:
            raise TimeoutError("AR488 did not acknowledge completion of the GPIB write. "
                               "The adapter may be waiting on the instrument handshake; "
                               "check instrument power, GPIB connection, and address. "
                               "No command was retried.") from exc
        if not reply.startswith(b"AR488 GPIB controller"):
            raise ConnectionError("Unexpected adapter response; serial stream is out of sync")

    @staticmethod
    def _validate_ascii(command, query):
        if (not command or len(command.encode("ascii")) >= 128 or
                any(ord(c) < 32 or ord(c) > 126 for c in command) or
                ";" in command or command.startswith("++")):
            raise ValueError("Only one short, printable SCPI command is allowed")
        if command.count("?") != int(query):
            raise ValueError("Queries and writes must use separate transport methods")
        if command.strip().upper() == "*OPT?":
            raise ValueError("E4433B uses DIAG:INFO:OPT?, not *OPT?")

    def write(self, command):
        self._validate_ascii(command, query=False)
        self._adapter(command)
        self._sync()

    def query(self, command):
        self._validate_ascii(command, query=True)
        self._adapter(command)
        self._sync()
        self._adapter("++read eoi")
        try:
            return self._line().decode("ascii").strip()
        except TimeoutError as exc:
            raise TimeoutError(f"Query {command!r} timed out: {exc}") from exc

    def _exact(self, count, deadline):
        data = bytearray()
        while len(data) < count and time.monotonic() < deadline:
            data.extend(self.serial.read(count - len(data)))
        if len(data) != count:
            raise TimeoutError(f"Binary response incomplete: {len(data)}/{count} bytes")
        return bytes(data)

    def read_block(self, command, max_bytes=2_097_152):
        self._validate_ascii(command, query=True)
        self._adapter(command)
        self._sync()
        self._adapter("++read eoi")
        deadline = time.monotonic() + self.settings.timeout
        if self._exact(1, deadline) != b"#":
            raise ConnectionError("Expected a SCPI definite-length binary block")
        digit = self._exact(1, deadline)
        if digit not in b"123456789":
            raise ConnectionError("Invalid binary block length header")
        size_bytes = self._exact(int(digit), deadline)
        if not size_bytes.isdigit():
            raise ConnectionError("Non-numeric binary block size")
        count = int(size_bytes)
        if count > max_bytes:
            raise ConnectionError(f"Binary response exceeds limit ({count} bytes)")
        # This Nano's GPIB reads are slower than the nominal USB serial bitrate.
        deadline = time.monotonic() + max(30, count / 1000 + 10)
        data = self._exact(count, deadline)
        tail = self.serial.read(2)
        if tail.strip(b"\r\n"):
            raise ConnectionError(f"Unexpected binary block suffix: {tail!r}")
        return data

    @staticmethod
    def escape(data):
        return b"".join((b"\x1b" + bytes([b])) if b in (10, 13, 27, 43)
                        else bytes([b]) for b in data)

    def write_block(self, prefix, data):
        self._validate_ascii(prefix, query=False)
        size = str(len(data)).encode("ascii")
        packet = prefix.encode("ascii") + b"#" + str(len(size)).encode() + size + data + b"\n"
        self._adapter("++eos 3")
        self._adapter("++eoi 0")
        try:
            for start in range(0, len(packet), 96):
                chunk = packet[start:start + 96]
                if start + len(chunk) == len(packet):
                    self._adapter("++eoi 1")
                self.serial.write(self.escape(chunk) + b"\n")
                self.serial.flush()
                self._sync()
                if start % 9600 == 0:
                    log.info("Waveform transfer: %s/%s bytes", start, len(packet))
        except BaseException:
            try:
                self._adapter("++clr")
            except Exception:
                log.exception("Could not clear incomplete waveform transfer")
            raise
        finally:
            self._adapter("++eoi 1")
            self._adapter("++eos 0")

    def local(self):
        self._adapter("++loc")
        self._sync()
