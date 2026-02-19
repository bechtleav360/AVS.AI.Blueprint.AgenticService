---
description: Keep testing documentation synchronized with actual test implementations
auto_execution_mode: 1
---

## Sync Test Documentation with Code Workflow

This workflow helps maintain synchronization between testing documentation and actual test implementations, ensuring documentation reflects current testing practices.

### Step 1: Choose Sync Mode
Select the synchronization mode:
- **analyze_only**: Analyze current state without making changes
- **update_documentation**: Update documentation based on code analysis
- **update_tests**: Update test code based on documentation
- **bidirectional**: Synchronize both ways where appropriate

### Step 2: Configure Focus Areas
Choose what aspects to focus on:
- **test_structure**: Directory structure and organization
- **test_patterns**: Testing patterns and conventions
- **best_practices**: Testing best practices and guidelines
- **examples**: Code examples and sample implementations
- **configuration**: Test configuration and setup

### Step 3: Prerequisites Check
Ensure these exist before proceeding:
- `docs/testing-guide.md` - Main testing documentation
- `tests/` directory - Test implementations directory

### Step 4: Analyze Test Structure
1. List all files and directories in the `tests/` directory recursively
2. Identify the overall test organization and structure
3. Count total number of test files and functions

### Step 5: Extract Test Functions
Search for test function definitions in the codebase:
- Look for functions starting with `test_` pattern
- Identify different types of tests (unit, integration, API, etc.)
- Categorize tests by functionality and scope

### Step 6: Read Current Documentation
1. Read the existing testing guide documentation
2. Understand current documented testing practices
3. Identify any outdated or missing information

### Step 7: Analyze Test Patterns
Analyze the actual test implementations to identify:
- **Naming Conventions**: How tests are named and organized
- **Test Structure**: Common patterns in test setup and execution
- **Mocking Patterns**: How dependencies are mocked or stubbed
- **Assertion Styles**: Common assertion patterns used
- **Setup/Teardown**: Common setup and cleanup patterns

### Step 8: Generate Analysis Report
Create a comprehensive analysis report:

```markdown
## Testing Patterns Analysis

**Analysis Date**: [Current Date]
**Tests Analyzed**: [Number of test functions found]
**Test Categories**: [Categories being analyzed]

### Current Test Structure
```
[Directory structure of tests]
```

### Test Naming Patterns
[List of naming patterns found]

### Common Testing Patterns
[List of structural patterns found]

### Mocking and Stubbing Patterns
[List of mocking approaches used]

### Assertion Styles
[List of assertion patterns used]

## Recommendations

[Analysis-based recommendations for documentation updates]

## Suggested Documentation Updates

### Test Structure Updates
[Recommended updates to reflect current structure]

### Best Practices
[Recommended best practices based on analysis]

### Code Examples
[Recommended code examples to add]

---
```

### Step 9: Update Documentation (Optional)
Based on sync mode, update the testing guide:
1. Add analysis results to the documentation
2. Update test structure documentation
3. Add new testing patterns and examples
4. Update best practices section
5. Add code examples where needed

### Step 10: Generate Test Documentation
Create auto-generated documentation from test analysis:

```markdown
# Generated Test Documentation

This section is automatically generated from current test implementations.

## Test Structure
```
[Test directory structure]
```

## Test Functions by Category
[Grouped test functions by category]

## Testing Patterns Observed
- **Setup Patterns**: [Common setup patterns]
- **Assertion Styles**: [Common assertion approaches]
- **Mocking Approaches**: [Common mocking strategies]

*Auto-generated on [Current Date]*
```

### Step 11: Save Sync Report
Save the complete analysis report to `docs/test-sync-report.md` for reference and tracking.

### Step 12: Review and Validate
1. Review the analysis report findings
2. Verify that documentation updates are accurate
3. Check that recommendations are actionable
4. Ensure changes maintain documentation quality

### Step 13: Optional - Bidirectional Sync
If bidirectional mode is selected:
1. Identify areas where tests can be improved based on documentation
2. Suggest test improvements or additions
3. Update test implementations where appropriate

### Error Handling
If synchronization fails:
- Verify the `tests/` directory exists and contains test files
- Check that the testing guide documentation exists
- Ensure file permissions allow reading and writing
- Retry up to 2 times if needed

### Best Practices
- Run this workflow regularly to maintain sync
- Use analyze_only mode first to review changes before applying
- Focus on specific areas if the full sync is too broad
- Keep detailed reports for tracking documentation evolution
