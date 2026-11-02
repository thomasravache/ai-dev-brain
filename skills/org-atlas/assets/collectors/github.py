#!/usr/bin/env python3
"""github collector of the org-atlas (SPEC-0034), category code: repositories, workflows, CODEOWNERS teams and
pull request signals of an organization, read through the `gh` already authenticated on the machine. Stdlib only,
Python 3.9+; prints the org-atlas/collector@1 output (ADR-0011).

Usage: python3 github.py --org ORG [--repos a,b] [--pr-sample N] [--input FOLDER]

The collector never reads the token (gh does), never reads code, PR bodies or issues and never emits author
logins: from the PRs only pattern counts and a sample of at most SAMPLE_MAX titles leave it (the scan redacts
them). --input FOLDER reads recorded responses instead of calling gh (references/collectors/github.md).
`gh` is the only external process, run by run_gh: argv as a list, never a shell, with a timeout.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

CONTRACT = "org-atlas/collector@1"
COLLECTOR = "github"
CATEGORY = "code"
DEFAULT_PR_SAMPLE = 100
SAMPLE_MAX = 10
PAGE_SIZE = 100  # the GitHub API maximum per page
GH_TIMEOUT = 120  # seconds per gh call
GH_MISSING = "gh não encontrado — instale e autentique (references/collectors/github.md)"

# type(scope)!: description — the type is a word, the scope and the "!" are optional
CONVENTIONAL = re.compile(r"^[A-Za-z]+(\([^)\n]*\))?!?: \S")
# ticket key such as ABC-123 anywhere in the title (upper case project key)
TICKET_KEY = re.compile(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9]+-\d+(?![A-Za-z0-9])")
# @org/team in CODEOWNERS; @user and e-mails are people and are ignored
TEAM_OWNER = re.compile(r"^@([A-Za-z0-9][A-Za-z0-9_.-]*)/([A-Za-z0-9][A-Za-z0-9_.-]*)$")
WORKFLOW_EXTENSIONS = (".yml", ".yaml")
MERGE_FIELDS = (("merge", "allow_merge_commit"), ("squash", "allow_squash_merge"), ("rebase", "allow_rebase_merge"))
# where GitHub looks for CODEOWNERS and the PR template, in its order
CODEOWNERS_PATHS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")
TEMPLATE_DIRS = (".github", "", "docs")
TEMPLATE_FILE = "pull_request_template.md"
TEMPLATE_FOLDER = "pull_request_template"
HTTP_STATUS = re.compile(r"HTTP (\d{3})")


class CollectorError(Exception):
    """A failure that ends the collector with exit 1; the message is shown as is."""


class GhError(Exception):
    """A gh call that failed; status is the HTTP status (None when unknown), auth = gh has no usable login."""

    def __init__(self, path: str, status=None, auth: bool = False, detail: str = ""):
        reason = f"HTTP {status}" if status else detail
        super().__init__(f"gh api {path} falhou" + (f" ({reason})" if reason else ""))
        self.path = path
        self.status = status
        self.auth = auth


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def entity(kind: str, eid: str, name: str, attrs: dict) -> dict:
    return {"kind": kind, "id": eid, "name": name, "attrs": attrs, "source": COLLECTOR}


def relation(source_ref: str, target_ref: str, rtype: str) -> dict:
    return {"from": source_ref, "to": target_ref, "type": rtype, "source": COLLECTOR}


# --------------------------------------------------------------------------- mapping (pure functions)


def count_title_patterns(titles):
    """PR titles -> {"total", "pattern_counts": {conventional, ticket_key, other}, "sample": [<= SAMPLE_MAX]}.
    Each title counts once: Conventional Commits first, then a ticket key, the rest is other. The sample is the
    first titles in the given order (the API returns the newest first)."""
    counts = {"conventional": 0, "ticket_key": 0, "other": 0}
    titles = [t for t in titles if isinstance(t, str)]
    for title in titles:
        if CONVENTIONAL.match(title.strip()):
            counts["conventional"] += 1
        elif TICKET_KEY.search(title):
            counts["ticket_key"] += 1
        else:
            counts["other"] += 1
    return {"total": len(titles), "pattern_counts": counts, "sample": titles[:SAMPLE_MAX]}


def count_branch_prefixes(branches):
    """PR branches -> {"total", "counts": {"feat/": n, ...}}; the prefix is the first segment plus "/".
    A branch without "/" counts in total but has no prefix."""
    counts = {}
    branches = [b for b in branches if isinstance(b, str)]
    for branch in branches:
        head, sep, _ = branch.partition("/")
        if sep and head:
            counts[head + "/"] = counts.get(head + "/", 0) + 1
    return {"total": len(branches), "counts": counts}


def map_repository(org, repo):
    """One repository of the repos response -> entity repository:<org>/<name> with only the contract attrs."""
    name = repo["name"]
    visibility = repo.get("visibility") or ("private" if repo.get("private") else "public")
    topics = [t for t in repo.get("topics") or [] if isinstance(t, str)]
    return entity("repository", f"{org}/{name}", name, {
        "language": repo.get("language"),
        "default_branch": repo.get("default_branch"),
        "topics": topics,
        "archived": bool(repo.get("archived", False)),
        "visibility": visibility,
    })


def map_workflows(org, repo_name, response):
    """actions/workflows response -> (pipeline entities, builds relations); the pipeline id is the workflow file
    name without the extension. Workflows without a file (path dynamic/..., such as Pages) are skipped."""
    entities, relations, seen = [], [], set()
    repo_ref = f"repository:{org}/{repo_name}"
    for workflow in (response or {}).get("workflows") or []:
        path = workflow.get("path") or ""
        if not path or path.startswith("dynamic/"):
            continue
        stem = path.rsplit("/", 1)[-1]
        for ext in WORKFLOW_EXTENSIONS:
            if stem.endswith(ext):
                stem = stem[: -len(ext)]
                break
        pid = f"{org}/{repo_name}/{stem}"
        if pid in seen:
            continue
        seen.add(pid)
        entities.append(entity("pipeline", pid, workflow.get("name") or stem, {"file": path}))
        relations.append(relation(f"pipeline:{pid}", repo_ref, "builds"))
    return entities, relations


def parse_codeowners(org, repo_name, text):
    """CODEOWNERS text -> (team entities, owns relations), each team once; users and e-mails are ignored."""
    entities, relations, seen = [], [], set()
    for line in (text or "").splitlines():
        tokens = line.split()
        if not tokens or tokens[0].startswith("#"):
            continue
        for owner in tokens[1:]:
            if owner.startswith("#"):  # comment at the end of the line
                break
            match = TEAM_OWNER.match(owner)
            if not match:
                continue
            tid = f"{match.group(1)}/{match.group(2)}"
            if tid in seen:
                continue
            seen.add(tid)
            entities.append(entity("team", tid, match.group(2), {}))
            relations.append(relation(f"team:{tid}", f"repository:{org}/{repo_name}", "owns"))
    return entities, relations


def map_policy(full_name, repo_response, has_template):
    """GET repos/{org}/{repo} and the template presence -> (merge-methods and pr-template signals, warnings).
    Without the allow_* fields (a token that cannot see them) merge-methods is left out with a warning."""
    signals, warnings = [], []
    response = repo_response if isinstance(repo_response, dict) else {}
    if all(isinstance(response.get(field), bool) for _, field in MERGE_FIELDS):
        signals.append({"type": "merge-methods", "repository": full_name,
                        "present": {method: response[field] for method, field in MERGE_FIELDS}})
    else:
        warnings.append(f"aviso: {full_name}: a resposta não traz allow_merge_commit, allow_squash_merge e "
                        "allow_rebase_merge (token sem permissão?) — sinal merge-methods omitido")
    signals.append({"type": "pr-template", "repository": full_name, "present": {"pr_template": bool(has_template)}})
    return signals, warnings


def has_template_entry(listing) -> bool:
    """A contents listing of a folder has pull_request_template.md (any case) or the PULL_REQUEST_TEMPLATE/ folder."""
    for item in listing if isinstance(listing, list) else []:
        name = str(item.get("name", "")).lower() if isinstance(item, dict) else ""
        if (item.get("type") == "file" and name == TEMPLATE_FILE) or (item.get("type") == "dir"
                                                                      and name == TEMPLATE_FOLDER):
            return True
    return False


# --------------------------------------------------------------------------- sources: --input folder and gh


class InputSource:
    """Recorded responses in a folder (--input): repos.json, workflows/<repo>.json, codeowners/<repo>,
    pulls/<repo>.json, repo/<repo>.json and pr-template/<repo> (the file existing = template present)."""

    def __init__(self, folder: str):
        self.folder = Path(folder)
        if not self.folder.is_dir():
            raise CollectorError(f"--input: pasta não encontrada: {folder}")

    def _json(self, rel: str, default=None, required=False):
        path = self.folder / rel
        if not path.is_file():
            if required:
                raise CollectorError(f"--input: {rel} não encontrado em {self.folder}")
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            raise CollectorError(f"--input: {rel}: não consegui ler ({e})") from None

    def repos(self) -> list:
        return self._json("repos.json", required=True)

    def repository(self, name: str):
        return self._json(f"repo/{name}.json", {})

    def workflows(self, name: str):
        return self._json(f"workflows/{name}.json", {"workflows": []})

    def codeowners(self, name: str):
        path = self.folder / "codeowners" / name
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def pulls(self, name: str, limit: int) -> list:
        return (self._json(f"pulls/{name}.json", []) or [])[:limit]

    def has_template(self, name: str) -> bool:
        return (self.folder / "pr-template" / name).is_file()


def parse_pages(text: str) -> list:
    """The JSON values printed by `gh api --paginate` (one per page, back to back) as a list."""
    decoder, pages, i = json.JSONDecoder(), [], 0
    while True:
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            return pages
        value, i = decoder.raw_decode(text, i)
        pages.append(value)


def run_gh(gh: str, args: list, path: str) -> str:
    """The only external process of the collector: gh with argv as a list, never a shell, with a timeout.
    Returns stdout; a failure is GhError (HTTP status from gh's stderr, auth when gh has no login)."""
    env = dict(os.environ, GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1", NO_COLOR="1")
    try:
        proc = subprocess.run([gh, *args], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=GH_TIMEOUT, env=env, check=False)
    except FileNotFoundError:
        raise CollectorError(GH_MISSING) from None
    except subprocess.TimeoutExpired:
        raise CollectorError(f"gh api {path}: tempo esgotado ({GH_TIMEOUT} s)") from None
    except OSError as e:
        raise CollectorError(f"não consegui executar gh: {e.strerror or e}") from None
    if proc.returncode == 0:
        return proc.stdout
    match = HTTP_STATUS.search(proc.stderr or "")
    status = int(match.group(1)) if match else None
    # exit 4 = gh needs `gh auth login`; 401 = invalid token
    auth = proc.returncode == 4 or status == 401
    detail = (proc.stderr or "").strip().splitlines()[-1:] or [f"saiu com {proc.returncode}"]
    raise GhError(path, status=status, auth=auth, detail=detail[0][:200])


class GhSource:
    """The same data through `gh api` (lists with --paginate), read with the standard library (no --jq)."""

    def __init__(self, org: str):
        self.org = org
        self.gh = shutil.which("gh")
        if self.gh is None:
            raise CollectorError(GH_MISSING)

    def _api(self, path: str, paginate=False, optional=False, org_call=False):
        """gh api <path> parsed: one value, or the list of pages with paginate. optional = 404 is None;
        org_call = the first call, whose 403/404 mean no access to or no such organization."""
        args = ["api", "-H", "Accept: application/vnd.github+json"] + (["--paginate"] if paginate else [])
        try:
            text = run_gh(self.gh, args + [path], path)
        except GhError as e:
            if e.auth or (org_call and e.status == 403):
                raise CollectorError(f"gh sem acesso à organização {self.org}") from None
            if org_call and e.status == 404:
                raise CollectorError(f"organização não encontrada: {self.org}") from None
            if optional and e.status == 404:
                return None
            raise CollectorError(str(e)) from None
        try:
            pages = parse_pages(text)
        except json.JSONDecodeError:
            raise CollectorError(f"gh api {path}: resposta que não é JSON") from None
        if paginate:
            return pages
        return pages[0] if pages else None

    def repos(self) -> list:
        pages = self._api(f"orgs/{self.org}/repos?per_page={PAGE_SIZE}", paginate=True, org_call=True)
        return [repo for page in pages if isinstance(page, list) for repo in page]

    def repository(self, name: str):
        return self._api(f"repos/{self.org}/{name}", optional=True) or {}

    def workflows(self, name: str):
        pages = self._api(f"repos/{self.org}/{name}/actions/workflows?per_page={PAGE_SIZE}", paginate=True,
                          optional=True) or []
        return {"workflows": [w for page in pages if isinstance(page, dict) for w in page.get("workflows") or []]}

    def codeowners(self, name: str):
        for path in CODEOWNERS_PATHS:
            data = self._api(f"repos/{self.org}/{name}/contents/{path}", optional=True)
            if isinstance(data, dict) and data.get("type") == "file":
                try:
                    return base64.b64decode(data.get("content") or "").decode("utf-8", errors="replace")
                except (binascii.Error, ValueError):
                    return None
        return None

    def pulls(self, name: str, limit: int) -> list:
        """The first `limit` PRs (all states, newest first), page by page: only the pages needed are fetched."""
        prs, page = [], 1
        while len(prs) < limit:
            size = min(PAGE_SIZE, limit)
            data = self._api(f"repos/{self.org}/{name}/pulls?state=all&per_page={size}&page={page}",
                             optional=True)
            if not isinstance(data, list) or not data:
                break
            prs.extend(data)
            if len(data) < size:
                break
            page += 1
        return prs[:limit]

    def has_template(self, name: str) -> bool:
        for folder in TEMPLATE_DIRS:
            path = f"repos/{self.org}/{name}/contents" + (f"/{folder}" if folder else "")
            if has_template_entry(self._api(path, optional=True)):
                return True
        return False


# --------------------------------------------------------------------------- collection


def selected(repos: list, wanted, org: str) -> list:
    """The repositories of the response, only the --repos ones when given (a warning for an unknown name)."""
    repos = [r for r in repos if isinstance(r, dict) and r.get("name")]
    if not wanted:
        return repos
    names = {r["name"] for r in repos}
    for name in wanted:
        if name not in names:
            print(f"aviso: repositório não encontrado na organização {org}: {name}", file=sys.stderr)
    return [r for r in repos if r["name"] in wanted]


def collect(org: str, source, wanted=None, pr_sample: int = DEFAULT_PR_SAMPLE) -> tuple:
    """(contract output, warnings) of the organization from a source (InputSource or GhSource)."""
    entities, relations, signals, warnings = [], [], [], []
    teams = set()
    for repo in selected(source.repos(), wanted, org):
        name = repo["name"]
        full_name = f"{org}/{name}"
        entities.append(map_repository(org, repo))
        pipelines, builds = map_workflows(org, name, source.workflows(name))
        entities += pipelines
        relations += builds
        owners, owns = parse_codeowners(org, name, source.codeowners(name))
        entities += [team for team in owners if team["id"] not in teams]
        teams.update(team["id"] for team in owners)
        relations += owns
        prs = [pr for pr in source.pulls(name, pr_sample) if isinstance(pr, dict)] if pr_sample else []
        titles = count_title_patterns([pr.get("title") for pr in prs])
        branches = count_branch_prefixes([(pr.get("head") or {}).get("ref") for pr in prs])
        signals.append({"type": "pr-titles", "repository": full_name, **titles})
        signals.append({"type": "branch-prefixes", "repository": full_name, **branches})
        policy, policy_warnings = map_policy(full_name, source.repository(name), source.has_template(name))
        signals += policy
        warnings += policy_warnings
    data = {"contract": CONTRACT, "collector": COLLECTOR, "category": CATEGORY, "collected_at": utc_now(),
            "entities": entities, "relations": relations, "signals": signals}
    return data, warnings


def build_parser():
    parser = argparse.ArgumentParser(prog="github.py", description="Coletor github da org-atlas")
    parser.add_argument("--org", required=True, help="organização no GitHub")
    parser.add_argument("--repos", default=None, help="só estes repositórios (a,b)")
    parser.add_argument("--pr-sample", type=int, default=DEFAULT_PR_SAMPLE, help="PRs lidos por repositório")
    parser.add_argument("--input", default=None, help="pasta com respostas gravadas em vez do gh")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.pr_sample < 0:
        parser.error("--pr-sample precisa ser um inteiro ≥ 0")
    wanted = None
    if args.repos:
        # "a,b" or "org/a,org/b"
        wanted = [r.strip().split("/")[-1] for r in args.repos.split(",") if r.strip()]
    try:
        source = InputSource(args.input) if args.input else GhSource(args.org)
        data, warnings = collect(args.org, source, wanted, args.pr_sample)
    except CollectorError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 1
    for warning in warnings:
        print(warning, file=sys.stderr)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
