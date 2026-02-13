# Contributing to Broke

Thank you for your interest in contributing to Broke! This document provides guidelines and instructions for contributing.

## Code of Conduct

- Be respectful and inclusive
- Provide constructive feedback
- Focus on what is best for the community
- Show empathy towards other community members

## Getting Started

### 1. Fork and Clone

```bash
# Fork the repository on GitHub, then:
git clone https://github.com/valteryde/broke.git
cd broke
```

### 2. Set Up Development Environment

```bash
# Install dependencies
make install-dev

# Or manually:
pip install -r requirements.txt
pip install -r requirements-test.txt
pip install pre-commit
pre-commit install
```

### 3. Create a Branch

```bash
git checkout -b feat/your-feature-name
# or
git checkout -b fix/issue-description
```

## Development Workflow

### Running Locally

```bash
# Start Redis (required for some features)
docker run -d -p 6379:6379 redis:alpine

# Run the development server
make run-dev
# or
FLASK_ENV=development python run.py
```

### Making Changes

1. **Write Code**
   - Follow PEP 8 style guidelines
   - Keep functions small and focused
   - Add docstrings for complex functions

2. **Format Code**
   ```bash
   make format
   ```

3. **Write Tests**
   - Add tests for new features in `tests/`
   - Ensure existing tests still pass
   - Aim for >80% code coverage

4. **Run Checks**
   ```bash
   make checks
   ```

### Testing

```bash
# Run all tests
make test

# Run tests with coverage
make coverage

# Run specific test file
ward --path tests/test_specific.py

# Verbose output
make test-verbose
```

### Code Quality

```bash
# Linting
make lint

# Security checks
make security

# Check code complexity
make complexity

# Run all pre-commit hooks
make pre-commit
```

## Commit Guidelines

We use [Conventional Commits](https://www.conventionalcommits.org/) for commit messages:

### Format

```
type(scope): description

[optional body]

[optional footer]
```

### Types

- **feat**: A new feature
- **fix**: A bug fix
- **docs**: Documentation changes
- **style**: Code style changes (formatting, missing semicolons, etc.)
- **refactor**: Code refactoring
- **test**: Adding or updating tests
- **chore**: Maintenance tasks
- **perf**: Performance improvements
- **ci**: CI/CD changes
- **build**: Build system changes
- **revert**: Reverting previous commits

### Examples

```bash
feat: add ticket filtering by project
fix(auth): resolve login redirect issue
docs: update installation instructions
test: add webhook integration tests
refactor(models): simplify ticket query logic
```

## Pull Request Process

### 1. Before Submitting

- [ ] All tests pass (`make test`)
- [ ] Code is formatted (`make format`)
- [ ] Linting passes (`make lint`)
- [ ] Security checks pass (`make security`)
- [ ] Coverage is maintained or improved
- [ ] No debug statements (print, breakpoint, etc.)
- [ ] Documentation is updated if needed

### 2. Creating the PR

1. **Title**: Use conventional commit format
   ```
   feat: add user profile settings
   ```

2. **Description**: Include:
   - What changes were made
   - Why these changes were necessary
   - How to test the changes
   - Screenshots (if UI changes)
   - Related issues (e.g., "Closes #123")

3. **Template**:
   ```markdown
   ## Description
   Brief description of changes
   
   ## Type of Change
   - [ ] Bug fix
   - [ ] New feature
   - [ ] Breaking change
   - [ ] Documentation update
   
   ## Testing
   How to test these changes
   
   ## Checklist
   - [ ] Tests pass
   - [ ] Code is formatted
   - [ ] Documentation updated
   - [ ] No breaking changes (or documented)
   ```

### 3. Review Process

- PRs require at least one approval
- CI checks must pass
- Address review feedback promptly
- Keep PR scope focused and small

### 4. After Approval

- Squash commits if needed
- Ensure branch is up to date with main
- Maintainer will merge

## Project Structure

```
broke/
├── app/                    # Main application code
│   ├── utils/             # Utility modules
│   │   ├── models.py      # Database models
│   │   ├── security.py    # Authentication
│   │   └── ...
│   ├── views/             # Route handlers (blueprints)
│   │   ├── auth.py        # Authentication routes
│   │   ├── tickets.py     # Ticket routes
│   │   └── ...
│   ├── templates/         # Jinja2 templates
│   ├── static/            # CSS, JS, images
│   └── server.py          # Application factory
├── tests/                 # Test suite
│   ├── fixtures.py        # Test fixtures
│   └── test_*.py          # Test modules
├── scripts/               # Utility scripts
├── data/                  # Runtime data (not in git)
└── .github/               # GitHub Actions workflows
```

## Testing Guidelines

### Writing Tests

```python
from ward import test, fixture
from app.utils.models import Ticket

@test("ticket can be created with valid data")
def test_create_ticket(client=client, test_project=test_project):
    response = client.post('/api/tickets', json={
        'title': 'Test Ticket',
        'project_id': test_project.id
    })
    assert response.status_code == 200
```

### Fixtures

Create reusable fixtures in `tests/fixtures.py`:

```python
@fixture(scope=Scope.Test)
def test_user(fake=fake):
    user = User.create(username=fake.user_name())
    yield user
    user.delete_instance()
```

### Running Specific Tests

```bash
# Run specific test
ward --path tests/test_tickets.py::test_create_ticket

# Run tests matching pattern
ward --path tests/ --search "webhook"
```

## Debugging

### Common Issues

**Tests failing locally but not in CI**
- Ensure Redis is running
- Check Python version matches CI
- Clear cache: `make clean`

**Import errors**
- Ensure all dependencies installed: `make install-dev`
- Check PYTHONPATH

**Database issues**
- Delete `data/app.db` and restart
- Run migrations: `make db-migrate`

### Debugging Tools

```bash
# Run with verbose logging
FLASK_ENV=development FLASK_DEBUG=1 python run.py

# Python debugger
import pdb; pdb.set_trace()
# or
breakpoint()

# Check coverage for specific file
coverage report --include="app/views/tickets.py"
```

## Documentation

### Code Documentation

- Add docstrings to functions and classes
- Explain complex algorithms
- Include type hints where helpful

```python
def create_ticket(title: str, project_id: str, user: User) -> Ticket:
    """
    Create a new ticket in the system.
    
    Args:
        title: The ticket title
        project_id: ID of the project to create ticket in
        user: User creating the ticket
    
    Returns:
        The created Ticket instance
    
    Raises:
        DoesNotExist: If project doesn't exist
    """
    # Implementation
```

### API Documentation

When adding/modifying API endpoints, document:
- HTTP method and path
- Request parameters
- Response format
- Status codes
- Example usage

## Security

### Reporting Vulnerabilities

**Do not open public issues for security vulnerabilities.**

Instead:
1. Email security concerns to the maintainer
2. Include detailed description
3. Provide steps to reproduce
4. Suggest a fix if possible

### Security Checklist

- [ ] No hardcoded secrets or passwords
- [ ] Input validation on all user inputs
- [ ] Proper authentication checks
- [ ] SQL injection prevention (use ORM)
- [ ] XSS prevention (escape output)
- [ ] CSRF protection

## Getting Help

- **Issues**: Open an issue for bugs or feature requests
- **Discussions**: Use GitHub Discussions for questions
- **Documentation**: Check `.github/workflows/README.md` for CI/CD help

## Recognition

Contributors will be:
- Listed in the contributors section
- Credited in release notes
- Acknowledged in the project

Thank you for contributing to Broke! 🎉
