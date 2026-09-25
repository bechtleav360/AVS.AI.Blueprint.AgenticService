# Component Naming Refactor - Simplified Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `asbs setup` and `asbs create api` to use component-name-based file naming and organize models in subfolders.

**Architecture:** Setup command passes `component_name` through config to generators for file naming. Create API command creates models in `models/{api_name}/` subfolder. Generator no longer creates agents folder (only agents folder removal, agent config processing stays). Setup never creates scheduler.

**Tech Stack:** Python, pathlib, part generators

---

## File Structure

**Files to modify:**
- `src/blueprint/agent_generator/generator/part_generators/part_generator_base.py` - Helper for component_name-based filenames
- `src/blueprint/agent_generator/generator/part_generators/handler_part_generator.py` - Use component_name for filename
- `src/blueprint/agent_generator/generator/part_generators/service_part_generator.py` - Use component_name for filename
- `src/blueprint/agent_generator/generator/part_generators/api_part_generator.py` - Use component_name for filename and models subfolder
- `src/blueprint/agent_generator/generator/part_generators/models_part_generator.py` - Use component_name for models subfolder path
- `src/blueprint/agent_generator/generator/generator.py` - Remove agents folder creation
- `src/blueprint/agent_generator/cli/commands/setup.py` - Add component_name to config, remove scheduler
- `src/blueprint/agent_generator/cli/commands/create.py` - Modify only create_api to create models subfolder

---

## Task 1: Update part_generator_base.py - Add filename helper

**Files:**
- Modify: `src/blueprint/agent_generator/generator/part_generators/part_generator_base.py`

**Goal:** Add method to calculate filenames using component_name.

- [ ] **Step 1: Read the file**

Run: `head -80 src/blueprint/agent_generator/generator/part_generators/part_generator_base.py`

Note the class structure and existing methods.

- [ ] **Step 2: Add get_output_filename method**

After `create_file()` method, add:

```python
def get_output_filename(self, component_type: str) -> str:
    """Get output filename with component_name prefix if available.
    
    Args:
        component_type: 'handler', 'service', 'api', or 'scheduler'
    
    Returns:
        Filename like 'order_validation_handler.py' if component_name in config,
        else returns self.output_file_name for backward compatibility
    """
    component_name = self.config.get("component_name", "")
    if not component_name:
        return self.output_file_name
    
    snake_name = self.camel_to_snake(component_name)
    return f"{snake_name}_{component_type}.py"
```

- [ ] **Step 3: Test**

Run: `pytest tests/agent_generator/ -v --tb=short`

Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/blueprint/agent_generator/generator/part_generators/part_generator_base.py
git commit -m "feat: add get_output_filename helper for component naming"
```

---

## Task 2: Update HandlerPartGenerator - Use component_name for filename

**Files:**
- Modify: `src/blueprint/agent_generator/generator/part_generators/handler_part_generator.py`

**Goal:** Handler files use component_name prefix.

- [ ] **Step 1: Read HandlerPartGenerator.__init__**

Run: `sed -n '/class HandlerPartGenerator/,/def.*methods start/p' src/blueprint/agent_generator/generator/part_generators/handler_part_generator.py | head -30`

- [ ] **Step 2: Update __init__ to use component_name**

Modify the `self.output_file_name` assignment:

```python
class HandlerPartGenerator(PartGeneratorBase):
    def __init__(self, config: dict[str, Any], template_dir: str | Path, src_path: str, handler_name: str = "") -> None:
        super().__init__(config, template_dir, src_path)
        
        # Use component_name if available, else use handler_name
        component_name = config.get("component_name", "")
        if component_name:
            snake_name = self.camel_to_snake(component_name)
            self.output_file_name = f"{snake_name}_handler.py"
        else:
            self.output_file_name = f"{self.camel_to_snake(handler_name)}_handler.py"
        
        self.handler_name = handler_name or component_name
        self.template_file_name = "handler.txt"
        # ... rest unchanged
```

- [ ] **Step 3: Test**

Run: `pytest tests/agent_generator/ -v -k handler --tb=short`

Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/blueprint/agent_generator/generator/part_generators/handler_part_generator.py
git commit -m "feat: use component_name for handler filename"
```

---

## Task 3: Update ServicePartGenerator - Use component_name for filename

**Files:**
- Modify: `src/blueprint/agent_generator/generator/part_generators/service_part_generator.py`

**Goal:** Service files use component_name prefix.

- [ ] **Step 1: Update __init__ similarly**

Modify `self.output_file_name` assignment in ServicePartGenerator:

```python
class ServicePartGenerator(PartGeneratorBase):
    def __init__(self, config: dict[str, Any], template_dir: str | Path, src_path: str, service_name: str = "") -> None:
        super().__init__(config, template_dir, src_path)
        
        # Use component_name if available, else use service_name
        component_name = config.get("component_name", "")
        if component_name:
            snake_name = self.camel_to_snake(component_name)
            self.output_file_name = f"{snake_name}_service.py"
        else:
            self.output_file_name = f"{self.camel_to_snake(service_name)}_service.py"
        
        self.service_name = service_name or component_name
        self.template_file_name = "service.txt"
        # ... rest unchanged
```

- [ ] **Step 2: Test**

Run: `pytest tests/agent_generator/ -v -k service --tb=short`

Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add src/blueprint/agent_generator/generator/part_generators/service_part_generator.py
git commit -m "feat: use component_name for service filename"
```

---

## Task 4: Update APIPartGenerator - Use component_name and models subfolder

**Files:**
- Modify: `src/blueprint/agent_generator/generator/part_generators/api_part_generator.py`

**Goal:** API files use component_name, models import path includes subfolder.

- [ ] **Step 1: Update __init__ for filename**

```python
class APIPartGenerator(PartGeneratorBase):
    def __init__(self, config: dict[str, Any], template_dir: str | Path, src_path: str) -> None:
        super().__init__(config, template_dir, src_path)
        
        # Use component_name if available
        component_name = config.get("component_name", "")
        if component_name:
            snake_name = self.camel_to_snake(component_name)
            self.output_file_name = f"{snake_name}_api.py"
        else:
            self.output_file_name = "routes.py"
        
        self.template_file_name = "routes.txt"
        self.template_vars["api_description"] = self.config["communication_layer"]["rest_api"]["description"]
        self.template_vars["imports"] = self._create_api_imports()
        # ... rest unchanged
```

- [ ] **Step 2: Update _create_api_imports() to use models subfolder**

Modify the method to include component_name subfolder in import path:

```python
def _create_api_imports(self) -> str:
    """Generate import statements for routes.py."""
    
    component_name = self.config.get("component_name", "")
    # If component_name exists, import from models/{component_name}
    if component_name:
        model_path = f"..models.{self.camel_to_snake(component_name)}"
    else:
        model_path = "..models"
    
    lines = []
    model_classes = list(self.config["communication_layer"]["rest_api"]["dto_classes"])
    model_classes.append(self.config["communication_layer"]["rest_api"]["mapper"]["name"])
    
    if len(model_classes) < 4:
        lines.append(f"from {model_path} import {', '.join(model_classes)}")
    else:
        lines.append(f"from {model_path} import (")
        for dto_class in model_classes:
            lines.append(f"    {dto_class},")
        lines[-1] = lines[-1][:-1]
        lines.append(")")
    
    # Services import unchanged
    service_classes = list(self.config["communication_layer"]["rest_api"]["uses_services"])
    if len(service_classes) < 4:
        lines.append(f"from ..services import {', '.join(service_classes)}")
    else:
        lines.append("from ..services import (")
        for service_class in service_classes:
            lines.append(f"    {service_class},")
        lines[-1] = lines[-1][:-1]
        lines.append(")")
    
    return "\n".join(lines)
```

- [ ] **Step 3: Test**

Run: `pytest tests/agent_generator/ -v -k api --tb=short`

Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/blueprint/agent_generator/generator/part_generators/api_part_generator.py
git commit -m "feat: use component_name for api filename and models subfolder imports"
```

---

## Task 5: Update ModelPartGenerator - Create models in component subfolder

**Files:**
- Modify: `src/blueprint/agent_generator/generator/part_generators/models_part_generator.py`

**Goal:** Model files created in `models/{component_name}/` subfolder.

- [ ] **Step 1: Add helper to ModelPartGenerator base class**

Add method to base class:

```python
def get_models_subfolder(self) -> str:
    """Get the subfolder for models based on component_name.
    
    Returns:
        Subfolder name (e.g., 'order_validation') or empty string if no component_name
    """
    component_name = self.config.get("component_name", "")
    if component_name:
        return self.camel_to_snake(component_name)
    return ""
```

- [ ] **Step 2: Update DTOPartGenerator.__init__**

```python
class DTOPartGenerator(ModelPartGenerator):
    def __init__(self, config: dict[str, Any], template_dir: str | Path, src_path: str) -> None:
        super().__init__(config, template_dir, src_path)
        self.template_file_name = "dto.txt"
        
        subfolder = self.get_models_subfolder()
        if subfolder:
            self.output_file_name = f"{subfolder}/dto.py"
            self.src_path = f"{src_path}/{subfolder}"
        else:
            self.output_file_name = "dto.py"
        
        self.template_vars["dto_classes"] = self._generate_model_classes(self.config["communication_layer"]["rest_api"]["dto_classes"])
```

- [ ] **Step 3: Update DomainModelPartGenerator.__init__**

```python
class DomainModelPartGenerator(ModelPartGenerator):
    def __init__(self, config: dict[str, Any], template_dir: str | Path, src_path: str) -> None:
        super().__init__(config, template_dir, src_path)
        self.template_file_name = "domain_models.txt"
        
        subfolder = self.get_models_subfolder()
        if subfolder:
            self.output_file_name = f"{subfolder}/domain_models.py"
            self.src_path = f"{src_path}/{subfolder}"
        else:
            self.output_file_name = "domain_models.py"
        
        self.template_vars["domain_model_classes"] = self._generate_model_classes(self.config["domain_models"])
```

- [ ] **Step 4: Update MapperPartGenerator.__init__**

```python
class MapperPartGenerator(ModelPartGenerator):
    def __init__(self, config: dict[str, Any], template_dir: str | Path, src_path: str) -> None:
        super().__init__(config, template_dir, src_path)
        self.template_file_name = "mapper.txt"
        
        subfolder = self.get_models_subfolder()
        if subfolder:
            self.output_file_name = f"{subfolder}/mapper.py"
            self.src_path = f"{src_path}/{subfolder}"
        else:
            self.output_file_name = "mapper.py"
        
        self.template_vars["imports"] = self._create_mapper_imports()
        self.template_vars["mapper_class"] = self._generate_mapper_class()
```

- [ ] **Step 5: Test**

Run: `pytest tests/agent_generator/ -v -k model --tb=short`

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/blueprint/agent_generator/generator/part_generators/models_part_generator.py
git commit -m "feat: create models in component subfolder"
```

---

## Task 6: Update generator.py - Remove agents folder creation

**Files:**
- Modify: `src/blueprint/agent_generator/generator/generator.py`

**Goal:** Remove agents folder creation, but keep agent config processing in main.py.

- [ ] **Step 1: Find agent creation section**

Run: `grep -n "for agent_name in self.config" src/blueprint/agent_generator/generator/generator.py`

- [ ] **Step 2: Remove the agents folder creation loop**

Find the section that creates agent prompts and delete it:

```python
# DELETE THIS SECTION:
for agent_name in self.config["agent_layer"]:
    CopyPartGenerator(
        self.config,
        self.template_dir,
        "src/prompts",
        "prompt.prompt",
        f"{self.config['agent_layer'][agent_name]['runtime_name']}_system.prompt",
    ).create_file(out)

    CopyPartGenerator(
        self.config,
        self.template_dir,
        "src/prompts",
        "prompt.prompt",
        f"{self.config['agent_layer'][agent_name]['runtime_name']}_instruction.prompt",
    ).create_file(out)
```

Keep everything else. Agents are still in main.py config, just no folder creation.

- [ ] **Step 3: Test**

Run: `pytest tests/agent_generator/ -v --tb=short`

Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/blueprint/agent_generator/generator/generator.py
git commit -m "feat: remove agents folder creation from setup (agent config processing stays)"
```

---

## Task 7: Update setup.py - Add component_name to config

**Files:**
- Modify: `src/blueprint/agent_generator/cli/commands/setup.py`

**Goal:** Pass component_name to config for file naming.

- [ ] **Step 1: Find create_basic_config function**

Run: `sed -n '/def create_basic_config/,/^def /p' src/blueprint/agent_generator/cli/commands/setup.py | head -50`

- [ ] **Step 2: Add component_name to returned config**

Add this line to the config dict:

```python
def create_basic_config(name: str) -> dict[str, Any]:
    """Create a basic configuration template."""
    # ... existing code ...
    
    return {
        "name": name,
        "component_name": name,  # ADD THIS LINE
        "description": f"{name} agent microservice",
        # ... rest of config unchanged
    }
```

- [ ] **Step 3: Test setup command**

Run:
```bash
cd /tmp && rm -rf TestSetup && asbs setup TestSetup
ls -la TestSetup/src/handlers/
ls -la TestSetup/src/services/
ls -la TestSetup/src/api/
ls -la TestSetup/src/models/
```

Expected:
- `test_setup_handler.py` in handlers/
- `test_setup_service.py` in services/
- `test_setup_api.py` in api/
- `test_setup/` subfolder in models/ with domain_models.py, dto.py, mapper.py

- [ ] **Step 4: Commit**

```bash
git add src/blueprint/agent_generator/cli/commands/setup.py
git commit -m "feat: add component_name to setup config for consistent file naming"
```

---

## Task 8: Update create.py - Modify create_api for models subfolder

**Files:**
- Modify: `src/blueprint/agent_generator/cli/commands/create.py`

**Goal:** Create API models in subfolder structure.

- [ ] **Step 1: Find create_api function**

Run: `sed -n '/^def create_api/,/^def /p' src/blueprint/agent_generator/cli/commands/create.py | head -80`

- [ ] **Step 2: Modify models directory handling**

Change how models are created. Find the section that creates models_file and modify:

```python
def create_api(args: Namespace) -> None:
    """Create a RestApi component with separate models file."""
    
    api_output_dir = Path(args.output_dir)
    api_output_dir.mkdir(parents=True, exist_ok=True)

    # Use naming utilities to normalize the API name
    class_name, snake_name, file_name = normalize_component_name(
        args.name, "api"
    )

    file_name = file_name.replace("-", "_")
    module_name = file_name[:-3]  # Remove .py extension
    api_output_file = api_output_dir / file_name

    if api_output_file.exists():
        print(f"Error: File already exists: {api_output_file}", file=sys.stderr)
        sys.exit(1)

    # Create models directory structure with component subfolder
    project_root = Path.cwd()
    models_dir = project_root / "src" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    
    # Create component-specific subfolder for models
    component_snake_name = _to_snake_case(args.name)
    component_models_dir = models_dir / component_snake_name
    component_models_dir.mkdir(parents=True, exist_ok=True)

    # Generate request/response class names
    request_class_name = f"{class_name.replace('Api', '')}Request"
    response_class_name = f"{class_name.replace('Api', '')}Response"

    # Models files go in subfolder
    models_file = component_models_dir / "dto.py"
    models_module_name = f"{component_snake_name}.dto"
    
    if models_file.exists():
        print(f"Error: File already exists: {models_file}", file=sys.stderr)
        sys.exit(1)

    # ... rest of function (generate models code and write files)
    
    # Update imports to use subfolder path
    models_import_statement = (
        f"from src.models.{component_snake_name}.dto import "
        f"{request_class_name}, {response_class_name}"
    )
    # ... rest unchanged
```

- [ ] **Step 3: Test create api command**

Run (in a project directory):
```bash
asbs create api TestPayment
ls -la src/api/
ls -la src/models/test_payment/
```

Expected:
- `test_payment_api.py` in src/api/
- `test_payment/` subfolder in src/models/ with dto.py

- [ ] **Step 4: Commit**

```bash
git add src/blueprint/agent_generator/cli/commands/create.py
git commit -m "feat: create api models in component subfolder"
```

---

## Task 9: Integration test - Verify setup and create_api behavior

**Files:**
- (Testing only - no new files)

**Goal:** Manual verification of setup and create_api commands.

- [ ] **Step 1: Test setup with new naming**

```bash
cd /tmp
rm -rf OrderValidation
asbs setup OrderValidation
cd OrderValidation

# Verify file naming
ls src/handlers/order_validation_handler.py
ls src/services/order_validation_service.py
ls src/api/order_validation_api.py
ls -la src/models/order_validation/
```

Expected: All files exist with correct names and models in subfolder.

- [ ] **Step 2: Test create_api in existing project**

```bash
cd /tmp/OrderValidation
asbs create api PaymentService
ls src/api/payment_service_api.py
ls -la src/models/payment_service/
```

Expected: API file and models subfolder created correctly.

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/agent_generator/ -v --tb=short
```

Expected: All tests pass.

- [ ] **Step 4: Verify no agents folder created**

```bash
cd /tmp && rm -rf TestAgent && asbs setup TestAgent
ls -la TestAgent/src/
```

Expected: No agents folder exists (agents config stays in main.py, just no folder).

- [ ] **Step 5: Commit if needed**

If any fixes were needed from testing, commit them:

```bash
git add -A
git commit -m "fix: address issues from integration testing"
```

---

## Summary

**Total tasks:** 9
**Scope:** Minimal, focused changes
- Setup: Use component_name for file naming, remove agents folder creation
- Create API: Create models in subfolder
- Generators: Add component_name support (backward compatible)
- Generator: Remove agents folder creation

**No changes to:**
- naming_utils.py
- Other create commands (handler, service, scheduler)
- Agent config processing

---

Plan complete. Ready for subagent-driven execution.