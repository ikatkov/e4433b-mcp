# E4433B integration

- Use the E4433B MCP tools for the connected generator; do not open its serial port
  concurrently with an active MCP connection. `disconnect` releases it.
- Read `src/e4433b_mcp/guide.md` and `commands.md` before extending control methods.
  Read `docs/comparison.md` for reviewed alternatives and exact source revisions.
- Keep hardware access lazy. Listing MCP tools/resources must work with no instrument.
- Preserve query/write separation, whole-operation locking, legacy I/Q encoding,
  and explicit RF enable semantics. Never retry a failed write automatically.
- Document the manufacturer source and add a meaningful protocol/profile test
  for new commands. Distinguish offline tests, live command readback, and actual
  scope measurements. A PDF command reference alone is not hardware verification.
- Do not reset the generator or alter its stored waveforms merely to test discovery.
- This is a standalone project. Keep runtime files and documentation inside it;
  do not link to other local checkouts. Use `./setup` and the stable `./run-mcp` launcher.
- Manufacturer manual text is local-only data excluded from Git and distributions.
  Keep the manifest and importer public; do not add generated manuals to commits.
