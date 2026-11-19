"""org_context no DISCOVER (SPEC-0041): chave opcional no modelo de configuração e instrução no SKILL.md.

A integração com o atlas (SPEC-0029/SPEC-0038) fica nas instruções do agente e numa chave opcional do
sdd-config; o spec_graph.py não chama o atlas (ADR-0001, ADR-0010). Por isso os testes guardam:

- UT-01: a chave `org_context` do references/sdd-config.template.yml é detectada como nova pelo `whats-new`
  (que lê as chaves de topo do modelo, SPEC-0013) num projeto cujo sdd-config não a tem, com o comentário do
  modelo. O comentário que o `whats-new` mostra é o bloco de linhas "#" imediatamente acima da chave
  (missing_config_keys, SPEC-0013); o comentário em linha não é lido.
- UT-02: a seção DISCOVER do SKILL.md cita `org_context` e `atlas.py context`.

SPEC-0081 (vários atlas por máquina, contrato SPEC-0079@1): o DISCOVER passa o `org_context` (nome do atlas ou
caminho) como `--atlas` ao `atlas.py config --json` e ao `context`, trata o exit 3 com `init --join ... --name` e, sem
`org_context`, relata `atlas_name`/`selected_by`. Sai a comparação manual de caminhos e o conselho de trocar
`ATLAS_CONFIG_HOME`; os testes da SPEC-0041 que exigiam isso foram ajustados.

- UT-01: o item "Org context" do SKILL.md e o "Organization context" do references/brownfield.md seguem o texto novo.
- UT-02: o `whats-new` mostra `org_context` com o comentário novo (nome do atlas ou caminho relativo/~, nunca absoluto).

Os testes de CLI rodam em repositórios temporários com o registro do usuário isolado (SDD_CONFIG_HOME).
"""
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
SKILL = TESTS.parent
SCRIPT = SKILL / "scripts" / "spec_graph.py"
TEMPLATE = SKILL / "references" / "sdd-config.template.yml"
sys.path.insert(0, str(SCRIPT.parent))
sys.path.insert(0, str(TESTS))
import spec_graph as sg
from test_spec_graph import Project

NEW_KEYS_HEADER = "Configurações novas (ausentes no seu sdd-config):"

_USER_ENV = {}


def setUpModule():
    """Isola o registro do usuário (projects.json), como as demais suítes."""
    _USER_ENV["SDD_CONFIG_HOME"] = os.environ.get("SDD_CONFIG_HOME")
    _USER_ENV["dir"] = tempfile.mkdtemp()
    os.environ["SDD_CONFIG_HOME"] = _USER_ENV["dir"]


def tearDownModule():
    if _USER_ENV["SDD_CONFIG_HOME"] is None:
        os.environ.pop("SDD_CONFIG_HOME", None)
    else:
        os.environ["SDD_CONFIG_HOME"] = _USER_ENV["SDD_CONFIG_HOME"]
    shutil.rmtree(_USER_ENV["dir"], ignore_errors=True)


def new_keys(out: str) -> list:
    """Linhas "- chave: comentário" do bloco de configurações novas da saída do whats-new."""
    lines = out.splitlines()
    if NEW_KEYS_HEADER not in lines:
        return []
    block = []
    for line in lines[lines.index(NEW_KEYS_HEADER) + 1:]:
        if not line.startswith("- "):
            break
        block.append(line)
    return block


def discover_section() -> str:
    """Texto da seção "### 1. DISCOVER" do SKILL.md, até o próximo cabeçalho de mesmo nível ou superior."""
    lines = (SKILL / "SKILL.md").read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == "### 1. DISCOVER"), None)
    if start is None:
        raise AssertionError("SKILL.md sem a seção '### 1. DISCOVER'")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith(("### ", "## ", "# "))), len(lines))
    return "\n".join(lines[start + 1:end])


def paragraphs(text: str) -> list:
    """Itens de lista (linhas "- " com suas continuações) ou parágrafos separados por linha em branco."""
    blocks, current = [], []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("- "):
            if current:
                blocks.append("\n".join(current))
            current = [line] if line.strip() else []
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def org_context_item(text: str, marker: str) -> str:
    """Item de lista de topo que começa com `marker` (ex.: "- **Org context:**"), com seus subitens e continuações."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(marker)), None)
    if start is None:
        raise AssertionError(f"item {marker!r} não encontrado")
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith(("- ", "#")) or (lines[i].strip() and not lines[i][0].isspace())), len(lines))
    return "\n".join(lines[start:end])


def org_context_texts() -> dict:
    """{origem: texto} das instruções de contexto da organização no SKILL.md e no references/brownfield.md."""
    brownfield = (SKILL / "references" / "brownfield.md").read_text(encoding="utf-8")
    return {"SKILL.md": org_context_item(discover_section(), "- **Org context:**"),
            "references/brownfield.md": org_context_item(brownfield, "- **Organization context:**")}


class TemplateKeyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_whats_new_lists_org_context_with_its_comment(self):
        """SPEC-0041:UT-01 — projeto sem org_context: whats-new mostra a chave nova com o comentário do modelo."""
        template = TEMPLATE.read_text(encoding="utf-8")
        parsed = sg.parse_yaml_subset(template)
        self.assertIn("org_context", parsed, "references/sdd-config.template.yml sem a chave org_context")
        self.assertEqual(parsed["org_context"], "", "org_context deve vir vazio no modelo (sem atlas, nada muda)")

        p = Project(self.tmp / "projeto")
        self.assertNotIn("org_context", sg.parse_yaml_subset(
            (p.root / "docs/specs/sdd-config.yml").read_text(encoding="utf-8")))
        res = p.run("whats-new")
        out = res.stdout + res.stderr
        self.assertEqual(res.returncode, 0, out)
        lines = [line for line in new_keys(res.stdout) if line.startswith("- org_context:")]
        self.assertEqual(len(lines), 1, f"org_context fora das configurações novas:\n{out}")
        comment = lines[0][len("- org_context:"):].strip()
        self.assertTrue(comment, f"org_context listado sem o comentário do modelo:\n{out}")
        for fragment in ("atlas", "atlas.py context"):
            self.assertIn(fragment, comment, f"comentário de org_context sem {fragment!r}: {comment!r}")

        config = p.root / "docs/specs/sdd-config.yml"
        config.write_text(config.read_text(encoding="utf-8") + 'org_context: ""\n', encoding="utf-8")
        res = p.run("whats-new")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertFalse([line for line in new_keys(res.stdout) if line.startswith("- org_context:")],
                         f"org_context presente (vazio) não é chave nova:\n{res.stdout}")


class DiscoverInstructionTest(unittest.TestCase):
    def test_discover_section_cites_org_context_and_atlas_context(self):
        """SPEC-0041:UT-02 — a seção DISCOVER do SKILL.md cita org_context e atlas.py context."""
        section = discover_section()
        for fragment in ("org_context", "atlas.py context"):
            self.assertIn(fragment, section, f"seção DISCOVER do SKILL.md não cita {fragment!r}")

    def test_atlas_identity_is_checked_against_local_org_atlas_config(self):
        """SPEC-0041:UT-02 (revisão G4 M1: o DISCOVER confere o atlas com `atlas.py config --json` junto com
        `org_context`). Ajustado pela SPEC-0081: o atlas não é mais comparado à mão com a config local; o
        `org_context` vai como `--atlas` (coberto por SPEC-0081:UT-01)."""
        section = discover_section()
        self.assertIn("atlas.py config", section, "seção DISCOVER do SKILL.md não cita 'atlas.py config'")
        near = [para for para in paragraphs(section) if "atlas.py config" in para]
        self.assertTrue(any("org_context" in para for para in near),
                        "seção DISCOVER: 'atlas.py config' sem 'org_context' no mesmo item")

        comments = dict(sg.missing_config_keys(TEMPLATE.read_text(encoding="utf-8"), {}))
        self.assertIn("org_context", comments, "references/sdd-config.template.yml sem a chave org_context")
        self.assertIn("atlas", comments["org_context"], f"comentário de org_context sem 'atlas': {comments['org_context']!r}")

        brownfield = (SKILL / "references" / "brownfield.md").read_text(encoding="utf-8")
        self.assertIn("atlas.py config", brownfield, "references/brownfield.md não cita 'atlas.py config'")


class AtlasSelectionInstructionTest(unittest.TestCase):
    def test_org_context_is_passed_as_atlas_option(self):
        """SPEC-0081:UT-01 — SKILL.md e brownfield.md: `config --json --atlas <org_context>` e
        `context --atlas <org_context>`, exit 3 com `init --join ... --name`, `atlas_name`/`selected_by` sem
        `org_context` e nada de `ATLAS_CONFIG_HOME` como saída."""
        for origin, text in org_context_texts().items():
            with self.subTest(arquivo=origin):
                self.assertRegex(text, r"atlas\.py config --json --atlas [\"'<]*org_context",
                                 f"{origin}: não manda rodar `atlas.py config --json --atlas <org_context>`")
                self.assertRegex(text, r"atlas\.py context --atlas [\"'<]*org_context",
                                 f"{origin}: não manda rodar `atlas.py context --atlas <org_context>`")
                exit3 = [para for para in paragraphs(text) if re.search(r"\b[Ee]xit 3\b", para)]
                self.assertTrue(any(re.search(r"init --join --atlas \S+ --name\b", para) for para in exit3),
                                f"{origin}: exit 3 sem o passo `atlas.py init --join --atlas <caminho> --name <nome>`")
                self.assertTrue(any("atlas_name" in para and "selected_by" in para for para in paragraphs(text)),
                                f"{origin}: não cita `atlas_name` e `selected_by` (caso sem org_context)")
                self.assertNotIn("ATLAS_CONFIG_HOME", text,
                                 f"{origin}: ainda cita ATLAS_CONFIG_HOME como saída (comparação manual removida)")

    def test_whats_new_shows_new_org_context_comment(self):
        """SPEC-0081:UT-02 — projeto sem org_context: o whats-new mostra a chave com o comentário novo (nome do
        atlas, recomendado, ou caminho relativo ou com ~, nunca absoluto)."""
        tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        p = Project(tmp / "projeto")
        res = p.run("whats-new")
        out = res.stdout + res.stderr
        self.assertEqual(res.returncode, 0, out)
        lines = [line for line in new_keys(res.stdout) if line.startswith("- org_context:")]
        self.assertEqual(len(lines), 1, f"org_context fora das configurações novas:\n{out}")
        comment = re.sub(r"[\"'`]", "", lines[0][len("- org_context:"):]).strip()
        self.assertIn("nome do atlas", comment, f"comentário de org_context sem 'nome do atlas': {comment!r}")
        self.assertRegex(comment, r"caminho relativo\s*(?:/|ou com)\s*~",
                         f"comentário de org_context sem 'caminho relativo ou com ~': {comment!r}")
        self.assertRegex(comment, r"\bnunca\b[^.]*\babsoluto",
                         f"comentário de org_context não proíbe caminho absoluto: {comment!r}")

if __name__ == "__main__":
    unittest.main()
