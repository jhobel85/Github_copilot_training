---
description: Project-specific guidance for Python source files
applyTo: '**/*.py'
---

## Tech Stack

This project uses Python for small console applications and utility functions. Keep implementations compatible with the repository's configured Python interpreter and standard library unless a dependency is clearly necessary.

## Coding Conventions

- Prefer clear, small functions with descriptive names and four-space indentation.
- Use standard Python formatting and include type hints for new or substantially changed public functions when they improve clarity.
- Preserve existing public behavior, including user-facing messages and error handling, unless the task explicitly changes it.
- Keep console input/output at the application boundary; keep reusable calculation logic in functions.

## Testing Requirements

- Add or update focused tests for changed calculation and error-handling behavior.
- At minimum, cover normal inputs and division or modulus by zero for arithmetic helpers.
- Run the smallest relevant Python test or script command after changes, and report any unavailable test setup.

## Code Review Checklist

- Check numeric behavior, edge cases, and error handling.
- Check that changes do not introduce unexpected console side effects or break existing function callers.
- Check for unnecessary dependencies, unclear naming, and avoidable duplication.