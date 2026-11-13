"""Regressões da revisão G4 da SPEC-0027 (CHANGES_REQUESTED): UT-01, UT-03, IT-01, IT-02 e IT-03.

Decisões do Architect que estes testes fixam:

1. (major, UT-01/IT-01) Um grupo com uma repetição dentro que é ele mesmo seguido de `{n}` ou `{n,m}` com n >= 2
   (além de `+`, `*` e `{n,}`) conta como aninhado e é recusado: `(?P<base>(a+){20})b\\.md$`,
   `(?P<base>(.*a){20})b\\.md$`; `(x){2}` e `(?:ab){3}` (sem repetição dentro) continuam aceitos. lint e doctor
   com `(a+){20}` terminam em menos de 3 s (o subprocesso tem um limite de GUARD s para o teste nunca travar).
2. (UT-01, docs) references/config.md, providers.md e maintenance.md dizem que a verificação é de melhor esforço
   (alternativas sobrepostas como `(a|aa)+` não são detectadas) e recomendam padrões simples.
3. (IT-02) A limpeza da exportação vale também para interrupção: um KeyboardInterrupt na 3ª escrita (a mesma troca
   de open() do teste de IT-02 em test_notebooklm_review.py) não deixa nenhuma pasta oculta `.<out>.brain-*` ao lado
   de --out, e --out fica sem arquivos exportados.
4. (IT-02, ADR-0007) `--out` com caixa diferente do caminho do vault (vault .../Drive/Vault, --out
   .../DRIVE/VAULT/out) é recusado com exit 2 e nada é escrito dentro do vault — só em sistemas de arquivos que não
   diferenciam maiúsculas (detectado pela existência do caminho em maiúsculas; senão o teste é pulado).
5. (IT-03, docs) A linha de `orphan` em references/maintenance.md concorda com o SKILL.md (o `index` só resolve a
   nota que tem contexto; sem contexto, `relate` ou uma nota nova), e a sugestão do achado orphan no `lint --json`
   também cita o contexto.
6. (UT-03) flatten_links preserva o código inline delimitado por sequências de crases de qualquer tamanho:
   ``[[x]]`` fica como está.
"""
import glob
import json
import os
import re
import subprocess
import sys
import unittest

import test_notebooklm_review as export_review
from brain_support import SCRIPT, SKILL, fn, output, snapshot
from test_lint_cli import LintCliTestCase, note_text
from test_lint_review import GUARD, LIMIT, run_guarded
from test_notebooklm_review import WRAPPER
from test_store_cli import StoreCliTestCase

SPEC = "SPEC-0027"
REPEATED_NESTED = (r"(?P<base>(a+){20})b\.md$", r"(?P<base>(.*a){20})b\.md$", r"(?P<base>(?:a+){2})b\.md$",
                   r"(?P<base>(a*){2,5})b\.md$", r"(?P<base>(\w+\s?){3})x\.md$")
REPEATED_SAFE = (r"(?P<base>(x){2})y\.md$", r"(?P<base>(?:ab){3})c\.md$", r"(?P<base>.+) \(\d{1,3}\)\.md$")
CATASTROPHIC_COUNT = r"(?P<base>(a+){20})b\.md$"
REFERENCES = SKILL / "references"
PATTERN_DOCS = (REFERENCES / "config.md", REFERENCES / "providers.md", REFERENCES / "maintenance.md")
MAINTENANCE_MD = REFERENCES / "maintenance.md"
FAIL_LINE = 'raise OSError(errno.ENOSPC, "falha simulada na escrita", full)'
INTERRUPT_WRAPPER = WRAPPER.replace(FAIL_LINE, "raise KeyboardInterrupt")


class RepeatedGroupPatternTest(unittest.TestCase):
    def compile(self, patterns):
        compiled, problems = fn("compile_conflict_patterns", "SPEC-0023")(list(patterns))
        return compiled, problems

    def test_a_group_with_a_repeat_inside_followed_by_a_count_is_refused(self):
        """SPEC-0027:UT-01"""
        for pattern in REPEATED_NESTED:
            with self.subTest(pattern=pattern):
                compiled, problems = self.compile([pattern])
                self.assertEqual(compiled, [], "grupo com repetição dentro, repetido por {n}, é aninhado")
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("conflict_patterns", problems[0])

    def test_a_counted_group_without_a_repeat_inside_is_still_accepted(self):
        """SPEC-0027:UT-01"""
        compiled, problems = self.compile(REPEATED_SAFE)
        self.assertEqual(problems, [], "(x){2} e (?:ab){3} não têm repetição dentro do grupo")
        self.assertEqual(len(compiled), len(REPEATED_SAFE))


class PatternDocsTest(unittest.TestCase):
    def test_docs_say_the_check_is_best_effort_and_advise_simple_patterns(self):
        """SPEC-0027:UT-01 — texto de references/config.md, providers.md e maintenance.md"""
        for path in PATTERN_DOCS:
            with self.subTest(doc=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertTrue(re.search(r"(?i)melhor esforço|best[- ]effort", text),
                                f"{path} deve dizer que a verificação dos padrões é de melhor esforço")
                self.assertTrue("(a|aa)+" in text, f"{path} deve citar alternativas sobrepostas como (a|aa)+")
                self.assertTrue(re.search(r"(?i)padr(ão|ões) simples", text), f"{path} deve recomendar padrões simples")


class FlattenInlineCodeTest(unittest.TestCase):
    def test_inline_code_with_backtick_runs_of_any_length_is_kept(self):
        """SPEC-0027:UT-03"""
        flatten_links = fn("flatten_links", "SPEC-0024")
        for text in ("``[[x]]``", "Veja ``[[x]]`` e [[Nota]].", "``a ` [[y]]`` e [[Nota]]"):
            with self.subTest(text=text):
                expected = text.replace("[[Nota]]", "Nota")
                self.assertEqual(flatten_links(text), expected, "código inline com `` fica como está")


class RepeatedGroupCliTest(LintCliTestCase):
    def counted_vault(self):
        self.make_vault()
        self.add_config(f"conflict_patterns:\n  - '{CATASTROPHIC_COUNT}'\n")
        name = "a" * 40
        self.put(f"projects/college/{name}.md", note_text(name, "Ver [[college]]."))

    def test_lint_refuses_the_counted_nested_pattern_in_under_3_seconds(self):
        """SPEC-0027:IT-01"""
        self.counted_vault()
        out, elapsed = run_guarded(self.box, "lint", "--json")
        self.assertLess(elapsed, LIMIT, f"lint levou {elapsed:.2f} s (limite do teste {GUARD} s)")
        self.assertExit(out, 1)
        config = [item for item in json.loads(out.stdout)["findings"] if item["rule"] == "config"]
        self.assertTrue(any("conflict_patterns" in item["detail"] + item["suggestion"] for item in config), config)

    def test_doctor_refuses_the_counted_nested_pattern_in_under_3_seconds(self):
        """SPEC-0027:IT-01"""
        self.counted_vault()
        out, elapsed = run_guarded(self.box, "doctor")
        self.assertLess(elapsed, LIMIT, f"doctor levou {elapsed:.2f} s (limite do teste {GUARD} s)")
        self.assertExit(out, 1)


class OrphanContextTest(LintCliTestCase):
    def test_orphan_suggestion_mentions_the_context(self):
        """SPEC-0027:IT-03"""
        self.make_vault()
        self.put("projects/college/Solta.md", note_text("Solta", "Nota sem nenhum link."))
        orphans = [item for item in self.lint_json()["findings"] if item["rule"] == "orphan"]
        self.assertEqual([item["path"] for item in orphans], ["projects/college/Solta.md"], orphans)
        self.assertRegex(orphans[0]["suggestion"], r"(?i)context",
                         "o `index` só põe no MOC a órfã que tem contexto")

    def test_maintenance_orphan_row_matches_skill_md(self):
        """SPEC-0027:IT-03 — texto de references/maintenance.md"""
        rows = [line for line in MAINTENANCE_MD.read_text(encoding="utf-8").splitlines()
                if line.startswith("| `orphan`")]
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("`index`", rows[0])
        self.assertRegex(rows[0], r"(?i)context", "o `index` só resolve a órfã que tem contexto")
        self.assertRegex(rows[0], r"`relate`.*nota nova|nota nova.*`relate`", "sem contexto: `relate` ou nota nova")


class ExportSafetyReviewTest(StoreCliTestCase):
    # os mesmos vault e listagem de test_notebooklm_review.py, sem herdar (e rodar de novo) os testes de lá
    build_vault = export_review.ExportReviewCliTest.build_vault
    entries = export_review.ExportReviewCliTest.entries

    def test_an_interruption_while_writing_leaves_no_staging_folder(self):
        """SPEC-0027:IT-02"""
        self.assertNotEqual(INTERRUPT_WRAPPER, WRAPPER, "a troca de open() mudou: atualize FAIL_LINE")
        self.build_vault()
        before = snapshot(self.box.vault)
        for existing in (True, False):
            with self.subTest(out_exists=existing):
                out = self.box.root / f"interrompido-{existing}"
                if existing:
                    out.mkdir()
                failed = self.run_interrupted("export-notebooklm", "college", "--out", out, "--combined")
                self.assertNotEqual(failed.returncode, 0, output(failed))
                self.assertIn("KeyboardInterrupt", output(failed), "a interrupção simulada aconteceu na escrita")
                staging = glob.glob(glob.escape(str(out.parent / f".{out.name}.brain-")) + "*")
                self.assertEqual(staging, [], "interrupção: nenhuma pasta temporária fica ao lado de --out")
                self.assertEqual(self.entries(out), [], "interrupção: nada fica em --out")
        self.assertEqual(snapshot(self.box.vault), before, "o vault não muda")

    def run_interrupted(self, *args):
        """O WRAPPER de IT-02 com KeyboardInterrupt (em vez de OSError) na 3ª escrita."""
        env = dict(os.environ, HOME=str(self.box.home), BRAIN_CONFIG_HOME=str(self.box.config_home))
        argv = [sys.executable, "-c", INTERRUPT_WRAPPER, self.box.root, 3, SCRIPT, self.box.vault,
                self.box.config_home, *args]
        return subprocess.run([str(a) for a in argv], check=False, cwd=self.box.root, capture_output=True,
                              text=True, env=env, timeout=60)

    def test_out_inside_the_vault_with_another_case_is_refused(self):
        """SPEC-0027:IT-02 (ADR-0007)"""
        self.build_vault()
        vault = self.box.vault
        upper = vault.parent.parent / vault.parent.name.upper() / vault.name.upper()
        if upper == vault or not upper.exists():
            self.skipTest("sistema de arquivos diferencia maiúsculas")
        before = snapshot(vault)
        result = self.box.run("export-notebooklm", "college", "--out", upper / "out")
        self.assertExit(result, 2)
        self.assertRegex(output(result), r"(?i)dentro do vault")
        self.assertEqual(snapshot(vault), before, "nada é escrito dentro do vault")
        self.assertFalse(re.search(r"\.brain-", " ".join(p.name for p in vault.iterdir())))


if __name__ == "__main__":
    unittest.main()
