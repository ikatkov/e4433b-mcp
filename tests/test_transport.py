import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from e4433b_mcp.transport import AR488, Settings


class SerialStub:
    def __init__(self, *args, **kwargs):
        self.buffer = bytearray()
        self.reply = b"Hewlett-Packard, ESG-D4000B, US00000000, B.03.86\n"
        self.writes = []
        self.closed = False

    def write(self, data):
        self.writes.append(data)
        if data == b"++ver real\n":
            self.buffer.extend(b"AR488 GPIB controller, ver. 0.55.22\n")
        elif data == b"++read eoi\n":
            self.buffer.extend(self.reply)
        return len(data)

    def read(self, count):
        n = min(count, len(self.buffer))
        result = bytes(self.buffer[:n])
        del self.buffer[:n]
        return result

    def read_until(self, delimiter):
        end = self.buffer.find(delimiter)
        return self.read(end + 1 if end >= 0 else len(self.buffer))

    def flush(self):
        pass

    def reset_input_buffer(self):
        self.buffer.clear()

    def close(self):
        self.closed = True


@pytest.fixture
def io(monkeypatch):
    monkeypatch.setattr("e4433b_mcp.transport.time.sleep", lambda _: None)
    value = AR488(Settings(timeout=0.002, reset_wait=0))
    value.serial = SerialStub()
    return value


def test_query_has_exactly_one_read_and_write_has_none(io):
    io.query("*IDN?")
    assert io.serial.writes == [b"*IDN?\n", b"++ver real\n", b"++read eoi\n"]
    io.serial.writes.clear()
    io.write("OUTP OFF")
    assert io.serial.writes == [b"OUTP OFF\n", b"++ver real\n"]


@pytest.mark.parametrize("command,is_query", [
    ("*OPT?", True), ("OUTP ON", True), ("FREQ?", False),
    ("++read eoi", False), ("FREQ 750000;OUTP ON", False),
    ("FREQ?\nOUTP ON", True), ("FREQ?;POW?", True), ("X" * 128, False),
])
def test_reject_invalid_commands_before_any_serial_write(io, command, is_query):
    with pytest.raises(ValueError):
        (io.query if is_query else io.write)(command)
    assert io.serial.writes == []


def unescape(data):
    out, escaped = bytearray(), False
    for n in data:
        if n == 27 and not escaped:
            escaped = True
        else:
            out.append(n)
            escaped = False
    assert not escaped
    return bytes(out)


def test_binary_chunks_preserve_all_bytes_and_eoi_only_at_end(io):
    payload = bytes(range(256)) * 3
    prefix = 'MMEM:DATA "ARBI:TEST",'
    io.write_block(prefix, payload)
    chunks, eoi, eos = [], 1, 0
    for line in io.serial.writes:
        if line.startswith(b"++eoi "):
            eoi = int(line.split()[1])
        elif line.startswith(b"++eos "):
            eos = int(line.split()[1])
        elif not line.startswith(b"++"):
            assert line.endswith(b"\n")
            decoded = unescape(line[:-1])
            assert len(decoded) <= 96
            assert eos == 3
            chunks.append((decoded, eoi))
    assert all(flag == 0 for _, flag in chunks[:-1])
    assert chunks[-1][1] == 1
    assert b"".join(c for c, _ in chunks) == prefix.encode() + b"#3768" + payload + b"\n"
    assert io.serial.writes[-2:] == [b"++eoi 1\n", b"++eos 0\n"]


def test_binary_read_is_length_based_not_line_based(io):
    payload = b"\x00\n\r\xff\x1b++" * 10
    size = str(len(payload)).encode()
    io.serial.reply = b"#" + str(len(size)).encode() + size + payload + b"\r\n"
    assert io.read_block('MMEM:DATA? "ARBI:TEST"') == payload
    assert io.serial.buffer == b""


def test_timeout_discards_connection_and_does_not_retry(io):
    serial = io.serial
    serial.reply = b"partial"
    with pytest.raises(TimeoutError), io.transaction():
        io.query("FREQ?")
    assert io.serial is None
    assert serial.closed
    assert serial.writes.count(b"FREQ?\n") == 1


def test_oversized_binary_response_discards_connection(io):
    serial = io.serial
    serial.reply = b"#6100000"
    with pytest.raises(ConnectionError), io.transaction():
        io.read_block('MMEM:DATA? "ARBI:TEST"', max_bytes=100)
    assert serial.closed


def test_truncated_binary_read_reports_count(io):
    io.serial.buffer.extend(b"123")
    with pytest.raises(TimeoutError, match="3/8 bytes"):
        import time
        io._exact(8, time.monotonic() + 0.002)


def test_failed_binary_transfer_clears_partial_command_and_restores_framing(io, monkeypatch):
    def fail():
        raise TimeoutError("No adapter acknowledgment")

    monkeypatch.setattr(io, "_sync", fail)
    with pytest.raises(TimeoutError):
        io.write_block('MMEM:DATA "ARBI:TEST",', b"1234")
    assert io.serial.writes[-3:] == [b"++clr\n", b"++eoi 1\n", b"++eos 0\n"]


def test_transactions_do_not_interleave(io):
    start = threading.Barrier(2)

    def query(command):
        start.wait()
        with io.transaction():
            io.query(command)
            io.query(command)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(query, "FREQ?")
        b = pool.submit(query, "POW?")
        a.result()
        b.result()
    commands = [v for v in io.serial.writes if v in (b"FREQ?\n", b"POW?\n")]
    assert commands in ([b"FREQ?\n"] * 2 + [b"POW?\n"] * 2,
                        [b"POW?\n"] * 2 + [b"FREQ?\n"] * 2)


def test_process_lease_blocks_second_client_and_releases(monkeypatch, tmp_path):
    monkeypatch.setattr("e4433b_mcp.transport.serial.Serial", SerialStub)
    monkeypatch.setattr("e4433b_mcp.transport.time.sleep", lambda _: None)
    config = Settings(port=str(tmp_path / "fake-port"), reset_wait=0)
    first, second = AR488(config), AR488(config)
    try:
        first.connect()
        with pytest.raises(ConnectionError, match="another E4433B MCP"):
            second.connect()
        first.close()
        second.connect()
        assert second.identity.startswith("Hewlett-Packard")
    finally:
        first.close()
        second.close()


def test_identity_mismatch_closes_without_rf_writes(monkeypatch, tmp_path):
    stub = SerialStub()
    stub.reply = b"RIGOL,DS1104Z,OTHER,1.0\n"
    monkeypatch.setattr("e4433b_mcp.transport.serial.Serial", lambda *a, **k: stub)
    monkeypatch.setattr("e4433b_mcp.transport.time.sleep", lambda _: None)
    io = AR488(Settings(port=str(tmp_path / "fake"), reset_wait=0))
    with pytest.raises(ConnectionError, match="Expected E4433B"):
        io.connect()
    assert stub.closed
    assert not any(b"OUTP" in w for w in stub.writes)
