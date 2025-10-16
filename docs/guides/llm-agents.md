# Working with AI Agents

**Time to complete:** 20 minutes  
**Difficulty:** Beginner

This guide shows you how to create and use AI agents in your handlers.

## What is an AI Agent?

An **AI agent** is like a smart assistant that:
- Reads your instructions
- Uses tools you give it (like calculators)
- Returns structured results

Think of it as: **You give instructions → Agent thinks → Agent returns answer**

## How Agents Work in This Framework

### The Simple Flow

```
1. Build Agent (in main.py)
   ↓
2. Register Agent (in main.py)
   ↓
3. Use Agent (in handler)
```

## Building an Agent

### Step 1: Build in main.py

Agents are built using the **AgentBuilder** pattern:

```python
from base.src.agent import AgentBuilder
from pydantic_ai import Tool

# Build your agent
invoice_agent = (
    AgentBuilder(config, runtime_name="invoice_analyzer")
    .with_model_from_config("invoice_analyzer")           # Which AI model?
    .with_system_prompt_file("invoice_analyzer")          # What's its role?
    .with_tools([calculate_tool])                         # What can it do?
    .with_result_type(InvoiceAnalysisOutput)             # What does it return?
    .build()
)
```

### Step 2: Register the Agent

```python
app = (
    AppBuilder(settings_files=settings_files, root_path=project_root)
    .with_handler(MyHandler)
    .with_agent(invoice_agent)    # Register your agent
    .build()
)
```

### Step 3: Use in Handler

```python
class MyHandler(EventHandler):
    async def handle_event(self, event, context):
        # Get the agent
        agent = self._get_agent("invoice_analyzer")
        
        # Run it with an instruction
        result = await agent.run("Analyze this invoice: ...")
        
        return {"result": result.data}
```

## Complete Example

### 1. Create a Tool (in services)

Tools are functions the agent can call:

```python
# In custom/src/services/invoice_services.py
class InvoiceProcessingLogic:
    @staticmethod
    async def calculate_invoice_tool(ctx, invoice):
        """Calculate invoice totals."""
        total = sum(item.price * item.quantity for item in invoice.line_items)
        tax = total * 0.19
        
        return InvoiceAnalysisOutput(
            invoice_id=invoice.invoice_id,
            total_amount=total + tax,
            tax_amount=tax
        )
```

### 2. Build the Agent (in main.py)

```python
from pydantic_ai import Tool
from .services import InvoiceProcessingLogic

# Build agent with the tool
invoice_agent = (
    AgentBuilder(config, "invoice_analyzer")
    .with_model_from_config("invoice_analyzer")
    .with_system_prompt_file("invoice_analyzer")
    .with_tools([
        Tool(
            name="calculate_invoice",
            function=InvoiceProcessingLogic.calculate_invoice_tool
        )
    ])
    .with_result_type(InvoiceAnalysisOutput)
    .build()
)

# Register it
app = (
    AppBuilder(...)
    .with_agent(invoice_agent)
    .build()
)
```

### 3. Use in Handler

```python
class InvoiceHandler(EventHandler):
    async def handle_event(self, event, context):
        # Get agent
        agent = self._get_agent("invoice_analyzer")
        
        # Prepare instruction
        instruction = f"""
        Analyze this invoice and calculate totals:
        {event.data['invoice_text']}
        
        Use the calculate_invoice tool to verify calculations.
        """
        
        # Run agent
        result = await agent.run(instruction)
        
        return {
            "status": "success",
            "analysis": result.data
        }
```

## Using Prompt Files

### Why Use Prompt Files?

- **Change prompts without code changes**
- **Different prompts per environment**
- **Version control your prompts**

### System Prompts (Agent's Role)

File: `custom/src/prompts/invoice_analyzer.prompt`
```
You are an expert invoice analyzer.
Your job is to extract invoice details and verify calculations.

Always use the calculate_invoice tool to verify totals.
Be precise with numbers and dates.
```

### Instruction Prompts (What to Do)

File: `custom/src/prompts/invoice_instruction.prompt`
```
Analyze this invoice and extract all information:

{invoice_text}

Priority: {priority}
Customer Type: {customer_type}

Extract:
- Invoice number and date
- Line items with prices
- Tax and total amounts
```

Use in handler:
```python
from base.src.agent import PromptLoader

instruction = PromptLoader.load_instruction_prompt(
    "invoice_instruction",
    self.__class__,
    invoice_text=event.data["text"],
    priority="high",
    customer_type="premium"
)

result = await agent.run(instruction)
```

## Agent Configuration

### In settings.toml

```toml
[runtime.invoice_analyzer]
model_name = "gpt-4"
temperature = 0.1
max_tokens = 2000

[runtime.invoice_analyzer.prompt]
system_prompt_name = "invoice_analyzer"
```

### Override in Environment

```bash
# Change model at runtime
RUNTIME__INVOICE_ANALYZER__MODEL_NAME=gpt-4-turbo

# Change prompt location
PROMPT__CUSTOM_PATH=/custom/prompts
```

## Multiple Agents

You can have different agents for different tasks:

```python
# Invoice analyzer
invoice_agent = (
    AgentBuilder(config, "invoice_analyzer")
    .with_model("gpt-4")
    .with_system_prompt_file("invoice_analyzer")
    .with_tools([calculate_tool])
    .build()
)

# Document classifier
classifier_agent = (
    AgentBuilder(config, "document_classifier")
    .with_model("gpt-3.5-turbo")
    .with_system_prompt_file("document_classifier")
    .build()
)

# Register both
app = (
    AppBuilder(...)
    .with_agent(invoice_agent)
    .with_agent(classifier_agent)
    .build()
)
```

Use in handlers:
```python
# Handler 1: Classify document
agent = self._get_agent("document_classifier")
doc_type = await agent.run("What type of document is this?")

# Handler 2: Process based on type
if doc_type == "invoice":
    agent = self._get_agent("invoice_analyzer")
    result = await agent.run("Analyze this invoice...")
```

## Result Types

Define what the agent returns:

```python
from pydantic import BaseModel

class InvoiceAnalysisOutput(BaseModel):
    invoice_id: str
    total_amount: float
    tax_amount: float
    line_items: list[dict]
    confidence: float
```

Use in agent:
```python
agent = (
    AgentBuilder(config, "invoice_analyzer")
    .with_result_type(InvoiceAnalysisOutput)
    .build()
)
```

The agent will return structured data:
```python
result = await agent.run(instruction)
print(result.data.invoice_id)      # "INV-001"
print(result.data.total_amount)    # 1234.56
```

## Common Patterns

### Pattern 1: Agent with Multiple Tools

```python
agent = (
    AgentBuilder(config, "multi_tool_agent")
    .with_tools([
        Tool("calculate", calculate_fn),
        Tool("validate", validate_fn),
        Tool("lookup", lookup_fn)
    ])
    .build()
)
```

### Pattern 2: Different Instructions for Different Cases

```python
if event.data.get("urgent"):
    instruction = PromptLoader.load_instruction_prompt(
        "urgent_instruction",
        self.__class__,
        data=event.data
    )
else:
    instruction = PromptLoader.load_instruction_prompt(
        "standard_instruction",
        self.__class__,
        data=event.data
    )

result = await agent.run(instruction)
```

### Pattern 3: Agent Error Handling

```python
try:
    agent = self._get_agent("invoice_analyzer")
    result = await agent.run(instruction)
    
    return {"status": "success", "result": result.data}
    
except ValueError as e:
    return {"status": "error", "message": str(e)}
```

## Tips for Junior Developers

1. **Start Simple** - Begin with one agent, no tools
2. **Test Prompts** - Try different instructions to see what works
3. **Use Tools** - Let agents call functions for complex calculations
4. **Structure Output** - Always use result types (Pydantic models)
5. **Handle Errors** - Agents can fail, always use try/except
6. **Prompt Files** - Put prompts in files, not code
7. **One Agent, One Job** - Don't make agents do everything

## Troubleshooting

**Agent not found?**
```python
# Make sure you registered it
app = AppBuilder(...).with_agent(my_agent).build()
```

**Wrong results?**
- Check your system prompt
- Make instruction more specific
- Add examples to the prompt

**Agent too slow?**
- Use faster model (gpt-3.5-turbo)
- Reduce max_tokens
- Simplify the task

## Next Steps

- Learn about [Event Handlers](./handlers.md)
- Understand [Configuration](./configuration/agent-configuration.md)
- Read about [Testing](./testing.md)
