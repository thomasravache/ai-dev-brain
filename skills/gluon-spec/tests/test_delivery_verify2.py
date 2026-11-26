"""G6 com verify@2, acompanhamento da entrega e validação funcional (SPEC-0105: CH-01, UT-01..UT-06, IT-01, IT-02,
CT-01).

A gluon-spec só orquestra o `atlas.py verify` da boson-atlas pelas instruções do agente e por chaves opcionais do
sdd-config, como na SPEC-0091 (o `test_delivery_verify.py` fica como está). Os testes guardam os fatos estáveis do
contrato (seção 6 da SPEC-0105), não frases:

- references/sdd-config.template.yml: `delivery_check` ganha `functional: false`, `max_new_dlq: 0`,
  `max_queue_age: 10m`, `max_signal_increase: 0.5`, `max_resources: 20` e `track_max_minutes: 30`, cada uma com
  comentário; o comentário de `delivery_check` (o que o `whats-new` mostra) cita `functional` e o `verify track`;
- references/gates.md (subseção "Active verification" do G6): o `verify track` como os passos 1 e 2 do roteiro, com o
  `expected_image` indo para o `--expect-image`; o exit 6 repetido a cada `window_minutes` só até
  `track_max_minutes` (um `track` sem imagem esperada pode ficar em `pending` para sempre, então o limite é o que
  encerra o acompanhamento); o escopo padrão do `verify@2` e o `--resource` só acima de `max_resources`; o
  `--functional` só com `delivery_check.functional: true` e `tier: test`; a confirmação de produção por execução,
  inclusive a cada repetição do `track`; a linha do Relatório de Entrega;
- SKILL.md (passo 7): uma oração com `verify track`, as dependências e `delivery_check.functional`, e o ponteiro;
- contrato: as opções citadas existem no `--help` real de `atlas.py verify snapshot|compare|track`, e os exits, os
  estados e as etapas do `track` são os de skills/boson-atlas/references/verify.md.

Os testes de CLI rodam com o registro do usuário (SDD_CONFIG_HOME) e HOME, ATLAS_CONFIG_HOME e XDG_CONFIG_HOME
temporários; o `atlas.py` só roda com `--help`.
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
SKILL_MD = SKILL / "SKILL.md"
CHANGELOG = SKILL / "CHANGELOG.md"
VERIFY_MD = SKILL.parent / "boson-atlas" / "references" / "verify.md"
sys.path.insert(0, str(SCRIPT.parent))
sys.path.insert(0, str(TESTS))
import spec_graph as sg
from test_delivery_check import LAST_SEEN, NO_BLOCK, PRODUCTION, section
from test_delivery_verify import (
    FLAG,
    active_section,
    changelog_section,
    chunks,
    chunks_with,
    help_flags,
    step7,
)
from test_org_context import new_keys
from test_spec_graph import Project
from test_whats_new import vendor_tool

_USER_ENV = {}

OLD_KEYS = {"verify": "false", "window_minutes": "10", "max_new_errors": "0", "max_new_restarts": "0"}
NEW_KEYS = {"functional": "false", "max_new_dlq": "0", "max_queue_age": "10m", "max_signal_increase": "0.5",
            "max_resources": "20", "track_max_minutes": "30"}
PREVIOUS_VERSION = "2026.11.10"
H2_HEADING = "## H2 — Integration approval (human)"
PERSON = r"\b(?:user|person|human|pessoa)\b"
DECIDES = r"decid"
MANUAL = r"manual|by hand|à mão|SPEC-0086"
REPEAT = r"repeat|repet|again|retry|de novo|novamente"
NOT_TRACKED = "entrega não acompanhada até o fim"
NO_ADAPTER_REPORT = "sem adaptador de recurso nesta máquina"
ACCESS_SETUP = r"access setup"
DECLARE_ADAPTER = r"declar\w*[^.\n]*adapt|adapt\w*[^.\n]*declar"
TIER_TEST = r"tier:?\s*`?\s*test\b"
PER_RUN = (r"each run|every run|per run|that run|this run|cada execução|por execução|aquela execução|essa execução|"
           r"each (?:execution|call|query)|every (?:execution|call|query)")
YES = r"\byes\b|\"sim\"|“sim”|explicit|explícit"
DEPENDENCY_FLAGS = ("--resource", "--max-resources", "--max-new-dlq", "--max-queue-age", "--expect-migration",
                    "--max-signal-increase")
TRACK_STATES = ("pending", "running", "ok", "failed", "not_verified")
TRACK_STAGES = ("pipeline", "image", "gitops", "rollout")


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


def exit_code(code: int) -> str:
    return rf"exit\s*{code}\b|\({code}\)|exit code {code}\b"


def isolated_env(tmp: Path) -> dict:
    """HOME, ATLAS_CONFIG_HOME e XDG_CONFIG_HOME temporários: nada de ~/.claude ou ~/.config reais."""
    home = tmp / "home"
    home.mkdir(parents=True, exist_ok=True)
    return {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"), "ATLAS_CONFIG_HOME": str(home / ".atlas")}


def version_tuple(version: str) -> tuple:
    return tuple(int(part) for part in version.split("."))


def track_section_of_verify_md() -> str:
    """Seção "## `verify track`" do verify.md da boson-atlas, até o próximo `## `."""
    lines = VERIFY_MD.read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == "## `verify track`"), None)
    if start is None:
        raise AssertionError("verify.md da boson-atlas sem a seção '## `verify track`'")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start + 1:end])


def track_exit_table() -> dict:
    """{state: exit} da tabela "Estado e exits" do `verify track` no verify.md."""
    return dict(re.findall(r"^\|\s*`(\w+)`\s*\|\s*(\d)\s*\|", track_section_of_verify_md(), re.MULTILINE))


class CharacterizationTest(unittest.TestCase):
    # SPEC-0105:CH-01
    def test_what_spec_0086_and_spec_0091_fixed_is_kept(self):
        """SPEC-0105:CH-01 — continuam: o roteiro do G6 com "último visto pelo atlas" e o fallback smoke_test e
        test_e2e; a foto no H2, antes do merge, inclusive com auto-on-green; o compare depois dos passos 1 e 2 do
        roteiro; passou → PASS, degradou → FAIL com o rollback decidido pela pessoa, inconclusivo → a pessoa decide;
        a confirmação de produção por execução; a foto temporária apagada no fim; e as quatro chaves da SPEC-0091 no
        template, com verify desligado (sem verify, nada de novo é exigido)."""
        g6 = section(GATES, "## G6 — Deploy")
        self.assertIn("### Verification route from the atlas (SPEC-0086)", GATES.read_text(encoding="utf-8"))
        for fragment in (LAST_SEEN, "smoke_test", "test_e2e"):
            self.assertIn(fragment, g6, f"gates.md (G6): sem {fragment!r} da SPEC-0086")
        h2 = section(GATES, H2_HEADING)
        self.assertTrue([c for c in chunks_with(h2, r"delivery_check\.verify", r"snapshot|foto",
                                                r"before (?:the )?merg|antes do merge") if "auto-on-green" in c],
                        "gates.md (H2): a foto deixou de ser tirada antes do merge, inclusive com auto-on-green")
        text = active_section()
        self.assertTrue(chunks_with(text, r"verify compare|compare",
                                    r"steps? 1 (?:and|e) 2|passos? 1 e 2|steps? 1\s*[–-]\s*2"),
                        "gates.md (G6): o compare deixou de vir depois dos passos 1 e 2 do roteiro")
        self.assertTrue(chunks_with(text, r"\bpassou\b", r"\bPASS\b"), "gates.md (G6): passou sem → PASS")
        self.assertTrue(chunks_with(text, r"\bdegradou\b", r"\bFAIL\b", r"rollback", PERSON, DECIDES),
                        "gates.md (G6): degradou sem → FAIL com o rollback decidido pela pessoa")
        self.assertTrue(chunks_with(text, r"\binconclusivo\b", PERSON, DECIDES),
                        "gates.md (G6): inconclusivo sem a decisão da pessoa")
        self.assertTrue([c for c in chunks_with(text, r"--confirm-production", PER_RUN) if PRODUCTION.search(c)],
                        "gates.md (G6): a confirmação de produção deixou de ser por execução")
        self.assertRegex(text, re.compile(r"temporar|temporári", re.IGNORECASE), "gates.md (G6): foto não temporária")
        self.assertRegex(text, re.compile(r"delete|apag|remov", re.IGNORECASE), "gates.md (G6): a foto não é apagada")
        self.assertRegex(text, re.compile(r"delivery_check\.verify[^\n]*default `?false", re.IGNORECASE),
                         "gates.md (G6): a verificação ativa deixou de ser desligada por padrão")
        value = sg.parse_yaml_subset(TEMPLATE.read_text(encoding="utf-8")).get("delivery_check")
        self.assertIsInstance(value, dict, f"template: delivery_check não é um objeto: {value!r}")
        for key, default in OLD_KEYS.items():
            with self.subTest(chave=key):
                self.assertEqual(str(value.get(key)).lower(), default, f"template: {key} da SPEC-0091 mudou")


class TemplateTest(unittest.TestCase):
    # SPEC-0105:UT-01
    def test_template_has_the_new_keys_with_defaults_and_comments(self):
        """SPEC-0105:UT-01 — delivery_check no template tem functional: false, max_new_dlq: 0, max_queue_age: 10m,
        max_signal_increase: 0.5, max_resources: 20 e track_max_minutes: 30, cada uma com comentário; o comentário de
        delivery_check cita functional e o verify track; as quatro chaves da SPEC-0091 continuam."""
        template = TEMPLATE.read_text(encoding="utf-8")
        value = sg.parse_yaml_subset(template).get("delivery_check")
        self.assertIsInstance(value, dict, f"template: delivery_check não é um objeto: {value!r}")
        block_comment = dict(sg.missing_config_keys(template, {})).get("delivery_check", "")
        for key, default in {**OLD_KEYS, **NEW_KEYS}.items():
            with self.subTest(chave=key):
                self.assertIn(key, value, f"template: delivery_check sem {key}")
                self.assertEqual(str(value[key]).lower(), default, f"template: {key} com padrão errado")
                line = next((ln for ln in template.splitlines() if re.match(rf"^\s+{key}\s*:", ln)), "")
                inline = "#" in line and line.split("#", 1)[1].strip()
                self.assertTrue(inline or key in block_comment, f"template: {key} sem comentário")
        self.assertRegex(block_comment, r"\bfunctional\b", "template: o comentário de delivery_check não cita functional")
        self.assertIn("verify track", block_comment, "template: o comentário de delivery_check não cita o verify track")

    # SPEC-0105:UT-01
    def test_track_max_minutes_comment_bounds_the_verify_track(self):
        """SPEC-0105:UT-01 — o comentário de track_max_minutes diz que é o tempo máximo acompanhando a entrega com o
        verify track (o track não repete sozinho e, sem imagem esperada, pode ficar em pending para sempre)."""
        template = TEMPLATE.read_text(encoding="utf-8")
        line = next((ln for ln in template.splitlines() if re.match(r"^\s+track_max_minutes\s*:", ln)), "")
        block_comment = dict(sg.missing_config_keys(template, {})).get("delivery_check", "")
        comment = (line.split("#", 1)[1] if "#" in line else "") + " " + block_comment
        self.assertIn("verify track", comment, "template: track_max_minutes não diz que limita o verify track")
        self.assertRegex(comment, re.compile(r"máxim|maximum|\bmax\b|limit", re.IGNORECASE),
                         "template: track_max_minutes não diz que é um limite")

    # SPEC-0105:UT-01
    def test_whats_new_lists_delivery_check_citing_functional_and_verify_track(self):
        """SPEC-0105:UT-01 — num projeto sem delivery_check, o whats-new lista delivery_check com um comentário que
        cita functional e o verify track (o whats-new só lê chaves de topo)."""
        tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        res = Project(tmp / "projeto").run("whats-new", env=isolated_env(tmp))
        out = res.stdout + res.stderr
        self.assertEqual(res.returncode, 0, out)
        lines = [line for line in new_keys(res.stdout) if line.startswith("- delivery_check:")]
        self.assertEqual(len(lines), 1, f"delivery_check fora das configurações novas:\n{out}")
        self.assertRegex(lines[0], r"\bfunctional\b", f"whats-new: delivery_check sem functional:\n{out}")
        self.assertIn("verify track", lines[0], f"whats-new: delivery_check sem o verify track:\n{out}")


class TrackTest(unittest.TestCase):
    # SPEC-0105:UT-02
    def test_track_replaces_route_steps_1_and_2_with_the_full_merge_sha(self):
        """SPEC-0105:UT-02 — gates.md (G6): verify track com --service, --env, --commit (o sha completo do merge, 40
        hexadecimais) e --json, como os passos 1 e 2 do roteiro."""
        text = active_section()
        track = chunks_with(text, r"verify track")
        self.assertTrue(track, "gates.md (G6): sem o verify track")
        joined = "\n".join(track)
        for flag in ("--service", "--env", "--commit", "--json"):
            self.assertIn(flag, joined, f"gates.md (G6): verify track sem {flag}")
        self.assertTrue(chunks_with(text, r"verify track", r"--commit", r"merge", r"\b40\b|full|complet"),
                        "gates.md (G6): --commit não é o sha completo do commit do merge")
        self.assertTrue(chunks_with(text, r"verify track|`track`",
                                    r"steps? 1 (?:and|e) 2|passos? 1 e 2|steps? 1\s*[–-]\s*2"),
                        "gates.md (G6): o verify track não faz os passos 1 e 2 do roteiro")

    # SPEC-0105:UT-02
    def test_state_ok_puts_expected_image_into_expect_image(self):
        """SPEC-0105:UT-02 — gates.md (G6): state ok (exit 0) da saída track@1 → o expected_image vira o
        --expect-image do compare."""
        found = chunks_with(active_section(), r"expected_image", r"--expect-image", r"`ok`|\bok\b", exit_code(0))
        self.assertTrue(found, "gates.md (G6): state ok (exit 0) sem o expected_image no --expect-image")
        self.assertTrue(chunks_with(active_section(), r"verify track|`track`", r"track@1", r"\bstate\b"),
                        "gates.md (G6): o track não é lido pelo state da saída track@1")

    # SPEC-0105:UT-02
    def test_in_progress_repeats_each_window_until_track_max_minutes_then_manual_route(self):
        """SPEC-0105:UT-02 — gates.md (G6): running ou pending (exit 6) → espera window_minutes e repete, até
        track_max_minutes; passou do limite → "entrega não acompanhada até o fim: <current_stage>" e o roteiro
        manual."""
        text = active_section()
        found = chunks_with(text, r"\brunning\b", r"\bpending\b", exit_code(6), r"window_minutes", REPEAT,
                            r"track_max_minutes")
        self.assertTrue(found, "gates.md (G6): exit 6 sem repetir a cada window_minutes até track_max_minutes")
        after = chunks_with(text, r"track_max_minutes", r"current_stage", MANUAL)
        self.assertTrue(after, "gates.md (G6): depois de track_max_minutes não segue o roteiro manual com o "
                               "current_stage")
        self.assertTrue([c for c in after if NOT_TRACKED in c],
                        f"gates.md (G6): sem {NOT_TRACKED!r} depois de track_max_minutes")

    # SPEC-0105:UT-02
    def test_every_retry_of_exit_6_is_bounded_by_track_max_minutes(self):
        """SPEC-0105:UT-02 — gates.md (G6): toda instrução de repetir o track no exit 6 traz o limite
        track_max_minutes. Sem --expect-image, um track com a pipeline not_verified fica em pending (exit 6) para
        sempre (verify.md: image pending enquanto a pipeline não está ok), e o track não repete sozinho: o limite do
        G6 é o que encerra o acompanhamento."""
        retries = chunks_with(active_section(), exit_code(6), REPEAT, r"wait|esper|window_minutes")
        self.assertTrue(retries, "gates.md (G6): sem a espera e a repetição do track no exit 6")
        for chunk in retries:
            with self.subTest(trecho=chunk.strip()[:80]):
                self.assertIn("track_max_minutes", chunk,
                              "gates.md (G6): repete o track no exit 6 sem o limite track_max_minutes")
        self.assertNotRegex(active_section(), re.compile(r"(?:until|até)[^.\n]{0,20}`?ok`?\b(?![^.\n]*track_max)",
                                                         re.IGNORECASE),
                            "gates.md (G6): repete o track até ok, sem limite")

    # SPEC-0105:UT-02
    def test_failed_stage_is_g6_fail_and_the_person_decides(self):
        """SPEC-0105:UT-02 — gates.md (G6): state failed (exit 1) → G6 FAIL com a etapa, e a pessoa decide."""
        found = chunks_with(active_section(), r"`failed`|\bfailed\b", exit_code(1), r"\bFAIL\b",
                            r"\bstage\b|etapa", PERSON, DECIDES)
        self.assertTrue(found, "gates.md (G6): track failed (exit 1) sem G6 FAIL com a etapa e a decisão da pessoa")
        self.assertRegex("\n".join(found), r"reason|evidence|motivo|evidência",
                         "gates.md (G6): o FAIL do track não leva o motivo ou a evidência da etapa")

    # SPEC-0105:UT-02
    def test_track_unavailable_falls_back_to_the_manual_route(self):
        """SPEC-0105:UT-02 — gates.md (G6): not_verified (exit 5), exits 2, 3 ou 4, ou sem o subcomando (boson-atlas
        antiga) → passos 1 e 2 à mão, como no roteiro da SPEC-0086."""
        text = active_section()
        manual = chunks_with(text, r"track", MANUAL)
        self.assertTrue(manual, "gates.md (G6): sem o roteiro manual quando o track não está disponível")
        joined = "\n".join(manual)
        self.assertTrue(chunks_with(text, r"not_verified", exit_code(5), MANUAL),
                        "gates.md (G6): track not_verified (exit 5) sem o roteiro manual")
        for code in (2, 3, 4):
            with self.subTest(exit=code):
                self.assertRegex(joined, rf"\b{code}\b", f"gates.md (G6): exit {code} do track sem o roteiro manual")
        self.assertRegex(joined, re.compile(r"subcomman|subcomando|older boson-atlas|boson-atlas antiga|"
                                            r"not available|indisponível|unavailable", re.IGNORECASE),
                         "gates.md (G6): sem o roteiro manual quando o verify track não existe")


class DependenciesTest(unittest.TestCase):
    # SPEC-0105:UT-03
    def test_default_scope_has_no_resource_and_the_same_max_resources(self):
        """SPEC-0105:UT-03 — gates.md (G6): por padrão, sem --resource (o escopo padrão do verify@2: os recursos
        ligados ao serviço no ambiente), e o mesmo --max-resources no snapshot e no compare."""
        text = active_section()
        self.assertTrue(chunks_with(text, r"verify@2", r"(?:without|no|sem)\s+`?--resource"),
                        "gates.md (G6): sem o escopo padrão do verify@2, sem --resource")
        for sub in ("snapshot", "compare"):
            with self.subTest(subcomando=sub):
                self.assertTrue([m for m in re.finditer(rf"verify {sub}\b([^\n]*)", text)
                                 if "--max-resources" in m.group(1)],
                                f"gates.md (G6): verify {sub} sem --max-resources")
        self.assertTrue(chunks_with(text, r"--max-resources", r"\bsame\b|mesm", r"snapshot", r"compare"),
                        "gates.md (G6): não diz que o mesmo --max-resources vai ao snapshot e ao compare")
        self.assertRegex(text, r"--max-resources\W+max_resources", "gates.md (G6): --max-resources não vem de "
                                                                   "max_resources")

    # SPEC-0105:UT-03
    def test_resource_only_above_max_resources_and_only_for_the_diff(self):
        """SPEC-0105:UT-03 — gates.md (G6): --resource só quando as dependências do serviço no pacote do context
        passam de max_resources, e então só para os recursos que o diff aponta, a mesma lista nos dois comandos."""
        found = chunks_with(active_section(), r"--resource", r"max_resources", r"\bdiff\b", r"context")
        self.assertTrue(found, "gates.md (G6): --resource não fica restrito a acima de max_resources e ao diff")
        self.assertTrue([c for c in chunks_with(active_section(), r"--resource", r"\bsame\b|mesm",
                                                r"snapshot", r"compare")],
                        "gates.md (G6): a mesma lista de --resource não vai ao snapshot e ao compare")

    # SPEC-0105:UT-03
    def test_candidates_are_queue_topic_and_datastore_only(self):
        """SPEC-0105:UT-03 — gates.md (G6): as candidatas são só queue, topic e datastore (sem bucket)."""
        text = active_section()
        self.assertTrue(chunks_with(text, r"\bqueue\b", r"\btopic\b", r"\bdatastore\b", r"max_resources"),
                        "gates.md (G6): as dependências não são queue, topic e datastore")
        for chunk in chunks_with(text, r"\bbucket\b"):
            self.assertRegex(chunk, re.compile(r"(?:not|no|sem|never|nunca|except|exceto)[^.\n]*bucket", re.IGNORECASE),
                             "gates.md (G6): bucket entre as dependências candidatas")

    # SPEC-0105:UT-03
    def test_expect_migration_always_carries_the_datastore(self):
        """SPEC-0105:UT-03 — gates.md (G6): --expect-migration <datastore>=<id> para cada migration nova do diff,
        sempre com o datastore."""
        text = active_section()
        self.assertTrue(chunks_with(text, r"--expect-migration", r"migration", r"\bdiff\b"),
                        "gates.md (G6): --expect-migration não vem das migrations novas do diff")
        uses = re.findall(r"--expect-migration`?\s*`?\s*(\S+)", text)
        self.assertTrue(uses, "gates.md (G6): sem --expect-migration")
        for value in uses:
            if value.startswith("<"):
                with self.subTest(valor=value):
                    self.assertRegex(value, r"^<datastore>=<", "gates.md (G6): --expect-migration sem o datastore")

    # SPEC-0105:UT-03
    def test_no_resource_adapter_is_like_verify_1_and_not_inconclusive(self):
        """SPEC-0105:UT-03 — gates.md (G6): sem nenhum adaptador de recurso declarado, o escopo fica vazio, o verify
        fica como o verify@1 e o Relatório diz "dependências: sem adaptador de recurso nesta máquina", sem tratar
        como inconclusivo."""
        found = chunks_with(active_section(), re.escape(NO_ADAPTER_REPORT), r"verify@1")
        self.assertTrue(found, f"gates.md (G6): sem adaptador de recurso não fica como o verify@1 com "
                               f"{NO_ADAPTER_REPORT!r}")
        self.assertRegex("\n".join(found), re.compile(r"(?:not|não|never|nunca)[^.\n]*inconclusivo", re.IGNORECASE),
                         "gates.md (G6): sem adaptador de recurso não diz que não é inconclusivo")

    # SPEC-0105:UT-03
    def test_resource_without_access_is_not_verified_and_inconclusive(self):
        """SPEC-0105:UT-03 — gates.md (G6): com adaptador declarado e um recurso sem acesso local ou sem adaptador, o
        recurso fica not_verified e o veredito inconclusivo, registrado assim (a pessoa decide), com a sugestão de
        access setup ou de declarar o adaptador."""
        found = chunks_with(active_section(), r"not_verified", r"\binconclusivo\b", ACCESS_SETUP, DECLARE_ADAPTER)
        self.assertTrue(found, "gates.md (G6): recurso sem acesso ou sem adaptador sem not_verified, inconclusivo e "
                               "as sugestões")
        self.assertTrue([c for c in found if re.search(PERSON, c, re.IGNORECASE) and re.search(DECIDES, c)],
                        "gates.md (G6): recurso sem acesso não fica com a decisão da pessoa")

    # SPEC-0105:UT-03
    def test_dependency_limits_come_from_delivery_check(self):
        """SPEC-0105:UT-03 — gates.md (G6): --max-new-dlq, --max-queue-age e --max-signal-increase no compare, vindas
        de max_new_dlq, max_queue_age e max_signal_increase."""
        text = active_section()
        compare = [m.group(0) for m in re.finditer(r"verify compare\b[^\n]*", text)]
        for flag, key in (("--max-new-dlq", "max_new_dlq"), ("--max-queue-age", "max_queue_age"),
                          ("--max-signal-increase", "max_signal_increase")):
            with self.subTest(opcao=flag):
                self.assertTrue([c for c in compare if flag in c], f"gates.md (G6): verify compare sem {flag}")
                self.assertRegex(text, rf"{flag}\W+{key}\b", f"gates.md (G6): {flag} não vem de {key}")


class FunctionalTest(unittest.TestCase):
    # SPEC-0105:UT-04
    def test_functional_only_with_the_key_and_tier_test(self):
        """SPEC-0105:UT-04 — gates.md (G6): --functional só com delivery_check.functional: true e só em ambiente
        tier: test, pelo tier do deployment no pacote do context."""
        found = chunks_with(active_section(), r"--functional", r"delivery_check\.functional", TIER_TEST)
        self.assertTrue(found, "gates.md (G6): --functional sem delivery_check.functional e tier: test")
        self.assertTrue(chunks_with(active_section(), r"\btier\b", r"deployment", r"context"),
                        "gates.md (G6): o tier não vem do deployment no pacote do context")

    # SPEC-0105:UT-04
    def test_functional_never_in_production_nor_with_confirmation(self):
        """SPEC-0105:UT-04 — gates.md (G6): em produção, ou sem tier, --functional nunca vai, nem com
        --confirm-production."""
        found = [c for c in chunks_with(active_section(), r"--functional", r"never|nunca", r"--confirm-production")
                 if PRODUCTION.search(c)]
        self.assertTrue(found, "gates.md (G6): não diz que --functional nunca vai em produção, nem com "
                               "--confirm-production")
        self.assertRegex("\n".join(chunks_with(active_section(), r"--functional")),
                         re.compile(r"(?:without|no|sem)\s+`?tier|tier[^.\n]*(?:missing|absent|ausente)", re.IGNORECASE),
                         "gates.md (G6): não diz que sem tier também não vai --functional")

    # SPEC-0105:UT-04
    def test_journey_results_go_to_the_delivery_report(self):
        """SPEC-0105:UT-04 — gates.md (G6): o resultado das jornadas funcionais entra no Relatório de Entrega."""
        self.assertTrue(chunks_with(active_section(), r"journey|jornada", r"Relatório de Entrega"),
                        "gates.md (G6): o resultado das jornadas não vai para o Relatório de Entrega")


class ProductionAndReportTest(unittest.TestCase):
    # SPEC-0105:UT-05
    def test_production_confirms_each_run_including_each_track_retry(self):
        """SPEC-0105:UT-05 — gates.md (G6): em produção, o "sim" da pessoa para cada execução de snapshot, track e
        compare, inclusive cada repetição do track, sem um "sim" cobrir a repetição seguinte; só passiva."""
        text = active_section()
        confirmed = [c for c in chunks_with(text, r"--confirm-production", r"snapshot", r"track", r"compare", PER_RUN)
                     if PRODUCTION.search(c)]
        self.assertTrue(confirmed, "gates.md (G6): produção sem a confirmação por execução de snapshot, track e "
                                   "compare")
        retry = [c for c in chunks_with(text, r"track", REPEAT, YES) if PRODUCTION.search(c)]
        self.assertTrue(retry, "gates.md (G6): cada repetição do track em produção não pede um sim novo")
        self.assertTrue([c for c in retry if re.search(r"(?:never|nunca|não|not|doesn't|does not)[^.\n]*"
                                                       r"(?:cover|cobre|reus|reaproveit)", c, re.IGNORECASE)],
                        "gates.md (G6): não diz que um sim não cobre a repetição seguinte do track")
        self.assertIn("sem confirmação de produção", text,
                      "gates.md (G6): sem o sim, não registra 'entrega não acompanhada até o fim: sem confirmação de "
                      "produção'")
        self.assertTrue([c for c in chunks(text) if PRODUCTION.search(c) and re.search(r"passiv", c, re.IGNORECASE)],
                        "gates.md (G6): produção deixou de ser só passiva")

    # SPEC-0105:UT-05
    def test_delivery_report_line_per_service_and_environment(self):
        """SPEC-0105:UT-05 — gates.md (G6): a linha do Relatório de Entrega por serviço e ambiente, com o veredito, a
        origem da imagem (track ou roteiro), as etapas do track, as verificações e "dependências: N verificadas, M
        não verificadas"."""
        found = chunks_with(active_section(), r"Relatório de Entrega", r"verdict|veredito",
                            r"expected_image_source|origem|source", r"stages|etapas",
                            r"dependências: <?\w+>? verificadas, <?\w+>? não verificadas")
        self.assertTrue(found, "gates.md (G6): sem a linha do Relatório de Entrega com veredito, origem da imagem, "
                               "etapas e a contagem de dependências")
        self.assertRegex("\n".join(found), re.compile(r"service|serviço", re.IGNORECASE))
        self.assertRegex("\n".join(found), re.compile(r"environment|ambiente", re.IGNORECASE))

    # SPEC-0105:UT-05
    def test_dependency_not_verified_for_access_is_recorded_without_blocking(self):
        """SPEC-0105:UT-05 — gates.md (G6): dependência not_verified por falta de acesso ou adaptador → registrada
        com o motivo e a sugestão de access setup ou de declarar o adaptador, sem bloquear o G6."""
        found = chunks_with(active_section(), r"not_verified", ACCESS_SETUP, DECLARE_ADAPTER, r"record|registr")
        self.assertTrue(found, "gates.md (G6): dependência sem acesso não é registrada com a sugestão")
        self.assertRegex("\n".join(found), NO_BLOCK, "gates.md (G6): dependência sem acesso bloqueia o G6")


class SkillPointerTest(unittest.TestCase):
    # SPEC-0105:UT-06
    def test_skill_step_7_has_one_clause_and_the_pointer(self):
        """SPEC-0105:UT-06 — a SKILL.md (passo 7) cita verify track, as dependências e delivery_check.functional numa
        só oração, no parágrafo da frase de delivery_check.verify, que aponta para references/gates.md (G6); as
        regras detalhadas não são repetidas."""
        text = step7()
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z`(])", text)
        found = [s for s in sentences if "verify track" in s and "delivery_check.functional" in s
                 and re.search(r"dependenc|dependênc", s, re.IGNORECASE)]
        self.assertTrue(found, "SKILL.md (passo 7): sem uma oração com verify track, as dependências e "
                               "delivery_check.functional")
        paragraph = next(p for p in re.split(r"\n\s*\n", text) if found[0].strip() in p)
        self.assertIn("delivery_check.verify", paragraph, "SKILL.md (passo 7): a oração fora do parágrafo de "
                                                          "delivery_check.verify")
        self.assertRegex(paragraph, re.compile(r"gates\.md`?\s*\(?G6"), "SKILL.md (passo 7): sem o ponteiro para o G6")
        for detail in ("--commit", "--resource", "--max-resources", "--functional", "--expect-migration",
                       "--max-new-dlq", "track_max_minutes", "max_resources", "current_stage", "expected_image",
                       NOT_TRACKED, NO_ADAPTER_REPORT, "exit 6"):
            self.assertNotIn(detail, text, f"SKILL.md (passo 7): repete a regra {detail!r} do gates.md")


class EpicCriterionIntegrationTest(unittest.TestCase):
    # SPEC-0105:IT-01
    def test_g6_describes_verify_2_functional_and_production_against_the_real_help(self):
        """SPEC-0105:IT-01 — o G6 descreve o verify@2 com as opções de dependências e sinais que existem no --help
        real de atlas.py verify snapshot/compare/track (rodados como processos), a validação funcional só com
        delivery_check.functional: true e tier: test (nunca em produção, nem com --confirm-production) e a
        confirmação de produção a cada execução de snapshot, track e compare."""
        snapshot, compare, track = help_flags("snapshot"), help_flags("compare"), help_flags("track")
        text = active_section()
        self.assertIn("verify@2", text, "gates.md (G6): não descreve o verify@2")
        for flag in DEPENDENCY_FLAGS + ("--functional",):
            with self.subTest(opcao=flag):
                self.assertIn(flag, text, f"gates.md (G6): sem {flag}")
                self.assertIn(flag, compare, f"atlas.py verify compare --help sem {flag}")
        for flag in ("--resource", "--max-resources"):
            self.assertIn(flag, snapshot, f"atlas.py verify snapshot --help sem {flag}")
        for flag in ("--service", "--env", "--commit", "--json"):
            self.assertIn(flag, track, f"atlas.py verify track --help sem {flag}")
        self.assertIn("--functional", compare)
        self.assertNotIn("--functional", snapshot | track, "--functional apareceu fora do compare")
        self.assertTrue(chunks_with(text, r"--functional", r"delivery_check\.functional", TIER_TEST),
                        "gates.md (G6): --functional sem delivery_check.functional e tier: test")
        self.assertTrue([c for c in chunks_with(text, r"--functional", r"never|nunca", r"--confirm-production")
                         if PRODUCTION.search(c)], "gates.md (G6): --functional não fica fora de produção")
        self.assertTrue([c for c in chunks_with(text, r"--confirm-production", r"snapshot", r"track", r"compare",
                                                PER_RUN) if PRODUCTION.search(c)],
                        "gates.md (G6): sem a confirmação de produção a cada execução de snapshot, track e compare")


class WhatsNewIntegrationTest(unittest.TestCase):
    # SPEC-0105:IT-02
    def test_whats_new_from_previous_version_shows_the_new_section(self):
        """SPEC-0105:IT-02 — o SDD_TOOL_VERSION sobe além de 2026.11.10, com a seção datada no CHANGELOG; num projeto
        temporário com tools/sdd em 2026.11.10 e o delivery_check da SPEC-0091, o spec_graph.py whats-new, rodado
        como processo, mostra a seção nova com o G6 do verify@2, o verify track, a validação funcional e as chaves
        novas de delivery_check (o projeto já tem delivery_check, então as chaves aparecem pela seção do
        CHANGELOG)."""
        version = sg.SDD_TOOL_VERSION
        self.assertGreater(version_tuple(version), version_tuple(PREVIOUS_VERSION),
                           f"spec_graph.py: SDD_TOOL_VERSION ({version}) não subiu além de {PREVIOUS_VERSION}")
        self.assertIn("SPEC-0105", changelog_section(version), f"CHANGELOG [{version}]: sem a entrada da SPEC-0105")
        tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        config = ("delivery_check:\n  enabled: true\n  environments: []\n  verify: true\n  window_minutes: 10\n"
                  "  max_new_errors: 0\n  max_new_restarts: 0\n")
        project = Project(tmp / "projeto", config_extra=config)
        vendor_tool(project.root, PREVIOUS_VERSION)
        res = project.run("whats-new", env=isolated_env(tmp))
        out = res.stdout + res.stderr
        self.assertEqual(res.returncode, 0, out)
        self.assertIn(f"Novidades desde {PREVIOUS_VERSION}:", res.stdout, out)
        header = re.search(rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", res.stdout, re.MULTILINE)
        self.assertTrue(header, f"whats-new: sem a seção [{version}]:\n{out}")
        body = res.stdout[header.end():]
        nxt = re.search(r"^## ", body, re.MULTILINE)
        body = body[:nxt.start()] if nxt else body
        for fragment in ("SPEC-0105", "verify@2", "verify track", "functional"):
            self.assertIn(fragment, body, f"whats-new [{version}]: sem {fragment!r}:\n{out}")
        for key in NEW_KEYS:
            self.assertRegex(body, rf"\b{key}\b", f"whats-new [{version}]: sem a chave {key}:\n{out}")


class ContractTest(unittest.TestCase):
    # SPEC-0105:CT-01
    def test_cited_options_exist_in_snapshot_track_and_compare_help(self):
        """SPEC-0105:CT-01 — toda opção citada no G6 existe no --help real de atlas.py verify snapshot, track ou
        compare, e as citadas logo depois de cada subcomando existem no help dele (o verify track inclusive)."""
        helps = {sub: help_flags(sub) for sub in ("snapshot", "track", "compare")}
        text = active_section()
        self.assertIn("verify track", text, "gates.md (G6): sem o verify track")
        unknown = set(FLAG.findall(text)) - set().union(*helps.values())
        self.assertFalse(unknown, f"gates.md (G6): opções fora do atlas.py verify: {sorted(unknown)}")
        for sub, flags in helps.items():
            for match in re.finditer(rf"verify {sub}\b([^`\n]*)", text):
                extra = set(FLAG.findall(match.group(1))) - flags
                with self.subTest(subcomando=sub, trecho=match.group(0)):
                    self.assertFalse(extra, f"gates.md (G6): verify {sub} não tem {sorted(extra)}")

    # SPEC-0105:CT-01
    def test_track_contract_states_exits_and_stages_match_verify_md(self):
        """SPEC-0105:CT-01 — o contrato track@1, as chaves state, current_stage e expected_image, os estados
        (pending, running, ok, failed, not_verified) e os exits (0, 1, 5, 6 e os outros 2, 3, 4) citados no G6 são
        os do verify.md da boson-atlas, que tem as etapas pipeline, image, gitops e rollout (o G6 não cita outra); o
        track não repete sozinho, então quem repete (o G6) põe o limite."""
        reference = track_section_of_verify_md()
        table = track_exit_table()
        self.assertEqual(table, {"failed": "1", "running": "6", "pending": "6", "not_verified": "5", "ok": "0"},
                         "verify.md mudou os estados ou exits do verify track que a SPEC-0105 consome")
        self.assertRegex(reference, r"Outros exits: 2[^\n]*3[^\n]*4", "verify.md: o track sem os exits 2, 3 e 4")
        self.assertRegex(reference, r"não espera nem repete", "verify.md: o track passou a repetir sozinho")
        for name in ("track@1", "state", "current_stage", "expected_image", "expected_image_source") + TRACK_STAGES:
            self.assertIn(f"`{name}`", reference, f"verify.md: o track sem {name!r}")
        text = active_section()
        for name in ("track@1", "state", "current_stage", "expected_image"):
            with self.subTest(chave=name):
                self.assertIn(name, text, f"gates.md (G6): sem {name!r} do track@1")
        for state in TRACK_STATES:
            with self.subTest(estado=state):
                self.assertRegex(text, rf"`{state}`", f"gates.md (G6): sem o estado {state!r} do track")
        cited = re.findall(r"`(ok|failed|running|pending|not_verified)`[^`\n]{0,40}?\((?:exit\s*)?(\d)\)", text)
        self.assertTrue(cited, "gates.md (G6): nenhum estado do track com o exit")
        for state, code in cited:
            with self.subTest(estado=state, exit=code):
                self.assertEqual(code, table[state], f"gates.md (G6): {state} citado com o exit {code}, não "
                                                     f"{table[state]}")
        stages = "\n".join(chunks_with(text, r"track", r"\bstages?\b|etapas?"))
        self.assertTrue(stages, "gates.md (G6): o track sem as etapas")
        for wrong in ("build", "deploy", "sync", "release"):
            self.assertNotRegex(stages, rf"`{wrong}`", f"gates.md (G6): etapa {wrong!r} fora do track@1")


if __name__ == "__main__":
    unittest.main()
