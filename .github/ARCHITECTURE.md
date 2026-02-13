# CI/CD Pipeline Architecture

## Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         Developer Workflow                       │
└─────────────────────────────────────────────────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │   git push / PR opened   │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   GitHub Actions         │
                    │   Workflow Triggered     │
                    └────────────┬────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
    ┌────▼────┐            ┌────▼────┐            ┌────▼────┐
    │  Lint   │            │ Security│            │  Test   │
    │ (fast)  │            │ (medium)│            │ (slow)  │
    └────┬────┘            └────┬────┘            └────┬────┘
         │                       │                       │
    ┌────▼────────┐        ┌────▼────────┐        ┌────▼────────┐
    │ flake8      │        │ bandit      │        │ Python 3.10 │
    │ pylint      │        │ safety      │        │ Python 3.11 │
    │             │        │ pip-audit   │        │ Python 3.12 │
    │             │        │             │        │ Python 3.13 │
    └─────────────┘        └─────────────┘        └──────┬──────┘
                                                          │
                                                    ┌─────▼──────┐
                                                    │  Coverage  │
                                                    │  Report    │
                                                    └─────┬──────┘
                                                          │
         ┌────────────────────────────────────────────────┤
         │                                                │
    ┌────▼────┐                                    ┌─────▼──────┐
    │ Docker  │                                    │  Summary   │
    │  Build  │                                    │   Report   │
    └────┬────┘                                    └─────┬──────┘
         │                                                │
         └────────────────────┬───────────────────────────┘
                              │
                     ┌────────▼────────┐
                     │  All Jobs Done  │
                     └────────┬────────┘
                              │
                    ┌─────────▼─────────┐
                    │   [PASS] All Pass?    │
                    └─────────┬─────────┘
                              │
                 ┌────────────┴────────────┐
                 │                         │
           ┌─────▼─────┐            ┌─────▼─────┐
           │  Success  │            │  Failure  │
           │ Can merge │            │ Fix issues│
           └───────────┘            └───────────┘
```

## Job Dependencies

```
ci.yml:
  lint ──────────────┐
  security ──────────┤
  code-quality ──────┤
  test ──────────────┼──► coverage ──┐
  docker-build ──────┘                ├──► summary
                                      │
pr-checks.yml:                        │
  pr-validation ──┐                   │
  code-diff ──────┼──► comment ───────┘
  security-diff ──┘
```

## Timeline (Typical Run)

```
0:00  ├── Jobs start in parallel
0:05  │   ├── Lint [PASS] (5s)
0:15  │   ├── Security [PASS] (15s)
0:20  │   ├── Code Quality [PASS] (20s)
0:30  │   ├── Docker Build [PASS] (30s)
1:00  │   └── Tests (Python 3.10) [PASS] (1m)
1:05  │       ├── Tests (Python 3.11) [PASS] (1m 5s)
1:10  │       ├── Tests (Python 3.12) [PASS] (1m 10s)
1:15  │       └── Tests (Python 3.13) [PASS] (1m 15s)
1:45  ├── Coverage Report [PASS] (1m 45s)
1:50  └── Summary [PASS] (1m 50s)

Total: ~2 minutes
```

## Artifact Generation

```
Test Run
  │
  ├── Test Results
  │   ├── test-results-3.10.tar.gz
  │   ├── test-results-3.11.tar.gz
  │   ├── test-results-3.12.tar.gz
  │   └── test-results-3.13.tar.gz
  │
  ├── Coverage Report
  │   ├── coverage.xml
  │   └── htmlcov/
  │
  └── Security Reports
      ├── bandit-report.json
      ├── safety-report.json
      └── pip-audit-report.json
```

## Trigger Matrix

| Event | ci.yml | pr-checks.yml | dependency-check.yml |
|-------|--------|---------------|---------------------|
| Push to main | [PASS] | [FAIL] | Only if deps changed |
| Push to develop | [PASS] | [FAIL] | Only if deps changed |
| Push to hooks | [PASS] | [FAIL] | Only if deps changed |
| PR opened | [PASS] | [PASS] | [FAIL] |
| PR updated | [PASS] | [PASS] | [FAIL] |
| Monday 9am UTC | [FAIL] | [FAIL] | [PASS] |
| Manual trigger | [FAIL] | [FAIL] | [PASS] |

## Cache Strategy

```
Python Dependencies
  └── pip cache
      ├── requirements.txt hash
      └── requirements-test.txt hash

Docker Layers
  └── GitHub Actions cache
      ├── Base image layers
      └── Dependency layers

Playwright Browsers
  └── System cache
      └── Chromium binary
```

## Status Check Requirements

For merging PRs, these must pass:

```
Required Checks:
  ├── lint
  ├── test (all Python versions)
  ├── coverage
  └── docker-build

Optional (informational):
  ├── security
  ├── code-quality
  └── pr-validation
```

## Notification Flow

```
Workflow Started
  │
  ├─► GitHub Status API
  │     └─► PR/Commit Status Badge
  │
  ├─► Workflow Summary
  │     └─► Detailed Results
  │
  └─► PR Comment (if PR)
        └─► Status Update
```

## Resource Usage

### Compute Time (per run)
- Lint: ~5 seconds
- Security: ~15 seconds
- Code Quality: ~20 seconds
- Test (per version): ~1 minute
- Coverage: ~1.5 minutes
- Docker Build: ~30 seconds

**Total: ~2 minutes (parallel execution)**

### GitHub Actions Minutes
- Free tier: 2,000 minutes/month
- This pipeline: ~2 minutes per run
- Estimated capacity: ~1,000 runs/month

### Storage
- Artifacts kept for 90 days
- ~10MB per run
- Free tier: 500MB storage

## Optimization Strategies

1. **Caching**: pip packages, Docker layers
2. **Parallelization**: Independent jobs run simultaneously  
3. **Matrix Testing**: Multiple Python versions in parallel
4. **Conditional Runs**: Skip unchanged paths
5. **Incremental Checks**: PR checks only on changed files

## Monitoring Points

- [PASS] Job success/failure rates
- ⏱️ Job duration trends
- [PACKAGE] Artifact sizes
- 🔄 Cache hit rates
- 💰 Minutes usage
