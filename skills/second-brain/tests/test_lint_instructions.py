"""Instruções da manutenção: fluxo do lint no SKILL.md e os padrões de conflito em references/providers.md
(SPEC-0023:UT-05).

O que o contrato exige que esteja escrito (as checagens aceitam português ou inglês):

    SKILL.md
        uma seção ("## " ou "### ") cujo título fala de manutenção (manutenção/maintenance/lint) que diz quando
        rodar (o usuário pede, o `doctor` mostra achados, depois de processar a inbox) e tem uma lista numerada
        de exatamente quatro passos, nesta ordem:
          1. `lint`
          2. explicar os achados por severidade
          3. propor uma correção por achado (`relate`, `index`, nota nova, ou orientar a comparar os conflitos)
          4. aplicar só com o sim do usuário
        e a regra de nunca apagar arquivo, na mesma seção.

    references/providers.md
        para cada provedor da v1 — Google Drive, OneDrive, iCloud e pasta local — ao menos um padrão de cópia de
        conflito: um regex com o grupo "base" (`(?P<base>...)`) que compila, numa seção do provedor ou numa linha
        (tabela, lista) que cita o provedor dentro de uma seção de conflitos; e a data da conferência
        (AAAA-MM-DD) junto do padrão ou na seção de conflitos que cita o provedor.
"""
import re
import unittest

from brain_support import SKILL

SKILL_MD = SKILL / "SKILL.md"
PROVIDERS_MD = SKILL / "references" / "providers.md"
STEPS = (
    (r"\blint\b",),
    (r"explic|explain", r"severidade|severity"),
    (r"propo|suggest", r"\brelate\b", r"\bindex\b", r"conflit|conflict"),
    (r"\bsim\b|\byes\b|confirm|aprova|approv", r"usuári|pessoa|user"),
)
WHEN = (r"\bdoctor\b", r"\binbox\b")
NEVER_DELETE = r"nunca apag|never delet|não apag|nada é apagado|nunca remov|never remov"
PROVIDERS = {
    "google-drive": r"google[ -]drive",
    "onedrive": r"onedrive",
    "icloud": r"icloud",
    "local": r"pasta local|local folder|`local`",
}
CONFLICT_TITLE = r"conflit|conflict"
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
BASE_GROUP = "(?P<base>"


def read(path):
    if not path.exists():
        raise AssertionError(f"{path} não existe (SPEC-0023)")
    return path.read_text(encoding="utf-8")


def sections(text, title_re):
    """Corpos (com os subtítulos) das seções '## '/'### ' cujo título casa com title_re; o título vai junto."""
    lines, found = text.splitlines(), []
    for i, line in enumerate(lines):
        m = re.match(r"^(#{2,3}) (.*)$", line)
        if not m or not re.search(rf"(?i){title_re}", m.group(2)):
            continue
        level, body = len(m.group(1)), [line]
        for nxt in lines[i + 1:]:
            h = re.match(r"^(#{1,6}) ", nxt)
            if h and len(h.group(1)) <= level:
                break
            body.append(nxt)
        found.append("\n".join(body))
    return found


def numbered_steps(section):
    steps = []
    for line in section.splitlines():
        m = re.match(r"^(\d+)\.\s+(.*)$", line)
        if m:
            steps.append([int(m.group(1)), m.group(2)])
        elif steps and line.strip() and not re.match(r"^\S", line):
            steps[-1][1] += "\n" + line
    return [tuple(step) for step in steps]


def patterns_in(block):
    """Regex com o grupo base de um bloco: trechos `entre crases` e linhas de bloco de código."""
    found = [m for m in re.findall(r"`([^`\n]+)`", block) if BASE_GROUP in m]
    found += [line.strip().strip("'\"") for line in block.splitlines()
              if BASE_GROUP in line and "`" not in line]
    return found


def compiles_with_base(pattern):
    try:
        return "base" in re.compile(pattern).groupindex
    except re.error:
        return False


class MaintenanceInstructionsTest(unittest.TestCase):
    def maintenance_section(self):
        candidates = [s for s in sections(read(SKILL_MD), r"manuten|maintenance|\blint\b")
                      if re.search(r"(?m)^\d+\.\s", s)]
        self.assertTrue(candidates, "SKILL.md sem seção de manutenção com passos numerados")
        return candidates[0]

    def test_skill_md_has_the_four_maintenance_steps_in_order(self):
        """SPEC-0023:UT-05"""
        steps = numbered_steps(self.maintenance_section())
        self.assertEqual([n for n, _ in steps], [1, 2, 3, 4], steps)
        for (number, body), needles in zip(steps, STEPS):
            for needle in needles:
                with self.subTest(step=number, needle=needle):
                    self.assertRegex(body, rf"(?i){needle}", f"passo {number}")

    def test_skill_md_says_when_to_run_and_never_to_delete(self):
        """SPEC-0023:UT-05"""
        section = self.maintenance_section()
        for needle in WHEN:
            with self.subTest(when=needle):
                self.assertRegex(section, rf"(?i){needle}", "quando rodar o lint")
        self.assertRegex(section, rf"(?i){NEVER_DELETE}", "regra de nunca apagar arquivo")

    def test_providers_md_has_conflict_patterns_per_provider_with_the_check_date(self):
        """SPEC-0023:UT-05"""
        text = read(PROVIDERS_MD)
        conflict_sections = sections(text, CONFLICT_TITLE)
        for provider, name_re in PROVIDERS.items():
            with self.subTest(provider=provider):
                lines = [line for sec in conflict_sections for line in sec.splitlines()
                         if re.search(rf"(?i){name_re}", line)]
                blocks = [b for b in sections(text, name_re) + lines if patterns_in(b)]
                self.assertTrue(blocks, f"providers.md sem padrão de conflito (?P<base>...) para {provider}")
                patterns = [p for b in blocks for p in patterns_in(b)]
                self.assertTrue(any(compiles_with_base(p) for p in patterns),
                                f"{provider}: nenhum padrão compila com o grupo base: {patterns}")
                dated = any(DATE.search(b) for b in blocks) or any(
                    DATE.search(sec) and re.search(rf"(?i){name_re}", sec) for sec in conflict_sections)
                self.assertTrue(dated, f"{provider}: padrão de conflito sem a data da conferência")


if __name__ == "__main__":
    unittest.main()
