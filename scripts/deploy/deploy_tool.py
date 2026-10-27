"""Deployment helper for the GitHub workflows.

Names, paths, commands and values come from deploy/settings.json and
deploy/components/<id>.json. Only the contract layout and the output names
(bicep-params.json, the stage folder, <id>.zip) are fixed here.
Standard library only, so it runs on Windows and on ubuntu-latest.
"""

from __future__ import annotations

import argparse
import fnmatch
import http.client
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = ROOT / "deploy" / "settings.json"
COMPONENTS_DIR = ROOT / "deploy" / "components"
FOUNDRY_COMPONENT = "foundry-agent"
APP_SERVICE = "appService"
FOUNDRY_AGENT = "foundryAgent"
IAC_KINDS = (APP_SERVICE, FOUNDRY_AGENT)
PHASES = ("install", "unitTest", "build", "e2e")
PARAMS_FILE = "bicep-params.json"
PARAMS_SCHEMA = "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#"
STAGE_DIR = "stage"
APP_SERVICE_HOST = ".azurewebsites.net"
REQUEST_TIMEOUT_SECONDS = 30
APP_SERVICE_WWWROOT = "/home/site/wwwroot"
SMOKE_ATTEMPTS = 30
SMOKE_DELAY_SECONDS = 2


class ConfigError(Exception):
    """Missing or invalid contract data, or an unsupported request (exit code 2)."""


class Doc:
    """A parsed JSON object with dotted-path lookup and optional type checks."""

    def __init__(self, label: str, data: Any) -> None:
        self.label = label
        self.data = data

    def get(
        self,
        dotted: str,
        kind: type | tuple[type, ...] | None = None,
        required: bool = True,
    ) -> Any:
        node: Any = self.data
        for key in dotted.split("."):
            if not isinstance(node, dict) or key not in node:
                if required:
                    raise ConfigError(f"field '{dotted}' not found in {self.label}")
                return None
            node = node[key]
        if kind is not None and not isinstance(node, kind):
            raise ConfigError(f"field '{dotted}' in {self.label} has the wrong type")
        return node


def read_json(path: Path) -> Any:
    try:
        # utf-8-sig also accepts a BOM that Windows tools may add.
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from None


def write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_settings() -> Doc:
    return Doc("settings.json", read_json(SETTINGS_PATH))


def load_component(component_id: str) -> Doc:
    return Doc(f"{component_id}.json", read_json(COMPONENTS_DIR / f"{component_id}.json"))


def require_kind(component: Doc, kind: str) -> None:
    actual = component.get("kind", str)
    if actual != kind:
        raise ConfigError(f"{component.label} has kind '{actual}'; this command needs '{kind}'")


def format_value(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))


def is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def ignore_matching(patterns: list[str]) -> Callable[[str, list[str]], list[str]]:
    def ignore(_directory: str, names: list[str]) -> list[str]:
        return [name for name in names if any(fnmatch.fnmatch(name, pattern) for pattern in patterns)]

    return ignore


def phase_commands(validate: dict[str, Any], phase: str) -> list[Any]:
    if phase != "e2e":
        return [validate[phase]] if validate.get(phase) else []
    e2e = validate.get("e2e") or {}
    if not isinstance(e2e, dict):
        raise ConfigError("validate.e2e must be an object with install and run commands")
    return [e2e[step] for step in ("install", "run") if e2e.get(step)]


def run_command(command: Any, cwd: Path) -> int:
    if not command or not is_string_list(command):
        raise ConfigError(f"command must be a non-empty list of strings: {command!r}")
    executable = shutil.which(command[0])
    if executable is None:
        print(f"error: executable not found on PATH: {command[0]}", file=sys.stderr)
        return 1
    print(f"$ {' '.join(command)}  (in {cwd})", flush=True)
    return subprocess.run([executable, *command[1:]], cwd=cwd).returncode


def write_params(out_dir: Path, params: dict[str, Any]) -> Path:
    document = {
        "$schema": PARAMS_SCHEMA,
        "contentVersion": "1.0.0.0",
        "parameters": {name: {"value": value} for name, value in params.items()},
    }
    path = out_dir / PARAMS_FILE
    write_json(path, document)
    return path


def cmd_info(args: argparse.Namespace) -> int:
    print(format_value(load_component(args.component).get(args.field)))
    return 0


def cmd_setting(args: argparse.Namespace) -> int:
    print(format_value(load_settings().get(args.field)))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    component = load_component(args.component)
    workdir = ROOT / component.get("sourcePath", str)
    if not workdir.is_dir():
        raise ConfigError(f"sourcePath does not exist: {workdir}")
    validate = component.get("validate", dict, required=False) or {}
    commands = phase_commands(validate, args.phase)
    if not commands:
        print(f"skip {args.phase}")
        return 0
    for command in commands:
        code = run_command(command, workdir)
        if code != 0:
            return code
    return 0


def app_service_params(component: Doc, settings: Doc) -> dict[str, Any]:
    app_settings = component.get("azure.appSettings", dict)
    if not all(isinstance(value, str) for value in app_settings.values()):
        raise ConfigError(f"azure.appSettings in {component.label} must map names to strings")
    return {
        "appName": component.get("azure.appName", str),
        "planName": settings.get("appServicePlan", str),
        "location": settings.get("location", str),
        "runtime": component.get("azure.runtime", str),
        "startupCommand": component.get("azure.startupCommand", str),
        "healthPath": component.get("azure.healthPath", str),
        "appSettings": app_settings,
    }


def foundry_agent_params(component: Doc) -> dict[str, Any]:
    return {
        "foundryAccountName": component.get("foundry.accountName", str),
        "foundryProjectName": component.get("foundry.projectName", str),
        "foundryLocation": component.get("foundry.location", str),
        "projectDescription": component.get("foundry.projectDescription", str),
        "apiAppName": component.get("foundry.apiAppName", str),
        "apiIdentityRoleDefinitionId": component.get("foundry.apiIdentityRole.roleDefinitionId", str),
        "apiIdentityRoleAssignmentName": component.get("foundry.apiIdentityRole.assignmentName", str),
        "grantApiIdentityRole": component.get("foundry.apiIdentityRole.grant", bool),
        "deployIdentityName": load_settings().get("deployIdentity.name", str),
    }


def cmd_render(args: argparse.Namespace) -> int:
    if args.tool != "bicep":
        raise ConfigError(
            f"Terraform rendering is not implemented yet; only --tool bicep works (got '{args.tool}')"
        )
    component = load_component(args.component)
    kind = component.get("kind", str)
    if kind == APP_SERVICE:
        params = app_service_params(component, load_settings())
    elif kind == FOUNDRY_AGENT:
        params = foundry_agent_params(component)
    else:
        raise ConfigError(f"render does not support kind '{kind}'")
    print(f"rendered {write_params(Path(args.out), params)}")
    return 0


def cmd_render_bootstrap(args: argparse.Namespace) -> int:
    settings = load_settings()
    foundry = load_component(FOUNDRY_COMPONENT)
    params = {
        "deployIdentityName": settings.get("deployIdentity.name", str),
        "deployIdentityIssuer": settings.get("deployIdentity.issuer", str),
        "deployIdentitySubject": settings.get("deployIdentity.subject", str),
        "deployIdentityAudience": settings.get("deployIdentity.audience", str),
        "grantContributorOnResourceGroup": settings.get("deployIdentity.grantContributorOnResourceGroup", bool),
        "grantUserAccessAdministratorOnFoundryAccount": settings.get(
            "deployIdentity.grantUserAccessAdministratorOnFoundryAccount", bool
        ),
        "foundryAccountName": foundry.get("foundry.accountName", str),
        "contributorRoleDefinitionId": settings.get("deployIdentity.roleDefinitionIds.contributor", str),
        "userAccessAdministratorRoleDefinitionId": settings.get(
            "deployIdentity.roleDefinitionIds.userAccessAdministrator", str
        ),
        "storageBlobDataContributorRoleDefinitionId": settings.get(
            "deployIdentity.roleDefinitionIds.storageBlobDataContributor", str
        ),
        "createTerraformState": settings.get("terraformState.create", bool),
        "terraformStateAccountName": settings.get("terraformState.storageAccountName", str),
        "terraformStateContainerName": settings.get("terraformState.containerName", str),
        "terraformStateSkuName": settings.get("terraformState.skuName", str),
        "location": settings.get("location", str),
    }
    print(f"rendered {write_params(Path(args.out), params)}")
    return 0


def cmd_package(args: argparse.Namespace) -> int:
    component = load_component(args.component)
    require_kind(component, APP_SERVICE)
    exclude = load_settings().get("packaging.exclude", list)
    out_dir = Path(args.out)
    stage = out_dir / STAGE_DIR
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    for index, raw in enumerate(component.get("package.stage", list)):
        entry = Doc(f"{component.label} package.stage[{index}]", raw)
        source = ROOT / entry.get("from", str)
        target = stage / entry.get("to", str)
        if not source.exists():
            raise ConfigError(f"package source not found: {source}")
        if source.is_dir():
            shutil.copytree(source, target, ignore=ignore_matching(exclude), dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    for index, raw in enumerate(component.get("package.patchJson", list)):
        patch = Doc(f"{component.label} package.patchJson[{index}]", raw)
        target = stage / patch.get("file", str)
        current = read_json(target) if target.exists() else {}
        if not isinstance(current, dict):
            raise ConfigError(f"cannot patch {target}: it does not contain a JSON object")
        write_json(target, deep_merge(current, patch.get("values", dict)))

    vendor = component.get("package.vendorPython", dict, required=False)
    if vendor is not None:
        vendor_python(component, stage, vendor)

    zip_path = out_dir / f"{args.component}.zip"
    files = sorted(path for path in stage.rglob("*") if path.is_file())
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(stage).as_posix())
    print(f"packaged {zip_path} ({len(files)} files)")
    return 0


def vendor_python(component: Doc, stage: Path, vendor: dict[str, Any]) -> None:
    """Install the Linux wheels for the Python requirements into the stage, so App Service runs no build.

    The wheels match the App Service platform (cp312, manylinux), and the smoke test starts the same files.
    """
    entry = Doc(f"{component.label} package.vendorPython", vendor)
    command = [
        sys.executable, "-m", "pip", "install",
        "--target", str(stage / entry.get("target", str)),
        *[option for platform in entry.get("platforms", list) for option in ("--platform", str(platform))],
        "--implementation", "cp",
        "--python-version", entry.get("pythonVersion", str),
        "--only-binary=:all:",
        "--no-compile",
        "--disable-pip-version-check",
        "--requirement", str(ROOT / entry.get("requirements", str)),
    ]
    if subprocess.run(command, cwd=ROOT).returncode != 0:
        raise ConfigError(f"could not vendor the Python dependencies of {component.label}")


def fetch_status(url: str) -> tuple[int | None, str]:
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return response.status, ""
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (OSError, http.client.HTTPException) as exc:  # URLError is an OSError subclass.
        return None, str(exc)


def cmd_health(args: argparse.Namespace) -> int:
    component = load_component(args.component)
    require_kind(component, APP_SERVICE)
    settings = load_settings()
    attempts = settings.get("healthCheck.attempts", int)
    delay = settings.get("healthCheck.delaySeconds", (int, float))
    if attempts < 1:
        raise ConfigError("healthCheck.attempts must be at least 1")
    app_name = component.get("azure.appName", str)
    health_path = component.get("azure.healthPath", str)
    url = f"https://{app_name}{APP_SERVICE_HOST}{health_path}"
    for attempt in range(1, attempts + 1):
        status, error = fetch_status(url)
        if status is not None and 200 <= status <= 399:
            print(f"healthy: {url} returned HTTP {status} (attempt {attempt}/{attempts})")
            return 0
        detail = f"HTTP {status}" if status is not None else error
        print(f"attempt {attempt}/{attempts} failed: {detail}")
        if attempt < attempts:
            time.sleep(delay)
    print(f"health check failed after {attempts} attempts: {url}", file=sys.stderr)
    return 1


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def cmd_smoke(args: argparse.Namespace) -> int:
    """Start the packaged app with its App Service startup command and check that the health path answers.

    The deploy job runs this before Bicep and the zip deploy, so a broken package never reaches the web app.
    App settings become environment variables, with the App Service folder replaced by the extracted folder.
    """
    component = load_component(args.component)
    require_kind(component, APP_SERVICE)
    app_settings = component.get("azure.appSettings", dict)
    startup = shlex.split(component.get("azure.startupCommand", str))
    port = int(app_settings.get("WEBSITES_PORT", "8000"))
    url = f"http://127.0.0.1:{port}{component.get('azure.healthPath', str)}"
    with tempfile.TemporaryDirectory(prefix="smoke-") as tmp:
        root = Path(tmp) / "app"
        with zipfile.ZipFile(args.package) as archive:
            archive.extractall(root)
        env = dict(os.environ)
        env.update({name: str(value).replace(APP_SERVICE_WWWROOT, str(root)) for name, value in app_settings.items()})
        log_path = Path(tmp) / "smoke.log"
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(startup, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                for attempt in range(1, SMOKE_ATTEMPTS + 1):
                    if process.poll() is not None:
                        print(f"the app exited early with code {process.returncode}")
                        break
                    status, error = fetch_status(url)
                    if status is not None and 200 <= status <= 399:
                        print(f"smoke test passed: {url} returned HTTP {status} (attempt {attempt}/{SMOKE_ATTEMPTS})")
                        return 0
                    detail = f"HTTP {status}" if status is not None else error
                    print(f"attempt {attempt}/{SMOKE_ATTEMPTS} failed: {detail}")
                    time.sleep(SMOKE_DELAY_SECONDS)
            finally:
                stop_process(process)
        print(log_path.read_text(encoding="utf-8")[-4000:], file=sys.stderr)
    print(f"smoke test failed: {url} did not return a healthy status", file=sys.stderr)
    return 1


def iac_templates() -> list[Path]:
    relative = [load_settings().get("bootstrap.bicepTemplate", str)]
    for path in sorted(COMPONENTS_DIR.glob("*.json")):
        component = load_component(path.stem)
        if component.get("kind", str) in IAC_KINDS:
            relative.append(component.get("infra.bicepTemplate", str))
    return list(dict.fromkeys(ROOT / item for item in relative))


def cmd_validate_iac(args: argparse.Namespace) -> int:
    templates = iac_templates()
    az = shutil.which("az")
    if az is None:
        print("error: Azure CLI (az) not found on PATH", file=sys.stderr)
        return 1
    failures = 0
    for template in templates:
        if not template.is_file():
            print(f"FAILED {template}: file not found")
            failures += 1
            continue
        result = subprocess.run(
            [az, "bicep", "build", "--file", str(template), "--stdout"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            print(f"ok {template}")
        else:
            print(f"FAILED {template}")
            print(result.stderr.strip(), file=sys.stderr)
            failures += 1
    return 1 if failures else 0


FOUNDRY_SCOPE = "https://ai.azure.com"
FOUNDRY_API_VERSION = "v1"
FOUNDRY_PROJECT_URL = "https://{account}.services.ai.azure.com/api/projects/{project}"


def foundry_token() -> str:
    az = shutil.which("az")
    if az is None:
        raise ConfigError("Azure CLI (az) was not found on PATH")
    result = subprocess.run(
        [az, "account", "get-access-token", "--resource", FOUNDRY_SCOPE, "--query", "accessToken", "-o", "tsv"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ConfigError(f"cannot get a Foundry token: {result.stderr.strip()}")
    return result.stdout.strip()


def foundry_call(method: str, url: str, token: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = response.read()
            return response.status, (json.loads(payload) if payload else None)
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")


def cmd_upsert_foundry(args: argparse.Namespace) -> int:
    component = load_component(args.component)
    require_kind(component, FOUNDRY_AGENT)
    account = component.get("foundry.accountName", str)
    project = component.get("foundry.projectName", str)
    agent = component.get("foundry.agentName", str)
    model = component.get("foundry.modelDeployment", str)
    instructions_file = component.get("foundry.instructionsFile", str)
    instructions_key = component.get("foundry.instructionsProperty", str)

    config = read_json(ROOT / instructions_file)
    instructions = config.get(instructions_key) if isinstance(config, dict) else None
    if not isinstance(instructions, str) or not instructions:
        raise ConfigError(f"{instructions_file} has no text in '{instructions_key}'")
    definition = {"kind": "prompt", "model": model, "instructions": instructions}

    base = FOUNDRY_PROJECT_URL.format(account=account, project=project)
    agents_url = f"{base}/agents"
    agent_url = f"{agents_url}/{agent}"
    token = foundry_token()

    status, current = foundry_call("GET", f"{agent_url}?api-version={FOUNDRY_API_VERSION}", token)
    if status == 404:
        if args.dry_run:
            print(f"dry run: would create agent {agent}")
            return 0
        status, created = foundry_call(
            "POST", f"{agents_url}?api-version={FOUNDRY_API_VERSION}", token, {"name": agent, "definition": definition}
        )
        if status >= 300:
            print(f"cannot create agent {agent}: HTTP {status} {created}", file=sys.stderr)
            return 1
        print(f"created agent {agent}")
        return 0
    if status != 200 or not isinstance(current, dict):
        print(f"cannot read agent {agent}: HTTP {status} {current}", file=sys.stderr)
        return 1

    latest = (current.get("versions") or {}).get("latest") or {}
    live = latest.get("definition") or {}
    if live.get("instructions") == instructions and live.get("model") == model and live.get("kind") == "prompt":
        print(f"agent {agent} is up to date (version {latest.get('version')})")
        return 0
    if args.dry_run:
        print(f"dry run: would create a new version of {agent} (current version {latest.get('version')})")
        return 0
    status, version = foundry_call(
        "POST", f"{agent_url}/versions?api-version={FOUNDRY_API_VERSION}", token, {"definition": definition}
    )
    if status >= 300:
        print(f"cannot create a version of {agent}: HTTP {status} {version}", file=sys.stderr)
        return 1
    new_version = version.get("version") if isinstance(version, dict) else None
    print(f"created version {new_version} of agent {agent}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deployment helper driven by deploy/settings.json and deploy/components/<id>.json.",
    )
    subcommands = parser.add_subparsers(dest="command", metavar="command", required=True)

    def add(name: str, handler: Callable[[argparse.Namespace], int], help_text: str) -> argparse.ArgumentParser:
        sub = subcommands.add_parser(name, help=help_text, description=help_text)
        sub.set_defaults(handler=handler)
        return sub

    sub = add("info", cmd_info, "print a field from a component descriptor")
    sub.add_argument("--component", required=True, help="component id, e.g. ui")
    sub.add_argument("--field", required=True, help="dotted field path, e.g. azure.appName")

    sub = add("setting", cmd_setting, "print a field from deploy/settings.json")
    sub.add_argument("--field", required=True, help="dotted field path, e.g. location")

    sub = add("run", cmd_run, "run one validation phase of a component inside its sourcePath")
    sub.add_argument("--component", required=True, help="component id, e.g. api")
    sub.add_argument("--phase", required=True, choices=PHASES, help="validation phase")

    sub = add("render", cmd_render, "write bicep-params.json for a component")
    sub.add_argument("--component", required=True, help="component id, e.g. ui")
    sub.add_argument("--out", required=True, help="output directory")
    sub.add_argument("--tool", default="bicep", help="IaC tool; only bicep is supported")

    sub = add("render-bootstrap", cmd_render_bootstrap, "write bicep-params.json for the bootstrap template")
    sub.add_argument("--out", required=True, help="output directory")

    sub = add("package", cmd_package, "stage an appService component and zip it to <out>/<id>.zip")
    sub.add_argument("--component", required=True, help="component id, e.g. ui")
    sub.add_argument("--out", required=True, help="output directory")

    sub = add("health", cmd_health, "poll the health URL of an appService component")
    sub.add_argument("--component", required=True, help="component id, e.g. api")

    sub = add("smoke", cmd_smoke, "start a packaged appService app with its startup command and check its health path")
    sub.add_argument("--component", required=True, help="component id, e.g. api")
    sub.add_argument("--package", required=True, help="path to the zip written by package")

    add("validate-iac", cmd_validate_iac, "run az bicep build on every IaC template")

    sub = add("upsert-foundry", cmd_upsert_foundry, "create the Foundry agent or add a version when its instructions or model change")
    sub.add_argument("--component", required=True, help="component id, e.g. foundry-agent")
    sub.add_argument("--dry-run", action="store_true", help="report the planned changes only")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
