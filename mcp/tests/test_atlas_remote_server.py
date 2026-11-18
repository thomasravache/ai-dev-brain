"""Tools atlas_* com o parâmetro `atlas` e rodando na pasta do projeto (SPEC-0080: CH-01, UT-08, IT-02 e CT-01;
ADR-0021). O hook e a CLI ficam em tests/plugin e skills/boson-atlas/tests.

Run: python3 -m unittest discover -s mcp/tests

Contrato (seção 6 da SPEC-0080) que estes testes fixam em mcp/fermion_mcp.py:

    atlas_config, atlas_doctor, atlas_context, atlas_lint e atlas_curate_list ganham o parâmetro opcional
        "atlas": string, 1–200 caracteres, sem caractere de controle → a CLI recebe "--atlas <valor>" (ou
        "--atlas=<valor>"), sempre antes do "--" do context. Sem "atlas", os argumentos são os de hoje (CH-01).
    Todas rodam a CLI com cwd = project_dir() (CLAUDE_PROJECT_DIR ou o cwd do servidor).
    Exit 2 da escolha (vários atlas sem escolha) → erro da tool com a mensagem da CLI; exit 3 → NOT_CONFIGURED.

O executor substituto aceita argumentos extras (posicionais ou por nome, como um `cwd=`), para não amarrar o teste à
forma como o servidor passa a pasta do projeto ao run_cli. Os IT abrem o servidor real por stdio com HOME, XDG_*,
ATLAS_CONFIG_HOME temporários, dois atlas criados pela CLI (coletor generic da boson-atlas) e repositórios git locais
com `origin` fictício; nunca a rede nem a configuração real da máquina.
"""
import unittest
from pathlib import Path
from types import SimpleNamespace

from helpers import (
    ATLAS_CLI,
    CLI_TIMEOUT,
    TOOLS,
    attr,
    call,
)

SPEC = "SPEC-0080"
# argumentos de hoje de cada tool sem "atlas" (SPEC-0054 seção 6)
TODAY = (
    ("atlas_config", {}, ["config", "--json"]),
    ("atlas_doctor", {}, ["doctor", "--json"]),
    ("atlas_context", {"query": "api payments"}, ["context", "--json", "--", "api", "payments"]),
    ("atlas_context", {"query": "api", "hops": 2, "limit": 5, "max_chars": 1000},
     ["context", "--hops", "2", "--limit", "5", "--max-chars", "1000", "--json", "--", "api"]),
    ("atlas_lint", {}, ["lint", "--json"]),
    ("atlas_lint", {"only": ["secret-leak", "stale"]}, ["lint", "--json", "--only", "secret-leak,stale"]),
    ("atlas_curate_list", {}, ["curate", "list", "--json"]),
    ("atlas_curate_list", {"status": "inferred"}, ["curate", "list", "--json", "--status", "inferred"]),
)


class Recorder:
    """Executor substituto: grava argv e timeout de cada chamada (aceita cwd e outros extras) e devolve o resultado
    configurado."""

    def __init__(self, returncode=0, stdout="{}", stderr=""):
        self.calls = []
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr

    def __call__(self, argv, timeout=None, *args, **kwargs):
        self.calls.append({"argv": list(argv), "timeout": timeout, "extra": args, "kwargs": kwargs})
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr=self.stderr)


def new_server(runner):
    return attr("Server")(runner=runner)


def result_of(case, response, id=1):
    case.assertIsNotNone(response)
    case.assertNotIn("error", response, response)
    case.assertIn("result", response, response)
    return response["result"]


def cli_args(case, runner):
    """argv depois de `<python> atlas.py` da única chamada gravada, conferindo o prefixo e o timeout."""
    case.assertEqual(len(runner.calls), 1, runner.calls)
    argv = runner.calls[0]["argv"]
    case.assertTrue(Path(argv[0]).name.startswith("python"), argv)
    case.assertEqual(Path(argv[1]).resolve(), ATLAS_CLI.resolve(), argv)
    case.assertEqual(runner.calls[0]["timeout"], CLI_TIMEOUT, runner.calls[0])
    return argv[2:]


# ---------------------------------------------------------------- caracterização (CH-01)

class AtlasToolsCharacterizationTest(unittest.TestCase):
    def test_atlas_tools_without_atlas_pass_todays_arguments(self):
        """SPEC-0080:CH-01 — com um atlas só, as tools atlas_* chamadas sem `atlas` passam à CLI os argumentos de
        hoje (nenhum --atlas)."""
        self.assertEqual(sorted({name for name, _, _ in TODAY}), sorted(TOOLS))
        for name, arguments, expected in TODAY:
            with self.subTest(tool=name, arguments=arguments):
                runner = Recorder()
                result = result_of(self, new_server(runner).handle(call(name, arguments)))
                self.assertIs(result.get("isError"), False, result)
                args = cli_args(self, runner)
                self.assertEqual(args, expected)
                self.assertFalse([a for a in args if a == "--atlas" or a.startswith("--atlas=")], args)
