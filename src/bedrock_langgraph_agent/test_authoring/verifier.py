from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class GeneratedTestVerificationResult:
    is_valid: bool
    errors: list[str]


def verify_generated_test_module(code: str) -> GeneratedTestVerificationResult:
    errors: list[str] = []

    try:
        module = ast.parse(code)
    except SyntaxError as exc:
        return GeneratedTestVerificationResult(
            is_valid=False,
            errors=[f"Generated Python is not valid syntax: {exc.msg} (line {exc.lineno})"],
        )

    has_pytest_import = False
    has_driver_fixture = False
    has_test_function = False
    has_page_loader = False

    for node in module.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "pytest":
                    has_pytest_import = True
        elif isinstance(node, ast.ImportFrom):
            if node.module == "pytest":
                has_pytest_import = True
        elif isinstance(node, ast.FunctionDef):
            if node.name == "_load_page_class":
                has_page_loader = True
            if node.name.startswith("test_"):
                has_test_function = True
            if node.name == "driver" and _has_pytest_fixture_decorator(node):
                has_driver_fixture = True

    if not has_pytest_import:
        errors.append("Generated test module does not import `pytest`.")
    if not has_driver_fixture:
        errors.append("Generated test module does not define a `driver` pytest fixture.")
    if not has_test_function:
        errors.append("Generated test module does not define a `test_*` function.")
    if not has_page_loader:
        errors.append("Generated test module does not define the `_load_page_class` helper.")

    return GeneratedTestVerificationResult(is_valid=not errors, errors=errors)


def _has_pytest_fixture_decorator(node: ast.FunctionDef) -> bool:
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Attribute):
            if (
                isinstance(decorator.value, ast.Name)
                and decorator.value.id == "pytest"
                and decorator.attr == "fixture"
            ):
                return True
        if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
            if (
                isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "pytest"
                and decorator.func.attr == "fixture"
            ):
                return True
    return False
