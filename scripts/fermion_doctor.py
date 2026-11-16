#!/usr/bin/env python3
"""Doctor de instalação antiga do plugin fermion (SPEC-0061, ADR-0019).

    python3 scripts/fermion_doctor.py [--project PASTA] [--json]

Confere se há instalação antiga ao lado do plugin e diz como atualizar; nunca atualiza sozinho. Checagens:
- old-name-copy: cópia de skill com o nome antigo na pasta de skills do usuário ou do projeto;
- stale-copy: cópia de skill com o nome novo mais velha que o plugin;
- stale-sdd-tool: tools/sdd/ do projeto mais velho que a gluon-spec do plugin;
- old-sdd-block: bloco sdd:start que ainda manda carregar a skill pelo nome antigo;
- stale-atlas: atlas vendorizado (.org-atlas/skill/) mais velho que a boson-atlas do plugin.
Cópia com versão ilegível vira unreadable-version.

Pasta de skills do usuário: $CLAUDE_CONFIG_DIR/skills, senão $HOME/.claude/skills; do projeto:
<projeto>/.claude/skills; projeto: --project, senão o cwd. Versões lidas por expressão regular (os scripts das skills
nunca são importados) e comparadas como tupla de inteiros (AAAA, MM, N).

Só leitura: nunca grava, apaga nem move arquivo, nunca abre processo, nunca usa rede, não segue link simbólico para
fora da pasta conferida e mostra caminho e versão, nunca conteúdo de arquivo. Sempre sai com 0. Só stdlib, 3.9+.
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
CHECKS = ("old-name-copy", "stale-copy", "stale-sdd-tool", "old-sdd-block", "stale-atlas")
UNREADABLE = "unreadable-version"
VERSION_TEXT_RE = re.compile(r"^\d+(?:\.\d+)*$")
READ_LIMIT = 256 * 1024  # só os primeiros 256 KB de cada arquivo (Emenda v2)
USAGE = "uso: fermion_doctor.py [--project PASTA] [--json]"


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
    relative = Path(".org-atlas") / "skill"
    text = read_text(project / relative / "scripts" / "atlas.py", real(project))
    if text is None:
        return
    cli = Path(plugin_root) / "skills" / "boson-atlas" / "scripts" / "atlas.py"
    fix = (f"rode no repositório do atlas: python3 {quoted(cli)} vendor --ci <github|generic>, o mesmo --ci da "
           "instalação")
    version = read_version(text, SKILL_SCRIPTS["boson-atlas"][1])
    if version is None:
        report.add("stale-atlas", UNREADABLE, relative / "scripts" / "atlas.py", "versão não encontrada", fix)
    elif older(version, versions["boson-atlas"]):
        report.add("stale-atlas", "stale-atlas", relative, f"{version} < {versions['boson-atlas']}", fix)


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
