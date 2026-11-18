"""Hook SessionStart do plugin fermion (SPEC-0058, ADR-0017).

Lê o JSON do hook no stdin (só o "cwd"), roda só comandos de leitura das CLIs do próprio plugin e imprime
`hookSpecificOutput.additionalContext` com até três blocos: o `status` do SDD (quando o projeto tem
docs/specs/sdd-config.yml), a linha do atlas (com vários atlas, o escolhido para o projeto e o motivo, SPEC-0080) e a
linha do segundo cérebro (quando `config --json` sai com 0). Depois
deles, o bloco "Instalação desatualizada" quando o doctor do plugin (scripts/fermion_doctor.py, SPEC-0061, ADR-0019)
tem achado.
Prazo de 10 s por CLI e 20 s no total (Emenda v2). Sempre sai com 0: CLI ou cwd que falha tira só o bloco dela e
vira uma linha de diagnóstico no stderr. Só stdlib, Python 3.9+.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN_ROOT / "skills"
SPEC_GRAPH = SKILLS / "gluon-spec" / "scripts" / "spec_graph.py"
ATLAS = SKILLS / "boson-atlas" / "scripts" / "atlas.py"
BRAIN = SKILLS / "photon-brain" / "scripts" / "brain.py"
DOCTOR = PLUGIN_ROOT / "scripts" / "fermion_doctor.py"

CLI_TIMEOUT = 10
TOTAL_TIMEOUT = 20
NOT_CONFIGURED = 3
SDD_LIMIT = 6000
CONTEXT_LIMIT = 8000
DOCTOR_LIMIT = 1500

SDD_HEADER = "## SDD (gluon-spec)\n"
CUT_NOTICE = "… (cortado; rode `status`)"
ATLAS_LINE = ("Atlas da organização (boson-atlas) configurado nesta máquina: para contexto de sistemas, use a skill "
              "boson-atlas ou a tool MCP atlas_context.")
DOCTOR_HEADER = "## Instalação desatualizada (fermion)\n"
ATLAS_CHOSEN = ("Atlas da organização (boson-atlas) para este projeto: {name} (escolhido por: {reason}). "
                "Outros nesta máquina: {others}. Use a skill boson-atlas ou a tool MCP atlas_context.")
ATLAS_NO_CHOICE = ("Vários atlas nesta máquina ({names}) e nenhum escolhido para este projeto: use --atlas, o "
                   "parâmetro atlas das tools MCP ou declare remotes: no atlas-config.yml.")
# selected_by do `config --json` (SPEC-0079@1 e SPEC-0080) → texto do motivo; desconhecido vira o próprio valor
ATLAS_REASONS = {"option": "--atlas", "env": "ATLAS_NAME", "remote": "remote do projeto", "default": "padrão",
                 "single": "único"}
CHOICE_EXIT = 2
BRAIN_LINE = ("Segundo cérebro (photon-brain) configurado nesta máquina: para notas e decisões do usuário, use a "
              "skill photon-brain.")


def run_cli(argv, cwd, timeout):
    """Único ponto que abre processo: argv em lista, sem shell, ambiente herdado. Não engole exceções."""
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, errors="replace", timeout=timeout,
                          check=False)


class Unavailable(Exception):
    """CLI ausente, timeout, saída ilegível ou exit fora do esperado: o bloco some e vira uma linha no stderr."""


class Deadline:
    """Prazo total a partir da primeira leitura do relógio; cada CLI recebe min(CLI_TIMEOUT, restante)."""

    def __init__(self, clock):
        self.clock = clock
        self.end = clock() + TOTAL_TIMEOUT

    def next_timeout(self):
        remaining = self.end - self.clock()
        if remaining <= 0:
            raise Unavailable(f"sem tempo: prazo total de {TOTAL_TIMEOUT} s esgotado")
        return min(CLI_TIMEOUT, remaining)


def call(runner, deadline, script, args, cwd):
    """Roda uma CLI do plugin com o interpretador atual; Unavailable no lugar de exceção de processo."""
    timeout = deadline.next_timeout()
    argv = [sys.executable, str(script), *args]
    try:
        result = runner(argv, cwd, timeout)
    except subprocess.TimeoutExpired:
        raise Unavailable(f"timeout de {timeout:g} s") from None
    except UnicodeError:
        raise Unavailable("saída que não decodifica") from None
    except OSError as error:
        raise Unavailable(f"não executou: {error.strerror or type(error).__name__}") from None
    if not isinstance(result.stdout, (str, type(None))) or not isinstance(result.stderr, (str, type(None))):
        raise Unavailable("saída que não é texto")
    return result


def read_cwd(stdin):
    """Pasta do "cwd" do JSON do hook; o cwd do processo quando não há stdin, o JSON é inválido ou sem "cwd"."""
    try:
        data = json.loads(stdin.read()) if stdin is not None else None
    except (ValueError, OSError, AttributeError):
        data = None
    cwd = data.get("cwd") if isinstance(data, dict) else None
    if isinstance(cwd, str) and cwd:
        return Path(cwd)
    return Path.cwd()


def project_root(cwd):
    """A primeira pasta, do cwd para cima, que contém .git (arquivo ou pasta); sem .git, o próprio cwd."""
    for folder in (cwd, *cwd.parents):
        if (folder / ".git").exists():
            return folder
    return cwd


def locate(stdin):
    """(projeto, cwd das CLIs). Projeto None quando o cwd não existe; Unavailable quando não dá para ler."""
    try:
        cwd = read_cwd(stdin)
        if not cwd.is_dir():
            return None, None
        project = project_root(cwd.resolve())
        has_config = (project / "docs" / "specs" / "sdd-config.yml").is_file()
    except (OSError, ValueError) as error:
        raise Unavailable(f"cwd ilegível: {type(error).__name__}") from None
    return (project if has_config else None), str(project)


def first_line(text):
    return next((line.strip() for line in (text or "").splitlines() if line.strip()), "")


def sdd_block(runner, deadline, project):
    """Bloco SDD com o stdout do `status`, cortado em SDD_LIMIT contando o cabeçalho."""
    result = call(runner, deadline, SPEC_GRAPH, ["status"], str(project))
    if result.returncode != 0:
        reason = first_line(result.stderr) or f"exit {result.returncode}"
        return SDD_HEADER + f"status falhou: {reason}"
    body = (result.stdout or "").rstrip()
    if len(SDD_HEADER) + len(body) > SDD_LIMIT:
        room = SDD_LIMIT - len(SDD_HEADER) - len(CUT_NOTICE) - 1
        body = body[:room].rstrip() + "\n" + CUT_NOTICE
    return SDD_HEADER + body


def configured_line(runner, deadline, script, line, cwd):
    """A linha fixa quando `config --json` sai com 0; None quando sai com 3 (não configurado)."""
    result = call(runner, deadline, script, ["config", "--json"], cwd)
    if result.returncode == 0:
        return line
    if result.returncode == NOT_CONFIGURED:
        return None
    raise Unavailable(f"config saiu com {result.returncode}")


def atlas_names(data):
    """Nomes de `atlases` (na ordem da CLI, por nome) de um JSON do `config`; [] quando o campo não serve."""
    atlases = data.get("atlases") if isinstance(data, dict) else None
    if not isinstance(atlases, list):
        return []
    names = [item.get("name") for item in atlases if isinstance(item, dict)]
    return [name for name in names if isinstance(name, str) and name]


def parse_json(text):
    try:
        return json.loads(text or "")
    except ValueError:
        return None


def atlas_line(runner, deadline, cwd):
    """Linha do atlas (SPEC-0080): com 1 atlas (ou JSON ilegível), a linha de sempre; com 2+, o nome escolhido e o
    motivo; exit 2 (vários sem escolha), o passo que falta, com os nomes de `config --list --json`. Nunca mostra
    caminho, remote nem credencial: só nomes de atlas."""
    result = call(runner, deadline, ATLAS, ["config", "--json"], cwd)
    if result.returncode == NOT_CONFIGURED:
        return None
    if result.returncode == CHOICE_EXIT:
        listed = call(runner, deadline, ATLAS, ["config", "--list", "--json"], cwd)
        names = atlas_names(parse_json(listed.stdout)) if listed.returncode == 0 else []
        if len(names) < 2:
            raise Unavailable(f"config saiu com {result.returncode}")
        return ATLAS_NO_CHOICE.format(names=", ".join(names))
    if result.returncode != 0:
        raise Unavailable(f"config saiu com {result.returncode}")
    data = parse_json(result.stdout)
    names = atlas_names(data)
    name = data.get("atlas_name") if isinstance(data, dict) else None
    selected_by = data.get("selected_by") if isinstance(data, dict) else None
    if len(names) < 2 or not isinstance(name, str) or not name or not isinstance(selected_by, str):
        return ATLAS_LINE
    others = [other for other in names if other != name]
    reason = ATLAS_REASONS.get(selected_by, selected_by)
    return ATLAS_CHOSEN.format(name=name, reason=reason, others=", ".join(others))


def doctor_lines(stdout):
    """Uma linha "- <detail> → <fix>" por achado do `--json` do doctor; Unavailable quando o JSON não serve."""
    try:
        data = json.loads(stdout or "")
    except ValueError:
        raise Unavailable("saída do doctor não é JSON") from None
    findings = data.get("findings") if isinstance(data, dict) else None
    if not isinstance(findings, list):
        raise Unavailable("saída do doctor sem findings")
    lines = []
    for finding in findings:
        detail = finding.get("detail") if isinstance(finding, dict) else None
        fix = finding.get("fix") if isinstance(finding, dict) else None
        if not isinstance(detail, str) or not isinstance(fix, str):
            raise Unavailable("achado do doctor sem detail ou fix")
        lines.append(f"- {' '.join(detail.split())} → {' '.join(fix.split())}")
    return lines


def doctor_block(runner, deadline, project):
    """Bloco do doctor com até DOCTOR_LIMIT caracteres; o que não cabe vira "… e mais N". None sem achado."""
    if project is None:
        return None
    result = call(runner, deadline, DOCTOR, ["--project", project, "--json"], project)
    if result.returncode != 0:
        raise Unavailable(f"exit {result.returncode}")
    lines = doctor_lines(result.stdout)
    if not lines:
        return None
    block = DOCTOR_HEADER.rstrip("\n")
    for shown, line in enumerate(lines):
        rest = len(lines) - shown - 1
        more = f"\n… e mais {rest}" if rest else ""
        if len(block) + 1 + len(line) + len(more) > DOCTOR_LIMIT:
            return block + f"\n… e mais {len(lines) - shown}"
        block += "\n" + line
    return block


def report(stderr, name, error):
    try:
        print(f"session_start: {name} indisponível ({error})", file=stderr)
    except (OSError, ValueError, AttributeError):
        pass


def main(stdin=None, stdout=None, stderr=None, runner=run_cli, clock=time.monotonic):
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    deadline = Deadline(clock)

    blocks = []
    try:
        project, cli_cwd = locate(stdin)
    except Unavailable as error:
        report(stderr, "SDD", error)
        project = cli_cwd = None
    steps = (("SDD", lambda: sdd_block(runner, deadline, project) if project else None),
             ("Atlas", lambda: atlas_line(runner, deadline, cli_cwd)),
             ("Brain", lambda: configured_line(runner, deadline, BRAIN, BRAIN_LINE, cli_cwd)))
    for name, step in steps:
        try:
            block = step()
        except Unavailable as error:
            report(stderr, name, error)
            continue
        if block:
            blocks.append(block)
    try:
        doctor = doctor_block(runner, deadline, cli_cwd)
    except Unavailable as error:
        report(stderr, "Doctor", error)
        doctor = None

    if blocks or doctor:
        context = "\n\n".join(blocks)
        if doctor:  # o corte dos 8.000 cai nos blocos da SPEC-0058, nunca no aviso
            room = CONTEXT_LIMIT - len(doctor) - (2 if context else 0)
            context = (context[:room] + "\n\n" if context else "") + doctor
        context = context[:CONTEXT_LIMIT]
        output = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}
        try:
            stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
        except (OSError, ValueError, AttributeError) as error:
            report(stderr, "SDD", f"stdout: {type(error).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
