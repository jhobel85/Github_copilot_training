import pytest

from controller.calculator_controller import parse_number, run
from model.calculator_model import add, calculate, divide, modulus, multiply, subtract


def test_add() -> None:
	assert add(2, 3) == 5


def test_subtract() -> None:
	assert subtract(7, 4) == 3


def test_multiply() -> None:
	assert multiply(6, 5) == 30


def test_divide() -> None:
	assert divide(8, 2) == 4


def test_modulus() -> None:
	assert modulus(9, 4) == 1


def test_divide_by_zero() -> None:
	with pytest.raises(ZeroDivisionError, match="division by zero"):
		divide(1, 0)


def test_modulus_by_zero() -> None:
	with pytest.raises(ZeroDivisionError, match="modulus by zero"):
		modulus(1, 0)


def test_calculate_rejects_unknown_operation() -> None:
	with pytest.raises(ValueError, match="Unsupported operation"):
		calculate("pow", 2, 3)


def test_parse_number_rejects_invalid_input() -> None:
	with pytest.raises(ValueError, match="Invalid number: abc"):
		parse_number("abc")


def test_run_adds_numbers() -> None:
	assert run("add", "2", "3") == 5
