"""Achar o vault e a inbox pelo conector e conectar só a pasta numa sessão na nuvem (SPEC-0110: UT-06, UT-07;
ADR-0013, ADR-0027).

O que o contrato exige que esteja escrito. Como em test_connector_session_instructions, as checagens comparam o
texto sem acento, sem maiúsculas, sem `**` e sem crases, e cada regra vale dentro de um mesmo item (um "- " ou "1. "
de lista, ou um parágrafo):

    references/connectors.md
        - usar primeiro os IDs de connectors.<provedor> (vault_folder_id, inbox_folder_id);
        - sem eles, buscar o brain-config.yml e conferir index.md e log.md na mesma pasta (o mesmo pai, parentId);
        - inbox: só a pasta layout.inbox cujo pai é a pasta do vault, nunca outra pasta inbox solta;
        - ler o .yml com download_file_content quando read_file_content recusar o tipo;
        - se nada ler a configuração: seguir com inbox e sem contexto, avisando a pessoa;
        - gravar os IDs com connector set numa máquina com a pasta montada.

    SKILL.md, "## Modo só conector", item **Localizar o vault** (v2)
        - usar primeiro os IDs de connectors.<provedor> quando o agente já os tiver;
        - só com o conector, o ganho principal dos IDs é escolher a inbox certa.

    SKILL.md, uma seção ("## " ou "### ") cujo título fala da sessão na nuvem (nuvem | cloud)
        - pedir só a pasta do vault ("Add folder"), nunca a pasta inteira da nuvem nem a configuração local;
        - o init --join ali roda na máquina virtual da sessão, sem a configuração local do computador da pessoa;
        - a skill com o nome second-brain é a skill antiga avulsa na conta: removê-la e instalar o plugin fermion.
"""
import unittest

from brain_support import SKILL
from test_connector_session_instructions import item_with, read, section
from test_inbox_instructions import SKILL_MD, sections

CONNECTORS_MD = SKILL / "references" / "connectors.md"
S = r"(?:[^.]|\.(?=\w))"  # qualquer caractere da mesma frase (o ponto de brain-config.yml não fecha a frase)

CONNECTORS_RULES = {
    "IDs de connectors.<provedor> primeiro": [r"connectors\.", r"vault_folder_id", r"primeiro|antes"],
    "sem os IDs, brain-config.yml com index.md e log.md na mesma pasta": [
        r"sem (eles|os ids|ids)", r"brain-config\.yml", rf"index\.md{S}{{0,10}}\be\b{S}{{0,10}}log\.md",
        r"mesma pasta|mesmo pai|parentid"],
    "inbox é a layout.inbox com pai na pasta do vault": [
        r"layout\.inbox", rf"pai{S}{{0,40}}pasta do vault", rf"nunca{S}{{0,60}}(outra|solta)"],
    "download_file_content quando read_file_content recusar": [
        r"download_file_content", r"read_file_content", r"recus"],
    "nada lê a configuração: inbox, sem contexto, avisando": [
        r"(nenhum|nada|os dois|ambos|nem )", r"\binbox\b", r"sem contexto", r"avis"],
    "gravar os IDs com connector set na máquina com a pasta montada": [
        r"connector set", r"pasta montada|montada"],
}

LOCATE_IDS_RULES = {
    "IDs de connectors.<provedor> primeiro": rf"connectors\.{S}{{0,80}}primeiro|primeiro{S}{{0,80}}connectors\.",
    "só com o conector, o ganho principal é a inbox certa": rf"ganho principal{S}{{0,80}}inbox certa",
    "só com o conector": r"so (com o |pelo )?conector",
}

CLOUD_RULES = {
    "só a pasta do vault, com Add folder; nunca a pasta inteira nem a configuração local": [
        r"add folder", rf"(so|apenas|somente){S}{{0,20}}pasta do vault", r"nunca", r"pasta inteira",
        r"configuracao local"],
    "init --join na máquina virtual, sem a configuração local da pessoa": [
        r"init --join", r"maquina virtual", rf"sem{S}{{0,20}}configuracao local"],
    "second-brain é a skill antiga avulsa: remover e instalar o plugin fermion": [
        r"second-brain", r"antiga|avulsa", r"remov", r"plugin fermion|fermion"],
}


class CloudSessionInstructionsTest(unittest.TestCase):
    def assertItems(self, body, rules, where):
        for rule, patterns in rules.items():
            with self.subTest(where=where, rule=rule):
                self.assertIsNotNone(item_with(body, patterns), f"{where}: falta um item com {rule}")

    def test_connectors_md_finds_the_vault_and_the_inbox(self):
        """SPEC-0110:UT-06"""
        # SPEC-0110:UT-06
        self.assertItems(read(CONNECTORS_MD), CONNECTORS_RULES, "references/connectors.md")

    def test_skill_md_locate_the_vault_uses_the_ids_first(self):
        """SPEC-0110:UT-06 (v2)"""
        # SPEC-0110:UT-06
        item = item_with(section(read(SKILL_MD), r"^Modo s[óo] conector"), [r"^- localizar o vault"])
        self.assertIsNotNone(item, "SKILL.md, Modo só conector: falta o item 'Localizar o vault'")
        for rule, pattern in LOCATE_IDS_RULES.items():
            with self.subTest(rule=rule):
                self.assertRegex(item, pattern, f"SKILL.md, Localizar o vault: {rule}")

    def test_skill_md_cloud_session_connects_only_the_vault_folder(self):
        """SPEC-0110:UT-07"""
        # SPEC-0110:UT-07
        bodies = sections(read(SKILL_MD), r"nuvem|cloud")
        self.assertTrue(bodies, "SKILL.md sem seção ('## ' ou '### ') de sessão na nuvem")
        self.assertItems("\n\n".join(bodies), CLOUD_RULES, "SKILL.md, sessão na nuvem")


if __name__ == "__main__":
    unittest.main()
