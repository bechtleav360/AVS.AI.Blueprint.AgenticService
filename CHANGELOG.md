# Changelog

## [0.2.8] - 2025-11-24

### Added
- New `MetricsRecorder` and `MetricsExtractor` classes for modular metrics handling
- `with_metrics(enabled: bool = True)` builder method to toggle metrics logging
- `AgentRuntime.get_prompt(prompt_name)` method for lazy-loaded prompt retrieval with caching
- Complete prompt handling redesign with simplified API

### Changed
- **BREAKING:** Simplified `AgentBuilder` prompt API - replaced 4 methods with single `with_system_prompt(prompt: str | None = None)`
- Extracted metrics functionality from `AgentBuilder` to dedicated `metrics.py` module
- Logging levels upgraded from DEBUG to INFO for builder configuration operations
- Prompt loading strategy changed from pre-load at build time to lazy-load on demand
- Removed `_prompts` pre-loading from `AgentBuilder` - now uses lazy loading with caching in `AgentRuntime`
- Cleaned up public API exports - removed unused factory classes

### Removed
- `AgentFactory` - not used, AgentBuilder creates agents directly
- `ResponseHandlerFactory` - not integrated into agent creation flow
- `_prompts` attribute from `AgentBuilder` (prompts now lazy-loaded)
- `_load_prompt()` internal method from `AgentBuilder`
- Unused factory and handler exports from public API

### Deprecated
- `with_system_prompt_text()` - use `with_system_prompt(prompt_text)` instead
- `with_system_prompt_file()` - use `with_system_prompt()` to load from config
- `with_system_prompt_from_config()` - use `with_system_prompt()` instead
- `with_prompt()` - use `agent.get_prompt(prompt_name)` for lazy loading instead
- `AgentRuntime.prompts` property - use `agent.get_prompt(name)` instead
- `AgentRuntime.register_prompt()` - use `agent.get_prompt(name)` instead

### Fixed
- All 73 unit tests passing with backward compatibility maintained
- Performance improved by eliminating unnecessary pre-loading of prompts

### Migration Guide
**Old (Deprecated):**
```python
agent = (
    AgentBuilder(config)
    .with_model_from_config()
    .with_system_prompt_text("prompt")
    .with_prompt("template")
    .build()
)
prompt = agent.prompts["template"]
```

**New (Recommended):**
```python
agent = (
    AgentBuilder(config)
    .with_model_from_config()
    .with_system_prompt("prompt")  # or .with_system_prompt() to load from config
    .build()
)
prompt = agent.get_prompt("template")  # lazy-loaded and cached
prompt = prompt.format(difficulty="hard")
```

### Notes
- ✅ All 73 unit tests passing
- ✅ Simpler, cleaner API with lazy loading and caching
- ✅ Better performance - no unnecessary pre-loading
- ✅ Clear separation of concerns - builder sets system prompt, runtime loads instruction prompts

## [0.2.6] - 2025-11-23

### Added
- Handlers can now return `list[HandlerResult]` to publish multiple events from a single handler
- Added 6 new tests for multiple handler results feature

### Changed
- `EventHandler.handle()` return type now includes `list[HandlerResult]`
- `ProcessingService.process_event()` now publishes each result with `event_type` separately
- `_ResultBuilder.extract_handler_result()` detects and handles list of results

### Fixed
- Proper handling of mixed results where some have `event_type=None`
- OpenTelemetry tracing now includes result count for multi-result scenarios

### Notes
- ✅ Fully backward compatible - all existing code continues to work
- ✅ All 137 unit tests passing (6 new tests added)
