# Concept: Exception Handling

Learn how to handle errors gracefully in handlers, services, and agents.

---

## Why Exception Handling Matters

Errors happen. Your code should handle them gracefully:
- **Prevent crashes** — Application keeps running
- **Preserve messages** — Dapr retries failed events
- **Log errors** — Know what went wrong
- **Inform users** — Return meaningful error messages

---

## Exception Handling in Event Handlers

### Let Exceptions Propagate

**IMPORTANT:** When processing events, **always** raise exceptions if something goes wrong. This ensures that Dapr does not delete the message.

If you catch exceptions inside your handler, Dapr will consider the message as "processed" and delete it. This could lead to data loss.

```python
class InvoiceHandler(EventHandler):
    async def can_handle_event(self, event: CloudEvent, context) -> bool:
        return event.get_type() == "invoice.submitted"

    async def handle_event(self, event: CloudEvent, context) -> HandlerResult:
        data = event.get_data()

        try:
            # Process the event
            result = await self.process_invoice(data)

            # Return success
            return HandlerResult(
                event_type="invoice.processed",
                data=result
            )
        except Exception as e:
            # IMPORTANT: Re-raise the exception
            # This tells Dapr the message was NOT processed
            logger.error(f"Failed to process invoice: {e}")
            raise  # Let exception propagate
```

### What Gets Retried?

```python
class InvoiceHandler(EventHandler):
    async def handle_event(self, event: CloudEvent, context) -> HandlerResult:
        try:
            # This exception will be retried by Dapr
            result = await database.save_invoice(data)
        except DatabaseError as e:
            logger.error(f"Database error: {e}")
            raise  # Dapr will retry

        try:
            # This exception will NOT be retried (caught and handled)
            vendor = await external_api.lookup_vendor(data["vendor"])
        except APIError as e:
            logger.warning(f"API error: {e}")
            # Don't raise - handle gracefully
            vendor = {"name": "Unknown", "approved": False}

        return HandlerResult(
            event_type="invoice.processed",
            data={"vendor": vendor}
        )
```

---

## Exception Handling in Services

### Validate Input

```python
class InvoiceService(BusinessService):
    def get_name(self) -> str:
        return "invoice_service"

    async def analyze(self, invoice_text: str) -> dict:
        # Validate input
        if not invoice_text:
            raise ValueError("Invoice text is required")

        if len(invoice_text) > 100000:
            raise ValueError("Invoice text is too long")

        # Process invoice
        agent = self._component_registry.get_agent("invoice_analyzer")
        result = await agent.run(invoice_text)

        return result.data.model_dump()
```

### Handle External Failures

```python
class PaymentService(BusinessService):
    def get_name(self) -> str:
        return "payment_service"

    async def process_payment(self, amount: float, vendor_id: str) -> dict:
        try:
            # Try to process payment
            result = await payment_gateway.charge(amount, vendor_id)
            return {"success": True, "transaction_id": result.id}

        except PaymentGatewayError as e:
            # Log error but don't crash
            logger.error(f"Payment failed: {e}")

            # Return error response
            return {
                "success": False,
                "error": "Payment processing failed",
                "retry_after": 60  # Retry after 60 seconds
            }
```

### Cleanup on Error

```python
class FileProcessingService(BusinessService):
    def get_name(self) -> str:
        return "file_service"

    async def process_file(self, file_path: str) -> dict:
        temp_file = None

        try:
            # Create temporary file
            temp_file = await self.create_temp_file(file_path)

            # Process file
            result = await self.analyze_file(temp_file)

            return result

        except Exception as e:
            logger.error(f"File processing failed: {e}")
            raise

        finally:
            # Always cleanup temporary file
            if temp_file:
                await self.delete_temp_file(temp_file)
```

---

## Exception Handling in Agents

### Validate Agent Response

```python
from pydantic import ValidationError

class InvoiceHandler(EventHandler):
    async def handle_event(self, event: CloudEvent, context) -> HandlerResult:
        data = event.get_data()

        agent = self._component_registry.get_agent("invoice_analyzer")

        try:
            # Run agent
            result = await agent.run(data["invoice_text"])
            analysis = result.data

            # Validate response
            if not analysis.vendor:
                raise ValueError("Agent did not extract vendor")

            if analysis.amount <= 0:
                raise ValueError("Agent returned invalid amount")

            return HandlerResult(
                event_type="invoice.analyzed",
                data=analysis.model_dump()
            )

        except ValidationError as e:
            logger.error(f"Agent response validation failed: {e}")
            raise

        except ValueError as e:
            logger.error(f"Invalid agent response: {e}")
            raise
```

### Handle Agent Timeouts

```python
import asyncio

class InvoiceHandler(EventHandler):
    async def handle_event(self, event: CloudEvent, context) -> HandlerResult:
        data = event.get_data()

        agent = self._component_registry.get_agent("invoice_analyzer")

        try:
            # Run agent with timeout
            result = await asyncio.wait_for(
                agent.run(data["invoice_text"]),
                timeout=30.0  # 30 second timeout
            )

            return HandlerResult(
                event_type="invoice.analyzed",
                data=result.data.model_dump()
            )

        except asyncio.TimeoutError:
            logger.error("Agent analysis timed out")
            raise RuntimeError("Analysis took too long")

        except Exception as e:
            logger.error(f"Agent failed: {e}")
            raise
```

---

## REST API Error Handling

### Return Error Responses

```python
from fastapi import HTTPException

class InvoiceRestApi(RestApi):
    def _register_routes(self):
        @self.router.post("/analyze")
        async def analyze_invoice(request: AnalyzeRequest):
            try:
                service = self._component_registry.get_service("invoice_service")
                result = await service.analyze(request.invoice_text)
                return {"status": "success", "data": result}

            except ValueError as e:
                # Bad request
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid input: {str(e)}"
                )

            except RuntimeError as e:
                # Server error
                raise HTTPException(
                    status_code=500,
                    detail=f"Processing failed: {str(e)}"
                )
```

### Status Codes

```python
from fastapi import HTTPException

# 400 Bad Request - Client error
raise HTTPException(status_code=400, detail="Invalid input")

# 401 Unauthorized - Authentication required
raise HTTPException(status_code=401, detail="API key required")

# 403 Forbidden - Not allowed
raise HTTPException(status_code=403, detail="Access denied")

# 404 Not Found - Resource doesn't exist
raise HTTPException(status_code=404, detail="Invoice not found")

# 409 Conflict - Duplicate
raise HTTPException(status_code=409, detail="Invoice already exists")

# 500 Internal Server Error - Server error
raise HTTPException(status_code=500, detail="Processing failed")

# 503 Service Unavailable - Temporary issue
raise HTTPException(status_code=503, detail="Service temporarily unavailable")
```

---

## Logging Errors

### Log Levels

```python
import logging

logger = logging.getLogger(__name__)

# Debug - detailed information for debugging
logger.debug("Processing invoice: %s", invoice_id)

# Info - general information
logger.info("Invoice processed successfully: %s", invoice_id)

# Warning - something unexpected but not critical
logger.warning("Vendor not found, using default: %s", vendor_name)

# Error - something failed
logger.error("Failed to process invoice: %s", error)

# Critical - system failure
logger.critical("Database connection lost")
```

### Structured Logging

```python
logger.error(
    "Invoice processing failed",
    extra={
        "invoice_id": invoice_id,
        "vendor": vendor_name,
        "error": str(e),
        "attempt": 1
    }
)
```

---

## Real-World Example

### Complete Error Handling

```python
from fastapi import HTTPException
from pydantic import ValidationError
import asyncio

class InvoiceHandler(EventHandler):
    async def can_handle_event(self, event: CloudEvent, context) -> bool:
        return event.get_type() == "invoice.submitted"

    async def handle_event(self, event: CloudEvent, context) -> HandlerResult:
        data = event.get_data()
        invoice_id = data.get("invoice_id")

        try:
            # Validate input
            if not invoice_id:
                raise ValueError("Invoice ID is required")

            # Get services
            agent = self._component_registry.get_agent("invoice_analyzer")
            service = self._component_registry.get_service("invoice_service")

            # Run agent with timeout
            try:
                result = await asyncio.wait_for(
                    agent.run(data["invoice_text"]),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                logger.error(f"Agent timeout for invoice {invoice_id}")
                raise RuntimeError("Analysis took too long")

            # Validate response
            analysis = result.data
            if not analysis.vendor:
                raise ValueError("Agent did not extract vendor")

            # Save to database
            try:
                await service.save_analysis(invoice_id, analysis)
            except Exception as e:
                logger.error(f"Failed to save analysis: {e}")
                raise

            # Success
            logger.info(f"Processed invoice {invoice_id}")
            return HandlerResult(
                event_type="invoice.analyzed",
                data=analysis.model_dump()
            )

        except ValueError as e:
            logger.error(f"Validation error for invoice {invoice_id}: {e}")
            raise  # Dapr will retry

        except ValidationError as e:
            logger.error(f"Response validation error for invoice {invoice_id}: {e}")
            raise  # Dapr will retry

        except RuntimeError as e:
            logger.error(f"Processing error for invoice {invoice_id}: {e}")
            raise  # Dapr will retry

        except Exception as e:
            logger.critical(f"Unexpected error for invoice {invoice_id}: {e}")
            raise  # Dapr will retry
```

---

## Best Practices

1. **Always raise in handlers** — Let Dapr know if processing failed
2. **Catch specific exceptions** — Not just `Exception`
3. **Log errors** — Include context and error details
4. **Cleanup resources** — Use `finally` blocks
5. **Return meaningful errors** — Help users understand what went wrong
6. **Retry on failure** — Dapr will retry if you raise
7. **Set timeouts** — Prevent hanging requests
8. **Validate input** — Catch errors early

---

## Common Patterns

### Retry with Exponential Backoff

```python
import asyncio

async def retry_with_backoff(func, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise

            wait_time = 2 ** attempt  # 1, 2, 4 seconds
            logger.warning(f"Attempt {attempt + 1} failed, retrying in {wait_time}s: {e}")
            await asyncio.sleep(wait_time)
```

### Fallback Handler

```python
class InvoiceHandler(EventHandler):
    async def handle_event(self, event: CloudEvent, context) -> HandlerResult:
        try:
            # Try primary processing
            return await self.process_with_ai(event)
        except Exception as e:
            logger.error(f"AI processing failed: {e}")
            # Fallback to simpler processing
            return await self.process_with_rules(event)
```

### Circuit Breaker

```python
class PaymentService(BusinessService):
    def __init__(self):
        self.failures = 0
        self.max_failures = 5

    async def process_payment(self, amount: float) -> dict:
        if self.failures >= self.max_failures:
            raise RuntimeError("Payment service is down")

        try:
            result = await payment_gateway.charge(amount)
            self.failures = 0  # Reset on success
            return result
        except Exception as e:
            self.failures += 1
            raise
```

---

## Next Steps

- [Tools](tools.md) — Give agents functions to call
- [Response Handling](response-handling.md) — Parse and validate responses
- [Health Checks](health-checks.md) — Monitor service health
