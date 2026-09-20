"""Calculator application controller."""

from __future__ import annotations

from model.calculator_model import calculate


def parse_number(text: str) -> float:
	try:
		return float(text.strip())
	except ValueError as exc:
		raise ValueError(f"Invalid number: {text}") from exc


def run(operation: str, left_text: str, right_text: str) -> float:
	left = parse_number(left_text)
	right = parse_number(right_text)
	return calculate(operation, left, right)
