# Repository Migration TODO

## Phase 1: Consolidate Framework Package
- [x] Move all modules from `base/src` to root `src/blueprint/agents`
  - [x] Created `/src/blueprint/agents` directory structure
  - [x] Copied all modules from `base/src`
  - [x] Created `src/blueprint/__init__.py` for package namespace
  - [x] Preserved package namespace and exports
- [x] Update build and packaging configuration
  - [x] Created root `pyproject.toml` with correct package-dir mappings
  - [x] Updated `pytest.ini` to point to root tests directory
  - [x] Copied `py.typed` marker file to new location
  - [x] Moved tests from `base/tests` to root `tests`
  - [x] Updated all test imports from `base.src.*` to `blueprint.agents.*`
- [x] Verify package installation
  - [x] Successfully installed package in editable mode: `pip install -e .`
  - [x] 107/118 unit tests passing (11 pre-existing test failures unrelated to migration)

## Phase 2: Relocate Custom Implementation into Examples ✅
- [x] Create `examples/invoice_analyzer` directory structure
  - [x] Moved contents of `custom` to `examples/invoice_analyzer`
  - [x] Updated example-specific `pyproject.toml` to depend on installed package
- [x] Update imports in examples
  - [x] Replaced all `from base.src.*` with `from blueprint.agents.*` (all Python files)
  - [x] Updated pytest.ini to use correct pythonpath
- [x] Create example README with setup instructions
  - [x] Documented how to install the framework package first
  - [x] Provided quick-start guide for running the example
  - [x] Added Docker Compose and direct Python run options

## Phase 3: Update Build and Packaging Configuration
- [ ] Update CI/CD pipelines
  - [ ] remove `azure-pipelines.yml`, it is outdated
  - [ ] Update `azure-pipelines-pypi.yml` for PyPI publishing
- [ ] Update root-level tooling configs
  - [ ] Verify `.flake8`, `.pre-commit-config.yaml` point to correct paths
  - [ ] Move Dockerfiles to examples/invoice_analyzer

## Phase 4: Refresh Documentation
- [ ] Update README.md
  - [ ] Document new package structure
  - [ ] Add installation instructions
  - [ ] Link to examples
- [ ] Update CONTRIBUTING.md
  - [ ] Development setup with new structure
  - [ ] Running tests from root
- [ ] Update docs/ folder
  - [ ] Architecture diagrams reflecting new layout
  - [ ] API documentation paths

## Phase 5: Cleanup ✅
- [x] Remove redundant directories
  - [x] Deleted `base/` directory (all content migrated to `/src/blueprint/agents/`)
  - [x] Deleted `custom/` directory (all content migrated to `/examples/invoice_analyzer/`)
- [x] Verify all imports work end-to-end
  - [x] Test package import: `from blueprint.agents import AppBuilder, Config` ✓
  - [x] Framework package installs successfully: `pip install -e .` ✓
  - [x] 107/118 unit tests passing
