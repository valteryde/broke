# Quick Start - CI/CD Guide

## Before You Commit

```bash
# Run this command to check everything:
make checks
```

## Essential Commands

| Command | What It Does |
|---------|--------------|
| `make install-dev` | Install all development dependencies |
| `make test` | Run the test suite |
| `make lint` | Check code style |
| `make format` | Auto-format your code |
| `make checks` | Run ALL checks (do this before pushing!) |

## Pull Request Checklist

- [ ] PR title follows format: `type: description`
  - Examples: `feat: add feature`, `fix: bug description`
- [ ] Ran `make checks` and all passed
- [ ] Tests pass: `make test`
- [ ] Code formatted: `make format`
- [ ] No debug statements (print, breakpoint)
- [ ] Added tests for new features

## PR Title Examples

**Good:**
- `feat: add user profile page`
- `fix: resolve login redirect bug`
- `docs: update installation guide`
- `test: add webhook tests`
- `refactor: simplify ticket query logic`

**Bad:**
- `Update code` (not descriptive)
- `Fixed stuff` (not conventional format)
- `WIP` (incomplete work)

## Common Issues & Fixes

### Linting Failed
```bash
make format  # Auto-fix most issues
make lint    # Check what's left
```

### Tests Failed
```bash
make test-verbose  # See detailed output
# Fix the failing tests
make test  # Verify they pass
```

### Security Alert
```bash
make security  # See what's flagged
# Review the Bandit output
# Fix or add # noqa comment if false positive
```

## CI Pipeline Status

Check these after pushing:
1. Go to **Actions** tab on GitHub
2. Find your workflow run
3. All checks should be green

## Need Help?

- Full guide: [.github/workflows/README.md](.github/workflows/README.md)
- Contributing: [CONTRIBUTING.md](../CONTRIBUTING.md)
- Questions: Open a GitHub Discussion

## Quick Test

```bash
# 1. Install dependencies
make install-dev

# 2. Run checks
make checks

# 3. If all green, you're ready to commit!
```

---

**Remember: CI will run the same checks, so if `make checks` passes locally, CI should pass too!**
