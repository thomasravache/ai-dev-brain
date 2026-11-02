"""Instruções do agente para backup: SKILL.md e references/backup.md (SPEC-0051:UT-06).

O que o contrato exige que esteja escrito (as checagens aceitam português ou inglês e leem linha a linha, ou seja,
cada regra numa frase/item de lista):

    SKILL.md
        uma seção ("## " ou "### ") cujo título fala de backup que cita references/backup.md e traz:
          - pelo menos dois destinos: um fora do provedor do vault e outro em outro provedor ou outra conta;
          - rodar backup antes de uma operação grande e quando o doctor avisar;
          - restaurar com restore, que cria arquivo novo (nunca sobrescreve).
    references/backup.md
        as mesmas regras e, além delas: agendar pelo agendador do sistema (cron, launchd, Agendador de Tarefas /
        Task Scheduler) sem que a skill instale nada; e o aviso de que o zip não é cifrado e o destino precisa ser
        tão protegido quanto o vault.
"""
import re
import unittest

from brain_support import SKILL
from test_confidential_instructions import lines_with, sections

SKILL_MD = SKILL / "SKILL.md"
BACKUP_MD = SKILL / "references" / "backup.md"
TWO = r"\b(dois|duas|2|two)\b|pelo menos|at least"
TARGET = r"destino|destination|target|pasta|folder"
OUTSIDE = r"fora d[oa]|outside|disco externo|external"
OTHER = r"outr[oa] (provedor|conta)|another (provider|account)|other (provider|account)|different (provider|account)"
BEFORE = r"\bantes\b|\bbefore\b"
BIG = r"grande|ado[cç][aã]o|adopt|inbox|large|big"
DOCTOR = r"doctor"
WARN = r"avis|warn"
RESTORE = r"restore"
NEW_FILE = r"arquivo novo|novo arquivo|new file|nunca sobrescreve|never overwrit"
SCHEDULERS = (r"cron", r"launchd", r"agendador de tarefas|task scheduler")
NO_INSTALL = r"n[aã]o instala|nada [eé] instalado|sem instalar|does not install|doesn't install|never install"
NOT_ENCRYPTED = r"n[aã]o [eé] cifrad|n[aã]o cifrad|sem cifra|n[aã]o [eé] criptografad|not encrypted|unencrypted"
PROTECTED = r"protegid|protected|seguro|secure"


def read(path):
    if not path.exists():
        raise AssertionError(f"{path} não existe (SPEC-0051)")
    return path.read_text(encoding="utf-8")


class BackupRulesMixin:
    def assertTargets(self, text, where):
        self.assertTrue(lines_with(text, TWO, TARGET), f"{where}: pelo menos dois destinos")
        self.assertTrue(lines_with(text, OUTSIDE) and lines_with(text, OTHER),
                        f"{where}: um destino fora do provedor e outro em outro provedor ou conta")

    def assertWhenToRun(self, text, where):
        self.assertTrue(lines_with(text, BEFORE, BIG), f"{where}: rodar backup antes de uma operação grande")
        self.assertTrue(lines_with(text, DOCTOR, WARN), f"{where}: rodar backup quando o doctor avisar")

    def assertRestore(self, text, where):
        self.assertTrue(lines_with(text, RESTORE, NEW_FILE), f"{where}: restaurar com restore, que cria arquivo novo")


class SkillInstructionsTest(BackupRulesMixin, unittest.TestCase):
    def section(self):
        found = sections(read(SKILL_MD), r"backup")
        self.assertTrue(found, "SKILL.md precisa de uma seção sobre backup (SPEC-0051)")
        return "\n".join(found)

    def test_skill_has_a_backup_section_with_the_agent_rules(self):
        """SPEC-0051:UT-06"""
        text = self.section()
        self.assertIn("references/backup.md", text)
        self.assertTargets(text, "SKILL.md")
        self.assertWhenToRun(text, "SKILL.md")
        self.assertRestore(text, "SKILL.md")


class BackupReferenceTest(BackupRulesMixin, unittest.TestCase):
    def test_reference_has_targets_when_to_run_and_restore(self):
        """SPEC-0051:UT-06"""
        text = read(BACKUP_MD)
        self.assertTargets(text, "references/backup.md")
        self.assertWhenToRun(text, "references/backup.md")
        self.assertRestore(text, "references/backup.md")

    def test_reference_shows_the_system_scheduler_without_installing_anything(self):
        """SPEC-0051:UT-06"""
        text = read(BACKUP_MD)
        for scheduler in SCHEDULERS:
            self.assertRegex(text, f"(?i){scheduler}", f"references/backup.md: agendar com {scheduler}")
        self.assertTrue(lines_with(text, NO_INSTALL), "references/backup.md: a skill não instala nada")

    def test_reference_warns_that_the_zip_is_not_encrypted(self):
        """SPEC-0051:UT-06"""
        text = read(BACKUP_MD)
        self.assertTrue(lines_with(text, NOT_ENCRYPTED), "references/backup.md: o zip não é cifrado")
        self.assertTrue(lines_with(text, PROTECTED), "references/backup.md: destino tão protegido quanto o vault")
        self.assertTrue(re.search(r"(?i)zip", text))


if __name__ == "__main__":
    unittest.main()
