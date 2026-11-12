"""Regressões da revisão G4 da SPEC-0023 (lint) e do lint sobre arquivos ocultos (SPEC-0027: UT-01, UT-02, IT-01 e
IT-03, parte do lint e do SKILL.md).

O que estes testes fixam (seção 3 da spec; regras, severidades, formatos e códigos de saída da SPEC-0023 não mudam):

    GENERIC_CONFLICT_PATTERNS  o padrão de "conflict" ignora maiúsculas: "Plano Conflict.md" ao lado de "Plano.md" é
                               cópia de conflito.
    compile_conflict_patterns(value) -> (compilados, problemas)
                               padrão com quantificador aninhado ((…+)+, (…*)*, (…+)*, (…*)+, também com (?:…))
                               ou maior que o limite de tamanho fica fora dos compilados e vira um problema que cita
                               conflict_patterns; os padrões genéricos e os de CONFLICT_PATTERNS continuam aceitos.
    check_missing_file         item de files fora da pasta files ("../../x.pdf", "/etc/hosts") tem o detalhe "fora da
                               pasta files"; um item ausente dentro dela continua "não existe na pasta files".
    lint --only ""             exit 2 e "nenhuma regra em --only".
    lint e doctor              com o padrão catastrófico no brain-config.yml e uma nota de 40 caracteres, terminam em
                               menos de 3 s com o achado config (o subprocesso tem um limite de GUARD s para o teste
                               nunca travar).
    lint                       .md oculto (nome começando com ".") não é nota: nenhum achado o cita.
    SKILL.md                   a sugestão para a órfã diz que o `index` só resolve a nota que tem contexto.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from brain_support import SCRIPT, SKILL, brain, doctor_lines, fn, output
from test_lint import findings, parse
from test_lint import note_text as unit_note
from test_lint_cli import LintCliTestCase, note_text

SPEC = "SPEC-0027"
CATASTROPHIC = r"(?P<base>(a+)+)b\.md$"
NESTED = (CATASTROPHIC, r"(?P<base>(a*)*)b\.md$", r"(?P<base>(a+)*)b\.md$", r"(?P<base>(a*)+)b\.md$",
          r"(?P<base>(?:a+)+)b\.md$", r"(?P<base>(\w+\s?)+)x\.md$")
TOO_LONG = r"(?P<base>.+)" + "x" * 5000 + r"\.md$"
LIMIT = 3.0  # segundos (spec, IT-01)
GUARD = 10  # segundos: o subprocesso é morto depois disso, para o teste nunca travar
SKILL_MD = SKILL / "SKILL.md"


def run_guarded(box, *args):
    """(resultado, segundos) de `brain.py args` no sandbox, com timeout; estourar o GUARD é falha, não espera."""
    env = dict(os.environ, HOME=str(box.home), BRAIN_CONFIG_HOME=str(box.config_home))
    start = time.monotonic()
    try:
        result = subprocess.run([sys.executable, str(SCRIPT), *[str(a) for a in args]], check=False, cwd=box.root,
                                capture_output=True, text=True, env=env, timeout=GUARD)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"brain.py {' '.join(map(str, args))} não terminou em {GUARD} s "
                             "(padrão catastrófico não foi recusado)") from None
    return result, time.monotonic() - start


class ConflictPatternsReviewTest(unittest.TestCase):
    def compile(self, patterns):
        result = fn("compile_conflict_patterns", "SPEC-0023")(list(patterns))
        self.assertIsInstance(result, tuple, result)
        compiled, problems = result
        return compiled, problems

    def test_nested_quantifiers_and_too_long_patterns_are_refused_without_matching(self):
        """SPEC-0027:UT-01"""
        for pattern in NESTED + (TOO_LONG,):
            with self.subTest(pattern=pattern[:40]):
                compiled, problems = self.compile([pattern])
                self.assertEqual(compiled, [], "padrão perigoso não pode ser usado para casar nomes")
                self.assertEqual(len(problems), 1, problems)
                self.assertIn("conflict_patterns", problems[0])

    def test_safe_patterns_are_still_accepted(self):
        """SPEC-0027:UT-01"""
        safe = sorted({pattern for patterns in brain().CONFLICT_PATTERNS.values() for pattern in patterns}
                      | set(brain().GENERIC_CONFLICT_PATTERNS))
        compiled, problems = self.compile(safe)
        self.assertEqual(problems, [], "os padrões genéricos e os de cada provedor não são recusados")
        self.assertEqual(len(compiled), len(safe))
        compiled, problems = self.compile([CATASTROPHIC, r"(?P<base>.+) \(\d+\)\.md$"])
        self.assertEqual(len(compiled), 1, "um padrão recusado não derruba os outros")
        self.assertEqual(len(problems), 1, problems)

    def test_generic_conflict_pattern_ignores_case(self):
        """SPEC-0027:UT-01"""
        check = fn("check_conflict_copy", "SPEC-0023")
        paths = ["projects/college/Plano.md", "projects/college/Plano Conflict.md",
                 "projects/college/Aula.md", "projects/college/Aula_CONFLICT 2026-10-30.md"]
        found = findings(check(paths, list(brain().GENERIC_CONFLICT_PATTERNS)))
        self.assertEqual(sorted(item["path"] for item in found),
                         ["projects/college/Aula_CONFLICT 2026-10-30.md", "projects/college/Plano Conflict.md"],
                         found)


class MissingFileReviewTest(unittest.TestCase):
    def setUp(self):
        self.files = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.files, True)

    def test_a_path_outside_the_files_folder_says_so(self):
        """SPEC-0027:UT-02"""
        (self.files / "college").mkdir()
        notes = [
            parse("resources/Sobe.md", unit_note("Sobe", extra="files: [../../x.pdf]\n")),
            parse("resources/Absoluto.md", unit_note("Absoluto", extra="files: [/etc/hosts]\n")),
            parse("resources/Ausente.md", unit_note("Ausente", extra="files: [college/falta.pdf]\n")),
        ]
        found = {item["path"]: item for item in findings(fn("check_missing_file", "SPEC-0023")(notes, self.files))}
        self.assertEqual(sorted(found), ["resources/Absoluto.md", "resources/Ausente.md", "resources/Sobe.md"], found)
        for path, item in found.items():
            with self.subTest(path=path):
                self.assertEqual((item["rule"], item["severity"]), ("missing-file", "error"))
        self.assertIn("../../x.pdf", found["resources/Sobe.md"]["detail"])
        self.assertIn("fora da pasta files", found["resources/Sobe.md"]["detail"])
        self.assertIn("fora da pasta files", found["resources/Absoluto.md"]["detail"])
        self.assertIn("não existe na pasta files", found["resources/Ausente.md"]["detail"])
        self.assertNotIn("fora da pasta files", found["resources/Ausente.md"]["detail"])


class LintReviewCliTest(LintCliTestCase):
    def test_empty_only_exits_2_with_the_message(self):
        """SPEC-0027:IT-01"""
        self.make_vault()
        for value in ("", ",", " , "):
            with self.subTest(only=value):
                out = self.box.run("lint", "--only", value)
                self.assertExit(out, 2)
                self.assertIn("nenhuma regra em --only", output(out))
                self.assertNotIn("regra desconhecida:  —", output(out))

    def catastrophic_vault(self):
        self.make_vault()
        self.add_config(f"conflict_patterns:\n  - '{CATASTROPHIC}'\n")
        name = "a" * 40
        self.assertEqual(len(name), 40)
        self.put(f"projects/college/{name}.md", note_text(name, "Ver [[college]]."))

    def test_lint_refuses_the_catastrophic_pattern_in_under_3_seconds(self):
        """SPEC-0027:IT-01"""
        self.catastrophic_vault()
        out, elapsed = run_guarded(self.box, "lint", "--json")
        self.assertLess(elapsed, LIMIT, f"lint levou {elapsed:.2f} s")
        self.assertExit(out, 1)
        data = json.loads(out.stdout)
        config = [item for item in data["findings"] if item["rule"] == "config"]
        self.assertTrue(config, data["findings"])
        self.assertTrue(any("conflict_patterns" in item["detail"] + item["suggestion"] for item in config), config)

    def test_doctor_refuses_the_catastrophic_pattern_in_under_3_seconds(self):
        """SPEC-0027:IT-01"""
        self.catastrophic_vault()
        out, elapsed = run_guarded(self.box, "doctor")
        self.assertLess(elapsed, LIMIT, f"doctor levou {elapsed:.2f} s")
        self.assertExit(out, 1)
        rows = [row for row in doctor_lines(out.stdout) if row[1] == "lint"]
        self.assertEqual(len(rows), 1, out.stdout)
        self.assertEqual(rows[0][0], "ERRO", rows[0])
        self.assertRegex(rows[0][2], r"^[1-9]\d* erros?, ", "o achado config é um erro")

    def test_hidden_md_files_are_not_lint_notes(self):
        """SPEC-0027:IT-03"""
        self.make_vault()
        self.put(".oculta.md", "# Oculta\n\nSem links.\n")
        self.put("projects/college/.oculta.md", "---\ntitle: [\n---\n# Oculta\n\nVer [[Inexistente]].\n")
        self.put("projects/college/Visivel.md", note_text("Visivel", "Nota sem nenhum link."))
        data = self.lint_json()
        cited = [item for item in data["findings"] if ".oculta.md" in item["path"] + item["detail"]]
        self.assertEqual(cited, [], "o lint ignora .md ocultos, como a varredura da busca")
        self.assertEqual([item["path"] for item in data["findings"] if item["rule"] == "orphan"],
                         ["projects/college/Visivel.md"], "as notas visíveis continuam avaliadas")


class OrphanHintTest(unittest.TestCase):
    def test_skill_md_says_index_only_helps_orphans_with_a_context(self):
        """SPEC-0027:IT-03 — texto do SKILL.md"""
        text = SKILL_MD.read_text(encoding="utf-8")
        clauses = [m.group(0) for m in re.finditer(r"(?i)órfã[^;\n]*", text) if "`index`" in m.group(0)]
        self.assertTrue(clauses, "SKILL.md sem a sugestão de `index` para a órfã")
        for clause in clauses:
            with self.subTest(clause=clause):
                self.assertRegex(clause, r"(?i)context", "o `index` só põe no MOC a órfã que tem contexto")
                self.assertRegex(clause, r"`relate`|nota nova", "sem contexto: `relate` ou uma nota nova")


if __name__ == "__main__":
    unittest.main()
