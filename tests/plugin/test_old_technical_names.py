"""Guarda dos nomes técnicos antigos (SPEC-0072:UT-03, ADR-0020; complementa a guarda de pastas da SPEC-0055).

Run: python3 -m unittest discover -s tests/plugin -p test_old_technical_names.py

Depois das SPEC-0069 a 0071 os nomes técnicos novos valem; os antigos só podem aparecer onde a leitura de
compatibilidade ou a migração precisam deles. A busca acusa, em todo arquivo versionado e com "<arquivo>:<linha> —
<regra>: <trecho>":

    (<cérebro> e <atlas> são os nomes antigos da photon-brain e da boson-atlas, montados por partes no código)
    config   pasta de configuração antiga:      .config/<cérebro> e .config/<atlas>
    folder   pasta antiga da cópia no atlas:    .<atlas> (com ou sem "/" depois; também logo depois de "/")
    contract nome antigo do contrato:           <atlas>/collector@<n>
    backup   prefixo antigo de backup:          <cérebro>-<data>, <cérebro>-AAAA, <cérebro>-{...}, <cérebro>-*,
                                                <cérebro>-<...>, <cérebro>- no fim da string (nos scripts, também
                                                a concatenação "<cérebro>-" + carimbo)
    output   nome antigo em texto de saída:     <cérebro> / <atlas> numa string de código dos scripts
             (skills/*/scripts/**/*.py, skills/*/assets/**/*.py, scripts/*.py, hooks/*.py, mcp/*.py, tools/sdd/*.py)
             — comentário e docstring não saem na tela —, e em cada linha de skills/*/assets/**/*.sh
             As strings dos scripts saem da AST (constantes de texto e f-strings, sem as docstrings), do mesmo
             jeito do Python 3.9 ao 3.15 (no 3.12+ o tokenize parte as f-strings em tokens FSTRING_*).

Exceções (estreitas e listadas; cada uma com o motivo):
    E1 docs/specs/ e docs/adr/: histórico das decisões.
    E2 */CHANGELOG.md: histórico das versões (anuncia a troca e a remoção).
    E3 fixtures de compatibilidade nomeados como tal: skills/boson-atlas/tests/fixtures/previous/ (o atlas.py da
       versão anterior), .../fixtures/contract/valid/old-contract-name.json e .../fake-collectors/legacy_contract.py.
    E4 scripts/fermion_doctor.py: procura esses nomes de propósito (checagens old-config, old-atlas-folder).
    E5 constantes de leitura de compatibilidade e avisos de migração dos scripts, por nome:
       photon-brain/scripts/brain.py: OLD_CONFIG_DIR, BACKUP_NAME_RE;
       boson-atlas/scripts/atlas.py: OLD_CONFIG_DIR, OLD_CONTRACT, SKILL_COPIES, OLD_COPY_LEFT_SUGGESTION.
       Nos scripts só strings de código são conferidas: comentários e docstrings ("formerly …" e a descrição da
       reserva de leitura) documentam a compatibilidade e nunca saem na tela.
    E6 notas de compatibilidade nos Markdown (SKILL.md, references/, README.md):
       a) parágrafo que começa com rótulo em negrito sobre o nome antigo ("**Compatibilidade…", "**Nome antigo…",
          "**Backups com o nome antigo…", "**O mesmo coletor … nome antigo…") e o bloco de código logo depois dele;
       b) seção cujo título fala do nome antigo ("compatib" ou "nome antigo"), até o próximo título do mesmo nível
          ou acima (um título que só diz "antigo", como "Dados antigos", não isenta);
       c) linha que cita, junto de cada identificador antigo, o identificador novo correspondente
          (~/.config/photon-brain, ~/.config/boson-atlas, .boson-atlas, boson-atlas/collector@, photon-brain-);
       d) linha de tabela que documenta um aviso de migração: fala do nome/caminho "antig…" e traz, na mesma
          linha, o nome novo correspondente a cada identificador antigo, como a tabela de mensagens do doctor em
          references/config.md.

Este arquivo monta todos os nomes antigos por partes, para não ser acusado pela própria busca. Arquivo de texto que
não é UTF-8 é lido com substituição dos bytes inválidos; só arquivo com byte NUL (binário) e link simbólico não são
lidos.
"""
import ast
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

OLD_BRAIN = "second" + "-brain"
OLD_ATLAS = "org" + "-atlas"
NEW_BRAIN = "photon-brain"
NEW_ATLAS = "boson-atlas"
OLD_NAMES = f"(?:{OLD_BRAIN}|{OLD_ATLAS})"

RULES = {
    "config": re.compile(rf"\.config/{OLD_NAMES}(?![\w-])"),
    "folder": re.compile(rf"(?<![\w.-])\.{OLD_ATLAS}(?![\w-])"),
    "contract": re.compile(rf"(?<![\w.-]){OLD_ATLAS}/collector@"),
    # nos scripts a string é o valor (sem aspas): "fim da string" é o fim do valor, e cobre "<cérebro>-" + carimbo
    "backup": re.compile(rf"(?<![\w.-]){OLD_BRAIN}-(?:\d|AAAA|YYYY|\{{|\*|<|[\"'`]|$)"),
}
OUTPUT_RULE = re.compile(rf"(?<![\w/.-]){OLD_NAMES}(?![\w/-])")
# identificador antigo -> o novo que, na mesma linha, faz dela uma nota de compatibilidade (E6c)
COUNTERPARTS = (
    (re.compile(rf"\.config/{OLD_BRAIN}(?![\w-])"), f".config/{NEW_BRAIN}"),
    (re.compile(rf"\.config/{OLD_ATLAS}(?![\w-])"), f".config/{NEW_ATLAS}"),
    (RULES["folder"], f".{NEW_ATLAS}"),
    (RULES["contract"], f"{NEW_ATLAS}/collector@"),
    (RULES["backup"], f"{NEW_BRAIN}-"),
)

EXEMPT_PREFIXES = ("docs/specs/", "docs/adr/", "skills/boson-atlas/tests/fixtures/previous/")  # E1, E3
EXEMPT_FILES = (
    "skills/boson-atlas/tests/fixtures/contract/valid/old-contract-name.json",  # E3
    "skills/boson-atlas/tests/fixtures/fake-collectors/legacy_contract.py",  # E3
    "scripts/fermion_doctor.py",  # E4
)
COMPAT_CONSTANTS = {  # E5
    "skills/photon-brain/scripts/brain.py": {"OLD_CONFIG_DIR", "BACKUP_NAME_RE"},
    "skills/boson-atlas/scripts/atlas.py": {"OLD_CONFIG_DIR", "OLD_CONTRACT", "SKILL_COPIES",
                                            "OLD_COPY_LEFT_SUGGESTION"},
}
SCRIPT_RE = re.compile(r"^(?:skills/[^/]+/(?:scripts|assets)/.+\.py|scripts/[^/]+\.py|hooks/[^/]+\.py|mcp/[^/]+\.py"
                       r"|tools/sdd/[^/]+\.py)$")
SHELL_RE = re.compile(r"^skills/[^/]+/assets/.+\.sh$")  # output linha a linha
MARKDOWN_RE = re.compile(r"^(?:README\.md|skills/[^/]+/SKILL\.md|skills/[^/]+/references/.+\.md)$")
COMPAT_LABEL_RE = re.compile(r"^\*\*[^*]*(?:compatib|nome antigo|old name)", re.IGNORECASE)
COMPAT_HEADING_RE = re.compile(r"^(#+)\s.*(?:compatib|nome antigo)", re.IGNORECASE)  # E6b
HEADING_RE = re.compile(r"^(#+)\s")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


def exempt_path(rel):
    return (rel.startswith(EXEMPT_PREFIXES) or rel in EXEMPT_FILES
            or rel == "CHANGELOG.md" or rel.endswith("/CHANGELOG.md"))  # E2


def line_hits(line, rules):
    return [(name, m.group(0)) for name, rule in rules.items() for m in rule.finditer(line)]


def has_counterparts(line):
    """E6c: cada identificador antigo da linha vem com o novo correspondente."""
    return all(new in line for old, new in COUNTERPARTS if old.search(line))


def markdown_compat_lines(lines):
    """Números (1-based) das linhas dentro de nota de compatibilidade (E6a e E6b)."""
    exempt, section_level, paragraph, after_paragraph, fence = set(), None, False, False, None
    for number, line in enumerate(lines, start=1):
        if fence:
            exempt.add(number)
            if FENCE_RE.match(line) and line.strip().startswith(fence):
                fence = None
            continue
        heading = HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            if section_level is not None and level <= section_level:
                section_level = None
            compat = COMPAT_HEADING_RE.match(line)
            if compat and section_level is None:
                section_level = level
            paragraph = after_paragraph = False
        elif not line.strip():
            after_paragraph = after_paragraph or paragraph
            paragraph = False
        elif FENCE_RE.match(line) and (paragraph or after_paragraph):
            fence = FENCE_RE.match(line).group(1)
            exempt.add(number)
            paragraph = after_paragraph = False
            continue
        elif COMPAT_LABEL_RE.match(line.strip()):
            paragraph, after_paragraph = True, False
        elif not paragraph:
            after_paragraph = False
        if paragraph or section_level is not None:
            exempt.add(number)
    return exempt


def python_strings(text):
    """(linha inicial, texto, constante) de cada string de código, tirada da AST; docstrings ficam de fora (E5) e
    comentários nem chegam à AST. Constante de texto vira o próprio valor (sem prefixo nem aspas); f-string vira o
    trecho da fonte (ast.get_source_segment), com os campos "{...}". Igual do Python 3.9 ao 3.15.
    `constante` é o nome atribuído no nível do módulo quando a string está nessa atribuição, senão None."""
    tree = ast.parse(text)
    docstrings, owners, inside_fstrings = set(), {}, set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
        elif isinstance(node, ast.JoinedStr):
            inside_fstrings.update(id(child) for child in ast.walk(node) if child is not node)
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                owners[line] = node.targets[0].id
    found = []
    for node in ast.walk(tree):
        if id(node) in docstrings or id(node) in inside_fstrings:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            string = node.value
        elif isinstance(node, ast.JoinedStr):
            string = ast.get_source_segment(text, node) or "".join(
                part.value if isinstance(part, ast.Constant) else "{}" for part in node.values)
        else:
            continue
        found.append((node.lineno, string, owners.get(node.lineno)))
    return sorted(found, key=lambda item: item[0])


def technical_findings(text, rel):
    """Achados "<arquivo>:<linha> — <regra>: <trecho>" de um arquivo (caminho relativo à raiz do repositório)."""
    if exempt_path(rel):
        return []
    findings = []
    if SCRIPT_RE.match(rel):
        allowed = COMPAT_CONSTANTS.get(rel, set())
        try:
            strings = python_strings(text)
        except (SyntaxError, ValueError):
            strings = [(n, line, None) for n, line in enumerate(text.splitlines(), start=1)]
        for number, string, owner in strings:
            if owner in allowed:
                continue
            rules = dict(RULES, output=OUTPUT_RULE)
            for name, match in line_hits(string, rules):
                findings.append(f"{rel}:{number} — {name}: {match}")
        return sorted(set(findings), key=lambda f: (int(f.split(":")[1].split(" ")[0]), f))
    lines = text.splitlines()
    if SHELL_RE.match(rel):
        rules = dict(RULES, output=OUTPUT_RULE)
        return [f"{rel}:{number} — {name}: {match}"
                for number, line in enumerate(lines, start=1) for name, match in line_hits(line, rules)]
    compat = markdown_compat_lines(lines) if MARKDOWN_RE.match(rel) else set()
    for number, line in enumerate(lines, start=1):
        # E6a e E6b; E6c e E6d (a linha de tabela com "antig…" só é isenta quando traz os nomes novos)
        if number in compat or (MARKDOWN_RE.match(rel) and has_counterparts(line)):
            continue
        for name, match in line_hits(line, RULES):
            findings.append(f"{rel}:{number} — {name}: {match}")
    return findings


def find_technical_names(root, rel_paths):
    findings = []
    for rel in rel_paths:
        path = Path(root) / rel
        if not path.is_file() or path.is_symlink():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data:  # binário
            continue
        text = data.decode("utf-8", errors="replace")
        findings.extend(technical_findings(text, rel))
    return findings


def git_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, check=True, capture_output=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


class OldTechnicalNamesTest(unittest.TestCase):
    def test_example_with_each_old_name_is_reported_and_listed_exceptions_are_not(self):
        """SPEC-0072:UT-03 (exemplo que viola a regra e cada exceção listada)"""
        q = '"'
        script = (
            f'"""Tooling for the photon-brain skill, formerly {OLD_BRAIN}."""\n'  # docstring: E5
            f"# reserva: ~/.config/{OLD_BRAIN}\n"  # comentário: E5
            f"OLD_CONFIG_DIR = {q}{OLD_BRAIN}{q}\n"  # constante listada: E5
            f"BACKUP_NAME_RE = r{q}^(?:photon-brain|{OLD_BRAIN})-(\\d{{4}})\\.zip${q}\n"  # constante listada: E5
            f"print({q}{OLD_BRAIN} não configurado{q})\n"  # 5: texto de saída
            f"CONFIG = {q}~/.config/{OLD_BRAIN}{q}\n"  # 6: pasta antiga
            f"NAME = f{q}{OLD_BRAIN}-{{stamp}}.zip{q}\n"  # 7: prefixo de backup
            f"CFG = f{q}~/.config/{OLD_BRAIN}/{{name}}{q}\n"  # 8: f-string com a pasta antiga (FSTRING_* no 3.12+)
            f"print(f{q}{OLD_BRAIN}: erro {{e}}{q})\n"  # 9: f-string de saída
            f"ZIP = {q}{OLD_BRAIN}-{q} + stamp\n"  # 10: concatenação com o carimbo (fim da string)
            f"HELP = {q}backups {OLD_BRAIN}-<data>.zip{q}\n"  # 11: prefixo seguido de "<"
            "def f():\n"
            f"    {q}{q}{q}Docstring de função: {OLD_BRAIN}.{q}{q}{q}\n"  # docstring: E5
            f"    return f{q}{{x}} ~/.config/{OLD_ATLAS}{q}\n"  # 14: f-string dentro de função
        )
        atlas_script = (
            f"OLD_CONTRACT = {q}{OLD_ATLAS}/collector@1{q}\n"  # E5
            f"SKILL_COPIES = ({q}.boson-atlas/skill{q}, {q}.{OLD_ATLAS}/skill{q})\n"  # E5
            f"CONTRACT = {q}{OLD_ATLAS}/collector@1{q}\n"  # 3: contrato fora de constante listada
            f"COPY = {q}.{OLD_ATLAS}/skill{q}\n"  # 4: pasta do atlas
        )
        markdown = (
            "# Skill\n\n"
            f"A configuração fica em `~/.config/{OLD_ATLAS}`.\n\n"  # 3: sem nota nem par novo
            f"**Compatibilidade com o nome antigo:** a pasta `~/.config/{OLD_ATLAS}` é lida como reserva.\n"  # E6a
            f"Ela continua sendo lida (`.{OLD_ATLAS}/skill`).\n\n"  # E6a (mesmo parágrafo)
            f"**O mesmo coletor com o nome antigo do contrato**:\n\n"
            f"```json\n{{\"contract\": \"{OLD_ATLAS}/collector@1\"}}\n```\n\n"  # E6a (bloco depois do parágrafo)
            f"Contrato `{NEW_ATLAS}/collector@1` (ou `{OLD_ATLAS}/collector@1`).\n"  # E6c
            f"Grava `.{OLD_ATLAS}/skill`.\n\n"  # 15: sem o par novo
            "## Atlas com o nome antigo\n\n"
            f"Antes o vendor gravava `.{OLD_ATLAS}/skill/`.\n\n"  # E6b
            "### Detalhe\n\n"
            f"`git rm -r .{OLD_ATLAS}`\n\n"  # E6b (subseção)
            "## Outra seção\n\n"
            f"| `pasta .{OLD_ATLAS}/ no atlas` | cópia antiga: mova para `.{NEW_ATLAS}/` e `git rm -r .{OLD_ATLAS}` |\n"
            # E6d: "antig" e o nome novo na mesma linha
            f"| `.{OLD_ATLAS}/skill` | cópia da ferramenta |\n\n"  # 28: tabela que não é aviso de migração
            f"Backups `{OLD_BRAIN}-AAAA-MM-DD.zip`.\n"  # 30: fora da seção antiga
            f"Copie de `<atlas>/.{OLD_ATLAS}/skill`.\n\n"  # 31: pasta do atlas logo depois de "/"
            f"| `~/.config/{OLD_ATLAS}` | pasta antiga |\n\n"  # 33: "antig" sem o nome novo (não é E6d)
            "## Dados antigos\n\n"  # título só com "antigo" (não é E6b)
            f"Ficam em `~/.config/{OLD_ATLAS}`.\n"  # 37
        )
        files = {
            "skills/photon-brain/scripts/brain.py": script,
            "skills/boson-atlas/scripts/atlas.py": atlas_script,
            "skills/boson-atlas/SKILL.md": markdown,
            "skills/boson-atlas/tests/test_x.py": f"OLD = {q}~/.config/{OLD_ATLAS}{q}\n",  # 1: teste também
            "mcp/tests/fixtures/snap.json": f'{{"contract": "{OLD_ATLAS}/collector@1"}}\n',  # 1
            "skills/boson-atlas/assets/atlas-config.yml": f"vendor: ./.{OLD_ATLAS}/skill\n",  # 1: depois de "/"
            "skills/boson-atlas/assets/collectors/legacy.py": f"print({q}{OLD_ATLAS}: falhou{q})\n",  # 1: output
            "skills/boson-atlas/assets/ci/scan.sh": f"#!/bin/sh\necho {q}{OLD_ATLAS} scan falhou{q}\n",  # 2: output
            "skills/photon-brain/scripts/lib/util.py": f"print({q}{OLD_BRAIN}{q})\n",  # 1: scripts/**
            "tools/sdd/spec_graph.py": f"print(f{q}{OLD_ATLAS} ausente: {{path}}{q})\n",  # 1: output
            # exceções E1 a E4
            "docs/specs/SPEC-0001-x.md": f"~/.config/{OLD_BRAIN}\n",
            "docs/adr/ADR-0001-x.md": f".{OLD_ATLAS}/\n",
            "skills/boson-atlas/CHANGELOG.md": f"- `{OLD_ATLAS}/collector@1`\n",
            "CHANGELOG.md": f"- `~/.config/{OLD_ATLAS}`\n",
            "skills/boson-atlas/tests/fixtures/previous/atlas.py": f"CONTRACT = {q}{OLD_ATLAS}/collector@1{q}\n",
            "skills/boson-atlas/tests/fixtures/contract/valid/old-contract-name.json":
                f'{{"contract": "{OLD_ATLAS}/collector@1"}}\n',
            "skills/boson-atlas/tests/fixtures/fake-collectors/legacy_contract.py":
                f"OLD = {q}{OLD_ATLAS}/collector@1{q}\n",
            "scripts/fermion_doctor.py": f"OLD = {q}~/.config/{OLD_BRAIN}{q}\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel, text in files.items():
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(text, encoding="utf-8")
            (root / "binary.bin").write_bytes(b"\xff\xfe.config/" + OLD_BRAIN.encode() + b"\x00")  # NUL: pulado
            (root / "notes").mkdir()
            (root / "notes" / "legado.md").write_bytes(  # latin-1: lido com substituição
                f"Configuração em ~/.config/{OLD_ATLAS}\n".encode("latin-1"))
            findings = find_technical_names(root, [*files, "binary.bin", "notes/legado.md"])
        self.assertEqual(findings, [
            f"skills/photon-brain/scripts/brain.py:5 — output: {OLD_BRAIN}",
            f"skills/photon-brain/scripts/brain.py:6 — config: .config/{OLD_BRAIN}",
            f"skills/photon-brain/scripts/brain.py:7 — backup: {OLD_BRAIN}-{{",
            f"skills/photon-brain/scripts/brain.py:8 — config: .config/{OLD_BRAIN}",
            f"skills/photon-brain/scripts/brain.py:9 — output: {OLD_BRAIN}",
            f"skills/photon-brain/scripts/brain.py:10 — backup: {OLD_BRAIN}-",
            f"skills/photon-brain/scripts/brain.py:11 — backup: {OLD_BRAIN}-<",
            f"skills/photon-brain/scripts/brain.py:14 — config: .config/{OLD_ATLAS}",
            f"skills/boson-atlas/scripts/atlas.py:3 — contract: {OLD_ATLAS}/collector@",
            f"skills/boson-atlas/scripts/atlas.py:4 — folder: .{OLD_ATLAS}",
            f"skills/boson-atlas/SKILL.md:3 — config: .config/{OLD_ATLAS}",
            f"skills/boson-atlas/SKILL.md:15 — folder: .{OLD_ATLAS}",
            f"skills/boson-atlas/SKILL.md:28 — folder: .{OLD_ATLAS}",
            f"skills/boson-atlas/SKILL.md:30 — backup: {OLD_BRAIN}-AAAA",
            f"skills/boson-atlas/SKILL.md:31 — folder: .{OLD_ATLAS}",
            f"skills/boson-atlas/SKILL.md:33 — config: .config/{OLD_ATLAS}",
            f"skills/boson-atlas/SKILL.md:37 — config: .config/{OLD_ATLAS}",
            f"skills/boson-atlas/tests/test_x.py:1 — config: .config/{OLD_ATLAS}",
            f"mcp/tests/fixtures/snap.json:1 — contract: {OLD_ATLAS}/collector@",
            f"skills/boson-atlas/assets/atlas-config.yml:1 — folder: .{OLD_ATLAS}",
            f"skills/boson-atlas/assets/collectors/legacy.py:1 — output: {OLD_ATLAS}",
            f"skills/boson-atlas/assets/ci/scan.sh:2 — output: {OLD_ATLAS}",
            f"skills/photon-brain/scripts/lib/util.py:1 — output: {OLD_BRAIN}",
            f"tools/sdd/spec_graph.py:1 — output: {OLD_ATLAS}",
            f"notes/legado.md:1 — config: .config/{OLD_ATLAS}",
        ])

    def test_versioned_files_have_no_old_technical_name_outside_the_exceptions(self):
        """SPEC-0072:UT-03 (arquivos versionados reais, depois das SPEC-0069 a 0071)"""
        findings = find_technical_names(REPO, git_files())
        self.assertEqual(findings, [], "nome técnico antigo fora das exceções:\n" + "\n".join(findings))


class SnapshotNameDocTest(unittest.TestCase):
    def test_collector_contract_says_the_scan_writes_the_old_name_until_spec_0073(self):
        """SPEC-0072:UT-03 (Emenda v3: references/collector-contract.md descreve o nome que o scan grava como o
        atlas.py faz — SNAPSHOT_CONTRACT = OLD_CONTRACT até a SPEC-0073)"""
        atlas = (REPO / "skills" / "boson-atlas" / "scripts" / "atlas.py").read_text(encoding="utf-8")
        self.assertRegex(atlas, r"(?m)^SNAPSHOT_CONTRACT = OLD_CONTRACT\b", "fixture: o scan grava o nome antigo")
        doc = (REPO / "skills" / "boson-atlas" / "references" / "collector-contract.md").read_text(encoding="utf-8")
        claims = re.findall(r"grava `snapshots/<id>\.json` sempre com [^.]*", doc)
        self.assertTrue(claims, "a referência não diz com que nome o scan grava os snapshots")
        for claim in claims:
            self.assertIn(f"{OLD_ATLAS}/collector@1", claim)
            self.assertNotIn(f"{NEW_ATLAS}/collector@1", claim)


class FallbackDocTest(unittest.TestCase):
    """SPEC-0072 (Emenda v4): a pasta antiga vale quando o config.yml da nova não existe, e a nota de compatibilidade
    do README cita o prefixo novo dos backups."""

    def read(self, rel):
        return (REPO / rel).read_text(encoding="utf-8")

    def test_readme_says_the_new_folder_config_yml(self):
        readme = self.read("README.md")
        self.assertTrue("quando o `config.yml` da pasta nova não existe" in readme,
                        "o README não diz 'quando o `config.yml` da pasta nova não existe'")
        self.assertFalse("quando a nova não existe" in readme, "o README ainda diz 'quando a nova não existe'")

    def test_gluon_spec_docs_say_the_new_folder_config_yml(self):
        for rel in ("skills/gluon-spec/SKILL.md", "skills/gluon-spec/references/brownfield.md"):
            with self.subTest(rel=rel):
                text = self.read(rel)
                self.assertFalse("only when the new folder does not exist" in text,
                                 f"{rel} ainda diz 'when the new folder does not exist'")
                self.assertTrue(re.search(r"fallback only when the new folder's `config\.yml` does not exist", text),
                                f"{rel} não diz que a reserva vale quando o config.yml da pasta nova não existe")

    def test_readme_compat_note_cites_the_new_backup_prefix(self):
        notes = [line for line in self.read("README.md").splitlines()
                 if line.startswith("**Compatibilidade com os nomes técnicos antigos")]
        self.assertEqual(len(notes), 1, "a nota de compatibilidade do README sumiu")
        self.assertTrue(f"`{NEW_BRAIN}-" in notes[0], f"a nota de compatibilidade não cita `{NEW_BRAIN}-`")


if __name__ == "__main__":
    unittest.main()
