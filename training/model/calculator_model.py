"""Calculator business rules and arithmetic operations."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

Number = int | float | Decimal


def add(left: Number, right: Number) -> Number:
	return left + right


def subtract(left: Number, right: Number) -> Number:
	return left - right


def multiply(left: float, right: float) -> float:
	return left * right


def divide(left: float, right: float) -> float:
	if right == 0:
		raise ZeroDivisionError("division by zero")
	return left / right


def modulus(left: float, right: float) -> float:
	if right == 0:
		raise ZeroDivisionError("modulus by zero")
	return left % right


OPERATIONS: dict[str, Callable[[float, float], float]] = {
	"+": add,
	"add": add,
	"-": subtract,
	"sub": subtract,
	"subtract": subtract,
	"*": multiply,
	"x": multiply,
	"mul": multiply,
	"multiply": multiply,
	"/": divide,
	"div": divide,
	"divide": divide,
	"%": modulus,
	"mod": modulus,
	"modulus": modulus,
}


def calculate(operation: str, left: float, right: float) -> float:
	try:
		calculator = OPERATIONS[operation.strip().lower()]
	except KeyError as exc:
		raise ValueError(f"Unsupported operation: {operation}") from exc
	return calculator(left, right)