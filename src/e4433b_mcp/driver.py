"""Documented E4433B commands and complete, read-back-verified operating profiles."""

from __future__ import annotations

import csv
import hashlib
import logging
from contextlib import contextmanager

from .transport import AR488
from .waveforms import finite_range, sample_data, voice_iq, waveform_name

log = logging.getLogger(__name__)

# Source: Agilent E4400-90324 and E4400-90328; see the adjacent commands.md.
BASIC = {
    "frequency_hz": ("FREQ?", float), "level_setting_dbm": ("POW?", float),
    "rf_enabled": ("OUTP?", lambda x: bool(int(x))),
    "modulation_enabled": ("OUTP:MOD:STAT?", lambda x: bool(int(x))),
}
FULL = {
    "frequency_mode": ("FREQ:MODE?", str), "power_mode": ("POW:MODE?", str),
    "alc_enabled": ("POW:ALC:STAT?", lambda x: bool(int(x))),
    "attenuator_auto": ("POW:ATT:AUTO?", lambda x: bool(int(x))),
    "iq_enabled": ("DM:STAT?", lambda x: bool(int(x))),
    "iq_source": ("DM:SOUR?", str),
    "iq_adjustments_enabled": ("DM:IQAD:STAT?", lambda x: bool(int(x))),
    "high_crest_enabled": ("DM:EXT:HICR:STAT?", lambda x: bool(int(x))),
    "burst_enabled": ("BURS:STAT?", lambda x: bool(int(x))),
    "frequency_offset_hz": ("FREQ:OFFS?", float),
    "frequency_multiplier": ("FREQ:MULT?", float),
    "frequency_reference_enabled": ("FREQ:REF:STAT?", lambda x: bool(int(x))),
    "power_offset_db": ("POW:OFFS?", float),
    "power_reference_enabled": ("POW:REF:STAT?", lambda x: bool(int(x))),
    "reference_source": ("ROSC:SOUR?", str),
    **{f"{kind.lower()}{path}_enabled": (f"{kind}{path}:STAT?", lambda x: bool(int(x)))
       for kind in ("AM", "FM", "PM") for path in (1, 2)},
    "pulse_enabled": ("PULM:STAT?", lambda x: bool(int(x))),
}
ARB = {
    "arb_enabled": ("RAD:ARB:STAT?", lambda x: bool(int(x))),
    "waveform": ("RAD:ARB:WAV?", lambda x: x.strip('"')),
    "sample_rate_hz": ("RAD:ARB:CLOC:SRAT?", float),
    "arb_clock_source": ("RAD:ARB:CLOC:REF?", str),
    "trigger_mode": ("RAD:ARB:TRIG:TYPE?", str),
    "marker_rf_blanking": ("RAD:ARB:MARK:RFBL?", lambda x: bool(int(x))),
}


class InstrumentError(RuntimeError):
    pass


def parse_catalog(raw):
    fields = next(csv.reader([raw], skipinitialspace=True))
    if len(fields) < 2:
        raise InstrumentError(f"Malformed waveform catalog: {raw!r}")
    # Firmware revisions use either flat triples or quoted CSV triples.
    values = []
    for field in fields[2:]:
        values.extend(next(csv.reader([field])) if "," in field else [field])
    if len(values) % 3:
        raise InstrumentError(f"Unrecognized waveform catalog: {raw!r}")
    entries = [{"name": values[i], "type": values[i + 1], "bytes": int(values[i + 2])}
               for i in range(0, len(values), 3)]
    return {"used_bytes": int(fields[0]), "free_bytes": int(fields[1]), "entries": entries}


class E4433B:
    def __init__(self, transport: AR488):
        self.io = transport

    def _errors(self):
        errors = []
        for _ in range(32):
            raw = self.io.query("SYST:ERR?")
            code, _, message = raw.partition(",")
            if int(code) == 0:
                return errors
            errors.append({"code": int(code), "message": message.strip('"')})
        raise InstrumentError(f"Error queue did not drain: {errors}")

    def read_errors(self):
        with self.io.transaction():
            return {"errors": self._errors(), "note": "Reading consumes the instrument error queue."}

    def scpi_query(self, command):
        # Validate before opening hardware. Do not add queries: SYST:ERR? and
        # event-register queries themselves consume state.
        AR488._validate_ascii(command, query=True)
        with self.io.transaction():
            return {"command": command, "response": self.io.query(command)}

    def scpi_write(self, command):
        AR488._validate_ascii(command, query=False)
        with self.io.transaction():
            self.io.write(command)
            return {"command": command, "sent": True,
                    "verification": "Transport completion only; query readback and read_errors next."}

    def _checked(self, command):
        self.io.write(command)
        errors = self._errors()
        if errors:
            raise InstrumentError(f"{command}: {errors}")

    def _require_arb(self):
        options = self.io.query("DIAG:INFO:OPT?").split(",")
        if "UND" not in options:
            raise InstrumentError("Installed option UND is required for arbitrary waveforms")

    def _status(self, full):
        result = {"identity": self.io.query("*IDN?"), "port": self.io.port,
                  "gpib_address": self.io.settings.address,
                  "adapter": self.io.adapter_version,
                  "options": self.io.query("DIAG:INFO:OPT?").split(",")}
        queries = BASIC | (FULL if full else {})
        if full and "UND" in result["options"]:
            queries |= ARB
        for name, (command, convert) in queries.items():
            result[name] = convert(self.io.query(command))
        notes = []
        if not result["rf_enabled"]:
            notes.append("RF output is OFF")
        if full and result.get("arb_enabled"):
            for key, expected, note in [
                ("modulation_enabled", True, "Master modulation is OFF"),
                ("iq_enabled", True, "I/Q modulation is OFF"),
                ("iq_source", "INT", "I/Q source is not internal"),
                ("trigger_mode", "CONT", "Playback is not continuous"),
                ("arb_clock_source", "INT", "Waveform clock uses an external reference"),
                ("burst_enabled", False, "Burst gating is enabled"),
                ("marker_rf_blanking", False, "Marker RF blanking is enabled"),
                ("high_crest_enabled", False, "High-crest mode changes output level"),
                ("alc_enabled", False, "ALC may flatten an AM voice envelope"),
            ]:
                if result.get(key) != expected:
                    notes.append(note)
            notes.append("Voice AM depth is encoded in I/Q samples; analog AM Depth does not change it")
        result["notes"] = notes
        result["verification"] = "Instrument readback only; use the separate scope MCP to measure RF."
        return result

    def status(self, full=True):
        with self.io.transaction():
            return self._status(full)

    @contextmanager
    def _change(self):
        with self.io.transaction():
            previous = self._errors()
            try:
                yield previous
            except BaseException:
                # Do not claim RF was disabled if communication has failed.
                try:
                    self.io.write("OUTP OFF")
                except Exception:
                    log.exception("Could not confirm RF OFF after failed operation")
                raise

    def _result(self, previous, full=True):
        result = {"status": self._status(full), "previous_errors": previous}
        errors = self._errors()
        if errors:
            raise InstrumentError(f"Readback failed: {errors}")
        result["errors"] = []
        return result

    def set_rf_output(self, enabled):
        with self._change() as previous:
            self._checked(f"OUTP {int(enabled)}")
            result = self._result(previous, full=False)
            if result["status"]["rf_enabled"] != enabled:
                raise InstrumentError("RF enable readback mismatch")
            return result

    @staticmethod
    def _validate_rf(frequency_hz, level_dbm):
        finite_range("Carrier frequency (Hz)", frequency_hz, 250_000, 4_000_000_000)
        finite_range("Level setting (dBm)", level_dbm, -135, 20)

    def _rf(self, frequency_hz, level_dbm):
        for cmd in ["FREQ:MODE CW", "POW:MODE FIX", "POW:ATT:AUTO ON",
                    "FREQ:REF:STAT OFF", "FREQ:OFFS 0", "FREQ:MULT 1",
                    "POW:REF:STAT OFF", "POW:OFFS 0", f"FREQ {frequency_hz:.12g}",
                    f"POW {level_dbm:.12g}DBM"]:
            self._checked(cmd)

    def set_rf(self, frequency_hz, level_dbm):
        self._validate_rf(frequency_hz, level_dbm)
        with self._change() as previous:
            was_on = bool(int(self.io.query("OUTP?")))
            self._checked("OUTP OFF")
            self._rf(frequency_hz, level_dbm)
            if not int(self.io.query("POW:ALC:STAT?")):
                self._checked("POW:ALC:SEAR ONCE")
            self._checked(f"OUTP {int(was_on)}")
            result = self._result(previous)
            actual = result["status"]
            if (abs(actual["frequency_hz"] - frequency_hz) > 0.01 or
                    abs(actual["level_setting_dbm"] - level_dbm) > 0.011 or
                    actual["rf_enabled"] != was_on):
                raise InstrumentError("RF settings readback mismatch")
            return result

    def _disable_other_modulation(self):
        for kind in ("AM", "FM", "PM"):
            for path in (1, 2):
                self._checked(f"{kind}{path}:STAT OFF")
        for cmd in ["PULM:STAT OFF", "BURS:STAT OFF", "DM:IQAD:STAT OFF",
                    "DM:EXT:HICR:STAT OFF"]:
            self._checked(cmd)

    def _catalog(self):
        self._require_arb()
        return parse_catalog(self.io.query('MMEM:CAT? "ARBI:"'))

    def list_waveforms(self):
        with self.io.transaction():
            return self._catalog()

    def _has_waveform(self, name):
        return any(e["name"].removeprefix("ARBI:") == name
                   for e in self._catalog()["entries"])

    def play_waveform(self, name, sample_rate_hz, frequency_hz, level_dbm, rf_on=False):
        waveform_name(name)
        finite_range("Sample rate (Hz)", sample_rate_hz, 1, 40_000_000)
        self._validate_rf(frequency_hz, level_dbm)
        with self.io.transaction():
            # Check existence before mutating the current output.
            if not self._has_waveform(name):
                raise InstrumentError(f"Waveform {name!r} is absent from volatile ARB memory. "
                                      "It may have been lost on power-off; upload the local WAV.")
            with self._change() as previous:
                self._checked("OUTP OFF")
                self._checked("RAD:ARB OFF")
                self._disable_other_modulation()
                self._rf(frequency_hz, level_dbm)
                cutoff = next((str(f) for f in (250000, 2500000, 8000000)
                               if sample_rate_hz / 2 <= f), "THR")
                for cmd in ["RAD:ARB:CLOC:REF INT", f"RAD:ARB:CLOC:SRAT {sample_rate_hz:.12g}",
                            f"RAD:ARB:RFIL {cutoff}", "RAD:ARB:TRIG:TYPE CONT",
                            "RAD:ARB:MARK:RFBL OFF", f'RAD:ARB:WAV "ARBI:{name}"',
                            "RAD:ARB ON", "DM:SOUR INT", "DM:STAT ON", "OUTP:MOD ON",
                            # Enabling ARB on B.03.86 re-enables high-crest mode.
                            "DM:EXT:HICR:STAT OFF",
                            "POW:ALC:STAT OFF", "POW:ALC:SEAR:REF FIX",
                            "POW:ALC:SEAR ONCE", f"OUTP {int(rf_on)}"]:
                    self._checked(cmd)
                result = self._result(previous)
                actual = result["status"]
                expected = {"frequency_hz": frequency_hz, "level_setting_dbm": level_dbm,
                            "rf_enabled": rf_on, "arb_enabled": True, "iq_enabled": True,
                            "iq_source": "INT", "modulation_enabled": True,
                            "trigger_mode": "CONT", "sample_rate_hz": sample_rate_hz,
                            "waveform": "ARBI:" + name, "alc_enabled": False,
                            "high_crest_enabled": False, "iq_adjustments_enabled": False,
                            "burst_enabled": False, "marker_rf_blanking": False,
                            "arb_clock_source": "INT"}
                mismatches = {k: (v, actual.get(k)) for k, v in expected.items()
                              if v != actual.get(k)}
                if mismatches:
                    raise InstrumentError(f"Playback readback mismatch: {mismatches}")
                return result

    def configure_am_tone(self, frequency_hz, level_dbm, rate_hz, depth_percent, rf_on=False):
        self._validate_rf(frequency_hz, level_dbm)
        finite_range("AM tone rate (Hz)", rate_hz, 0.1, 50_000)
        finite_range("AM depth (%)", depth_percent, 0.1, 100)
        with self._change() as previous:
            self._checked("OUTP OFF")
            if "UND" in self.io.query("DIAG:INFO:OPT?").split(","):
                self._checked("RAD:ARB OFF")
            self._disable_other_modulation()
            self._rf(frequency_hz, level_dbm)
            for cmd in ["DM:STAT OFF", "POW:ALC:STAT ON", "AM:SOUR INT",
                        "AM:DEPTH:TRAC OFF", "AM:INT:FUNC:SHAP SINE",
                        f"AM:INT:FREQ {rate_hz:.12g}", f"AM:DEPTH {depth_percent:.12g}PCT",
                        "AM:STAT ON", "OUTP:MOD ON", f"OUTP {int(rf_on)}"]:
                self._checked(cmd)
            result = self._result(previous)
            result["am_rate_hz"] = float(self.io.query("AM:INT:FREQ?"))
            result["am_depth_percent"] = float(self.io.query("AM:DEPTH?"))
            if (abs(result["am_rate_hz"] - rate_hz) > 0.051 or
                    abs(result["am_depth_percent"] - depth_percent) > 0.051):
                raise InstrumentError("AM rate/depth readback mismatch")
            errors = self._errors()
            if errors:
                raise InstrumentError(f"AM readback failed: {errors}")
            return result

    def set_am_depth(self, depth_percent):
        finite_range("AM depth (%)", depth_percent, 0.1, 100)
        with self.io.transaction():
            if int(self.io.query("DM:STAT?")):
                raise InstrumentError("I/Q modulation is active. Uploaded voice depth is encoded "
                                      "in the waveform; this control only changes analog AM path 1.")
            if not int(self.io.query("AM:STAT?")):
                raise InstrumentError("Analog AM path 1 is off; configure_am_tone first")
            with self._change() as previous:
                self._checked(f"AM:DEPTH {depth_percent:.12g}PCT")
                actual = float(self.io.query("AM:DEPTH?"))
                errors = self._errors()
                if errors or abs(actual - depth_percent) > 0.051:
                    raise InstrumentError(f"AM depth readback failed: {actual}, errors={errors}")
                return {"depth_percent": actual, "previous_errors": previous, "errors": []}

    def upload_am_wav(self, path, name, depth=0.5, overwrite=False):
        waveform_name(name)
        i, q, metadata = voice_iq(path, depth)
        with self.io.transaction():
            if self._has_waveform(name) and not overwrite:
                raise InstrumentError(f"{name!r} already exists; choose a new name or overwrite=True")
            with self._change() as previous:
                self._checked("OUTP OFF")
                self._checked("RAD:ARB OFF")
                hashes = {}
                for channel, data in [("ARBI", i), ("ARBQ", q)]:
                    filename = f"{channel}:{name}"
                    self.io.write_block(f'MMEM:DATA "{filename}",', data)
                    errors = self._errors()
                    if errors:
                        raise InstrumentError(f"Upload {filename}: {errors}")
                    received = self.io.read_block(f'MMEM:DATA? "{filename}"', max_bytes=len(data))
                    # Exact comparison before playback: marker bits should not change yet.
                    if received != data:
                        raise InstrumentError(f"Binary readback mismatch for {filename}")
                    hashes[channel] = hashlib.sha256(received).hexdigest()
                errors = self._errors()
                if errors:
                    raise InstrumentError(f"Waveform verification: {errors}")
                return {"name": name, **metadata, "sha256": hashes, "verified": True,
                        "rf_enabled": False, "previous_errors": previous, "errors": [],
                        "note": "Uploaded to volatile memory. Use play_waveform to select/play it. "
                                "RF level setting is not the calibrated carrier level with scaled I/Q."}

    def inspect_waveform(self, name):
        waveform_name(name)
        with self.io.transaction():
            if not self._has_waveform(name):
                raise InstrumentError(f"Waveform {name!r} not found")
            result = {"name": name, "channels": {}}
            for channel in ("ARBI", "ARBQ"):
                data = self.io.read_block(f'MMEM:DATA? "{channel}:{name}"')
                samples = sample_data(data)
                result["channels"][channel] = {
                    "bytes": len(data), "samples": len(samples),
                    "sha256_raw": hashlib.sha256(data).hexdigest(),
                    "min_sample": min(samples), "max_sample": max(samples),
                    "all_zero_signal": all(s == 8192 for s in samples),
                }
            result["note"] = "Upper two bits are markers/sequencing, excluded from sample statistics."
            return result

    def disconnect(self, return_local=True):
        with self.io.lock:
            try:
                if return_local and self.io.serial is not None:
                    self.io.local()
            finally:
                self.io.close()
        return {"disconnected": True, "rf_changed": False}
