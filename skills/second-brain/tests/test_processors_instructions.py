"""Guia dos processadores: references/processors.md (SPEC-0022:UT-05).

O que o contrato exige que esteja escrito (as checagens aceitam português ou inglês):

    references/processors.md
        uma seção ("## " ou "### ") por modelo, cujo título cita o tipo ou a ferramenta:
          youtube        -> yt-dlp, só as legendas, sem baixar o vídeo (--skip-download)
          video ou audio -> Whisper (saída txt ou vtt)
          pdf            -> pdftotext
        cada seção com a linha do modelo (o `command:` com o marcador {input}), a versão da ferramenta
        (ex.: 2025.10.22, 20250625, 24.02.0) e a data da conferência contra o --help em AAAA-MM-DD;
        o aviso de que o yt-dlp acessa a rede; e como trocar por outra ferramenta (ex.: whisper.cpp).
"""
import re
import unittest

from brain_support import SKILL

PROCESSORS_MD = SKILL / "references" / "processors.md"
HEADING = re.compile(r"^(#{2,3})[ \t]+(.+?)[ \t#]*$", re.MULTILINE)
VERSION = re.compile(r"\b(?:v(?:ers[ãa]o|ersion)?\s*:?\s*)?\d+(?:\.\d+)+\b|\b(?:vers[ãa]o|version)\s*:?\s*\d{6,8}\b",
                     re.IGNORECASE)
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
MODELS = (
    ("youtube", r"youtube|yt-dlp", r"yt-dlp", r"--skip-download"),
    ("video ou audio", r"v[íi]deo|[áa]udio|whisper", r"whisper", None),
    ("pdf", r"\bpdf|pdftotext", r"pdftotext", None),
)


def sections(text):
    """(título, corpo) de cada seção "## " ou "### "; o corpo vai até o próximo título."""
    marks = list(HEADING.finditer(text))
    return [(m.group(2), text[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(text)])
            for i, m in enumerate(marks)]


class ProcessorsGuideTest(unittest.TestCase):
    def setUp(self):
        if not PROCESSORS_MD.is_file():
            self.fail(f"{PROCESSORS_MD} não existe (SPEC-0022)")
        self.text = PROCESSORS_MD.read_text(encoding="utf-8")

    def test_three_models_each_with_command_version_and_check_date(self):
        """SPEC-0022:UT-05"""
        found = sections(self.text)
        for kind, title, tool, flag in MODELS:
            with self.subTest(kind):
                matching = [(t, body) for t, body in found
                            if re.search(title, t, re.IGNORECASE) and re.search(tool, body, re.IGNORECASE)]
                self.assertTrue(matching, f"sem seção do modelo {kind} ({tool}) em processors.md")
                _, body = matching[0]
                self.assertRegex(body, r"command:.*\{input\}", f"{kind}: sem linha command: com {{input}}")
                self.assertRegex(body, VERSION, f"{kind}: sem a versão da ferramenta")
                self.assertRegex(body, DATE, f"{kind}: sem a data da conferência (AAAA-MM-DD)")
                if flag:
                    self.assertIn(flag, body, f"{kind}: o modelo baixa só as legendas ({flag})")

    def test_network_warning_for_yt_dlp_and_how_to_swap_tools(self):
        """SPEC-0022:UT-05"""
        paragraphs = re.split(r"\n\s*\n", self.text)
        self.assertTrue(any(re.search(r"yt-dlp", p, re.IGNORECASE)
                            and re.search(r"\brede\b|network|internet", p, re.IGNORECASE) for p in paragraphs),
                        "falta o aviso de que o yt-dlp acessa a rede")
        self.assertIn("whisper.cpp", self.text, "falta como trocar por outra ferramenta (ex.: whisper.cpp)")


if __name__ == "__main__":
    unittest.main()
