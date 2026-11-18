"""Atlas escolhido pelo remote `origin` do projeto (SPEC-0080: UT-01 a UT-07 e IT-01; ADR-0021). As tools MCP ficam
em mcp/tests/test_atlas_remote_server.py e o hook em tests/plugin/test_atlas_remote_hook.py.

Contrato (seção 6 da SPEC-0080) que os testes fixam:
    atlas-config.yml (compartilhado), chave opcional `remotes:` com prefixos host/caminho. Cada item: minúsculas,
        sem esquema, "@", ":", espaço, "..", barra no início ou no fim → exit 2 com o item.
    init --atlas P --org O --mode M --remote X [--remote Y] grava a lista no atlas novo.
    Passo 3 da ordem de escolha (entre ATLAS_NAME e default): remote = `git -C <cwd> config --get
        remote.origin.url`, normalizado para host/caminho em minúsculas, sem esquema, credenciais, porta nem ".git"
        (https://u:t@GitHub.com/Acme/API.git e git@github.com:Acme/API.git → github.com/acme/api;
        ssh://git@host:2222/g/r.git → host/g/r). Casa quando um item é igual ao remote ou prefixo dele por segmentos
        inteiros; vale o prefixo mais longo; empate → passo pulado (cai no default). Pasta sem git, sem origin, sem
        `git` no PATH → passo pulado sem erro nem aviso.
    config --json: "selected_by": "remote"; texto: "escolhido por: remote do projeto".
    doctor: remote da pasta que casa com mais de um atlas no mesmo comprimento → AVISO com os nomes, sem o remote.

Isolamento: HOME, XDG_CONFIG_HOME e ATLAS_CONFIG_HOME temporários (helpers.Sandbox), ATLAS_NAME tirado do ambiente,
git com GIT_CONFIG_NOSYSTEM, GIT_CONFIG_GLOBAL=/dev/null e GIT_CEILING_DIRECTORIES na raiz temporária. Repositórios git
locais com `origin` fictício (nunca acessado); organizações genéricas (Acme, Globex, Initech); sem rede.
"""
import json
import os
import shutil
import subprocess
import sys
import unittest

from helpers import SCRIPT, Sandbox, doctor_lines, fn, output
from test_multi_atlas import facts_config, write_facts

SPEC = "SPEC-0080"
HAS_GIT = shutil.which("git") is not None
TIMEOUT = 120
REMOTE_TEXT = "escolhido por: remote do projeto"
# credenciais fictícias e fáceis de procurar na saída (o "u:tok" do UT-02)
USER, TOKEN = "usr-q7", "tok-z9"


@unittest.skipUnless(HAS_GIT, "git não está no PATH")
class RemoteCase(unittest.TestCase):
    def setUp(self):
        self.fresh()

    def fresh(self):
        """Sandbox novo (para cada subTest que precisa de outro conjunto de atlas)."""
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        self.paths = {}

    # ------------------------------------------------------------ processos

    def environ(self, env=None, config_home=None):
        environ = {k: v for k, v in os.environ.items()
                   if k not in ("ATLAS_NAME", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG")}
        environ.update(HOME=str(self.box.home), XDG_CONFIG_HOME=str(self.box.home / ".config"),
                       ATLAS_CONFIG_HOME=str(config_home or self.box.config_home), GIT_CONFIG_NOSYSTEM="1",
                       GIT_CONFIG_GLOBAL=os.devnull, GIT_CEILING_DIRECTORIES=str(self.box.root))
        environ.update(env or {})
        return environ

    def cli(self, *args, cwd=None, env=None, config_home=None):
        """atlas.py como processo, na pasta `cwd` (padrão: a raiz temporária)."""
        return subprocess.run([sys.executable, str(SCRIPT), *[str(a) for a in args]], check=False,
                              cwd=str(cwd or self.box.root), capture_output=True, text=True, timeout=TIMEOUT,
                              env=self.environ(env, config_home))

    def git(self, cwd, *args):
        out = subprocess.run(["git", "-c", "init.defaultBranch=main", *args], cwd=str(cwd), capture_output=True,
                             text=True, timeout=TIMEOUT, env=self.environ(), check=False)
        self.assertEqual(out.returncode, 0, output(out))
        return out

    def repo(self, name, origin=None, **remotes):
        """Repositório git local em <raiz>/repos/<name>; `origin` e outros remotes fictícios."""
        path = self.box.root / "repos" / name
        path.mkdir(parents=True)
        self.git(path, "init", "-q")
        if origin:
            self.git(path, "remote", "add", "origin", origin)
        for remote, url in remotes.items():
            self.git(path, "remote", "add", remote, url)
        return path

    def assertExit(self, result, code):
        self.assertEqual(result.returncode, code, output(result))
        self.assertNotIn("Traceback", output(result))
        self.assertNotIn("usage:", result.stderr, "erro do argparse, não do contrato")

    def config_json(self, cwd, *args, env=None):
        out = self.cli("config", "--json", *args, cwd=cwd, env=env)
        self.assertExit(out, 0)
        return json.loads(out.stdout)

    def assertChosen(self, cwd, name, selected_by, *args, env=None):
        data = self.config_json(cwd, *args, env=env)
        self.assertEqual((data.get("atlas_name"), data.get("selected_by")), (name, selected_by), data)
        return data

    # ------------------------------------------------------------ atlas

    def make_atlas(self, name, remotes=(), service=None):
        """Atlas criado por init numa configuração de rascunho; com `service`, coletor generic e grafo (scan);
        `remotes:` acrescentado no fim do atlas-config.yml."""
        path = self.box.root / "work" / f"{name}-atlas"
        path.mkdir(parents=True)
        scratch = self.box.root / "scratch" / name
        self.assertExit(self.cli("init", "--atlas", path, "--org", name.title(), "--mode", "repo",
                                 config_home=scratch), 0)
        if service:
            (path / "atlas-config.yml").write_text(facts_config(name.title()), encoding="utf-8")
            write_facts(path, service, f"{service}-db")
            self.assertExit(self.cli("scan", config_home=scratch), 0)
        if remotes:
            self.set_remotes(path, remotes)
        self.paths[name] = path
        return path

    @staticmethod
    def set_remotes(path, remotes):
        """Troca (ou acrescenta) a chave remotes: do atlas-config.yml, com cada item entre aspas."""
        shared = path / "atlas-config.yml"
        text = shared.read_text(encoding="utf-8").split("\nremotes:\n")[0].rstrip("\n") + "\n"
        text += "remotes:\n" + "".join(f"  - {json.dumps(item)}\n" for item in remotes)
        shared.write_text(text, encoding="utf-8")

    def configure(self, default=None):
        """Configuração local na forma de vários atlas, com todas as entradas criadas por make_atlas."""
        head = f"default: {default}\n" if default else ""
        body = "".join(f"  {name}:\n    atlas: \"{self.paths[name]}\"\n    credentials: {{}}\n"
                       for name in sorted(self.paths))
        return self.box.write_local(f"{head}atlases:\n{body}")

    def acme_and_globex(self, default=None, **services):
        self.make_atlas("acme", ["github.com/acme"], services.get("acme"))
        self.make_atlas("globex", ["github.com/globex"], services.get("globex"))
        self.configure(default)


# ---------------------------------------------------------------- UT-01

class RemoteMatchTest(RemoteCase):
    def test_project_remote_chooses_the_atlas_of_its_organization(self):
        """SPEC-0080:UT-01 — acme com remotes [github.com/acme], globex com [github.com/globex], sem default: na
        pasta com origin https://github.com/Acme/api.git, acme com selected_by remote."""
        self.acme_and_globex()
        acme = self.repo("acme-api", "https://github.com/Acme/api.git")
        data = self.assertChosen(acme, "acme", "remote")
        self.assertEqual(data["values"]["atlas"], str(self.paths["acme"]))
        out = self.cli("config", cwd=acme)
        self.assertExit(out, 0)
        self.assertIn(f"atlas: acme ({REMOTE_TEXT})", out.stdout)
        nested = acme / "src" / "app"
        nested.mkdir(parents=True)
        self.assertChosen(nested, "acme", "remote")  # subpasta do repositório
        globex = self.repo("globex-billing", "git@github.com:globex/billing.git")
        self.assertChosen(globex, "globex", "remote")


# ---------------------------------------------------------------- UT-02

class NormalizationTest(RemoteCase):
    CASES = (
        (f"https://{USER}:{TOKEN}@GitHub.com/Acme/API.git", "acme"),
        ("git@github.com:Acme/API.git", "acme"),
        (f"ssh://git:{TOKEN}@host.interno:2222/g/r.git", "interno"),
        ("ssh://git@host.interno:2222/g/r.git", "interno"),
        ("https://host/g/r/", "plain"),
    )

    def test_remote_forms_are_normalized_without_credentials(self):
        """SPEC-0080:UT-02 — https com credenciais, scp-like, ssh com porta, ".git", maiúsculas e barra final dão
        github.com/acme/api, host.interno/g/r e host/g/r; usuário e token não aparecem em nenhuma saída."""
        self.make_atlas("acme", ["github.com/acme/api"])
        self.make_atlas("interno", ["host.interno/g/r"])
        self.make_atlas("plain", ["host/g/r"])
        self.make_atlas("globex", ["github.com/globex"])
        self.configure()
        for index, (url, expected) in enumerate(self.CASES):
            with self.subTest(remote=url):
                repo = self.repo(f"r{index}", url)
                self.assertChosen(repo, expected, "remote")
                for args in (("config",), ("config", "--json"), ("config", "--list"), ("config", "--list", "--json"),
                             ("doctor",), ("doctor", "--json"), ("lint",)):
                    out = self.cli(*args, cwd=repo)
                    self.assertNotIn("Traceback", output(out))
                    for secret in (USER, TOKEN):
                        self.assertNotIn(secret, output(out), f"{secret} vazou em {' '.join(args)}")


# ---------------------------------------------------------------- UT-03

class LongestPrefixTest(RemoteCase):
    def test_whole_segments_longest_prefix_and_tie(self):
        """SPEC-0080:UT-03 — github.com/acme e github.com/acme/infra: o remote github.com/acme/infra/x fica com o
        segundo; github.com/acme não casa github.com/acme-labs/x; dois atlas com o mesmo prefixo pulam o passo e vale
        o default."""
        with self.subTest(caso="prefixo mais longo"):
            self.make_atlas("acme", ["github.com/acme"])
            self.make_atlas("infra", ["github.com/acme/infra"])
            self.configure()
            self.assertChosen(self.repo("infra-x", "https://github.com/acme/infra/x.git"), "infra", "remote")
            self.assertChosen(self.repo("acme-api", "https://github.com/acme/api.git"), "acme", "remote")
            self.assertChosen(self.repo("infra-exact", "https://github.com/acme/infra"), "infra", "remote")

        with self.subTest(caso="segmento inteiro"):
            self.fresh()
            self.acme_and_globex(default="globex")
            self.assertChosen(self.repo("acme-api", "https://github.com/acme/api.git"), "acme", "remote")
            self.assertChosen(self.repo("labs", "https://github.com/acme-labs/x.git"), "globex", "default")

        with self.subTest(caso="empate"):
            self.fresh()
            self.make_atlas("acme", ["github.com/acme"])
            self.make_atlas("initech", ["github.com/acme"])
            self.make_atlas("globex", ["github.com/globex"])
            self.configure(default="globex")
            self.assertChosen(self.repo("globex-api", "https://github.com/globex/api.git"), "globex", "remote")
            self.assertChosen(self.repo("acme-api", "https://github.com/acme/api.git"), "globex", "default")


# ---------------------------------------------------------------- UT-04

class OrderTest(RemoteCase):
    def test_option_and_environment_win_over_the_remote(self):
        """SPEC-0080:UT-04 — remote que casa acme: --atlas globex dá globex (option) e ATLAS_NAME=globex dá globex
        (env)."""
        self.acme_and_globex()
        repo = self.repo("acme-api", "https://github.com/acme/api.git")
        self.assertChosen(repo, "acme", "remote")
        self.assertChosen(repo, "globex", "option", "--atlas", "globex")
        self.assertChosen(repo, "globex", "env", env={"ATLAS_NAME": "globex"})
        self.assertChosen(repo, "globex", "option", "--atlas", "globex", env={"ATLAS_NAME": "acme"})


# ---------------------------------------------------------------- UT-05

class NoRemoteTest(RemoteCase):
    def assertQuietDefault(self, cwd, env=None):
        out = self.cli("config", "--json", cwd=cwd, env=env)
        self.assertExit(out, 0)
        data = json.loads(out.stdout)
        self.assertEqual((data.get("atlas_name"), data.get("selected_by")), ("globex", "default"), data)
        self.assertEqual(out.stderr, "", "sem erro nem aviso")

    def test_without_a_readable_origin_the_step_is_skipped_quietly(self):
        """SPEC-0080:UT-05 — com default: globex, pasta sem git, repositório sem origin (só com outro remote que casa
        acme) e PATH sem git dão globex sem erro nem aviso; com git e origin, o remote vale (controle)."""
        self.acme_and_globex(default="globex")
        acme = self.repo("acme-api", "https://github.com/acme/api.git")
        with self.subTest(caso="controle: origin casa acme"):
            self.assertChosen(acme, "acme", "remote")
        with self.subTest(caso="pasta sem git"):
            plain = self.box.root / "plain"
            plain.mkdir()
            self.assertQuietDefault(plain)
        with self.subTest(caso="repositório sem origin"):
            self.assertQuietDefault(self.repo("no-origin", upstream="https://github.com/acme/api.git"))
        with self.subTest(caso="PATH sem git"):
            empty = self.box.root / "empty-bin"
            empty.mkdir()
            self.assertQuietDefault(acme, env={"PATH": str(empty)})


# ---------------------------------------------------------------- UT-06

class DoctorTieTest(RemoteCase):
    def test_doctor_warns_about_a_remote_matching_two_atlases(self):
        """SPEC-0080:UT-06 — acme e initech com o mesmo prefixo que casa o remote da pasta: o doctor tem um AVISO
        com os dois nomes e sem o remote."""
        self.make_atlas("acme", ["github.com/acme"])
        self.make_atlas("initech", ["github.com/acme"])
        self.make_atlas("globex", ["github.com/globex"])
        self.configure(default="globex")
        repo = self.repo("acme-api", "https://github.com/acme/api.git")
        out = self.cli("doctor", cwd=repo)
        self.assertNotIn("Traceback", output(out))
        rows = doctor_lines(out.stdout)
        warned = [row for row in rows if row[0] == "AVISO" and "acme" in " ".join(row) and "initech" in " ".join(row)]
        self.assertTrue(warned, out.stdout)
        for row in warned:
            self.assertNotIn("github.com", " ".join(row), "o AVISO não mostra o remote")
        self.assertNotIn("github.com/acme/api", output(out))
        with self.subTest(caso="sem empate, sem aviso"):
            other = self.repo("globex-api", "https://github.com/globex/api.git")
            rows = doctor_lines(self.cli("doctor", cwd=other).stdout)
            self.assertFalse([row for row in rows if row[0] == "AVISO" and "initech" in " ".join(row)], rows)


# ---------------------------------------------------------------- UT-07

INVALID_REMOTES = (
    "https://github.com/acme",
    "user@github.com/acme",
    "github.com/ac me",
    "github.com/../acme",
    "/github.com/acme",
    "github.com/acme/",
    "github.com:acme",
    "GitHub.com/acme",
)


class RemotesValidationTest(RemoteCase):
    def test_invalid_items_exit_2_and_init_writes_the_list(self):
        """SPEC-0080:UT-07 — item de remotes: com esquema, "@", espaço, "..", absoluto, barra final, ":" ou
        maiúscula → exit 2 com o item; init --remote grava a lista; lista válida não é chave desconhecida."""
        atlas = self.make_atlas("acme", ["github.com/acme"])
        self.configure()
        with self.subTest(caso="lista válida"):
            self.assertExit(self.cli("config", "--json"), 0)
            lint = self.cli("lint")
            self.assertNotIn("chave desconhecida: remotes", output(lint))
        for item in INVALID_REMOTES:
            with self.subTest(item=item):
                self.set_remotes(atlas, ["github.com/globex", item])
                out = self.cli("config", "--json")
                self.assertExit(out, 2)
                self.assertIn(item, output(out))
        with self.subTest(caso="init --remote"):
            new = self.box.root / "work" / "globex-atlas"
            new.mkdir(parents=True)
            out = self.cli("init", "--atlas", new, "--org", "Globex", "--mode", "repo", "--remote",
                           "github.com/globex", "--remote", "gitlab.globex.interno/plataforma",
                           config_home=self.box.root / "scratch" / "init-remote")
            self.assertNotIn("usage:", out.stderr, "init ainda não aceita --remote")
            self.assertExit(out, 0)
            shared = fn("parse_yaml")((new / "atlas-config.yml").read_text(encoding="utf-8"))
            self.assertEqual(shared.get("remotes"), ["github.com/globex", "gitlab.globex.interno/plataforma"])


# ---------------------------------------------------------------- IT-01

class TwoRepositoriesTest(RemoteCase):
    def services(self, cwd) -> list:
        out = self.cli("context", "api", "--json", cwd=cwd)
        self.assertExit(out, 0)
        return sorted(s["key"] for s in json.loads(out.stdout)["services"])

    def test_context_uses_the_graph_of_the_atlas_of_each_repository(self):
        """SPEC-0080:IT-01 — CLI como processo, dois atlas com remotes: e grafo, dois repositórios com origin
        diferente: context sem opção usa o grafo do atlas certo em cada um."""
        self.acme_and_globex(acme="payments-api", globex="billing-api")
        acme = self.repo("acme-payments", "git@github.com:acme/payments.git")
        globex = self.repo("globex-billing", "https://github.com/globex/billing.git")
        self.assertEqual(self.services(acme), ["service:payments-api"])
        self.assertEqual(self.services(globex), ["service:billing-api"])
