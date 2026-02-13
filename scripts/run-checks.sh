#!/usr/bin/env bash
# Local CI/CD checks - Run this before pushing to ensure CI passes

# Don't exit on error - we want to run all checks and report at the end
set +e

echo "Running Local CI Checks..."
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track failures
FAILED=0

# Function to print status
print_status() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}[PASS]${NC} $2"
    else
        echo -e "${RED}[FAIL]${NC} $2"
        FAILED=1
    fi
}

# Check if we're in the right directory
if [ ! -f "pyproject.toml" ]; then
    echo -e "${RED}Error: Must run from project root${NC}"
    exit 1
fi

# 1. Linting
echo "Running Flake8..."
flake8 app/ > /tmp/flake8.log 2>&1
FLAKE8_EXIT=$?
if [ $FLAKE8_EXIT -eq 0 ]; then
    print_status 0 "Flake8 passed"
else
    print_status 1 "Flake8 failed - see /tmp/flake8.log"
    echo "  Preview of issues:"
    head -10 /tmp/flake8.log | sed 's/^/    /'
fi
echo ""

# 2. Security check
echo "Running Bandit security scan..."
bandit -r app/ -ll -ii > /tmp/bandit.log 2>&1
BANDIT_EXIT=$?
if [ $BANDIT_EXIT -eq 0 ]; then
    print_status 0 "Bandit passed"
else
    print_status 1 "Bandit found issues - see /tmp/bandit.log"
    echo "  Preview of issues:"
    head -10 /tmp/bandit.log | sed 's/^/    /'
fi
echo ""

# 3. Code complexity with Radon (if available)
if command -v radon &> /dev/null; then
    echo "Running Radon complexity check..."
    radon cc app/ -a -nb > /tmp/radon.log 2>&1
    RADON_EXIT=$?
    if [ $RADON_EXIT -eq 0 ]; then
        print_status 0 "Radon complexity check passed"
    else
        print_status 1 "Radon found complex code - see /tmp/radon.log"
        echo "  Preview of issues:"
        head -10 /tmp/radon.log | sed 's/^/    /'
    fi
    echo ""
else
    echo -e "${YELLOW}[SKIP]${NC} Radon not installed (optional)"
    echo ""
fi

# 4. Type checking with pylint
echo "Running Pylint..."
pylint app/ --exit-zero --output-format=text > /tmp/pylint.log 2>&1
PYLINT_EXIT=$?
PYLINT_SCORE=$(grep "Your code has been rated at" /tmp/pylint.log | awk '{print $7}' | cut -d'/' -f1)
if [ -n "$PYLINT_SCORE" ]; then
    THRESHOLD=7.0
    if (( $(echo "$PYLINT_SCORE >= $THRESHOLD" | bc -l) )); then
        print_status 0 "Pylint passed (score: $PYLINT_SCORE/10.0)"
    else
        print_status 1 "Pylint score too low: $PYLINT_SCORE/10.0 (threshold: $THRESHOLD)"
    fi
else
    print_status 1 "Pylint failed - see /tmp/pylint.log"
fi
echo ""

# 5. Tests
echo "Running tests with Ward..."
ward --path tests/ > /tmp/ward.log 2>&1
WARD_EXIT=$?
if [ $WARD_EXIT -eq 0 ]; then
    print_status 0 "Tests passed"
else
    print_status 1 "Tests failed - see /tmp/ward.log"
    echo "  Preview of failures:"
    grep -A 3 "FAIL" /tmp/ward.log | head -10 | sed 's/^/    /'
fi
echo ""

# 6. Coverage check
echo "Checking code coverage..."
coverage run -m ward --path tests/ > /dev/null 2>&1
COVERAGE_EXIT=$?
if [ $COVERAGE_EXIT -eq 0 ]; then
    coverage report > /tmp/coverage.log 2>&1
    COVERAGE=$(grep "TOTAL" /tmp/coverage.log | awk '{print $NF}' | sed 's/%//')
    if [ -n "$COVERAGE" ]; then
        if (( $(echo "$COVERAGE < 70" | bc -l) )); then
            echo -e "${YELLOW}[WARN]${NC} Coverage is below 70% ($COVERAGE%)"
        else
            print_status 0 "Coverage: $COVERAGE%"
        fi
    else
        print_status 0 "Coverage report generated"
    fi
else
    print_status 1 "Coverage check failed"
fi
echo ""

# 7. Dependency audit (if pip-audit is available)
if command -v pip-audit &> /dev/null; then
    echo "Running dependency vulnerability scan..."
    pip-audit > /tmp/pip-audit.log 2>&1
    AUDIT_EXIT=$?
    if [ $AUDIT_EXIT -eq 0 ]; then
        print_status 0 "No vulnerable dependencies found"
    else
        print_status 1 "Vulnerable dependencies found - see /tmp/pip-audit.log"
        echo "  Preview of issues:"
        head -10 /tmp/pip-audit.log | sed 's/^/    /'
    fi
    echo ""
else
    echo -e "${YELLOW}[SKIP]${NC} pip-audit not installed (optional)"
    echo ""
fi

# Summary
echo "================================"
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}[PASS] All checks passed!${NC}"
    echo "You're ready to push!"
    exit 0
else
    echo -e "${RED}[FAIL] Some checks failed${NC}"
    echo "Please fix the issues before pushing."
    echo ""
    echo "Log files are in /tmp:"
    echo "  - /tmp/flake8.log"
    echo "  - /tmp/bandit.log"
    echo "  - /tmp/ward.log"
    echo "  - /tmp/coverage.log"
    if command -v radon &> /dev/null; then
        echo "  - /tmp/radon.log"
    fi
    if command -v pip-audit &> /dev/null; then
        echo "  - /tmp/pip-audit.log"
    fi
    exit 1
fi
