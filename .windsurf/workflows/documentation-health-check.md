---
description: Validate documentation completeness and identify gaps
auto_execution_mode: 1
---

## Documentation Health Check Workflow

This workflow performs a comprehensive health check on project documentation to identify missing files, broken links, and structural issues.

### Step 1: Choose Check Type
Select the type of health check to perform:
- **comprehensive**: Full analysis including links, structure, and content
- **links_only**: Check only internal and external links
- **content_only**: Analyze content quality and metrics
- **structure_only**: Validate document structure and formatting

### Step 2: Prerequisites Check
Ensure these exist before proceeding:
- `docs/` directory with documentation files
- Required documentation files should include:
  - README.md
  - design-decisions.md
  - requirements.md
  - architecture.md
  - api-reference.md
  - development-guide.md
  - deployment-guide.md
  - testing-guide.md
  - troubleshooting.md
  - changelog.md
  - roadmap.md

### Step 3: Perform Health Check Analysis

#### 3.1 Scan Documentation Structure
1. List all files in the `docs/` directory
2. Count total number of documentation files

#### 3.2 Validate Required Files
Check for the presence of all required documentation files listed in prerequisites.

#### 3.3 Check Internal Links
1. Scan all markdown files in `docs/` for internal links
2. Validate that all referenced files exist
3. Identify any broken or outdated links

#### 3.4 Validate Document Structure
Check each document for required structural elements:
- Title/headings
- Description/introduction
- Table of contents (where appropriate)
- Last updated information

#### 3.5 Content Quality Analysis
Analyze content metrics for each file:
- Word count
- Heading depth
- Code examples count
- Last modified date

### Step 4: Generate Health Report
Create a comprehensive report with findings:

```markdown
# Documentation Health Check Report

**Date**: [Current Date]
**Check Type**: [Selected Check Type]
**Total Files**: [Number of files found]

## 📊 Summary

### ❌ Missing Required Files ([count])
[List of missing files]

### 🔗 Broken Links Found ([count])
[Details of broken links with file locations]

### 🏗️ Structure Issues ([count])
[List of structural issues found]

### ✅ No Issues Found (for any category)

## 📈 Content Metrics

[For each file]:
- Words: [count]
- Last Modified: [days] days ago
- Max Heading Depth: [level]
- Code Examples: [count]

## 🎯 Recommendations

[Based on findings, provide specific recommendations for fixes]
```

### Step 5: Save Report
Save the health check report to `docs/health-report.md` for reference.

### Step 6: Address Issues Found
Based on the report findings:

1. **Missing Files**: Create the missing documentation files using appropriate templates
2. **Broken Links**: Fix internal links and update references to moved/renamed files
3. **Structure Issues**: Add missing sections and ensure consistent formatting
4. **Content Quality**: Update outdated content and improve documentation quality

### Step 7: Optional - Auto Fix
If enabled, automatically fix minor issues:
- Add missing table of contents
- Update last modified dates
- Fix obvious formatting issues

### Step 8: Review and Notify
1. Review the health report findings
2. Notify team members about critical issues
3. Plan documentation improvements based on findings

### Error Handling
If the health check fails:
- Verify the `docs/` directory exists
- Check file permissions
- Ensure all required files are accessible
- Retry the check if needed
