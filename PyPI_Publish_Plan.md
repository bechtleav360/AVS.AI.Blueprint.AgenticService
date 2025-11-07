# Plan for Publishing Base Package to PyPI

This document outlines the steps to publish the `base` package as a PyPI package named `avs-blueprint-agents`.

## Checklist

- [x] **Update base/pyproject.toml**
  - Reset `version` to `"0.1.0"` for the first PyPI release
  - Set name to "avs-blueprint-agents"
  - Add `[tool.setuptools]` section with `package-dir = {"agents.base": "src"}` to map the package name to the existing `src/` directory without restructuring
  - Ensure `build` and `semver` are included in the `dev` dependency group for local testing


- [x] **Create a new pipeline file (e.g., azure-pipelines-pypi.yml)**
  - Create `azure-pipelines-pypi.yml` in the repo root
  - Include a `PythonPackage` stage with jobs for:
    - On `master` branch: Run a script to increment the patch version in `base/pyproject.toml` (e.g., 0.1.0 → 0.1.1)
    - Install required tooling (e.g., `python -m pip install --upgrade pip`, `pip install semver build twine`)
    - Building the Python package using `python -m build`
    - Running tests with `pytest`
    - Publishing to PyPI on `master` branch
    - Committing the new version back to the repository and tagging the release (e.g., `v0.1.1`)
  - For `dev` branch: Build and test only (no version bump or publish)
  - Configure triggers for `master` and `dev` branches, excluding the YAML file itself
  - Add variable groups for PyPI tokens (`PyPI` group with `PyPIApiToken`, optionally `TestPyPIApiToken`)

- [x] **Create version bump script**
  - Add a Python script (e.g., `scripts/bump_version.py`) to the repo that reads `base/pyproject.toml`, increments the patch version, and writes it back
  - Use a library like `semver` for parsing and bumping versions
  - Script should handle committing the updated file and creating/pushing a git tag for the new version

- [ ] **Set up PyPI API tokens in Azure DevOps**
  - Create or update variable groups in Azure DevOps Pipelines
  - Ensure `PyPIApiToken` is set for production releases
  - Optionally set `TestPyPIApiToken` for testing releases on dev branch

- [ ] **Update base/README.md**
  - Change title to "AVS Blueprint Agents Base Framework"
  - Add an "Installation" section with `pip install avs-blueprint-agents`
  - Keep the "Structure" section as is (folder structure unchanged)
  - Update "Usage" section with example imports like `from agents.base.api.rest import RestApi`

- [ ] **Test the package build locally**
  - Install `build` tool: `pip install build`
  - Run `python -m build` in `base/` directory
  - Verify the built package structure and test imports
  - Ensure no import errors with the `agents.base` namespace

## Notes

- The package will be published under the name `avs-blueprint-agents` using `package-dir` mapping to avoid changing the folder structure.
- After publishing, the `custom` folder should import from `agents.base` instead of `base.src`.
- CI/CD will handle building and testing on `dev`, and building, testing, and publishing on `master`.
- Ensure all dependencies and classifiers in `pyproject.toml` are appropriate for PyPI.
- Generate PyPI API tokens (`__token__` format) from the PyPI account settings and store them securely in Azure DevOps variable groups.
