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
import unittest
from pathlib import Path

from helpers import (
    NEW_CONFIG_DIR,
    Sandbox,
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


if __name__ == "__main__":
    unittest.main()
