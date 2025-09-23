---
description: Automatically update API reference documentation when endpoints or schemas change
auto_execution_mode: 1
---

## Update API Reference Documentation Workflow

This workflow helps maintain up-to-date API reference documentation by tracking changes to endpoints, schemas, and API-related modifications.

### Step 1: Gather API Change Information
Collect the following information about the API change:

**Required Information:**
- **API Change Type**: Choose from: new_endpoint, endpoint_update, schema_change, deprecation, removal
- **Change Description**: Detailed description of what changed (minimum 20 characters)

**Optional Information:**
- **Endpoint Path**: API endpoint path (e.g., `/v1/check-backup`) - required for endpoint-related changes
- **Affected Files**: Files that might need API documentation updates
- **Breaking Change**: Whether this is a breaking change requiring versioning

### Step 2: Prerequisites Check
Ensure these files exist before proceeding:
- `docs/api-reference.md` - Main API reference documentation
- `src/api/routes.py` - API routes implementation for reference

### Step 3: Analyze Current API State
1. **Extract Current Endpoints**: Scan the API routes file for existing endpoints
2. **Review Current Documentation**: Read the existing API reference to understand current state
3. **Identify Documentation Gaps**: Compare endpoints with documented APIs

### Step 4: Generate API Documentation Update

Based on the change type, create the appropriate documentation update:

#### For New Endpoints:
```markdown
### New Endpoint Added

**Endpoint**: `[Endpoint Path]`
**Method**: `[HTTP Method]`
**Description**: [Change Description]

#### Request Format
```json
[Request Schema]
```

#### Response Format
```json
[Response Schema]
```

#### Example Usage
```bash
curl -X [Method] "http://localhost:8000[Endpoint]" \
     -H "Content-Type: application/json" \
     -d '[Request Example]'
```
```

#### For Endpoint Updates:
```markdown
### Endpoint Updated

**Endpoint**: `[Endpoint Path]`
**Changes**: [Change Description]

⚠️ **Breaking Change**: [If applicable]
```

#### For Schema Changes:
```markdown
### Schema Changes

**Affected Endpoint**: `[Endpoint Path]`
**Schema Changes**: [Change Description]

⚠️ **Version Impact**: [If breaking changes]
```

#### For Deprecations:
```markdown
### Endpoint Deprecated

**Endpoint**: `[Endpoint Path]`
**Deprecation Notice**: [Change Description]
**Migration Path**: See migration guide for v2.0
```

#### For Removals:
```markdown
### Endpoint Removed

**Removed Endpoint**: `[Endpoint Path]`
**Removal Reason**: [Change Description]
**Migration Required**: Update integrations to use replacement endpoints
```

### Step 5: Update API Reference
1. Open `docs/api-reference.md`
2. Add the generated documentation update to the appropriate section
3. Ensure proper formatting and consistent structure
4. Update the table of contents if needed

### Step 6: Validation
Before finalizing, ensure:
- Change description is detailed and clear (minimum 20 characters)
- Endpoint path is provided for endpoint-related changes
- Breaking changes are clearly marked
- All required information is included

### Step 7: Post-Processing
1. Stage the API documentation changes: `git add docs/api-reference.md`
2. Review the updated API reference for accuracy
3. Consider notifying API consumers about changes
4. Update related documentation if needed

### Step 8: Special Considerations

**Breaking Changes:**
- Clearly mark breaking changes with warning symbols
- Consider if a new API version is needed
- Provide migration guidance for consumers
- Update integration tests if applicable

**New Endpoints:**
- Ensure proper OpenAPI/Swagger documentation
- Add request/response examples
- Include authentication requirements
- Document error responses

**Schema Changes:**
- Update related model documentation
- Consider backward compatibility
- Update client SDKs if applicable
- Add migration notes for existing users

### Error Handling
If the update fails:
- Verify that the API reference file exists and is accessible
- Check that the change description is provided
- Ensure endpoint path is specified for relevant change types
- Retry up to 2 times if needed

### Best Practices
- Keep API documentation in sync with implementation
- Use consistent formatting across all endpoints
- Include practical examples for each endpoint
- Document all possible response codes
- Keep change descriptions clear and actionable
