#!/usr/bin/env python3
"""Provision an offline MCP bundle into a per-user, versioned Intel Mac root."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

RUNTIME_SHA256 = "327814efd865a0b6a99c149b12a261e9d0ad409183515c745d41bda2d07282e9"
RUNTIME_NAME = "cpython-3.13.15-macos-x64.tar.gz"
MCP_NAME = "axiom_mcp-0.1.0-py3-none-any.whl"
MCP_SHA256 = "365d4d2baa3b155b1c2cb661fdfd8439db1f628ba9ea524e0b0ee49d14c22705"
LOCK_SHA256 = "5cf467f4d856044458d29124fa866632fdf64f398dd3fd227f6b6d3501ed99c9"


class Refusal(Exception):
    pass


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_root(path: Path) -> Path:
    raw_home = Path.home()
    home = raw_home.resolve()
    if os.geteuid() == 0:
        raise Refusal("root_user_refused")
    if not path.is_absolute() or ".." in path.parts:
        raise Refusal("root_outside_user_home")
    if path != raw_home and raw_home in path.parents:
        cursor = path
        while cursor != raw_home:
            if cursor.is_symlink():
                raise Refusal("symlink_at_managed_path")
            cursor = cursor.parent
    path = path.resolve(strict=False)
    if path == home or home not in path.parents:
        raise Refusal("root_outside_user_home")
    cursor = path
    while cursor != home:
        if cursor.is_symlink():
            raise Refusal("symlink_at_managed_path")
        cursor = cursor.parent
    return path


def bundle_manifest(bundle: Path) -> tuple[dict, str]:
    if bundle.is_symlink() or not bundle.is_dir():
        raise Refusal("bundle_path_invalid")
    path = bundle / "mcp-bundle.json"
    if not path.is_file() or path.is_symlink():
        raise Refusal("bundle_manifest_missing")
    try:
        value = json.loads(path.read_text())
    except (ValueError, UnicodeError) as error:
        raise Refusal("bundle_manifest_invalid") from error
    if value.get("schema_version") != 1 or value.get("platform") != "macos-x64":
        raise Refusal("bundle_manifest_incompatible")
    if value.get("python_version") != "3.13.15" or value.get("mcp_version") != "0.1.0":
        raise Refusal("bundle_version_incompatible")
    if value.get("python_runtime_sha256") != RUNTIME_SHA256 or value.get("mcp_wheel_sha256") != MCP_SHA256:
        raise Refusal("pinned_artifact_disagrees")
    rows = value.get("artifacts")
    if not isinstance(rows, list) or len(rows) != 36:
        raise Refusal("bundle_artifacts_invalid")
    seen = set()
    for row in rows:
        relative = row.get("path") if isinstance(row, dict) else None
        if not isinstance(relative, str) or not relative or relative.startswith("/") or ".." in Path(relative).parts or relative in seen:
            raise Refusal("bundle_artifact_path_invalid")
        seen.add(relative)
        source = bundle / relative
        if not source.is_file() or source.is_symlink():
            raise Refusal("bundle_artifact_missing")
        if source.stat().st_size != row.get("size_bytes") or sha(source) != row.get("sha256"):
            raise Refusal("bundle_artifact_digest_mismatch")
    if RUNTIME_NAME not in seen or f"wheels/{MCP_NAME}" not in seen or "mcp-requirements.lock" not in seen:
        raise Refusal("bundle_artifacts_invalid")
    if sha(bundle / "mcp-requirements.lock") != LOCK_SHA256:
        raise Refusal("pinned_dependency_lock_disagrees")
    return value, sha(path)


def command(*argv: str) -> str:
    result = subprocess.run(argv, text=True, capture_output=True, check=False)
    if result.returncode:
        raise Refusal(f"command_failed:{Path(argv[0]).name}:{result.returncode}")
    return result.stdout.strip()


def atomic_json(path: Path, value: dict) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".pointer-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump(value, output, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def active(root: Path) -> str | None:
    pointer = root / "current.json"
    if pointer.is_symlink():
        raise Refusal("active_pointer_changed")
    if not pointer.exists():
        return None
    try:
        value = json.loads(pointer.read_text())
    except (ValueError, UnicodeError) as error:
        raise Refusal("active_pointer_invalid") from error
    generation = value.get("active")
    if not isinstance(generation, str) or len(generation) != 64 or any(c not in "0123456789abcdef" for c in generation):
        raise Refusal("active_pointer_invalid")
    return generation


def generation(root: Path, digest: str) -> Path:
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise Refusal("generation_invalid")
    return root / "versions" / digest


def inventory(target: Path) -> list[dict]:
    rows = []
    for path in sorted(target.rglob("*")):
        if path.name in ("record.json", "inventory.json") and path.parent == target:
            continue
        relative = path.relative_to(target).as_posix()
        if path.is_symlink():
            rows.append({"path": relative, "link": os.readlink(path)})
        elif path.is_file():
            rows.append({"path": relative, "sha256": sha(path)})
    return rows


def owned_inventory(target: Path) -> list[dict]:
    path = target / "inventory.json"
    if path.is_symlink() or not path.is_file():
        raise Refusal("inventory_missing")
    try:
        rows = json.loads(path.read_text())
    except (ValueError, UnicodeError) as error:
        raise Refusal("inventory_invalid") from error
    if not isinstance(rows, list):
        raise Refusal("inventory_invalid")
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise Refusal("inventory_invalid")
        relative = Path(row["path"])
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise Refusal("inventory_invalid")
        item = target / relative
        if "link" in row:
            if not item.is_symlink() or os.readlink(item) != row["link"]:
                raise Refusal("owned_file_changed")
        elif not item.is_file() or item.is_symlink() or sha(item) != row.get("sha256"):
            raise Refusal("owned_file_changed")
    return rows


def owned(root: Path, digest: str) -> dict:
    target = generation(root, digest)
    record = target / "record.json"
    if target.is_symlink() or record.is_symlink() or not record.is_file():
        raise Refusal("generation_unowned")
    try:
        value = json.loads(record.read_text())
    except (ValueError, UnicodeError) as error:
        raise Refusal("generation_record_invalid") from error
    if value.get("schema_version") != 1 or value.get("manifest_sha256") != digest:
        raise Refusal("generation_record_invalid")
    if sha(target / "inventory.json") != value.get("inventory_sha256"):
        raise Refusal("inventory_changed")
    runtime = target / "runtime" / RUNTIME_NAME
    if not runtime.is_file() or runtime.is_symlink() or sha(runtime) != RUNTIME_SHA256:
        raise Refusal("runtime_changed")
    artifact = target / "artifact" / MCP_NAME
    if not artifact.is_file() or artifact.is_symlink() or sha(artifact) != MCP_SHA256:
        raise Refusal("owner_wheel_changed")
    lock = target / "artifact/mcp-requirements.lock"
    if not lock.is_file() or lock.is_symlink() or sha(lock) != value.get("dependency_lock_sha256"):
        raise Refusal("dependency_lock_changed")
    venv = target / "venv"
    scripts = venv / "bin"
    if venv.is_symlink() or scripts.is_symlink() or venv.resolve().parent != target.resolve() or scripts.resolve().parent != venv.resolve():
        raise Refusal("environment_path_changed")
    python = scripts / "python"
    if python.is_symlink() or not python.is_file() or not os.access(python, os.X_OK):
        raise Refusal("interpreter_missing")
    if venv.resolve() not in python.resolve().parents:
        raise Refusal("interpreter_outside_owned_environment")
    if sha(python) != value.get("runtime_executable_sha256"):
        raise Refusal("interpreter_changed")
    runtime_python = target / "runtime/python/bin/python3.13"
    if runtime_python.is_symlink() or not runtime_python.is_file() or sha(runtime_python) != value.get("runtime_executable_sha256"):
        raise Refusal("runtime_interpreter_changed")
    lockfile = target / "lockfile.json"
    if lockfile.is_symlink() or not lockfile.is_file() or sha(lockfile) != value.get("entrypoint_lock_sha256"):
        raise Refusal("entrypoint_lock_changed")
    try:
        launch_lock = json.loads(lockfile.read_text())
    except (ValueError, UnicodeError) as error:
        raise Refusal("entrypoint_lock_invalid") from error
    if launch_lock.get("layout") != 1 or launch_lock.get("version") != digest or launch_lock.get("venv") != "venv":
        raise Refusal("entrypoint_lock_invalid")
    python_record = launch_lock.get("python")
    artifact_record = launch_lock.get("artifact")
    if not isinstance(python_record, dict) or not isinstance(artifact_record, dict):
        raise Refusal("entrypoint_lock_invalid")
    if (python_record.get("executable") != str(python)
            or python_record.get("version") != "3.13.15"
            or python_record.get("marker") != value.get("mcp_version")
            or launch_lock.get("frozen") != value.get("frozen")):
        raise Refusal("entrypoint_lock_invalid")
    if (artifact_record.get("name") != MCP_NAME
            or artifact_record.get("sha256") != MCP_SHA256
            or artifact_record.get("size") != artifact.stat().st_size):
        raise Refusal("entrypoint_lock_invalid")
    if command(str(python), "-c", "import sys; print(sys.version.split()[0])") != "3.13.15":
        raise Refusal("interpreter_unsupported")
    command(str(python), "-m", "pip", "check")
    if command(str(python), "-m", "pip", "freeze").splitlines() != value.get("frozen"):
        raise Refusal("environment_drifted")
    return value


def install(root: Path, bundle: Path, manifest: dict, digest: str) -> dict:
    safe_root(root)
    previous = active(root)
    if previous is not None:
        owned(root, previous)
    target = generation(root, digest)
    if target.exists() or target.is_symlink():
        owned(root, digest)
    else:
        (root / "versions").mkdir(parents=True, exist_ok=True)
        target.mkdir()
        try:
            runtime_dir = target / "runtime"
            runtime_dir.mkdir()
            shutil.copyfile(bundle / RUNTIME_NAME, runtime_dir / RUNTIME_NAME)
            artifact_dir = target / "artifact"
            artifact_dir.mkdir()
            shutil.copyfile(bundle / "wheels" / MCP_NAME, artifact_dir / MCP_NAME)
            shutil.copyfile(bundle / "mcp-requirements.lock", artifact_dir / "mcp-requirements.lock")
            with tarfile.open(runtime_dir / RUNTIME_NAME, "r:gz") as archive:
                for member in archive.getmembers():
                    parts = Path(member.name).parts
                    if not parts or parts[0] != "python" or ".." in parts or Path(member.name).is_absolute():
                        raise Refusal("runtime_archive_unsafe")
                    if member.issym() or member.islnk():
                        link = Path(member.linkname)
                        if link.is_absolute() or ".." in link.parts:
                            raise Refusal("runtime_archive_unsafe")
                archive.extractall(runtime_dir, filter="data")
            python = runtime_dir / "python/bin/python3.13"
            if command(str(python), "--version") != "Python 3.13.15":
                raise Refusal("interpreter_unsupported")
            venv = target / "venv"
            # The MCP owner's locked launcher resolves the interpreter and requires
            # its executable bytes to stay inside this version's venv.
            command(str(python), "-m", "venv", "--copies", str(venv))
            installed = venv / "bin/python"
            command(str(installed), "-m", "pip", "install", "--no-index", "--find-links", str(bundle / "wheels"), "--require-hashes", "-r", str(bundle / "mcp-requirements.lock"))
            command(str(installed), "-m", "pip", "install", "--no-index", "--no-deps", str(bundle / "wheels" / MCP_NAME))
            command(str(installed), "-m", "pip", "check")
            command(str(installed), "-m", "axiom_mcp.cli", "version", "--json")
            freeze = command(str(installed), "-m", "pip", "freeze")
            atomic_json(target / "lockfile.json", {
                "layout": 1, "version": digest,
                "artifact": {"name": MCP_NAME, "sha256": MCP_SHA256,
                             "size": (artifact_dir / MCP_NAME).stat().st_size},
                "python": {"executable": str(installed), "version": "3.13.15",
                           "marker": manifest["mcp_version"]},
                "venv": "venv", "frozen": freeze.splitlines(), "created_at": time.time(),
            })
            atomic_json(target / "inventory.json", inventory(target))
            record = {"schema_version": 1, "manifest_sha256": digest, "mcp_version": manifest["mcp_version"], "mcp_wheel_sha256": MCP_SHA256, "runtime_sha256": RUNTIME_SHA256, "runtime_executable_sha256": sha(installed), "dependency_lock_sha256": sha(artifact_dir / "mcp-requirements.lock"), "entrypoint_lock_sha256": sha(target / "lockfile.json"), "inventory_sha256": sha(target / "inventory.json"), "frozen": freeze.splitlines(), "python": str(installed)}
            atomic_json(target / "record.json", record)
        except Exception:
            shutil.rmtree(target)
            raise
    atomic_json(root / "current.json", {"schema_version": 1, "layout": 1, "active": digest})
    return {"status": "installed", "active": digest, "previous": previous, "python": str(target / "venv/bin/python"), "mcp_executable": str(target / "venv/bin/axiom-mcp")}


def rollback(root: Path, digest: str) -> dict:
    safe_root(root)
    current = active(root)
    if current is None:
        raise Refusal("active_pointer_missing")
    owned(root, current)
    record = owned(root, digest)
    atomic_json(root / "current.json", {"schema_version": 1, "layout": 1, "active": digest})
    return {"status": "rolled_back", "active": digest, "previous": current, "python": record["python"]}


def uninstall(root: Path) -> dict:
    safe_root(root)
    versions = root / "versions"
    if versions.is_symlink():
        raise Refusal("versions_path_changed")
    targets = sorted(path for path in versions.iterdir() if path.is_dir()) if versions.exists() else []
    verified: list[tuple[Path, list[dict]]] = []
    for target in targets:
        if target.is_symlink():
            raise Refusal("version_path_changed")
        owned(root, target.name)
        verified.append((target, owned_inventory(target)))
    current = active(root)
    if current is not None and current not in {target.name for target, _ in verified}:
        raise Refusal("active_generation_missing")
    if current is not None:
        (root / "current.json").unlink()
    preserved = 0
    for target, rows in verified:
        for row in rows:
            (target / row["path"]).unlink()
        (target / "inventory.json").unlink()
        (target / "record.json").unlink()
        for directory in sorted((path for path in target.rglob("*") if path.is_dir() and not path.is_symlink()), key=lambda path: len(path.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        try:
            target.rmdir()
        except OSError:
            preserved += 1
    try:
        versions.rmdir()
    except OSError:
        pass
    return {"status": "uninstalled", "removed_generations": len(verified), "preserved_generations_with_unowned_files": preserved}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "rollback", "status", "uninstall"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--to")
    args = parser.parse_args()
    if (platform.system(), platform.machine()) != ("Darwin", "x86_64") or sys.version_info[:2] != (3, 13):
        raise Refusal("unsupported_runtime")
    root = safe_root(args.root)
    if args.action == "install":
        if args.bundle is None:
            raise Refusal("bundle_required")
        manifest, digest = bundle_manifest(args.bundle)
        answer = install(root, args.bundle, manifest, digest)
    elif args.action == "rollback":
        if args.to is None:
            raise Refusal("rollback_target_required")
        answer = rollback(root, args.to)
    elif args.action == "uninstall":
        answer = uninstall(root)
    else:
        digest = active(root)
        answer = {"status": "absent", "active": None} if digest is None else {"status": "active", "active": digest, "python": owned(root, digest)["python"]}
    print(json.dumps(answer, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (Refusal, OSError, ValueError, tarfile.TarError) as error:
        print(json.dumps({"status": "refused", "reason": str(error)}))
        sys.exit(9)
