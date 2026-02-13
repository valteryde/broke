# First CI Run Checklist

Use this checklist for your first push to ensure everything works smoothly.

## Pre-Push Checklist

### 1. Verify Local Environment

- [ ] All configuration files exist:
  ```bash
  ls -la .github/workflows/ci.yml
  ls -la .flake8
  ls -la .pylintrc
  ls -la .coveragerc
  ls -la Makefile
  ```

- [ ] Dependencies installed:
  ```bash
  make install-dev
  ```

- [ ] Redis is running (for tests):
  ```bash
  docker run -d -p 6379:6379 redis:alpine
  # Or use existing Redis
  redis-cli ping  # Should return PONG
  ```

### 2. Run Local Checks

- [ ] Format code:
  ```bash
  make format
  ```

- [ ] Run linting:
  ```bash
  make lint
  ```
  Expected: No critical errors

- [ ] Run security checks:
  ```bash
  make security
  ```
  Expected: No high-severity issues

- [ ] Run tests:
  ```bash
  make test
  ```
  Expected: All tests pass

- [ ] Check coverage:
  ```bash
  make coverage
  ```
  Expected: Coverage report generated

- [ ] Run full checks:
  ```bash
  make checks
  ```
  Expected: All checks pass [PASS]

### 3. Prepare Repository

- [ ] Create GitHub repository (if not exists):
  ```bash
  # If new repo:
  gh repo create valteryde/broke --public
  
  # If existing:
  git remote add origin https://github.com/valteryde/broke.git
  ```

- [ ] Add secrets (if needed):
  - Go to Settings → Secrets and variables → Actions
  - Add any required secrets (none required for basic setup)

### 4. Commit and Push

- [ ] Stage all CI/CD files:
  ```bash
  git add .github/ .flake8 .pylintrc .coveragerc .bandit
  git add Makefile .pre-commit-config.yaml
  git add scripts/run-checks.sh
  git add CONTRIBUTING.md
  git add requirements-test.txt
  ```

- [ ] Create conventional commit:
  ```bash
  git commit -m "ci: add comprehensive GitHub Actions pipeline
  
  - Add CI workflow with lint, security, test, and coverage jobs
  - Add PR validation workflow
  - Add dependency check workflow
  - Configure code quality tools (flake8, pylint, bandit)
  - Add Makefile for development convenience
  - Update documentation with CI/CD info"
  ```

- [ ] Push to GitHub:
  ```bash
  git push -u origin hooks  # or your branch name
  ```

## Post-Push Verification

### 5. Monitor First Run

- [ ] Navigate to GitHub Actions:
  - Go to: `https://github.com/valteryde/broke/actions`

- [ ] Watch workflow execution:
  - Click on the latest workflow run
  - Monitor each job in real-time

- [ ] Expected timeline:
  - Lint: ~5 seconds [PASS]
  - Security: ~15 seconds [PASS]
  - Code Quality: ~20 seconds [PASS]
  - Docker Build: ~30 seconds [PASS]
  - Tests: ~1-2 minutes [PASS]
  - Coverage: ~1.5 minutes [PASS]
  - Summary: ~2 seconds [PASS]

### 6. Check Artifacts

- [ ] Scroll to bottom of workflow run
- [ ] Verify artifacts are generated:
  - [ ] test-results-3.10
  - [ ] test-results-3.11
  - [ ] test-results-3.12
  - [ ] test-results-3.13
  - [ ] coverage-report
  - [ ] bandit-security-report

- [ ] Download and inspect coverage report:
  - Download `coverage-report`
  - Extract and open `htmlcov/index.html`

### 7. Review Summary

- [ ] Check workflow summary page
- [ ] Verify all jobs show [PASS]
- [ ] Review any warnings or notices

### 8. Test Pull Request Flow

- [ ] Create a test branch:
  ```bash
  git checkout -b test/ci-validation
  ```

- [ ] Make a small change:
  ```bash
  echo "# CI Test" >> test_ci.txt
  git add test_ci.txt
  git commit -m "test: validate CI pipeline"
  git push -u origin test/ci-validation
  ```

- [ ] Create pull request:
  - Go to GitHub
  - Click "Compare & pull request"
  - Title: `test: validate CI pipeline`
  - Create PR

- [ ] Verify PR checks:
  - [ ] CI workflow runs [PASS]
  - [ ] PR checks workflow runs [PASS]
  - [ ] Automated comment appears
  - [ ] All status checks pass

- [ ] Clean up test:
  ```bash
  # Close/delete the PR on GitHub
  git checkout hooks
  git branch -D test/ci-validation
  git push origin --delete test/ci-validation
  ```

## Troubleshooting First Run

### If Lint Fails

```bash
# Check what failed
make lint

# Auto-fix most issues
make format

# Commit fixes
git add .
git commit -m "style: fix linting issues"
git push
```

### If Security Fails

```bash
# Check security issues
make security

# Review Bandit output
# If false positive, add comment:
# dangerous_function()  # noqa: S123

# Commit fixes
git add .
git commit -m "fix: resolve security issues"
git push
```

### If Tests Fail

```bash
# Run tests locally with verbose output
make test-verbose

# Fix failing tests
# Then verify
make test

# Commit fixes
git add .
git commit -m "test: fix failing tests"
git push
```

### If Docker Build Fails

```bash
# Test locally
make docker-build

# Check Dockerfile syntax
docker build -t broke:test .

# Fix issues and push
```

## Success Criteria

[PASS] **All jobs pass** with green checkmarks
[PASS] **Artifacts generated** and downloadable
[PASS] **No critical errors** in any job
[PASS] **Summary report** shows all green
[PASS] **PR flow works** (if tested)

## Next Steps After Success

- [ ] Enable branch protection rules:
  - Settings → Branches → Add rule
  - Branch name pattern: `main`
  - Require status checks to pass:
    - [PASS] lint
    - [PASS] test
    - [PASS] coverage
    - [PASS] docker-build

- [ ] Update README badges:
  - Verify badges show correct status
  - Update if needed

- [ ] Configure notifications:
  - Settings → Notifications
  - Set preferences for workflow failures

- [ ] Share with team:
  - Point them to [QUICK_START.md](.github/QUICK_START.md)
  - Share [CONTRIBUTING.md](../CONTRIBUTING.md)

- [ ] Schedule review:
  - Set reminder for weekly dependency checks
  - Monitor CI performance

## Resources

-  [Full CI/CD Documentation](.github/workflows/README.md)
- 🏗️ [Architecture Diagram](.github/ARCHITECTURE.md)
-  [Quick Start Guide](.github/QUICK_START.md)
-  [Contributing Guidelines](../CONTRIBUTING.md)
- [METRICS] [GitHub Actions Dashboard](https://github.com/valteryde/broke/actions)

---

**Ready to push?** Make sure all checkboxes above are [PASS] before pushing!

Good luck! 
