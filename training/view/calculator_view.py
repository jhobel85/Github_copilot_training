"""Calculator application view and command-line interface."""

from __future__ import annotations

import sys

from controller.calculator_controller import run


def _prompt_float(prompt: str) -> str:
	return input(prompt)


def run_interactive() -> int:
	print("Calculator")
	while True:
		operation = input("Operation (+, -, *, /, %) or q to quit: ").strip()
		if operation.lower() in {"q", "quit", "exit"}:
			return 0

		left_text = _prompt_float("First number: ")
		right_text = _prompt_float("Second number: ")

		try:
			result = run(operation, left_text, right_text)
		except ValueError as error:
			print(error)
			continue
		except ZeroDivisionError as error:
			print(error)
			continue

		print(f"Result: {result}")
		print()


def main(argv: list[str] | None = None) -> int:
	arguments = sys.argv[1:] if argv is None else argv
	if not arguments:
		return run_interactive()

	if len(arguments) != 3:
		print("Usage: calculator.py OPERATION LEFT RIGHT")
		return 1

	operation, left_text, right_text = arguments
	try:
		result = run(operation, left_text, right_text)
	except ValueError as error:
		print(error)
		return 1
	except ZeroDivisionError as error:
		print(error)
		return 1

	print(result)
	return 0