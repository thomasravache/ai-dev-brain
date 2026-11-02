"""org_context no DISCOVER (SPEC-0041): chave opcional no modelo de configuração e instrução no SKILL.md.

A integração com o atlas (SPEC-0029/SPEC-0038) fica nas instruções do agente e numa chave opcional do
sdd-config; o spec_graph.py não chama o atlas (ADR-0001, ADR-0010). Por isso os testes guardam:

- UT-01: a chave `org_context` do references/sdd-config.template.yml é detectada como nova pelo `whats-new`
  (que lê as chaves de topo do modelo, SPEC-0013) num projeto cujo sdd-config não a tem, com o comentário do
  modelo. O comentário que o `whats-new` mostra é o bloco de linhas "#" imediatamente acima da chave
  (missing_config_keys, SPEC-0013); o comentário em linha não é lido.
- UT-02: a seção DISCOVER do SKILL.md cita `org_context` e `atlas.py context`.

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
        """SPEC-0041:UT-02 (revisão G4 M1: `atlas.py context` lê o atlas da config local da org-atlas; o DISCOVER
        confere `atlas.py config --json` contra `org_context` e o modelo diz que a config local decide o atlas lido)"""
        section = discover_section()
        self.assertIn("atlas.py config", section, "seção DISCOVER do SKILL.md não cita 'atlas.py config'")
        near = [para for para in paragraphs(section) if "atlas.py config" in para]
        self.assertTrue(any("org_context" in para for para in near),
                        "seção DISCOVER: 'atlas.py config' sem 'org_context' no mesmo item")

        comments = dict(sg.missing_config_keys(TEMPLATE.read_text(encoding="utf-8"), {}))
        self.assertIn("org_context", comments, "references/sdd-config.template.yml sem a chave org_context")
        comment = re.sub(r"sdd-config", "", comments["org_context"])
        self.assertIn("atlas", comment, f"comentário de org_context sem 'atlas': {comment!r}")
        self.assertRegex(comment, r"\bconfig", "comentário de org_context não diz que a config local da org-atlas "
                         f"decide o atlas lido: {comment!r}")

        brownfield = (SKILL / "references" / "brownfield.md").read_text(encoding="utf-8")
        self.assertIn("atlas.py config", brownfield, "references/brownfield.md não cita 'atlas.py config'")


if __name__ == "__main__":
    unittest.main()
