//! Artifact acquisition and the verification that must happen before an artifact is used.
//!
//! Two rules shape this module.
//!
//! First, an artifact is used only after its byte length and its sha256 both match the recorded
//! channel manifest. Verification happens against the destination copy, and a copy that fails
//! is deleted rather than left behind: an unverified artifact never exists in the install root
//! where a later step could mistake it for a verified one.
//!
//! Second, this wave is a closed-publication wave. Acquisition resolves an artifact from a
//! local, on-disk source only - the artifact cache named by `AXIOM_CLI_ARTIFACT_CACHE`, or a
//! `file://` location - and an `https://` artifact that is not in the local cache is refused as
//! unreachable instead of being fetched from a network. Nothing here contacts a remote, opens a
//! socket, or follows a redirect, which is exactly why the offline case can be tested honestly.

use std::path::{Path, PathBuf};

use super::error::Refusal;
use super::sha256;
use super::state::{self, State};

/// Where an artifact's bytes were taken from.
#[derive(Clone, Debug)]
pub enum Origin {
    /// The local artifact cache.
    Cache(PathBuf),
    /// A `file://` location.
    File(PathBuf),
}

impl Origin {
    /// A short label for evidence and for the JSON details.
    pub fn label(&self) -> String {
        match self {
            Origin::Cache(path) => format!("cache:{}", path.display()),
            Origin::File(path) => format!("file:{}", path.display()),
        }
    }
}

/// The cache key of an artifact URL: its last path segment, without a query or a fragment.
///
/// Only the path is considered, never the authority: an origin such as
/// `https://example.invalid/` names no artifact file, so it has no cache key and the lookup is
/// skipped instead of resolving a file named after the host.
pub fn url_basename(url: &str) -> Option<String> {
    let without_fragment = url.split('#').next().unwrap_or(url);
    let without_query = without_fragment
        .split('?')
        .next()
        .unwrap_or(without_fragment);
    let path = match without_query.split_once("://") {
        Some((_, rest)) => match rest.find('/') {
            Some(index) => &rest[index..],
            None => "",
        },
        None => without_query,
    };
    let trimmed = path.trim_end_matches('/');
    let name = trimmed.rsplit('/').next()?;
    if name.is_empty() || name == "." || name == ".." {
        return None;
    }
    if name.contains('\\') || name.contains(':') {
        return None;
    }
    Some(name.to_string())
}

/// The artifact cache directory, when the host declared one.
pub fn cache_dir() -> Option<PathBuf> {
    match std::env::var(state::ARTIFACT_CACHE_ENV) {
        Ok(value) if !value.trim().is_empty() => Some(PathBuf::from(value)),
        _ => None,
    }
}

/// Resolve an artifact URL to a local source, or refuse.
pub fn resolve(url: &str) -> Result<Origin, Refusal> {
    if let Some(directory) = cache_dir() {
        if let Some(name) = url_basename(url) {
            let candidate = directory.join(name);
            if candidate.is_file() {
                return Ok(Origin::Cache(candidate));
            }
        }
    }
    if let Some(rest) = url.strip_prefix("file://") {
        let cleaned = rest.trim_start_matches('/');
        let candidate = PathBuf::from(cleaned.replace('/', std::path::MAIN_SEPARATOR_STR));
        if candidate.is_file() {
            return Ok(Origin::File(candidate));
        }
        return Err(Refusal::not_ready(
            "artifact_unreachable",
            format!(
                "the artifact location {url} does not exist ({})",
                candidate.display()
            ),
        ));
    }
    Err(Refusal::not_ready(
        "artifact_unreachable",
        format!(
            "the artifact {url} is not present in the local artifact cache ({} is {}, and no \
             cached file is named {}): this wave acquires artifacts from local, on-disk sources \
             only and never contacts a remote, so the artifact stays unverified and nothing is \
             applied for it",
            state::ARTIFACT_CACHE_ENV,
            match cache_dir() {
                Some(path) => path.display().to_string(),
                None => "unset".to_string(),
            },
            url_basename(url).unwrap_or_else(|| "<unresolved>".to_string())
        ),
    ))
}

/// Acquire one artifact into `destination`, verifying length and digest before returning.
pub fn acquire(
    url: &str,
    expected_sha256: &str,
    expected_size: i64,
    destination: &Path,
) -> Result<Origin, Refusal> {
    let origin = resolve(url)?;
    let source = match &origin {
        Origin::Cache(path) | Origin::File(path) => path.clone(),
    };
    let bytes = std::fs::read(&source).map_err(|error| {
        Refusal::io("artifact_unreadable", &source.display().to_string(), &error)
    })?;
    if destination.exists() {
        std::fs::remove_file(destination).map_err(|error| {
            Refusal::io(
                "artifact_stale_removal_failed",
                &destination.display().to_string(),
                &error,
            )
        })?;
    }
    if let Some(parent) = destination.parent() {
        std::fs::create_dir_all(parent).map_err(|error| {
            Refusal::io(
                "artifact_destination_unwritable",
                &parent.display().to_string(),
                &error,
            )
        })?;
    }
    if bytes.len() as i64 != expected_size {
        return Err(Refusal::validation(
            "artifact_size_mismatch",
            format!(
                "the artifact {} is {} bytes but the recorded channel manifest declares {}: the \
                 artifact was not used",
                url,
                bytes.len(),
                expected_size
            ),
        ));
    }
    let observed = sha256::digest_hex(&bytes);
    if observed != expected_sha256 {
        return Err(Refusal::validation(
            "artifact_digest_mismatch",
            format!(
                "the artifact {} digests to {} but the recorded channel manifest declares {}: the \
                 artifact was not used and nothing was installed from it",
                url, observed, expected_sha256
            ),
        ));
    }
    std::fs::write(destination, &bytes).map_err(|error| {
        Refusal::io(
            "artifact_write_failed",
            &destination.display().to_string(),
            &error,
        )
    })?;
    Ok(origin)
}

/// Verify an artifact already on disk against its recorded digest and length.
pub fn verify_file(path: &Path, expected_sha256: &str, expected_size: i64) -> Result<(), Refusal> {
    let metadata = std::fs::metadata(path)
        .map_err(|error| Refusal::io("artifact_unreadable", &path.display().to_string(), &error))?;
    if metadata.len() as i64 != expected_size {
        return Err(Refusal::validation(
            "artifact_size_mismatch",
            format!(
                "{} is {} bytes but the recorded channel manifest declares {}",
                path.display(),
                metadata.len(),
                expected_size
            ),
        ));
    }
    let observed = state::digest_file(path, "artifact_unreadable")?;
    if observed != expected_sha256 {
        return Err(Refusal::validation(
            "artifact_digest_mismatch",
            format!(
                "{} digests to {} but the recorded channel manifest declares {}",
                path.display(),
                observed,
                expected_sha256
            ),
        ));
    }
    Ok(())
}

/// The install root a `State` wraps, as the manifest-ready string used in plan documents.
pub fn install_root_text(state: &State) -> String {
    state.root().to_string_lossy().replace('\\', "/")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_cache_key_is_the_last_segment_without_a_query() {
        assert_eq!(
            url_basename("https://example.invalid/axiom/axiom-cli.exe?x=1#frag").as_deref(),
            Some("axiom-cli.exe")
        );
        assert_eq!(
            url_basename("https://example.invalid/dist/0.0.0-dev/").as_deref(),
            Some("0.0.0-dev")
        );
        assert_eq!(url_basename("https://example.invalid/"), None);
    }

    #[test]
    fn a_cache_key_may_not_smuggle_a_separator_or_a_drive_letter() {
        assert_eq!(url_basename("https://example.invalid/a\\.exe"), None);
        assert_eq!(url_basename("https://example.invalid/C:payload.exe"), None);
    }

    #[test]
    fn an_https_artifact_without_a_cache_entry_is_unreachable_not_installed() {
        std::env::remove_var(state::ARTIFACT_CACHE_ENV);
        let error = resolve("https://example.invalid/artifact.exe").expect_err("must refuse");
        assert_eq!(error.reason, "artifact_unreachable");
        assert_eq!(error.class, super::super::error::Class::NotReady);
    }

    #[test]
    fn the_install_root_text_uses_forward_slashes() {
        let state = State::new("D:\\fixture\\root");
        assert_eq!(install_root_text(&state), "D:/fixture/root");
    }
}
