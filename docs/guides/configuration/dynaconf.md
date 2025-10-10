# Dynaconf Configuration Management

**Complete guide to using Dynaconf for configuration**

Dynaconf is a layered configuration system that supports multiple file formats, environment variables, and environment-specific settings.

## What is Dynaconf?

**Dynaconf** provides:
- ✅ Multiple configuration sources (TOML, YAML, JSON, INI, .env)
- ✅ Environment-specific settings
- ✅ Environment variable overrides
- ✅ Secrets management
- ✅ Validation
- ✅ Type casting

## Configuration Files

### settings.toml

Main configuration file for non-sensitive settings.

**Location:** `custom/settings.toml`

```toml
[default]
# Default settings for all environments
app_name = "invoice-processor"
app_port = 8001
log_level = "INFO"

# AI Model
ai_model_provider = "openai"
ai_model_name = "gpt-4"
ai_model_timeout = 60

[development]
# Development-specific overrides
log_level = "DEBUG"
ai_model_timeout = 120

[staging]
# Staging-specific overrides
log_level = "INFO"
app_name = "invoice-processor-staging"

[production]
# Production-specific overrides
log_level = "WARNING"
app_name = "invoice-processor-prod"
```

### secrets.toml

Sensitive configuration (never commit to git).

**Location:** `custom/secrets.toml`

```toml
[default]
ai_model_api_key = "sk-your-key"
database_password = "secret"
data_gateway_api_key = "gateway-key"

[production]
ai_model_api_key = "sk-prod-key"
database_password = "prod-secret"
```

**⚠️ Security:** Add to `.gitignore`:
```
secrets.toml
.secrets.*
```

### .env Files

Alternative to TOML for environment variables.

**Location:** `custom/.env`

```bash
# Application
APP_NAME=invoice-processor
APP_PORT=8001
LOG_LEVEL=INFO

# AI Model
AI_MODEL_PROVIDER=openai
AI_MODEL_NAME=gpt-4
AI_MODEL_API_KEY=sk-your-key

# Database
DATABASE_URL=postgresql://user:pass@localhost/db
```

## Configuration Priority

Dynaconf loads configuration in this order (later overrides earlier):

```
1. settings.toml [default]
   ↓
2. settings.toml [environment-specific]
   ↓
3. secrets.toml [default]
   ↓
4. secrets.toml [environment-specific]
   ↓
5. Environment variables
   ↓
6. .env file (highest priority)
```

**Example:**

```toml
# settings.toml
[default]
log_level = "INFO"

[development]
log_level = "DEBUG"
```

```bash
# Environment variable
export LOG_LEVEL="WARNING"
export ENVIRONMENT=development
```

**Result:** `log_level = "WARNING"` (environment variable wins)

## Using Dynaconf in Code

### Basic Usage

```python
from base.src.config import Config

# Initialize config
config = Config()

# Get values
app_name = config.get("app_name")
log_level = config.get("log_level")
api_key = config.get("ai_model_api_key")

# Get with default
timeout = config.get("ai_model_timeout", 60)

# Get nested values
email_host = config.get("email.smtp_host")
```

### Type Casting

Dynaconf automatically casts types:

```toml
[default]
app_port = 8001           # int
debug = true              # bool
timeout = 60.5            # float
tags = ["api", "agent"]   # list
```

```python
port = config.get("app_port")        # int: 8001
debug = config.get("debug")          # bool: True
timeout = config.get("timeout")      # float: 60.5
tags = config.get("tags")            # list: ["api", "agent"]
```

### Environment Variables

Dynaconf automatically reads environment variables:

```bash
export APP_NAME="my-agent"
export APP_PORT=8002
export DEBUG=true
```

```python
config.get("app_name")  # "my-agent"
config.get("app_port")  # 8002 (int)
config.get("debug")     # True (bool)
```

**Naming convention:**
- Use uppercase: `APP_NAME`, `LOG_LEVEL`
- Use underscores: `AI_MODEL_API_KEY`
- Nested values: `EMAIL__SMTP_HOST` (double underscore)

## Environment-Specific Settings

### Switch Environments

```bash
# Development
export ENVIRONMENT=development
python -m uvicorn custom.src.main:app --reload

# Staging
export ENVIRONMENT=staging
python -m uvicorn custom.src.main:app

# Production
export ENVIRONMENT=production
python -m uvicorn custom.src.main:app --workers 4
```

### Environment Detection

```python
from base.src.config import Config

config = Config()

# Check current environment
env = config.get("environment", "development")

if env == "production":
    # Production-specific logic
    pass
elif env == "development":
    # Development-specific logic
    pass
```

## Nested Configuration

### Define Nested Settings

```toml
[default.database]
host = "localhost"
port = 5432
name = "mydb"
pool_size = 10

[default.email]
smtp_host = "smtp.example.com"
smtp_port = 587
from_address = "noreply@example.com"
enabled = true

[default.cache]
backend = "redis"
host = "localhost"
port = 6379
ttl = 3600
```

### Access Nested Settings

```python
# Method 1: Dot notation
db_host = config.get("database.host")
smtp_host = config.get("email.smtp_host")

# Method 2: Get section
database = config.get("database")
db_host = database["host"]
db_port = database["port"]

email = config.get("email")
if email["enabled"]:
    send_email(email["smtp_host"], email["from_address"])
```

### Environment Variables for Nested

Use double underscore `__` for nested values:

```bash
export DATABASE__HOST=prod-db.example.com
export DATABASE__PORT=5432
export EMAIL__SMTP_HOST=smtp.prod.example.com
```

## Validation

### Validate Required Settings

```python
from base.src.config import Config

def validate_config(config: Config):
    """Validate required configuration."""
    required = [
        "app_name",
        "ai_model_api_key",
        "ai_model_provider",
    ]
    
    missing = []
    for key in required:
        if not config.get(key):
            missing.append(key)
    
    if missing:
        raise ValueError(f"Missing required configuration: {', '.join(missing)}")

# In main.py
config = Config()
validate_config(config)
```

### Validate Types

```python
def validate_types(config: Config):
    """Validate configuration types."""
    port = config.get("app_port")
    if not isinstance(port, int):
        raise TypeError(f"app_port must be int, got {type(port)}")
    
    if port < 1 or port > 65535:
        raise ValueError(f"app_port must be 1-65535, got {port}")
    
    timeout = config.get("ai_model_timeout")
    if not isinstance(timeout, (int, float)):
        raise TypeError(f"ai_model_timeout must be number, got {type(timeout)}")
```

### Validate Values

```python
def validate_values(config: Config):
    """Validate configuration values."""
    provider = config.get("ai_model_provider")
    valid_providers = ["openai", "vllm", "anthropic"]
    
    if provider not in valid_providers:
        raise ValueError(
            f"ai_model_provider must be one of {valid_providers}, got {provider}"
        )
    
    log_level = config.get("log_level")
    valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    
    if log_level not in valid_levels:
        raise ValueError(
            f"log_level must be one of {valid_levels}, got {log_level}"
        )
```

## Advanced Features

### Multiple Configuration Files

```python
from dynaconf import Dynaconf

config = Dynaconf(
    settings_files=[
        "settings.toml",
        "settings.local.toml",  # Local overrides
        "secrets.toml",
    ],
    environments=True,
    env_switcher="ENVIRONMENT",
)
```

### Configuration Merging

```toml
# settings.toml
[default]
features = ["feature1", "feature2"]

[production]
# Merge with default
dynaconf_merge = true
features = ["feature3"]  # Results in ["feature1", "feature2", "feature3"]
```

### Lazy Loading

```python
# Configuration is loaded on first access
config = Config()

# Not loaded yet
app_name = config.get("app_name")  # Loaded now
```

### Reload Configuration

```python
# Reload from files (useful for testing)
config.reload()
```

## Best Practices

### 1. Use Environment-Specific Sections

```toml
[default]
log_level = "INFO"
debug = false

[development]
log_level = "DEBUG"
debug = true

[production]
log_level = "WARNING"
debug = false
```

### 2. Never Commit Secrets

```bash
# .gitignore
secrets.toml
.secrets.*
.env
*.key
```

### 3. Provide Defaults

```python
# Always provide sensible defaults
timeout = config.get("ai_model_timeout", 60)
log_level = config.get("log_level", "INFO")
max_retries = config.get("max_retries", 3)
```

### 4. Document Settings

```toml
[default]
# Maximum invoice amount to process (in EUR)
# Values above this will be flagged for manual review
max_invoice_amount = 100000

# AI model request timeout in seconds
# Increase for slower models or complex prompts
ai_model_timeout = 60
```

### 5. Validate on Startup

```python
# In main.py
from base.src.app_builder import AppBuilder

builder = AppBuilder()
config = builder.config

# Validate before building app
validate_config(config)
validate_types(config)
validate_values(config)

app = builder.build()
```

### 6. Use Type Hints

```python
from typing import Optional

def get_timeout(config: Config) -> int:
    """Get AI model timeout in seconds."""
    timeout = config.get("ai_model_timeout", 60)
    if not isinstance(timeout, int):
        raise TypeError(f"timeout must be int, got {type(timeout)}")
    return timeout

def get_api_key(config: Config) -> str:
    """Get AI model API key."""
    api_key = config.get("ai_model_api_key")
    if not api_key:
        raise ValueError("AI model API key not configured")
    return api_key
```

## Troubleshooting

### Configuration Not Loading

**Check:**
1. File exists: `ls -la custom/settings.toml`
2. Valid TOML: `python -c "import tomli; tomli.load(open('custom/settings.toml', 'rb'))"`
3. Correct working directory
4. File permissions

**Debug:**
```python
from base.src.config import Config

config = Config()
print(f"Config files: {config.settings_files}")
print(f"Environment: {config.get('environment')}")
print(f"All settings: {config.as_dict()}")
```

### Environment Variables Not Working

**Check:**
1. Variable exported: `echo $APP_NAME`
2. Correct naming: Use uppercase with underscores
3. Application restarted after setting

**Debug:**
```bash
# Print all environment variables
env | grep -i app

# Test specific variable
python -c "import os; print(os.getenv('APP_NAME'))"
```

### Wrong Value Being Used

**Check priority:**
```python
# Show where value came from
value = config.get("log_level")
print(f"log_level = {value}")

# Check all sources
print(f"From settings.toml: {config.from_file('log_level')}")
print(f"From environment: {os.getenv('LOG_LEVEL')}")
```

### Nested Values Not Working

**Use double underscore:**
```bash
# Wrong
export DATABASE_HOST=localhost

# Correct
export DATABASE__HOST=localhost
```

## Example Configurations

### Minimal

```toml
# settings.toml
[default]
app_name = "my-agent"
ai_model_provider = "openai"
ai_model_name = "gpt-4"
```

```toml
# secrets.toml
[default]
ai_model_api_key = "sk-your-key"
```

### Complete

```toml
# settings.toml
[default]
# Application
app_name = "invoice-processor"
app_port = 8001
log_level = "INFO"

# AI Model
ai_model_provider = "openai"
ai_model_name = "gpt-4"
ai_model_timeout = 60
ai_model_max_retries = 3

# Database
[default.database]
host = "localhost"
port = 5432
name = "invoices"
pool_size = 10

# Cache
[default.cache]
backend = "redis"
host = "localhost"
port = 6379
ttl = 3600

# Email
[default.email]
enabled = true
smtp_host = "smtp.example.com"
smtp_port = 587
from_address = "noreply@example.com"

[development]
log_level = "DEBUG"
ai_model_timeout = 120

[production]
log_level = "WARNING"
app_name = "invoice-processor-prod"
```

## See Also

- [Agent Configuration](agent-configuration.md) - Complete agent settings
- [OpenTelemetry Configuration](opentelemetry.md) - Tracing and observability
- [Getting Started](../getting-started.md) - Initial setup
