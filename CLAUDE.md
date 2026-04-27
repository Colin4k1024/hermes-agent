# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
uv venv venv --python 3.11
source venv/bin/activate
uv pip install -e ".[all,dev]"
```

For targeted installs: `uv pip install -e ".[messaging,mcp,dev]"` — see `pyproject.toml` for all extras.

## Common Commands

```bash
# Run all tests (parallel, skips integration tests)
python -m pytest tests/ -q

# Run a single test file
python -m pytest tests/test_model_tools.py -q

# Run a single test by name
python -m pytest tests/test_model_tools.py -q -k "test_name"

# Run with integration tests (requires API keys)
python -m pytest tests/ -q -m integration

# Run specific test directories
python -m pytest tests/gateway/ -q
python -m pytest tests/tools/ -q
python -m pytest tests/test_cli_init.py -q

# Start the CLI
hermes

# Run agent directly
hermes-agent "your task here"
```

No separate build or lint step — the project uses `setuptools` with `uv` for dependency management.

## Architecture

### Dependency Chain

```
tools/registry.py → tools/*.py → model_tools.py → run_agent.py / cli.py
```

- `tools/registry.py` — central tool registry; tools self-register via `registry.register()` at module level
- `toolsets.py` — groups tools into named sets; `_HERMES_CORE_TOOLS` is shared across all platform toolsets
- `model_tools.py` — translates registry into OpenAI-format tool schemas; triggers tool discovery on import
- `run_agent.py` — `AIAgent` class and synchronous agent loop (~570KB, single file)
- `cli.py` — interactive REPL, slash commands, session management
- `hermes_cli/` — web UI, config loader, skin engine, command registry

### Major Modules

| Directory/File | Purpose |
|---|---|
| `agent/` | AIAgent internals: provider adapters, prompt caching, credential pool, rate limiting, memory, redaction, smart routing, usage pricing |
| `tools/` | All tool implementations (one file per tool) |
| `gateway/` | Messaging adapters — `gateway/platforms/base.py` defines `BasePlatformAdapter(ABC)` |
| `hermes_cli/` | CLI UI, config, commands, skins |
| `hermes_cli/plugins/` | Plugin manager, pre/post tool hooks (NOT `plugins/` at root — that's just a package marker) |
| `cron/` | Scheduled task runner |
| `acp_adapter/` | ACP (Agent Communication Protocol) bridge |
| `tests/` | pytest suite (~3000 tests, ~3 min) |

### AIAgent Class (`run_agent.py`)

```python
class AIAgent:
    def __init__(self,
        model: str = "anthropic/claude-opus-4.6",
        max_iterations: int = 90,
        enabled_toolsets: list = None,
        disabled_toolsets: list = None,
        quiet_mode: bool = False,
        save_trajectories: bool = False,
        platform: str = None,
        session_id: str = None,
        skip_context_files: bool = False,
        skip_memory: bool = False,
    ): ...
    def chat(self, message: str) -> str: ...
    def run_conversation(self, user_message, system_message=None,
                         conversation_history=None, task_id=None) -> dict: ...
```

The agent loop is synchronous. All providers (Anthropic, Bedrock, OpenRouter, etc.) go through the OpenAI-compatible client interface — provider-specific behavior is abstracted into `agent/` submodules.

### Tool System

**Discovery:** `model_tools.py` calls `discover_builtin_tools()` which uses AST parsing to find files containing `registry.register()` before importing them. Not runtime import scanning.

**Registration:** Tools call `registry.register()` at module level. Handlers must return JSON strings via `tool_result()` or `tool_error()` helpers from `tools/registry.py`.

**Agent-loop tools:** `todo`, `memory`, `session_search`, `delegate_task` bypass the registry dispatcher — they're handled directly in the agent loop (`_AGENT_LOOP_TOOLS` in `model_tools.py`).

**Schema rewriting:** `execute_code` and `browser_navigate` schemas are dynamically rewritten at definition-fetch time based on which other tools are available.

**Adding a tool:**
1. Create `tools/your_tool.py` with a `registry.register()` call at module level
2. Add the toolset entry in `toolsets.py`
3. Return JSON strings via `tool_result()`/`tool_error()` — never return raw dicts
4. Use `get_hermes_home()` from `hermes_constants` for all file paths

### Toolset System (`toolsets.py`)

- `_HERMES_CORE_TOOLS` — shared list referenced by all platform toolsets; edit here to propagate everywhere
- Toolsets support `includes` for composition; `resolve_toolset()` does recursive diamond-safe resolution
- `"all"` and `"*"` resolve to every registered tool
- Plugin toolsets are dynamically merged at query time — they don't appear in the static `TOOLSETS` dict

### Adding a Slash Command

1. Add a `CommandDef` (frozen dataclass) entry in `hermes_cli/commands.py` (`COMMAND_REGISTRY`)
2. Add the handler in `cli.py` (and optionally `gateway/run.py`)
3. Note: `cli_only=True` commands can still appear on gateway if `gateway_config_gate` is set
4. Platform constraints: Telegram strips non-`[a-z0-9_]`, max 32 chars, 100 commands; Discord max 25 subcommand groups

### Config

Two separate config loaders exist:
- `load_cli_config()` in `cli.py` — for the interactive CLI
- `load_config()` in `hermes_cli/config.py` — for programmatic use; `DEFAULT_CONFIG` lives here

When changing the config schema, bump `_config_version` (currently `5`) in `hermes_cli/config.py`.

Env loading order: `~/.hermes/.env` first, then project root `.env` as a dev override fallback.

Managed mode: `HERMES_MANAGED` env var or `~/.hermes/.managed` marker file locks down config editing.

### Profiles (Multi-instance Isolation)

Use `get_hermes_home()` from `hermes_constants` everywhere for paths. The `HERMES_HOME` env var overrides the default. `get_subprocess_home()` returns `{HERMES_HOME}/home/` for isolating subprocess writes (git, ssh, npm) — but only if that directory already exists.

Tests use an `_isolate_hermes_home` autouse fixture that redirects to a temp dir — never write to `~/.hermes/` in tests.

### Path Resolution (`hermes_constants.py`)

`get_hermes_dir(new_subpath, old_name)` provides backward-compatible paths: returns the old path if it already exists on disk. Both old and new paths may coexist in existing installs — migrations are not automatic.

## Known Pitfalls

- **Never hardcode `~/.hermes`** — always use `get_hermes_home()`
- **Never use `asyncio.run()` in tool handlers** — it creates and closes a loop, breaking cached async clients. Use `_run_async()` from `model_tools.py` instead
- **Never use `simple_term_menu`** — use `curses` instead (rendering bugs in tmux/iTerm2)
- **Never use `\033[K`** in display code — use space-padding
- **`_last_resolved_tool_names` is process-global** — `delegate_tool.py` saves/restores it; be careful in concurrent contexts
- **Don't cross-reference tool names** in static schema descriptions
- **Prompt caching (Anthropic)**: the system prompt and first few messages are cached via `agent/prompt_caching.py` — don't restructure message history mid-conversation or caching breaks
- **Tool shadowing is silent** — non-MCP tools that duplicate an existing name are rejected with `logger.error` only, no exception
- **Plugin hooks can block** — a `pre_tool_call` hook returning a string prevents tool execution
- **Gateway is deny-by-default** — `GATEWAY_ALLOW_ALL_USERS=false`; users must be explicitly allowlisted
- **IPv4 monkey-patch** — `apply_ipv4_preference()` in `hermes_constants` globally patches `socket.getaddrinfo` when `network.force_ipv4` is configured

## LLM Providers

Model strings use `provider/model-name` format (e.g., `anthropic/claude-opus-4.6`, `openai/gpt-4o`). All providers use the OpenAI-compatible client interface — provider adapters in `agent/` handle specifics (Anthropic cache control, Bedrock signing, etc.).

Supported: OpenAI, Anthropic, OpenRouter, Bedrock, Mistral, GLM/z.ai, Kimi/Moonshot, MiniMax, Hugging Face, Xiaomi MiMo, Arcee AI, Qwen, Nous Portal, and any OpenAI-compatible endpoint.

`LLM_MODEL` env var is deprecated — model config belongs in `config.yaml`.

## Testing Notes

- Integration tests require real API keys; they're excluded by default (`-m 'not integration'`)
- Tests run in parallel via `pytest-xdist` (`-n auto`)
- The `_isolate_hermes_home` fixture is autouse — no manual isolation needed in new tests
- The fixture also resets `hermes_cli.plugins._plugin_manager` to `None` and deletes 5 env vars (`HERMES_SESSION_PLATFORM`, `HERMES_SESSION_CHAT_ID`, `HERMES_SESSION_CHAT_NAME`, `HERMES_GATEWAY_SESSION`, `OPENROUTER_API_KEY`) — gateway tests must re-set these
- Hard 30-second timeout per test via SIGALRM (Unix only)
