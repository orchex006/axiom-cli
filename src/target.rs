//! Delivery target identity and release tier.
//!
//! The distribution contract (`axiom-specs/contracts/axiom-cli-distribution-contract.md`
//! section 3, machine-readable in `compatibility/platform-matrix.json`) is the canonical source
//! of the platform table and the tiers. This module is the local, read-only mirror of the parts
//! a running CLI needs to answer "which target am I, and what is it allowed to claim?". It never
//! invents a platform: a host that the contract does not declare is reported as undeclared
//! instead of being folded into the nearest known target.

/// A delivery platform declared by the distribution contract.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct DeliveryPlatform {
    /// Canonical target id, for example `macos-x64`.
    pub id: &'static str,
    /// Operating system, as the contract names it.
    pub os: &'static str,
    /// Architecture, as the contract names it.
    pub arch: &'static str,
    /// Artifact class id.
    pub artifact_class: &'static str,
}

/// Release tier of a delivery platform.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Tier {
    /// Delivered first and required to carry native evidence.
    FinishFirst,
    /// Design complete; certified only once a native run is recorded.
    DesignCompleteTestLater,
}

impl Tier {
    /// Canonical token, matching the platform matrix.
    pub fn name(self) -> &'static str {
        match self {
            Tier::FinishFirst => "finish-first",
            Tier::DesignCompleteTestLater => "design-complete/test-later",
        }
    }
}

/// Every delivery platform of the contract, in platform-matrix order.
pub const DELIVERY_PLATFORMS: &[DeliveryPlatform] = &[
    DeliveryPlatform {
        id: "windows-x64",
        os: "windows",
        arch: "x86_64",
        artifact_class: "per-user-installer",
    },
    DeliveryPlatform {
        id: "macos-x64",
        os: "macos",
        arch: "x86_64",
        artifact_class: "per-user-installer",
    },
    DeliveryPlatform {
        id: "container-linux-x64",
        os: "container",
        arch: "x86_64",
        artifact_class: "oci-image",
    },
    DeliveryPlatform {
        id: "linux-x64",
        os: "linux",
        arch: "x86_64",
        artifact_class: "per-user-installer",
    },
    DeliveryPlatform {
        id: "macos-arm64",
        os: "macos",
        arch: "aarch64",
        artifact_class: "per-user-installer",
    },
    DeliveryPlatform {
        id: "wsl2-linux-x64",
        os: "wsl2",
        arch: "x86_64",
        artifact_class: "per-user-installer",
    },
];

/// The finish-first tier, in contract order.
pub const FINISH_FIRST: &[&str] = &["windows-x64", "macos-x64", "container-linux-x64"];

/// The design-complete / test-later tier, in contract order.
pub const DESIGN_COMPLETE_TEST_LATER: &[&str] = &["linux-x64", "macos-arm64", "wsl2-linux-x64"];

/// The native target a host's evidence is recorded against, when it differs from the host id.
///
/// The WSL2 lane is one case: it runs the Linux installer, so its evidence belongs to
/// `linux-x64`. It is never recorded as Windows evidence.
pub fn evidence_target_for(host_id: &str) -> &str {
    match host_id {
        "wsl2-linux-x64" => "linux-x64",
        other => other,
    }
}

/// The delivery platform for a target id, when the contract declares it.
pub fn platform(id: &str) -> Option<&'static DeliveryPlatform> {
    DELIVERY_PLATFORMS.iter().find(|item| item.id == id)
}

/// The release tier of a target id, when the contract declares it.
pub fn tier(id: &str) -> Option<Tier> {
    if FINISH_FIRST.contains(&id) {
        Some(Tier::FinishFirst)
    } else if DESIGN_COMPLETE_TEST_LATER.contains(&id) {
        Some(Tier::DesignCompleteTestLater)
    } else {
        None
    }
}

/// The compiled-in host id of this process.
///
/// The mapping is by operating system *and* architecture on purpose: `macos-x64` and
/// `macos-arm64` are different delivery platforms with different tiers, so an architecture-blind
/// answer would misreport the host. An undeclared combination returns `None`; the caller reports
/// it as undeclared rather than guessing.
pub fn host_id() -> Option<&'static str> {
    host_id_for(std::env::consts::OS, std::env::consts::ARCH)
}

/// Map an operating system and architecture pair to a delivery target id.
///
/// Split out of [`host_id`] so the *undeclared host* branch is reachable from a test on any
/// machine. That branch is what makes `install` answer the incompatible exit code instead of
/// folding an unknown host into the nearest known target, and it is exactly the branch a
/// compiled-in `host_id()` can only exercise by running on hardware nobody has.
///
/// Two declared platforms are deliberately absent, because they are not detected from the
/// compiled-in platform but chosen by the distribution channel:
///
/// * `container-linux-x64` - the OCI image lane, which runs the Linux path inside a container;
/// * `wsl2-linux-x64` - the WSL2 lane, which is a Windows host running the Linux installer and
///   records its evidence against `linux-x64` (see [`evidence_target_for`]).
pub fn host_id_for(os: &str, arch: &str) -> Option<&'static str> {
    match (os, arch) {
        ("windows", "x86_64") => Some("windows-x64"),
        ("macos", "x86_64") => Some("macos-x64"),
        ("macos", "aarch64") => Some("macos-arm64"),
        ("linux", "x86_64") => Some("linux-x64"),
        _ => None,
    }
}

/// A human-readable description of the running host, including an undeclared combination.
pub fn host_description() -> String {
    format!("{}/{}", std::env::consts::OS, std::env::consts::ARCH)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_delivery_platform_has_a_tier() {
        for item in DELIVERY_PLATFORMS {
            assert!(
                tier(item.id).is_some(),
                "{} is declared but has no tier",
                item.id
            );
        }
    }

    #[test]
    fn the_tier_sets_partition_the_platform_table() {
        let mut counted = 0usize;
        for id in FINISH_FIRST.iter().chain(DESIGN_COMPLETE_TEST_LATER.iter()) {
            assert!(platform(id).is_some(), "{id} is in a tier but not declared");
            counted += 1;
        }
        assert_eq!(counted, DELIVERY_PLATFORMS.len());
    }

    #[test]
    fn the_finish_first_set_matches_the_contract() {
        assert_eq!(
            FINISH_FIRST,
            &["windows-x64", "macos-x64", "container-linux-x64"]
        );
    }

    #[test]
    fn the_wsl2_lane_records_linux_evidence() {
        assert_eq!(evidence_target_for("wsl2-linux-x64"), "linux-x64");
        assert_eq!(evidence_target_for("macos-x64"), "macos-x64");
    }

    #[test]
    fn the_host_id_agrees_with_the_compiled_platform() {
        let expected = match (std::env::consts::OS, std::env::consts::ARCH) {
            ("macos", "x86_64") => Some("macos-x64"),
            ("macos", "aarch64") => Some("macos-arm64"),
            ("linux", "x86_64") => Some("linux-x64"),
            ("windows", "x86_64") => Some("windows-x64"),
            _ => None,
        };
        assert_eq!(host_id(), expected);
    }

    #[test]
    fn an_undeclared_host_is_never_folded_into_a_known_target() {
        // The branch behind the incompatible exit code: the CLI must report "undeclared" rather
        // than claim the nearest platform. Without this seam the branch is only reachable by
        // running the binary on hardware the contract does not declare.
        for (os, arch) in [
            ("linux", "aarch64"),
            ("windows", "aarch64"),
            ("freebsd", "x86_64"),
            ("macos", "x86"),
            ("", ""),
        ] {
            assert_eq!(
                host_id_for(os, arch),
                None,
                "{os}/{arch} is not a declared delivery platform, so it must not resolve"
            );
        }
    }

    #[test]
    fn every_host_a_running_cli_can_report_is_a_declared_platform() {
        for (os, arch) in [
            ("windows", "x86_64"),
            ("macos", "x86_64"),
            ("macos", "aarch64"),
            ("linux", "x86_64"),
        ] {
            let id = host_id_for(os, arch).expect("this pair is declared and must resolve");
            assert!(
                platform(id).is_some(),
                "{id} resolved from {os}/{arch} but the platform table does not declare it"
            );
            assert!(tier(id).is_some(), "{id} resolved but carries no tier");
        }
    }

    #[test]
    fn only_the_channel_chosen_platforms_are_absent_from_host_detection() {
        // Locks the intent documented on `host_id_for`: the two platforms a running CLI never
        // detects are the container lane and the WSL2 lane, and nothing else may quietly drop out.
        let detectable: Vec<&str> = DELIVERY_PLATFORMS
            .iter()
            .map(|item| item.id)
            .filter(|id| {
                [
                    ("windows", "x86_64"),
                    ("macos", "x86_64"),
                    ("macos", "aarch64"),
                    ("linux", "x86_64"),
                ]
                .iter()
                .any(|(os, arch)| host_id_for(os, arch) == Some(id))
            })
            .collect();
        let absent: Vec<&str> = DELIVERY_PLATFORMS
            .iter()
            .map(|item| item.id)
            .filter(|id| !detectable.contains(id))
            .collect();
        assert_eq!(absent, vec!["container-linux-x64", "wsl2-linux-x64"]);
    }

    #[test]
    fn the_detected_host_rows_are_exactly_the_engine_bundle_hosts() {
        // `axiom-graphd` owns this list: `crates/axiom/src/install/plan.rs`, `HOSTS`, which is the
        // vocabulary a bundle manifest's `host` field is validated against. The CLI mirrors it here
        // as a literal so a divergence fails in this repository, instead of surfacing only as an
        // opaque refusal at the moment a bundle the CLI stamped is handed to the engine.
        //
        // The container and WSL2 rows are absent from both lists on purpose: they are chosen by the
        // distribution channel, never detected from the compiled-in platform.
        const ENGINE_BUNDLE_HOSTS: [&str; 4] =
            ["windows-x64", "linux-x64", "macos-arm64", "macos-x64"];
        let detected: Vec<&str> = [
            ("windows", "x86_64"),
            ("macos", "x86_64"),
            ("macos", "aarch64"),
            ("linux", "x86_64"),
        ]
        .into_iter()
        .map(|(os, arch)| host_id_for(os, arch).expect("a declared pair must resolve"))
        .collect();
        for host in ENGINE_BUNDLE_HOSTS {
            assert!(
                detected.contains(&host),
                "{host} is declared by the engine but no host detection reaches it"
            );
        }
        assert_eq!(
            detected.len(),
            ENGINE_BUNDLE_HOSTS.len(),
            "the CLI must not detect a host the engine's bundle manifest does not declare: {detected:?}"
        );
    }
}
