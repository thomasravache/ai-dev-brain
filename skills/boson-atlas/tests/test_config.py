"""Configuração em duas camadas, YAML próprio, init, config e doctor do atlas.py (SPEC-0032: UT-01 a UT-04 e
IT-01 a IT-05).

Contrato esperado das funções puras de scripts/atlas.py (o Implementer segue estes testes):

    AtlasError(Exception)
        Erro mostrado sem traceback; a CLI imprime a mensagem e sai com o código do contrato.

    parse_yaml(text: str) -> dict
        Subconjunto de YAML no estilo do brain.py, escrito no próprio atlas.py (ADR-0010): `chave: valor`, mapas
        aninhados por indentação, mapas inline `{a: b, c: []}`, listas inline `[a, b]` e em bloco (`- item`),
        lista em bloco de mapas (`- id: x` seguido das outras chaves do item, forma dos `collectors` da
        SPEC-0033), comentários de linha inteira e no fim da linha (` # ...`, fora de aspas), strings com `:`
        (sem aspas quando o `:` não é seguido de espaço, ou entre aspas). Os testes comparam escalares como texto
        (str), então converter ou não `1`/`14` em número é decisão do Implementer.

    dump_yaml(data: dict) -> str
        Escritor do mesmo subconjunto (dicts, listas de strings, escalares): parse_yaml(dump_yaml(d)) == d.

    render_atlas_config(organization: str, mode: str) -> str
        Texto do atlas-config.yml que init grava: assets/atlas-config.yml com os comentários do modelo mantidos;
        só organization e mode mudam. Nunca contém caminho absoluto.

    validate_credentials(credentials: dict) -> None
        credentials = {<coletor>: {"env": [NOME, ...], "profile": <nome>}}. Nome de variável fora de
        ^[A-Z_][A-Z0-9_]*$ -> AtlasError com "credentials aceita só nomes de variável: <coletor>" (exit 2 na
        CLI); a mensagem nunca repete o valor recebido.

    load_config(config_home: Path | str | None = None) -> dict
        Lê <config_home>/config.yml (local: atlas, credentials; None = $ATLAS_CONFIG_HOME ou
        ~/.config/org-atlas) e <atlas>/atlas-config.yml, completa com os padrões do contrato e devolve
        {"values": {...}, "origins": {...}}:
          values  : atlas, credentials, version, organization, mode, language, stale_days, categories,
                    collectors, redaction.
          origins : "local" | "atlas" | "padrão" por chave de primeiro nível.
        credentials inválidas -> AtlasError (validate_credentials), sem gravar nada.
        `atlas.py config --json` imprime exatamente esse objeto em JSON.

Saídas da CLI que os testes conferem (contrato da seção 6; mensagens de erro podem ir para stdout ou stderr):
    init (pasta vazia/inexistente) exit 0, "Atlas criado em <P>" e o que foi criado
    init repetido igual            exit 0, "Atlas já configurado"
    atlas-config.yml diferente     exit 2, "atlas-config.yml já existe — use --join ou --force"
    pasta ocupada                  exit 2, "pasta não está vazia — escolha outra pasta"
    --mode inválido                exit 2, mensagem com repo e local
    init --join sem config         exit 2, "atlas sem atlas-config.yml — rode init"
    config / doctor sem local      exit 3, "org-atlas não configurado nesta máquina — rode init (ou init --join)"
    credentials com valor          exit 2, "credentials aceita só nomes de variável: <coletor>"
    doctor                         linhas "OK|AVISO|ERRO <item> — <detalhe>", itens começando por
                                   "configuração local", "pasta do atlas", "atlas-config.yml", "estrutura", "git";
                                   uma linha por coletor (com o id e o executável, que é command[0]) e por
                                   credencial (com o nome da variável e "definida" | "não definida").
                                   Exit 0 sem ERRO, 1 com ERRO.

Coletor declarado no IT-05: forma da SPEC-0033 (`collectors: - id, category, command: [argv]`); o doctor só
confere se o executável (primeiro item de `command`) existe no PATH.
"""
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import (
    ASSET_CONFIG,
    DEFAULTS,
    NOT_CONFIGURED,
    SCRIPT,
    SHARED_KEYS,
    STRUCTURE_DIRS,
    STRUCTURE_FILES,
    Sandbox,
    absolute_values,
    doctor_lines,
    fn,
    normalize,
    output,
    snapshot,
)

SECRET = "s3cr3t-value-0032-do-not-print"
MISSING_EXE = "atlas-missing-collector-0032"
REGION_BEGIN = re.compile(r"<!-- atlas:begin (\S+) -->")


def comments(text):
    """Comentários do texto: linhas inteiras '# ...' e o trecho ' # ...' no fim de uma linha."""
    found = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            found.append(stripped)
        elif " #" in line:
            found.append(line[line.index(" #") + 1:].strip())
    return found


def atlas_config_text(organization="Acme", mode="local", collectors=""):
    return ("version: 1\n"
            f"organization: {organization}\n"
            f"mode: {mode}\n"
            "language: auto\n"
            "stale_days: 14\n"
            "categories: [code, delivery]\n"
            f"{collectors or 'collectors: []'}\n"
            "redaction: {extra_patterns: []}\n")


# --------------------------------------------------------------------------- unitários


class LoadConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.atlas = self.tmp / "acme-atlas"
        self.atlas.mkdir()
        self.config_home = self.tmp / "config-home"
        self.config_home.mkdir()
        (self.config_home / "config.yml").write_text(
            f'atlas: "{self.atlas}"\n'
            "credentials:\n"
            "  github: {env: [GITHUB_TOKEN], profile: work}\n", encoding="utf-8")
        # sem language, stale_days, categories, collectors nem redaction: vêm do padrão
        (self.atlas / "atlas-config.yml").write_text(
            "version: 1\norganization: Acme\nmode: local\n", encoding="utf-8")

    def test_effective_config_reports_the_origin_of_each_value(self):
        """SPEC-0032:UT-01"""
        config = fn("load_config")(self.config_home)
        values, origins = normalize(config["values"]), config["origins"]
        self.assertEqual(values["atlas"], str(self.atlas))
        self.assertEqual(origins["atlas"], "local")
        self.assertEqual(values["credentials"], {"github": {"env": ["GITHUB_TOKEN"], "profile": "work"}})
        self.assertEqual(origins["credentials"], "local")
        for key, value in (("version", "1"), ("organization", "Acme"), ("mode", "local")):
            with self.subTest(key=key):
                self.assertEqual(values[key], value)
                self.assertEqual(origins[key], "atlas")
        for key in ("language", "stale_days", "categories", "collectors", "redaction"):
            with self.subTest(key=key):
                self.assertEqual(values[key], DEFAULTS[key])
                self.assertEqual(origins[key], "padrão")

    def test_atlas_config_value_wins_over_the_default(self):
        """SPEC-0032:UT-01"""
        (self.atlas / "atlas-config.yml").write_text(
            "version: 1\norganization: Acme\nmode: repo\nstale_days: 30\n", encoding="utf-8")
        config = fn("load_config")(self.config_home)
        self.assertEqual(normalize(config["values"])["stale_days"], "30")
        self.assertEqual(config["origins"]["stale_days"], "atlas")
        self.assertEqual(config["origins"]["language"], "padrão")

    def test_config_home_defaults_to_the_environment_variable(self):
        """SPEC-0032:UT-01"""
        with mock.patch.dict(os.environ, {"ATLAS_CONFIG_HOME": str(self.config_home)}):
            config = fn("load_config")()
        self.assertEqual(config["values"]["atlas"], str(self.atlas))
        self.assertEqual(config["origins"]["organization"], "atlas")


class ValidateCredentialsTest(unittest.TestCase):
    def test_variable_names_and_profiles_are_accepted(self):
        """SPEC-0032:UT-02"""
        validate = fn("validate_credentials")
        self.assertIsNone(validate({}))
        self.assertIsNone(validate({"github": {"env": ["GITHUB_TOKEN", "_GH2"], "profile": "work"},
                                    "argocd": {"env": ["ARGOCD_AUTH_TOKEN"]},
                                    "aws": {"profile": "acme-prod"}}))

    def test_a_value_instead_of_a_variable_name_is_rejected_without_echoing_it(self):
        """SPEC-0032:UT-02"""
        validate, error = fn("validate_credentials"), fn("AtlasError")
        for value in ("ghp_abc", "ghp_0123456789abcdef", "1TOKEN", "GH-TOKEN", "GH TOKEN", ""):
            with self.subTest(value=value):
                with self.assertRaises(error) as caught:
                    validate({"github": {"env": ["GITHUB_TOKEN", value], "profile": "work"}})
                message = str(caught.exception)
                self.assertIn("credentials aceita só nomes de variável: github", message)
                if value:
                    self.assertNotIn(value, message)

    def test_invalid_local_credentials_fail_and_nothing_is_written(self):
        """SPEC-0032:UT-02"""
        tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        atlas, home = tmp / "acme-atlas", tmp / "config-home"
        atlas.mkdir()
        home.mkdir()
        (home / "config.yml").write_text(
            f'atlas: "{atlas}"\ncredentials:\n  github: {{env: ["ghp_abc"]}}\n', encoding="utf-8")
        (atlas / "atlas-config.yml").write_text(atlas_config_text(), encoding="utf-8")
        before = snapshot(tmp)
        with self.assertRaises(fn("AtlasError")) as caught:
            fn("load_config")(home)
        self.assertIn("credentials aceita só nomes de variável: github", str(caught.exception))
        self.assertNotIn("ghp_abc", str(caught.exception))
        self.assertEqual(snapshot(tmp), before, "a validação gravou algo")


class AtlasConfigWithoutAbsolutePathsTest(unittest.TestCase):
    def test_generated_atlas_config_has_no_absolute_path(self):
        """SPEC-0032:UT-03"""
        render, parse = fn("render_atlas_config"), fn("parse_yaml")
        for organization, mode in (("Acme", "repo"), ("Acme Corp", "local")):
            with self.subTest(mode=mode):
                text = render(organization, mode)
                self.assertNotIn("/Users/", text)
                self.assertNotIn("/home/", text)
                self.assertNotIn(":\\", text)
                data = normalize(parse(text))
                for key in SHARED_KEYS:
                    self.assertIn(key, data)
                self.assertEqual(data["version"], "1")
                self.assertEqual(data["organization"], organization)
                self.assertEqual(data["mode"], mode)
                self.assertEqual(absolute_values(data), [])


SAMPLE = """# configuração de exemplo
version: 1
organization: "Acme: Platform"   # aspas por causa do ': '
mode: repo
language: auto   # idioma do conteúdo
stale_days: 14
categories: [code, delivery]
collectors:
  - id: github
    category: code
    command: ["python3", "{skill}/assets/collectors/github.py", "--org", "acme"]
  - id: argocd
    category: delivery
    command: [argocd-collector, --server, https://argocd.example.com]
redaction: {extra_patterns: []}
atlas: /data/acme-atlas
credentials:
  github: {env: [GITHUB_TOKEN, GH_ENTERPRISE_TOKEN], profile: work}
  aws:
    profile: acme-prod
steps:
  - one
  - "two: three"
url: https://example.com/a?b=c
hash: "a # b"
empty: {}
"""

EXPECTED = {
    "version": "1",
    "organization": "Acme: Platform",
    "mode": "repo",
    "language": "auto",
    "stale_days": "14",
    "categories": ["code", "delivery"],
    "collectors": [
        {"id": "github", "category": "code",
         "command": ["python3", "{skill}/assets/collectors/github.py", "--org", "acme"]},
        {"id": "argocd", "category": "delivery",
         "command": ["argocd-collector", "--server", "https://argocd.example.com"]},
    ],
    "redaction": {"extra_patterns": []},
    "atlas": "/data/acme-atlas",
    "credentials": {
        "github": {"env": ["GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN"], "profile": "work"},
        "aws": {"profile": "acme-prod"},
    },
    "steps": ["one", "two: three"],
    "url": "https://example.com/a?b=c",
    "hash": "a # b",
    "empty": {},
}


class YamlTest(unittest.TestCase):
    def test_parser_reads_the_subset_used_by_the_configuration_files(self):
        """SPEC-0032:UT-04"""
        self.assertEqual(normalize(fn("parse_yaml")(SAMPLE)), EXPECTED)

    def test_writer_round_trip_preserves_the_data(self):
        """SPEC-0032:UT-04"""
        parse, dump = fn("parse_yaml"), fn("dump_yaml")
        data = {key: value for key, value in EXPECTED.items() if key != "collectors"}
        tricky = dict(data, dash="-x", empty_list=[], quote='say "hi"', colon="a: b", path="C:\\x")
        local = {"atlas": "/data/acme-atlas", "credentials": EXPECTED["credentials"]}
        for sample in (data, tricky, local):
            with self.subTest(keys=sorted(sample)):
                text = dump(sample)
                self.assertIsInstance(text, str)
                self.assertEqual(normalize(parse(text)), sample)
                self.assertEqual(normalize(parse(dump(parse(text)))), sample)

    def test_model_atlas_config_is_read_and_rewritten_keeping_values_and_comments(self):
        """SPEC-0032:UT-04"""
        self.assertTrue(ASSET_CONFIG.is_file(), f"{ASSET_CONFIG} não existe (SPEC-0032)")
        model = ASSET_CONFIG.read_text(encoding="utf-8")
        parse, render = fn("parse_yaml"), fn("render_atlas_config")
        data = normalize(parse(model))
        for key in SHARED_KEYS:
            self.assertIn(key, data)
        for key, value in DEFAULTS.items():
            self.assertEqual(data[key], value, key)
        model_comments = comments(model)
        self.assertTrue(model_comments, "assets/atlas-config.yml sem comentários para orientar quem edita")

        text = render("Acme", "local")
        for comment in model_comments:
            self.assertIn(comment, text, "render_atlas_config perdeu um comentário do modelo")
        rendered = normalize(parse(text))
        self.assertEqual(rendered["organization"], "Acme")
        self.assertEqual(rendered["mode"], "local")
        rest = {k: v for k, v in data.items() if k not in ("organization", "mode")}
        self.assertEqual({k: v for k, v in rendered.items() if k not in ("organization", "mode")}, rest)


# --------------------------------------------------------------------------- integração (CLI)


class CliTestCase(unittest.TestCase):
    def setUp(self):
        if not SCRIPT.exists():
            self.fail(f"{SCRIPT} não existe (SPEC-0032)")
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)

    def assertExit(self, result, code):
        self.assertEqual(result.returncode, code, output(result))
        self.assertNotIn("Traceback", output(result))


class NewAtlasTest(CliTestCase):
    def assert_structure(self, atlas):
        for name in STRUCTURE_DIRS:
            self.assertTrue((atlas / name).is_dir(), f"{name}/ não foi criada")
        for name in STRUCTURE_FILES:
            self.assertTrue((atlas / name).is_file(), f"{name} não foi criado")
        for name in ("ATLAS.md", "glossary.md"):
            text = (atlas / name).read_text(encoding="utf-8")
            regions = REGION_BEGIN.findall(text)
            self.assertTrue(regions, f"{name} sem região <!-- atlas:begin <nome> -->")
            for region in regions:
                self.assertIn(f"<!-- atlas:end {region} -->", text, f"{name}: região {region} sem fim")

    def test_init_creates_the_structure_and_both_configs(self):
        """SPEC-0032:IT-01"""
        out = self.box.new_atlas()
        atlas = self.box.atlas
        self.assertExit(out, 0)
        self.assertIn(f"Atlas criado em {atlas}", out.stdout)
        for name in ("ATLAS.md", "atlas-config.yml", "glossary.md", "services", "snapshots"):
            self.assertIn(name, out.stdout, "init não disse o que foi criado")
        self.assert_structure(atlas)

        shared = (atlas / "atlas-config.yml").read_text(encoding="utf-8")
        self.assertNotIn(str(self.box.root), shared)
        self.assertEqual(absolute_values(fn("parse_yaml")(shared)), [])
        for comment in comments(ASSET_CONFIG.read_text(encoding="utf-8")):
            self.assertIn(comment, shared, "atlas-config.yml perdeu os comentários do modelo")

        local = self.box.config_home / "config.yml"
        self.assertTrue(local.is_file(), "configuração local não foi gravada em $ATLAS_CONFIG_HOME")
        self.assertIn(str(atlas), local.read_text(encoding="utf-8"))
        self.assertFalse((self.box.home / ".config" / "org-atlas").exists(), "ignorou ATLAS_CONFIG_HOME")

        config = self.box.config_json()
        values, origins = normalize(config["values"]), config["origins"]
        self.assertEqual(values["atlas"], str(atlas))
        self.assertEqual(values["organization"], "Acme")
        self.assertEqual(values["mode"], "repo")
        for key, value in DEFAULTS.items():
            self.assertEqual(values[key], value, key)
            self.assertEqual(origins[key], "atlas", key)

    def test_init_creates_a_missing_folder_in_local_mode(self):
        """SPEC-0032:IT-01"""
        out = self.box.init(mode="local")
        self.assertExit(out, 0)
        self.assertIn(f"Atlas criado em {self.box.atlas}", out.stdout)
        self.assert_structure(self.box.atlas)
        self.assertEqual(normalize(self.box.config_json()["values"])["mode"], "local")

    def test_invalid_mode_exits_2_with_the_options(self):
        """SPEC-0032:IT-01"""
        self.box.atlas.mkdir(parents=True)
        out = self.box.init(mode="cloud")
        self.assertExit(out, 2)
        self.assertIn("repo", output(out))
        self.assertIn("local", output(out))
        self.assertEqual(os.listdir(self.box.atlas), [])
        self.assertFalse((self.box.config_home / "config.yml").exists())


class ReinitTest(CliTestCase):
    def test_same_init_again_only_writes_the_local_config(self):
        """SPEC-0032:IT-02"""
        self.box.new_atlas()
        before = snapshot(self.box.atlas)
        other_home = self.box.root / "config-home-2"
        out = self.box.init(config_home=other_home)
        self.assertExit(out, 0)
        self.assertIn("Atlas já configurado", out.stdout)
        self.assertTrue((other_home / "config.yml").is_file())
        self.assertIn(str(self.box.atlas), (other_home / "config.yml").read_text(encoding="utf-8"))
        self.assertEqual(snapshot(self.box.atlas), before, "init repetido mexeu no atlas")

    def test_different_atlas_config_needs_force_and_force_keeps_a_backup(self):
        """SPEC-0032:IT-02"""
        self.box.new_atlas()
        atlas = self.box.atlas
        shared = atlas / "atlas-config.yml"
        edited = shared.read_text(encoding="utf-8").rstrip("\n") + "\nnote: editado à mão\n"
        shared.write_text(edited, encoding="utf-8")
        before = snapshot(atlas)

        for extra_org in ("Acme", "Other Org"):
            with self.subTest(org=extra_org):
                out = self.box.init(org=extra_org)
                self.assertExit(out, 2)
                self.assertIn("atlas-config.yml já existe — use --join ou --force", output(out))
                self.assertEqual(snapshot(atlas), before)
                self.assertFalse((atlas / "atlas-config.yml.bak").exists())

        out = self.box.init("--force")
        self.assertExit(out, 0)
        self.assertEqual((atlas / "atlas-config.yml.bak").read_text(encoding="utf-8"), edited)
        new_text = shared.read_text(encoding="utf-8")
        self.assertNotIn("editado à mão", new_text)
        self.assertIn("Acme", new_text)
        after = snapshot(atlas)
        untouched = {k: v for k, v in before.items() if k != "atlas-config.yml"}
        self.assertEqual({k: v for k, v in after.items() if k not in ("atlas-config.yml", "atlas-config.yml.bak")},
                         untouched, "--force sobrescreveu algo além do atlas-config.yml")

    def test_folder_with_content_and_no_atlas_config_exits_2(self):
        """SPEC-0032:IT-02"""
        self.box.atlas.mkdir(parents=True)
        (self.box.atlas / "notes.txt").write_text("conteúdo de outra coisa\n", encoding="utf-8")
        out = self.box.init()
        self.assertExit(out, 2)
        self.assertIn("pasta não está vazia — escolha outra pasta", output(out))
        self.assertEqual(os.listdir(self.box.atlas), ["notes.txt"])
        self.assertFalse((self.box.config_home / "config.yml").exists())


class JoinTest(CliTestCase):
    def test_join_writes_only_the_local_config(self):
        """SPEC-0032:IT-03"""
        self.box.new_atlas()
        before = snapshot(self.box.atlas)
        second = self.box.root / "config-home-2"
        out = self.box.run("init", "--join", "--atlas", self.box.atlas, config_home=second)
        self.assertExit(out, 0)
        self.assertEqual(snapshot(self.box.atlas), before, "join escreveu no atlas")
        self.assertIn(str(self.box.atlas), (second / "config.yml").read_text(encoding="utf-8"))
        first, other = self.box.config_json(), self.box.config_json(config_home=second)
        self.assertEqual(other["values"]["atlas"], str(self.box.atlas))
        self.assertEqual(other["values"]["organization"], first["values"]["organization"])
        self.assertEqual(other["values"]["mode"], first["values"]["mode"])

    def test_join_without_atlas_config_exits_2(self):
        """SPEC-0032:IT-03"""
        empty = self.box.root / "empty"
        empty.mkdir()
        third = self.box.root / "config-home-3"
        out = self.box.run("init", "--join", "--atlas", empty, config_home=third)
        self.assertExit(out, 2)
        self.assertIn("atlas sem atlas-config.yml — rode init", output(out))
        self.assertFalse((third / "config.yml").exists())
        self.assertEqual(os.listdir(empty), [])


class ConfigTest(CliTestCase):
    def test_config_and_doctor_without_local_config_exit_3(self):
        """SPEC-0032:IT-04"""
        self.box.config_home.mkdir()
        for args in (("config",), ("config", "--json"), ("doctor",), ("doctor", "--json")):
            with self.subTest(args=args):
                out = self.box.run(*args)
                self.assertExit(out, 3)
                if args[0] == "config":
                    self.assertIn(NOT_CONFIGURED, output(out))

    def write_layers(self):
        self.box.atlas.mkdir(parents=True)
        (self.box.atlas / "atlas-config.yml").write_text(
            "version: 1\norganization: Acme\nmode: local\n", encoding="utf-8")
        self.box.write_local(f'atlas: "{self.box.atlas}"\n'
                             "credentials:\n"
                             "  github: {env: [GITHUB_TOKEN], profile: work}\n")

    def test_config_json_shows_the_origin_of_each_value_and_credentials_only_by_name(self):
        """SPEC-0032:IT-04"""
        self.write_layers()
        env = {"GITHUB_TOKEN": SECRET}
        config = self.box.config_json(env=env)
        values, origins = normalize(config["values"]), config["origins"]
        self.assertEqual((values["atlas"], origins["atlas"]), (str(self.box.atlas), "local"))
        self.assertEqual(values["credentials"], {"github": {"env": ["GITHUB_TOKEN"], "profile": "work"}})
        self.assertEqual(origins["credentials"], "local")
        self.assertEqual((values["organization"], origins["organization"]), ("Acme", "atlas"))
        self.assertEqual((values["mode"], origins["mode"]), ("local", "atlas"))
        self.assertEqual((values["stale_days"], origins["stale_days"]), ("14", "padrão"))
        self.assertEqual((values["language"], origins["language"]), ("auto", "padrão"))

        for args in (("config",), ("config", "--json")):
            with self.subTest(args=args):
                out = self.box.run(*args, env=env)
                self.assertExit(out, 0)
                self.assertNotIn(SECRET, output(out))
                self.assertIn("GITHUB_TOKEN", out.stdout)
        text = self.box.run("config", env=env).stdout
        self.assertIn("Acme", text)
        for origin in ("local", "atlas", "padrão"):
            self.assertIn(origin, text, "config sem a origem dos valores")

    def test_config_with_a_credential_value_exits_2_and_writes_nothing(self):
        """SPEC-0032:UT-02"""
        self.box.atlas.mkdir(parents=True)
        (self.box.atlas / "atlas-config.yml").write_text(atlas_config_text(), encoding="utf-8")
        self.box.write_local(f'atlas: "{self.box.atlas}"\ncredentials:\n  github: {{env: ["ghp_abc"]}}\n')
        before = snapshot(self.box.root)
        out = self.box.run("config")
        self.assertExit(out, 2)
        self.assertIn("credentials aceita só nomes de variável: github", output(out))
        self.assertNotIn("ghp_abc", output(out))
        self.assertEqual(snapshot(self.box.root), before)


class DoctorTest(CliTestCase):
    COLLECTORS = ("collectors:\n"
                  "  - id: fake\n"
                  "    category: code\n"
                  f"    command: [{MISSING_EXE}, --org, acme]\n")

    def prepare(self):
        """Atlas criado por init (sem git), um coletor sem executável e duas variáveis declaradas."""
        self.box.new_atlas()
        (self.box.atlas / "atlas-config.yml").write_text(atlas_config_text(collectors=self.COLLECTORS),
                                                         encoding="utf-8")
        self.box.write_local(f'atlas: "{self.box.atlas}"\n'
                             "credentials:\n"
                             "  fake: {env: [ATLAS_TEST_TOKEN_0032, ATLAS_TEST_UNSET_0032], profile: work}\n")

    def doctor(self, *args):
        return self.box.run("doctor", *args, env={"ATLAS_TEST_TOKEN_0032": SECRET},
                            unset=("ATLAS_TEST_UNSET_0032",))

    def test_doctor_reports_each_item_and_never_prints_a_credential_value(self):
        """SPEC-0032:IT-05"""
        self.prepare()
        out = self.doctor()
        self.assertExit(out, 1)
        self.assertNotIn(SECRET, output(out))
        rows = doctor_lines(out.stdout)
        self.assertTrue(rows, out.stdout)

        ok = [item for status, item, _ in rows if status == "OK"]
        for item in ("configuração local", "pasta do atlas", "atlas-config.yml", "estrutura"):
            self.assertTrue(any(i.startswith(item) for i in ok), f"OK {item} ausente:\n{out.stdout}")
        self.assertTrue(any(status == "AVISO" and item.startswith("git") for status, item, _ in rows),
                        f"AVISO git ausente (pasta não é repositório git):\n{out.stdout}")
        self.assertTrue(any(status == "ERRO" and "fake" in item + detail and MISSING_EXE in item + detail
                            for status, item, detail in rows),
                        f"ERRO do coletor sem executável ausente:\n{out.stdout}")

        defined = [(s, i + " " + d) for s, i, d in rows if "ATLAS_TEST_TOKEN_0032" in i + d]
        self.assertEqual(len(defined), 1, out.stdout)
        self.assertEqual(defined[0][0], "OK", out.stdout)
        self.assertIn("definida", defined[0][1])
        self.assertNotIn("não definida", defined[0][1])
        unset = [(s, i + " " + d) for s, i, d in rows if "ATLAS_TEST_UNSET_0032" in i + d]
        self.assertEqual(len(unset), 1, out.stdout)
        self.assertIn(unset[0][0], ("AVISO", "ERRO"), out.stdout)
        self.assertIn("não definida", unset[0][1])

        out = self.doctor("--json")
        self.assertExit(out, 1)
        self.assertNotIn(SECRET, output(out))
        json.loads(out.stdout)

    def test_missing_atlas_folder_is_an_error_without_traceback(self):
        """SPEC-0032:IT-05"""
        self.box.new_atlas()
        shutil.rmtree(self.box.atlas)
        out = self.box.run("doctor")
        self.assertExit(out, 1)
        errors = [item for status, item, _ in doctor_lines(out.stdout) if status == "ERRO"]
        self.assertTrue(any(item.startswith("pasta do atlas") for item in errors), out.stdout)
        self.assertIn(str(self.box.atlas), out.stdout)


if __name__ == "__main__":
    unittest.main()
