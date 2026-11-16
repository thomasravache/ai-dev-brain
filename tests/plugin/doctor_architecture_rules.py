"""Checadores das regras do ADR-0019 para scripts/fermion_doctor.py (SPEC-0061:UT-06).

Usados por test_fermion_doctor.py (carregados por caminho). Cada checador recebe o código-fonte e devolve uma linha
por violação: "<arquivo>:<linha> — <regra> — <achado>", em ordem de linha.

Regras (o doctor só lê e avisa, nunca atualiza sozinho):
- só biblioteca padrão;
- nenhum processo: sem subprocess, os.system, os.popen, os.exec*, os.spawn*, os.fork, pty, multiprocessing nem
  asyncio.create_subprocess_*;
- nenhuma rede: sem socket, ssl, urllib, http, ftplib, smtplib, poplib, imaplib, telnetlib, xmlrpc nem asyncio de
  conexão (open_connection, create_connection);
- nenhuma escrita: open/io.open/Path.open com modo de escrita (w, a, x ou +) ou modo que não é texto literal,
  os.open, write_text, write_bytes, unlink, rmtree, rename, mkdir, makedirs, rmdir, removedirs, touch, symlink_to,
  hardlink_to, chmod, lchmod, chown, truncate, utime; os.remove, os.replace, os.link, os.symlink e shutil.copy*,
  shutil.move (também importados com from);
- nenhum carregamento de código (importlib, runpy, __import__, exec, eval, compile): as versões são lidas por
  expressão regular, nunca importando os scripts das skills.
"""
import ast
import importlib.util
import sys
import sysconfig
from pathlib import Path

RULE_STDLIB = "só biblioteca padrão"
RULE_PROCESS = "nenhum processo"
RULE_NETWORK = "nenhuma rede"
RULE_WRITE = "nenhuma escrita em arquivo"
RULE_CODE = "nenhum carregamento de código"

PROCESS_MODULES = ("subprocess", "pty", "multiprocessing", "concurrent.futures.process")
PROCESS_CALLS = {
    "os": {"system", "popen", "execv", "execve", "execvp", "execvpe", "execl", "execle", "execlp", "execlpe",
           "spawnv", "spawnve", "spawnvp", "spawnvpe", "spawnl", "spawnle", "posix_spawn", "posix_spawnp",
           "fork", "forkpty"},
    "asyncio": {"create_subprocess_exec", "create_subprocess_shell"},
}
NETWORK_MODULES = ("socket", "ssl", "urllib", "http", "ftplib", "smtplib", "poplib", "imaplib", "telnetlib",
                   "xmlrpc", "socketserver", "webbrowser")
NETWORK_CALLS = {"asyncio": {"open_connection", "create_connection", "start_server"}}
# métodos que só existem para gravar (Path, os, shutil, arquivo aberto); nomes ambíguos (replace, remove, copy,
# write) só contam com o módulo na frente
WRITE_METHODS = {"write_text", "write_bytes", "unlink", "rmtree", "rename", "mkdir", "makedirs", "rmdir",
                 "removedirs", "touch", "symlink_to", "hardlink_to", "link_to", "chmod", "lchmod", "chown",
                 "lchown", "truncate", "utime", "mkfifo", "mknod"}
WRITE_CALLS = {
    "os": {"remove", "replace", "link", "symlink", "open", "renames", "fdopen"},
    "shutil": {"copy", "copy2", "copyfile", "copytree", "copymode", "copystat", "move", "rmtree", "chown",
               "make_archive", "unpack_archive"},
}
OPEN_FUNCTIONS = {"open", "io.open", "codecs.open"}
DYNAMIC_MODULES = ("importlib", "runpy", "imp", "zipimport")
DYNAMIC_BUILTINS = {"__import__", "exec", "eval", "compile"}


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


def _under(module, names):
    return any(module == name or module.startswith(name + ".") for name in names)


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


def _imported(tree):
    """[(linha, módulo, nome importado ou None)] de cada import do código."""
    items = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            items += [(node.lineno, alias.name, None, 0) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            items += [(node.lineno, node.module or "", alias.name, node.level) for alias in node.names]
    return items


def _aliases(tree):
    """Nome local -> módulo real (import os as o) e nome local -> 'módulo.função' (from os import remove)."""
    modules, functions = {}, {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else \
                    alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                functions[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return modules, functions


def _call_name(node, modules, functions):
    """Nome qualificado da função chamada, resolvendo alias de módulo e função importada com from."""
    name = _dotted(node.func)
    if name is None:
        return None
    if name in functions:
        return functions[name]
    head, _, rest = name.partition(".")
    if head in modules and rest:
        return f"{modules[head]}.{rest}"
    return name


def _finding(findings, line, filename, rule, detail):
    findings.append((line, f"{filename}:{line} — {rule} — {detail}"))


def _sorted(findings):
    return [message for _, message in sorted(findings)]


def import_findings(source, filename):
    """Import fora da biblioteca padrão, ou relativo."""
    findings = []
    for line, module, _, level in _imported(ast.parse(source)):
        if level:
            _finding(findings, line, filename, RULE_STDLIB, f"import relativo '{'.' * level}{module}'")
        elif module and not is_stdlib(module.split(".")[0]):
            _finding(findings, line, filename, RULE_STDLIB, f"import de '{module.split('.')[0]}'")
    return _sorted(findings)


def process_findings(source, filename):
    """Import de módulo de processo e chamada que abre processo (também por alias ou from)."""
    tree = ast.parse(source)
    modules, functions = _aliases(tree)
    findings = []
    for line, module, name, _ in _imported(tree):
        full = f"{module}.{name}" if name else module
        if _under(module, PROCESS_MODULES) or _under(full, PROCESS_MODULES):
            _finding(findings, line, filename, RULE_PROCESS, f"import de '{full}'")
        elif name and name in PROCESS_CALLS.get(module, ()):
            _finding(findings, line, filename, RULE_PROCESS, f"from {module} import {name}")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node, modules, functions)
            module, _, func = (name or "").rpartition(".")
            if func in PROCESS_CALLS.get(module, ()) or (name and _under(module, PROCESS_MODULES)):
                _finding(findings, node.lineno, filename, RULE_PROCESS, f"{name}()")
    return _sorted(findings)


def network_findings(source, filename):
    """Import de módulo de rede e chamada de conexão do asyncio."""
    tree = ast.parse(source)
    modules, functions = _aliases(tree)
    findings = []
    for line, module, name, _ in _imported(tree):
        full = f"{module}.{name}" if name else module
        if _under(module, NETWORK_MODULES) or _under(full, NETWORK_MODULES):
            _finding(findings, line, filename, RULE_NETWORK, f"import de '{full}'")
        elif name and name in NETWORK_CALLS.get(module, ()):
            _finding(findings, line, filename, RULE_NETWORK, f"from {module} import {name}")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node, modules, functions) or ""
            module, _, func = name.rpartition(".")
            if func in NETWORK_CALLS.get(module, ()):
                _finding(findings, node.lineno, filename, RULE_NETWORK, f"{name}()")
    return _sorted(findings)


def _open_mode(node, positional):
    """O argumento de modo de uma chamada de open (posição `positional` ou mode=); None quando ausente."""
    for keyword in node.keywords:
        if keyword.arg == "mode":
            return keyword.value
        if keyword.arg is None:  # **kwargs pode trazer mode=
            return keyword.value
    return node.args[positional] if len(node.args) > positional else None


def _writes(mode):
    if mode is None:
        return False
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return any(flag in mode.value for flag in "wax+")
    return True  # modo calculado: não dá para provar que é leitura


def write_findings(source, filename):
    """open com modo de escrita (ou calculado), Path.open idem, e as chamadas que gravam, apagam ou movem."""
    tree = ast.parse(source)
    modules, functions = _aliases(tree)
    findings = []
    for line, module, name, _ in _imported(tree):
        if name and name in WRITE_CALLS.get(module, ()):
            _finding(findings, line, filename, RULE_WRITE, f"from {module} import {name}")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node, modules, functions) or ""
        module, _, func = name.rpartition(".")
        is_attribute = isinstance(node.func, ast.Attribute)
        if name in OPEN_FUNCTIONS:
            if _writes(_open_mode(node, 1)):
                _finding(findings, node.lineno, filename, RULE_WRITE, f"{name}() com modo de escrita")
        elif func in WRITE_CALLS.get(module, ()):
            _finding(findings, node.lineno, filename, RULE_WRITE, f"{name}()")
        elif is_attribute and node.func.attr == "open":  # Path.open(mode)
            if _writes(_open_mode(node, 0)):
                _finding(findings, node.lineno, filename, RULE_WRITE, ".open() com modo de escrita")
        elif is_attribute and node.func.attr in WRITE_METHODS:
            _finding(findings, node.lineno, filename, RULE_WRITE, f".{node.func.attr}()")
    return _sorted(findings)


def dynamic_code_findings(source, filename):
    """importlib, runpy, imp, zipimport, __import__, exec, eval e compile."""
    tree = ast.parse(source)
    modules, functions = _aliases(tree)
    findings = []
    for line, module, name, _ in _imported(tree):
        if _under(module, DYNAMIC_MODULES):
            _finding(findings, line, filename, RULE_CODE, f"import de '{module}'")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node, modules, functions) or ""
            if name in DYNAMIC_BUILTINS:
                _finding(findings, node.lineno, filename, RULE_CODE, f"{name}()")
    return _sorted(findings)


def all_findings(source, filename):
    return (import_findings(source, filename) + process_findings(source, filename)
            + network_findings(source, filename) + write_findings(source, filename)
            + dynamic_code_findings(source, filename))
