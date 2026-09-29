#!/usr/bin/env python3
"""Add an unpublished local engine channel to an Intel Mac entrypoint set.

This is a candidate packaging bridge. It consumes an already verified core
entrypoint set, a pinned MCP wheel, and an engine-format skills bundle. It does
not provision Python, install anything, sign, notarize or publish a release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
REVISION = re.compile(r"[0-9a-f]{40}\Z")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?\Z")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def require_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"required regular file is absent: {path}")


def require_sha(value: str, label: str) -> None:
    if not SHA256.fullmatch(value):
        raise ValueError(f"{label} must be lowercase SHA-256")


def require_revision(value: str, label: str) -> None:
    if not REVISION.fullmatch(value):
        raise ValueError(f"{label} must be an immutable 40-hex revision")


def core(release: Path) -> dict:
    release_set = release / "release-set.json"
    require_file(release_set)
    data = json.loads(release_set.read_text(encoding="utf-8"))
    if (
        data.get("platform"),
        data.get("arch"),
        data.get("signing"),
        data.get("notarization"),
    ) != ("macos-x64", "x86_64", "unsigned", "not_notarized"):
        raise ValueError(
            "the input is not an honest Intel Mac candidate entrypoint set"
        )
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list) or [r.get("name") for r in artifacts] != [
        "axiom-cli",
        "axiom",
        "axiom-graphd",
    ]:
        raise ValueError("the candidate must carry the CLI and both core executables")
    for row in artifacts:
        name = row["name"]
        path = release / name
        require_file(path)
        require_sha(str(row.get("sha256", "")), name)
        if digest(path) != row["sha256"] or path.stat().st_size != row.get(
            "size_bytes"
        ):
            raise ValueError(f"candidate artifact has changed: {name}")
        if not os.access(path, os.X_OK):
            raise ValueError(f"candidate artifact is not executable: {name}")
    if (
        artifacts[1]["version"] != artifacts[2]["version"]
        or artifacts[1]["revision"] != artifacts[2]["revision"]
    ):
        raise ValueError("core executable versions or revisions disagree")
    require_revision(artifacts[2]["revision"], "core revision")
    if not VERSION.fullmatch(artifacts[2]["version"]):
        raise ValueError("core version is not SemVer")
    return data


def mcp_wheel(path: Path, expected_sha: str) -> str:
    require_file(path)
    require_sha(expected_sha, "MCP wheel digest")
    if digest(path) != expected_sha:
        raise ValueError("MCP wheel digest mismatch")
    if not path.name.startswith("axiom_mcp-") or not path.name.endswith(".whl"):
        raise ValueError("MCP wheel filename is not an axiom-mcp wheel")
    with zipfile.ZipFile(path) as wheel:
        names = [
            name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(names) != 1:
            raise ValueError("MCP wheel has no unique metadata")
        metadata = wheel.read(names[0]).decode("utf-8")
    fields = dict(line.split(": ", 1) for line in metadata.splitlines() if ": " in line)
    version = fields.get("Version", "")
    if fields.get("Name", "").lower() != "axiom-mcp" or not VERSION.fullmatch(version):
        raise ValueError("MCP wheel owner name or SemVer is invalid")
    if f"axiom_mcp-{version}-" not in path.name:
        raise ValueError("MCP wheel filename and metadata version disagree")
    return version


def skills_bundle(
    source: Path, revision: str | None = None, manifest_sha256: str | None = None
) -> dict:
    owner_source = (source / "skills-manifest.json").is_file()
    manifest = source / ("skills-manifest.json" if owner_source else "bundle.json")
    require_file(manifest)
    if owner_source:
        if manifest_sha256 is None or not SHA256.fullmatch(manifest_sha256):
            raise ValueError("owner skills source needs a pinned manifest SHA-256")
        if digest(manifest) != manifest_sha256:
            raise ValueError("owner skills manifest differs from its K-101 pin")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if owner_source:
        if data.get("manifest_version") != 1 or data.get("component") != "axiom-skills":
            raise ValueError("owner skills source schema or component is incompatible")
        if (
            data.get("spec_revision")
            != json.loads((ROOT / "spec.lock.json").read_text())["spec_revision"]
        ):
            raise ValueError("owner skills spec revision differs from the CLI pin")
        if revision is None:
            raise ValueError("owner skills source needs an immutable revision")
        require_revision(revision, "skills revision")
        version, entries = data.get("component_version"), data.get("files")
    else:
        if data.get("schema_version") != 1 or data.get("component") != "skills":
            raise ValueError("skills bundle schema or component is incompatible")
        version, entries = data.get("version"), data.get("entries")
        revision = data.get("revision")
    if not VERSION.fullmatch(str(version or "")):
        raise ValueError("skills version is not SemVer")
    require_revision(str(revision or ""), "skills revision")
    require_revision(str(data.get("spec_revision", "")), "skills spec revision")
    if not isinstance(entries, list) or not entries:
        raise ValueError("skills bundle has no entries")
    declared = set()
    for row in entries:
        name = row.get("path")
        if (
            not isinstance(name, str)
            or not name
            or name.startswith("/")
            or ".." in Path(name).parts
            or name in declared
        ):
            raise ValueError("skills bundle path is unsafe or duplicated")
        declared.add(name)
        path = source / name if owner_source else source / "payload" / name
        require_file(path)
        require_sha(str(row.get("sha256", "")), "skills payload digest")
        if digest(path) != row["sha256"] or path.stat().st_size != row.get(
            "bytes" if owner_source else "size_bytes"
        ):
            raise ValueError(f"skills payload has changed: {name}")
    observed = set()
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError("skills bundle contains a symlink")
        if path.is_file() and path != manifest:
            observed.add(
                path.relative_to(
                    source if owner_source else source / "payload"
                ).as_posix()
            )
    if observed != declared:
        raise ValueError("skills bundle has undeclared or missing payload files")
    return {
        "version": version,
        "revision": revision,
        "spec_revision": data["spec_revision"],
        "manifest_sha256": digest(manifest),
        "format": "owner-source" if owner_source else "engine",
    }


def component(
    name: str,
    version: str,
    revision: str,
    source: str,
    artifact: Path | None,
    restart: bool,
) -> dict:
    rows = []
    if artifact is not None:
        rows = [
            {
                "platform": "macos-x64",
                "class": "per-user-installer",
                "url": f"https://candidate.invalid/{artifact.name}",
                "sha256": digest(artifact),
                "size_bytes": artifact.stat().st_size,
            }
        ]
    return {
        "component": name,
        "status": "declared",
        "version": version,
        "revision": revision,
        "declared_source": source,
        "needs_restart": restart,
        "artifacts": rows,
    }


def build(
    release: Path,
    wheel: Path,
    wheel_sha: str,
    mcp_revision: str,
    skills: Path,
    skills_revision: str | None = None,
    skills_manifest_sha256: str | None = None,
) -> dict:
    release = release.resolve()
    if not release.is_dir():
        raise ValueError("release set directory is absent")
    require_revision(mcp_revision, "MCP revision")
    core_set = core(release)
    mcp_version = mcp_wheel(wheel, wheel_sha)
    skill_info = skills_bundle(skills, skills_revision, skills_manifest_sha256)
    skills_target = (
        "skills-source" if skill_info["format"] == "owner-source" else "skills"
    )
    outputs = [release / "channel.json", release / wheel.name]
    if skills_target == "skills-source":
        outputs += [release / entry.name for entry in skills.iterdir()]
    else:
        outputs.append(release / "skills")
    for target in outputs:
        if target.exists() or target.is_symlink():
            raise ValueError(f"candidate output already exists: {target.name}")
    trusted = json.loads((ROOT / "channels/stable.json").read_text(encoding="utf-8"))[
        "trust"
    ]
    if not SHA256.fullmatch(trusted["trust_root"]):
        raise ValueError("development trust root is invalid")
    with tempfile.TemporaryDirectory(
        prefix=".engine-candidate-", dir=release
    ) as stage_name:
        stage = Path(stage_name)
        staged_wheel = stage / wheel.name
        shutil.copyfile(wheel, staged_wheel)
        if digest(staged_wheel) != wheel_sha:
            raise ValueError("staged MCP wheel digest mismatch")
        staged_skills = stage / skills_target
        shutil.copytree(skills, staged_skills)
        skills_bundle(staged_skills, skills_revision, skills_manifest_sha256)
        channel = {
            "manifest_version": 1,
            "channel": "stable",
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "published": False,
            "note": "Unsigned local Intel Mac candidate; no release or trust certification.",
            "trust": {
                "metadata_version": 1,
                "metadata_expiry": trusted["metadata_expiry"],
                "trust_root": trusted["trust_root"],
                "signature_artifact": None,
            },
            "components": [
                component(
                    "axiom-graphd",
                    core_set["artifacts"][2]["version"],
                    core_set["artifacts"][2]["revision"],
                    "Mac release-set.json",
                    release / "axiom-graphd",
                    True,
                ),
                component(
                    "axiom-mcp",
                    mcp_version,
                    mcp_revision,
                    "pinned owner wheel metadata and digest",
                    staged_wheel,
                    True,
                ),
                component(
                    "skills",
                    skill_info["version"],
                    skill_info["revision"],
                    skill_info["format"] + " skills manifest",
                    None,
                    False,
                ),
            ],
        }
        channel_file = stage / "channel.json"
        channel_file.write_text(
            json.dumps(channel, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        installed = []
        try:
            os.replace(staged_wheel, release / wheel.name)
            installed.append(release / wheel.name)
            if skills_target == "skills-source":
                # The CLI converts this verified owner source when assembling the engine bundle.
                shutil.copyfile(
                    staged_skills / "skills-manifest.json",
                    stage / "skills-manifest.json",
                )
                os.replace(
                    stage / "skills-manifest.json", release / "skills-manifest.json"
                )
                installed.append(release / "skills-manifest.json")
                for entry in staged_skills.iterdir():
                    if entry.name == "skills-manifest.json":
                        continue
                    target = release / entry.name
                    if target.exists() or target.is_symlink():
                        raise ValueError(
                            f"candidate output already exists: {entry.name}"
                        )
                    os.replace(entry, target)
                    installed.append(target)
            else:
                os.replace(staged_skills, release / "skills")
                installed.append(release / "skills")
            os.replace(channel_file, release / "channel.json")
        except Exception:
            for path in reversed(installed):
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
            raise
    return {
        "status": "candidate",
        "published": False,
        "channel_sha256": digest(release / "channel.json"),
        "core_revision": core_set["artifacts"][2]["revision"],
        "mcp_revision": mcp_revision,
        "mcp_wheel_sha256": wheel_sha,
        "skills_revision": skill_info["revision"],
        "skills_manifest_sha256": skill_info["manifest_sha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-set", required=True, type=Path)
    parser.add_argument("--mcp-wheel", required=True, type=Path)
    parser.add_argument("--mcp-sha256", required=True)
    parser.add_argument("--mcp-revision", required=True)
    parser.add_argument("--skills-bundle", required=True, type=Path)
    parser.add_argument("--skills-revision")
    parser.add_argument("--skills-manifest-sha256")
    args = parser.parse_args()
    try:
        result = build(
            args.release_set,
            args.mcp_wheel,
            args.mcp_sha256,
            args.mcp_revision,
            args.skills_bundle,
            args.skills_revision,
            args.skills_manifest_sha256,
        )
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        parser.exit(2, f"engine candidate refused: {error}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
