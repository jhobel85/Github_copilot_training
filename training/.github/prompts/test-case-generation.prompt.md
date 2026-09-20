---
name: test-case-generation
description: Use when generating tests for Python changes after a focused code review.
---

First, run the /performance-review command (a focused code review of performance characteristics), then generate test cases.

Use the findings from /performance-review to prioritize test cases that cover identified risk areas or performance-sensitive code paths. If /performance-review cannot be run or returns no actionable findings, proceed with test generation based on the code diff alone and note this in the output.

Generate pytest unit tests covering happy paths, edge cases, and error conditions for each changed function. Include at least one test per public function modified.