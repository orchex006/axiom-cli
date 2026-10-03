#!/usr/bin/env python3
"""Build an unsigned Windows B kit from exact A and native core bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[2]
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
OLD_CORE = "axiom-0.1.1-windows-x64.zip"
NEW_CORE = "axiom-0.1.2-windows-x64.zip"
K309_CORE_MANIFEST_SHA = (
    "b33999d07c1a71d3ce00c93620870d08948eec6f0e010f7891d6c630717af7df"
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read(path: Path, expected: str) -> bytes:
    if not HEX64.fullmatch(expected) or path.is_symlink() or not path.is_file():
        raise ValueError("missing or unsafe candidate input: " + path.name)
    value = path.read_bytes()
    if sha(value) != expected:
        raise ValueError("candidate input differs: " + path.name)
    return value


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def safe_name(name: str) -> bool:
    return (
        bool(name)
        and "\\" not in name
        and ":" not in name
        and all(part not in ("", ".", "..") for part in name.split("/"))
    )


def pe_x64(data: bytes) -> bool:
    if len(data) < 0x40 or data[:2] != b"MZ":
        return False
    offset = int.from_bytes(data[0x3C:0x40], "little")
    return (
        offset >= 0x40
        and offset + 26 <= len(data)
        and data[offset : offset + 4] == b"PE\0\0"
        and data[offset + 4 : offset + 6] == bytes.fromhex("6486")
        and data[offset + 24 : offset + 26] == bytes.fromhex("0b02")
    )


def archive(path: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as output:
        for name, body in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 0
            output.writestr(info, body)


def build(args: argparse.Namespace) -> dict:
    task_id = args.task_id
    if args.out.exists():
        raise ValueError("kit output already exists")
    if (
        args.b_core_dir.is_symlink()
        or args.b_cli.is_symlink()
        or not args.b_cli.is_file()
    ):
        raise ValueError("B core directory or CLI input is missing or linked")
    if not HEX40.fullmatch(args.cli_revision):
        raise ValueError("CLI source revision must be immutable")
    source = read(args.a_archive, args.a_sha)
    with zipfile.ZipFile(args.a_archive) as zipped:
        rows = zipped.infolist()
        if (
            len(rows) != 60
            or len({r.filename for r in rows}) != 60
            or any(r.is_dir() or not safe_name(r.filename) for r in rows)
        ):
            raise ValueError("K-305 A archive membership differs")
        files = {r.filename: zipped.read(r) for r in rows}
    old_set = json.loads(files["release-set.json"])
    old_channel = json.loads(files["channel.json"])
    if (
        old_set.get("release_version") != "0.1.1"
        or old_set.get("platform") != "windows-x64"
        or old_set.get("arch") != "x86_64"
        or old_channel.get("published") is not False
    ):
        raise ValueError("A is not the K-305 Windows candidate")
    for row in old_set["artifacts"]:
        body = files.get(row["name"])
        if body is None or sha(body) != row["sha256"] or len(body) != row["size_bytes"]:
            raise ValueError("A release set artifact differs: " + row["name"])
    core_bytes = read(
        args.b_core_dir / "candidate-manifest.json", args.b_core_manifest_sha
    )
    if task_id == "K-010" and sha(core_bytes) != K309_CORE_MANIFEST_SHA:
        raise ValueError("K-010 requires the reviewed K-309 core manifest")
    core = json.loads(core_bytes)
    if (
        core.get("platform") != "windows-x64"
        or core.get("version") != "0.1.2"
        or core.get("signing") != "unsigned"
        or core.get("publication") != "not_published"
        or not HEX40.fullmatch(core.get("source_revision", ""))
    ):
        raise ValueError("B core identity differs")
    core_archive = read(args.b_core_dir / NEW_CORE, core["archive"]["sha256"])
    binaries = {row["name"]: row for row in core["binaries"]}
    if set(binaries) != {"axiom.exe", "axiom-graphd.exe"}:
        raise ValueError("B core executable set differs")
    with zipfile.ZipFile(args.b_core_dir / NEW_CORE) as zipped:
        for name, row in binaries.items():
            body = zipped.read(name)
            if not pe_x64(body) or sha(body) != row["sha256"]:
                raise ValueError("B core executable differs: " + name)
            files[name] = body
    cli = args.b_cli.read_bytes()
    if not pe_x64(cli):
        raise ValueError("B CLI is not native Windows x64")
    reported = subprocess.run(
        [str(args.b_cli), "version", "--json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    if (
        reported.returncode
        or json.loads(reported.stdout)["details"]["cli"]["version"] != "0.1.2"
    ):
        raise ValueError("B CLI version report differs")
    files["axiom-cli.exe"] = cli
    del files[OLD_CORE]
    files[NEW_CORE] = core_archive
    files["candidate-manifest.json"] = core_bytes

    release_set = old_set
    release_set["release_version"] = "0.1.2"
    release_set["assembled_by"] = f"packaging/windows/Build-UpdateKit.py [{task_id}]"
    release_set["assembled_at"] = (
        "2026-10-01T00:00:00Z" if task_id == "K-306" else "2026-10-02T00:00:00Z"
    )
    for row in release_set["artifacts"]:
        if row["name"] == OLD_CORE:
            row["name"] = row["file_name"] = NEW_CORE
            row["install_relative_path"] = NEW_CORE
        body = files[row["name"]]
        row["sha256"] = sha(body)
        row["size_bytes"] = len(body)
        if row["component"] in (
            "axiom-cli",
            "axiom",
            "axiom-graphd",
            "core-candidate",
            "core-manifest",
        ):
            row["version"] = "0.1.2"
    for row in release_set.get("declared_components", []):
        if row.get("component") in ("axiom-graphd", "axiom"):
            row["installed_version"] = "0.1.2"
            row["version_source"] = (
                f"axiom-graphd/evidence/{'K-308' if task_id == 'K-306' else 'K-309/final-4f'}/candidate-manifest.json"
            )
    if task_id == "K-306":
        release_set["service_reason"] = (
            "The graph daemon service lifecycle is owned by axiom-graphd; this unsigned "
            f"Windows x64 core 0.1.2 candidate at revision {core['source_revision']} "
            "declares no managed service registration. K-306 tests a Limited per-user "
            "Scheduled Task separately."
        )
    else:
        release_set["service_reason"] = (
            "The graph daemon service lifecycle is owned by axiom-graphd. "
            f"K-309 core revision {core['source_revision']} provides the public per-user "
            "Windows service verbs; K-010 verifies them after distribution install."
        )
    files["release-set.json"] = json_bytes(release_set)
    channel = old_channel
    channel["updated_at"] = "2026-10-01T00:00:00Z"
    graphd = next(
        row for row in channel["components"] if row["component"] == "axiom-graphd"
    )
    graphd["version"] = "0.1.2"
    graphd["revision"] = core["source_revision"]
    graphd["artifacts"][0]["sha256"] = sha(files["axiom-graphd.exe"])
    graphd["artifacts"][0]["size_bytes"] = len(files["axiom-graphd.exe"])
    files["channel.json"] = json_bytes(channel)
    lock = json.loads(files["candidate-lock.json"])
    lock.update(
        task_id=task_id,
        release_set_sha256=sha(files["release-set.json"]),
        core_archive_sha256=sha(core_archive),
        core_revision=core["source_revision"],
        cli_revision=args.cli_revision,
        a_archive_sha256=sha(source),
    )
    files["candidate-lock.json"] = json_bytes(lock)
    if len(files) != 60:
        raise ValueError("B release membership differs")
    output = args.out
    release = output / "release"
    release.mkdir(parents=True)
    for name, body in files.items():
        path = release.joinpath(*name.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    file_manifest = {
        "task_id": task_id,
        "lane": "windows-x64",
        "candidate": True,
        "a_archive_sha256": sha(source),
        "core_b_manifest_sha256": sha(core_bytes),
        "cli_b_revision": args.cli_revision,
        "files": [
            {"path": name, "sha256": sha(body), "size_bytes": len(body)}
            for name, body in sorted(files.items())
        ],
    }
    (output / "candidate-files.json").write_bytes(json_bytes(file_manifest))
    runtime = ROOT / "packaging/windows/runtime-input.json"
    for name, path in {
        "runtime-input.json": runtime,
        "Update-Distribution.py": ROOT / "packaging/windows/Update-Distribution.py",
        "Install-AxiomCli.ps1": ROOT / "installers/windows/Install-AxiomCli.ps1",
        "AxiomCli.Windows.Common.ps1": ROOT
        / "installers/windows/AxiomCli.Windows.Common.ps1",
    }.items():
        shutil.copyfile(path, output / name)
    kit = {
        "task_id": task_id,
        "lane": "windows-x64",
        "published": False,
        "certified": False,
        "release_set_sha256": sha(files["release-set.json"]),
        "files": {
            name: sha((output / name).read_bytes())
            for name in (
                "runtime-input.json",
                "Update-Distribution.py",
                "Install-AxiomCli.ps1",
                "AxiomCli.Windows.Common.ps1",
                "candidate-files.json",
            )
        },
    }
    (output / "kit-manifest.json").write_bytes(json_bytes(kit))
    archive(output / "axiom-0.1.2-windows-x64-update-kit.zip", files)
    return {
        "task_id": task_id,
        "source_revision": args.cli_revision,
        "core_revision": core["source_revision"],
        "a_sha256": sha(source),
        "b_archive_sha256": sha(
            (output / "axiom-0.1.2-windows-x64-update-kit.zip").read_bytes()
        ),
        "b_release_set_sha256": sha(files["release-set.json"]),
        "kit_manifest_sha256": sha((output / "kit-manifest.json").read_bytes()),
        "candidate": True,
        "certified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a-archive", type=Path, required=True)
    parser.add_argument("--a-sha", required=True)
    parser.add_argument("--b-core-dir", type=Path, required=True)
    parser.add_argument("--b-core-manifest-sha", required=True)
    parser.add_argument("--b-cli", type=Path, required=True)
    parser.add_argument("--cli-revision", required=True)
    parser.add_argument("--task-id", choices=("K-306", "K-010"), default="K-306")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(build(args), sort_keys=True))
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        zipfile.BadZipFile,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ) as error:
        print(json.dumps({"status": "refused", "reason": str(error)}, sort_keys=True))
        return 9


if __name__ == "__main__":
    sys.exit(main())
