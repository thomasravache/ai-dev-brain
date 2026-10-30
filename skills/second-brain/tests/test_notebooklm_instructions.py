"""Instruções da exportação para o NotebookLM: SKILL.md e references/notebooklm.md (SPEC-0024:UT-02).

O que o contrato exige que esteja escrito (as checagens aceitam português ou inglês):

    SKILL.md
        uma linha que cita o comando `export-notebooklm` e diz quando oferecer a exportação: ao estudar ou se
        preparar para uma prova ("me prepara para a prova" -> oferecer o pacote do MOC), e que aponta para
        references/notebooklm.md (na mesma linha ou no parágrafo de referências).

    references/notebooklm.md
        o passo a passo de envio (lista numerada com pelo menos três passos, um deles falando de enviar/subir/
        adicionar as fontes e citando o export-notebooklm);
        os formatos aceitos (Markdown/.md entre eles);
        os limites (algum número com unidade: MB, palavras/words, fontes/sources);
        a data da conferência (AAAA-MM-DD junto de "conferido"/"verificado"/"checked"/"verified").
"""
import re
import unittest

from brain_support import SKILL
from test_store_instructions import numbered_steps, read

SKILL_MD = SKILL / "SKILL.md"
GUIDE = SKILL / "references" / "notebooklm.md"
WHEN = r"(?i)prova|exame|exam\b|estud|study|revis"
UPLOAD = r"(?i)envi|sub[ai]|upload|adicion|add\b|import|carreg"
LIMIT = r"(?i)\d[\d.,]*\s*(?:MB|GB|mil\s+palavras|palavras|words|fontes|sources)\b"
CHECKED = r"(?i)(?:conferid|verificad|checked|verified)[^\n]{0,80}?\d{4}-\d{2}-\d{2}|\d{4}-\d{2}-\d{2}[^\n]{0,80}?(?:conferid|verificad|checked|verified)"


class NotebookLMInstructionsTest(unittest.TestCase):
    def test_skill_says_when_to_offer_the_export_and_the_guide_has_steps_formats_and_limits(self):
        """SPEC-0024:UT-02"""
        skill = read(SKILL_MD)
        lines = [line for line in skill.splitlines() if "export-notebooklm" in line]
        self.assertTrue(lines, "SKILL.md não cita o comando export-notebooklm (SPEC-0024)")
        self.assertTrue(any(re.search(WHEN, line) for line in lines),
                        f"SKILL.md não diz quando oferecer a exportação (ex.: prova): {lines}")
        self.assertIn("references/notebooklm.md", skill, "SKILL.md aponta para o guia do NotebookLM")

        if not GUIDE.exists():
            self.fail(f"{GUIDE} não existe (SPEC-0024)")
        guide = GUIDE.read_text(encoding="utf-8")
        steps = numbered_steps(guide)
        self.assertGreaterEqual(len(steps), 3, f"passo a passo de envio numerado: {steps}")
        self.assertTrue(any(re.search(UPLOAD, text) for _, text in steps), f"um passo fala de enviar: {steps}")
        self.assertTrue(any("export-notebooklm" in text for _, text in steps), f"um passo usa o comando: {steps}")
        self.assertRegex(guide, r"(?i)markdown|\.md\b", "formatos aceitos: Markdown entre eles")
        self.assertRegex(guide, r"(?i)formato|format", "seção ou frase sobre formatos aceitos")
        self.assertRegex(guide, r"(?i)limite|limit", "seção ou frase sobre limites")
        self.assertRegex(guide, LIMIT, "limites com número e unidade (MB, palavras, fontes)")
        self.assertRegex(guide, CHECKED, "data da conferência dos formatos e limites (AAAA-MM-DD)")


if __name__ == "__main__":
    unittest.main()
