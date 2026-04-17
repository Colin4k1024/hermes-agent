# LiteLLM Configuration Guide

Production LLM proxy configuration for the Hermes Enterprise SaaS platform.

## Overview

LiteLLM provides an OpenAI-compatible API layer that proxies to multiple LLM providers (OpenAI, Anthropic, Google Gemini, Azure, etc.). This enables the Hermes platform to use enterprise LLMs with standardized API endpoints, token tracking, and rate limiting.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Hermes Platform                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │router-service│  │hermes-agent  │  │  quota-service   │   │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘   │
│         │                 │                    │              │
│         └─────────────────┼────────────────────┘              │
│                           ▼                                   │
│              ┌────────────────────────┐                       │
│              │    LiteLLM Proxy       │                       │
│              │    (Port 4000)         │                       │
│              └───────────┬────────────┘                       │
│                          │                                    │
│    ┌─────────────────────┼─────────────────────┐              │
│    ▼                     ▼                     ▼              │
│ ┌──────┐          ┌──────────────┐       ┌──────────┐        │
│ │OpenAI│          │ Anthropic    │       │  Gemini  │        │
│ └──────┘          └──────────────┘       └──────────┘        │
└─────────────────────────────────────────────────────────────┘
```

## Deployment Modes

### Production Mode (Default)

```bash
docker compose up  # Starts with real LiteLLM
```

Requires:
- Valid API keys in environment variables or `.env` file
- `LITELLM_MASTER_KEY` must be set

### Development/Mock Mode

```bash
docker compose --profile mock up  # Starts with fake LLM
```

For local development without API keys. Uses mock responses.

## Configuration Files

| File | Purpose |
|------|---------|
| `config.yaml.example` | Production template with real model definitions |
| `.env.example` | Environment variables for API keys |
| `docker-compose.yaml` | Service definition for standalone deployment |

## Environment Variables

### Required for Production

```bash
# Master key for LiteLLM admin API
LITELLM_MASTER_KEY=sk-prod-your-secure-random-key

# API Keys (at least one required)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...

# Database for token tracking
DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/hermes_platform
```

### Generate a Secure Master Key

```bash
openssl rand -hex 32
```

## Supported Providers

### OpenAI

| Model | Model Name | Context Length | Notes |
|-------|------------|----------------|-------|
| GPT-4o | `gpt-4o` | 128K | Latest flagship |
| GPT-4o Mini | `gpt-4o-mini` | 128K | Faster, cost-effective |

**Configuration:**
```yaml
- model_name: gpt-4o
  litellm_params:
    model: openai/gpt-4o
    api_key: ${OPENAI_API_KEY}
    api_base: https://api.openai.com/v1
```

### Anthropic

| Model | Model Name | Context Length | Notes |
|-------|------------|----------------|-------|
| Claude Sonnet 4 | `claude-sonnet-4` | 200K | Latest stable |
| Claude 3.5 Sonnet | `claude-3-5-sonnet` | 200K | Extended thinking |

**Configuration:**
```yaml
- model_name: claude-sonnet-4
  litellm_params:
    model: anthropic/claude-sonnet-4-20250514
    api_key: ${ANTHROPIC_API_KEY}
    api_base: https://api.anthropic.com/v1
```

### Google Gemini

| Model | Model Name | Context Length | Notes |
|-------|------------|----------------|-------|
| Gemini 1.5 Pro | `gemini-1.5-pro` | 1M | Long context |
| Gemini 1.5 Flash | `gemini-1.5-flash` | 1M | Fast, cost-effective |

**Configuration:**
```yaml
- model_name: gemini-1.5-pro
  litellm_params:
    model: gemini/gemini-1.5-pro
    api_key: ${GOOGLE_API_KEY}
    api_base: https://generativelanguage.googleapis.com/v1beta
```

## Adding Custom Models

### Custom OpenAI-Compatible Endpoint

```yaml
- model_name: custom-model
  litellm_params:
    model: openai/<model-name>
    api_key: ${CUSTOM_API_KEY}
    api_base: https://your-custom-endpoint/v1
  router_settings:
    temperature: 0.7
    max_tokens: 4096
```

### Azure OpenAI

```yaml
- model_name: azure-gpt-4o
  litellm_params:
    model: azure/<deployment-name>
    api_key: ${AZURE_API_KEY}
    api_base: https://<resource>.openai.azure.com/v1
    api_version: "2024-06-01"
```

### Custom Model with Specific Routing

```yaml
- model_name: high-quality-model
  litellm_params:
    model: openai/gpt-4o
    api_key: ${OPENAI_API_KEY}
  router_settings:
    temperature: 0.2  # Lower temperature for precise tasks
    max_tokens: 8192
    routing_strategy: latency-based-routing  # Route to fastest endpoint
```

## Per-Model Router Settings

The `router_settings` section controls per-model behavior:

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `temperature` | float | 0.7 | Response randomness |
| `max_tokens` | int | 4096 | Maximum response length |
| `routing_strategy` | string | simple-shuffle | Load balancing strategy |

### Routing Strategies

- **simple-shuffle**: Round-robin across endpoints
- **latency-based-routing**: Route to fastest responding endpoint
- **usage-based-routing**: Route based on current load

## LiteLLM Settings

```yaml
litellm_settings:
  drop_params: true          # Ignore unsupported params
  set_verbose: ${LITELLM_DEBUG:-false}
  request_timeout: 600       # 10 minute timeout
  num_retries: 3             # Retry on failure
  retry_after: 3             # Seconds between retries
  log_level: info            # Log verbosity
```

## General Settings

```yaml
general_settings:
  master_key: ${LITELLM_MASTER_KEY}  # Required admin key
  database_url: ${DATABASE_URL}      # Token tracking DB
  otel: true                         # OpenTelemetry tracing
  proxy_batch_write_at: 60           # Batch write interval
```

## Database Configuration

LiteLLM uses PostgreSQL for:
- Virtual key management
- Token usage tracking
- Spend limits per user/team

```bash
DATABASE_URL=postgresql+asyncpg://hermes:hermes@postgres:5432/hermes_platform
```

## Health Check

```bash
curl http://localhost:4000/health
```

Returns:
```json
{
  "status": "healthy",
  "version": "1.0.0"
}
```

## API Usage

### Chat Completions

```bash
curl http://localhost:4000/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

### List Models

```bash
curl http://localhost:4000/models \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}"
```

## Upgrading from Mock to Production

1. Copy the example config:
   ```bash
   cp services/litellm/config.yaml.example services/litellm/config.yaml
   ```

2. Edit `config.yaml` and set your API keys as environment variables

3. Create `.env` file:
   ```bash
   cp services/litellm/.env.example services/litellm/.env
   # Edit .env with real API keys
   ```

4. Stop mock and start production:
   ```bash
   docker compose down
   docker compose up --build
   ```

5. Update dependent services to use the real LiteLLM URL:
   - Set `LLM_PROXY_URL=http://litellm:4000` in router-service
   - Or use the default which points to the litellm service

## Troubleshooting

### "Invalid API Key" Error

Ensure your API key is correctly set in the environment:
```bash
echo $OPENAI_API_KEY  # Should show your key
```

### "Model not found" Error

Check that the model is defined in `model_list` and the service has been restarted:
```bash
docker compose restart litellm
```

### Connection Timeout

Increase the request timeout:
```yaml
litellm_settings:
  request_timeout: 600  # 10 minutes
```

### High Latency

Use latency-based routing:
```yaml
router_settings:
  routing_strategy: latency-based-routing
```
