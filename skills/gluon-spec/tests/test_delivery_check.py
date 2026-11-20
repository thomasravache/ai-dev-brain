"""Roteiro de verificação do G6 a partir do `delivery` do atlas (SPEC-0086: UT-06).

A gluon-spec não chama o atlas pelo spec_graph.py (ADR-0001, ADR-0010): o roteiro fica nas instruções do agente e numa
chave opcional do sdd-config. Os testes guardam os fatos estáveis do contrato (seção 6 da SPEC-0086), não frases:

- references/sdd-config.template.yml: chave de topo `delivery_check` com `enabled` (true) e `environments` ([]), com
  o comentário do modelo acima (o `whats-new` só lê chaves de topo, e um bloco comentado com "#" não seria listado:
  "comentado" é lido como "com comentário");
- SKILL.md (seção "### 7. DEPLOY (G6)") e references/gates.md (seção "## G6 — Deploy"): `delivery_check`,
  `atlas.py context` com `--json`, o `delivery` do serviço, os três passos do roteiro (pipelines no commit do merge;
  repositório de configuração em que a imagem nova aparece; por ambiente, deployment, cluster e o estado esperado de
  sync e health), "último visto pelo atlas", só leitura, produção só com confirmação explícita e o caminho sem atlas
  (`smoke_test`, `test_e2e`, `deploy_*`, sem bloquear o G6);
- references/brownfield.md: o item "Organization context" diz que as regras do `org_context` valem também no G6;
- `whats-new` lista `delivery_check` como chave nova num projeto sem ela.

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
GATES = SKILL / "references" / "gates.md"
BROWNFIELD = SKILL / "references" / "brownfield.md"
sys.path.insert(0, str(SCRIPT.parent))
sys.path.insert(0, str(TESTS))
import spec_graph as sg
from test_org_context import new_keys, org_context_item
from test_spec_graph import Project

_USER_ENV = {}

READ_ONLY = re.compile(r"read-only|read only|só (?:de )?leitura|somente (?:de )?leitura|apenas (?:de )?leitura", re.IGNORECASE)
PRODUCTION = re.compile(r"produ(?:ction|ção)", re.IGNORECASE)
CONFIRMATION = re.compile(r"explicit|explícita", re.IGNORECASE)
NO_BLOCK = re.compile(r"never block|nunca bloque|não bloque|does(?:n't| not) block|without blocking|sem bloquear",
                      re.IGNORECASE)
LAST_SEEN = "último visto pelo atlas"


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


def section(path: Path, heading: str) -> str:
    """Texto da seção `heading` (linha exata) até o próximo cabeçalho de mesmo nível ou superior."""
    lines = path.read_text(encoding="utf-8").splitlines()
    level = len(heading) - len(heading.lstrip("#"))
    start = next((i for i, line in enumerate(lines) if line.strip() == heading), None)
    if start is None:
        raise AssertionError(f"{path.name} sem a seção {heading!r}")
    stops = tuple("#" * n + " " for n in range(1, level + 1))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith(stops)), len(lines))
    return "\n".join(lines[start + 1:end])


def g6_texts() -> dict:
    return {"SKILL.md (passo 7)": section(SKILL / "SKILL.md", "### 7. DEPLOY (G6)"),
            "references/gates.md (G6)": section(GATES, "## G6 — Deploy")}


class TemplateTest(unittest.TestCase):
    def test_template_has_delivery_check_with_enabled_and_environments(self):
        """SPEC-0086:UT-06 — o sdd-config.template.yml traz delivery_check (enabled: true, environments: []), com o
        comentário do modelo acima da chave."""
        template = TEMPLATE.read_text(encoding="utf-8")
        parsed = sg.parse_yaml_subset(template)
        self.assertIn("delivery_check", parsed, "references/sdd-config.template.yml sem a chave delivery_check")
        value = parsed["delivery_check"]
        self.assertIsInstance(value, dict, f"delivery_check não é um objeto: {value!r}")
        self.assertEqual(set(value), {"enabled", "environments"})
        self.assertEqual(str(value["enabled"]).lower(), "true")
        self.assertIn(value["environments"], ([], "[]"))
        comments = dict(sg.missing_config_keys(template, {}))
        self.assertTrue(comments.get("delivery_check", "").strip(), "delivery_check sem o comentário do modelo")

    def test_whats_new_lists_delivery_check_as_a_new_key(self):
        """SPEC-0086:UT-06 — num projeto sem delivery_check, o whats-new lista a chave nova com o comentário."""
        tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        p = Project(tmp / "projeto")
        res = p.run("whats-new")
        out = res.stdout + res.stderr
        self.assertEqual(res.returncode, 0, out)
        lines = [line for line in new_keys(res.stdout) if line.startswith("- delivery_check:")]
        self.assertEqual(len(lines), 1, f"delivery_check fora das configurações novas:\n{out}")
        self.assertTrue(lines[0][len("- delivery_check:"):].strip(), f"delivery_check sem comentário:\n{out}")


class G6InstructionTest(unittest.TestCase):
    def test_skill_and_gates_describe_the_verification_route(self):
        """SPEC-0086:UT-06 — SKILL.md (passo 7) e gates.md (G6): delivery_check, atlas.py context --json, o
        delivery dos serviços e os três passos do roteiro (pipelines do código no commit do merge; repositório de
        configuração em que a imagem nova aparece; por ambiente, deployment, cluster e estado esperado de sync e
        health), com o estado marcado "último visto pelo atlas"."""
        for origin, text in g6_texts().items():
            with self.subTest(arquivo=origin):
                for fragment in ("delivery_check", "atlas.py context", "--json", "delivery", LAST_SEEN):
                    self.assertIn(fragment, text, f"{origin}: sem {fragment!r}")
                self.assertRegex(text, re.compile(r"pipeline", re.IGNORECASE), f"{origin}: sem o passo das pipelines")
                self.assertRegex(text, re.compile(r"merge", re.IGNORECASE), f"{origin}: sem o commit do merge")
                self.assertRegex(text, re.compile(r"config_repositories|reposit\w+ de configura|configuration "
                                                  r"repositor", re.IGNORECASE), f"{origin}: sem o repositório de configuração")
                self.assertRegex(text, re.compile(r"imag", re.IGNORECASE), f"{origin}: sem a imagem nova")
                for word in ("cluster", "sync", "health"):
                    self.assertIn(word, text, f"{origin}: sem {word!r} no passo por ambiente")
                self.assertRegex(text, re.compile(r"environments|ambientes?\b|environment", re.IGNORECASE))

    def test_route_is_read_only_production_needs_confirmation_and_works_without_atlas(self):
        """SPEC-0086:UT-06 — SKILL.md (passo 7) e gates.md (G6): passos só de leitura, produção só com a confirmação
        explícita da pessoa e, sem atlas ou sem delivery, o caminho do smoke_test/test_e2e/deploy_* sem bloquear o G6."""
        for origin, text in g6_texts().items():
            with self.subTest(arquivo=origin):
                self.assertRegex(text, READ_ONLY, f"{origin}: não diz que os passos são só de leitura")
                confirmed = [para for para in re.split(r"\n\s*\n|\n(?=\s*- )", text)
                             if PRODUCTION.search(para) and CONFIRMATION.search(para)]
                self.assertTrue(confirmed, f"{origin}: produção sem a confirmação explícita")
                for fragment in ("smoke_test", "test_e2e", "deploy_"):
                    self.assertIn(fragment, text, f"{origin}: caminho sem atlas sem {fragment!r}")
                self.assertRegex(text, NO_BLOCK, f"{origin}: não diz que a falta de dado do atlas não bloqueia o G6")


class BrownfieldTest(unittest.TestCase):
    def test_org_context_rules_also_apply_in_g6(self):
        """SPEC-0086:UT-06 — o item "Organization context" do brownfield.md diz que as regras do org_context valem
        também no G6."""
        item = org_context_item(BROWNFIELD.read_text(encoding="utf-8"), "- **Organization context:**")
        self.assertIn("G6", item, "brownfield.md: as regras do org_context não citam o G6")


if __name__ == "__main__":
    unittest.main()
