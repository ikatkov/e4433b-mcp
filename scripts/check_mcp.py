"""Exercise the actual stdio MCP protocol; add --hardware for status/catalog reads."""

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def check(hardware):
    report = {"timestamp": datetime.now(UTC).isoformat(), "hardware": hardware}
    params = StdioServerParameters(command=str(ROOT / "run-mcp"), env=dict(os.environ))
    async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
        await client.initialize()
        report["tools"] = [t.name for t in (await client.list_tools()).tools]
        report["resources"] = [str(r.uri) for r in (await client.list_resources()).resources]
        for uri in report["resources"]:
            response = await client.read_resource(uri)
            assert response.contents and len(response.contents[0].text) > 100
        print(f"MCP handshake: {len(report['tools'])} tools, "
              f"{len(report['resources'])} readable resources", flush=True)
        response = await client.call_tool("list_manuals", {})
        assert not response.isError
        catalog = json.loads(response.content[0].text)
        manuals_available = all(entry["available"] for entry in catalog["manuals"])
        report["manuals_available"] = manuals_available
        manual_checks = [
            ("search_manuals", {"query": "HICRest", "manual_id": "E4400-90324"}),
            ("read_manual_pages", {"manual_id": "E4400-90327", "page": 250})]
        for name, arguments in manual_checks if manuals_available else []:
            response = await client.call_tool(name, arguments)
            if response.isError:
                raise RuntimeError(f"{name}: {response.content}")
            report[name] = {"passed": True, "response_characters":
                           sum(len(c.text) for c in response.content if hasattr(c, "text"))}
        manual_uris = ("e4433b://manuals/E4400-90324",
                       "e4433b://manuals/E4400-90327/pages/250")
        for uri in manual_uris if manuals_available else []:
            response = await client.read_resource(uri)
            report[uri] = {"characters": len(response.contents[0].text)}
            assert len(response.contents[0].text) > 100
        if hardware:
            try:
                for name in ("get_status", "list_waveforms"):
                    response = await client.call_tool(name, {})
                    report[name] = response.model_dump(mode="json")
                    print(name, json.dumps(response.structuredContent or
                                           [c.text for c in response.content]), flush=True)
                    if response.isError:
                        report["passed"] = False
                        return report
            finally:
                result = await client.call_tool("disconnect", {})
                report["disconnect"] = result.model_dump(mode="json")
                if result.isError:
                    report["passed"] = False
        report.setdefault("passed", True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hardware", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(check(args.hardware))
    filename = "live-smoke.json" if args.hardware else "protocol-smoke.json"
    (ROOT / "docs" / filename).write_text(json.dumps(result, indent=2) + "\n")
    raise SystemExit(0 if result["passed"] else 1)
