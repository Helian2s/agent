from __future__ import annotations

from dataclasses import dataclass
import ast

from .page_object_policy import PageSpec


@dataclass(frozen=True)
class VerificationResult:
    is_valid: bool
    errors: list[str]


def verify_page_object(code: str, page_spec: PageSpec) -> VerificationResult:
    errors: list[str] = []

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return VerificationResult(
            is_valid=False,
            errors=[f"Generated Python is not valid syntax: {exc.msg} (line {exc.lineno})"],
        )

    class_node = _find_class(tree, page_spec.class_name)
    if class_node is None:
        return VerificationResult(
            is_valid=False,
            errors=[f"Expected a class named {page_spec.class_name}, but it was not found."],
        )

    import_map = _collect_imports(tree)
    if import_map.get("By") != "selenium.webdriver.common.by":
        errors.append(
            "Expected `By` to be imported from `selenium.webdriver.common.by`."
        )

    needs_select = any(element.action == "choose" for element in page_spec.elements)
    if needs_select and import_map.get("Select") != "selenium.webdriver.support.ui":
        errors.append(
            "Expected `Select` to be imported from `selenium.webdriver.support.ui` because the page contains a `<select>` element."
        )

    method_map = {
        node.name: node for node in class_node.body if isinstance(node, ast.FunctionDef)
    }
    locator_map = _collect_locator_assignments(class_node)

    init_method = method_map.get("__init__")
    if init_method is None:
        errors.append("Expected an `__init__(self, driver)` method.")
    else:
        if len(init_method.args.args) != 2 or init_method.args.args[1].arg != "driver":
            errors.append("`__init__` must take exactly `(self, driver)`.")
        if not _assigns_self_driver(init_method):
            errors.append("`__init__` must assign `self.driver = driver`.")

    for element in page_spec.elements:
        locator = locator_map.get(element.locator_name)
        if locator is None:
            errors.append(f"Missing locator constant `{element.locator_name}`.")
        else:
            actual_by, actual_value = locator
            if actual_by != element.by_member or actual_value != element.selector_value:
                errors.append(
                    (
                        f"Locator `{element.locator_name}` must be "
                        f"(By.{element.by_member}, {element.selector_value!r}), "
                        f"but found (By.{actual_by}, {actual_value!r})."
                    )
                )

        method = method_map.get(element.method_name)
        if method is None:
            errors.append(f"Missing method `{element.method_name}`.")
            continue

        errors.extend(_verify_method_contract(method, element.locator_name, element.action))

    return VerificationResult(is_valid=not errors, errors=errors)


def collect_page_object_locators(
    code: str,
    class_name: str,
) -> dict[str, tuple[str, str]]:
    tree = ast.parse(code)
    class_node = _find_class(tree, class_name)
    if class_node is None:
        raise ValueError(f"Expected a class named {class_name}, but it was not found.")
    return _collect_locator_assignments(class_node)


def render_verification_feedback(result: VerificationResult) -> str:
    if result.is_valid:
        return "Verifier accepted the page object."

    lines = ["Verifier rejected the page object for these reasons:"]
    for error in result.errors:
        lines.append(f"- {error}")
    return "\n".join(lines)


def _find_class(tree: ast.Module, class_name: str) -> ast.ClassDef | None:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    return None


def _collect_imports(tree: ast.Module) -> dict[str, str]:
    imports: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        module_name = node.module or ""
        for alias in node.names:
            imports[alias.asname or alias.name] = module_name
    return imports


def _collect_locator_assignments(class_node: ast.ClassDef) -> dict[str, tuple[str, str]]:
    locators: dict[str, tuple[str, str]] = {}

    for node in class_node.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        if not isinstance(node.value, ast.Tuple) or len(node.value.elts) != 2:
            continue

        by_node, value_node = node.value.elts
        if not (
            isinstance(by_node, ast.Attribute)
            and isinstance(by_node.value, ast.Name)
            and by_node.value.id == "By"
            and isinstance(value_node, ast.Constant)
            and isinstance(value_node.value, str)
        ):
            continue

        locators[node.targets[0].id] = (by_node.attr, value_node.value)

    return locators


def _assigns_self_driver(method: ast.FunctionDef) -> bool:
    for node in ast.walk(method):
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
            and target.attr == "driver"
        ):
            continue
        if isinstance(node.value, ast.Name) and node.value.id == "driver":
            return True
    return False


def _verify_method_contract(
    method: ast.FunctionDef,
    locator_name: str,
    action: str,
) -> list[str]:
    errors: list[str] = []
    rendered = ast.unparse(method)

    if locator_name not in rendered:
        errors.append(
            f"Method `{method.name}` must reference the locator constant `{locator_name}`."
        )

    if action == "fill":
        if method.args.args[-1].arg != "value":
            errors.append(f"Method `{method.name}` must accept a `value` argument.")
        if "clear(" not in rendered or "send_keys(" not in rendered:
            errors.append(
                f"Method `{method.name}` must clear the element and then send keys."
            )
    elif action == "choose":
        if method.args.args[-1].arg != "value":
            errors.append(f"Method `{method.name}` must accept a `value` argument.")
        if "Select(" not in rendered or "select_by_visible_text(" not in rendered:
            errors.append(
                f"Method `{method.name}` must use `Select(...).select_by_visible_text(value)`."
            )
    elif action == "set":
        if method.args.args[-1].arg != "checked":
            errors.append(f"Method `{method.name}` must accept a `checked` argument.")
        if "is_selected(" not in rendered or "click(" not in rendered:
            errors.append(
                f"Method `{method.name}` must compare the current checkbox state and click when needed."
            )
    elif action == "click":
        if len(method.args.args) != 1:
            errors.append(f"Method `{method.name}` must not accept extra arguments.")
        if "click(" not in rendered:
            errors.append(f"Method `{method.name}` must click the target element.")

    return errors
