"""The import rules that keep each capability replaceable. They are checked, not hoped for."""
import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "reqx"
PURE_LIBRARIES = {"pydantic", "pathspec"}


def imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def reqx_imports(path: Path) -> set[str]:
    return {name for name in imports(path) if name == "reqx" or name.startswith("reqx.")}


def module_files():
    for folder in sorted((SRC / "modules").iterdir()):
        if folder.is_dir() and folder.name != "__pycache__":
            for path in sorted(folder.glob("*.py")):
                yield folder.name, path


def test_a_domain_imports_only_the_kernel_and_itself():
    """Rule 1: a domain knows nothing of ports, use cases, other modules or adapters."""
    for module, path in module_files():
        if path.name != "domain.py":
            continue
        for name in reqx_imports(path):
            assert name.startswith("reqx.kernel") or name == f"reqx.modules.{module}.domain", f"{path}: {name}"


def test_a_module_reaches_another_only_through_its_facade():
    """Rule 2: use cases, ports and facades may use another capability's facade, never its insides."""
    for module, path in module_files():
        for name in reqx_imports(path):
            if name.startswith("reqx.modules.") and not name.startswith(f"reqx.modules.{module}."):
                assert name.endswith(".facade"), f"{path}: {name}"


def test_no_module_and_no_kernel_file_imports_an_adapter():
    """Rule 3: the dependency points inward. Only the host knows the adapters."""
    for path in list((SRC / "modules").rglob("*.py")) + list((SRC / "kernel").rglob("*.py")):
        for name in reqx_imports(path):
            assert not name.startswith("reqx.host"), f"{path}: {name}"


def test_the_kernel_imports_no_module():
    for path in (SRC / "kernel").rglob("*.py"):
        for name in reqx_imports(path):
            assert name.startswith("reqx.kernel"), f"{path}: {name}"


def test_every_module_has_a_domain_use_cases_and_a_facade():
    for folder in sorted((SRC / "modules").iterdir()):
        if folder.is_dir() and folder.name != "__pycache__":
            names = {p.name for p in folder.glob("*.py")}
            assert {"use_cases.py", "facade.py"} <= names, folder
            assert "domain.py" in names or folder.name == "extraction", folder
