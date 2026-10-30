"""Pastas sempre em kebab-case (SPEC-0042: UT-01, IT-01 e IT-02).

Interface esperada em scripts/brain.py:
    kebab(name) -> str   minúsculas, sem acento (fold), cada sequência fora de [a-z0-9] vira "-", sem traço no
                         começo nem no fim; só símbolos = "" ("Cálculo_II" -> "calculo-ii", "???" -> "").

Contrato da CLI que estes testes conferem (mensagens podem ir para stdout ou stderr):
    init --context / context add   o nome do contexto e cada parte da pasta passam por kebab; se mudar, o comando
                                   segue e avisa "nome ajustado para kebab-case: <de> → <para>" (com ou sem crases
                                   em volta de <de> e <para>). O título do MOC (--title ou :título) fica como o
                                   usuário escreveu. Nome vazio depois do ajuste = exit 2, nada gravado.
    init --adopt --map             as pastas mapeadas não mudam (ADR-0007: não renomear o que é do usuário).
    doctor                         linha AVISO, com "kebab" no texto, para a pasta do vault fora do padrão (o item
                                   começa por "vault" e o texto cita a pasta, ex.: "SecondBrain"), para o nome de
                                   contexto e para a pasta de contexto gravados à mão fora do padrão; não renomeia
                                   nada, e o exit segue 0 sem ERRO.

Os nomes no disco são conferidos com os.listdir, que mostra a caixa real também em sistemas de arquivos que não
diferenciam maiúsculas (macOS).
"""
import os
import re
import unittest

from brain_support import doctor_lines, fn, output, snapshot
from test_cli import CliTestCase

ADJUSTED = "nome ajustado para kebab-case: `?{de}`? → `?{para}`?"


def adjusted(de, para):
    return re.compile(ADJUSTED.format(de=re.escape(de), para=re.escape(para)))


class KebabTest(unittest.TestCase):
    def test_kebab_lowercases_folds_and_joins_with_dashes(self):
        """SPEC-0042:UT-01"""
        kebab = fn("kebab", "SPEC-0042")
        cases = {"Faculdade": "faculdade", "Trabalho Novo": "trabalho-novo", "Cálculo_II": "calculo-ii",
                 "--Ok--": "ok", "???": ""}
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(kebab(name), expected)


class KebabContextCliTest(CliTestCase):
    def test_init_and_context_add_adjust_names_and_folders_to_kebab_case(self):
        """SPEC-0042:IT-01"""
        vault = self.box.vault
        vault.mkdir(parents=True)
        out = self.box.init("--context", "Faculdade=Projects/Faculdade:Faculdade")
        self.assertExit(out, 0)
        self.assertRegex(output(out), adjusted("Faculdade", "faculdade"))

        out = self.box.run("context", "add", "Trabalho Novo", "--folder", "Areas/Trabalho Novo")
        self.assertExit(out, 0)
        self.assertRegex(output(out), adjusted("Trabalho Novo", "trabalho-novo"))

        contexts = self.box.config_json()["values"]["contexts"]
        self.assertEqual(sorted(contexts), ["faculdade", "trabalho-novo"])
        self.assertEqual(contexts["faculdade"], {"folder": "projects/faculdade", "title": "Faculdade"})
        self.assertEqual(contexts["trabalho-novo"]["folder"], "areas/trabalho-novo")

        self.assertNotIn("Projects", os.listdir(vault))
        self.assertNotIn("Areas", os.listdir(vault))
        self.assertEqual(os.listdir(vault / "projects"), ["faculdade"])
        self.assertEqual(os.listdir(vault / "areas"), ["trabalho-novo"])
        self.assertEqual(sorted(os.listdir(vault / "mocs")), ["faculdade.md", "trabalho-novo.md"])
        self.assertIn("Faculdade", (vault / "mocs" / "faculdade.md").read_text(encoding="utf-8"))

        shared_before = (vault / "brain-config.yml").read_text(encoding="utf-8")
        out = self.box.run("context", "add", "???", "--folder", "x")
        self.assertExit(out, 2)
        self.assertEqual((vault / "brain-config.yml").read_text(encoding="utf-8"), shared_before)
        self.assertNotIn("x", os.listdir(vault))


class KebabAdoptAndDoctorTest(CliTestCase):
    def test_adopt_keeps_mapped_folders_as_they_are(self):
        """SPEC-0042:IT-02"""
        vault = self.box.vault
        (vault / "Inbox").mkdir(parents=True)
        out = self.box.init("--adopt", "--map", "inbox=Inbox", provider="local")
        self.assertExit(out, 0)
        self.assertIn("Inbox", os.listdir(vault))
        self.assertNotIn("inbox", os.listdir(vault))
        self.assertEqual(self.box.config_json()["values"]["layout"]["inbox"], "Inbox")

    def test_doctor_warns_about_folders_and_contexts_outside_kebab_case_without_renaming(self):
        """SPEC-0042:IT-02"""
        box = self.box
        vault = box.root / "SecondBrain" / "vault"
        files = box.root / "second-brain-files"
        vault.mkdir(parents=True)
        self.assertExit(box.init(vault=vault, files=files), 0)

        parse, dump = fn("parse_yaml"), fn("dump_yaml")
        shared = vault / "brain-config.yml"
        data = parse(shared.read_text(encoding="utf-8"))
        data["contexts"] = {"Work": {"folder": "Areas/Work", "title": "Work"}}
        shared.write_text(dump(data), encoding="utf-8")
        (vault / "Areas" / "Work").mkdir(parents=True)
        (vault / "mocs" / "Work.md").write_text("# Work\n", encoding="utf-8")
        before = snapshot(box.root)

        out = box.run("doctor")
        self.assertExit(out, 0)
        warnings = [(item, detail) for status, item, detail in doctor_lines(out.stdout) if status == "AVISO"]
        self.assertTrue(any(item.startswith("vault") and "SecondBrain" in item + detail
                            and "kebab" in item + detail for item, detail in warnings), out.stdout)
        work = [item + " " + detail for item, detail in warnings if "Work" in item + detail]
        self.assertTrue(any("kebab" in text and re.search(r"\bWork\b", text) for text in work), out.stdout)
        self.assertTrue(any("kebab" in text and "Areas/Work" in text for text in work), out.stdout)

        self.assertEqual(snapshot(box.root), before, "doctor renomeou ou alterou algo")
        self.assertEqual(parse(shared.read_text(encoding="utf-8"))["contexts"],
                         {"Work": {"folder": "Areas/Work", "title": "Work"}})


if __name__ == "__main__":
    unittest.main()
