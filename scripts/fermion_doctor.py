#!/usr/bin/env python3
"""Doctor de instalação antiga do plugin fermion (SPEC-0061, ADR-0019).

    python3 scripts/fermion_doctor.py [--project PASTA] [--json]

Confere se há instalação antiga ao lado do plugin e diz como atualizar; nunca atualiza sozinho. Checagens:
- old-name-copy: cópia de skill com o nome antigo na pasta de skills do usuário ou do projeto;
- stale-copy: cópia de skill com o nome novo mais velha que o plugin;
- stale-sdd-tool: tools/sdd/ do projeto mais velho que a gluon-spec do plugin;
- old-sdd-block: bloco sdd:start que ainda manda carregar a skill pelo nome antigo;
- stale-atlas: atlas vendorizado (.boson-atlas/skill/ ou .org-atlas/skill/) mais velho que a boson-atlas do plugin;
- old-atlas-folder: pasta .org-atlas/ no projeto (cópia da boson-atlas no nome antigo), com o passo de migração do
  vendor (SPEC-0072);
- old-config: configuração da máquina na pasta antiga ($HOME/.config/second-brain ou $HOME/.config/org-atlas): só a
  antiga existe -> o comando de cópia para a nova; as duas existem -> a antiga é ignorada e pode ser apagada. Sem
  achado quando BRAIN_CONFIG_HOME/ATLAS_CONFIG_HOME está definido, como nas skills, que também não usam
  XDG_CONFIG_HOME (SPEC-0072);
- broken-leak-hook: pre-push do leak-check instalado pelo SDD (modo privado) cujo caminho gravado não existe e sem
  nenhuma alternativa da busca do hook (plugin fermion do installed_plugins.json, cópias de skill do usuário,
  tools/sdd/ não rastreado) — todo push seria recusado (SPEC-0068). O hook é lido de <projeto>/.git (pasta, ou
  arquivo `gitdir:` de worktree seguindo `commondir`); "não rastreado" é conferido nas entradas do índice do git v2/v3,
  sem rodar git (índice ausente, v4, ilegível ou grande demais: tools/sdd/ não conta como alternativa).
Cópia com versão ilegível vira unreadable-version.

Pasta de skills do usuário: $CLAUDE_CONFIG_DIR/skills, senão $HOME/.claude/skills; do projeto:
<projeto>/.claude/skills; projeto: --project, senão o cwd. Versões lidas por expressão regular (os scripts das skills
nunca são importados) e comparadas como tupla de inteiros (AAAA, MM, N).

Só leitura: nunca grava, apaga nem move arquivo, nunca abre processo, nunca usa rede, não lê arquivo por link
simbólico para fora da pasta conferida (old-config só confere a existência do config.yml, mesmo por link, como as
skills: Emenda v4) e mostra caminho e versão, nunca conteúdo de arquivo. Sempre sai com 0. Só stdlib, 3.9+.
"""
import json
import os
import re
import shlex
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

# nome novo -> (script, constante de versão)
SKILL_SCRIPTS = {
    "gluon-spec": ("spec_graph.py", "SDD_TOOL_VERSION"),
    "photon-brain": ("brain.py", "BRAIN_VERSION"),
    "boson-atlas": ("atlas.py", "ATLAS_VERSION"),
}
# nome antigo -> nome novo (SPEC-0055)
OLD_TO_NEW = {"sdd-management": "gluon-spec", "second-brain": "photon-brain", "org-atlas": "boson-atlas"}
AGENT_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")
BLOCK_START = "<!-- sdd:start -->"
BLOCK_END = "<!-- sdd:end -->"
CHECKS = ("old-name-copy", "stale-copy", "stale-sdd-tool", "old-sdd-block", "stale-atlas", "broken-leak-hook",
          "old-config", "old-atlas-folder")
UNREADABLE = "unreadable-version"
VERSION_TEXT_RE = re.compile(r"^\d+(?:\.\d+)*$")
READ_LIMIT = 256 * 1024  # só os primeiros 256 KB de cada arquivo (Emenda v2)
USAGE = "uso: fermion_doctor.py [--project PASTA] [--json]"
LEAK_HOOK_SIGNATURE = "# SDD modo privado: recusa o push"  # 2ª linha do hook do leak-check (SPEC-0068)
VENDORED_TOOL = "tools/sdd/spec_graph.py"
# cópias da boson-atlas no atlas: a nova (SPEC-0070) e a antiga, ainda lida pela skill até a SPEC-0073
ATLAS_COPIES = (".boson-atlas/skill", ".org-atlas/skill")
OLD_ATLAS_FOLDER = ".org-atlas"
# pasta de configuração antiga -> (nova, variável que a substitui) (SPEC-0069, SPEC-0070, SPEC-0072)
OLD_CONFIG_DIRS = {"second-brain": ("photon-brain", "BRAIN_CONFIG_HOME"),
                   "org-atlas": ("boson-atlas", "ATLAS_CONFIG_HOME")}


# --------------------------------------------------------------------------- leitura segura

def real(path):
    return Path(os.path.realpath(str(path)))


def inside(path, root):
    """True se o caminho, com os links resolvidos, fica dentro de root (já resolvida)."""
    resolved = real(path)
    return resolved == root or root in resolved.parents


def is_file(path, root):
    try:
        return inside(path, root) and path.is_file()
    except OSError:
        return False


def read_text(path, root):
    """Os primeiros READ_LIMIT bytes do arquivo dentro de root, como texto; None quando não existe, sai de root ou não dá para ler."""
    if not is_file(path, root):
        return None
    try:
        with path.open("rb") as stream:
            return stream.read(READ_LIMIT).decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return None


def read_bytes(path, root):
    """Os primeiros READ_LIMIT bytes do arquivo dentro de root; None quando não existe, sai de root ou não dá para ler."""
    if not is_file(path, root):
        return None
    try:
        with path.open("rb") as stream:
            return stream.read(READ_LIMIT)
    except (OSError, ValueError):
        return None


def read_version(text, constant):
    """Versão da constante (`CONSTANTE = "AAAA.MM.N"`); None quando ausente ou fora do formato."""
    match = re.search(rf'^{constant} = "([^"]+)"', text or "", re.MULTILINE)
    if not match or not VERSION_TEXT_RE.match(match.group(1)):
        return None
    return match.group(1)


def quoted(path):
    """Caminho com aspas de shell, pronto para colar no terminal (Emenda v2)."""
    return shlex.quote(str(path))


def version_tuple(version):
    return tuple(int(part) for part in version.split("."))


def older(version, plugin_version):
    return plugin_version is not None and version_tuple(version) < version_tuple(plugin_version)


def plugin_versions(plugin_root):
    root = real(plugin_root)
    versions = {}
    for skill, (script, constant) in SKILL_SCRIPTS.items():
        text = read_text(Path(plugin_root) / "skills" / skill / "scripts" / script, root)
        versions[skill] = read_version(text, constant)
    return versions


# --------------------------------------------------------------------------- achados

class Report:
    def __init__(self):
        self.findings = []  # (checagem de origem, achado)

    def add(self, origin, check, path, summary, fix):
        """Um achado: `detail` traz o caminho e o resumo; a linha de texto, o resumo e a instrução."""
        self.findings.append((origin, {"check": check, "level": "warn", "path": str(path),
                                       "detail": f"{path}: {summary}", "fix": fix, "_summary": summary}))

    def public(self):
        return [{k: v for k, v in finding.items() if not k.startswith("_")} for _, finding in self.findings]

    def text_lines(self):
        lines = [f"AVISO {f['check']} {f['path']} — {f['_summary']} ({f['fix']})" for _, f in self.findings]
        reported = {origin for origin, _ in self.findings}
        lines += [f"OK {check} — nada a avisar" for check in CHECKS if check not in reported]
        return lines


def skills_folders(project, env):
    config = env.get("CLAUDE_CONFIG_DIR")
    if config:
        user = Path(config) / "skills"
    else:
        user = Path(env.get("HOME") or Path.home()) / ".claude" / "skills"
    return [user, Path(project) / ".claude" / "skills"]


def check_old_names(report, folder):
    root = real(folder)
    for old, new in OLD_TO_NEW.items():
        copy = folder / old
        if is_file(copy / "SKILL.md", root):
            report.add("old-name-copy", "old-name-copy", copy,
                       f"cópia com o nome antigo; o plugin fermion já traz {new}", "remova a pasta")


def check_stale_copies(report, folder, versions, plugin_root):
    root = real(folder)
    for skill, (script, constant) in SKILL_SCRIPTS.items():
        copy = folder / skill
        path = copy / "scripts" / script
        text = read_text(path, root)
        if text is None:
            continue
        version = read_version(text, constant)
        if version is None:
            report.add("stale-copy", UNREADABLE, path, "versão não encontrada",
                       f"copie de novo de {quoted(Path(plugin_root) / 'skills' / skill)} ou remova a pasta")
        elif older(version, versions[skill]):
            report.add("stale-copy", "stale-copy", copy, f"{version} < {versions[skill]}",
                       f"copie de novo de {quoted(Path(plugin_root) / 'skills' / skill)} ou remova a pasta")


def check_sdd_tool(report, project, versions, plugin_root):
    relative = Path("tools") / "sdd" / "spec_graph.py"
    text = read_text(project / relative, real(project))
    if text is None:
        return
    cli = Path(plugin_root) / "skills" / "gluon-spec" / "scripts" / "spec_graph.py"
    fix = f"rode: python3 {quoted(cli)} whats-new, depois vendor"
    version = read_version(text, SKILL_SCRIPTS["gluon-spec"][1])
    if version is None:
        report.add("stale-sdd-tool", UNREADABLE, relative, "versão não encontrada", fix)
    elif older(version, versions["gluon-spec"]):
        report.add("stale-sdd-tool", "stale-sdd-tool", relative, f"{version} < {versions['gluon-spec']}", fix)


def sdd_block(text):
    start = text.find(BLOCK_START)
    if start < 0:
        return None
    end = text.find(BLOCK_END, start)
    return text[start:] if end < 0 else text[start:end]


def check_sdd_blocks(report, project, plugin_root):
    cli = Path(plugin_root) / "skills" / "gluon-spec" / "scripts" / "spec_graph.py"
    root = real(project)
    for name in AGENT_FILES:
        block = sdd_block(read_text(project / name, root) or "")
        if block and "sdd-management" in block and "gluon-spec" not in block:
            report.add("old-sdd-block", "old-sdd-block", name, "bloco SDD com o nome antigo",
                       f"rode: python3 {quoted(cli)} vendor --agents")


def check_atlas(report, project, versions, plugin_root):
    cli = Path(plugin_root) / "skills" / "boson-atlas" / "scripts" / "atlas.py"
    fix = (f"rode no repositório do atlas: python3 {quoted(cli)} vendor --ci <github|generic>, o mesmo --ci da "
           "instalação")
    for copy in ATLAS_COPIES:
        relative = Path(copy)
        text = read_text(project / relative / "scripts" / "atlas.py", real(project))
        if text is None:
            continue
        version = read_version(text, SKILL_SCRIPTS["boson-atlas"][1])
        if version is None:
            report.add("stale-atlas", UNREADABLE, relative / "scripts" / "atlas.py", "versão não encontrada", fix)
        elif older(version, versions["boson-atlas"]):
            report.add("stale-atlas", "stale-atlas", relative, f"{version} < {versions['boson-atlas']}", fix)


def check_old_atlas_folder(report, project, plugin_root):
    """Pasta .org-atlas/ no projeto: a cópia da boson-atlas no nome antigo, com o passo de migração (SPEC-0070)."""
    folder = Path(project) / OLD_ATLAS_FOLDER
    try:
        found = inside(folder, real(project)) and folder.is_dir()
    except OSError:
        found = False
    if not found:
        return
    cli = Path(plugin_root) / "skills" / "boson-atlas" / "scripts" / "atlas.py"
    remove = f"git rm -r {OLD_ATLAS_FOLDER}"
    report.add("old-atlas-folder", "old-atlas-folder", OLD_ATLAS_FOLDER,
               "cópia da boson-atlas no nome antigo",
               f"para migrar, rode no repositório do atlas: python3 {quoted(cli)} vendor --ci <github|generic> "
               f"--force e depois {remove} (se a CI já roda .boson-atlas/skill, só {remove})")


def config_exists(path):
    """True quando o config.yml existe, mesmo por link simbólico (pasta de dotfiles): só a existência é conferida,
    nunca o conteúdo, como nas skills (Emenda v4)."""
    try:
        return path.is_file()
    except OSError:
        return False


def check_old_config(report, env):
    """Configuração da máquina na pasta antiga (SPEC-0069, SPEC-0070): o mesmo critério do doctor de cada skill."""
    config = Path(env.get("HOME") or Path.home()) / ".config"
    for old, (new, override) in OLD_CONFIG_DIRS.items():
        if env.get(override) or not config_exists(config / old / "config.yml"):
            continue
        old_text, new_text = f"~/.config/{old}", f"~/.config/{new}"
        if config_exists(config / new / "config.yml"):
            report.add("old-config", "old-config", config / old, f"{old_text} é ignorada (vale {new_text})",
                       "pode apagar a pasta antiga")
        else:
            report.add("old-config", "old-config", config / old, f"configuração no caminho antigo {old_text}",
                       f"copie com: mkdir -p {new_text} && cp -p {old_text}/config.yml {new_text}/")


def git_common_dir(project):
    """Pasta comum do git do projeto: <projeto>/.git, ou o `gitdir:` do arquivo .git seguindo `commondir`; sem git."""
    dot_git = Path(project) / ".git"
    try:
        if dot_git.is_dir():
            return dot_git
    except OSError:
        return None
    text = read_text(dot_git, real(project))
    if not text or not text.startswith("gitdir:"):
        return None
    value = text[len("gitdir:"):].strip()
    if not value:
        return None
    git_dir = Path(value.splitlines()[0].strip())
    if not git_dir.is_absolute():
        git_dir = Path(project) / git_dir
    common = read_text(git_dir / "commondir", real(git_dir))
    if common and common.strip():
        target = Path(common.strip().splitlines()[0])
        git_dir = target if target.is_absolute() else git_dir / target
    return Path(os.path.normpath(str(git_dir)))


def recorded_tool(text):
    """Caminho gravado: `recorded="..."` (template atual) ou o 2º trecho entre aspas da linha do leak-check."""
    match = re.search(r'^recorded="([^"]*)"', text, re.MULTILINE)
    if match:
        return match.group(1)
    for line in text.splitlines():
        if "leak-check" in line and not line.lstrip().startswith("#"):
            parts = re.findall(r'"([^"]*)"', line)
            if len(parts) >= 2:
                return parts[1]
    return None


def exists(path):
    try:
        return Path(path).is_file()
    except (OSError, ValueError):
        return False


def leak_tool_alternatives(project, env, git_dir):
    """As alternativas da busca do hook, na mesma ordem: plugin fermion, cópias do usuário, tools/sdd/ não rastreado."""
    config = Path(env.get("CLAUDE_CONFIG_DIR") or Path(env.get("HOME") or Path.home()) / ".claude")
    registry = config / "plugins" / "installed_plugins.json"
    try:
        plugins = json.loads(read_text(registry, real(registry.parent)) or "{}").get("plugins")
    except (ValueError, AttributeError):
        plugins = None
    for key, value in (plugins.items() if isinstance(plugins, dict) else []):
        if str(key).startswith("fermion@"):
            for entry in value if isinstance(value, list) else [value]:
                if isinstance(entry, dict) and isinstance(entry.get("installPath"), str):
                    yield Path(entry["installPath"]) / "skills" / "gluon-spec" / "scripts" / "spec_graph.py"
    for skill in ("gluon-spec", "sdd-management"):
        yield config / "skills" / skill / "scripts" / "spec_graph.py"
    vendored = Path(project) / VENDORED_TOOL
    if exists(vendored):
        tracked = index_paths(read_bytes(git_dir / "index", real(git_dir)))
        if tracked is not None and VENDORED_TOOL.encode("utf-8") not in tracked:
            yield vendored


def index_paths(data):
    """Caminhos das entradas de um índice do git v2/v3 (Emenda v3); None quando não dá para ter certeza: índice
    ausente, ilegível, v4 (caminhos comprimidos), truncado ou no limite de leitura (grande demais)."""
    if data is None or len(data) >= READ_LIMIT or len(data) < 12 or data[:4] != b"DIRC":
        return None
    version = int.from_bytes(data[4:8], "big")
    count = int.from_bytes(data[8:12], "big")
    if version not in (2, 3):
        return None
    paths, offset = set(), 12
    for _ in range(count):
        fixed = 62
        if offset + fixed > len(data):
            return None
        flags = int.from_bytes(data[offset + 60:offset + 62], "big")
        if flags & 0x4000:  # flags estendidas (só v3)
            if version < 3:
                return None
            fixed += 2
        start = offset + fixed
        end = data.find(b"\x00", start)
        if end < 0:
            return None
        paths.add(data[start:end])
        offset += (fixed + (end - start) + 8) & ~7  # entrada com 1 a 8 NULs até múltiplo de 8
        if offset > len(data):
            return None
    return paths


def check_leak_hook(report, project, env, plugin_root):
    git_dir = git_common_dir(project)
    if git_dir is None:
        return
    hook = git_dir / "hooks" / "pre-push"
    text = read_text(hook, real(hook.parent))
    lines = (text or "").splitlines()
    if len(lines) < 2 or not lines[1].startswith(LEAK_HOOK_SIGNATURE):
        return
    recorded = recorded_tool(text)
    if recorded and exists(recorded):
        return
    if any(exists(candidate) for candidate in leak_tool_alternatives(project, env, git_dir)):
        return
    cli = Path(plugin_root) / "skills" / "gluon-spec" / "scripts" / "spec_graph.py"
    report.add("broken-leak-hook", "broken-leak-hook", hook,
               f"o hook do leak-check aponta para {recorded or 'um caminho ilegível'}, que não existe, e não acha "
               "outra ferramenta: todo push será recusado",
               f"rode: python3 {quoted(cli)} --root {quoted(project)} private hooks --refresh")


def diagnose(project, env, plugin_root=PLUGIN_ROOT):
    versions = plugin_versions(plugin_root)
    report = Report()
    folders = skills_folders(project, env)
    for folder in folders:
        check_old_names(report, folder)
    for folder in folders:
        check_stale_copies(report, folder, versions, plugin_root)
    check_sdd_tool(report, project, versions, plugin_root)
    check_sdd_blocks(report, project, plugin_root)
    check_atlas(report, project, versions, plugin_root)
    check_leak_hook(report, project, env, plugin_root)
    check_old_config(report, env)
    check_old_atlas_folder(report, project, plugin_root)
    return versions, report


# --------------------------------------------------------------------------- linha de comando

def parse_args(argv):
    """(projeto, json); None quando os argumentos não servem."""
    project, as_json, args = None, False, list(argv)
    while args:
        arg = args.pop(0)
        if arg == "--json":
            as_json = True
        elif arg == "--project" and args:
            project = args.pop(0)
        elif arg.startswith("--project="):
            project = arg.split("=", 1)[1]
        else:
            return None
    return project, as_json


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    parsed = parse_args(sys.argv[1:] if argv is None else argv)
    if parsed is None:
        print(USAGE, file=sys.stderr)
        return 0
    project, as_json = parsed
    try:
        project = Path(project) if project else Path.cwd()
        versions, report = diagnose(project, os.environ)
    except Exception as error:  # noqa: BLE001 — o doctor sempre sai com 0
        print(f"fermion_doctor: não foi possível conferir ({type(error).__name__})", file=sys.stderr)
        return 0
    if as_json:
        print(json.dumps({"plugin_versions": versions, "findings": report.public()}, ensure_ascii=False, indent=2))
    else:
        print("\n".join(report.text_lines()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
