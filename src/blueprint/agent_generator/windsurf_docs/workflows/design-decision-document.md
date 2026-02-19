---
description: Capture and summarize design decisions from discussions and implementation changes
auto_execution_mode: 1
---

## Document Design Decision Workflow

This workflow helps capture and document important design decisions made during project development.

### Step 1: Gather Decision Information
Collect the following information about the design decision:

- **Decision Title**: A clear, descriptive title for the decision
- **Category**: Choose from: architecture, technology_stack, data_design, security, performance, scalability, usability, maintainability
- **Context**: The problem statement and background that led to this decision
- **Rationale**: Detailed explanation of why this approach was chosen
- **Alternatives Considered**: Other approaches that were evaluated and rejected (optional)
- **Trade-offs**: Any compromises or limitations of this decision (optional)
- **Consequences**: Long-term implications and effects (optional)
- **Related Components**: Affected system components (optional)
- **Status**: Current status (proposed, approved, implemented, deprecated, superseded)

### Step 2: Prerequisites Check
Ensure these files exist before proceeding:
- `docs/design-decisions.md` - Main design decisions documentation
- `docs/architecture.md` - Architecture documentation for reference

### Step 3: Read Current Documentation
Read the existing design decisions document to understand the current structure and context.

### Step 4: Create Decision Entry
Format the decision using this structure:

```markdown
## [Category] Decision: [Decision Title]

**Status**: [Status]
**Date**: [Current Date]
**Components**: [Components or "General"]

### Context
[Decision context and problem statement]

### Decision
[Detailed rationale for the chosen approach]

### Alternatives Considered
[Alternative approaches and why they were rejected]

### Trade-offs
[Any trade-offs or compromises made]

### Consequences
[Long-term consequences and implications]

### Review Notes
- **Rationale Reviewed**: [Yes/No based on detail level]
- **Alternatives Documented**: [Yes/No]
- **Components Identified**: [Yes/No]

---
```

### Step 5: Add to Design Decisions Document
1. Open `docs/design-decisions.md`
2. Add the formatted decision entry to the document
3. Add the decision to the document index/table of contents
4. Update the "Last updated" date

### Step 6: Validation
Before finalizing, ensure:
- Decision title is descriptive (minimum 5 characters)
- Context is provided and clear
- Rationale is detailed (minimum 50 characters)
- All required information is included

### Step 7: Post-Processing
- Stage the documentation changes with git
- Review the updated design decisions document
- Consider notifying team members about the new decision

### Error Handling
If any step fails:
- Check that all required files exist
- Verify all required information is provided
- Ensure proper formatting is maintained
- Retry up to 2 times if needed
