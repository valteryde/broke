# CI/CD Pipeline Documentation

This directory contains GitHub Actions workflows for automated testing, code quality assurance, and continuous integration.

## Workflows

### 1. CI - Code Quality & Tests (`ci.yml`)

**Triggers:**
- Push to `main`, `develop`, or `hooks` branches
- Pull requests to `main` or `develop`

**Jobs:**

#### Lint
- Runs `flake8` for Python syntax and style checking
- Runs `pylint` for deeper code analysis
- Configuration: `.flake8` and `.pylintrc`

#### Security
- Runs `bandit` for security vulnerability scanning
- Runs `safety` to check for known security issues in dependencies
- Configuration: `.bandit`

#### Code Quality
- Calculates cyclomatic complexity using `radon`
- Generates maintainability index reports
- Adds metrics to GitHub Actions summary

#### Test
- Runs test suite on Python 3.10, 3.11, 3.12, and 3.13
- Uses Redis service container
- Runs with Ward test framework
- Installs Playwright for browser testing

#### Coverage
- Generates code coverage reports
- Creates HTML and XML coverage reports
- Uploads coverage artifacts
- Requires >80% coverage for critical paths

#### Docker Build
- Tests Docker image building
- Validates docker-compose configuration
- Uses build cache for efficiency

#### Summary
- Aggregates results from all jobs
- Fails if any critical job fails

### 2. PR Checks (`pr-checks.yml`)

**Triggers:**
- Pull request opened, synchronized, or reopened

**Jobs:**

#### PR Validation
- Validates PR title follows [Conventional Commits](https://www.conventionalcommits.org/)
- Format: `type(scope): description`
- Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`, `ci`, `build`, `revert`
- Checks for large files (>1MB)

#### Code Diff Analysis
- Analyzes complexity of changed files
- Checks for debugging statements (print, breakpoint, pdb)
- Reports complexity metrics for modified code

#### Security Diff
- Runs security checks only on changed files
- Faster feedback for security issues

#### Comment Summary
- Posts or updates a comment on the PR with results
- Provides quick overview of all checks

### 3. Dependency Check (`dependency-check.yml`)

**Triggers:**
- Weekly schedule (Mondays at 9:00 AM UTC)
- Manual trigger via `workflow_dispatch`
- Changes to dependency files

**Jobs:**

#### Dependency Review
- Audits dependencies with `pip-audit`
- Checks for known vulnerabilities with `safety`
- Uploads audit reports as artifacts

#### Outdated Check
- Lists outdated packages
- Helps with maintenance planning

#### License Check
- Lists all dependency licenses
- Checks for incompatible licenses (GPL, AGPL, LGPL)
- Ensures license compliance

## Configuration Files

### `.flake8`
Configures Python linting:
- Max line length: 120
- Excludes test files and migrations
- Ignores specific warnings (E203, W503)
- Max complexity: 15

### `.pylintrc`
Configures Pylint:
- Max line length: 120
- Disables docstring requirements
- Configures acceptable variable names
- Sets complexity thresholds

### `.bandit`
Configures security scanning:
- Excludes test directories
- Sets severity and confidence levels
- Skips assert checks in tests

### `.coveragerc`
Configures coverage reporting:
- Source: `app/` directory
- Omits: tests, migrations, virtual environments
- Branch coverage enabled
- Generates HTML and XML reports

## Local Development

### Running Tests Locally

```bash
# Install test dependencies
pip install -r requirements-test.txt

# Run all tests
ward --path tests/

# Run with coverage
coverage run -m ward --path tests/
coverage report
coverage html
```

### Running Linters Locally

```bash
# Flake8
flake8 app/

# Pylint
pylint app/

# Bandit security check
bandit -r app/ -ll

# Check complexity
radon cc app/ -a -s
radon mi app/ -s
```

### Running Security Checks

```bash
# Check dependencies for vulnerabilities
pip-audit
safety check

# Check for outdated packages
pip list --outdated
```

## Best Practices

### PR Title Format
Always use conventional commits format:
- `feat: add new feature`
- `fix(auth): resolve login issue`
- `docs: update README`
- `test: add webhook tests`

### Before Committing
1. Run tests locally: `ward --path tests/`
2. Check linting: `flake8 app/`
3. Verify no debug statements: `grep -r "print(" app/`
4. Ensure coverage: `coverage run -m ward --path tests/ && coverage report`

### Code Quality Guidelines
- Keep functions under 50 lines
- Maintain cyclomatic complexity < 10
- Write tests for new features
- Aim for >80% code coverage
- Remove debugging statements
- Follow PEP 8 style guide

## Troubleshooting

### Failed Lint Job
- Check the flake8 output for syntax errors
- Run `flake8 app/` locally to see specific issues
- Fix style violations or add `# noqa` comments with justification

### Failed Security Job
- Review Bandit findings
- Check if vulnerabilities are false positives
- Update dependencies if needed: `pip install --upgrade <package>`

### Failed Tests
- Check Redis connection (tests require Redis)
- Verify test data setup
- Run locally with `ward --path tests/ -v` for verbose output

### Failed Coverage
- Identify uncovered lines: `coverage report -m`
- Add tests for uncovered code
- Generate HTML report: `coverage html` and open `htmlcov/index.html`

## Artifacts

Workflows generate artifacts that can be downloaded:
- **Test results**: Test output and logs
- **Coverage reports**: HTML and XML coverage reports
- **Security reports**: Bandit and Safety JSON reports
- **Dependency audits**: pip-audit results

Access artifacts from the Actions tab in GitHub.

## Updating Workflows

When modifying workflows:
1. Test changes in a separate branch
2. Use `act` for local testing: `brew install act`
3. Validate YAML syntax
4. Monitor first run carefully
5. Update this documentation

## Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Ward Testing Framework](https://ward.readthedocs.io/)
- [Conventional Commits](https://www.conventionalcommits.org/)
- [Python Code Quality Tools](https://realpython.com/python-code-quality/)
