"""Instruções da inbox: fluxo "processar a inbox" no SKILL.md e o guia references/mobile-capture.md (SPEC-0021:UT-04).

O que o contrato exige que esteja escrito (as checagens aceitam português ou inglês):

    SKILL.md
        uma seção ("## " ou "### ") cujo título fala da inbox com uma lista numerada de exatamente quatro passos,
        nesta ordem:
          1. `inbox list`
          2. para cada item, do mais antigo: fluxo de guardar; arquivo -> `ingest --move`; texto ou link -> nota
          3. item de texto ou link já guardado -> `inbox done ITEM --note <nota>`
          4. pular os itens `syncing` e avisar; reportar no fim

    references/mobile-capture.md
        uma seção ("## " ou "### ") por provedor da v1 — Google Drive, OneDrive, iCloud e pasta local — cada uma
        citando iOS e Android (no corpo ou em subtítulos) e a pasta inbox; e uma seção do Obsidian mobile que diz
        que a pasta padrão de notas novas é a inbox e em quais provedores o Obsidian mobile abre o vault
        (ADR-0008: iCloud recomendado no iOS; Google Drive e OneDrive não suportados oficialmente no iOS).
"""
import re
import unittest

from brain_support import SKILL

SKILL_MD = SKILL / "SKILL.md"
MOBILE_MD = SKILL / "references" / "mobile-capture.md"
STEPS = (
    (r"\binbox list\b",),
    (r"antig|oldest", r"guardar|store", r"ingest --move", r"nota|note"),
    (r"\binbox done\b", r"--note"),
    (r"\bsyncing\b", r"report"),
)
PROVIDERS = {
    "google-drive": r"google[ -]drive",
    "onedrive": r"onedrive",
    "icloud": r"icloud",
    "local": r"pasta local|local folder|\blocal\b",
}


def read(path):
    if not path.exists():
        raise AssertionError(f"{path} não existe (SPEC-0021)")
    return path.read_text(encoding="utf-8")


def sections(text, title_re):
    """Corpos (com os subtítulos) das seções '## '/'### ' cujo título casa com title_re."""
    lines, found = text.splitlines(), []
    for i, line in enumerate(lines):
        m = re.match(r"^(#{2,3}) (.*)$", line)
        if not m or not re.search(rf"(?i){title_re}", m.group(2)):
            continue
        level, body = len(m.group(1)), []
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


class InboxInstructionsTest(unittest.TestCase):
    def test_skill_md_has_the_four_inbox_steps_in_order(self):
        """SPEC-0021:UT-04"""
        candidates = [s for s in sections(read(SKILL_MD), r"inbox") if re.search(r"(?m)^\d+\.\s", s)]
        self.assertTrue(candidates, "SKILL.md sem seção da inbox com passos numerados")
        steps = numbered_steps(candidates[0])
        self.assertEqual([n for n, _ in steps], [1, 2, 3, 4], steps)
        for (number, body), needles in zip(steps, STEPS):
            for needle in needles:
                with self.subTest(step=number, needle=needle):
                    self.assertRegex(body, rf"(?i){needle}", f"passo {number}")

    def test_mobile_capture_has_a_section_per_provider_with_ios_and_android(self):
        """SPEC-0021:UT-04"""
        text = read(MOBILE_MD)
        for provider, title in PROVIDERS.items():
            with self.subTest(provider=provider):
                bodies = [s for s in sections(text, title)
                          if re.search(r"\biOS\b", s) and re.search(r"(?i)\bandroid\b", s)]
                self.assertTrue(bodies, f"mobile-capture.md sem seção de {provider} com iOS e Android")
                self.assertTrue(any(re.search(r"\binbox\b", s) for s in bodies), f"{provider}: pasta inbox")

    def test_mobile_capture_has_the_obsidian_mobile_section(self):
        """SPEC-0021:UT-04"""
        bodies = sections(read(MOBILE_MD), r"obsidian")
        self.assertTrue(bodies, "mobile-capture.md sem seção do Obsidian mobile")
        body = "\n".join(bodies)
        self.assertRegex(body, r"\binbox\b")
        self.assertRegex(body, r"(?i)notas? novas?|new notes?", "pasta padrão de notas novas")
        self.assertRegex(body, r"(?i)icloud", "em quais provedores o Obsidian mobile abre o vault")
        self.assertRegex(body, r"\biOS\b")
        self.assertRegex(body, r"(?i)\bandroid\b")


if __name__ == "__main__":
    unittest.main()
