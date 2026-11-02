"""Localizar o vault pelo conector numa sessão sem configuração local (SPEC-0052:UT-01, SPEC-0052:UT-02; ADR-0013).

O que o contrato exige que esteja escrito. As checagens comparam o texto sem acento, sem maiúsculas, sem `**` e
sem crases, com as quebras de linha viradas espaço; cada regra vale dentro de um mesmo item (um "- " ou "1. " de
lista, ou um parágrafo):

    SKILL.md, "## Antes de qualquer fluxo"
        um item que diz que exit 3 numa sessão nova é normal e, no mesmo item: com conector, buscar o
        brain-config.yml pelo conector antes do onboarding; sem perguntar nem comentar configuração; onboarding só
        se o conector não achar o arquivo ou se a pessoa pedir para configurar esta máquina; pedido fora do modo só
        conector → explicar o limite em uma frase.

    SKILL.md, "## Modo só conector"
        o primeiro item de lista começa com **Localizar o vault**: brain-config.yml pelo conector; a pasta dele é a
        raiz do vault; o layout dá a inbox; não pedir o caminho; mais de um brain-config.yml → o que tem index.md e
        log.md na mesma pasta, e só então uma pergunta curta.
        continua com o item **Qualquer outra escrita**: recusar e fazer no computador (o limite não mudou).

    SKILL.md, "## Regras"
        o primeiro item cobre "Configurado" e "Exit 3 com conector" (localizar o vault pelo conector, sem perguntar).

    references/connectors.md, "## Quando entra o modo só conector" (ou "Quando usar")
        um item com o passo de localizar o vault pelo brain-config.yml e a regra de mais de um.
"""
import re
import unicodedata
import unittest

from brain_support import SKILL
from test_inbox_instructions import SKILL_MD, sections

CONNECTORS_MD = SKILL / "references" / "connectors.md"

# Padrões sobre o texto normalizado (sem acento, minúsculo, sem ** e crases, espaços simples).
# "(?:[^.]|\.(?=\w))" é qualquer caractere dentro da mesma frase: o ponto de brain-config.yml ou index.md não fecha a frase.
EXIT3_NORMAL = {
    "exit 3": r"\bexit 3\b",
    "sessão nova": r"sessao nova|nova sessao",
    "normal": r"\bnormal\b",
}
EXIT3_RULES = {
    "busca o brain-config.yml": r"(busc|busq|procur|localiz|ach)\w*(?:[^.]|\.(?=\w)){0,80}brain-config\.yml",
    "pelo conector": r"brain-config\.yml(?:[^.]|\.(?=\w)){0,60}conector|conector(?:[^.]|\.(?=\w)){0,60}brain-config\.yml",
    "antes do onboarding": r"antes(?:[^.]|\.(?=\w)){0,60}onboarding",
    "não perguntar configuração": r"(sem|nao|nunca) pergunt",
    "não comentar configuração": r"(sem|nem|nao|nunca) coment\w*(?:[^.]|\.(?=\w)){0,40}configura",
    "onboarding só se não achar": r"onboarding(?:[^.]|\.(?=\w)){0,40}\bso\b(?:[^.]|\.(?=\w)){0,40}(nao (ach|encontr)|nao for (achado|encontrado))",
    "ou se a pessoa pedir para configurar esta máquina": r"pe(dir|ca|de)(?:[^.]|\.(?=\w)){0,40}configurar esta maquina",
    "limite em uma frase": r"limite(?:[^.]|\.(?=\w)){0,40}(uma|1) frase|(uma|1) frase(?:[^.]|\.(?=\w)){0,40}limite",
}
LOCATE_RULES = {
    "brain-config.yml": r"brain-config\.yml",
    "pelo conector": r"conector",
    "a pasta é a raiz do vault": r"pasta(?:[^.]|\.(?=\w)){0,60}raiz do vault",
    "layout dá a inbox": r"layout(?:[^.]|\.(?=\w)){0,60}inbox",
    "não pedir o caminho": r"(nao|sem|nunca) (pe(dir|ca|de)|pergunt)\w*(?:[^.]|\.(?=\w)){0,30}caminho",
}
MANY_CONFIGS_RULES = {
    "mais de um brain-config.yml": r"mais de um(?:[^.]|\.(?=\w)){0,20}brain-config\.yml",
    "o que tem index.md e log.md": r"index\.md(?:[^.]|\.(?=\w)){0,10}\be\b(?:[^.]|\.(?=\w)){0,10}log\.md",
    "na mesma pasta": r"mesma pasta|ao lado",
    "uma pergunta curta": r"(uma|1) (unica )?pergunta curta",
}


def norm(text):
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", text).strip().lower()


def read(path):
    if not path.exists():
        raise AssertionError(f"{path} não existe (SPEC-0052)")
    return path.read_text(encoding="utf-8")


def section(text, title_re):
    bodies = sections(text, title_re)
    if not bodies:
        raise AssertionError(f"seção {title_re!r} não encontrada")
    return bodies[0]


def items(body):
    """Itens da seção: cada item de lista ("- ", "1. ") ou parágrafo, com as linhas de continuação juntas."""
    out, cur = [], []
    for line in body.splitlines():
        starts_item = re.match(r"^(\s*)(-|\*|\d+\.) ", line)
        if not line.strip() or (starts_item and not starts_item.group(1)):
            if cur:
                out.append("\n".join(cur))
            cur = [line] if line.strip() else []
        else:
            cur.append(line)
    if cur:
        out.append("\n".join(cur))
    return out


def bullets(body):
    return [i for i in items(body) if re.match(r"^(-|\*|\d+\.) ", i)]


def item_with(body, patterns):
    """Primeiro item (normalizado) que casa com todos os padrões, ou None."""
    for raw in items(body):
        text = norm(raw)
        if all(re.search(p, text) for p in patterns):
            return text
    return None


class ConnectorSessionInstructionsTest(unittest.TestCase):
    def assertRules(self, text, rules, where):
        for rule, pattern in rules.items():
            with self.subTest(where=where, rule=rule):
                self.assertRegex(text, pattern, f"{where}: {rule}")

    def test_before_any_flow_says_exit_3_in_a_new_session_is_normal(self):
        """SPEC-0052:UT-01"""
        body = section(read(SKILL_MD), r"^Antes de qualquer fluxo")
        text = item_with(body, EXIT3_NORMAL.values())
        self.assertIsNotNone(text, "Antes de qualquer fluxo: falta o item 'Exit 3 numa sessão nova é normal'")
        self.assertRules(text, EXIT3_RULES, "Antes de qualquer fluxo, exit 3 numa sessão nova")

    def test_connector_only_mode_starts_by_locating_the_vault(self):
        """SPEC-0052:UT-01"""
        body = section(read(SKILL_MD), r"^Modo s[óo] conector")
        first = norm(bullets(body)[0])
        self.assertTrue(first.startswith("- localizar o vault"),
                        f"Modo só conector: o primeiro item deve ser 'Localizar o vault', é: {first[:60]!r}")
        self.assertRules(first, LOCATE_RULES, "Modo só conector, Localizar o vault")
        self.assertRules(first, MANY_CONFIGS_RULES, "Modo só conector, mais de um brain-config.yml")

    def test_first_rule_covers_configured_and_exit_3_with_connector(self):
        """SPEC-0052:UT-01"""
        body = section(read(SKILL_MD), r"^Regras$")
        first = norm(bullets(body)[0])
        self.assertRules(first, {
            "brain.py config antes de qualquer fluxo": r"brain\.py config antes de qualquer fluxo",
            "Configurado": r"\bconfigurado\b",
            "Exit 3 com conector": r"exit 3 com conector",
            "localizar o vault pelo conector": r"localiz\w*(?:[^.]|\.(?=\w)){0,20}vault(?:[^.]|\.(?=\w)){0,20}conector",
            "sem perguntar configuração": r"(sem|nao|nunca) pergunt\w*(?:[^.]|\.(?=\w)){0,20}configura",
        }, "Regras, primeiro item")
        exit3 = first[first.find("exit 3 com conector"):]
        self.assertRegex(exit3, r"(sem|nao|nunca) pergunt", "Regras: Exit 3 com conector também sem perguntar")

    def test_connectors_md_when_to_use_locates_the_vault(self):
        """SPEC-0052:UT-02"""
        body = section(read(CONNECTORS_MD), r"^Quando (usar|entra)")
        text = item_with(body, [r"brain-config\.yml", r"(busc|busq|procur|localiz|ach)\w*(?:[^.]|\.(?=\w)){0,80}brain-config\.yml"])
        self.assertIsNotNone(text, "connectors.md, Quando usar: falta o passo de localizar o vault pelo brain-config.yml")
        self.assertRules(text, {
            "pelo conector": r"conector",
            "a pasta é a raiz do vault": r"pasta(?:[^.]|\.(?=\w)){0,60}(raiz do vault|e o vault)",
        }, "connectors.md, Quando usar")
        self.assertRules(text, MANY_CONFIGS_RULES, "connectors.md, Quando usar, mais de um brain-config.yml")

    def test_skill_md_keeps_the_connector_only_write_limit(self):
        """SPEC-0052:UT-02"""
        body = section(read(SKILL_MD), r"^Modo s[óo] conector")
        text = item_with(body, [r"^- qualquer outra escrita"])
        self.assertIsNotNone(text, "Modo só conector: falta o item 'Qualquer outra escrita'")
        self.assertRules(text, {
            "recusa": r"recus",
            "feito no computador": r"computador",
        }, "Modo só conector, Qualquer outra escrita")

    def test_exit_3_case_sends_to_onboarding_only_without_connector_or_on_request(self):
        """SPEC-0052:UT-01"""
        body = section(read(SKILL_MD), r"^Antes de qualquer fluxo")
        case = next((norm(b) for b in bullets(body) if norm(b).startswith("- exit 3")), None)
        self.assertIsNotNone(case, "Antes de qualquer fluxo: falta o caso '- **Exit 3**' da lista")
        self.assertRules(case, {
            "sem conector do provedor": r"\bsem (um |o )?conector",
            "ou a pedido": r"a pedido|(pessoa|ela) pe(dir|ca|de)|pedir para configurar",
        }, "Antes de qualquer fluxo, caso Exit 3")

    def test_onboarding_heading_points_to_the_connector(self):
        """SPEC-0052:UT-01"""
        lines = read(SKILL_MD).splitlines()
        idx = next((i for i, line in enumerate(lines) if line.startswith("## Onboarding")), None)
        self.assertIsNotNone(idx, "SKILL.md sem o título '## Onboarding'")
        first = next((line for line in lines[idx + 1:] if line.strip()), "")
        self.assertRegex(norm(lines[idx] + " " + first), r"conector",
                         f"onboarding: o título ou a primeira linha deve citar o conector: {lines[idx]!r} / {first!r}")

    def test_first_rule_says_follow_in_connector_only_mode(self):
        """SPEC-0052:UT-01"""
        first = norm(bullets(section(read(SKILL_MD), r"^Regras$"))[0])
        self.assertIn("siga no modo so conector", first, "Regras, primeiro item: 'siga no modo só conector'")

    def test_locate_the_vault_searches_by_the_exact_file_name(self):
        """SPEC-0052:UT-01"""
        where = {
            "SKILL.md, Modo só conector": section(read(SKILL_MD), r"^Modo s[óo] conector"),
            "connectors.md, Quando usar": section(read(CONNECTORS_MD), r"^Quando (usar|entra)"),
        }
        for name, body in where.items():
            with self.subTest(where=name):
                item = item_with(body, [r"^- localizar o vault"])
                self.assertIsNotNone(item, f"{name}: falta o item 'Localizar o vault'")
                self.assertRegex(item, r"brain-config\.yml", f"{name}: brain-config.yml")
                self.assertRegex(item, r"exatamente|pelo nome|nome exato",
                                 f"{name}: buscar o arquivo pelo nome exato brain-config.yml, não pelo conteúdo")


if __name__ == "__main__":
    unittest.main()
