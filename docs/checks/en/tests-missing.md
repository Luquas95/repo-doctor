# tests-missing – Project without tests

**Category:** Maintenance · **Severity:** LOW · **Automatic fix:** no

## What the check looks for

Applies to repositories with at least 5 source files (Python, Node/TypeScript, Rust, Go; excluding `node_modules`, `vendor` and tests). Looks for tests: `tests/`, `test/`, `__tests__/`, `spec/` directories, `test_*.py`, `*_test.py`, `*_test.go`, `*.test.ts`, `*.spec.js` files and similar; for Rust also `#[test]` and `#[cfg(test)]` in sources. No test is run.

## Why it matters

Without tests every change is verified by hand and regressions surface at the users. The bigger the project, the more expensive adding them later is.

## Steps

1. Start with one test of the most important function (`pytest`, `vitest`, `cargo test`, `go test`).
2. Add the command to CI and pre-push (the `tests-not-in-ci` check then makes sure it really runs).
3. A small script or sample repository does not need tests; in that case add the finding to the allowlist.
