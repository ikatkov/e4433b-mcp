import struct
import threading
import wave
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from e4433b_mcp.driver import ARB, BASIC, E4433B, FULL, InstrumentError, parse_catalog
from e4433b_mcp.waveforms import sample_data, voice_iq


class FakeInstrument:
    def __init__(self):
        self.values = {command: "0" for command, _ in (BASIC | FULL | ARB).values()}
        self.values.update({"*IDN?": "Hewlett-Packard,ESG-D4000B,US00000000,B.03.86",
                            "DIAG:INFO:OPT?": "1E5,UN8,UN9,UND", "FREQ?": "750000",
                            "POW?": "-10", "OUTP?": "1",
                            'MMEM:CAT? "ARBI:"': '32,2097120,"VOICE_T12",ARBI,32',
                            "SYST:ERR?": '+0,"No error"'})
        self.writes, self.queries = [], []
        self.lock = threading.RLock()
        self.serial = True
        self.settings = SimpleNamespace(address=30)
        self.port = "/dev/fake"
        self.adapter_version = "AR488 GPIB controller"
        self.fail_on = None

    @contextmanager
    def transaction(self):
        with self.lock:
            yield self

    def query(self, command):
        self.queries.append(command)
        if command == "SYST:ERR?" and self.fail_on in self.writes:
            self.fail_on = None
            return '-113,"Undefined header"'
        return self.values[{"AM:STAT?": "AM1:STAT?"}.get(command, command)]

    def write(self, command):
        self.writes.append(command)
        if command == "RAD:ARB ON":
            self.values["DM:EXT:HICR:STAT?"] = "1"
        key, value = command.split(" ", 1)
        value = {"ON": "1", "OFF": "0"}.get(value, value)
        value = value.removesuffix("DBM").removesuffix("PCT")
        if key in {"RAD:ARB", "OUTP:MOD"}:
            key += ":STAT"
        if key == "AM:STAT":
            key = "AM1:STAT"
        self.values[key + "?"] = value


@pytest.fixture
def driver():
    return E4433B(FakeInstrument())


def test_status_is_read_only_and_does_not_consume_errors(driver):
    assert driver.status()["frequency_hz"] == 750000
    assert driver.io.writes == []
    assert "SYST:ERR?" not in driver.io.queries
    assert "*OPT?" not in driver.io.queries


def test_expert_query_reads_once_without_consuming_errors(driver):
    assert driver.scpi_query("FREQ?")["response"] == "750000"
    assert driver.io.queries == ["FREQ?"]
    assert driver.io.writes == []


def test_expert_write_does_not_add_rf_changes_or_queries(driver):
    assert driver.scpi_write("DM:EXT:HICR:STAT OFF")["sent"] is True
    assert driver.io.writes == ["DM:EXT:HICR:STAT OFF"]
    assert driver.io.queries == []


@pytest.mark.parametrize("method,command", [
    ("scpi_query", "OUTP ON"), ("scpi_write", "FREQ?"),
    ("scpi_query", "FREQ?;POW?"), ("scpi_write", "OUTP ON\n++read eoi"),
    ("scpi_write", "++auto 1")])
def test_expert_invalid_commands_rejected_before_hardware(driver, method, command):
    with pytest.raises(ValueError):
        getattr(driver, method)(command)
    assert not driver.io.queries and not driver.io.writes


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 4.1e9])
def test_invalid_rf_values_never_connect_or_write(driver, value):
    with pytest.raises(ValueError):
        driver.set_rf(value, -10)
    assert not driver.io.queries and not driver.io.writes


def test_missing_waveform_does_not_modify_running_output(driver):
    driver.io.values['MMEM:CAT? "ARBI:"'] = "0,2097152"
    with pytest.raises(InstrumentError, match="absent"):
        driver.play_waveform("VOICE_T12", 16000, 750000, -10, True)
    assert driver.io.writes == []


def test_profile_restores_every_gate_and_leaves_rf_off_by_default(driver):
    result = driver.play_waveform("VOICE_T12", 16000, 750000, -10)
    assert result["status"]["rf_enabled"] is False
    assert result["status"]["high_crest_enabled"] is False
    for cmd in ["DM:SOUR INT", "DM:STAT ON", "BURS:STAT OFF",
                "DM:EXT:HICR:STAT OFF", "RAD:ARB:MARK:RFBL OFF", "AM2:STAT OFF",
                "FM2:STAT OFF", "PM2:STAT OFF", "RAD:ARB:TRIG:TYPE CONT",
                "POW:ALC:STAT OFF", "POW:ALC:SEAR ONCE"]:
        assert cmd in driver.io.writes
    assert "OUTP 1" not in driver.io.writes


def test_explicit_rf_on_happens_after_profile_configuration(driver):
    result = driver.play_waveform("VOICE_T12", 16000, 750000, -10, True)
    assert result["status"]["rf_enabled"] is True
    assert driver.io.writes[-1] == "OUTP 1"


def test_rejected_command_aborts_profile_and_mutes_output(driver):
    driver.io.fail_on = "RAD:ARB:RFIL 250000"
    with pytest.raises(InstrumentError, match="Undefined header"):
        driver.play_waveform("VOICE_T12", 16000, 750000, -10, True)
    assert "OUTP 1" not in driver.io.writes
    assert driver.io.writes[-1] == "OUTP OFF"


def test_analog_depth_cannot_silently_change_iq_voice(driver):
    driver.io.values["DM:STAT?"] = "1"
    with pytest.raises(InstrumentError, match="encoded"):
        driver.set_am_depth(75)
    assert driver.io.writes == []


def test_analog_tone_disables_iq_and_enables_only_requested_path(driver):
    result = driver.configure_am_tone(750000, -10, 1000, 50)
    assert result["status"]["rf_enabled"] is False
    assert result["status"]["iq_enabled"] is False
    assert result["status"]["am1_enabled"] is True
    assert result["status"]["am2_enabled"] is False
    assert result["am_rate_hz"] == 1000
    assert result["am_depth_percent"] == 50
    assert "AM:STAT ON" in driver.io.writes
    assert "RAD:ARB OFF" in driver.io.writes


def test_higher_sample_rate_does_not_use_voice_lowpass(driver):
    driver.play_waveform("VOICE_T12", 40_000_000, 750000, -10)
    assert "RAD:ARB:RFIL THR" in driver.io.writes


def test_refused_rf_setting_detected_by_readback(driver, monkeypatch):
    original = driver.io.write

    def ignore_frequency(command):
        if not command.startswith("FREQ "):
            original(command)

    monkeypatch.setattr(driver.io, "write", ignore_frequency)
    with pytest.raises(InstrumentError, match="RF settings readback mismatch"):
        driver.set_rf(1_000_000, -10)
    assert driver.io.writes[-1] == "OUTP OFF"


@pytest.mark.parametrize("raw", ['32,2097120,"VOICE_T12",ARBI,32',
                                 '32,2097120,"VOICE_T12,ARBI,32"'])
def test_catalog_formats(raw):
    assert parse_catalog(raw)["entries"] == [{"name": "VOICE_T12", "type": "ARBI", "bytes": 32}]


def test_voice_encoding_even_samples_depth_and_reserved_bits(tmp_path):
    path = tmp_path / "audio.wav"
    samples = [-32768, 0, 32767] * 7
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    i, q, metadata = voice_iq(str(path), 0.5)
    assert metadata["samples"] == 22
    assert metadata["carrier_scale"] == pytest.approx(0.6)
    assert set(sample_data(q)) == {8192}
    v = sample_data(i)
    assert (v[0] - 8192) / 8191 == pytest.approx(0.3, abs=1 / 8191)
    assert (v[2] - 8192) / 8191 == pytest.approx(0.9, abs=1 / 8191)
    assert sample_data(b"\xa0\x00") == [8192]
