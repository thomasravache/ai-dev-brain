"""Checadores das regras do ADR-0017, usados por test_architecture.py (SPEC-0054:UT-07).

Escritos aqui, sem importar das skills (o padrão é o de skills/boson-atlas/tests/architecture_rules.py, copiado).
Cada checador recebe o código-fonte e devolve uma linha por violação: "<arquivo>:<linha> — <regra> — <achado>".

Regras:
- só biblioteca padrão;
- nenhum import de código das skills (nem de tools/), nem carregamento dinâmico de código (importlib,
  __import__, runpy, exec, sys.path): o servidor só fala com as skills pela CLI;
- nenhum shell (shell= diferente de False, os.system, os.popen, create_subprocess_shell, getoutput);
- processo externo só dentro da função executora (run_cli) e só para a CLI do atlas: nenhum texto aponta para
  a CLI de outra skill.
"""
import ast
import importlib.util
import re
import sys
import sysconfig
from pathlib import Path

RULE_STDLIB = "só biblioteca padrão"
RULE_SKILLS = "nenhum import de skills/ nem carregamento de código"
RULE_SHELL = "processos sem shell"
RULE_PROCESS = "processo só na função executora"
RULE_ATLAS_ONLY = "processo só para a CLI do atlas"

# módulos das skills (nomes novos e antigos), de tools/ e das suítes de teste
SKILL_MODULES = ("atlas", "spec_graph", "brain", "brain_support", "tools", "architecture_rules", "helpers",
                 "sdd_management", "gluon_spec", "photon_brain", "boson_atlas", "org_atlas", "second_brain")
DYNAMIC_LOADERS = {
    "importlib": {"import_module", "__import__", "reload"},
    "importlib.util": {"spec_from_file_location", "module_from_spec", "spec_from_loader"},
    "runpy": {"run_path", "run_module"},
}
DYNAMIC_BUILTINS = {"__import__", "exec", "eval", "compile"}
SYS_PATH_MUTATORS = {"insert", "append", "extend", "__setitem__"}
PROCESS_CALLS = {
    "subprocess": {"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"},
    "os": {"system", "popen", "execv", "execve", "execvp", "execvpe", "execl", "execle", "execlp", "execlpe",
           "spawnv", "spawnve", "spawnvp", "spawnvpe", "spawnl", "spawnle", "posix_spawn", "posix_spawnp",
           "fork", "forkpty"},
    "asyncio": {"create_subprocess_exec", "create_subprocess_shell"},
    "pty": {"spawn", "fork"},
}
SHELL_CALLS = {"os.system", "os.popen", "subprocess.getoutput", "subprocess.getstatusoutput",
               "asyncio.create_subprocess_shell"}
# CLIs e pastas de outras skills (nomes novos e antigos) e tools/sdd/ (métodos MCP como tools/list não contam)
OTHER_CLI = re.compile(r"spec_graph\.py|brain\.py|gluon-spec|photon-brain|sdd-management|second-brain"
                       r"|(^|/)tools/sdd(/|$)")


def is_stdlib(name):
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


def _matches(module, names):
    return any(module == name or module.startswith(name + ".") for name in names)


def _sorted(findings):
    return [message for _, message in sorted(findings)]


def _dotted(node):
    """'a.b.c' de Name/Attribute encadeados; None para outras expressões."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def import_findings(source, filename):
    """Imports fora da stdlib, relativos ou de módulos das skills/tools/."""
    findings = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            items = [(alias.name, 0) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            items = [(node.module or "", node.level)]
        else:
            continue
        for module, level in items:
            where = f"{filename}:{node.lineno}"
            top = module.split(".")[0]
            if level:
                findings.append((node.lineno, f"{where} — {RULE_SKILLS} — import relativo '{'.' * level}{module}'"))
            elif _matches(module, SKILL_MODULES) or "sdd" in top.lower():
                findings.append((node.lineno, f"{where} — {RULE_SKILLS} — import de '{module}'"))
            elif not is_stdlib(top):
                findings.append((node.lineno, f"{where} — {RULE_STDLIB} — import de '{top}'"))
    return _sorted(findings)


def dynamic_code_findings(source, filename):
    """Carregamento de código por fora do import: importlib, __import__, runpy, exec/eval/compile, sys.path."""
    findings = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module in DYNAMIC_LOADERS:
            names = [a.name for a in node.names if a.name in DYNAMIC_LOADERS[node.module]]
            for name in names:
                message = f"{filename}:{node.lineno} — {RULE_SKILLS} — from {node.module} import {name}"
                findings.append((node.lineno, message))
        if not isinstance(node, ast.Call):
            continue
        name = _dotted(node.func)
        if name is None:
            continue
        module, _, func = name.rpartition(".")
        loader = module in DYNAMIC_LOADERS and func in DYNAMIC_LOADERS[module]
        builtin = not module and name in DYNAMIC_BUILTINS
        path_change = module == "sys.path" and func in SYS_PATH_MUTATORS
        if loader or builtin or path_change:
            findings.append((node.lineno, f"{filename}:{node.lineno} — {RULE_SKILLS} — {name}()"))
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                base = target.value if isinstance(target, ast.Subscript) else target
                if _dotted(base) == "sys.path":
                    findings.append((node.lineno, f"{filename}:{node.lineno} — {RULE_SKILLS} — sys.path alterado"))
    return _sorted(findings)


def _process_call(node):
    name = _dotted(node.func)
    if name is None:
        return None
    module, _, func = name.rpartition(".")
    return name if func in PROCESS_CALLS.get(module, ()) else None


def shell_findings(source, filename):
    """shell= diferente de False em qualquer chamada, e as funções que sempre usam shell."""
    findings = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.keyword) and node.arg == "shell"
                and not (isinstance(node.value, ast.Constant) and node.value.value is False)):
            line = node.value.lineno
            findings.append((line, f"{filename}:{line} — {RULE_SHELL} — shell="))
        elif isinstance(node, ast.Call) and _process_call(node) in SHELL_CALLS:
            findings.append((node.lineno, f"{filename}:{node.lineno} — {RULE_SHELL} — {_process_call(node)}"))
    return _sorted(findings)


def process_findings(source, filename, allowed=("run_cli",)):
    """Processo externo fora das funções permitidas, ou importado como nome solto (from subprocess import run)."""
    allowed = set(allowed)
    findings = []

    def visit(node, function):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function = node.name
        if isinstance(node, ast.ImportFrom) and node.module in PROCESS_CALLS:
            for alias in node.names:
                if alias.name in PROCESS_CALLS[node.module]:
                    message = f"{filename}:{node.lineno} — {RULE_PROCESS} — from {node.module} import {alias.name}"
                    findings.append((node.lineno, message))
        if isinstance(node, ast.Call):
            call = _process_call(node)
            if call and function not in allowed:
                where = f"{function}()" if function else "nível de módulo"
                findings.append((node.lineno, f"{filename}:{node.lineno} — {RULE_PROCESS} — {call} em {where}"))
        for child in ast.iter_child_nodes(node):
            visit(child, function)

    visit(ast.parse(source), None)
    return _sorted(findings)


def other_cli_findings(source, filename):
    """Textos que apontam para a CLI ou a pasta de outra skill, ou para tools/."""
    findings = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and OTHER_CLI.search(node.value):
            findings.append((node.lineno, f"{filename}:{node.lineno} — {RULE_ATLAS_ONLY} — '{node.value}'"))
    return _sorted(findings)
