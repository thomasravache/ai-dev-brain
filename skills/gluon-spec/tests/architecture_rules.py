"""Checadores das regras estruturais do ADR-0001, usados por test_architecture.py.

Cada checador recebe o código-fonte como texto e devolve uma linha por violação:
"<arquivo>:<linha> — <regra do ADR-0001> — <o que foi encontrado>".
"""
from __future__ import annotations

import ast
import importlib.util
import sys
import sysconfig
from collections.abc import Iterable
from pathlib import Path

RULE_STDLIB = "só biblioteca padrão"
RULE_SINGLE_FILE = "arquivo único"
RULE_PROCESS = "processos só git ou comando do sdd-config"
RULE_VENDOR_COPY = "skills/ não carrega a cópia do vendor"
PROCESS_CALLS = {
    "subprocess": {"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"},
    "os": {"system", "popen", "execv", "execve", "execvp", "execvpe", "spawnv", "spawnve", "spawnvp", "spawnvpe"},
}


def is_stdlib(name: str) -> bool:
    if name in sys.builtin_module_names or name == "__future__":
        return True
    names = getattr(sys, "stdlib_module_names", None)  # Python 3.10+
    if names is not None:
        return name in names
    spec = importlib.util.find_spec(name)
    if spec is None or spec.origin is None:
        return False
    if spec.origin in ("built-in", "frozen"):
        return True
    origin = Path(spec.origin).resolve()
    stdlib = Path(sysconfig.get_paths()["stdlib"]).resolve()
    return stdlib in origin.parents and "site-packages" not in origin.parts


def import_findings(source: str, filename: str, local_modules: Iterable[str] = ()) -> list[str]:
    """Imports fora da biblioteca padrão ou de módulos locais (o script é arquivo único)."""
    local = set(local_modules)
    findings = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                message = (f"{filename}:{node.lineno} — {RULE_SINGLE_FILE} — import relativo "
                           f"'{'.' * node.level}{node.module or ''}'")
                findings.append((node.lineno, message))
                continue
            names = [node.module]
        else:
            continue
        for name in names:
            top = name.split(".")[0]
            if top in local:
                message = f"{filename}:{node.lineno} — {RULE_SINGLE_FILE} — import de módulo local '{top}'"
                findings.append((node.lineno, message))
            elif not is_stdlib(top):
                findings.append((node.lineno, f"{filename}:{node.lineno} — {RULE_STDLIB} — import de '{top}'"))
    return [message for _, message in sorted(findings)]


def _process_call(node: ast.Call) -> str | None:
    func = node.func
    if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
            and func.attr in PROCESS_CALLS.get(func.value.id, ())):
        return f"{func.value.id}.{func.attr}"
    return None


def subprocess_findings(source: str, filename: str, allowed: Iterable[str]) -> list[str]:
    """Chamadas de subprocess fora das funções permitidas."""
    allowed = set(allowed)
    findings = []

    def visit(node: ast.AST, function: str | None):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function = node.name
        if isinstance(node, ast.Call):
            call = _process_call(node)
            if call and function not in allowed:
                where = f"{function}()" if function else "nível de módulo"
                findings.append((node.lineno, f"{filename}:{node.lineno} — {RULE_PROCESS} — {call} em {where}"))
        for child in ast.iter_child_nodes(node):
            visit(child, function)

    visit(ast.parse(source), None)
    return [message for _, message in sorted(findings)]


def _mentions_vendor_copy(node: ast.AST) -> bool:
    """O nó monta o caminho da cópia: "tools/sdd" num texto, ou "tools" e "sdd" em partes (root / "tools" / "sdd")."""
    texts = [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    return any("tools/sdd" in text for text in texts) or {"tools", "sdd"} <= set(texts)


def _loads_code(node: ast.Call) -> bool:
    """sys.path.insert/append/extend, ou carregamento de arquivo (importlib, runpy)."""
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in ("insert", "append", "extend"):
        target = func.value
        return (isinstance(target, ast.Attribute) and target.attr == "path"
                and isinstance(target.value, ast.Name) and target.value.id == "sys")
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    return name in ("spec_from_file_location", "run_path", "SourceFileLoader")


def vendor_copy_findings(source: str, filename: str) -> list[str]:
    """Código que carrega a cópia do vendor (import de tools/sdd ou tools/sdd no sys.path)."""
    findings = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        elif isinstance(node, ast.Call) and _loads_code(node) and _mentions_vendor_copy(node):
            findings.append((node.lineno, f"{filename}:{node.lineno} — {RULE_VENDOR_COPY} — carrega código de tools/sdd"))
            continue
        else:
            continue
        for module in modules:
            if module == "tools.sdd" or module.startswith("tools.sdd."):
                findings.append((node.lineno, f"{filename}:{node.lineno} — {RULE_VENDOR_COPY} — import de '{module}'"))
    return [message for _, message in sorted(findings)]
