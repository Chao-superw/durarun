# Changelog

## 0.1.0 — 2026-09-21

Initial release.

- `DurableRunner` with sequential step execution and WAL-backed crash recovery
- `@runner.step` decorator with per-step `retry` and `timeout` overrides
- Pluggable WAL backends: `SqliteWAL` (production) and `MemoryWAL` (testing)
- `arun()` for async workflows
- `resume()` to continue incomplete runs
- `RunResult` with step timeline and recovery statistics
- `Context` for passing state between steps
- Optional OpenTelemetry tracing with lazy SDK loading
- LangGraph `BaseCheckpointSaver` integration (`DurarunCheckpointer`)
