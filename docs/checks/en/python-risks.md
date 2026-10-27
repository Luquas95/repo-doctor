# python-risks – Risky patterns in Python

**Category:** Security · **Severity:** MED (some rules LOW) · **Automatic fix:** no

## What the check looks for

Parses `*.py` files (`ast.parse`, nothing is executed or imported) and looks for: `eval()`/`exec()` with a non-constant argument, `shell=True`, `os.system()`/`os.popen()`, `pickle.load(s)`/`marshal.load(s)`, `yaml.load()` without `SafeLoader`, `verify=False`, `app.run(debug=True)` (all MED) and bare `except:`, `breakpoint()`/`pdb.set_trace()`, `tempfile.mktemp()` and `DEBUG = True` in a `settings*.py` file (LOW). Tests (`tests/`, `test_*.py`) and vendored code (`node_modules`, `vendor`, `.venv`) are skipped. One finding per file and rule, with the first line and the number of occurrences; above 50 findings an "Incomplete scan" finding is added.

## Why it matters

These patterns are the most common route to command injection, code execution when loading data, or eavesdropping through disabled TLS. Debugging leftovers and bare `except:` hide errors nobody then sees.

## Steps

1. Replace `shell=True` with an argument list: `subprocess.run(["ls", path], check=True)`.
2. Use `ast.literal_eval`, JSON and `yaml.safe_load` instead of `eval`/`pickle`/`yaml.load`.
3. If the use is intentional and the input trusted, add the finding to the allowlist and comment why.
