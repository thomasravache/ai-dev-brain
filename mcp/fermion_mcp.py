#!/usr/bin/env python3
"""Servidor MCP local do plugin fermion (SPEC-0054, ADR-0017): tools de leitura do atlas da organização.

JSON-RPC 2.0 sobre stdio, uma mensagem por linha. Atende as duas eras do protocolo MCP:
- legada: handshake `initialize` (versões 2025-11-25, 2025-06-18, 2025-03-26 e 2024-11-05);
- moderna (2026-07-28): sem handshake, versão em params._meta, `server/discover` e `resultType` nos resultados.

Cada tool vira uma linha de comando da CLI da boson-atlas (`atlas.py <comando> ... --json`), executada só por
run_cli: argv em lista, sem shell, com timeout e o ambiente herdado. O servidor não importa código das skills e
não interpreta a saída da CLI; só expõe leitura (confirmar ou rejeitar convenção é de pessoas, ADR-0012).

stdout é reservado ao protocolo; diagnóstico vai para o stderr, sem argumentos nem saída da CLI.
Só biblioteca padrão, Python 3.9+.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SERVER_NAME = "fermion"
CLI_RELATIVE = ("skills", "boson-atlas", "scripts", "atlas.py")
CLI_TIMEOUT = 120  # segundos por chamada da CLI

LEGACY_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
LEGACY_DEFAULT = "2025-11-25"
MODERN_VERSION = "2026-07-28"
SUPPORTED_VERSIONS = (MODERN_VERSION,) + LEGACY_VERSIONS
VERSION_KEY = "io.modelcontextprotocol/protocolVersion"
SERVER_INFO_KEY = "io.modelcontextprotocol/serverInfo"
CACHE_TTL_MS = 3600000
CACHE_SCOPE = "private"  # o atlas é dado da organização

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
UNSUPPORTED_VERSION = -32022

NOT_CONFIGURED = "atlas não configurado nesta máquina — rode a skill boson-atlas (onboarding)"
TIMEOUT_TEXT = f"atlas.py não respondeu em {CLI_TIMEOUT} s"
NOT_CONFIGURED_EXIT = 3
LINT_REPORT_EXIT = 1  # no lint, exit 1 = "há ERRO no relatório", não falha da CLI

MAX_DEPTH = 256  # aninhamento máximo de uma mensagem; além disso vira -32700 (o parser do json é recursivo)
LOG_METHOD_MAX = 64
# corta o método no log no primeiro caractere de controle (C0, DEL, C1, separadores de linha e parágrafo)
LOG_UNSAFE = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")
READ_ONLY = {"readOnlyHint": True}


def _object(properties=None, required=None):
    schema = {"type": "object", "properties": properties or {}, "additionalProperties": False}
    if required:
        schema["required"] = list(required)
    return schema


TOOLS = (
    {
        "name": "atlas_config",
        "description": "Configuração efetiva do atlas da organização nesta máquina (atlas.py config --json).",
        "inputSchema": _object(),
        "annotations": READ_ONLY,
    },
    {
        "name": "atlas_doctor",
        "description": "Diagnóstico do atlas: configuração, pasta, coletores e frescor (atlas.py doctor --json).",
        "inputSchema": _object(),
        "annotations": READ_ONLY,
    },
    {
        "name": "atlas_context",
        "description": ("Contexto do atlas para uma consulta em texto livre: serviços, times, convenções e vizinhos "
                        "no grafo (atlas.py context --json)."),
        "inputSchema": _object({
            "query": {"type": "string", "minLength": 1, "maxLength": 500,
                      "pattern": "^[^\\u0000-\\u0008\\u000b\\u000c\\u000e-\\u001f\\u007f]*$",
                      "description": "Termos da consulta, separados por espaço (tab e quebra de linha contam como espaço)."},
            "hops": {"type": "integer", "minimum": 0, "maximum": 2,
                     "description": "Saltos no grafo a partir dos resultados."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200,
                      "description": "Número máximo de resultados."},
            "max_chars": {"type": "integer", "minimum": 500, "maximum": 200000,
                          "description": "Tamanho máximo da saída em caracteres."},
        }, required=["query"]),
        "annotations": READ_ONLY,
    },
    {
        "name": "atlas_lint",
        "description": ("Checagens de qualidade do atlas (atlas.py lint --json). Achados de ERRO vêm no relatório, "
                        "não como erro da tool."),
        "inputSchema": _object({
            "only": {"type": "array", "items": {"type": "string", "pattern": "^[a-z-]+$"},
                     "description": "Só estas regras do lint (nomes em minúsculas com hífen)."},
        }),
        "annotations": READ_ONLY,
    },
    {
        "name": "atlas_curate_list",
        "description": ("Convenções do atlas e o estado de curadoria de cada uma (atlas.py curate list --json). "
                        "Confirmar ou rejeitar convenção é só de pessoas, fora do MCP."),
        "inputSchema": _object({
            "status": {"type": "string", "enum": ["inferred", "confirmed", "rejected"],
                       "description": "Só convenções neste estado."},
        }),
        "annotations": READ_ONLY,
    },
)
TOOLS_BY_NAME = {tool["name"]: tool for tool in TOOLS}


class ProtocolError(Exception):
    """Erro JSON-RPC devolvido ao cliente como `error`."""

    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data


def run_cli(argv, timeout):
    """Único ponto que abre processo: argv em lista, sem shell, ambiente herdado. Não engole exceções."""
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)


def log(message):
    """Diagnóstico no stderr (uma linha), nunca no stdout."""
    print(f"fermion-mcp: {message}", file=sys.stderr, flush=True)


def safe_method(method):
    """Método para o log: até o primeiro caractere de controle, truncado; nunca quebra a linha do stderr."""
    text = LOG_UNSAFE.split(method, 1)[0]
    cut = len(text) < len(method) or len(text) > LOG_METHOD_MAX
    return repr(text[:LOG_METHOD_MAX] + ("..." if cut else ""))


def too_deep(text):
    """True se a mensagem aninha arrays/objetos além de MAX_DEPTH (fora de strings)."""
    depth, in_string, escaped = 0, False, False
    for char in text:  # uma varredura, O(N), sem regex (sem retrocesso em string sem fechar)
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                return True
        elif char in "]}":
            depth -= 1
    return False


def decode_line(raw):
    """Bytes de uma linha do stdin para a mensagem JSON; ValueError se não for UTF-8 nem JSON válido."""
    text = raw.decode("utf-8")
    if too_deep(text):
        raise ValueError("JSON aninhado demais")
    try:
        return json.loads(text)
    except RecursionError:
        raise ValueError("JSON aninhado demais") from None


def python_executable():
    name = Path(sys.executable).name if sys.executable else ""
    return sys.executable if name.startswith("python") else "python3"


def plugin_version(plugin_root):
    try:
        data = json.loads((Path(plugin_root) / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "0.0.0"
    version = data.get("version") if isinstance(data, dict) else None
    return version if isinstance(version, str) else "0.0.0"


# --------------------------------------------------------------------------- validação dos argumentos

def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _check(value, schema, path):
    """Valida `value` contra o subconjunto de JSON Schema usado nas tools; erro -32602 na primeira falha."""
    kind = schema["type"]
    if kind == "object":
        if not isinstance(value, dict):
            raise ProtocolError(INVALID_PARAMS, f"{path}: precisa ser um objeto")
        properties = schema.get("properties", {})
        extra = sorted(set(value) - set(properties))
        if extra:
            raise ProtocolError(INVALID_PARAMS, f"{path}: chave não permitida: {', '.join(extra)}")
        for key in schema.get("required", []):
            if key not in value:
                raise ProtocolError(INVALID_PARAMS, f"{path}: falta {key}")
        for key, item in value.items():
            _check(item, properties[key], f"{path}.{key}")
    elif kind == "string":
        if not isinstance(value, str):
            raise ProtocolError(INVALID_PARAMS, f"{path}: precisa ser texto")
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", len(value)):
            raise ProtocolError(INVALID_PARAMS, f"{path}: tamanho fora da faixa")
        if "enum" in schema and value not in schema["enum"]:
            raise ProtocolError(INVALID_PARAMS, f"{path}: valor fora de {schema['enum']}")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            raise ProtocolError(INVALID_PARAMS, f"{path}: formato inválido")
    elif kind == "integer":
        if not _is_int(value):
            raise ProtocolError(INVALID_PARAMS, f"{path}: precisa ser inteiro")
        if not schema["minimum"] <= value <= schema["maximum"]:
            raise ProtocolError(INVALID_PARAMS, f"{path}: fora de {schema['minimum']}..{schema['maximum']}")
    elif kind == "array":
        if not isinstance(value, list):
            raise ProtocolError(INVALID_PARAMS, f"{path}: precisa ser lista")
        for index, item in enumerate(value):
            _check(item, schema["items"], f"{path}[{index}]")


# --------------------------------------------------------------------------- linhas de comando

def command_args(name, arguments):
    """Argumentos da CLI (depois de `atlas.py`) para uma tool já validada."""
    if name == "atlas_config":
        return ["config", "--json"]
    if name == "atlas_doctor":
        return ["doctor", "--json"]
    if name == "atlas_context":
        args = ["context"]
        for key, flag in (("hops", "--hops"), ("limit", "--limit"), ("max_chars", "--max-chars")):
            if key in arguments:
                args += [flag, str(arguments[key])]
        return args + ["--json", "--"] + arguments["query"].split()
    if name == "atlas_lint":
        args = ["lint", "--json"]
        if arguments.get("only"):
            args += ["--only", ",".join(arguments["only"])]
        return args
    if name == "atlas_curate_list":
        args = ["curate", "list", "--json"]
        if "status" in arguments:
            args += ["--status", arguments["status"]]
        return args
    raise ProtocolError(INVALID_PARAMS, f"tool desconhecida: {name}")


def _text_result(text, is_error, structured=None):
    result = {"content": [{"type": "text", "text": text}], "isError": is_error}
    if structured is not None:
        result["structuredContent"] = structured
    return result


def _with_stderr(text, stderr):
    detail = (stderr or "").strip()
    return f"{text}\n{detail}" if detail else text


def map_output(name, completed):
    """CallToolResult a partir do exit code e da saída da CLI (seção 6 da SPEC-0054)."""
    code = completed.returncode
    if code == 0 or (name == "atlas_lint" and code == LINT_REPORT_EXIT):
        stdout = completed.stdout or ""
        try:
            parsed = json.loads(stdout)
        except ValueError:
            parsed = None
        return _text_result(stdout, False, parsed if isinstance(parsed, dict) else None)
    if code == NOT_CONFIGURED_EXIT:
        return _text_result(_with_stderr(NOT_CONFIGURED, completed.stderr), True)
    return _text_result(_with_stderr(f"atlas.py saiu com o código {code}", completed.stderr), True)


# --------------------------------------------------------------------------- servidor

class Server:
    """Trata uma mensagem JSON-RPC por vez; guarda o estado da era legada."""

    def __init__(self, runner=run_cli, plugin_root=PLUGIN_ROOT):
        self.runner = runner
        self.plugin_root = Path(plugin_root)
        self.cli = self.plugin_root.joinpath(*CLI_RELATIVE)
        self.server_info = {"name": SERVER_NAME, "version": plugin_version(self.plugin_root)}
        self.legacy_version = None  # versão negociada no initialize (era legada)

    # ----- entrada

    def handle(self, message):
        """Resposta (dict) para um request, None para notificação."""
        if not isinstance(message, dict):
            return self._error(None, INVALID_REQUEST, "Invalid Request")
        has_id = "id" in message
        msg_id = message.get("id")
        valid_id = isinstance(msg_id, str) or _is_int(msg_id)  # RequestId: string ou inteiro, nunca null
        method = message.get("method")
        if message.get("jsonrpc") != "2.0" or not isinstance(method, str) or (has_id and not valid_id):
            log("request inválido")
            return self._error(msg_id if valid_id else None, INVALID_REQUEST, "Invalid Request")
        params = message.get("params", {})
        if not has_id:
            return None  # notificação: nunca recebe resposta
        try:
            if not isinstance(params, dict):
                raise ProtocolError(INVALID_PARAMS, "params precisa ser um objeto")
            modern = self._modern_version(params)
            result = self._dispatch(method, params, modern)
        except ProtocolError as exc:
            if exc.code != UNSUPPORTED_VERSION:
                log(f"erro {exc.code} em {safe_method(method)}")
            return self._error(msg_id, exc.code, exc.message, exc.data)
        if modern:
            result["resultType"] = "complete"
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _error(msg_id, code, message, data=None):
        error = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": msg_id, "error": error}

    @staticmethod
    def _modern_version(params):
        """Versão moderna pedida em _meta (None = request legado); versão não suportada vira -32022."""
        meta = params.get("_meta")
        if not isinstance(meta, dict) or VERSION_KEY not in meta:
            return None
        requested = meta[VERSION_KEY]
        if requested != MODERN_VERSION:
            raise ProtocolError(UNSUPPORTED_VERSION, "Unsupported protocol version",
                                {"supported": list(SUPPORTED_VERSIONS), "requested": requested})
        return requested

    def _dispatch(self, method, params, modern):
        if method == "initialize":
            return self._initialize(params)
        if method == "ping":
            return {}
        if method == "server/discover":
            return self._discover()
        if method == "tools/list":
            result = {"tools": [dict(tool) for tool in TOOLS]}
            if modern:
                result.update(ttlMs=CACHE_TTL_MS, cacheScope=CACHE_SCOPE)
            return result
        if method == "tools/call":
            return self._call(params)
        raise ProtocolError(METHOD_NOT_FOUND, "Method not found")

    # ----- métodos

    def _initialize(self, params):
        requested = params.get("protocolVersion")
        self.legacy_version = requested if requested in LEGACY_VERSIONS else LEGACY_DEFAULT
        return {"protocolVersion": self.legacy_version, "capabilities": {"tools": {}},
                "serverInfo": dict(self.server_info)}

    def _discover(self):
        return {"supportedVersions": list(SUPPORTED_VERSIONS), "capabilities": {"tools": {}},
                "ttlMs": CACHE_TTL_MS, "cacheScope": CACHE_SCOPE,
                "_meta": {SERVER_INFO_KEY: dict(self.server_info)}}

    def _call(self, params):
        name = params.get("name")
        if not isinstance(name, str) or name not in TOOLS_BY_NAME:
            raise ProtocolError(INVALID_PARAMS, "tool desconhecida")
        arguments = params.get("arguments", {})
        if arguments is None:
            arguments = {}
        _check(arguments, TOOLS_BY_NAME[name]["inputSchema"], "arguments")
        args = command_args(name, arguments)
        if not self.cli.is_file():
            return _text_result(f"CLI do atlas não encontrada em {self.cli}", True)
        argv = [python_executable(), str(self.cli)] + args
        try:
            completed = self.runner(argv, CLI_TIMEOUT)
        except subprocess.TimeoutExpired:
            log(f"{name}: timeout da CLI")
            return _text_result(TIMEOUT_TEXT, True)
        except OSError as exc:
            log(f"{name}: falha ao abrir a CLI ({type(exc).__name__})")
            return _text_result(f"não foi possível executar {argv[0]} {self.cli}: {exc.strerror or exc}", True)
        return map_output(name, completed)


# --------------------------------------------------------------------------- laço de stdio

def _write(stream, response):
    stream.write(json.dumps(response) + "\n")
    stream.flush()


def main():
    """Lê uma mensagem por linha do stdin e escreve cada resposta numa linha do stdout; sai com 0 no EOF."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    server = Server()
    stdin = sys.stdin.buffer
    while True:
        raw = stdin.readline()
        if not raw:
            return 0
        if not raw.strip():
            continue
        try:
            message = decode_line(raw)
        except ValueError:  # inclui UnicodeDecodeError
            log("linha com JSON inválido")
            _write(sys.stdout, Server._error(None, PARSE_ERROR, "Parse error"))
            continue
        try:
            response = server.handle(message)
        except Exception as exc:  # noqa: BLE001 — erro numa chamada não derruba o servidor
            log(f"erro interno ({type(exc).__name__})")
            msg_id = message.get("id") if isinstance(message, dict) else None
            response = Server._error(msg_id if isinstance(msg_id, (str, int)) else None, INTERNAL_ERROR,
                                     "Internal error")
        if response is not None:
            _write(sys.stdout, response)


if __name__ == "__main__":
    sys.exit(main())
