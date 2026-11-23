"""Verificação ativa no G6 com `atlas.py verify` (SPEC-0091: CH-01, UT-01..UT-04, CT-01).

A gluon-spec só orquestra o `atlas.py verify` da boson-atlas (SPEC-0090) pelas instruções do agente e por chaves
opcionais do sdd-config. Os testes guardam os fatos estáveis do contrato (seção 6 da SPEC-0091), não frases:

- references/sdd-config.template.yml: `delivery_check` ganha `verify: false`, `window_minutes: 10`,
  `max_new_errors: 0` e `max_new_restarts: 0`, cada uma com comentário; o `whats-new` só lê chaves de topo, então o
  comentário de `delivery_check` (o que ele mostra) precisa citar as quatro;
- references/gates.md (subseção "Active verification" dentro de "## G6 — Deploy"): foto (`verify snapshot`) depois do
  H2 e antes do merge; `verify compare` depois dos passos 1 e 2 do roteiro da SPEC-0086 e da janela, com
  `--baseline`, `--expect-image` e os limites; veredito → G6; produção confirmada por execução e só passiva;
  "verificação ativa não executada: <motivo>" sem bloquear; foto temporária, apagada no fim, nunca em commit;
- SKILL.md (passo 7): uma frase com `delivery_check.verify` e `atlas.py verify` e o ponteiro para o gates.md (G6),
  sem repetir as regras;
- contrato: as opções citadas existem no `--help` real do `atlas.py verify`, e os exits e vereditos são os de
  skills/boson-atlas/references/verify.md.

Os testes de CLI rodam com o registro do usuário (SDD_CONFIG_HOME) e o HOME/configuração do atlas isolados.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
SKILL = TESTS.parent
SCRIPT = SKILL / "scripts" / "spec_graph.py"
TEMPLATE = SKILL / "references" / "sdd-config.template.yml"
GATES = SKILL / "references" / "gates.md"
SKILL_MD = SKILL / "SKILL.md"
ATLAS = SKILL.parent / "boson-atlas" / "scripts" / "atlas.py"
VERIFY_MD = SKILL.parent / "boson-atlas" / "references" / "verify.md"
sys.path.insert(0, str(SCRIPT.parent))
sys.path.insert(0, str(TESTS))
import spec_graph as sg
from test_delivery_check import LAST_SEEN, NO_BLOCK, PRODUCTION, section
from test_org_context import new_keys
from test_spec_graph import Project

_USER_ENV = {}

NEW_KEYS = {"verify": "false", "window_minutes": "10", "max_new_errors": "0", "max_new_restarts": "0"}
ACTIVE_HEADING = re.compile(r"^(#{3,4}) Active verification\b")
NOT_EXECUTED = "verificação ativa não executada"
FLAG = re.compile(r"(?<![\w-])--[a-z][a-z-]*")
VERDICT_EXIT = re.compile(r"`(passou|degradou|inconclusivo)` \(exit (\d)\)")


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


def g6() -> str:
    return section(GATES, "## G6 — Deploy")


def active_section() -> str:
    """Texto da subseção "Active verification" do G6, até o próximo cabeçalho de mesmo nível ou superior."""
    lines = g6().splitlines()
    start = next((i for i, line in enumerate(lines) if ACTIVE_HEADING.match(line)), None)
    if start is None:
        raise AssertionError("references/gates.md (G6) sem a subseção 'Active verification (SPEC-0091)'")
    level = len(ACTIVE_HEADING.match(lines[start]).group(1))
    stops = tuple("#" * n + " " for n in range(1, level + 1))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith(stops)), len(lines))
    return "\n".join(lines[start + 1:end])


def chunks(text: str) -> list:
    """Parágrafos e itens de lista (cada linha que começa com "- " ou "1. " abre um pedaço)."""
    return [c for c in re.split(r"\n\s*\n|\n(?=\s*(?:- |\d+\. ))", text) if c.strip()]


def chunks_with(text: str, *patterns) -> list:
    return [c for c in chunks(text) if all(re.search(p, c, re.IGNORECASE) for p in patterns)]


def step7() -> str:
    return section(SKILL_MD, "### 7. DEPLOY (G6)")


def help_flags(sub: str) -> set:
    """Opções do `atlas.py verify <sub> --help` real, com HOME e configuração isolados."""
    tmp = tempfile.mkdtemp()
    try:
        env = dict(os.environ, HOME=tmp, ATLAS_CONFIG_HOME=tmp, XDG_CONFIG_HOME=tmp)
        res = subprocess.run([sys.executable, str(ATLAS), "verify", sub, "--help"], check=False, cwd=tmp,
                             capture_output=True, text=True, env=env)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if res.returncode != 0:
        raise AssertionError(f"atlas.py verify {sub} --help saiu com {res.returncode}:\n{res.stdout}{res.stderr}")
    return set(FLAG.findall(res.stdout))


class CharacterizationTest(unittest.TestCase):
    def test_spec_0086_route_is_kept_and_verify_is_off_by_default(self):
        """SPEC-0091:CH-01 — o que a SPEC-0086 fixou continua: o roteiro do G6 (atlas.py context --json, "último
        visto pelo atlas", só leitura, fallback smoke_test/test_e2e/deploy_* sem bloquear), a SKILL.md (passo 7)
        com delivery_check e o ponteiro, e o template com delivery_check (enabled: true, environments: []). Sem
        verify (ou verify: false), nada de novo é exigido: o padrão do template é desligado."""
        text = g6()
        self.assertIn("### Verification route from the atlas (SPEC-0086)", GATES.read_text(encoding="utf-8"))
        for fragment in ("delivery_check", "atlas.py context", "--json", LAST_SEEN, "smoke_test", "test_e2e",
                         "deploy_"):
            self.assertIn(fragment, text, f"gates.md (G6): sem {fragment!r} da SPEC-0086")
        self.assertRegex(text, NO_BLOCK, "gates.md (G6): o fallback sem atlas deixou de dizer que não bloqueia")
        skill = step7()
        for fragment in ("delivery_check", "atlas.py context", "gates.md"):
            self.assertIn(fragment, skill, f"SKILL.md (passo 7): sem {fragment!r} da SPEC-0086")
        parsed = sg.parse_yaml_subset(TEMPLATE.read_text(encoding="utf-8"))
        value = parsed.get("delivery_check")
        self.assertIsInstance(value, dict, f"template: delivery_check não é um objeto: {value!r}")
        self.assertEqual(str(value.get("enabled")).lower(), "true")
        self.assertIn(value.get("environments"), ([], "[]"))
        self.assertEqual(str(value.get("verify", "false")).lower(), "false",
                         "template: a verificação ativa não pode vir ligada")


class TemplateTest(unittest.TestCase):
    def test_template_has_verify_keys_with_defaults_and_comments(self):
        """SPEC-0091:UT-01 — delivery_check no template traz verify: false, window_minutes: 10, max_new_errors: 0 e
        max_new_restarts: 0, cada uma com comentário (na linha ou no comentário da chave)."""
        template = TEMPLATE.read_text(encoding="utf-8")
        value = sg.parse_yaml_subset(template).get("delivery_check")
        self.assertIsInstance(value, dict, f"template: delivery_check não é um objeto: {value!r}")
        for key, default in NEW_KEYS.items():
            with self.subTest(chave=key):
                self.assertIn(key, value, f"template: delivery_check sem {key}")
                self.assertEqual(str(value[key]).lower(), default, f"template: {key} com padrão errado")
        block_comment = dict(sg.missing_config_keys(template, {})).get("delivery_check", "")
        for key in NEW_KEYS:
            with self.subTest(comentario=key):
                line = next((ln for ln in template.splitlines() if re.match(rf"^\s+{key}\s*:", ln)), "")
                inline = "#" in line and line.split("#", 1)[1].strip()
                self.assertTrue(inline or key in block_comment, f"template: {key} sem comentário")

    def test_whats_new_shows_the_verify_keys(self):
        """SPEC-0091:UT-01 — num projeto sem delivery_check, o whats-new lista delivery_check com um comentário que
        cita verify, window_minutes, max_new_errors e max_new_restarts (o whats-new só lê chaves de topo)."""
        tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        res = Project(tmp / "projeto").run("whats-new")
        out = res.stdout + res.stderr
        self.assertEqual(res.returncode, 0, out)
        lines = [line for line in new_keys(res.stdout) if line.startswith("- delivery_check:")]
        self.assertEqual(len(lines), 1, f"delivery_check fora das configurações novas:\n{out}")
        for key in NEW_KEYS:
            self.assertRegex(lines[0], rf"\b{key}\b", f"whats-new: o comentário de delivery_check não cita {key}:\n{out}")


class PhasesAndVerdictTest(unittest.TestCase):
    def test_snapshot_after_h2_and_before_merge(self):
        """SPEC-0091:UT-02 — gates.md (G6): verify snapshot por serviço e ambiente, depois do H2 e antes do merge,
        com --service, --env e --out."""
        text = active_section()
        found = chunks_with(text, r"verify snapshot", r"\bH2\b", r"before (?:the )?merge|antes do merge")
        self.assertTrue(found, "gates.md (G6): a foto não está marcada depois do H2 e antes do merge")
        for flag in ("--service", "--env", "--out"):
            self.assertTrue(any(flag in c for c in chunks_with(text, r"verify snapshot")),
                            f"gates.md (G6): verify snapshot sem {flag}")
        self.assertIn("delivery_check.verify", text, "gates.md (G6): não diz que a foto depende de delivery_check.verify")
        self.assertIn("environments", text, "gates.md (G6): não diz quais ambientes (delivery_check.environments)")

    def test_compare_after_route_steps_1_and_2_and_the_window(self):
        """SPEC-0091:UT-02 — gates.md (G6): verify compare depois dos passos 1 e 2 do roteiro e de window_minutes,
        com --baseline, --expect-image, --window, --max-new-errors, --max-new-restarts e --json."""
        text = active_section()
        compare = "\n".join(chunks_with(text, r"verify compare"))
        self.assertTrue(compare, "gates.md (G6): sem verify compare")
        for flag in ("--baseline", "--expect-image", "--window", "--max-new-errors", "--max-new-restarts", "--json"):
            self.assertIn(flag, text, f"gates.md (G6): verify compare sem {flag}")
        for key in ("window_minutes", "max_new_errors", "max_new_restarts"):
            self.assertIn(key, text, f"gates.md (G6): os limites não vêm de {key}")
        self.assertRegex(text, re.compile(r"steps? 1 (?:and|e) 2|passos? 1 e 2|steps? 1\s*[–-]\s*2|passos? 1\s*[–-]\s*2",
                                          re.IGNORECASE), "gates.md (G6): compare não espera os passos 1 e 2 do roteiro")
        self.assertRegex(text, re.compile(r"after|depois", re.IGNORECASE))
        self.assertRegex(text, re.compile(r"window|janela", re.IGNORECASE), "gates.md (G6): sem a espera da janela")

    def test_verdict_maps_to_g6(self):
        """SPEC-0091:UT-02 — gates.md (G6): passou → PASS; degradou → FAIL com a sugestão de rollback e a pessoa
        decide; inconclusivo → a pessoa decide PASS ou FAIL e a decisão é registrada."""
        text = active_section()
        self.assertTrue(chunks_with(text, r"\bpassou\b", r"\bPASS\b"), "gates.md (G6): passou sem → PASS")
        degraded = chunks_with(text, r"\bdegradou\b", r"\bFAIL\b", r"rollback")
        self.assertTrue(degraded, "gates.md (G6): degradou sem → FAIL e a sugestão de rollback")
        self.assertTrue([c for c in degraded if re.search(r"\b(?:user|person|human|pessoa)\b", c, re.IGNORECASE)
                         and re.search(r"decid", c, re.IGNORECASE)],
                        "gates.md (G6): em degradou, o rollback não fica com a decisão da pessoa")
        unsure = chunks_with(text, r"\binconclusivo\b", r"\b(?:user|person|human|pessoa)\b", r"decid")
        self.assertTrue(unsure, "gates.md (G6): inconclusivo sem a decisão da pessoa")
        self.assertTrue([c for c in unsure if re.search(r"record|registr", c, re.IGNORECASE)],
                        "gates.md (G6): inconclusivo sem registrar a decisão")
        self.assertRegex(text, re.compile(r"Relatório de Entrega", re.IGNORECASE),
                         "gates.md (G6): o veredito não vai para o Relatório de Entrega")


class SafetyTest(unittest.TestCase):
    def test_production_is_confirmed_per_run_and_passive(self):
        """SPEC-0091:UT-03 — gates.md (G6): em produção, --confirm-production só depois do "sim" da pessoa para
        aquela execução, e a verificação lá é só passiva."""
        text = active_section()
        confirmed = [c for c in chunks_with(text, r"--confirm-production") if PRODUCTION.search(c)]
        self.assertTrue(confirmed, "gates.md (G6): produção sem --confirm-production")
        self.assertTrue([c for c in confirmed
                         if re.search(r"each run|every run|per run|that run|this run|cada execução|por execução|"
                                      r"aquela execução|essa execução", c, re.IGNORECASE)],
                        "gates.md (G6): a confirmação de produção não é por execução")
        self.assertTrue([c for c in confirmed if re.search(r"\byes\b|\"sim\"|“sim”|explicit|explícit", c,
                                                           re.IGNORECASE)],
                        "gates.md (G6): --confirm-production não espera o sim da pessoa")
        self.assertTrue([c for c in chunks(text) if PRODUCTION.search(c) and re.search(r"passiv", c, re.IGNORECASE)],
                        "gates.md (G6): não diz que em produção a verificação é só passiva")

    def test_unavailable_verification_is_recorded_without_blocking(self):
        """SPEC-0091:UT-03 — gates.md (G6): probes desligadas, sem acesso ou sem atlas → "verificação ativa não
        executada: <motivo>", segue smoke_test/test_e2e e não bloqueia o G6."""
        text = active_section()
        found = [c for c in chunks(text) if NOT_EXECUTED in c]
        self.assertTrue(found, f"gates.md (G6): sem {NOT_EXECUTED!r}")
        joined = "\n".join(found)
        self.assertRegex(joined, re.compile(r"<motivo>|<reason>|reason|motivo", re.IGNORECASE))
        for pattern, what in ((r"probe", "probes desligadas"), (r"access|acesso", "sem acesso"),
                              (r"atlas", "sem atlas")):
            self.assertRegex(text, re.compile(pattern, re.IGNORECASE), f"gates.md (G6): sem o caso {what}")
        for fragment in ("smoke_test", "test_e2e"):
            self.assertIn(fragment, text, f"gates.md (G6): a verificação não executada não segue com {fragment}")
        self.assertRegex(text, NO_BLOCK, "gates.md (G6): a verificação não executada bloqueia o G6")

    def test_snapshot_file_is_temporary_deleted_and_never_committed(self):
        """SPEC-0091:UT-03 — gates.md (G6): a foto fica num arquivo temporário da tarefa, fora do repositório e do
        atlas, é apagada no fim da tarefa e nunca entra em commit."""
        text = active_section()
        self.assertRegex(text, re.compile(r"temporar|temporári", re.IGNORECASE), "gates.md (G6): foto não temporária")
        self.assertRegex(text, re.compile(r"outside|fora d", re.IGNORECASE),
                         "gates.md (G6): não diz que a foto fica fora do repositório e do atlas")
        self.assertRegex(text, re.compile(r"delete|apag|remov", re.IGNORECASE), "gates.md (G6): a foto não é apagada")
        self.assertRegex(text, re.compile(r"(?:never|nunca)[^.\n]*commit", re.IGNORECASE),
                         "gates.md (G6): não diz que a foto nunca entra em commit")


class SkillPointerTest(unittest.TestCase):
    def test_skill_step_7_mentions_verify_in_one_sentence_and_points_to_gates(self):
        """SPEC-0091:UT-04 — a SKILL.md (passo 7) cita delivery_check.verify e atlas.py verify numa frase, aponta
        para references/gates.md (G6) e não repete as regras (opções, limites e vereditos)."""
        text = step7()
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z`(])", text)
        found = [s for s in sentences if "delivery_check.verify" in s and "atlas.py verify" in s]
        self.assertTrue(found, "SKILL.md (passo 7): sem uma frase com delivery_check.verify e atlas.py verify")
        paragraph = next(p for p in re.split(r"\n\s*\n", text) if found[0].strip() in p)
        self.assertRegex(paragraph, re.compile(r"gates\.md`?\s*\(?G6"), "SKILL.md (passo 7): sem o ponteiro para o G6")
        for detail in ("--expect-image", "--baseline", "--max-new-errors", "--max-new-restarts", "--confirm-production",
                       "window_minutes", "max_new_errors", "degradou", "inconclusivo", NOT_EXECUTED):
            self.assertNotIn(detail, text, f"SKILL.md (passo 7): repete a regra {detail!r} do gates.md")


class ContractTest(unittest.TestCase):
    def test_cited_options_exist_in_atlas_verify_help(self):
        """SPEC-0091:CT-01 — toda opção citada na verificação ativa do G6 existe no --help real de atlas.py verify
        snapshot/compare; as citadas logo depois de cada subcomando existem no help dele."""
        snapshot, compare = help_flags("snapshot"), help_flags("compare")
        text = active_section()
        cited = set(FLAG.findall(text))
        self.assertTrue(cited, "gates.md (G6): nenhuma opção do atlas.py verify citada")
        unknown = cited - (snapshot | compare)
        self.assertFalse(unknown, f"gates.md (G6): opções fora do atlas.py verify: {sorted(unknown)}")
        for sub, flags in (("snapshot", snapshot), ("compare", compare)):
            for match in re.finditer(rf"verify {sub}\b([^`\n]*)", text):
                extra = set(FLAG.findall(match.group(1))) - flags
                with self.subTest(subcomando=sub, trecho=match.group(0)):
                    self.assertFalse(extra, f"gates.md (G6): verify {sub} não tem {sorted(extra)}")

    def test_cited_exits_and_verdicts_match_verify_md(self):
        """SPEC-0091:CT-01 — os vereditos e exits citados no G6 (passou 0, degradou 1, inconclusivo 5, recusado ou
        probes desligadas 4) são os de skills/boson-atlas/references/verify.md."""
        reference = dict(VERDICT_EXIT.findall(VERIFY_MD.read_text(encoding="utf-8")))
        self.assertEqual(reference, {"passou": "0", "degradou": "1", "inconclusivo": "5"},
                         "verify.md mudou os vereditos ou exits que a SPEC-0091 consome")
        self.assertRegex(VERIFY_MD.read_text(encoding="utf-8"), r"\b4 probes desligadas")
        text = active_section()
        for verdict, code in reference.items():
            with self.subTest(veredito=verdict):
                cited = rf"exit\s*{code}\b|\({code}\)|exit code {code}\b"
                self.assertTrue(chunks_with(text, rf"\b{verdict}\b", cited),
                                f"gates.md (G6): {verdict} sem o exit {code} do verify.md")
                for c in chunks_with(text, rf"\b{verdict}\b"):
                    for other in set(re.findall(r"exit\s*(\d)|\((\d)\)", c)):
                        num = next(n for n in other if n)
                        if num != code and not any(re.search(rf"\b{v}\b", c) for v, k in reference.items()
                                                   if k == num):
                            self.fail(f"gates.md (G6): {verdict} citado com o exit {num}, não {code}")
        self.assertTrue(chunks_with(text, r"exit\s*4\b|\(4\)", r"probe|recus|refus"),
                        "gates.md (G6): sem o exit 4 (probes desligadas ou produção recusada)")


if __name__ == "__main__":
    unittest.main()
