---
description: Add new tasks, features, or improvements to the project roadmap
auto_execution_mode: 1
---

## Add Task to Project Roadmap Workflow

This workflow helps add new tasks, features, or improvements to the project roadmap with proper categorization and prioritization.

### Step 1: Gather Task Information
Collect the following information about the task:

**Required Information:**
- **Task Title**: Clear, descriptive title for the task or feature (minimum 10 characters)
- **Task Description**: Detailed description of what needs to be done (minimum 30 characters)
- **Category**: Choose from: feature, enhancement, bug_fix, technical_debt, documentation, testing, performance, security, infrastructure

**Optional Information:**
- **Priority Level**: Choose from: critical, high, medium, low
- **Target Version**: Version where this should be completed (e.g., v1.2.3)
- **Estimated Effort**: Choose from: small, medium, large, extra_large
- **Dependencies**: Other tasks or components this depends on
- **Success Criteria**: How to measure success for this task
- **Target Timeline**: Choose from: q1_2024, q2_2024, q3_2024, q4_2024, q1_2025, future
- **Assignee**: Person or team responsible for this task

### Step 2: Prerequisites Check
Ensure these files exist before proceeding:
- `docs/roadmap.md` - Main roadmap documentation
- `docs/changelog.md` - Changelog for version reference

### Step 3: Read Current Roadmap
1. Open and read the existing roadmap to understand:
   - Current structure and organization
   - Existing priorities and timelines
   - Version targets currently planned
   - Similar tasks already listed

### Step 4: Format Task Entry
Create the task entry using this format:

```markdown
#### [Category]: [Task Title]

**Priority**: [Priority Level]
**Effort**: [Estimated Effort]
**Timeline**: [Target Timeline]
**Target Version**: [Version] (if specified)
**Assignee**: [Assignee] (if specified)

[Task Description]

**Dependencies**:
[List of dependencies]

**Success Criteria**:
[How to measure success]

**Status**: Proposed
**Date Added**: [Current Date]

---
```

### Step 5: Add Task to Roadmap
1. Open `docs/roadmap.md`
2. Add the formatted task entry to the appropriate section based on priority:
   - Critical priority tasks go in the highest priority section
   - High priority tasks in the high priority section
   - Medium priority tasks in the medium priority section
   - Low priority tasks in the low priority section
3. Ensure proper formatting and consistent structure

### Step 6: Update Roadmap Metadata
1. Update the "Last updated" date in the roadmap
2. Regenerate or update the table of contents if needed
3. Ensure the roadmap maintains consistent formatting

### Step 7: Validation
Before finalizing, ensure:
- Task title is descriptive and clear
- Description provides sufficient detail
- Priority level matches the task's importance
- All dependencies are listed
- Success criteria are measurable

### Step 8: Post-Processing
1. Stage the roadmap changes with git: `git add docs/roadmap.md`
2. Review the updated roadmap for consistency
3. Consider notifying relevant team members about the new task

### Step 9: Version Planning
If a target version is specified:
1. Check if the version exists in current planning
2. Ensure the timeline aligns with version release schedules
3. Consider adding the task to version-specific planning sections

### Error Handling
If any step fails:
- Verify that the roadmap file exists and is accessible
- Check that all required information is provided
- Ensure proper markdown formatting is maintained
- Retry up to 2 times if needed

### Best Practices
- Use consistent terminology across tasks
- Be specific about success criteria
- Consider dependencies between tasks
- Align priorities with project goals
- Keep task descriptions actionable
