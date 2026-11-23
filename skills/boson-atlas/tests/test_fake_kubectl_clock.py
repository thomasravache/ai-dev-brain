"""Relógio do `kubectl` falso (SPEC-0094, UT-01): um "agora" único por cenário, gravado por `install_kubectl`, para que
chamadas separadas (um processo por chamada) rendam os mesmos horários mesmo quando o relógio vira de segundo entre
elas.

Isolamento: pasta temporária com HOME, XDG_CONFIG_HOME e ATLAS_CONFIG_HOME próprios e PATH só com a pasta do dublê;
nenhum kubectl de verdade, nenhuma rede; nomes genéricos (acme, clock).
"""
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from test_probe_kubernetes import CLUSTER_V5, CONTEXT, NAMESPACE, install_kubectl

POD = "clock-7c1e-bbbb"


def wait_for_the_next_second():
    """Dorme até passar a próxima virada de segundo (com folga), sem depender de sorte."""
    time.sleep(1.0 - time.time() % 1.0 + 0.05)


class FakeKubectlClockTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.home = self.root / "home"
        self.home.mkdir()
        self.kubectl = install_kubectl(self.root / "bin", self.root / "kubectl-calls.jsonl", fixtures=(CLUSTER_V5,))

    def environment(self):
        env = {"PATH": str(self.kubectl.parent), "HOME": str(self.home),
               "XDG_CONFIG_HOME": str(self.home / ".config"), "ATLAS_CONFIG_HOME": str(self.root / "config-home"),
               "LANG": "C.UTF-8"}
        for name in ("TMPDIR", "SYSTEMROOT"):
            if name in os.environ:
                env[name] = os.environ[name]
        return env

    def logs(self):
        argv = [str(self.kubectl), "logs", f"pod/{POD}", "--all-containers", "--timestamps", "--since=1800s",
                "--tail=100", "--prefix", "--context", CONTEXT, "-n", NAMESPACE, "--request-timeout=20s"]
        result = subprocess.run(argv, capture_output=True, text=True, cwd=self.root, env=self.environment(),
                                timeout=60, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertTrue(lines, "o dublê não devolveu linhas")
        return lines

    def test_separate_logs_calls_render_the_same_timestamps_across_a_second_boundary(self):
        """SPEC-0094:UT-01 — com o dublê instalado por `install_kubectl`, duas chamadas de `logs` do mesmo pod com a
        virada de um segundo entre elas imprimem os mesmos horários para cada linha (antes, a segunda saía um
        segundo depois, porque cada processo tirava o próprio "agora")."""
        first = self.logs()
        wait_for_the_next_second()
        second = self.logs()
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
