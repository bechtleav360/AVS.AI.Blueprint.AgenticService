# Windsurf Rules

This directory contains Windsurf rules that define code conventions, architecture constraints, and best practices for the Blueprint Agents framework.

## Active Rules

All rules are set to `trigger: always_on` to ensure consistent code quality and architecture compliance.

### 1. Architecture Conventions (`architecture-conventions.md`)
- Component-based architecture patterns
- Dependency injection rules
- Registration order requirements
- Configuration access patterns
- Directory layout standards
- Dependency flow constraints

### 2. Code Style and Quality (`code-style-quality.md`)
- Object-oriented design principles
- Type annotation requirements
- Async/await conventions
- Import organization
- Docstring standards
- Error message formatting
- Logging conventions
- Method naming patterns
- Pydantic model usage

### 3. Security and Error Handling (`security-error-handling.md`)
- Secure coding practices (API keys, input validation)
- SQL injection prevention
- Path traversal prevention
- Exception hierarchy and handling
- Context manager usage
- Error recovery patterns
- REST API error handling
- Sensitive data logging
- Timeout configuration
- Rate limiting

### 4. Testing Conventions (`testing-conventions.md`)
- Test organization and structure
- Component testing patterns
- Mocking best practices
- Fixture usage
- Async testing
- Test coverage requirements
- Assertion patterns
- Test data management
- Integration testing
- Performance testing

### 5. Strict OOP (`strict-oop.md`)
- Enforce object-oriented code style
- No global functions or variables
- Use singleton pattern only when absolutely necessary

## Usage

These rules are automatically applied by Windsurf Cascade when working on the codebase. They complement the workflows in `.windsurf/workflows/` which provide step-by-step guides for specific tasks.

## Rules vs Workflows

- **Rules**: Define "what" and "how" - conventions, constraints, and best practices
- **Workflows**: Define "when" and "steps" - procedural guides for specific tasks

For example:
- **Rule**: "Always resolve dependencies in `on_startup()`, never in `__init__`"
- **Workflow**: Step-by-step guide to create a new EventHandler component

## Updating Rules

When updating rules:
1. Keep them focused on conventions and constraints
2. Avoid duplicating workflow content
3. Use concrete examples (✅ Good / ❌ Bad)
4. Reference official documentation where applicable
5. Test that rules don't conflict with existing code patterns
