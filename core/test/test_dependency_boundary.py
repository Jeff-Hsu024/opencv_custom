import ast
from pathlib import Path
import unittest


FORBIDDEN_TOP_LEVEL = {
    "application",
    "cli",
    "mcp",
    "vision",
    "interfaces",
}


class TestDependencyBoundary(unittest.TestCase):
    def test_core_does_not_import_higher_layers(self):
        core_root = Path(__file__).resolve().parents[1]
        violations = []
        for py_file in core_root.rglob("*.py"):
            if "test" in py_file.parts:
                continue
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        if top in FORBIDDEN_TOP_LEVEL:
                            violations.append(f"{py_file}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    top = node.module.split(".")[0]
                    if top in FORBIDDEN_TOP_LEVEL:
                        violations.append(f"{py_file}: from {node.module} import ...")
        self.assertEqual(violations, [], f"Forbidden higher-layer imports in core: {violations}")


if __name__ == "__main__":
    unittest.main()
