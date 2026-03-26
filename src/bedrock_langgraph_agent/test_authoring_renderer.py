from __future__ import annotations

from .test_authoring_models import GeneratedTestPlan, GeneratedTestStep


def render_generated_test_module(plan: GeneratedTestPlan) -> str:
    lines: list[str] = [
        "from __future__ import annotations",
        "",
        "import importlib.util",
        "import os",
        "from pathlib import Path",
        "import shutil",
        "import tempfile",
        "",
        "import pytest",
        "from selenium import webdriver",
        "",
        "RUN_ROOT = Path(__file__).resolve().parents[1]",
        "",
        "",
        "def _load_page_class(relative_module_path: str, class_name: str):",
        "    module_path = RUN_ROOT / relative_module_path",
        "    module_name = f\"proofica_{module_path.stem}\"",
        "    spec = importlib.util.spec_from_file_location(module_name, module_path)",
        "    if spec is None or spec.loader is None:",
        "        raise RuntimeError(f\"Unable to load page object module from {module_path}.\")",
        "    module = importlib.util.module_from_spec(spec)",
        "    spec.loader.exec_module(module)",
        "    return getattr(module, class_name)",
        "",
        "",
        "@pytest.fixture",
        "def driver():",
        "    options = webdriver.ChromeOptions()",
        "    if os.environ.get(\"PROOFICA_HEADLESS\", \"1\") != \"0\":",
        "        options.add_argument(\"--headless=new\")",
        "    profile_dir = Path(tempfile.mkdtemp(prefix=\"proofica-test-chrome-\"))",
        "    options.add_argument(\"--window-size=1440,1400\")",
        "    options.add_argument(f\"--user-data-dir={profile_dir}\")",
        "    options.add_argument(\"--remote-debugging-pipe\")",
        "    options.add_argument(\"--disable-dev-shm-usage\")",
        "    options.add_argument(\"--disable-gpu\")",
        "    options.add_argument(\"--no-first-run\")",
        "    options.add_argument(\"--no-default-browser-check\")",
        "    options.add_argument(\"--disable-background-networking\")",
        "    options.add_argument(\"--no-sandbox\")",
        "    driver = webdriver.Chrome(options=options)",
        "    driver.set_page_load_timeout(30)",
        "    try:",
        "        yield driver",
        "    finally:",
        "        driver.quit()",
        "        shutil.rmtree(profile_dir, ignore_errors=True)",
        "",
        "",
        f"def {plan.test_name}(driver):",
    ]

    for open_step in _unique_open_steps(plan.steps):
        class_variable = _class_variable_name(open_step)
        lines.append(
            f"    {class_variable} = _load_page_class("
            f"{open_step.page_object_relative_path!r}, {open_step.class_name!r})"
        )

    if _unique_open_steps(plan.steps):
        lines.append("")

    for step in plan.steps:
        if step.step_type == "open_page":
            class_variable = _class_variable_name(step)
            lines.append(f"    driver.get({step.url!r})")
            if step.page_title:
                lines.append(f"    assert driver.title == {step.page_title!r}")
            lines.append(f"    {step.variable_name} = {class_variable}(driver)")
            lines.append(f"    assert {step.variable_name} is not None")
            lines.append("")
            continue

        if step.step_type == "page_object_call":
            args = ", ".join(repr(argument) for argument in step.args)
            if args:
                lines.append(f"    {step.variable_name}.{step.method_name}({args})")
            else:
                lines.append(f"    {step.variable_name}.{step.method_name}()")
            continue

        if step.step_type == "scroll":
            lines.append(
                "    driver.execute_script("
                "\"window.scrollTo(0, document.body.scrollHeight * arguments[0]);\", "
                f"{step.scroll_fraction!r})"
            )

    if lines[-1] != "":
        lines.append("")

    return "\n".join(lines)


def _unique_open_steps(steps: list[GeneratedTestStep]) -> list[GeneratedTestStep]:
    unique_steps: list[GeneratedTestStep] = []
    seen_keys: set[tuple[str | None, str | None]] = set()
    for step in steps:
        if step.step_type != "open_page":
            continue
        key = (step.page_object_relative_path, step.class_name)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique_steps.append(step)
    return unique_steps


def _class_variable_name(step: GeneratedTestStep) -> str:
    class_name = step.class_name or "PageObject"
    snake = []
    for index, character in enumerate(class_name):
        if character.isupper() and index > 0:
            snake.append("_")
        snake.append(character.lower())
    return "".join(snake) + "_cls"
