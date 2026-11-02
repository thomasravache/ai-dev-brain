"""Instruções do modo "só conector": SKILL.md, references/connectors.md e references/mobile-capture.md
(SPEC-0044:UT-03; ADR-0013).

O que o contrato exige que esteja escrito (as checagens aceitam português ou inglês):

    SKILL.md
        uma seção ("## " ou "### ") cujo título fala do conector (conector | connector) que:
          - nomeia o modo "só conector" (ou "connector-only") e aponta para references/connectors.md;
          - captura: monta com `capture --print` e só cria arquivo novo na inbox pelo conector; nunca edita, move
            ou apaga arquivo do vault pelo conector (nem sobrescreve);
          - consulta: só leitura, cita [[nota]] e avisa que a resposta é parcial;
          - qualquer outra escrita: recusar e explicar que é feita no computador.

    references/connectors.md
        o modo e as regras; o formato da nota de captura (nome AAAA-MM-DD-HHMMSS-<slug>.md e frontmatter
        type: capture e created); como achar o conector de cada provedor, com o Google Drive conferido numa data
        AAAA-MM-DD e OneDrive e iCloud citados (com "não conferido" quando não houver data); os limites.

    references/mobile-capture.md
        cita o conector do provedor (conector | connector) e references/connectors.md.
"""
import re
import unittest

from brain_support import SKILL
from test_inbox_instructions import SKILL_MD, sections

CONNECTORS_MD = SKILL / "references" / "connectors.md"
MOBILE_MD = SKILL / "references" / "mobile-capture.md"
DATE = r"\b\d{4}-\d{2}-\d{2}\b"

SKILL_RULES = {
    "nome do modo": r"só conector|so conector|connector[- ]only",
    "aponta para connectors.md": r"references/connectors\.md",
    "monta com capture --print": r"capture --print",
    "cria arquivo novo": r"(cri[ae]r?|create)[^\n]{0,40}(arquivo novo|novo arquivo|new file)",
    "só na inbox": r"\binbox\b",
    "nunca": r"\bnunca\b|\bnever\b",
    "editar": r"\bedit",
    "mover": r"\bmov(e|er)\b",
    "apagar": r"\bapag|\bdelet",
    "sobrescrever": r"sobrescrev|overwrit",
    "consulta só leitura": r"só leitura|so leitura|somente leitura|read[- ]only",
    "cita [[nota]]": r"\[\[nota\]\]|\[\[note\]\]",
    "avisa que é parcial": r"parcial|partial",
    "recusa outras escritas": r"recus|refuse",
    "feito no computador": r"computador|computer",
}


def read(path):
    if not path.exists():
        raise AssertionError(f"{path} não existe (SPEC-0044)")
    return path.read_text(encoding="utf-8")


def connector_sections(text):
    return sections(text, r"conector|connector")


class ConnectorInstructionsTest(unittest.TestCase):
    def test_skill_md_has_the_connector_only_mode_with_its_rules(self):
        """SPEC-0044:UT-03"""
        bodies = connector_sections(read(SKILL_MD))
        self.assertTrue(bodies, "SKILL.md sem seção do modo só conector")
        body = "\n".join(bodies)
        for rule, pattern in SKILL_RULES.items():
            with self.subTest(rule=rule):
                self.assertRegex(body, rf"(?i){pattern}", f"SKILL.md, modo só conector: {rule}")

    def test_connectors_md_has_the_mode_the_capture_format_and_the_providers(self):
        """SPEC-0044:UT-03"""
        text = read(CONNECTORS_MD)
        for rule in ("nome do modo", "monta com capture --print", "cria arquivo novo", "nunca",
                     "consulta só leitura", "cita [[nota]]", "avisa que é parcial", "recusa outras escritas"):
            with self.subTest(rule=rule):
                self.assertRegex(text, rf"(?i){SKILL_RULES[rule]}", f"connectors.md: {rule}")
        self.assertIn("AAAA-MM-DD-HHMMSS-", text, "nome da nota de captura")
        self.assertRegex(text, r"type: capture", "frontmatter da captura")
        self.assertRegex(text, r"\bcreated\b", "frontmatter da captura")
        self.assertRegex(text, r"(?i)limit", "limites do modo")

        drive = [line for line in text.splitlines() if re.search(r"(?i)google[ -]drive", line)]
        self.assertTrue(drive, "connectors.md sem o Google Drive")
        self.assertTrue(any(re.search(DATE, line) for line in drive),
                        f"Google Drive sem data de conferência (AAAA-MM-DD): {drive}")
        for provider in (r"onedrive", r"icloud"):
            with self.subTest(provider=provider):
                self.assertRegex(text, rf"(?i){provider}")
        self.assertRegex(text, r"(?i)não conferido|nao conferido|not verified|unverified",
                         "provedores sem conferência marcados como não conferidos")

    def test_mobile_capture_mentions_the_connector(self):
        """SPEC-0044:UT-03"""
        text = read(MOBILE_MD)
        self.assertTrue(re.search(r"(?i)conector|connector", text), "mobile-capture.md não cita o conector")
        self.assertTrue(re.search(r"connectors\.md", text), "mobile-capture.md não aponta para connectors.md")


if __name__ == "__main__":
    unittest.main()
