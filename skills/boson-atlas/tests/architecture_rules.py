"""Checadores das regras do ADR-0010, usados por test_architecture.py (SPEC-0032:UT-05).

Escritos aqui, sem importar de outra skill (ADR-0010 proíbe import entre skills).
Cada checador recebe o código-fonte (ou o texto do arquivo) e devolve uma linha por violação:
"<arquivo>:<linha> — <regra> — <o que foi encontrado>".
As regras são por nome: acesso dinâmico (__import__, importlib, getattr) não é pego.
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
            hidden = [f"from {node.module} import {a.name}" for a in node.names
                      if _is_process_name(node.module, a.name)]
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
        if any(k.arg is None for k in node.keywords):  # **opts can hide shell=True
            message = f"{where} — {RULE_COLLECTOR_PROCESS_ARGS} — {call} com **kwargs desempacotados"
            findings.add((node.lineno, message))
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


# ---------------------------------------------------------------- probes (SPEC-0096, ADR-0025)

RULE_PROBE_RESOURCE = "recurso da entrada de probe só pela resolução do recurso"
RULE_PROBE_LOG = "probes.log só com as chaves de PROBE_LOG_KEYS"


def _functions(tree):
    """{nome: nó} de cada função do arquivo (inclusive aninhadas; o último nome vence)."""
    return {node.name: node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _called_names(function):
    """Nomes chamados diretamente (f(...)) dentro da função."""
    return {node.func.id for node in ast.walk(function)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}


def _reaching(functions, target):
    """Funções do arquivo que chamam `target`, direta ou indiretamente (pelos nomes; sem escopo)."""
    reach = {target}
    changed = True
    while changed:
        changed = False
        for name, node in functions.items():
            if name not in reach and _called_names(node) & reach:
                reach.add(name)
                changed = True
    return reach


def _const(node, value):
    return isinstance(node, ast.Constant) and node.value == value


def _is_target_expr(node):
    """`target` ou `<algo>["target"]`: o alvo da entrada de uma probe."""
    if isinstance(node, ast.Name):
        return node.id == "target"
    return isinstance(node, ast.Subscript) and _const(node.slice, "target")


def _resource_writes(node):
    """True quando o nó põe a chave "resource" no alvo de uma probe: dict literal com "resource" e "service",
    target["resource"] = ..., ou dict(..., resource=...) / target.update(resource=...)."""
    if isinstance(node, ast.Dict):
        keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
        return "resource" in keys and "service" in keys
    if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return any(isinstance(t, ast.Subscript) and _const(t.slice, "resource") and _is_target_expr(t.value)
                   for t in targets)
    if isinstance(node, ast.Call) and any(k.arg == "resource" for k in node.keywords):
        func = node.func
        return ((isinstance(func, ast.Name) and func.id == "dict")
                or (isinstance(func, ast.Attribute) and func.attr == "update" and _is_target_expr(func.value)))
    return False


def probe_resource_findings(source, filename, resolver="linked_resources"):
    """ADR-0025 (SPEC-0096, G3): a entrada de uma probe só ganha "resource" numa função que chega à função de
    resolução do recurso (`resolver`, direta ou indiretamente); sem a função, uma violação. Regra por nome, como as
    demais: um dict montado por ** ou por acesso dinâmico não é pego."""
    tree = ast.parse(source)
    functions = _functions(tree)
    if resolver not in functions:
        return [f"{filename}:1 — {RULE_PROBE_RESOURCE} — a função {resolver} não existe"]
    reach = _reaching(functions, resolver)
    findings = []

    def visit(node, function):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function = node.name
        if _resource_writes(node) and function not in reach:
            where = f"{function}()" if function else "nível de módulo"
            findings.append((node.lineno, (f"{filename}:{node.lineno} — {RULE_PROBE_RESOURCE} — \"resource\" no alvo "
                                          f"em {where}, que não passa por {resolver}")))
        for child in ast.iter_child_nodes(node):
            visit(child, function)

    visit(tree, None)
    return [message for _, message in sorted(findings)]


def _string_items(node):
    """Textos de uma coleção literal (tupla, lista, conjunto), também dentro de tuple()/frozenset()/soma; None
    quando o nó não é uma coleção de textos."""
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        items = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        return items if len(items) == len(node.elts) else None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("tuple", "frozenset",
                                                                                         "list") and node.args:
        return _string_items(node.args[0])
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _string_items(node.left), _string_items(node.right)
        return None if left is None or right is None else left + right
    return None


def probe_log_findings(source, filename, function="write_probe_log", constant="PROBE_LOG_KEYS"):
    """SPEC-0096 (G3): as chaves do probes.log ficam numa constante única do módulo (`constant`, coleção literal de
    textos) e `function` monta a linha só a partir dela: usa o nome da constante e não escreve chave fixa (dict
    literal com chave de texto, linha["x"] = ..., dict(x=...))."""
    tree = ast.parse(source)
    findings = []
    keys = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == constant for t in node.targets):
            keys = _string_items(node.value)
    if not keys:
        findings.append((1, (f"{filename}:1 — {RULE_PROBE_LOG} — {constant} não é uma constante do módulo com os "
                            "nomes das chaves")))
    writer = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == function), None)
    if writer is None:
        findings.append((1, f"{filename}:1 — {RULE_PROBE_LOG} — a função {function} não existe"))
        return [message for _, message in sorted(findings)]
    if not any(isinstance(n, ast.Name) and n.id == constant for n in ast.walk(writer)):
        findings.append((writer.lineno, (f"{filename}:{writer.lineno} — {RULE_PROBE_LOG} — {function}() não usa "
                                        f"{constant}")))
    for node in ast.walk(writer):
        fixed = False
        if isinstance(node, ast.Dict):
            fixed = any(isinstance(k, ast.Constant) and isinstance(k.value, str) for k in node.keys)
        elif isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            fixed = any(isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                        and isinstance(t.slice.value, str) for t in targets)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict":
            fixed = any(k.arg for k in node.keywords)
        if fixed:
            findings.append((node.lineno, (f"{filename}:{node.lineno} — {RULE_PROBE_LOG} — chave fixa em "
                                          f"{function}(), fora de {constant}")))
    return [message for _, message in sorted(findings)]


# ---------------------------------------------------------------- probes.log: o conjunto fechado (SPEC-0104)

RULE_PROBE_LOG_SET = "probes.log só com o conjunto fechado de chaves do contrato"
# as de hoje (SPEC-0088), resource e commit (SPEC-0096), reason e access (SPEC-0104)
PROBE_LOG_CONTRACT_KEYS = frozenset({"at", "atlas", "service", "environment", "capability", "verb", "adapter",
                                     "status", "exit", "confirmed_production", "resource", "commit", "reason",
                                     "access"})


def probe_log_key_set_findings(source, filename, expected=PROBE_LOG_CONTRACT_KEYS, constant="PROBE_LOG_KEYS"):
    """SPEC-0104 (UT-06): a constante `constant` do módulo tem exatamente o conjunto `expected`; uma chave a mais
    (por exemplo um valor de acesso ou um resultado) ou a menos é violação, citando a chave."""
    tree = ast.parse(source)
    keys = None
    line = 1
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == constant for t in node.targets):
            keys, line = _string_items(node.value), node.lineno
    if keys is None:
        return [(f"{filename}:1 — {RULE_PROBE_LOG_SET} — {constant} não é uma constante do módulo com os nomes das "
                 "chaves")]
    findings = [f"{filename}:{line} — {RULE_PROBE_LOG_SET} — chave a mais em {constant}: {key}"
                for key in sorted(set(keys) - set(expected))]
    findings += [f"{filename}:{line} — {RULE_PROBE_LOG_SET} — falta em {constant}: {key}"
                 for key in sorted(set(expected) - set(keys))]
    return findings
