"""Checadores das regras do ADR-0007 (e da regra de rede do ADR-0008), usados por test_architecture.py.

Escritos aqui, sem importar da sdd-management (ADR-0007 proíbe import entre skills).
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
RULE_NETWORK = "sem chamada de rede"
RULE_PROCESS = "processos externos só em run_processor"
RULE_PERSONAL_PATH = "nenhum caminho pessoal absoluto"

FORBIDDEN_MODULES = ("spec_graph", "sdd_management", "tools", "architecture_rules")
NETWORK_MODULES = ("socket", "ssl", "http", "urllib.request", "ftplib", "smtplib", "poplib", "imaplib",
                   "telnetlib", "xmlrpc", "socketserver", "asyncio")
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
    """Imports fora da biblioteca padrão, de módulo local (arquivo único), de outra skill/tools ou de rede."""
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
        elif _matches(module, NETWORK_MODULES):
            findings.append((line, f"{where} — {RULE_NETWORK} — import de '{module}'"))
    return [message for _, message in sorted(findings)]


def cross_skill_path_findings(source, filename):
    """Textos que apontam para a outra skill ou para tools/ (ex.: sys.path com sdd-management)."""
    findings = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and ("sdd-management" in node.value or re.search(r"(^|/)tools/", node.value))):
            findings.append((node.lineno, f"{filename}:{node.lineno} — {RULE_CROSS_SKILL} — '{node.value}'"))
    return [message for _, message in sorted(findings)]


def _process_call(node):
    func = node.func
    if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
            and func.attr in PROCESS_CALLS.get(func.value.id, ())):
        return f"{func.value.id}.{func.attr}"
    return None


def subprocess_findings(source, filename, allowed=("run_processor",)):
    """Chamadas de processo externo fora das funções permitidas (padrão: só run_processor)."""
    allowed = set(allowed)
    findings = []

    def visit(node, function):
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


def personal_path_findings(text, filename):
    """Caminhos absolutos de usuário (/Users/<nome>, C:\\Users\\<nome>, /home/<nome>) em qualquer arquivo de texto."""
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        for match in PERSONAL_PATH.finditer(line):
            findings.append(f"{filename}:{number} — {RULE_PERSONAL_PATH} — '{match.group(0)}'")
    return findings
