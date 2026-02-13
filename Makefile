.PHONY: help install install-dev test coverage lint security clean docker-build docker-up docker-down checks format

# Default target
help:
	@echo "Available commands:"
	@echo "  make install       - Install production dependencies"
	@echo "  make install-dev   - Install development and test dependencies"
	@echo "  make test          - Run test suite"
	@echo "  make coverage      - Run tests with coverage report"
	@echo "  make lint          - Run code linters (flake8, pylint)"
	@echo "  make security      - Run security checks (bandit, safety)"
	@echo "  make checks        - Run all pre-commit checks"
	@echo "  make format        - Format code with black and isort"
	@echo "  make clean         - Clean up generated files"
	@echo "  make docker-build  - Build Docker image"
	@echo "  make docker-up     - Start services with docker-compose"
	@echo "  make docker-down   - Stop services"

# Installation
install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements.txt
	pip install -r requirements-test.txt
	pip install pre-commit
	pre-commit install

# Testing
test:
	ward --path tests/

test-verbose:
	ward --path tests/ -v

coverage:
	coverage run -m ward --path tests/
	coverage report
	coverage html
	@echo "Coverage report generated in htmlcov/index.html"

# Code Quality
lint:
	@echo "Running flake8..."
	flake8 app/
	@echo "Running pylint..."
	pylint app/ --exit-zero

security:
	@echo "Running Bandit security scan..."
	bandit -r app/ -ll -ii
	@echo "Checking dependencies for vulnerabilities..."
	pip-audit || true
	safety check || true

complexity:
	@echo "Cyclomatic Complexity:"
	radon cc app/ -a -s
	@echo "\nMaintainability Index:"
	radon mi app/ -s

# Formatting
format:
	@echo "Formatting with black..."
	black app/ tests/ scripts/ --line-length=100
	@echo "Sorting imports with isort..."
	isort app/ tests/ scripts/ --profile black --line-length=100

# Pre-commit checks
checks:
	@./scripts/run-checks.sh

pre-commit:
	pre-commit run --all-files

# Cleanup
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.coverage" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ward" -exec rm -rf {} + 2>/dev/null || true
	rm -rf htmlcov/ coverage.xml .coverage
	rm -rf build/ dist/
	@echo "Cleanup complete"

# Docker
docker-build:
	docker build -t broke:latest .

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f

# Development server
run:
	python run.py

run-dev:
	FLASK_ENV=development FLASK_DEBUG=1 python run.py

# Database
db-migrate:
	python -m scripts.migrate

# Dependencies
deps-check:
	pip list --outdated

deps-licenses:
	pip-licenses --format=markdown

deps-tree:
	pipdeptree

# Quick development workflow
dev: clean install-dev format lint test
	@echo "Development setup complete!"

# CI simulation (runs what CI will run)
ci: clean lint security test coverage
	@echo "CI checks complete!"
