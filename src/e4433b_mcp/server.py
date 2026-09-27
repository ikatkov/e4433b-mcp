"""Local stdio MCP entry point. Startup/discovery never opens the serial port."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import manuals
from .driver import E4433B
from .transport import AR488, Settings, available_adapters


def create_server(driver=None):
    driver = driver or E4433B(AR488(Settings.from_env()))

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield {}
        finally:
            driver.io.close()

    mcp = FastMCP(
        "E4433B signal generator",
        instructions=("Controls an Agilent/HP E4433B through AR488 at GPIB 30. "
                      "Start with get_status. Read e4433b://guide for voice AM and recovery. "
                      "Use typed tools; do not open the same serial adapter with shell scripts. "
                      "For unsupported features, search the original Markdown manuals, then use "
                      "scpi_query/scpi_write. Expert tools apply exactly the requested command. "
                      "Configuration tools leave RF off unless rf_on=true is explicit. "
                      "Instrument readback is not a scope measurement. "
                      "Call disconnect when finished so another client can use the adapter."),
        lifespan=lifespan,
    )
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    change = ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                             idempotentHint=True, openWorldHint=False)

    @mcp.tool(annotations=read)
    def list_manuals() -> dict:
        """List local original-manual Markdown conversions, sources, coverage and page counts."""
        return manuals.catalog()

    @mcp.tool(annotations=read)
    def search_manuals(query: str, manual_id: str | None = None,
                       max_results: int = 10, offset: int = 0) -> dict:
        """Search original manual text offline; return page references and short excerpts.

        Literal, case-insensitive matching; whitespace is normalized. Search full
        command spellings (e.g. HICRest) or keywords, not only abbreviated SCPI.
        Use next_offset for more matches, read_manual_pages for complete context.
        """
        return manuals.search(query, manual_id, max_results, offset)

    @mcp.tool(annotations=read)
    def read_manual_pages(manual_id: str, page: int, page_count: int = 1) -> dict:
        """Read 1–5 source pages of original documentation as Markdown.

        Page numbers are 1-based source-document pages, not printed chapter labels.
        Text preserves syntax and tables; diagrams are not reproduced. Check model,
        installed option and firmware applicability before issuing an exotic command.
        """
        return manuals.read_pages(manual_id, page, page_count)

    expert = ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                             idempotentHint=False, openWorldHint=False)

    @mcp.tool(annotations=expert)
    async def scpi_query(command: str) -> dict:
        """Expert escape hatch: send ONE ASCII query and read ONE ASCII response.

        Look up the command in the Markdown manuals first. Queries can consume
        state or start tests, so this is not universally read-only. No extra error
        query, preset, retry or RF change is added. For binary responses use the
        driver's block transport, not this ASCII tool. One printable command under
        128 bytes; no semicolon batches, newlines or AR488 ++ commands. Unsupported
        queries may time out or cause -420. Query errors separately with read_errors.
        """
        return await asyncio.to_thread(driver.scpi_query, command)

    @mcp.tool(annotations=expert)
    async def scpi_write(command: str) -> dict:
        """Expert escape hatch: send ONE ASCII non-query exactly as requested.

        May change RF, erase data, reset or calibrate depending on the command;
        use only within the user's requested work after checking the manual. No
        automatic RF mute, preset, error drain or retry is added. Success confirms
        transport completion only: follow with the documented query and read_errors.
        Under 128 printable ASCII bytes; no semicolon batches, newlines, AR488 ++
        commands or binary blocks. Prefer typed tools for supported procedures.
        """
        return await asyncio.to_thread(driver.scpi_write, command)

    @mcp.tool(annotations=read)
    async def list_adapters() -> dict:
        """List USB serial adapters without opening ports or changing the instrument."""
        return {"adapters": available_adapters()}

    @mcp.tool(annotations=read)
    async def get_status(full: bool = True) -> dict:
        """Connect lazily and read E4433B identity, installed options, and live settings.

        full=True also checks I/Q source, both analog modulation paths, ALC,
        high-crest mode, clocks, trigger, offsets, and blanking. Does not reset,
        clear errors, or change generator settings. Returns diagnostic notes.
        """
        return await asyncio.to_thread(driver.status, full)

    @mcp.tool(annotations=change)
    async def read_errors() -> dict:
        """Read and consume the instrument's error queue, returning every recorded error.

        This is separate from status because reading removes the errors. No *CLS
        or preset is sent. Old errors are also returned by configuration tools.
        """
        return await asyncio.to_thread(driver.read_errors)

    @mcp.tool(annotations=change)
    async def set_rf_output(enabled: bool) -> dict:
        """Explicitly turn RF OUTPUT on or off and verify the enable state.

        Enabling uses the current frequency, level, and modulation. Read status
        first when these are unknown. Disabling does not discard the waveform.
        """
        return await asyncio.to_thread(driver.set_rf_output, enabled)

    @mcp.tool(annotations=change)
    async def set_rf(frequency_hz: float, level_dbm: float) -> dict:
        """Set a fixed carrier (250 kHz–4 GHz) and level setting (−135 to +20 dBm).

        Preserves RF on/off and modulation. Clears frequency/power display offsets
        and reference modes, disables sweeps, and enables automatic attenuation.
        RF is temporarily muted while settings change. With scaled I/Q, level_dbm
        is a generator setting, not a calibrated carrier-power measurement.
        """
        return await asyncio.to_thread(driver.set_rf, frequency_hz, level_dbm)

    @mcp.tool(annotations=read)
    async def list_waveforms() -> dict:
        """List existing volatile ARB waveforms. Requires installed UND option.

        Volatile waveforms can disappear after power-off. Check this before
        restoring playback; never assume yesterday's voice waveform still exists.
        """
        return await asyncio.to_thread(driver.list_waveforms)

    @mcp.tool(annotations=change)
    async def play_waveform(name: str, sample_rate_hz: float, frequency_hz: float,
                            level_dbm: float, rf_on: bool = False) -> dict:
        """Restore a complete continuous I/Q playback setup using an existing waveform.

        For our voice: name='VOICE_T12', sample_rate_hz=16000, frequency_hz=750000,
        level_dbm=-10. Specify rf_on=True only when output is requested. Restores
        internal I/Q and clock, master modulation, continuous trigger, normal
        crest mode, no gating/blanking or competing analog modulation, ALC off,
        and runs fixed-reference power search. Does not upload or modify samples.
        Voice modulation depth is encoded in the waveform, not the AM menu.
        """
        return await asyncio.to_thread(driver.play_waveform, name, sample_rate_hz,
                                       frequency_hz, level_dbm, rf_on)

    @mcp.tool(annotations=change)
    async def configure_am_tone(frequency_hz: float, level_dbm: float,
                                rate_hz: float = 1000, depth_percent: float = 50,
                                rf_on: bool = False) -> dict:
        """Configure ordinary sine-tone AM with adjustable front-panel depth.

        Uses analog AM path 1 and disables ARB/IQ and competing modulation. Rate
        0.1–50000 Hz, depth 0.1–100%. RF stays OFF unless rf_on=True. This replaces
        voice playback with a tone; it does not alter the stored voice waveform.
        """
        return await asyncio.to_thread(driver.configure_am_tone, frequency_hz, level_dbm,
                                       rate_hz, depth_percent, rf_on)

    @mcp.tool(annotations=change)
    async def set_am_depth(depth_percent: float) -> dict:
        """Change active analog AM path 1 depth (0.1–100%). Preserves RF on/off.

        Rejects I/Q voice playback: its depth must be changed by generating a new
        waveform with upload_am_wav. Does not silently switch modulation modes.
        """
        return await asyncio.to_thread(driver.set_am_depth, depth_percent)

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                         idempotentHint=False, openWorldHint=False))
    async def upload_am_wav(path: str, name: str, depth: float = 0.5,
                            overwrite: bool = False) -> dict:
        """Upload a local mono 16-bit PCM WAV as conventional AM using separate I/Q files.

        Depth is a fraction (0.5 means 50% peak), range 0.001–0.99. Input must be
        8–48 kHz, 16–131072 samples. Files stay local; no cloud service is involved.
        Uses E443xB offset-14-bit big-endian format and verifies every uploaded byte.
        Turns RF and ARB OFF and leaves them off. Call play_waveform separately.
        Existing names require overwrite=True. May take several minutes; configure
        the MCP client's tool timeout to 900 seconds. Partial files may remain on
        failure; no automatic upload retry or deletion is performed.
        """
        return await asyncio.to_thread(driver.upload_am_wav, path, name, depth, overwrite)

    @mcp.tool(annotations=read)
    async def inspect_waveform(name: str) -> dict:
        """Read stored I/Q samples and report hashes/ranges without modifying them.

        This can take minutes and may interrupt playback while the instrument
        services the read. Marker/sequencer bits can change raw hashes without
        changing the lower 14-bit audio samples. This does not measure RF output.
        """
        return await asyncio.to_thread(driver.inspect_waveform, name)

    @mcp.tool(annotations=change)
    async def disconnect(return_local: bool = True) -> dict:
        """Release the adapter so another client can use it; preserve RF settings.

        By default also return front-panel control. The next status/control call
        reconnects automatically. Server exit closes the port without turning RF off.
        """
        return await asyncio.to_thread(driver.disconnect, return_local)

    @mcp.resource("e4433b://guide", mime_type="text/markdown")
    def guide() -> str:
        """Operating notes, complete voice-restoration recipe, and known pitfalls."""
        return Path(__file__).with_name("guide.md").read_text()

    @mcp.resource("e4433b://commands", mime_type="text/markdown")
    def commands() -> str:
        """Documented command families and primary manual references."""
        return Path(__file__).with_name("commands.md").read_text()

    @mcp.resource("e4433b://manuals", mime_type="text/markdown")
    def manual_index() -> str:
        """Original manual library index and conversion limitations."""
        return (manuals.ROOT / "README.md").read_text()

    @mcp.resource("e4433b://manuals/{manual_id}", mime_type="text/markdown")
    def full_manual(manual_id: str) -> str:
        """Complete original manual text as Markdown; prefer search/page tools for large manuals."""
        return manuals.markdown(manual_id)

    @mcp.resource("e4433b://manuals/{manual_id}/pages/{page}", mime_type="text/markdown")
    def manual_page(manual_id: str, page: int) -> str:
        """One source page as Markdown."""
        return manuals.read_pages(manual_id, page)["pages"][0]["markdown"]

    return mcp


def main():
    logging.basicConfig(level=logging.INFO)  # stderr; stdout belongs to MCP JSON-RPC
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
