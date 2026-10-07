//! Refuse to install, update or uninstall elevated (distribution contract section 12, ADR-0033).
//!
//! Axiom installs per user. An elevated run would write a per-user root and PATH as Administrator
//! or root, leaving files the real user cannot update or remove, so the mutating verbs refuse it
//! before planning anything. Windows asks the process token whether it is elevated (a member of
//! Administrators running with a filtered UAC token is not); POSIX checks the effective user id.

use crate::update::error::{Class, Refusal};

/// `Some(refusal)` when this process runs elevated.
pub fn refusal() -> Option<Refusal> {
    if std::env::var_os(ALLOW_TEST_ENV).is_some() {
        return None;
    }
    is_elevated().then(|| {
        Refusal::new(
            Class::Conflict,
            "elevated_refused",
            if cfg!(windows) {
                "refusing to run elevated: Axiom installs per user. Re-run from a normal \
                 (non-Administrator) terminal; nothing was changed"
            } else {
                "refusing to run as root: Axiom installs per user. Re-run as your normal user \
                 without sudo; nothing was changed"
            },
        )
    })
}

/// Test seam for CI images that only offer a root user; never set it for a real install.
pub const ALLOW_TEST_ENV: &str = "AXIOM_CLI_TEST_ALLOW_ELEVATED";

#[cfg(windows)]
fn is_elevated() -> bool {
    use std::ffi::c_void;
    #[link(name = "advapi32")]
    extern "system" {
        fn OpenProcessToken(process: *mut c_void, access: u32, token: *mut *mut c_void) -> i32;
        fn GetTokenInformation(
            token: *mut c_void,
            class: u32,
            info: *mut c_void,
            length: u32,
            returned: *mut u32,
        ) -> i32;
    }
    #[link(name = "kernel32")]
    extern "system" {
        fn GetCurrentProcess() -> *mut c_void;
        fn CloseHandle(handle: *mut c_void) -> i32;
    }
    const TOKEN_QUERY: u32 = 0x0008;
    const TOKEN_ELEVATION: u32 = 20;
    let mut token: *mut c_void = std::ptr::null_mut();
    // SAFETY: plain Win32 calls with a valid out-pointer; the handle is closed below.
    unsafe {
        if OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token) == 0 {
            return false;
        }
        let mut elevated: u32 = 0;
        let mut returned: u32 = 0;
        let ok = GetTokenInformation(
            token,
            TOKEN_ELEVATION,
            &mut elevated as *mut u32 as *mut c_void,
            std::mem::size_of::<u32>() as u32,
            &mut returned,
        );
        CloseHandle(token);
        ok != 0 && elevated != 0
    }
}

#[cfg(unix)]
fn is_elevated() -> bool {
    extern "C" {
        fn geteuid() -> u32;
    }
    // SAFETY: geteuid has no preconditions.
    unsafe { geteuid() == 0 }
}

#[cfg(not(any(windows, unix)))]
fn is_elevated() -> bool {
    false
}

#[cfg(test)]
mod tests {
    #[test]
    fn the_test_process_is_not_elevated_or_the_seam_is_explicit() {
        // Developer and CI runs are expected to be unelevated; the check itself must not panic.
        let _ = super::is_elevated();
        std::env::set_var(super::ALLOW_TEST_ENV, "1");
        assert!(super::refusal().is_none());
        std::env::remove_var(super::ALLOW_TEST_ENV);
    }
}
