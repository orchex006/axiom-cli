//! J-007 acceptance suite for the `update` channel.
//!
//! Every case drives the real `axiom-cli` binary as a child process against a local, on-disk
//! fixture install root and a local artifact cache. Nothing here reaches a network, a remote, a
//! tag or a branch tip: the fixture channel manifest is written by this file, the artifacts are
//! bytes this file creates, and the whole fixture is removed when the test ends. The
//! `channels/stable.json` that ships with the repository is read-only seed data and is never
//! published by this suite.
//!
//! The suite covers the AC2 legs: a tampered artifact digest, an unreachable artifact while
//! offline, an interrupted apply that is recovered, a rollback after a failed health check, an
//! idempotent re-run, and the negative boundaries that keep a version from being resolved from
//! anything but the recorded manifest.
//!
//! The package has no third-party dependencies, so the digest the fixture records for its own
//! artifact bytes is computed by a small self-contained SHA-256 in this file, pinned against the
//! published FIPS vectors.

use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicUsize, Ordering};

const SUCCESS: i32 = 0;
const VALIDATION: i32 = 2;
const NOT_FOUND: i32 = 3;
const NOT_READY: i32 = 4;
const CONFLICT: i32 = 6;
const INCOMPATIBLE: i32 = 9;

const SEED_GENERATION: &str = "g-20260920t000000z-00000001";
const SEED_VERSION: &str = "0.0.0-seed";
const TARGET_VERSION: &str = "0.0.1-dev";
const TRUST_ROOT: &str = "23e4845c8e76c7cf8642b2c47f759d401345424309aec6b3bf4ad8413b40ee7a";
const METADATA_EXPIRY: &str = "2027-09-20T00:00:00Z";
/// A detached signature artifact digest the fixture channel carries, so the mirrored
/// plan contract sees a signed channel. Unsigned mode deliberately omits it.
const SIGNATURE_ARTIFACT: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
const SEED_PLAN_DIGEST: &str = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
const ZERO_DIGEST: &str = "0000000000000000000000000000000000000000000000000000000000000000";
const DECLARED: [&str; 4] = ["axiom-graphd", "axiom", "axiom-cli", "skills"];
const ALL_COMPONENTS: [&str; 5] = ["axiom-graphd", "axiom-mcp", "axiom", "axiom-cli", "skills"];

/// A self-contained SHA-256.
///
/// The integration test cannot reach the binary's private `update::sha256` module, and the
/// package deliberately declares no dependencies, so the digest the fixture records is computed
/// here. It is verified against the published vectors before it is used to build a fixture.
mod sha256 {
    #[allow(clippy::needless_range_loop)]
    pub fn hex(input: &[u8]) -> String {
        const K: [u32; 64] = [
            0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
            0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
            0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
            0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
            0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
            0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
            0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
            0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
            0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
            0xc67178f2,
        ];
        let mut state: [u32; 8] = [
            0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
            0x5be0cd19,
        ];
        let mut message = input.to_vec();
        let bit_len = (input.len() as u64).wrapping_mul(8);
        message.push(0x80);
        while message.len() % 64 != 56 {
            message.push(0);
        }
        message.extend_from_slice(&bit_len.to_be_bytes());
        for chunk in message.chunks(64) {
            let mut w = [0u32; 64];
            for i in 0..16 {
                w[i] = u32::from_be_bytes([
                    chunk[i * 4],
                    chunk[i * 4 + 1],
                    chunk[i * 4 + 2],
                    chunk[i * 4 + 3],
                ]);
            }
            for i in 16..64 {
                let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
                let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
                w[i] = w[i - 16]
                    .wrapping_add(s0)
                    .wrapping_add(w[i - 7])
                    .wrapping_add(s1);
            }
            let mut a = state[0];
            let mut b = state[1];
            let mut c = state[2];
            let mut d = state[3];
            let mut e = state[4];
            let mut f = state[5];
            let mut g = state[6];
            let mut h = state[7];
            for i in 0..64 {
                let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
                let ch = (e & f) ^ ((!e) & g);
                let t1 = h
                    .wrapping_add(s1)
                    .wrapping_add(ch)
                    .wrapping_add(K[i])
                    .wrapping_add(w[i]);
                let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
                let maj = (a & b) ^ (a & c) ^ (b & c);
                let t2 = s0.wrapping_add(maj);
                h = g;
                g = f;
                f = e;
                e = d.wrapping_add(t1);
                d = c;
                c = b;
                b = a;
                a = t1.wrapping_add(t2);
            }
            state[0] = state[0].wrapping_add(a);
            state[1] = state[1].wrapping_add(b);
            state[2] = state[2].wrapping_add(c);
            state[3] = state[3].wrapping_add(d);
            state[4] = state[4].wrapping_add(e);
            state[5] = state[5].wrapping_add(f);
            state[6] = state[6].wrapping_add(g);
            state[7] = state[7].wrapping_add(h);
        }
        state.iter().map(|value| format!("{value:08x}")).collect()
    }
}
/// The canonical host id of the running test process.
fn host() -> &'static str {
    if cfg!(all(target_os = "windows", target_arch = "x86_64")) {
        "windows-x64"
    } else if cfg!(all(target_os = "linux", target_arch = "x86_64")) {
        "linux-x64"
    } else if cfg!(all(target_os = "macos", target_arch = "aarch64")) {
        "macos-arm64"
    } else {
        "macos-x64"
    }
}

/// How the fixture's channel manifest is deliberately wrong, when it must be.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Mode {
    /// A well-formed, unsigned-nowhere-but-trusted-locally manifest whose probe passes.
    Published,
    /// The same manifest, but the `axiom-cli` post-swap probe exits non-zero.
    FailingProbe,
    /// `trust.trust_root` is null: the channel is unsigned.
    Unsigned,
    /// `axiom-cli`'s version is the forbidden pin `latest`.
    ForbiddenPin,
    /// The trust metadata expired in 2020.
    Expired,
}

/// One local, on-disk fixture: an install root, an artifact cache, a channel manifest and a plan
/// path. Dropped, and therefore removed, at the end of the case.
struct Fixture {
    dir: PathBuf,
    root: PathBuf,
    cache: PathBuf,
    manifest_path: PathBuf,
    plan_path: PathBuf,
}

static COUNTER: AtomicUsize = AtomicUsize::new(0);

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.dir);
    }
}

/// The bytes the channel manifest publishes for `component` at the target version.
fn payload(component: &str) -> Vec<u8> {
    format!("j-007 local fixture payload for {component} at {TARGET_VERSION}\n")
        .repeat(3)
        .into_bytes()
}

/// The bytes one seed generation already carries for `component`.
fn seed_payload(component: &str) -> Vec<u8> {
    format!("j-007 seed payload for {component} at {SEED_VERSION}\n").into_bytes()
}

/// The artifact file name of `component` as the channel manifest's URL names it.
fn cache_name(component: &str) -> String {
    let version = if component == "skills" {
        "0.1.0-draft.1"
    } else {
        TARGET_VERSION
    };
    format!("{component}-{version}.zip")
}

/// A stable 40-hex revision per component, so a revision is never guessed at run time.
fn revision(component: &str) -> String {
    let digit = match component {
        "axiom-graphd" => '1',
        "axiom" => '2',
        "axiom-cli" => '3',
        _ => '4',
    };
    digit.to_string().repeat(40)
}

/// A stable 40-hex seed revision per component, distinct from the target revision.
fn seed_revision(component: &str) -> String {
    let digit = match component {
        "axiom-graphd" => 'a',
        "axiom" => 'b',
        "axiom-cli" => 'c',
        _ => 'd',
    };
    digit.to_string().repeat(40)
}
/// Where the owner declares `component`'s version, recorded so the manifest names a real source.
fn declared_source(component: &str) -> String {
    match component {
        "axiom-graphd" => {
            "axiom-graphd/Cargo.toml = 0.0.0-dev (executed, not released)".to_string()
        }
        "axiom" => "axiom-graphd/Cargo.toml = 0.0.0-dev (shared core release)".to_string(),
        "axiom-cli" => "axiom-cli/VERSION = 0.0.1-dev (local fixture)".to_string(),
        _ => "axiom-skills/VERSION = 0.1.0-draft.1 (local fixture)".to_string(),
    }
}

/// One component entry of the fixture channel manifest.
fn component_json(component: &str, mode: Mode) -> String {
    if component == "axiom-mcp" {
        return concat!(
            "{\"component\":\"axiom-mcp\",\"status\":\"undeclared\",\"version\":null,",
            "\"revision\":null,\"declared_source\":",
            "\"axiom-mcp/pyproject.toml = 0.0.0.dev0 (PEP 440, not SemVer)\",",
            "\"needs_restart\":true,\"artifacts\":[]}"
        )
        .to_string();
    }
    let declared_version = if component == "skills" {
        "0.1.0-draft.1"
    } else {
        TARGET_VERSION
    };
    let version = if mode == Mode::ForbiddenPin && component == "axiom-cli" {
        "latest"
    } else {
        declared_version
    };
    let bytes = payload(component);
    let digest = sha256::hex(&bytes);
    let size = bytes.len();
    let url = format!("https://fixtures.invalid/j007/{}", cache_name(component));
    let health = match component {
        "axiom-cli" => {
            let program = env!("CARGO_BIN_EXE_axiom-cli").replace('\\', "\\\\");
            let args = if mode == Mode::FailingProbe {
                "[\"frobnicate\"]"
            } else {
                "[\"--help\"]"
            };
            format!(",\"health\":{{\"program\":\"{program}\",\"args\":{args},\"expect_exit\":0}}")
        }
        _ => String::new(),
    };
    format!(
        "{{\"component\":\"{component}\",\"status\":\"declared\",\"version\":\"{version}\",\
         \"revision\":\"{revision}\",\"declared_source\":\"{source}\",\"needs_restart\":true{health},\
         \"artifacts\":[{{\"platform\":\"{host}\",\"class\":\"per-user-installer\",\
         \"url\":\"{url}\",\"sha256\":\"{digest}\",\"size_bytes\":{size}}}]}}",
        revision = revision(component),
        source = declared_source(component),
        host = host(),
    )
}

/// The whole fixture channel manifest, as text.
fn manifest_text(mode: Mode) -> String {
    let components: Vec<String> = ALL_COMPONENTS
        .iter()
        .map(|component| component_json(component, mode))
        .collect();
    let trust_root = match mode {
        Mode::Unsigned => "null".to_string(),
        _ => format!("\"{TRUST_ROOT}\""),
    };
    let signature = match mode {
        Mode::Unsigned => "null".to_string(),
        _ => format!("\"{SIGNATURE_ARTIFACT}\""),
    };
    let expiry = match mode {
        Mode::Expired => "2020-01-01T00:00:00Z",
        _ => METADATA_EXPIRY,
    };
    format!(
        "{{\"manifest_version\":1,\"channel\":\"stable\",\
         \"updated_at\":\"2026-09-20T00:00:00Z\",\"published\":false,\
         \"note\":\"J-007 local acceptance fixture; never published\",\
         \"trust\":{{\"metadata_version\":1,\"metadata_expiry\":\"{expiry}\",\
         \"trust_root\":{trust_root},\"signature_artifact\":{signature}}},\
         \"components\":[{}]}}",
        components.join(",")
    )
}
impl Fixture {
    /// Build a fixture whose channel manifest is well formed unless `mode` says otherwise.
    fn new(name: &str, mode: Mode) -> Fixture {
        let ordinal = COUNTER.fetch_add(1, Ordering::SeqCst);
        let dir = std::env::temp_dir().join(format!(
            "axiom-cli-j007-{}-{ordinal}-{name}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&dir);
        let root = dir.join("root");
        let cache = dir.join("cache");
        std::fs::create_dir_all(&root).expect("the fixture install root must be creatable");
        std::fs::create_dir_all(&cache).expect("the fixture artifact cache must be creatable");
        let manifest_path = dir.join("manifest.json");
        let plan_path = dir.join("plan.json");
        let fixture = Fixture {
            dir,
            root,
            cache,
            manifest_path,
            plan_path,
        };
        std::fs::write(&fixture.manifest_path, manifest_text(mode).as_bytes())
            .expect("the fixture channel manifest must be writable");
        fixture.seed();
        fixture.cache_artifacts();
        fixture
    }

    /// The install root as the CLI records it: absolute, forward slashes, no trailing slash.
    fn root_text(&self) -> String {
        self.root.to_string_lossy().replace('\\', "/")
    }

    /// Write a seed installed release: `installed.json`, the recorded manifest and one generation.
    fn seed(&self) {
        let manifest = std::fs::read(&self.manifest_path).expect("the fixture manifest must exist");
        let manifest_digest = sha256::hex(&manifest);
        std::fs::write(self.root.join("recorded-manifest.json"), &manifest)
            .expect("the recorded manifest must be writable");
        std::fs::write(
            self.root.join("installed.json"),
            self.installed_text(&manifest_digest),
        )
        .expect("the installed record must be writable");
        let generation_dir = self.root.join("generations").join(SEED_GENERATION);
        let mut entries: Vec<String> = Vec::new();
        for component in DECLARED {
            let bytes = seed_payload(component);
            let digest = sha256::hex(&bytes);
            let name = format!("{component}-{SEED_VERSION}.zip");
            let relative = format!("payload/{component}/{name}");
            let path = generation_dir.join("payload").join(component).join(&name);
            std::fs::create_dir_all(path.parent().expect("the payload path has a parent"))
                .expect("the seed payload directory must be creatable");
            std::fs::write(&path, &bytes).expect("the seed payload must be writable");
            entries.push(format!(
                "{{\"component\":\"{component}\",\"action\":\"install\",\
                 \"version\":\"{SEED_VERSION}\",\"revision\":\"{revision}\",\
                 \"artifact_sha256\":\"{digest}\",\"payload\":\"{relative}\",\
                 \"needs_restart\":false,\"probe\":null}}",
                revision = seed_revision(component),
            ));
        }
        let record = format!(
            "{{\"schema_version\":1,\"generation_id\":\"{SEED_GENERATION}\",\
             \"transaction_id\":\"t-20260920t000000z-00000001\",\
             \"plan_id\":\"update-stable-axiom-cli\",\"plan_digest\":\"{SEED_PLAN_DIGEST}\",\
             \"channel\":\"stable\",\"host\":\"{host}\",\"install_root\":\"{root_text}\",\
             \"created_at\":\"2026-09-20T00:00:00Z\",\"components\":[{}]}}",
            entries.join(","),
            host = host(),
            root_text = self.root_text(),
        );
        std::fs::write(generation_dir.join("generation.json"), record.as_bytes())
            .expect("the seed generation record must be writable");
    }

    /// The `installed.json` text naming the active seed generation.
    fn installed_text(&self, manifest_digest: &str) -> String {
        format!(
            "{{\"schema_version\":1,\"channel\":\"stable\",\
             \"channel_manifest_sha256\":\"{manifest_digest}\",\
             \"current_generation\":\"{SEED_GENERATION}\",\"previous_generation\":null,\
             \"installed_at\":\"2026-09-20T00:00:00Z\"}}"
        )
    }

    /// Put the target-version artifact bytes of every declared component into the local cache.
    fn cache_artifacts(&self) {
        for component in DECLARED {
            let path = self.cache.join(cache_name(component));
            std::fs::write(&path, payload(component))
                .expect("the cached artifact must be writable");
        }
    }

    /// Replace the channel manifest this installation records, keeping the record self-consistent.
    fn rewrite_channel(&self, text: &str) {
        let digest = sha256::hex(text.as_bytes());
        std::fs::write(&self.manifest_path, text.as_bytes())
            .expect("the fixture manifest must be rewritable");
        std::fs::write(self.root.join("recorded-manifest.json"), text.as_bytes())
            .expect("the recorded manifest must be rewritable");
        std::fs::write(
            self.root.join("installed.json"),
            self.installed_text(&digest),
        )
        .expect("the installed record must be rewritable");
    }
}
/// Run the real binary against one install root, channel manifest and artifact cache.
fn run_in(
    root: &Path,
    manifest: Option<&Path>,
    cache: &Path,
    args: &[&str],
) -> (i32, String, String) {
    let manifest = match manifest {
        Some(path) => path.to_string_lossy().to_string(),
        None => String::new(),
    };
    let output = Command::new(env!("CARGO_BIN_EXE_axiom-cli"))
        .args(args)
        .env("AXIOM_CLI_INSTALL_ROOT", root)
        .env("AXIOM_CLI_ARTIFACT_CACHE", cache)
        .env("AXIOM_CLI_CHANNEL_MANIFEST", manifest)
        .output()
        .expect("the axiom-cli test binary must be runnable");
    (
        output.status.code().unwrap_or(-1),
        String::from_utf8_lossy(&output.stdout).to_string(),
        String::from_utf8_lossy(&output.stderr).to_string(),
    )
}

/// Run the real binary against a fixture.
fn run(fixture: &Fixture, args: &[&str]) -> (i32, String, String) {
    run_in(
        &fixture.root,
        Some(&fixture.manifest_path),
        &fixture.cache,
        args,
    )
}

/// Assert the `--json` contract: exactly one JSON object, on one line.
fn assert_single_json_object(stdout: &str) {
    let trimmed = stdout.trim();
    assert!(
        trimmed.starts_with('{'),
        "stdout must be one JSON object: {stdout}"
    );
    assert!(
        trimmed.ends_with('}'),
        "stdout must be one JSON object: {stdout}"
    );
    assert_eq!(
        trimmed.matches('\n').count(),
        0,
        "stdout must be one line: {stdout}"
    );
}

/// The value of a JSON string field, by first occurrence.
fn field(document: &str, key: &str) -> String {
    let needle = format!("\"{key}\":\"");
    let start = document
        .find(&needle)
        .unwrap_or_else(|| panic!("`{key}` is absent from {document}"))
        + needle.len();
    let rest = &document[start..];
    let end = rest
        .find('"')
        .unwrap_or_else(|| panic!("`{key}` is unterminated in {document}"));
    rest[..end].to_string()
}

/// The raw text of a JSON field, up to the next `,` or `}`.
fn raw_field(document: &str, key: &str) -> String {
    let needle = format!("\"{key}\":");
    let start = document
        .find(&needle)
        .unwrap_or_else(|| panic!("`{key}` is absent from {document}"))
        + needle.len();
    let rest = &document[start..];
    let end = rest.find([',', '}']).unwrap_or(rest.len());
    rest[..end].to_string()
}

/// Build the plan through the real `update plan` verb and return its digest.
fn plan_once(fixture: &Fixture) -> String {
    let plan_path = fixture.plan_path.to_string_lossy().to_string();
    let (code, out, err) = run(
        fixture,
        &[
            "update",
            "plan",
            "--to",
            TARGET_VERSION,
            "--out",
            &plan_path,
            "--json",
        ],
    );
    assert_eq!(
        code, SUCCESS,
        "update plan must succeed\nstdout={out}\nstderr={err}"
    );
    assert_single_json_object(&out);
    assert!(fixture.plan_path.is_file(), "the plan file must be written");
    field(&out, "plan_digest")
}

/// Apply the plan file with one approval digest.
fn apply_with(fixture: &Fixture, digest: &str) -> (i32, String, String) {
    let plan_path = fixture.plan_path.to_string_lossy().to_string();
    run(
        fixture,
        &[
            "update",
            "apply",
            "--plan",
            &plan_path,
            "--approve-digest",
            digest,
            "--json",
        ],
    )
}

/// The generation directories present under the install root.
fn generations_on_disk(fixture: &Fixture) -> Vec<String> {
    let mut names: Vec<String> = Vec::new();
    if let Ok(entries) = std::fs::read_dir(fixture.root.join("generations")) {
        for entry in entries.flatten() {
            if entry.path().is_dir() {
                names.push(entry.file_name().to_string_lossy().to_string());
            }
        }
    }
    names.sort();
    names
}

/// The digest of one file.
fn digest_of(path: &Path) -> String {
    sha256::hex(&std::fs::read(path).unwrap_or_else(|error| panic!("reading {path:?}: {error}")))
}
#[test]
fn the_test_local_sha256_matches_the_published_vectors() {
    assert_eq!(
        sha256::hex(b""),
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    );
    assert_eq!(
        sha256::hex(b"abc"),
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    );
    assert_eq!(
        sha256::hex(b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"),
        "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"
    );
}

#[test]
fn the_committed_channel_manifest_parses_and_declares_the_component_set() {
    let committed = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("channels")
        .join("stable.json");
    assert!(
        committed.is_file(),
        "channels/stable.json must ship with this repository"
    );
    let empty = std::env::temp_dir().join(format!("axiom-cli-j007-empty-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&empty);
    std::fs::create_dir_all(empty.join("cache")).expect("a scratch root must be creatable");
    let cache = empty.join("cache");
    let (code, out, err) = run_in(
        &empty,
        Some(&committed),
        &cache,
        &["update", "check", "--json"],
    );
    assert_eq!(
        code, SUCCESS,
        "check must accept the committed manifest\nstderr={err}"
    );
    assert_single_json_object(&out);
    assert_eq!(field(&out, "state"), "not_installed");
    assert_eq!(field(&out, "channel"), "stable");
    assert_eq!(raw_field(&out, "published"), "false");
    assert_eq!(raw_field(&out, "manifest_version"), "1");
    for component in ALL_COMPONENTS {
        assert!(
            out.contains(&format!("\"component\":\"{component}\"")),
            "`{component}` must be reported from the committed manifest: {out}"
        );
    }
    assert!(
        out.contains("\"status\":\"undeclared\""),
        "axiom-mcp must stay undeclared: {out}"
    );
    let _ = std::fs::remove_dir_all(&empty);
}

#[test]
fn check_reads_the_recorded_manifest_and_changes_nothing() {
    let fixture = Fixture::new("check", Mode::Published);
    let before = digest_of(&fixture.root.join("installed.json"));
    let (code, out, err) = run(&fixture, &["update", "check", "--json"]);
    assert_eq!(code, SUCCESS, "check must succeed\nstderr={err}");
    assert_single_json_object(&out);
    assert_eq!(field(&out, "state"), "installed");
    assert_eq!(field(&out, "current_generation"), SEED_GENERATION);
    assert_eq!(raw_field(&out, "updates_available"), "true");
    assert_eq!(digest_of(&fixture.root.join("installed.json")), before);
    assert_eq!(
        generations_on_disk(&fixture),
        vec![SEED_GENERATION.to_string()]
    );

    let (code, out, err) = run(&fixture, &["update", "check", "--all", "--json"]);
    assert_eq!(code, SUCCESS, "check --all must succeed\nstderr={err}");
    assert!(
        out.contains("\"state\":\"verified\""),
        "an artifact already in the local cache must verify: {out}"
    );
    assert!(
        !out.contains("\"state\":\"unverified\""),
        "nothing in this fixture is unverified: {out}"
    );
}

#[test]
fn check_with_no_installed_release_and_no_named_manifest_is_not_ready() {
    let empty = std::env::temp_dir().join(format!("axiom-cli-j007-nr-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&empty);
    std::fs::create_dir_all(empty.join("cache")).expect("a scratch root must be creatable");
    let cache = empty.join("cache");
    let (code, out, err) = run_in(&empty, None, &cache, &["update", "check", "--json"]);
    assert_eq!(
        code, NOT_READY,
        "check must refuse without an installed release\nstdout={out}\nstderr={err}"
    );
    assert_single_json_object(&out);
    assert_eq!(field(&out, "reason_code"), "no_installed_release");
    assert!(
        out.contains("\"retryable\":true"),
        "a missing release is retryable: {out}"
    );

    let (code, out, err) = run_in(&empty, None, &cache, &["update", "check"]);
    assert_eq!(code, NOT_READY);
    assert!(
        out.trim().is_empty(),
        "plain NotReady must not write stdout: {out}"
    );
    assert!(
        err.contains("NotReady"),
        "plain NotReady must state its class: {err}"
    );
    let _ = std::fs::remove_dir_all(&empty);
}

#[test]
fn plan_resolves_only_the_version_the_recorded_manifest_declares() {
    let fixture = Fixture::new("plan-version", Mode::Published);
    for attempted in ["9.9.9", "latest", "main"] {
        let (code, out, err) = run(&fixture, &["update", "plan", "--to", attempted, "--json"]);
        assert_eq!(
            code, VALIDATION,
            "plan --to {attempted} must be refused\nstdout={out}\nstderr={err}"
        );
        assert_eq!(field(&out, "reason_code"), "version_not_in_channel");
    }
    let digest = plan_once(&fixture);
    assert_eq!(
        digest.len(),
        64,
        "the approval digest must be a sha256: {digest}"
    );
    assert!(
        fixture.plan_path.is_file(),
        "the plan file must survive the run"
    );
}

#[test]
fn the_recorded_digest_must_match_the_installed_bytes() {
    let fixture = Fixture::new("recorded-digest", Mode::Published);
    let recorded = fixture.root.join("recorded-manifest.json");
    let mut tampered = std::fs::read(&recorded).expect("the recorded manifest must exist");
    tampered.push(b'\n');
    std::fs::write(&recorded, &tampered).expect("the recorded manifest must be rewritable");

    let (code, out, err) = run(&fixture, &["update", "check", "--json"]);
    assert_eq!(
        code, VALIDATION,
        "check must refuse a changed recorded manifest\nstderr={err}"
    );
    assert_eq!(
        field(&out, "reason_code"),
        "recorded_manifest_digest_mismatch"
    );

    let (code, out, _) = run(
        &fixture,
        &["update", "plan", "--to", TARGET_VERSION, "--json"],
    );
    assert_eq!(
        code, VALIDATION,
        "plan must refuse a changed recorded manifest"
    );
    assert_eq!(
        field(&out, "reason_code"),
        "recorded_manifest_digest_mismatch"
    );
}
#[test]
fn apply_swaps_atomically_and_keeps_the_previous_generation() {
    let fixture = Fixture::new("apply", Mode::Published);
    let digest = plan_once(&fixture);
    let (code, out, err) = apply_with(&fixture, &digest);
    assert_eq!(
        code, SUCCESS,
        "apply must succeed\nstdout={out}\nstderr={err}"
    );
    assert_single_json_object(&out);
    assert_eq!(raw_field(&out, "idempotent"), "false");
    assert_eq!(field(&out, "previous_generation"), SEED_GENERATION);
    assert_eq!(field(&out, "plan_digest"), digest);
    assert_eq!(field(&out, "journal_state"), "finalized");
    let generation = field(&out, "generation");
    assert_ne!(
        generation, SEED_GENERATION,
        "a new generation must be created"
    );
    assert!(
        out.contains("\"needs_restart\":[\"axiom-graphd\",\"axiom\",\"axiom-cli\",\"skills\"]"),
        "every changed component must be reported per component: {out}"
    );

    let mut kept = generations_on_disk(&fixture);
    kept.sort();
    let mut expected = vec![SEED_GENERATION.to_string(), generation.clone()];
    expected.sort();
    assert_eq!(kept, expected, "the previous generation must be retained");

    let installed = std::fs::read_to_string(fixture.root.join("installed.json"))
        .expect("the installed record must be readable");
    assert!(
        installed.contains(&format!("\"current_generation\":\"{generation}\"")),
        "the new generation must be active: {installed}"
    );
    assert!(
        installed.contains(&format!("\"previous_generation\":\"{SEED_GENERATION}\"")),
        "the seed must be the retained previous generation: {installed}"
    );

    let swapped = fixture
        .root
        .join("generations")
        .join(&generation)
        .join("payload")
        .join("axiom-cli")
        .join(cache_name("axiom-cli"));
    assert_eq!(
        digest_of(&swapped),
        sha256::hex(&payload("axiom-cli")),
        "the active payload must be the bytes the manifest published"
    );
}

#[test]
fn apply_refuses_a_tampered_artifact_digest() {
    let fixture = Fixture::new("tampered", Mode::Published);
    let digest = plan_once(&fixture);
    let cached = fixture.cache.join(cache_name("axiom-cli"));
    let mut bytes = std::fs::read(&cached).expect("the cached artifact must exist");
    bytes[0] ^= 0xff;
    std::fs::write(&cached, &bytes).expect("the cached artifact must be rewritable");

    let (code, out, err) = apply_with(&fixture, &digest);
    assert_eq!(
        code, VALIDATION,
        "a tampered artifact must be refused\nstdout={out}\nstderr={err}"
    );
    assert_eq!(field(&out, "reason_code"), "artifact_digest_mismatch");
    assert_eq!(
        generations_on_disk(&fixture),
        vec![SEED_GENERATION.to_string()],
        "nothing may be swapped when an artifact does not verify"
    );
    let installed = std::fs::read_to_string(fixture.root.join("installed.json")).unwrap();
    assert!(installed.contains(&format!("\"current_generation\":\"{SEED_GENERATION}\"")));
    let staging = fixture.root.join("staging");
    let leftovers: Vec<PathBuf> = std::fs::read_dir(&staging)
        .map(|entries| entries.flatten().map(|entry| entry.path()).collect())
        .unwrap_or_default();
    assert!(
        leftovers.is_empty(),
        "the staging tree must be discarded: {leftovers:?}"
    );
}

#[test]
fn apply_refuses_an_unreachable_artifact_while_offline() {
    let fixture = Fixture::new("unreachable", Mode::Published);
    let digest = plan_once(&fixture);
    std::fs::remove_file(fixture.cache.join(cache_name("axiom-cli")))
        .expect("the cached artifact must be removable");

    let (code, out, err) = apply_with(&fixture, &digest);
    assert_eq!(
        code, NOT_READY,
        "an artifact that cannot be obtained locally is not ready, not applied\nstdout={out}\nstderr={err}"
    );
    assert_eq!(field(&out, "reason_code"), "artifact_unreachable");
    assert_eq!(
        generations_on_disk(&fixture),
        vec![SEED_GENERATION.to_string()],
        "an unverified artifact must leave the active generation untouched"
    );
}

#[test]
fn apply_rolls_back_when_the_health_check_fails() {
    let fixture = Fixture::new("health", Mode::FailingProbe);
    let digest = plan_once(&fixture);
    let (code, out, err) = apply_with(&fixture, &digest);
    assert_eq!(
        code, CONFLICT,
        "a failed post-swap probe is a conflict\nstdout={out}\nstderr={err}"
    );
    assert_eq!(field(&out, "reason_code"), "health_check_failed:axiom-cli");

    let installed = std::fs::read_to_string(fixture.root.join("installed.json"))
        .expect("the installed record must be readable");
    assert!(
        installed.contains(&format!("\"current_generation\":\"{SEED_GENERATION}\"")),
        "the seed must be active again after the rollback: {installed}"
    );
    assert!(
        installed.contains("\"previous_generation\":null"),
        "a generation that just failed its probe must not become the retained rollback target: {installed}"
    );

    // `previous` therefore has nothing to restore, and the CLI says so instead of re-activating
    // a generation that failed its own health check.
    let (code, out, err) = run(
        &fixture,
        &["update", "rollback", "--transaction", "previous", "--json"],
    );
    assert_eq!(
        code, CONFLICT,
        "there is no verified previous generation to restore\nstdout={out}\nstderr={err}"
    );
    assert_eq!(field(&out, "reason_code"), "no_previous_generation");
}

#[test]
fn apply_is_idempotent_on_a_re_run() {
    let fixture = Fixture::new("idempotent", Mode::Published);
    let digest = plan_once(&fixture);
    let (code, first, err) = apply_with(&fixture, &digest);
    assert_eq!(code, SUCCESS, "the first apply must succeed\nstderr={err}");
    let generation = field(&first, "generation");
    let after_first = generations_on_disk(&fixture);

    let (code, second, err) = apply_with(&fixture, &digest);
    assert_eq!(
        code, SUCCESS,
        "re-applying an already-recorded plan is not a failure\nstdout={second}\nstderr={err}"
    );
    assert_eq!(field(&second, "status"), "already_applied");
    assert_eq!(raw_field(&second, "idempotent"), "true");
    assert_eq!(field(&second, "generation"), generation);
    assert_eq!(
        generations_on_disk(&fixture),
        after_first,
        "an idempotent re-run must not create a generation"
    );
}

#[test]
fn apply_recovers_an_interrupted_transaction_before_it_starts() {
    let fixture = Fixture::new("interrupted", Mode::Published);
    let digest = plan_once(&fixture);
    let interrupted = "t-20260920t000000z-deadbeef";
    let staged_generation = "g-20260920t000000z-99999999";

    let staging = fixture.root.join("staging").join(interrupted);
    std::fs::create_dir_all(staging.join("payload").join("axiom-cli"))
        .expect("the fixture staging tree must be creatable");
    std::fs::write(
        staging
            .join("payload")
            .join("axiom-cli")
            .join("never-verified.zip"),
        b"a staging tree that was never verified",
    )
    .expect("the fixture staging payload must be writable");
    std::fs::create_dir_all(fixture.root.join("journal"))
        .expect("the fixture journal directory must be creatable");
    let journal = format!(
        "{{\"schema_version\":1,\"transaction_id\":\"{interrupted}\",\
         \"plan_id\":\"update-stable-axiom-cli\",\"plan_digest\":\"{SEED_PLAN_DIGEST}\",\
         \"channel\":\"stable\",\"host\":\"{host}\",\"install_root\":\"{root}\",\
         \"state\":\"staged\",\"started_at\":\"2026-09-20T00:00:00Z\",\
         \"updated_at\":\"2026-09-20T00:00:00Z\",\"from_generation\":\"{SEED_GENERATION}\",\
         \"to_generation\":\"{staged_generation}\",\"needs_restart\":[],\"actions\":[]}}",
        host = host(),
        root = fixture.root_text(),
    );
    std::fs::write(
        fixture
            .root
            .join("journal")
            .join(format!("{interrupted}.json")),
        journal.as_bytes(),
    )
    .expect("the fixture journal must be writable");
    std::fs::write(
        fixture.root.join("update.lock"),
        format!("transaction={interrupted}\npid=999999\n").as_bytes(),
    )
    .expect("the fixture lock must be writable");

    let (code, out, err) = apply_with(&fixture, &digest);
    assert_eq!(
        code, SUCCESS,
        "apply must recover the interrupted transaction and then succeed\nstdout={out}\nstderr={err}"
    );
    assert!(
        out.contains("\"recovered\""),
        "the recovery must be reported: {out}"
    );
    assert!(
        !staging.exists(),
        "the abandoned staging tree must be discarded"
    );
    assert!(
        !fixture.root.join("update.lock").exists(),
        "the lock left behind by the interrupted transaction must be released"
    );
    let settled = std::fs::read_to_string(
        fixture
            .root
            .join("journal")
            .join(format!("{interrupted}.json")),
    )
    .expect("the interrupted journal must still exist");
    assert!(
        settled.contains("\"state\":\"abandoned\""),
        "the interrupted transaction must settle as abandoned: {settled}"
    );
}
#[test]
fn rollback_restores_the_retained_generation() {
    let fixture = Fixture::new("rollback", Mode::Published);
    let digest = plan_once(&fixture);
    let (code, applied, err) = apply_with(&fixture, &digest);
    assert_eq!(code, SUCCESS, "the apply must succeed\nstderr={err}");
    let applied_generation = field(&applied, "generation");

    let (code, out, err) = run(
        &fixture,
        &["update", "rollback", "--transaction", "previous", "--json"],
    );
    assert_eq!(
        code, SUCCESS,
        "rolling back to the retained generation must succeed\nstdout={out}\nstderr={err}"
    );
    assert_eq!(field(&out, "status"), "rolled_back");
    assert_eq!(field(&out, "generation"), SEED_GENERATION);
    assert_eq!(field(&out, "replaced_generation"), applied_generation);
    let installed = std::fs::read_to_string(fixture.root.join("installed.json"))
        .expect("the installed record must be readable");
    assert!(installed.contains(&format!("\"current_generation\":\"{SEED_GENERATION}\"")));
    assert!(installed.contains(&format!("\"previous_generation\":\"{applied_generation}\"")));

    let (code, out, err) = run(
        &fixture,
        &["update", "rollback", "--transaction", "nope", "--json"],
    );
    assert_eq!(
        code, NOT_FOUND,
        "an unknown transaction is refused as not found\nstdout={out}\nstderr={err}"
    );
    assert_eq!(field(&out, "reason_code"), "transaction_unknown");
}

#[test]
fn rollback_refuses_a_stale_approval_digest() {
    let fixture = Fixture::new("rollback-stale", Mode::Published);
    let digest = plan_once(&fixture);
    let (code, _, err) = apply_with(&fixture, &digest);
    assert_eq!(code, SUCCESS, "the apply must succeed\nstderr={err}");

    let (code, out, err) = run(
        &fixture,
        &[
            "update",
            "rollback",
            "--transaction",
            "previous",
            "--approve-digest",
            ZERO_DIGEST,
            "--json",
        ],
    );
    assert_eq!(
        code, VALIDATION,
        "an approval that does not cover the generation is stale\nstdout={out}\nstderr={err}"
    );
    assert_eq!(field(&out, "reason_code"), "approval_stale");
}

#[test]
fn rollback_refuses_when_no_previous_generation_is_retained() {
    let fixture = Fixture::new("rollback-none", Mode::Published);
    let (code, out, err) = run(
        &fixture,
        &["update", "rollback", "--transaction", "previous", "--json"],
    );
    assert_eq!(
        code, CONFLICT,
        "there is nothing to roll back to\nstdout={out}\nstderr={err}"
    );
    assert_eq!(field(&out, "reason_code"), "no_previous_generation");
}

#[test]
fn apply_refuses_an_approval_digest_that_does_not_match_the_plan() {
    let fixture = Fixture::new("approval", Mode::Published);
    let _approved = plan_once(&fixture);
    let (code, out, err) = apply_with(&fixture, ZERO_DIGEST);
    assert_eq!(
        code, CONFLICT,
        "a digest that does not cover the plan body is stale\nstdout={out}\nstderr={err}"
    );
    assert_eq!(field(&out, "reason_code"), "approval_stale");
    assert_eq!(
        generations_on_disk(&fixture),
        vec![SEED_GENERATION.to_string()]
    );
}

#[test]
fn apply_refuses_a_plan_whose_recorded_digest_is_not_in_the_recorded_manifest() {
    let fixture = Fixture::new("plan-not-in-manifest", Mode::Published);
    let approved = plan_once(&fixture);

    // Replace the manifest this installation records - and keep `installed.json` consistent with
    // it - so the plan is still self-consistent but no longer matches the recorded bytes.
    let original = manifest_text(Mode::Published);
    let replaced = original.replace(
        &sha256::hex(&payload("axiom-cli")),
        &sha256::hex(b"a different artifact for axiom-cli"),
    );
    assert_ne!(
        replaced, original,
        "the fixture edit must change the manifest"
    );
    fixture.rewrite_channel(&replaced);

    let (code, out, err) = apply_with(&fixture, &approved);
    assert_eq!(
        code, VALIDATION,
        "a plan that no longer matches the recorded bytes is refused\nstdout={out}\nstderr={err}"
    );
    assert_eq!(
        field(&out, "reason_code"),
        "plan_not_in_recorded_manifest:axiom-cli"
    );
    assert_eq!(
        generations_on_disk(&fixture),
        vec![SEED_GENERATION.to_string()],
        "the recorded digest mismatch must stop the transaction before anything is staged"
    );
}
/// `10` lock unavailable, from the canonical exit vocabulary.
const LOCK_UNAVAILABLE: i32 = 10;
const IO_ERROR: i32 = 8;

#[test]
fn an_unsigned_channel_is_never_resolved() {
    let fixture = Fixture::new("unsigned", Mode::Unsigned);
    let (code, out, err) = run(&fixture, &["update", "check", "--json"]);
    assert_eq!(
        code, VALIDATION,
        "a channel with no trust_root must never be resolved\nstdout={out}\nstderr={err}"
    );
    assert_eq!(field(&out, "reason_code"), "unsigned_channel");
    let (code, out, _) = run(
        &fixture,
        &["update", "plan", "--to", TARGET_VERSION, "--json"],
    );
    assert_eq!(code, VALIDATION);
    assert_eq!(field(&out, "reason_code"), "unsigned_channel");
}

#[test]
fn a_forbidden_pin_is_never_resolved() {
    let fixture = Fixture::new("forbidden-pin", Mode::ForbiddenPin);
    let (code, out, err) = run(&fixture, &["update", "check", "--json"]);
    assert_eq!(
        code, VALIDATION,
        "a version pinned to `latest` must never be resolved\nstdout={out}\nstderr={err}"
    );
    assert_eq!(field(&out, "reason_code"), "forbidden_pin:latest");
}

#[test]
fn an_expired_trust_window_refuses_installation() {
    let fixture = Fixture::new("expired", Mode::Expired);
    let (code, out, err) = run(&fixture, &["update", "check", "--json"]);
    assert_eq!(
        code, INCOMPATIBLE,
        "an expired trust window is incompatible, not valid\nstdout={out}\nstderr={err}"
    );
    assert_eq!(field(&out, "reason_code"), "channel_metadata_expired");
    // An expired window cannot even be planned, so no approval digest can ever be produced for
    // it: the update is refused before anything is downloaded.
    let (code, out, _) = run(
        &fixture,
        &["update", "plan", "--to", TARGET_VERSION, "--json"],
    );
    assert_eq!(code, INCOMPATIBLE);
    assert_eq!(field(&out, "reason_code"), "channel_metadata_expired");
}

#[test]
fn apply_re_verifies_the_trust_window_of_the_recorded_manifest() {
    // The plan is approved while the window is open, then the recorded channel expires before
    // the bytes are swapped: apply must re-verify the trust metadata rather than apply the
    // stale approval, and it must leave the installed generation untouched.
    let fixture = Fixture::new("expired-late", Mode::Published);
    let digest = plan_once(&fixture);
    fixture.rewrite_channel(&manifest_text(Mode::Expired));
    let (code, out, err) = apply_with(&fixture, &digest);
    assert_eq!(
        code, INCOMPATIBLE,
        "a channel that expired after approval must not be applied\\nstdout={out}\\nstderr={err}"
    );
    assert_eq!(field(&out, "reason_code"), "channel_metadata_expired");
    assert_eq!(
        generations_on_disk(&fixture),
        vec![SEED_GENERATION.to_string()],
        "a refused apply must leave the installed generation untouched"
    );
}

#[test]
fn apply_refuses_while_the_coordinator_lock_is_held() {
    let fixture = Fixture::new("lock", Mode::Published);
    let digest = plan_once(&fixture);
    std::fs::write(
        fixture.root.join("update.lock"),
        b"transaction=t-00000000t000000z-00000000\npid=1\n",
    )
    .expect("the fixture lock must be writable");

    let (code, out, err) = apply_with(&fixture, &digest);
    assert_eq!(
        code, LOCK_UNAVAILABLE,
        "another transaction holds the coordinator lock\nstdout={out}\nstderr={err}"
    );
    assert_eq!(field(&out, "reason_code"), "lock_unavailable");
    assert_eq!(
        generations_on_disk(&fixture),
        vec![SEED_GENERATION.to_string()],
        "a refused transaction must not create a generation"
    );
}

#[test]
fn an_unreadable_installed_record_is_an_io_error_not_a_missing_release() {
    // Exit 8 had no test: an installed record that exists but cannot be read is an internal I/O
    // failure of this host, and must not be reported as "nothing is installed" (which would tell
    // an operator their install is gone when it is merely unreadable).
    if unsafe { libc_geteuid() } == 0 {
        eprintln!("skipping: root ignores file permissions, so the record stays readable");
        return;
    }
    let fixture = Fixture::new("unreadable-record", Mode::Published);
    let record = fixture.root.join("installed.json");
    assert!(record.is_file(), "the fixture must have written a record");
    let mut permissions = std::fs::metadata(&record)
        .expect("the record must be statable")
        .permissions();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        permissions.set_mode(0o000);
    }
    std::fs::set_permissions(&record, permissions).expect("the record must be made unreadable");

    let (code, out, err) = run(&fixture, &["update", "check", "--json"]);

    // Restore before the fixture drops, so its cleanup can remove the tree.
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut restored = std::fs::metadata(&record)
            .expect("the record must be statable")
            .permissions();
        restored.set_mode(0o644);
        let _ = std::fs::set_permissions(&record, restored);
    }
    assert_eq!(
        code, IO_ERROR,
        "an unreadable record is an I/O failure\nstdout={out}\nstderr={err}"
    );
    assert_eq!(field(&out, "reason_code"), "installed_unreadable");
    assert!(
        !out.contains("no_installed_release"),
        "an unreadable record must not be reported as absent: {out}"
    );
}

/// The process's effective uid, without pulling in a dependency.
///
/// `axiom-cli` has zero third-party dependencies, so the test reaches the C library directly:
/// `geteuid` takes no arguments and cannot fail.
unsafe fn libc_geteuid() -> u32 {
    unsafe extern "C" {
        fn geteuid() -> u32;
    }
    unsafe { geteuid() }
}

#[test]
fn the_transaction_never_touches_state_outside_the_install_root() {
    let fixture = Fixture::new("outside", Mode::Published);
    let userdata = fixture.dir.join("userdata");
    let graph_output = fixture.dir.join("graph-output");
    std::fs::create_dir_all(&userdata).expect("a user data stand-in must be creatable");
    std::fs::create_dir_all(&graph_output).expect("a graph output stand-in must be creatable");
    std::fs::write(userdata.join("library.db"), b"user data that must survive")
        .expect("the stand-in user data must be writable");
    std::fs::write(graph_output.join("graph.json"), b"{\"nodes\":[]}")
        .expect("the stand-in graph output must be writable");
    let before_user = digest_of(&userdata.join("library.db"));
    let before_graph = digest_of(&graph_output.join("graph.json"));

    let digest = plan_once(&fixture);
    let (code, out, err) = apply_with(&fixture, &digest);
    assert_eq!(
        code, SUCCESS,
        "apply must succeed\nstdout={out}\nstderr={err}"
    );
    let (code, out, err) = run(
        &fixture,
        &["update", "rollback", "--transaction", "previous", "--json"],
    );
    assert_eq!(
        code, SUCCESS,
        "rollback must succeed\nstdout={out}\nstderr={err}"
    );

    assert_eq!(
        digest_of(&userdata.join("library.db")),
        before_user,
        "user data must be untouched by apply and rollback"
    );
    assert_eq!(
        digest_of(&graph_output.join("graph.json")),
        before_graph,
        "the graph output root must be untouched by apply and rollback"
    );
}
