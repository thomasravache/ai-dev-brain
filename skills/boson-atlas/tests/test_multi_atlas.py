"""Vários atlas na configuração local e escolha por --atlas (SPEC-0079: CH-01, UT-01 a UT-08, IT-01, IT-02, CT-01
e E2E-01; ADR-0021).

Contrato (seção 6 da spec) que os testes fixam:
    Configuração local, forma de vários atlas:
        default: <nome>                  # opcional; precisa existir em atlases
        atlases:
          <nome>:                        # [a-z0-9][a-z0-9-]{0,62}
            atlas: <caminho absoluto>
            credentials: {...}           # só nomes
    Forma de um atlas só (continua lida e gravada enquanto houver uma entrada): atlas: + credentials:; o nome da
        entrada é a organization do atlas-config.yml em minúsculas com o que não for [a-z0-9-] trocado por "-"
        (ilegível -> "default").
    As duas formas juntas, nome inválido, default sem entrada ou chave desconhecida numa entrada -> exit 2 com a
        chave.
    Ordem de escolha (todos os comandos menos init): --atlas <nome|caminho> -> ATLAS_NAME -> default -> atlas
        único. Nome ou caminho fora da lista -> exit 3 ("atlas não configurado nesta máquina: <x> — rode init
        --join --atlas <caminho> (atlas configurados: a, b)"); vários sem escolha -> exit 2 ("vários atlas
        configurados (a, b) e nenhum escolhido — use --atlas <nome>, ATLAS_NAME ou config --set-default <nome>").
    init/init --join [--name N] [--default]: acrescenta sem apagar; a primeira entrada vira default; nome ou caminho
        já usado por outra entrada -> exit 2 sem mudar o arquivo; 1 entrada -> forma de um atlas só; 2 ou mais ->
        forma nova, com config.yml.bak da forma antiga.
    config --json: "values", "origins" + "atlas_name", "selected_by" (option | env | default | single) e
        "atlases": [{"name", "atlas", "default"}] por nome. config --list: todos os atlas e o escolhido ("nenhum"
        sem escolha, sem falhar). config --set-default <nome>: nome inexistente -> exit 2.
    doctor: linha "Atlas configurados: N (a, b)"; pasta de outro atlas ausente -> AVISO com o nome.

Isolamento: HOME, XDG_CONFIG_HOME e ATLAS_CONFIG_HOME temporários (helpers.Sandbox; run_default para a pasta
padrão), ATLAS_NAME sempre tirado do ambiente salvo quando o teste o define. Organizações genéricas (Acme, Globex);
coletor generic com fatos locais; sem rede.
"""
import json
import shutil
import unittest
from pathlib import Path

from helpers import (
    NEW_CONFIG_DIR,
    Sandbox,
    doctor_lines,
    fn,
    output,
)

SPEC = "SPEC-0079"
EXPECTED_HEADER = f"# {NEW_CONFIG_DIR} — configuração local desta máquina"


def facts_config(organization="Acme", mode="repo") -> str:
    """atlas-config.yml com o coletor generic lendo {atlas}/facts/services.json."""
    command = ["python3", "{skill}/assets/collectors/generic.py", "--facts", "{atlas}/facts/services.json",
               "--category", "runtime", "--source", "facts"]
    return (f"version: 1\norganization: {organization}\nmode: {mode}\nlanguage: auto\nstale_days: 14\n"
            "categories: [code, delivery]\ncollectors:\n  - id: facts\n    category: runtime\n"
            "    command: [" + ", ".join(json.dumps(a) for a in command) + "]\n    timeout: 60\n"
            "redaction: {extra_patterns: []}\n")


def write_facts(atlas_dir: Path, service: str, datastore: str) -> None:
    folder = atlas_dir / "facts"
    folder.mkdir(exist_ok=True)
    facts = {"entities": [{"kind": "service", "id": service, "name": service, "attrs": {}},
                          {"kind": "datastore", "id": datastore, "name": datastore, "attrs": {}}],
             "relations": [{"from": f"service:{service}", "to": f"datastore:{datastore}", "type": "writes"}]}
    (folder / "services.json").write_text(json.dumps(facts), encoding="utf-8")


def parse(path: Path) -> dict:
    return fn("parse_yaml")(path.read_text(encoding="utf-8"))


class MultiAtlasCase(unittest.TestCase):
    def setUp(self):
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        self.local = self.box.config_home / "config.yml"

    # ------------------------------------------------------------ CLI

    def cli(self, *args, env=None, default=False, config_home=None):
        """atlas.py como processo; ATLAS_NAME só existe quando `env` o define."""
        unset = ["ATLAS_NAME"] if "ATLAS_NAME" not in (env or {}) else []
        if default:
            unset.append("ATLAS_CONFIG_HOME")
        return self.box.run(*args, env=env, unset=unset, config_home=config_home)

    def assertExit(self, result, code):
        self.assertEqual(result.returncode, code, output(result))
        self.assertNotIn("Traceback", output(result))
        self.assertNotIn("usage:", result.stderr, "erro do argparse, não do contrato")

    def config_json(self, *args, env=None):
        out = self.cli("config", "--json", *args, env=env)
        self.assertExit(out, 0)
        return json.loads(out.stdout)

    # ------------------------------------------------------------ fixtures

    def make_atlas(self, path: Path, organization: str, service=None, datastore=None, scan=False) -> Path:
        """Atlas criado por init numa configuração de rascunho (não toca a do teste); com `service`, o coletor
        generic e os fatos; com `scan`, já escaneado (graph.json) pela configuração de rascunho."""
        path.mkdir(parents=True, exist_ok=True)
        scratch = self.box.root / "scratch" / path.name
        out = self.box.init(atlas=path, org=organization, config_home=scratch)
        self.assertExit(out, 0)
        if service:
            (path / "atlas-config.yml").write_text(facts_config(organization), encoding="utf-8")
            write_facts(path, service, datastore or f"{service}-db")
        if scan:
            self.assertExit(self.cli("scan", config_home=scratch), 0)
        return path

    def two_atlases(self, default="acme", acme_credentials="{}", globex_credentials="{}", **kwargs):
        """acme e globex na forma nova (gravada pelo teste); globex fica sob o HOME (para o caminho com ~)."""
        self.acme = self.make_atlas(self.box.root / "work" / "acme-atlas", "Acme", **kwargs.get("acme", {}))
        self.globex = self.make_atlas(self.box.home / "work" / "globex-atlas", "Globex",
                                      **kwargs.get("globex", {}))
        head = f"default: {default}\n" if default else ""
        text = (f"{head}atlases:\n"
                f"  acme:\n    atlas: \"{self.acme}\"\n    credentials: {acme_credentials}\n"
                f"  globex:\n    atlas: \"{self.globex}\"\n    credentials: {globex_credentials}\n")
        return self.box.write_local(text)


# ---------------------------------------------------------------- caracterização (CH-01)

class CharacterizationTest(MultiAtlasCase):
    def test_single_atlas_configuration_keeps_todays_outputs_and_file(self):
        """SPEC-0079:CH-01 — configuração de um atlas só: config --json, context, lint e init --join como hoje."""
        for default in (False, True):
            with self.subTest(pasta_padrao=default):
                self.box = Sandbox()
                self.addCleanup(self.box.cleanup)
                local = (self.box.default_dir(NEW_CONFIG_DIR) if default else self.box.config_home) / "config.yml"
                atlas_dir = self.box.atlas
                atlas_dir.mkdir(parents=True)
                out = self.cli("init", "--atlas", atlas_dir, "--org", "Acme", "--mode", "repo", default=default)
                self.assertExit(out, 0)
                self.assertTrue(local.is_file(), output(out))
                written = local.read_text(encoding="utf-8")
                self.assertTrue(written.startswith(EXPECTED_HEADER), written)
                self.assertEqual(parse(local), {"atlas": str(atlas_dir), "credentials": {}})
                (atlas_dir / "atlas-config.yml").write_text(facts_config(), encoding="utf-8")
                write_facts(atlas_dir, "payments-api", "payments-db")
                with_credentials = fn("render_local_config")(str(atlas_dir), {"facts": {"env": ["A_TOKEN"]}})
                local.write_text(with_credentials, encoding="utf-8")

                out = self.cli("config", "--json", default=default)
                self.assertExit(out, 0)
                data = json.loads(out.stdout)
                self.assertEqual(data["values"]["atlas"], str(atlas_dir))
                self.assertEqual(data["origins"]["atlas"], "local")
                self.assertEqual(data["values"]["organization"], "Acme")
                self.assertEqual(data["values"]["credentials"], {"facts": {"env": ["A_TOKEN"]}})

                out = self.cli("config", default=default)
                self.assertExit(out, 0)
                self.assertIn(f"atlas: {atlas_dir} (local)", out.stdout)

                self.assertExit(self.cli("scan", default=default), 0)
                out = self.cli("context", "payments", "--json", default=default)
                self.assertExit(out, 0)
                self.assertIn("service:payments-api", [s["key"] for s in json.loads(out.stdout)["services"]])

                out = self.cli("lint", "--json", default=default)
                self.assertExit(out, 0)
                self.assertTrue(json.loads(out.stdout)["ok"], out.stdout)

                out = self.cli("init", "--join", "--atlas", atlas_dir, default=default)
                self.assertExit(out, 0)
                self.assertIn(f"Máquina ligada ao atlas em {atlas_dir} (Acme, modo repo)", out.stdout)
                self.assertEqual(local.read_text(encoding="utf-8"), with_credentials,
                                 "init --join no mesmo atlas grava o mesmo arquivo de hoje")
                self.assertFalse(local.with_name("config.yml.bak").exists(), "uma entrada: sem .bak")


# ---------------------------------------------------------------- mensagens do contrato (seção 6)

NAMES = "acme, globex"
NO_CHOICE = (f"vários atlas configurados ({NAMES}) e nenhum escolhido — use --atlas <nome>, ATLAS_NAME ou "
             "config --set-default <nome>")
UNKNOWN_PREFIX = "atlas não configurado nesta máquina: "
UNKNOWN_STEP = "rode init --join --atlas <caminho>"
UNKNOWN_LIST = f"(atlas configurados: {NAMES})"
SELECTED_BY = ("option", "env", "default", "single")
A_CREDENTIALS = "\n      facts: {env: [A_TOKEN]}"
B_CREDENTIALS = "\n      facts: {env: [B_TOKEN]}"


# ---------------------------------------------------------------- leitura (UT-01, UT-02)

class ReadTest(MultiAtlasCase):
    def test_single_form_is_one_entry_named_after_the_organization(self):
        """SPEC-0079:UT-01 — forma de um atlas só = uma entrada com o nome da organization, escolhida (single)."""
        path = self.box.root / "work" / "acme-corp-atlas"
        path.mkdir(parents=True)
        self.assertExit(self.box.init(atlas=path, org="Acme Corp"), 0)
        self.assertEqual(set(parse(self.local)), {"atlas", "credentials"}, "fixture: forma de um atlas só")
        data = self.config_json()
        self.assertEqual(data.get("atlas_name"), "acme-corp")
        self.assertEqual(data.get("selected_by"), "single")
        self.assertEqual([(a.get("name"), a.get("atlas")) for a in data.get("atlases") or []],
                         [("acme-corp", str(path))])
        self.assertEqual(data["values"]["atlas"], str(path))

        bare = self.box.root / "work" / "bare-atlas"  # sem atlas-config.yml: organization ilegível
        bare.mkdir(parents=True)
        self.box.write_local(fn("render_local_config")(str(bare), {}))
        data = self.config_json()
        self.assertEqual(data.get("atlas_name"), "default")
        self.assertEqual(data.get("selected_by"), "single")

    def test_invalid_local_configuration_exits_2_naming_the_key(self):
        """SPEC-0079:UT-02 — duas formas juntas, nome inválido, default sem entrada, chave desconhecida: exit 2."""
        acme = self.make_atlas(self.box.root / "work" / "acme-atlas", "Acme")
        entry = f"    atlas: \"{acme}\"\n    credentials: {{}}\n"
        cases = {
            "duas formas": (f"atlas: \"{acme}\"\ncredentials: {{}}\natlases:\n  acme:\n{entry}", "atlases"),
            "nome inválido": (f"atlases:\n  Acme_Corp:\n{entry}", "Acme_Corp"),
            "default sem entrada": (f"default: initech\natlases:\n  acme:\n{entry}", "initech"),
            "chave desconhecida": (f"atlases:\n  acme:\n{entry}    tokenz: x\n", "tokenz"),
        }
        for case, (text, key) in cases.items():
            self.box.write_local(text)
            for args in (("config", "--json"), ("scan",), ("lint",), ("context", "api")):
                with self.subTest(caso=case, comando=args[0]):
                    out = self.cli(*args)
                    self.assertExit(out, 2)
                    self.assertIn(key, output(out))


# ---------------------------------------------------------------- escolha (UT-03, UT-04)

class SelectionTest(MultiAtlasCase):
    def test_option_beats_env_which_beats_default(self):
        """SPEC-0079:UT-03 — sem opção: default; ATLAS_NAME; --atlas vence ATLAS_NAME; --atlas por caminho."""
        self.two_atlases()
        cases = [
            ("sem opção", (), {}, "acme", "default"),
            ("ATLAS_NAME", (), {"ATLAS_NAME": "globex"}, "globex", "env"),
            ("--atlas vence ATLAS_NAME", ("--atlas", "globex"), {"ATLAS_NAME": "acme"}, "globex", "option"),
            ("--atlas caminho relativo", ("--atlas", "home/work/globex-atlas"), {}, "globex", "option"),
            ("--atlas caminho com ./", ("--atlas", "./home/work/globex-atlas"), {}, "globex", "option"),
            ("--atlas caminho com ~", ("--atlas", "~/work/globex-atlas"), {}, "globex", "option"),
        ]
        paths = {"acme": str(self.acme), "globex": str(self.globex)}
        for case, args, env, name, by in cases:
            with self.subTest(caso=case):
                data = self.config_json(*args, env=env)
                self.assertEqual((data.get("atlas_name"), data.get("selected_by")), (name, by))
                self.assertEqual(data["values"]["atlas"], paths[name])

    def test_no_choice_exits_2_and_unknown_choice_exits_3(self):
        """SPEC-0079:UT-04 — vários sem escolha: exit 2 com a lista e os passos; fora da lista: exit 3."""
        self.two_atlases(default=None)
        for args in (("config", "--json"), ("context", "api"), ("scan",), ("lint",)):
            with self.subTest(sem_escolha=args[0]):
                out = self.cli(*args)
                self.assertExit(out, 2)
                self.assertIn(NO_CHOICE, output(out))

        other = self.box.root / "work" / "initech-atlas"
        other.mkdir(parents=True)
        cases = [
            ("--atlas nome", ("--atlas", "initech"), {}, "initech"),
            ("ATLAS_NAME nome", (), {"ATLAS_NAME": "initech"}, "initech"),
            ("--atlas caminho", ("--atlas", str(other)), {}, None),
        ]
        for case, args, env, shown in cases:
            for command in (("config", "--json"), ("context", "api")):
                with self.subTest(caso=case, comando=command[0]):
                    out = self.cli(*command, *args, env=env)
                    self.assertExit(out, 3)
                    text = output(out)
                    self.assertIn(UNKNOWN_PREFIX + (shown or ""), text)
                    self.assertIn(UNKNOWN_STEP, text)
                    self.assertIn(UNKNOWN_LIST, text)

        out = self.cli("config", "--list")
        self.assertExit(out, 0)
        for name, path in (("acme", self.acme), ("globex", self.globex)):
            self.assertIn(name, out.stdout)
            self.assertIn(str(path), out.stdout)
        self.assertIn("nenhum", out.stdout)


# ---------------------------------------------------------------- init, set-default e doctor (UT-05 a UT-08)

class WriteTest(MultiAtlasCase):
    def test_join_of_a_second_atlas_switches_to_the_new_form_with_a_backup(self):
        """SPEC-0079:UT-05 — init --join de outro atlas com --name: forma nova, a primeira entrada intacta, .bak."""
        credentials = {"facts": {"env": ["A_TOKEN"]}}
        for make_default in (False, True):
            with self.subTest(default=make_default):
                self.box = Sandbox()
                self.addCleanup(self.box.cleanup)
                self.local = self.box.config_home / "config.yml"
                acme = self.make_atlas(self.box.root / "work" / "acme-atlas", "Acme")
                globex = self.make_atlas(self.box.root / "work" / "globex-atlas", "Globex")
                self.box.write_local(fn("render_local_config")(str(acme), credentials))
                before = self.local.read_bytes()

                extra = ("--default",) if make_default else ()
                out = self.cli("init", "--join", "--atlas", globex, "--name", "globex", *extra)
                self.assertExit(out, 0)
                data = parse(self.local)
                self.assertEqual(set(data), {"default", "atlases"}, "forma nova")
                self.assertEqual(data["default"], "globex" if make_default else "acme")
                self.assertEqual(sorted(data["atlases"]), ["acme", "globex"])
                self.assertEqual(data["atlases"]["acme"], {"atlas": str(acme), "credentials": credentials},
                                 "a entrada anterior e as credenciais dela não mudam")
                self.assertEqual(data["atlases"]["globex"].get("atlas"), str(globex))
                self.assertEqual(data["atlases"]["globex"].get("credentials") or {}, {},
                                 "as credenciais de acme não passam para globex")
                backup = self.local.with_name("config.yml.bak")
                self.assertTrue(backup.is_file(), "a forma antiga fica em config.yml.bak")
                self.assertEqual(backup.read_bytes(), before)

    def test_name_or_path_in_use_by_another_entry_exits_2_without_writing(self):
        """SPEC-0079:UT-06 — --name de outro caminho, ou caminho já com outro nome: exit 2 e o arquivo não muda."""
        self.two_atlases()
        before = self.local.read_bytes()
        cases = [
            ("nome em uso", self.globex, "acme", "acme"),
            ("caminho em uso", self.acme, "initech", str(self.acme)),
        ]
        for case, path, name, shown in cases:
            with self.subTest(caso=case):
                out = self.cli("init", "--join", "--atlas", path, "--name", name)
                self.assertExit(out, 2)
                self.assertIn(shown, output(out))
                self.assertEqual(self.local.read_bytes(), before)
                self.assertFalse(self.local.with_name("config.yml.bak").exists())

    def test_set_default_switches_the_default_and_rejects_an_unknown_name(self):
        """SPEC-0079:UT-07 — config --set-default globex grava default: globex; nome inexistente: exit 2."""
        self.two_atlases()
        out = self.cli("config", "--set-default", "globex")
        self.assertExit(out, 0)
        data = parse(self.local)
        self.assertEqual(data.get("default"), "globex")
        self.assertEqual(sorted(data.get("atlases") or {}), ["acme", "globex"])
        before = self.local.read_bytes()
        out = self.cli("config", "--set-default", "initech")
        self.assertExit(out, 2)
        self.assertIn("initech", output(out))
        self.assertEqual(self.local.read_bytes(), before)

        single = self.box.root / "single"  # com uma entrada só o arquivo não muda (já é o default)
        self.box.write_local(fn("render_local_config")(str(self.acme), {}), config_home=single)
        before = (single / "config.yml").read_bytes()
        self.assertExit(self.cli("config", "--set-default", "acme", config_home=single), 0)
        self.assertEqual((single / "config.yml").read_bytes(), before)

    def test_doctor_lists_the_atlases_and_warns_about_a_missing_folder(self):
        """SPEC-0079:UT-08 — doctor: "Atlas configurados: 2 (acme, globex)" e AVISO da pasta de globex ausente."""
        self.two_atlases()
        shutil.rmtree(self.globex)
        for args in (("doctor",), ("doctor", "--atlas", "acme")):
            with self.subTest(args=args):
                out = self.cli(*args)
                self.assertExit(out, 0)
                self.assertIn(f"Atlas configurados: 2 ({NAMES})", out.stdout)
                rows = doctor_lines(out.stdout)
                self.assertTrue([r for r in rows if r[0] == "AVISO" and "globex" in f"{r[1]} {r[2]}"], out.stdout)
                self.assertEqual([r for r in rows if r[0] == "ERRO" and "globex" in f"{r[1]} {r[2]}"], [])
                self.assertIn(("OK", "pasta do atlas", str(self.acme)), rows)


# ---------------------------------------------------------------- integração (IT-01, IT-02)

class CliIntegrationTest(MultiAtlasCase):
    def test_single_form_survives_and_the_backup_restores_it(self):
        """SPEC-0079:IT-01 — init e join no mesmo atlas mantêm a forma antiga byte a byte; o segundo atlas passa à
        forma nova com .bak; restaurar o .bak volta a um atlas só."""
        credentials = {"facts": {"env": ["A_TOKEN"]}}
        acme = self.box.root / "work" / "acme-atlas"
        acme.mkdir(parents=True)
        self.assertExit(self.box.init(atlas=acme), 0)
        self.local.write_text(fn("render_local_config")(str(acme), credentials), encoding="utf-8")
        before = self.local.read_bytes()

        self.assertExit(self.cli("init", "--join", "--atlas", acme), 0)
        self.assertEqual(self.local.read_bytes(), before, "join no mesmo atlas: o arquivo de hoje")
        self.assertExit(self.cli("init", "--join", "--atlas", acme, "--name", "acme"), 0)
        self.assertEqual(self.local.read_bytes(), before, "mesmo nome e caminho: continua na forma antiga")
        self.assertFalse(self.local.with_name("config.yml.bak").exists())

        globex = self.make_atlas(self.box.root / "work" / "globex-atlas", "Globex")
        self.assertExit(self.cli("init", "--join", "--atlas", globex, "--name", "globex"), 0)
        backup = self.local.with_name("config.yml.bak")
        self.assertEqual(backup.read_bytes(), before)
        data = parse(self.local)
        self.assertEqual(data.get("default"), "acme")
        self.assertEqual(data["atlases"]["acme"], {"atlas": str(acme), "credentials": credentials})
        data = self.config_json()
        self.assertEqual((data.get("atlas_name"), data.get("selected_by")), ("acme", "default"))

        shutil.copyfile(backup, self.local)  # rollback documentado no CHANGELOG
        data = self.config_json()
        self.assertEqual((data.get("atlas_name"), data.get("selected_by")), ("acme", "single"))
        self.assertEqual(data["values"]["atlas"], str(acme))
        self.assertEqual(data["values"]["credentials"], credentials)

    def test_scan_and_doctor_of_one_atlas_never_touch_the_other_atlas_credentials(self):
        """SPEC-0079:IT-02 — scan --atlas globex e doctor --atlas globex só checam B_TOKEN; A_TOKEN não aparece."""
        self.two_atlases(acme_credentials=A_CREDENTIALS, globex_credentials=B_CREDENTIALS,
                         acme={"service": "payments-api"}, globex={"service": "billing-api"})
        env = {"A_TOKEN": "acme-test-value-0079", "B_TOKEN": "globex-test-value-0079"}

        out = self.cli("scan", "--atlas", "globex", env=env)
        self.assertExit(out, 0)
        self.assertTrue((self.globex / "snapshots" / "facts.json").is_file(), output(out))
        self.assertFalse((self.acme / "snapshots" / "facts.json").exists(), "o scan rodou no atlas errado")
        for leaked in ("A_TOKEN", env["A_TOKEN"]):
            self.assertNotIn(leaked, output(out))
            for path in sorted(self.globex.rglob("*")):
                if path.is_file() and path.suffix in (".json", ".md"):
                    self.assertNotIn(leaked, path.read_text(encoding="utf-8"), path)

        out = self.cli("doctor", "--atlas", "globex", env=env)
        self.assertExit(out, 0)
        rows = doctor_lines(out.stdout)
        self.assertTrue([r for r in rows if r[0] == "OK" and "B_TOKEN" in r[1] and r[2] == "definida"], out.stdout)
        self.assertNotIn("A_TOKEN", output(out))
        self.assertIn(("OK", "pasta do atlas", str(self.globex)), rows)


# ---------------------------------------------------------------- contrato (CT-01)

class ConfigJsonContractTest(MultiAtlasCase):
    def assertContract(self, data, name, by, atlases):
        self.assertIn("values", data)
        self.assertIn("origins", data)
        self.assertEqual(data.get("atlas_name"), name)
        self.assertIn(data.get("selected_by"), SELECTED_BY)
        self.assertEqual(data.get("selected_by"), by)
        listed = data.get("atlases")
        self.assertIsInstance(listed, list)
        for item in listed:
            self.assertIsInstance(item, dict)
            self.assertEqual(set(item), {"name", "atlas", "default"})
            self.assertIsInstance(item["default"], bool)
        self.assertEqual([item["name"] for item in listed], sorted(item["name"] for item in listed), "por nome")
        self.assertEqual([(item["name"], item["atlas"]) for item in listed], atlases)
        self.assertEqual(data["values"]["atlas"], dict(atlases)[name])

    def test_config_json_fields_for_each_way_of_choosing(self):
        """SPEC-0079:CT-01 — config --json: atlas_name, selected_by (option | env | default | single) e atlases."""
        self.two_atlases()
        atlases = [("acme", str(self.acme)), ("globex", str(self.globex))]
        cases = [
            ("default", (), {}, "acme"),
            ("option", ("--atlas", "globex"), {}, "globex"),
            ("env", (), {"ATLAS_NAME": "globex"}, "globex"),
        ]
        for by, args, env, name in cases:
            with self.subTest(selected_by=by):
                data = self.config_json(*args, env=env)
                self.assertContract(data, name, by, atlases)
                self.assertEqual([(i["name"], i["default"]) for i in data["atlases"]],
                                 [("acme", True), ("globex", False)])

        single = self.box.root / "single"
        self.box.write_local(fn("render_local_config")(str(self.acme), {}), config_home=single)
        out = self.cli("config", "--json", config_home=single)
        self.assertExit(out, 0)
        self.assertContract(json.loads(out.stdout), "acme", "single", [("acme", str(self.acme))])


# ---------------------------------------------------------------- jornada (E2E-01)

class TwoOrganizationsJourneyTest(MultiAtlasCase):
    def context_services(self, *args, env=None) -> list:
        out = self.cli("context", "api", "--json", *args, env=env)
        self.assertExit(out, 0)
        return sorted(s["key"] for s in json.loads(out.stdout)["services"])

    def test_person_working_for_two_organizations(self):
        """SPEC-0079:E2E-01 — init de Acme, join de Globex, config --list, context por --atlas, ATLAS_NAME,
        default e config --set-default."""
        acme = self.box.root / "work" / "acme-atlas"
        acme.mkdir(parents=True)
        self.assertExit(self.cli("init", "--atlas", acme, "--org", "Acme", "--mode", "repo"), 0)  # 1
        (acme / "atlas-config.yml").write_text(facts_config("Acme"), encoding="utf-8")
        write_facts(acme, "payments-api", "payments-db")
        self.assertExit(self.cli("scan"), 0)

        globex = self.make_atlas(self.box.root / "work" / "globex-atlas", "Globex", service="billing-api",
                                 scan=True)
        self.assertExit(self.cli("init", "--join", "--atlas", globex, "--name", "globex"), 0)  # 2

        out = self.cli("config", "--list")  # 3
        self.assertExit(out, 0)
        for text in ("acme", "globex", str(acme), str(globex), "Acme", "Globex"):
            self.assertIn(text, out.stdout)
        data = self.config_json()
        self.assertEqual([(i.get("name"), i.get("default")) for i in data.get("atlases") or []],
                         [("acme", True), ("globex", False)])

        acme_services, globex_services = ["service:payments-api"], ["service:billing-api"]
        self.assertEqual(self.context_services("--atlas", "globex"), globex_services)  # 4
        self.assertEqual(self.context_services(env={"ATLAS_NAME": "globex"}), globex_services)
        self.assertEqual(self.context_services(), acme_services)  # 5

        self.assertExit(self.cli("config", "--set-default", "globex"), 0)  # 6
        self.assertEqual(self.context_services(), globex_services)


if __name__ == "__main__":
    unittest.main()
