"""Função pura do `append`: acrescentar uma seção (ou texto a uma seção existente) a uma nota (SPEC-0107: UT-01, UT-02, UT-07).

Contrato esperado de scripts/brain.py (seções 4 e 6 da spec), ao lado de `append_relation`:

    append_section(text: str, heading: str, addition: str) -> str
        Pura. `heading` é o título sem "## " ("Resumo").
        - com "## <heading>" na nota: `addition` entra no fim da seção (antes do próximo título de nível 1 ou 2,
          ou do fim do arquivo), depois do texto antigo e de uma linha em branco; "### " dentro da seção não a fecha.
        - sem a seção: "## <heading>\\n\\n<addition>\\n" entra logo antes de "## Relations"; sem "## Relations",
          no fim do texto.
        - o texto acrescentado termina com uma quebra de linha; o resto da nota nunca muda.

Validação do título e do arquivo, BOM/CRLF gravados e o log são conferidos pela CLI (test_append_cli).
"""
import re
import unittest

from brain_support import fn

SPEC = "SPEC-0107"

HEAD = "---\ntype: note\ntitle: \"Aula 1\"\ncreated: 2026-01-01\ntags: []\n---\n\n# Aula 1\n\n"
RELATIONS = "## Relations\n\n- [[Aula 2]] — continua\n"


def append_section(text, heading, addition):
    return fn("append_section", SPEC)(text, heading, addition)


class NewSectionTest(unittest.TestCase):
    def test_new_section_goes_right_before_relations(self):
        """SPEC-0107:UT-01 — seção nova antes de ## Relations, o resto igual."""
        # SPEC-0107:UT-01
        before = HEAD + "## Summary\n\nTexto antigo.\n\n"
        text = before + RELATIONS
        new = append_section(text, "Resumo", "Linha um.\nLinha dois.\n")
        self.assertTrue(new.endswith(RELATIONS), new)
        self.assertEqual(new.count("## Relations"), 1, new)
        start = new.index("## Resumo")
        self.assertEqual(new[:start].rstrip("\n"), before.rstrip("\n"), "o que vem antes não muda")
        middle = new[start:new.index("## Relations")]
        self.assertRegex(middle, r"\A## Resumo\n\nLinha um\.\nLinha dois\.\n\n*\Z")
        self.assertIn("Texto antigo.\n\n## Resumo", new, "uma linha em branco separa a seção anterior")

    def test_without_relations_the_section_goes_at_the_end(self):
        """SPEC-0107:UT-01 — sem ## Relations, a seção vai para o fim do arquivo."""
        # SPEC-0107:UT-01
        text = HEAD + "## Summary\n\nTexto antigo.\n"
        new = append_section(text, "Resumo", "Novo texto.\n")
        self.assertTrue(new.startswith(text.rstrip("\n")), new)
        self.assertRegex(new[len(text.rstrip("\n")):], r"\A\n+## Resumo\n\nNovo texto\.\n\Z")

    def test_addition_without_final_newline_ends_with_one(self):
        """SPEC-0107:UT-01 — o texto acrescentado termina com uma quebra de linha."""
        # SPEC-0107:UT-01
        new = append_section(HEAD + RELATIONS, "Resumo", "Sem quebra no fim")
        self.assertIn("## Resumo\n\nSem quebra no fim\n", new)
        self.assertTrue(new.endswith(RELATIONS), new)
        new = append_section(HEAD + "## Summary\n", "Resumo", "Sem quebra no fim")
        self.assertTrue(new.endswith("## Resumo\n\nSem quebra no fim\n"), new)

    def test_a_similar_heading_is_not_the_section(self):
        """SPEC-0107:UT-01 — "## Resumo geral" e "### Resumo" não são a seção "## Resumo"."""
        # SPEC-0107:UT-01
        text = HEAD + "## Resumo geral\n\nA.\n\n### Resumo\n\nB.\n\n" + RELATIONS
        new = append_section(text, "Resumo", "C.\n")
        self.assertEqual(len(re.findall(r"^## Resumo$", new, re.MULTILINE)), 1, new)
        self.assertTrue(new.startswith(text[:text.index("## Relations")].rstrip("\n")), new)
        self.assertTrue(new.endswith(RELATIONS), new)


class ExistingSectionTest(unittest.TestCase):
    def test_text_goes_at_the_end_of_the_existing_section(self):
        """SPEC-0107:UT-02 — depois do texto antigo e de uma linha em branco; nada mais muda."""
        # SPEC-0107:UT-02
        text = HEAD + "## Resumo\n\nTexto antigo.\n\n" + RELATIONS
        new = append_section(text, "Resumo", "Texto novo.\n")
        self.assertEqual(new.count("## Resumo"), 1, new)
        self.assertTrue(new.startswith(HEAD + "## Resumo\n\nTexto antigo.\n\nTexto novo.\n"), new)
        self.assertRegex(new[len(HEAD):], r"\A## Resumo\n\nTexto antigo\.\n\nTexto novo\.\n\n*## Relations")
        self.assertTrue(new.endswith(RELATIONS), new)

    def test_existing_section_followed_by_another_section(self):
        """SPEC-0107:UT-02 — a seção termina no próximo título de nível 1 ou 2; ### fica dentro dela."""
        # SPEC-0107:UT-02
        after = "## Outra\n\nOutra coisa.\n\n" + RELATIONS
        text = HEAD + "## Resumo\n\nA.\n\n### Detalhe\n\nB.\n\n" + after
        new = append_section(text, "Resumo", "C.\n")
        self.assertTrue(new.endswith(after), new)
        self.assertRegex(new, r"### Detalhe\n\nB\.\n\nC\.\n\n*## Outra")
        self.assertEqual(new.replace("C.\n", "", 1).replace("\n\n\n", "\n\n"), text)

    def test_existing_section_at_the_end_without_trailing_newline(self):
        """SPEC-0107:UT-02 — seção no fim do arquivo, sem quebra de linha final."""
        # SPEC-0107:UT-02
        text = HEAD + "## Resumo\n\nA."
        new = append_section(text, "Resumo", "B.\n")
        self.assertEqual(new, HEAD + "## Resumo\n\nA.\n\nB.\n")

    def test_empty_existing_section(self):
        """SPEC-0107:UT-02 — seção que existe sem texto recebe o texto, sem duplicar o título."""
        # SPEC-0107:UT-02
        text = HEAD + "## Resumo\n\n" + RELATIONS
        new = append_section(text, "Resumo", "A.\n")
        self.assertEqual(new.count("## Resumo"), 1, new)
        self.assertRegex(new, r"## Resumo\n\nA\.\n\n*## Relations")
        self.assertTrue(new.endswith(RELATIONS), new)

    def test_two_appends_keep_the_order(self):
        """SPEC-0107:UT-02 — dois acréscimos seguidos ficam na ordem."""
        # SPEC-0107:UT-02
        once = append_section(HEAD + RELATIONS, "Resumo", "Primeiro.\n")
        twice = append_section(once, "Resumo", "Segundo.\n")
        self.assertRegex(twice, r"## Resumo\n\nPrimeiro\.\n\nSegundo\.\n\n*## Relations")
        self.assertTrue(twice.endswith(RELATIONS), twice)


class FencedCodeTest(unittest.TestCase):
    """Emenda v2: linha dentro de bloco cercado (``` ou ~~~, até a mesma cerca; sem fechamento, até o fim) nunca é
    título — não abre nem fecha seção."""

    SETUP = "## Setup\n\nInstale assim:\n\n```bash\n# instala\n## não é título\napt install x\n```\n"
    OTHER = "## Outra\n\n~~~\n## Resumo\n# também não\n~~~\n"

    def text(self):
        return HEAD + self.SETUP + "\n" + self.OTHER + "\n" + RELATIONS

    def test_text_goes_after_the_closing_fence_of_the_section(self):
        """SPEC-0107:UT-07 — "# instala" no bloco ```bash não fecha ## Setup; o bloco fica igual."""
        # SPEC-0107:UT-07
        text = self.text()
        new = append_section(text, "Setup", "Texto novo.\n")
        self.assertIn(self.SETUP + "\nTexto novo.\n", new, "o texto entra depois do fechamento do bloco")
        self.assertTrue(new.startswith(HEAD + self.SETUP), new)
        self.assertTrue(new.endswith("\n" + self.OTHER + "\n" + RELATIONS), new)
        self.assertEqual(new.count("Texto novo."), 1, new)

    def test_heading_inside_a_tilde_block_is_not_the_section(self):
        """SPEC-0107:UT-07 — "## Resumo" dentro de ~~~ não conta: a seção é criada antes de ## Relations."""
        # SPEC-0107:UT-07
        text = self.text()
        new = append_section(text, "Resumo", "Texto novo.\n")
        self.assertTrue(new.startswith(HEAD + self.SETUP + "\n" + self.OTHER), "os blocos ficam iguais")
        self.assertTrue(new.endswith(RELATIONS), new)
        self.assertRegex(new[len(HEAD + self.SETUP + "\n" + self.OTHER):],
                         r"\A\n*## Resumo\n\nTexto novo\.\n\n*## Relations\n")

    def test_relations_inside_a_block_is_not_the_relations_heading(self):
        """SPEC-0107:UT-07 — "## Relations" num bloco cercado não é a seção: a nova vai antes da de verdade."""
        # SPEC-0107:UT-07
        block = "## Setup\n\n```markdown\n## Relations\n\n- [[X]] — y\n```\n\n"
        text = HEAD + block + RELATIONS
        new = append_section(text, "Resumo", "Texto novo.\n")
        self.assertTrue(new.startswith(HEAD + block.rstrip("\n")), new)
        self.assertTrue(new.endswith(RELATIONS), new)
        self.assertRegex(new[len(HEAD + block.rstrip("\n")):], r"\A\n+## Resumo\n\nTexto novo\.\n\n*## Relations\n")

    def test_a_fence_closes_only_with_the_same_fence(self):
        """SPEC-0107:UT-07 — "~~~" dentro de ``` não fecha o bloco; "## Resumo" continua dentro dele."""
        # SPEC-0107:UT-07
        block = "## Setup\n\n```\n~~~\n## Resumo\n~~~\n```\n\n"
        text = HEAD + block + RELATIONS
        new = append_section(text, "Resumo", "Texto novo.\n")
        self.assertTrue(new.startswith(HEAD + block.rstrip("\n")), new)
        self.assertRegex(new[len(HEAD + block.rstrip("\n")):], r"\A\n+## Resumo\n\nTexto novo\.\n\n*## Relations\n")

    def test_an_unclosed_block_goes_to_the_end_of_the_file(self):
        """SPEC-0107:UT-07 — bloco sem fechamento vai até o fim: "# x" nele não fecha ## Setup."""
        # SPEC-0107:UT-07
        text = HEAD + "## Setup\n\n```bash\n# x\nmake\n"
        new = append_section(text, "Setup", "Texto novo.\n")
        self.assertTrue(new.startswith(text), new)
        self.assertRegex(new[len(text):], r"\A\n*Texto novo\.\n\Z")


if __name__ == "__main__":
    unittest.main()
