"""atlas_context com o caminho de entrega (SPEC-0086: UT-05).

O servidor MCP real (python3 mcp/fermion_mcp.py, por stdio) sobre um atlas de teste criado pela CLI da boson-atlas
(init + scan com os coletores github e argocd sobre as fixtures image-link da SPEC-0082, com --input, sem rede): o
JSON de atlas_context traz `delivery` em service:api igual ao da CLI (`context --json -- api`) e com o conteúdo do
contrato (seção 6 da SPEC-0086).

Isolamento: HOME, ATLAS_CONFIG_HOME e BRAIN_CONFIG_HOME temporários (helpers.Sandbox); nomes só acme e team-x.
"""
import json
import unittest

from helpers import Sandbox, ServerProcess, call, request, text_of

PATTERN = r"^(?:dev|qa)-(?P<service>.+)$"
API_DELIVERY = {
    "code_repositories": ["acme/api"],
    "config_repositories": ["acme/iac"],
    "pipelines": [{"id": "acme/api/build", "name": "Build", "repository": "acme/api"},
                  {"id": "acme/api/publish", "name": "Publish", "repository": "acme/api"}],
    "images": ["acme/api"],
    "deployments": [
        {"id": "dev-api", "environments": ["dev"], "clusters": ["cluster-dev"], "sync_status": "Synced",
         "health_status": "Healthy", "images": ["acme/api"]},
        {"id": "qa-api", "environments": ["qa"], "clusters": ["cluster-qa"], "sync_status": "OutOfSync",
         "health_status": "Degraded", "images": ["acme/api"]},
    ],
}
PROCESS_TIMEOUT = 60


def collectors_config():
    collectors = (
        ("github", "code", ["python3", "{skill}/assets/collectors/github.py", "--org", "acme", "--input",
                            "{skill}/tests/fixtures/github/image-link"]),
        ("argocd", "delivery", ["python3", "{skill}/assets/collectors/argocd.py", "--from", "argocd", "--input",
                                "{skill}/tests/fixtures/argocd/image-link.json", "--service-pattern", PATTERN]),
    )
    lines = ["version: 1", "organization: Acme", "mode: local", "language: auto", "stale_days: 14",
             "categories: [code, delivery]", "collectors:"]
    for cid, category, command in collectors:
        lines += [f"  - id: {cid}", f"    category: {category}",
                  "    command: [" + ", ".join(json.dumps(a) for a in command) + "]", "    timeout: 60"]
    return "\n".join(lines + ["redaction: {extra_patterns: []}"]) + "\n"


def api_service(data):
    found = [s for s in data.get("services", []) if s.get("key") == "service:api"]
    if not found:
        raise AssertionError(f"service:api fora do pacote: {data}")
    return found[0]


class AtlasContextDeliveryTest(unittest.TestCase):
    def setUp(self):
        self.sandbox = Sandbox()
        self.addCleanup(self.sandbox.cleanup)
        self.sandbox.atlas.mkdir(parents=True)
        out = self.sandbox.cli("init", "--atlas", self.sandbox.atlas, "--org", "Acme", "--mode", "local")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        (self.sandbox.atlas / "atlas-config.yml").write_text(collectors_config(), encoding="utf-8")
        out = self.sandbox.cli("scan")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

    def test_atlas_context_returns_the_same_delivery_as_the_cli(self):
        """SPEC-0086:UT-05 — servidor MCP com um atlas de teste (fixtures image-link): atlas_context {"query": "api"}
        devolve o JSON da CLI, e service:api traz delivery igual ao da CLI e ao do contrato."""
        server = ServerProcess(self.sandbox)
        self.addCleanup(server.close)
        response, _ = server.ask(request("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                                        "clientInfo": {"name": "it", "version": "0"}}, id=0))
        self.assertIn("result", response, response)
        response, _ = server.ask(call("atlas_context", {"query": "api"}, id=1), timeout=PROCESS_TIMEOUT)
        self.assertIn("result", response, response)
        result = response["result"]
        self.assertIs(result.get("isError"), False, text_of(result))
        expected = self.sandbox.cli("context", "--json", "--", "api")
        self.assertEqual(expected.returncode, 0, expected.stderr)
        cli_data = json.loads(expected.stdout)
        self.assertEqual(text_of(result), expected.stdout)
        tool_data = result.get("structuredContent")
        self.assertEqual(tool_data, cli_data)
        service = api_service(tool_data)
        self.assertIn("delivery", service, "atlas_context: service:api sem a chave delivery (SPEC-0086)")
        self.assertEqual(service["delivery"], api_service(cli_data)["delivery"])
        self.assertEqual(service["delivery"], API_DELIVERY)


if __name__ == "__main__":
    unittest.main()
