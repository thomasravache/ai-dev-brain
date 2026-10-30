"""Instruções para o agente: SKILL.md, references/config.md e references/providers.md (SPEC-0017:UT-05).

O que o contrato exige que esteja escrito (as checagens aceitam português ou inglês):

    SKILL.md
        frontmatter com `name: second-brain` e `description:`;
        manda rodar `brain.py config` antes de qualquer fluxo e trata o exit 3 como "não configurado" -> onboarding;
        o onboarding cita `brain.py init` com `--adopt` e `--context`, avisa sobre o celular conforme
        `references/providers.md` e termina com `brain.py doctor`;
        vault com brain-config.yml e máquina sem configuração local -> `init --join`;
        já configurado -> segue direto o fluxo pedido, sem perguntar nada de configuração.

    references/config.md
        as duas camadas: `config.yml` local (com `BRAIN_CONFIG_HOME`) e `brain-config.yml` no vault, e as chaves
        vault, files, provider, layout, para, contexts, processors.

    references/providers.md
        uma seção `## ` por provedor da v1, com o id no título (ex.: "## Google Drive (`google-drive`)"):
        google-drive, onedrive, icloud, local; cada seção fala de iOS e de Android.

    SKILL.md (SPEC-0018:UT-05)
        cita `brain.py search`, `brain.py related` e `brain.py links` e diz em que passo de cada fluxo usar:
        no fluxo de guardar, `related`/`search` antes de escrever (buscar relações); no fluxo de consultar,
        `search` para achar as notas e `links` para seguir os links (as checagens aceitam português ou inglês).
"""
import re
import unittest

from brain_support import SKILL

SKILL_MD = SKILL / "SKILL.md"
CONFIG_MD = SKILL / "references" / "config.md"
PROVIDERS_MD = SKILL / "references" / "providers.md"
PROVIDERS = ("google-drive", "onedrive", "icloud", "local")


def read(path):
    if not path.exists():
        raise AssertionError(f"{path} não existe (SPEC-0017)")
    return path.read_text(encoding="utf-8")


def sections(text):
    """{título: corpo} de cada seção '## ' (até o próximo '## ')."""
    result, title, body = {}, None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if title is not None:
                result[title] = "\n".join(body)
            title, body = line[3:].strip(), []
        elif title is not None:
            body.append(line)
    if title is not None:
        result[title] = "\n".join(body)
    return result


class InstructionsTest(unittest.TestCase):
    def test_skill_md_describes_onboarding_join_and_direct_use(self):
        """SPEC-0017:UT-05"""
        text = read(SKILL_MD)
        self.assertTrue(text.startswith("---\n"), "SKILL.md sem frontmatter")
        front = text.split("---", 2)[1]
        self.assertRegex(front, r"(?m)^name:\s*second-brain\s*$")
        self.assertRegex(front, r"(?m)^description:")
        for needle in ("brain.py config", "brain.py init", "init --join", "--adopt", "--context",
                       "brain.py doctor", "references/providers.md"):
            self.assertIn(needle, text)
        self.assertRegex(text, r"(?i)onboarding")
        self.assertRegex(text, r"(?i)(exit|código|code|sai com|saída)\D{0,20}\b3\b")
        self.assertRegex(text, r"(?is)(antes de qualquer|before any)")
        self.assertRegex(text, r"(?is)configurad[oa].{0,120}(direto|diretamente|sem perguntar)"
                               r"|configured.{0,120}(directly|without asking)")

    def test_config_reference_describes_both_layers(self):
        """SPEC-0017:UT-05"""
        text = read(CONFIG_MD)
        for needle in ("BRAIN_CONFIG_HOME", "config.yml", "brain-config.yml"):
            self.assertIn(needle, text)
        for key in ("vault", "files", "provider", "layout", "para", "contexts", "processors"):
            self.assertRegex(text, rf"\b{key}\b")

    def test_providers_reference_has_a_section_per_provider_with_mobile_warning(self):
        """SPEC-0017:UT-05"""
        found = sections(read(PROVIDERS_MD))
        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                titles = [t for t in found if re.search(rf"(?<![\w-]){re.escape(provider)}(?![\w-])", t)]
                self.assertEqual(len(titles), 1, f"seção de {provider}: {titles} em {list(found)}")
                body = found[titles[0]]
                self.assertIn("iOS", body)
                self.assertIn("Android", body)


class SearchInstructionsTest(unittest.TestCase):
    def test_skill_md_says_when_to_use_search_related_and_links(self):
        """SPEC-0018:UT-05"""
        text = read(SKILL_MD)
        for command in ("brain.py search", "brain.py related", "brain.py links"):
            self.assertTrue(command in text, f"SKILL.md não cita `{command}` (SPEC-0018)")
        self.assertRegex(text, r"(?is)(guardar|store|save)\b.{0,600}\b(related|search)\b.{0,300}"
                               r"(antes de escrever|before writing)"
                               r"|(guardar|store|save)\b.{0,600}(antes de escrever|before writing).{0,300}"
                               r"\b(related|search)\b",
                         "fluxo de guardar: related/search antes de escrever")
        self.assertRegex(text, r"(?is)(consultar|query|answer)\b.{0,600}\bsearch\b",
                         "fluxo de consultar: search")
        self.assertRegex(text, r"(?is)(consultar|query|answer)\b.{0,600}\blinks\b.{0,200}(seguir|follow)"
                               r"|(consultar|query|answer)\b.{0,600}(seguir|follow).{0,200}\blinks\b",
                         "fluxo de consultar: links para seguir os links")


if __name__ == "__main__":
    unittest.main()
