"""Checadores das regras do ADR-0017, usados por test_architecture.py (SPEC-0054:UT-07).

Escritos aqui, sem importar das skills (o padrão é o de skills/boson-atlas/tests/architecture_rules.py, copiado).
Cada checador recebe o código-fonte e devolve uma linha por violação: "<arquivo>:<linha> — <regra> — <achado>".

Regras:
- só biblioteca padrão;
- nenhum import de código das skills (nem de tools/), nem carregamento dinâmico de código (importlib,
  __import__, runpy, exec, sys.path): o servidor só fala com as skills pela CLI;
- nenhum shell (shell= diferente de False, os.system, os.popen, create_subprocess_shell, getoutput, também por
  alias ou getattr, e nenhum ** numa chamada de processo);
- processo externo só dentro da função executora (run_cli), pelo nome literal do módulo (sem alias, sem
  `from subprocess import run`, sem getattr), e só para a CLI do atlas: nenhum texto aponta para a CLI de
  outra skill.
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


class _Names:
    """Nomes locais que apontam para módulos e funções de processo (import X as Y, from X import f as g)."""

    def __init__(self, tree):
        self.modules = {name: name for name in PROCESS_CALLS}
        self.functions = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in PROCESS_CALLS:
                        self.modules[alias.asname or alias.name] = alias.name
            elif isinstance(node, ast.ImportFrom) and node.module in PROCESS_CALLS:
                for alias in node.names:
                    if alias.name in PROCESS_CALLS[node.module]:
                        self.functions[alias.asname or alias.name] = f"{node.module}.{alias.name}"

    def module_of(self, node):
        name = _dotted(node)
        return self.modules.get(name) if name else None

    def getattr_target(self, node):
        """'mod.func' (ou 'mod.<dinâmico>') de getattr(<módulo de processo>, ...); None para o resto."""
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
                and node.args):
            return None
        module = self.module_of(node.args[0])
        if module is None:
            return None
        attr = node.args[1] if len(node.args) > 1 else None
        if isinstance(attr, ast.Constant) and isinstance(attr.value, str):
            return f"{module}.{attr.value}"
        return f"{module}.<dinâmico>"

    def process_call(self, node):
        """'mod.func' de uma chamada de processo, resolvendo alias de módulo, alias de função e getattr."""
        func = node.func
        if isinstance(func, ast.Call):
            target = self.getattr_target(func)
            return target if target and self._is_process(target) else None
        name = _dotted(func)
        if name is None:
            return None
        if name in self.functions:
            return self.functions[name]
        head, _, rest = name.partition(".")
        if head in self.modules and rest:
            name = f"{self.modules[head]}.{rest}"
        return name if self._is_process(name) else None

    @staticmethod
    def _is_process(name):
        module, _, func = name.rpartition(".")
        return func == "<dinâmico>" and module in PROCESS_CALLS or func in PROCESS_CALLS.get(module, ())


def shell_findings(source, filename):
    """shell= diferente de False em qualquer chamada, as funções que sempre usam shell (também por alias ou
    getattr) e qualquer ** numa chamada de processo (pode trazer shell=True escondido)."""
    tree = ast.parse(source)
    names = _Names(tree)
    findings = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.keyword) and node.arg == "shell"
                and not (isinstance(node.value, ast.Constant) and node.value.value is False)):
            line = node.value.lineno
            findings.append((line, f"{filename}:{line} — {RULE_SHELL} — shell="))
        if not isinstance(node, ast.Call):
            continue
        target = names.getattr_target(node)
        call = names.process_call(node)
        if target in SHELL_CALLS:
            findings.append((node.lineno, f"{filename}:{node.lineno} — {RULE_SHELL} — getattr {target}"))
        elif call in SHELL_CALLS and not isinstance(node.func, ast.Call):  # getattr(...)() já contou acima
            findings.append((node.lineno, f"{filename}:{node.lineno} — {RULE_SHELL} — {call}"))
        elif call and any(keyword.arg is None for keyword in node.keywords):
            findings.append((node.lineno, f"{filename}:{node.lineno} — {RULE_SHELL} — ** em {call}"))
    return _sorted(findings)


def process_findings(source, filename, allowed=("run_cli",)):
    """Processo externo fora das funções permitidas; módulo de processo com alias, função importada solta
    (from subprocess import run) ou acessada por getattr, em qualquer lugar."""
    allowed = set(allowed)
    tree = ast.parse(source)
    names = _Names(tree)
    findings = []

    def add(node, detail):
        findings.append((node.lineno, f"{filename}:{node.lineno} — {RULE_PROCESS} — {detail}"))

    def visit(node, function):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function = node.name
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in PROCESS_CALLS and alias.asname and alias.asname != alias.name:
                    add(node, f"import {alias.name} as {alias.asname}")
        elif isinstance(node, ast.ImportFrom) and node.module in PROCESS_CALLS:
            for alias in node.names:
                if alias.name in PROCESS_CALLS[node.module]:
                    add(node, f"from {node.module} import {alias.name}")
        elif isinstance(node, ast.Call):
            target = names.getattr_target(node)
            call = names.process_call(node)
            if target:
                add(node, f"getattr {target}")
            elif call and function not in allowed and not isinstance(node.func, ast.Call):
                where = f"{function}()" if function else "nível de módulo"
                add(node, f"{call} em {where}")
        for child in ast.iter_child_nodes(node):
            visit(child, function)

    visit(tree, None)
    return _sorted(findings)


def other_cli_findings(source, filename):
    """Textos que apontam para a CLI ou a pasta de outra skill, ou para tools/."""
    findings = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and OTHER_CLI.search(node.value):
            findings.append((node.lineno, f"{filename}:{node.lineno} — {RULE_ATLAS_ONLY} — '{node.value}'"))
    return _sorted(findings)
