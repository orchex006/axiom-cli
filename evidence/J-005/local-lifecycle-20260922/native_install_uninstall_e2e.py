#!/usr/bin/env python3
"""Scoped native install/uninstall lifecycle proof; never touches LaunchAgents."""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
root = pathlib.Path(tempfile.mkdtemp(prefix="axiom-cli-local-lifecycle-"))
template = HERE / "fixture-template"
bundle = pathlib.Path(os.environ.get("AXIOM_E2E_BUNDLE", template))
cli = pathlib.Path(os.environ.get("AXIOM_CLI_BIN", "target/debug/axiom-cli"))
engine = pathlib.Path(os.environ["AXIOM_ENGINE_BIN"])
graph_source = pathlib.Path(os.environ.get("AXIOM_E2E_GRAPHD_BIN", "../axiom-graphd/target/debug/axiom-graphd"))
mcp_source = pathlib.Path(os.environ.get("AXIOM_E2E_MCP_SOURCE", "../axiom-mcp"))
python_dir = os.environ.get("AXIOM_E2E_PYTHON_DIR")
env = os.environ | {"AXIOM_CLI_INSTALL_ROOT": str(root), "AXIOM_ENGINE_BIN": str(engine)}
if python_dir:
    env["PATH"] = f"{python_dir}:{env['PATH']}"
elif sys.version_info[:2] == (3, 13):
    env["PATH"] = f"{pathlib.Path(sys.executable).parent}:{env['PATH']}"
else:
    raise SystemExit("set AXIOM_E2E_PYTHON_DIR to a CPython 3.13 bin directory")
results = []

def run(*args, expect=0):
    p = subprocess.run([cli, *args, "--json"], env=env, text=True, capture_output=True)
    body = json.loads(p.stdout)
    public_args = ["<generated-release>" if value == str(release) else value for value in args]
    results.append({"argv": public_args, "exit": p.returncode, "code": body.get("code")})
    if p.returncode != expect:
        raise AssertionError(f"{args}: {p.stderr or p.stdout}")
    return body

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

try:
    release = root / "release"
    shutil.copytree(bundle, release)
    template_channel = release / "channel.template.json"
    if template_channel.exists():
        template_channel.replace(release / "channel.json")
    if not list(release.glob("axiom_mcp-*.whl")):
        subprocess.run(["uv", "build", "--wheel", "--out-dir", str(release), str(mcp_source)],
                       check=True, stdout=subprocess.DEVNULL)
    graph_artifact = release / "axiom-graphd-0.0.0-dev.bin"
    shutil.copy2(graph_source, graph_artifact)
    channel_path = release / "channel.json"
    channel = json.loads(channel_path.read_text())
    artifact = next(component for component in channel["components"] if component["component"] == "axiom-graphd")["artifacts"][0]
    artifact["sha256"] = sha(graph_artifact)
    artifact["size_bytes"] = graph_artifact.stat().st_size
    mcp_artifact = next(component for component in channel["components"] if component["component"] == "axiom-mcp")["artifacts"][0]
    mcp_wheel = next(release.glob("axiom_mcp-*.whl"))
    mcp_artifact["sha256"] = sha(mcp_wheel)
    mcp_artifact["size_bytes"] = mcp_wheel.stat().st_size
    channel_path.write_text(json.dumps(channel, indent=2) + "\n")
    install_preview = run("install", "--dry-run", "--from", str(release))
    install_digest = install_preview["details"]["plan_digest"]
    run("install", "--apply", "--from", str(release), "--approve-digest", install_digest)
    activation = json.loads((root / "installs/ecosystem/current").read_text())
    graph = next(item for item in activation["activated"] if item["component"] == "axiom-graphd")
    graphd = pathlib.Path(graph["destination"])
    assert graphd.is_file() and os.access(graphd, os.X_OK)
    assert sha(graphd) == graph["sha256"]
    assert subprocess.run([graphd, "version"], capture_output=True).returncode == 0
    source = root / "source-preserved.txt"; source.write_text("human source\n")
    unowned = root / "unowned.txt"; unowned.write_text("unowned\n")
    edited_skill = root / "installs/ecosystem/skills/0.1.0/skills/example/SKILL.md"
    edited_skill.write_text(edited_skill.read_text() + "\nhuman edit\n")
    uninstall_preview = run("uninstall", "--dry-run")
    uninstall_digest = uninstall_preview["details"]["plan_digest"]
    run("uninstall", "--apply", "--approve-digest", "0" * 64, expect=6)
    run("uninstall", "--apply", "--approve-digest", uninstall_digest)
    assert source.read_text() == "human source\n" and unowned.read_text() == "unowned\n"
    assert edited_skill.read_text().endswith("human edit\n")
    assert not graphd.exists()
    (HERE / "native_install_uninstall_e2e.result.json").write_text(json.dumps({
        "schema_version": 1, "scope": "temporary AXIOM_CLI_INSTALL_ROOT", "host": "macos-x64",
        "engine_sha256": graph["sha256"], "commands": results,
        "assertions": ["installed-executable-mode", "installed-hash", "installed-version", "wrong-approval-refused", "owned-payload-removed", "source-unowned-edited-skill-preserved"],
    }, indent=2) + "\n")
finally:
    shutil.rmtree(root, ignore_errors=True)
