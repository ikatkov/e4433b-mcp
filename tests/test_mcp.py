import asyncio

from e4433b_mcp.server import create_server


def test_mcp_discovery_without_hardware(monkeypatch, sample_manuals):
    def fail(*args, **kwargs):
        raise AssertionError("MCP discovery must not open serial ports")

    monkeypatch.setattr("e4433b_mcp.transport.serial.Serial", fail)

    async def check():
        server = create_server()
        tools = await server.list_tools()
        names = {tool.name for tool in tools}
        assert {"get_status", "play_waveform", "upload_am_wav", "disconnect"} <= names
        assert {"scpi_query", "scpi_write", "list_manuals", "search_manuals",
                "read_manual_pages"} <= names
        for name in ("scpi_query", "scpi_write"):
            tool = next(t for t in tools if t.name == name)
            assert tool.annotations.readOnlyHint is False
            assert tool.annotations.idempotentHint is False
        output = next(t for t in tools if t.name == "set_rf_output")
        assert output.annotations.readOnlyHint is False
        play = next(t for t in tools if t.name == "play_waveform")
        assert play.inputSchema["properties"]["rf_on"]["default"] is False
        resources = await server.list_resources()
        assert {str(r.uri) for r in resources} == {
            "e4433b://guide", "e4433b://commands", "e4433b://manuals"}
        matches = await server.call_tool("search_manuals", {"query": "HICRest"})
        assert matches
        resource = await server.read_resource("e4433b://manuals/E4400-90324/pages/1")
        assert "Programming Guide" in next(iter(resource)).content

    asyncio.run(check())
