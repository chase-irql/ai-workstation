import ast
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "src" / "notifications"


def names_defined(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def imports_shared_helper(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {"validation", "notifications.validation"}:
            if any(alias.name == "normalize_recipient" for alias in node.names):
                return True
    return False


result = subprocess.run(
    [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
    cwd=ROOT,
    check=False,
)
if result.returncode:
    raise SystemExit(result.returncode)

validation = SOURCE / "validation.py"
if "normalize_recipient" not in names_defined(validation):
    raise SystemExit("validation.py must define normalize_recipient")

for channel in ("email.py", "sms.py"):
    path = SOURCE / channel
    if "normalize_recipient" in names_defined(path):
        raise SystemExit(f"{channel} still defines normalize_recipient locally")
    if not imports_shared_helper(path):
        raise SystemExit(f"{channel} must import normalize_recipient from validation")

print("structural refactor checks passed")
