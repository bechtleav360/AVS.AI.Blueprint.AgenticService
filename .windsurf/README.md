# Windsurf Workflows for Agents Blueprint

This directory contains automated workflows for maintaining the Agents Blueprint project documentation and codebase.

## 📁 Workflow Categories

### 📝 Documentation Workflows
- **changelog-append**: Append recent chat session changes to changelog
- **api-reference-update**: Update API reference documentation
- **design-decision-summarize**: Document design decisions from discussions
- **roadmap-add-task**: Add new tasks to the project roadmap

### 🔧 Development Workflows
- **test-documentation-sync**: Keep test documentation in sync with code
- **deployment-guide-update**: Update deployment guides when infrastructure changes
- **config-documentation-sync**: Sync configuration documentation with actual configs

### 🎯 Utility Workflows
- **documentation-health-check**: Validate documentation completeness
- **link-checker**: Verify all internal links work correctly
- **documentation-index-update**: Update table of contents and indexes

## 🚀 Usage

### Running Workflows
1. **From Command Palette**: `Ctrl+Shift+P` → "Windsurf: Run Workflow"
2. **From Sidebar**: Click the workflow icon and select workflow
3. **From Context Menu**: Right-click in editor → "Run Workflow"

### Creating Custom Workflows
1. Create new `.yaml` file in this directory
2. Follow the workflow schema (see `workflow-schema.json`)
3. Test with `workflow validate` command
4. Add to relevant category in this README

## 📋 Workflow Configuration

All workflows support:
- **Variables**: Customizable parameters
- **Conditions**: Prerequisites and validation
- **Actions**: File operations, text transformations
- **Validation**: Schema validation and linting
- **Logging**: Detailed execution logs

## 🤝 Contributing

When creating new workflows:
1. Follow the established patterns and naming conventions
2. Include comprehensive documentation
3. Add proper error handling and validation
4. Test thoroughly before committing
5. Update this README with new workflow descriptions

---

*Maintained by the development team. For workflow issues or suggestions, please refer to the [Development Guide](../docs/development-guide.md).*
