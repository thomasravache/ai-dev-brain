"""Checadores das regras do ADR-0010, usados por test_architecture.py (SPEC-0032:UT-05).

Escritos aqui, sem importar de outra skill (ADR-0010 proíbe import entre skills).
Cada checador recebe o código-fonte (ou o texto do arquivo) e devolve uma linha por violação:
"<arquivo>:<linha> — <regra> — <o que foi encontrado>".
"""
import ast
import importlib.util
import re
import sys
import sysconfig
from pathlib import Path

RULE_STDLIB = "só biblioteca padrão"
RULE_SINGLE_FILE = "arquivo único"
RULE_CROSS_SKILL = "nenhum import entre skills nem de tools/"
RULE_PROCESS = "processos externos só em run_collector"
RULE_SHELL = "processos sem shell"
RULE_COLLECTOR_PROCESS = "processos externos do coletor só em"
RULE_COLLECTOR_NO_PROCESS = "coletor sem processo externo"
RULE_COLLECTOR_PROCESS_ARGS = "processos do coletor com lista de argumentos, sem os.system/os.popen"
RULE_PERSONAL_PATH = "nenhum caminho pessoal absoluto"

# módulos das outras skills (gluon-spec e photon-brain, antes sdd-management e second-brain) e de tools/
FORBIDDEN_MODULES = ("spec_graph", "sdd_management", "gluon_spec", "tools", "architecture_rules", "brain",
                     "brain_support", "brain_architecture_rules", "second_brain", "photon_brain")
# textos que apontam para outra skill ou para tools/ (ex.: sys.path com a photon-brain); nomes novos e antigos
CROSS_SKILL_PATH = re.compile(r"gluon-spec|photon-brain|sdd-management|second-brain|(^|/)tools/")
PROCESS_CALLS = {
    "subprocess": {"run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"},
    "os": {"system", "popen", "execv", "execve", "execvp", "execvpe", "execl", "execle", "execlp", "execlpe",
           "spawnv", "spawnve", "spawnvp", "spawnvpe", "spawnl", "spawnle", "posix_spawn", "posix_spawnp"},
    "asyncio": {"create_subprocess_exec", "create_subprocess_shell"},
}
# Placeholders como /Users/<nome> são permitidos; nomes reais não.
PERSONAL_PATH = re.compile(r"/Users/(?!<)[A-Za-z0-9._-]+|[A-Za-z]:\\\\?Users\\\\?(?!<)[A-Za-z0-9._-]+"
                           r"|/home/(?!<)[A-Za-z0-9._-]+")


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


def _imports(source):
    """(linha, módulo completo, nível relativo) de cada import."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name, 0
        elif isinstance(node, ast.ImportFrom):
            yield node.lineno, node.module or "", node.level


def _matches(module, names):
    return any(module == name or module.startswith(name + ".") for name in names)


def import_findings(source, filename, local_modules=()):
    """Imports fora da biblioteca padrão, de módulo local (arquivo único) ou de outra skill/tools."""
    local = set(local_modules)
    findings = []
    for line, module, level in _imports(source):
        top = module.split(".")[0]
        where = f"{filename}:{line}"
        if level:
            findings.append((line, f"{where} — {RULE_SINGLE_FILE} — import relativo '{'.' * level}{module}'"))
        elif _matches(module, FORBIDDEN_MODULES) or "sdd" in top.lower():
            findings.append((line, f"{where} — {RULE_CROSS_SKILL} — import de '{module}'"))
        elif top in local:
            findings.append((line, f"{where} — {RULE_SINGLE_FILE} — import de módulo local '{top}'"))
        elif not is_stdlib(top):
            findings.append((line, f"{where} — {RULE_STDLIB} — import de '{top}'"))
    return [message for _, message in sorted(findings)]


def imports_of(source, module_names):
    """Linhas que importam algum dos módulos (usado no sentido inverso: outra skill importando atlas)."""
    return [line for line, module, _ in _imports(source) if _matches(module, module_names)]


def cross_skill_path_findings(source, filename):
    """Textos que apontam para outra skill ou para tools/."""
    findings = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and CROSS_SKILL_PATH.search(node.value):
            findings.append((node.lineno, f"{filename}:{node.lineno} — {RULE_CROSS_SKILL} — '{node.value}'"))
    return [message for _, message in sorted(findings)]


def _is_process_name(module, name):
    """True when `name` of `module` starts an external process (exec*/spawn* of os included)."""
    if module == "os" and name.startswith(("exec", "spawn")):
        return True
    return name in PROCESS_CALLS.get(module, ())


def _process_names(tree):
    """(module aliases, imported names) of the source: {"sp": "subprocess"} and {"run": "subprocess.run"}.

    Approximation without scopes: an import anywhere in the file counts for the whole file."""
    modules = {module: module for module in PROCESS_CALLS}
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in PROCESS_CALLS:
                    modules[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module in PROCESS_CALLS:
            for alias in node.names:
                if _is_process_name(node.module, alias.name):
                    names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return modules, names


def _process_import(node):
    """Text of an import that hides a process call from the module.function check (SPEC-0046:UT-01), or None:
    from subprocess import ..., import subprocess as x and from os import system|popen|exec*|spawn*."""
    if isinstance(node, ast.Import):
        hidden = [f"import {a.name} as {a.asname}" for a in node.names
                  if a.name == "subprocess" and a.asname and a.asname != a.name]
    elif isinstance(node, ast.ImportFrom) and not node.level and node.module in PROCESS_CALLS:
        if node.module == "subprocess":
            hidden = [f"from subprocess import {a.name}" for a in node.names]
        else:
            hidden = [f"from {node.module} import {a.name}" for a in node.names if _is_process_name(node.module, a.name)]
    else:
        return None
    return ", ".join(hidden) or None


def _process_call(node, modules=None, names=None):
    """'módulo.função' of a call that starts an external process (by module, alias or imported name), or None."""
    modules = {module: module for module in PROCESS_CALLS} if modules is None else modules
    names = names or {}
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in modules:
        module = modules[func.value.id]
        if _is_process_name(module, func.attr):
            return f"{module}.{func.attr}"
    if isinstance(func, ast.Name) and func.id in names:
        return names[func.id]
    return None


def _process_findings(tree, filename, allowed, rule):
    """(line, message) of each process call or hiding import outside the functions in `allowed`."""
    allowed = set(allowed)
    modules, names = _process_names(tree)
    findings = []

    def visit(node, function):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function = node.name
        found = None
        if isinstance(node, ast.Call):
            found = _process_call(node, modules, names)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            found = _process_import(node)
        if found and function not in allowed:
            where = f"{function}()" if function else "nível de módulo"
            findings.append((node.lineno, f"{filename}:{node.lineno} — {rule} — {found} em {where}"))
        for child in ast.iter_child_nodes(node):
            visit(child, function)

    visit(tree, None)
    return findings


def subprocess_findings(source, filename, allowed=("run_collector",)):
    """Chamadas de processo externo fora das funções permitidas (padrão: só run_collector), inclusive por import
    de nome ou com alias (from subprocess import run, import subprocess as sp, from os import system) — SPEC-0046."""
    findings = _process_findings(ast.parse(source), filename, allowed, RULE_PROCESS)
    return [message for _, message in sorted(findings)]


def collector_process_findings(source, filename, allowed=()):
    """Regra dos coletores de assets/collectors/ (SPEC-0046:UT-04): processo externo só nas funções `allowed` (a que
    chama o executável do provedor: run_gh, run_cli), com lista de argumentos e sem shell; os.system, os.popen,
    os.exec* e os.spawn* proibidos em qualquer lugar. Coletor sem função permitida não roda processo."""
    tree = ast.parse(source)
    rule = f"{RULE_COLLECTOR_PROCESS} {', '.join(allowed)}" if allowed else RULE_COLLECTOR_NO_PROCESS
    findings = set(_process_findings(tree, filename, allowed, rule))
    modules, names = _process_names(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call = _process_call(node, modules, names)
        if not call:
            continue
        where = f"{filename}:{node.lineno}"
        if not call.startswith("subprocess."):
            findings.add((node.lineno, f"{where} — {RULE_COLLECTOR_PROCESS_ARGS} — {call} proibido em coletor"))
            continue
        argv = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "args"), None)
        if not isinstance(argv, (ast.List, ast.Tuple)):
            findings.add((node.lineno, f"{where} — {RULE_COLLECTOR_PROCESS_ARGS} — {call} sem lista de argumentos"))
    for message in shell_findings(source, filename):
        findings.add((int(message.split(" — ", 1)[0].rsplit(":", 1)[1]), message))
    return [message for _, message in sorted(findings)]


def shell_findings(source, filename):
    """Argumento shell= diferente de False em qualquer chamada (ADR-0010: coletores rodam sem shell)."""
    findings = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.keyword) and node.arg == "shell"
                and not (isinstance(node.value, ast.Constant) and node.value.value is False)):
            line = node.value.lineno
            findings.append((line, f"{filename}:{line} — {RULE_SHELL} — shell="))
    return [message for _, message in sorted(findings)]


def personal_path_findings(text, filename):
    """Caminhos absolutos de usuário (/Users/<nome>, C:\\Users\\<nome>, /home/<nome>) em qualquer arquivo de texto."""
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        for match in PERSONAL_PATH.finditer(line):
            findings.append(f"{filename}:{number} — {RULE_PERSONAL_PATH} — '{match.group(0)}'")
    return findings
