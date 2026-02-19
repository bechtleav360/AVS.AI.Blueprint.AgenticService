---
description: Automatically append recent changes from chat sessions to the project changelog
auto_execution_mode: 1
---

## Append Chat Session Changes to Changelog Workflow

This workflow helps automatically document changes made during development sessions by appending them to the project changelog with proper categorization and formatting.

### Step 1: Gather Session Information
Collect the following information about the changes:

**Required Information:**
- **Session Summary**: Brief but descriptive summary of changes (minimum 10 characters)
- **Change Type**: Choose from: feature, bugfix, documentation, maintenance, performance, security
- **Affected Components**: Components affected by the changes (optional)

### Step 2: Prerequisites Check
Ensure these files exist before proceeding:
- `docs/changelog.md` - Main changelog file
- `docs/requirements.md` - Requirements file for context

### Step 3: Extract Current Version Information
1. Read the current changelog to understand the version structure
2. Extract the current version number (e.g., v1.2.3)
3. Note the current date and session context

### Step 4: Generate Changelog Entry
Create a properly formatted changelog entry:

```markdown
### [Session Summary](changelog.md#[change-type]-[timestamp])

**Change Type**: [Session Summary]

#### Details
- **Date**: [Current Date]
- **Components**: [Affected Components]
- **Type**: [Change Type]
- **Session**: [Session ID]

[Contextual description based on change type]
```

**Contextual Descriptions by Type:**

- **Feature**: "This feature enhances the [component] component with new capabilities."
- **Bugfix**: "This fix resolves issues in the [components] components."
- **Documentation**: "Documentation updated for [components] components."
- **Maintenance**: "Maintenance updates applied to [components] components."
- **Performance**: "Performance improvements implemented for [components] components."
- **Security**: "Security enhancements applied to [components] components."

### Step 5: Add Entry to Changelog
1. Open `docs/changelog.md`
2. Add the new entry to the top of the "Unreleased" section
3. Ensure proper chronological ordering (newest first)
4. Maintain consistent formatting with existing entries

### Step 6: Update Changelog Metadata
1. Update the "Last updated" timestamp in the changelog
2. Ensure the version information remains accurate
3. Check that the table of contents is up to date

### Step 7: Validation
Before finalizing, ensure:
- Session summary is descriptive and clear (minimum 10 characters)
- Session summary contains meaningful text with spaces
- Change type is appropriate for the changes made
- All required information is included

### Step 8: Post-Processing
1. Review the updated changelog for accuracy and consistency
2. Consider notifying team members about significant changes
3. Stage the changelog changes: `git add docs/changelog.md`
4. Verify the formatting matches existing entries

### Step 9: Best Practices for Session Documentation

**Session Summaries:**
- Be specific about what was accomplished
- Use action-oriented language
- Include key outcomes or deliverables
- Keep summaries concise but informative

**Change Types:**
- **Feature**: New functionality or capabilities
- **Bugfix**: Corrections to existing functionality
- **Documentation**: Updates to documentation or comments
- **Maintenance**: Refactoring, cleanup, or technical improvements
- **Performance**: Optimizations and efficiency improvements
- **Security**: Security-related changes and fixes

**Affected Components:**
- **API**: Changes to REST endpoints or API interfaces
- **Agent**: Modifications to agent logic or behavior
- **Data Gateway**: Changes to data access or integration layers
- **Documentation**: Updates to documentation files
- **Testing**: Changes to test suites or testing infrastructure
- **Deployment**: Changes to deployment or infrastructure
- **Configuration**: Updates to configuration files or settings

### Step 10: Integration with Development Workflow
This workflow should be run:
- At the end of significant development sessions
- Before major commits or releases
- When completing user stories or features
- After resolving critical bugs

### Error Handling
If the changelog update fails:
- Verify that the changelog file exists and is accessible
- Check that the session summary meets requirements
- Ensure proper file permissions for editing
- Retry up to 3 times if needed

### Benefits
- Maintains a complete history of changes
- Helps with release notes generation
- Provides context for future development
- Supports compliance and audit requirements
- Enables better project tracking and reporting
