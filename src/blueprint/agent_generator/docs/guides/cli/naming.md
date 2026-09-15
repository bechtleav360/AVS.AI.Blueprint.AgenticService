# Naming Conventions and Auto-Registration

All `asbs create` commands follow consistent naming conventions and automatically register components in `src/main.py`.

## Input Flexibility

The CLI accepts component names in multiple formats and normalizes them to proper class and file names:

- **snake_case**: `order_placed` → `OrderPlacedHandler`
- **CamelCase**: `OrderPlaced` → `OrderPlacedHandler`
- **kebab-case**: `order-placed` → `OrderPlacedHandler`

All formats are converted to proper class names without double suffixes (e.g., never `OrderPlacedHandlerHandler`).

## Component Naming

Each component type follows a consistent suffix pattern:

| Component Type | Input | Class Name | File Name | Notes |
|---|---|---|---|---|
| **Handler** | `order_placed` | `OrderPlacedHandler` | `order_placed_handler.py` | Handles events |
| **Service** | `invoice_processor` | `InvoiceProcessorService` | `invoice_processor_service.py` | Contains business logic |
| **API** | `order_management` | `OrderManagementApi` | `order_management_api.py` | REST endpoints + models file |
| **Agent** | `document_analyzer` | -- | -- | No module of its own: a builder in `main.py` plus two prompt files |
| **Scheduler** | `cleanup` | `CleanupScheduler` | `cleanup_scheduler.py` | Background tasks |

## Name Normalization Examples

The CLI handles various input formats correctly:

### Handler Examples
```bash
asbs create handler order_placed     # Snake case input
asbs create handler OrderPlaced      # CamelCase input
asbs create handler order-placed     # Kebab-case input
# All produce: OrderPlacedHandler in order_placed_handler.py
```

### Service Examples
```bash
asbs create service user_manager
asbs create service UserManager
asbs create service user-manager
# All produce: UserManagerService in user_manager_service.py
```

### API Examples
```bash
asbs create api product_catalog
asbs create api ProductCatalog
asbs create api product-catalog
# All produce: ProductCatalogApi in product_catalog_api.py
# And the models package src/models/product_catalog/ (dto, domain_models, mapper)
```

### Agent Examples
```bash
asbs create agent document_analyzer
asbs create agent DocumentAnalyzer
asbs create agent document-analyzer
# All produce the runtime name: document_analyzer_agent
# Declared in src/main.py as an AgentBuilder; prompts in src/prompts/
```

## Auto-Registration

When you create a component, the CLI automatically:

1. **Creates the component file** in the appropriate directory
2. **Adds imports** to `src/main.py`
3. **Registers with AppBuilder** in the chain

If auto-registration fails (e.g., `src/main.py` not found), the CLI displays a clear error message with manual registration instructions.

### Example Auto-Registration Output

```bash
$ asbs create handler order_placed
✓ Created handler: src/handlers/order_placed_handler.py
✓ Auto-registered in src/main.py
  - Added import: from src.handlers.order_placed_handler import OrderPlacedHandler
  - Added registration: .with_handler(OrderPlacedHandler)
```
