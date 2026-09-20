#!/bin/sh
# Invoke-AxiomCliLinuxDistributionTests.sh - Linux x64 / WSL2 distribution legs.
#
# Owner: axiom-cli. Task J-008. POSIX shell only: the harness must be runnable
# with the platform /bin/sh, exactly like the installer it exercises.
#
# It drives installers/linux/Install-AxiomCli.sh and
# installers/linux/Uninstall-AxiomCli.sh through positive, negative and
# boundary legs against a real release set built by
# packaging/linux/Build-ReleaseSet.sh, and asserts the machine-readable
# install-result envelope each leg emits.
#
# Usage:
#   sh tests/linux/Invoke-AxiomCliLinuxDistributionTests.sh \
#       --cli-binary _w10ev/out/axiom-cli --scratch _w10ev/run \
#       [--json-out _w10ev/run/results.json]
#
# Prints one line per leg and a final `RESULT: PASS` or `RESULT: FAIL`, and
# exits 0 on PASS, 1 on FAIL. Nothing outside --scratch is written.

set -u

AC_SELF_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
AC_REPO_ROOT="$(CDPATH= cd -- "$AC_SELF_DIR/../.." && pwd)"

AC_INSTALL_SCRIPT="$AC_REPO_ROOT/installers/linux/Install-AxiomCli.sh"
AC_UNINSTALL_SCRIPT="$AC_REPO_ROOT/installers/linux/Uninstall-AxiomCli.sh"
AC_BUILD_SCRIPT="$AC_REPO_ROOT/packaging/linux/Build-ReleaseSet.sh"
AC_CLI_BINARY=""
AC_SCRATCH=""
AC_JSON_OUT=""

while [ $# -gt 0 ]; do
    case "$1" in
        --install-script)   AC_INSTALL_SCRIPT="$2"; shift 2 ;;
        --uninstall-script) AC_UNINSTALL_SCRIPT="$2"; shift 2 ;;
        --build-script)     AC_BUILD_SCRIPT="$2"; shift 2 ;;
        --cli-binary)       AC_CLI_BINARY="$2"; shift 2 ;;
        --scratch)          AC_SCRATCH="$2"; shift 2 ;;
        --json-out)         AC_JSON_OUT="$2"; shift 2 ;;
        --help|-h)          sed -n '2,20p' "$0"; exit 0 ;;
        *) printf 'unknown option: %s\n' "$1" >&2; exit 2 ;;
    esac
done

[ -n "$AC_CLI_BINARY" ] || { printf 'error: --cli-binary is required\n' >&2; exit 2; }
[ -n "$AC_SCRATCH" ] || { printf 'error: --scratch is required\n' >&2; exit 2; }
[ -f "$AC_CLI_BINARY" ] || { printf 'error: cli binary not found: %s\n' "$AC_CLI_BINARY" >&2; exit 2; }
mkdir -p -- "$AC_SCRATCH" || exit 2
AC_SCRATCH="$(CDPATH= cd -- "$AC_SCRATCH" && pwd)"
AC_ERR_FILE="$AC_SCRATCH/last.stderr"

# ---------------------------------------------------------------------------
# JSON field helpers. The envelope is one line, so first-match greps are exact
# for the keys this harness reads; key order in the envelope is canonical.
# ---------------------------------------------------------------------------

jfield() { # $1 json, $2 key, $3 occurrence (default 1)
    printf '%s' "$1" | grep -o "\"$2\":\"[^\"]*\"" | sed -n "${3:-1}p" | sed 's/^[^:]*:"//; s/"$//'
}
jbool() { # $1 json, $2 key
    printf '%s' "$1" | grep -o -E "\"$2\":(true|false)" | head -n 1 | sed 's/^[^:]*://'
}
jnum() { # $1 json, $2 key
    printf '%s' "$1" | grep -o -E "\"$2\":[0-9][0-9]*" | head -n 1 | sed 's/^[^:]*://'
}
countof() { # $1 json, $2 needle
    printf '%s' "$1" | grep -o -F "$2" | wc -l | tr -d ' '
}

jservice() { # $1 json, $2 key -> string value inside the service_registration object
    printf '%s' "$1" | grep -o '"service_registration":{[^}]*}' | head -n 1 \
        | sed -n "s/.*\"$2\":\"\([^\"]*\)\".*/\1/p"
}

jservice_bool() { # $1 json, $2 key -> boolean value inside service_registration
    printf '%s' "$1" | grep -o '"service_registration":{[^}]*}' | head -n 1 \
        | grep -o -E "\"$2\":(true|false)" | sed 's/^[^:]*://'
}

as_bool() { # $1 1/0 -> true/false
    [ "$1" = "1" ] && printf 'true' || printf 'false'
}

# ---------------------------------------------------------------------------
# Leg framework
# ---------------------------------------------------------------------------

AC_TOTAL=0
AC_FAILURES=0
AC_RESULTS="$AC_SCRATCH/results.tsv"
: > "$AC_RESULTS"

begin_leg() { # $1 name, $2 class
    AC_LEG="$1"; AC_CLASS="$2"; AC_LEG_FAILS=0
    printf '\n== %s (%s)\n' "$AC_LEG" "$AC_CLASS"
}
ok() { printf '   ok   %s\n' "$1"; }
bad() {
    printf '   FAIL %s\n' "$1"
    AC_LEG_FAILS=$((AC_LEG_FAILS + 1))
}
check_eq() { # $1 actual, $2 expected, $3 detail
    if [ "$1" = "$2" ]; then ok "$3 [$1]"; else bad "$3 (expected '$2', got '$1')"; fi
}
check_is() { # $1 truthy(1/0), $2 detail
    if [ "$1" = "1" ]; then ok "$2"; else bad "$2"; fi
}
end_leg() { # $1 expected exit code
    AC_TOTAL=$((AC_TOTAL + 1))
    AC_STATUS="PASS"
    if [ "$AC_LEG_FAILS" != "0" ] || [ "$AC_RUN_EXIT" != "$1" ]; then
        AC_STATUS="FAIL"
        AC_FAILURES=$((AC_FAILURES + 1))
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$AC_LEG" "$AC_CLASS" "$1" "$AC_RUN_EXIT" "$AC_STATUS" "${AC_RUN_OUTCOME:-}" >> "$AC_RESULTS"
    printf '   -> exit %s (expected %s) outcome=%s : %s\n' \
        "$AC_RUN_EXIT" "$1" "${AC_RUN_OUTCOME:-?}" "$AC_STATUS"
}

invoke() { # $1 script, rest args -> AC_RUN_OUT, AC_RUN_ERR, AC_RUN_EXIT
    AC_SCRIPT="$1"; shift
    AC_RUN_OUT="$("$AC_SCRIPT" "$@" 2>"$AC_ERR_FILE")"
    AC_RUN_EXIT=$?
    AC_RUN_ERR="$(cat "$AC_ERR_FILE")"
    AC_RUN_OUTCOME="$(jfield "$AC_RUN_OUT" outcome)"
}

# ---------------------------------------------------------------------------
# Fixtures: real release sets
# ---------------------------------------------------------------------------

AC_MAIN="$AC_SCRATCH/rel-main"
AC_HIGH="$AC_SCRATCH/rel-high"
AC_CORRUPT="$AC_SCRATCH/rel-corrupt"
AC_SERVICE="$AC_SCRATCH/rel-service"

printf '== fixtures: building release sets from %s\n' "$AC_CLI_BINARY"
sh "$AC_BUILD_SCRIPT" --out-dir "$AC_MAIN" --cli-binary "$AC_CLI_BINARY" --release-version 0.0.0-dev >/dev/null \
    || { printf 'fixture build failed\n' >&2; exit 2; }
sh "$AC_BUILD_SCRIPT" --out-dir "$AC_HIGH" --cli-binary "$AC_CLI_BINARY" --release-version 0.9.9 >/dev/null \
    || { printf 'fixture build failed\n' >&2; exit 2; }
sh "$AC_BUILD_SCRIPT" --out-dir "$AC_SERVICE" --cli-binary "$AC_CLI_BINARY" --release-version 0.0.0-dev \
    --service systemd-user --unit-name axiom-graphd.service \
    --unit-exec-start '/usr/bin/true --axiom-user-service' \
    --unit-description 'Axiom graph daemon (declaration fixture)' --unit-owner axiom-graphd >/dev/null \
    || { printf 'fixture build failed\n' >&2; exit 2; }

# Corrupt copy: identical manifest, different artifact bytes.
cp -a "$AC_MAIN" "$AC_CORRUPT"
printf 'corruption' >> "$AC_CORRUPT/axiom-cli"

AC_MAIN_SET="$AC_MAIN/release-set.json"
AC_MAIN_ART_SHA="$(sha256sum -- "$AC_MAIN/axiom-cli" | cut -d' ' -f1)"
AC_MAIN_ART_SIZE="$(wc -c < "$AC_MAIN/axiom-cli" | tr -d ' ')"

# ---------------------------------------------------------------------------
# Host facts (recorded, not guessed)
# ---------------------------------------------------------------------------

AC_HOST_KERNEL="$(uname -srmo 2>/dev/null || uname -a)"
if [ -n "${WSL_DISTRO_NAME:-}" ]; then AC_HOST_WSL_EXPECT=1
elif grep -qi microsoft /proc/version 2>/dev/null; then AC_HOST_WSL_EXPECT=1
else AC_HOST_WSL_EXPECT=0; fi
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ] && systemctl --user show-environment >/dev/null 2>&1; then
    AC_HOST_SYSTEMD_EXPECT=1
else
    AC_HOST_SYSTEMD_EXPECT=0
fi
printf '== host: %s\n' "$AC_HOST_KERNEL"
printf '== host: wsl=%s systemd_user=%s uid=%s\n' "$AC_HOST_WSL_EXPECT" "$AC_HOST_SYSTEMD_EXPECT" "$(id -u)"

present() { [ -e "$1" ] && printf 1 || printf 0; }
absent() { [ -e "$1" ] && printf 0 || printf 1; }
modeof() { stat -c '%a' -- "$1" 2>/dev/null || printf '?'; }
sha_of() { sha256sum -- "$1" | cut -d' ' -f1; }

AC_ENVELOPE_KEYS="schema_version spec_version envelope_kind operation outcome exit_code
status message retryable platform host install_root bin_dir dry_run mutated plan_digest
approved_digest transaction_id interrupted_install_recovered release_set artifacts
unverified_artifacts components refusals path_rule service_registration preserved removed
elevation_required shell limitations generated_at request_id"

# ---------------------------------------------------------------------------
# L01 - install plan only (positive)
# ---------------------------------------------------------------------------

R1="$AC_SCRATCH/root-main"; B1="$AC_SCRATCH/bin-main"; S1="$AC_SCRATCH/state-main"
begin_leg L01-install-plan-only positive
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_MAIN_SET" --install-root "$R1" --bin-dir "$B1" --state-dir "$S1" --plan
check_eq "$(jfield "$AC_RUN_OUT" outcome)" planned "outcome is planned"
check_eq "$(jbool "$AC_RUN_OUT" mutated)" false "mutated is false"
check_eq "$(jbool "$AC_RUN_OUT" dry_run)" true "dry_run is true"
check_eq "$(jfield "$AC_RUN_OUT" platform)" linux-x64 "platform is linux-x64"
check_eq "$(jfield "$AC_RUN_OUT" envelope_kind)" install-result "envelope_kind is install-result"
check_eq "$(jfield "$AC_RUN_OUT" shell)" linux-posix-sh "shell is linux-posix-sh"
check_is "$(absent "$R1")" "no install root was created"
check_eq "$(jfield "$AC_RUN_OUT" sha256 2)" "$AC_MAIN_ART_SHA" "artifact sha256 is the real file digest"
check_eq "$(jfield "$AC_RUN_OUT" sha256)" "$(sha_of "$AC_MAIN_SET")" "release_set sha256 is the manifest digest"
check_eq "$(jfield "$AC_RUN_OUT" arch 2)" x86_64 "artifact arch is recorded as x86_64"
check_eq "$(countof "$AC_RUN_OUT" '"verified":true')" 1 "exactly one verified artifact"
check_eq "$(jfield "$AC_RUN_OUT" check)" "" "no refusal is recorded for a clean plan"
PLAN_DIGEST="$(jfield "$AC_RUN_OUT" plan_digest)"
check_eq "${#PLAN_DIGEST}" 64 "plan digest is a 64-char sha256"
check_is "$(case "$AC_RUN_ERR" in *'"outcome"'*) printf 0 ;; *) printf 1 ;; esac)" "stdout carries the JSON; diagnostics stay on stderr"
end_leg 0

# ---------------------------------------------------------------------------
# L02 - apply without approval (negative)
# ---------------------------------------------------------------------------

begin_leg L02-apply-without-approval negative
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_MAIN_SET" --install-root "$R1" --bin-dir "$B1" --state-dir "$S1" --apply
check_eq "$(jfield "$AC_RUN_OUT" outcome)" refused "outcome is refused"
check_eq "$(jfield "$AC_RUN_OUT" check)" approval-digest "refusal names approval-digest"
check_is "$(absent "$R1")" "nothing was installed"
end_leg 2

# ---------------------------------------------------------------------------
# L03 - apply with a wrong approval digest (negative)
# ---------------------------------------------------------------------------

begin_leg L03-apply-wrong-approval negative
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_MAIN_SET" --install-root "$R1" --bin-dir "$B1" --state-dir "$S1" --apply --approve-digest 0000000000000000000000000000000000000000000000000000000000000000
check_eq "$(jfield "$AC_RUN_OUT" outcome)" refused "outcome is refused"
check_eq "$(jfield "$AC_RUN_OUT" check)" approval-digest "refusal names approval-digest"
check_is "$(absent "$R1")" "nothing was installed"
end_leg 5

# ---------------------------------------------------------------------------
# L04 - apply with the approved plan digest (positive)
# ---------------------------------------------------------------------------

begin_leg L04-apply-approved positive
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_MAIN_SET" --install-root "$R1" --bin-dir "$B1" --state-dir "$S1" --apply --approve-digest "$PLAN_DIGEST"
check_eq "$(jfield "$AC_RUN_OUT" outcome)" installed "outcome is installed"
check_eq "$(jbool "$AC_RUN_OUT" mutated)" true "mutated is true"
check_eq "$(jbool "$AC_RUN_OUT" dry_run)" false "dry_run is false"
check_eq "$(jbool "$AC_RUN_OUT" elevation_required)" false "elevation_required is false"
check_eq "$(jbool "$AC_RUN_OUT" applied)" false "PATH rule was not applied (no hidden PATH mutation)"
check_eq "$(jbool "$AC_RUN_OUT" machine_wide_change)" false "no machine-wide change"
check_is "$(present "$B1/axiom-cli")" "the entrypoint exists under bin-dir"
check_is "$(case "$(test -L "$B1/axiom-cli" && printf 1 || printf 0)" in 1) printf 0 ;; *) printf 1 ;; esac)" "the entrypoint is a real file, not a symlink"
check_eq "$(modeof "$B1/axiom-cli")" 755 "the entrypoint is mode 0755"
check_eq "$(sha_of "$B1/axiom-cli")" "$AC_MAIN_ART_SHA" "the installed entrypoint digest equals the artifact digest"
check_is "$(present "$R1/.axiom-cli-owner")" "the ownership record exists"
check_is "$(present "$S1")" "the per-user state directory exists"
check_is "$(test "$(id -u)" != "0" && printf 1 || printf 0)" "the run was unelevated (uid != 0)"
check_eq "$(countof "$AC_RUN_OUT" '"kind":"staging"')" 0 "no staging recovery was reported for a clean install"
end_leg 0

# ---------------------------------------------------------------------------
# L05 - idempotent re-run (boundary)
# ---------------------------------------------------------------------------

begin_leg L05-install-idempotent-rerun boundary
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_MAIN_SET" --install-root "$R1" --bin-dir "$B1" --state-dir "$S1" --apply --approve-digest "$PLAN_DIGEST"
check_eq "$(jfield "$AC_RUN_OUT" outcome)" already_installed "outcome is already_installed"
check_eq "$(jbool "$AC_RUN_OUT" mutated)" false "an idempotent re-run mutates nothing"
check_eq "$(sha_of "$B1/axiom-cli")" "$AC_MAIN_ART_SHA" "the entrypoint is byte-identical after the re-run"
end_leg 0

# ---------------------------------------------------------------------------
# L06 - corrupted artifact is refused before anything is staged (negative)
# ---------------------------------------------------------------------------

R6="$AC_SCRATCH/root-corrupt"
begin_leg L06-corrupted-artifact-refused negative
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_CORRUPT/release-set.json" --install-root "$R6" --bin-dir "$AC_SCRATCH/bin-corrupt" --state-dir "$AC_SCRATCH/state-corrupt" --plan
check_eq "$(jfield "$AC_RUN_OUT" outcome)" refused "a corrupted artifact is refused"
check_eq "$(jfield "$AC_RUN_OUT" check)" artifact-digest "the refusal names artifact-digest"
check_is "$(absent "$R6")" "nothing was installed from a corrupted release set"
end_leg 9

# ---------------------------------------------------------------------------
# L07 - unowned entrypoint conflict, and --force override (negative/boundary)
# ---------------------------------------------------------------------------

R7="$AC_SCRATCH/root-unowned"; B7="$AC_SCRATCH/bin-unowned"; S7="$AC_SCRATCH/state-unowned"
mkdir -p -- "$B7"; printf 'not an axiom binary' > "$B7/axiom-cli"
begin_leg L07-unowned-entrypoint-conflict negative
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_MAIN_SET" --install-root "$R7" --bin-dir "$B7" --state-dir "$S7" --plan
PD7="$(jfield "$AC_RUN_OUT" plan_digest)"
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_MAIN_SET" --install-root "$R7" --bin-dir "$B7" --state-dir "$S7" --apply --approve-digest "$PD7"
check_eq "$(jfield "$AC_RUN_OUT" outcome)" refused "an unowned entrypoint is a conflict"
check_eq "$(jfield "$AC_RUN_OUT" check)" unowned-entrypoint "the refusal names unowned-entrypoint"
check_is "$(absent "$R7")" "the unowned install root was not created"
end_leg 6

begin_leg L07b-unowned-entrypoint-forced boundary
check_eq "$(cat "$B7/axiom-cli")" 'not an axiom binary' "the unowned file was left untouched by the refused install"
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_MAIN_SET" --install-root "$R7" --bin-dir "$B7" --state-dir "$S7" --apply --approve-digest "$PD7" --force
check_eq "$(jfield "$AC_RUN_OUT" outcome)" installed "--force replaces the unowned file"
check_eq "$(sha_of "$B7/axiom-cli")" "$AC_MAIN_ART_SHA" "the forced install wrote the verified artifact"
end_leg 0

# ---------------------------------------------------------------------------
# L08 - downgrade guard (negative)
# ---------------------------------------------------------------------------

R8="$AC_SCRATCH/root-downgrade"; B8="$AC_SCRATCH/bin-downgrade"; S8="$AC_SCRATCH/state-downgrade"
begin_leg L08-downgrade-refused negative
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_HIGH/release-set.json" --install-root "$R8" --bin-dir "$B8" --state-dir "$S8" --plan
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_HIGH/release-set.json" --install-root "$R8" --bin-dir "$B8" --state-dir "$S8" --apply --approve-digest "$(jfield "$AC_RUN_OUT" plan_digest)"
check_eq "$(jfield "$AC_RUN_OUT" outcome)" installed "the newer release installed first"
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_MAIN_SET" --install-root "$R8" --bin-dir "$B8" --state-dir "$S8" --plan
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_MAIN_SET" --install-root "$R8" --bin-dir "$B8" --state-dir "$S8" --apply --approve-digest "$(jfield "$AC_RUN_OUT" plan_digest)"
check_eq "$(jfield "$AC_RUN_OUT" outcome)" refused "an older release set is refused"
check_eq "$(jfield "$AC_RUN_OUT" check)" no-downgrade "the refusal names no-downgrade"
end_leg 9

# ---------------------------------------------------------------------------
# L09 - interrupted-install recovery (boundary)
# ---------------------------------------------------------------------------

R9="$AC_SCRATCH/root-recovery"; B9="$AC_SCRATCH/bin-recovery"; S9="$AC_SCRATCH/state-recovery"
mkdir -p -- "$R9/.staging"; printf 'abandoned' > "$R9/.staging/axiom-cli"
begin_leg L09-interrupted-install-recovery boundary
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_MAIN_SET" --install-root "$R9" --bin-dir "$B9" --state-dir "$S9" --plan
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_MAIN_SET" --install-root "$R9" --bin-dir "$B9" --state-dir "$S9" --apply --approve-digest "$(jfield "$AC_RUN_OUT" plan_digest)"
check_eq "$(jfield "$AC_RUN_OUT" outcome)" recovered_and_installed "outcome is recovered_and_installed"
check_eq "$(jbool "$AC_RUN_OUT" interrupted_install_recovered)" true "interrupted_install_recovered is true"
check_eq "$(countof "$AC_RUN_OUT" '"kind":"staging"')" 1 "the abandoned staging directory is reported as removed"
check_is "$(absent "$R9/.staging")" "the abandoned staging directory is gone"
check_eq "$(sha_of "$B9/axiom-cli")" "$AC_MAIN_ART_SHA" "the recovered install placed the verified artifact"
end_leg 0

# ---------------------------------------------------------------------------
# L10 - transaction lock held (negative)
# ---------------------------------------------------------------------------

R10="$AC_SCRATCH/root-lock"; B10="$AC_SCRATCH/bin-lock"; S10="$AC_SCRATCH/state-lock"
begin_leg L10-transaction-lock-held negative
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_MAIN_SET" --install-root "$R10" --bin-dir "$B10" --state-dir "$S10" --plan
PD10="$(jfield "$AC_RUN_OUT" plan_digest)"
mkdir -p -- "$R10/.lock"; printf 'other-txn\n' > "$R10/.lock/owner"
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_MAIN_SET" --install-root "$R10" --bin-dir "$B10" --state-dir "$S10" --apply --approve-digest "$PD10"
check_eq "$(jfield "$AC_RUN_OUT" outcome)" refused "a held lock refuses the transaction"
check_eq "$(jfield "$AC_RUN_OUT" check)" transaction-lock "the refusal names transaction-lock"
check_eq "$(jbool "$AC_RUN_OUT" retryable)" true "the refusal is marked retryable"
check_is "$(absent "$B10/axiom-cli")" "no entrypoint was written while the lock was held"
end_leg 10

skip_leg() { # $1 reason
    AC_TOTAL=$((AC_TOTAL + 1))
    printf '   SKIP %s\n' "$1"
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$AC_LEG" "$AC_CLASS" "n/a" "n/a" "SKIP" "$1" >> "$AC_RESULTS"
}

# ---------------------------------------------------------------------------
# L11 - uninstall plan only (positive)
# ---------------------------------------------------------------------------

begin_leg L11-uninstall-plan-only positive
invoke "$AC_UNINSTALL_SCRIPT" --install-root "$R1" --bin-dir "$B1" --state-dir "$S1" --plan
check_eq "$(jfield "$AC_RUN_OUT" operation)" uninstall "operation is uninstall"
check_eq "$(jfield "$AC_RUN_OUT" outcome)" planned "outcome is planned"
check_eq "$(jbool "$AC_RUN_OUT" mutated)" false "a plan mutates nothing"
check_is "$(present "$B1/axiom-cli")" "the installed entrypoint is still present after a plan"
end_leg 0

# ---------------------------------------------------------------------------
# L12 - uninstall with a wrong approval digest (negative)
# ---------------------------------------------------------------------------

begin_leg L12-uninstall-wrong-approval negative
invoke "$AC_UNINSTALL_SCRIPT" --install-root "$R1" --bin-dir "$B1" --state-dir "$S1" --apply --approve-digest 1111111111111111111111111111111111111111111111111111111111111111
check_eq "$(jfield "$AC_RUN_OUT" outcome)" refused "uninstall refuses a wrong approval"
check_is "$(present "$B1/axiom-cli")" "the entrypoint survived the refused uninstall"
end_leg 5

# ---------------------------------------------------------------------------
# L13 - uninstall approved preserves state (boundary)
# ---------------------------------------------------------------------------

begin_leg L13-uninstall-approved boundary
invoke "$AC_UNINSTALL_SCRIPT" --install-root "$R1" --bin-dir "$B1" --state-dir "$S1" --plan
invoke "$AC_UNINSTALL_SCRIPT" --install-root "$R1" --bin-dir "$B1" --state-dir "$S1" --apply --approve-digest "$(jfield "$AC_RUN_OUT" plan_digest)"
check_eq "$(jfield "$AC_RUN_OUT" outcome)" removed "outcome is removed"
check_is "$(absent "$B1/axiom-cli")" "the entrypoint was removed"
check_is "$(absent "$R1/.axiom-cli-owner")" "the ownership record was removed"
check_is "$(present "$S1")" "per-user state survives a plain uninstall"
check_eq "$(countof "$AC_RUN_OUT" '"kind":"executable"')" 1 "the removal names the executable"
check_is "$(case "$AC_RUN_OUT" in *preserved*"$S1"*) printf 1 ;; *) printf 0 ;; esac)" "the state directory is listed as preserved"
end_leg 0

# ---------------------------------------------------------------------------
# L14 - uninstall when nothing is installed (negative)
# ---------------------------------------------------------------------------

begin_leg L14-uninstall-when-absent negative
invoke "$AC_UNINSTALL_SCRIPT" --install-root "$AC_SCRATCH/root-never" --bin-dir "$AC_SCRATCH/bin-never" --state-dir "$AC_SCRATCH/state-never" --plan
check_eq "$(jfield "$AC_RUN_OUT" outcome)" not_removed "outcome is not_removed"
end_leg 3

# ---------------------------------------------------------------------------
# L15 - purge with an approved digest removes the install root (boundary)
# ---------------------------------------------------------------------------

R15="$AC_SCRATCH/root-purge"; B15="$AC_SCRATCH/bin-purge"; S15="$AC_SCRATCH/state-purge"
begin_leg L15-purge-approved boundary
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_MAIN_SET" --install-root "$R15" --bin-dir "$B15" --state-dir "$S15" --plan
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_MAIN_SET" --install-root "$R15" --bin-dir "$B15" --state-dir "$S15" --apply --approve-digest "$(jfield "$AC_RUN_OUT" plan_digest)"
check_eq "$(jfield "$AC_RUN_OUT" outcome)" installed "the purge fixture installed"
invoke "$AC_UNINSTALL_SCRIPT" --install-root "$R15" --bin-dir "$B15" --state-dir "$S15" --plan --purge
invoke "$AC_UNINSTALL_SCRIPT" --install-root "$R15" --bin-dir "$B15" --state-dir "$S15" --apply --purge --approve-digest "$(jfield "$AC_RUN_OUT" plan_digest)"
check_eq "$(jfield "$AC_RUN_OUT" outcome)" removed "purge reports removed"
check_is "$(absent "$S15")" "--purge removed the state directory"
check_is "$(absent "$R15")" "--purge removed the install root"
check_is "$(case "$AC_RUN_OUT" in *'"kind":"state-directory"'*) printf 1 ;; *) printf 0 ;; esac)" "the removal names the state directory"
end_leg 0

# ---------------------------------------------------------------------------
# L16 - systemd user service: used when available, degraded explicitly when not
# ---------------------------------------------------------------------------

R16="$AC_SCRATCH/root-service"; B16="$AC_SCRATCH/bin-service"; S16="$AC_SCRATCH/state-service"
begin_leg L16a-service-auto-degrades-or-registers boundary
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_SERVICE/release-set.json" --install-root "$R16" --bin-dir "$B16" --state-dir "$S16" --plan
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_SERVICE/release-set.json" --install-root "$R16" --bin-dir "$B16" --state-dir "$S16" --apply --approve-digest "$(jfield "$AC_RUN_OUT" plan_digest)"
    check_eq "$(jfield "$AC_RUN_OUT" outcome)" installed "the install still succeeds with a declared service"
    if [ "$AC_HOST_SYSTEMD_EXPECT" = "1" ]; then
    check_eq "$(jservice "$AC_RUN_OUT" kind)" systemd-user "a reachable user manager registers the unit"
    check_eq "$(jservice_bool "$AC_RUN_OUT" registered)" true "the unit is reported registered"
    else
    check_eq "$(jservice "$AC_RUN_OUT" kind)" none "no user manager means no registration"
    check_eq "$(jservice_bool "$AC_RUN_OUT" registered)" false "registered stays false when there is no user manager"
    check_is "$(case "$(jservice "$AC_RUN_OUT" reason)" in *systemd*) printf 1 ;; *) printf 0 ;; esac)" "the degradation reason names systemd"
    check_is "$(case "$(jservice "$AC_RUN_OUT" reason)" in *'not the running init'*|*'does not answer'*) printf 1 ;; *) printf 0 ;; esac)" "the reason states the exact failing precondition"
    fi
end_leg 0

begin_leg L16b-explicit-systemd-user-request boundary
# The plan digest binds the service mode, so the plan must be taken with the
# same --service value that --apply will use.
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_SERVICE/release-set.json" --install-root "$AC_SCRATCH/root-service2" --bin-dir "$AC_SCRATCH/bin-service2" --state-dir "$AC_SCRATCH/state-service2" --service systemd-user --plan
PD16B="$(jfield "$AC_RUN_OUT" plan_digest)"
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_SERVICE/release-set.json" --install-root "$AC_SCRATCH/root-service2" --bin-dir "$AC_SCRATCH/bin-service2" --state-dir "$AC_SCRATCH/state-service2" --apply --approve-digest "$PD16B" --service systemd-user
if [ "$AC_HOST_SYSTEMD_EXPECT" = "1" ]; then
    check_eq "$(jservice "$AC_RUN_OUT" kind)" systemd-user "an explicit request registers when the manager is reachable"
    check_eq "$(jservice_bool "$AC_RUN_OUT" registered)" true "registered is true"
    end_leg 0
else
    check_eq "$(jfield "$AC_RUN_OUT" outcome)" refused "an explicit request is refused, not silently skipped, when there is no user manager"
    check_eq "$(jfield "$AC_RUN_OUT" check)" systemd-user-available "the refusal names systemd-user-available"
    check_is "$(absent "$AC_SCRATCH/bin-service2/axiom-cli")" "the not-ready install rolled its entrypoint back"
    end_leg 4
fi

begin_leg L16c-generated-unit-is-removed boundary
if [ "$AC_HOST_SYSTEMD_EXPECT" = "1" ]; then
    invoke "$AC_UNINSTALL_SCRIPT" --install-root "$AC_SCRATCH/root-service2" --bin-dir "$AC_SCRATCH/bin-service2" --state-dir "$AC_SCRATCH/state-service2" --plan
    invoke "$AC_UNINSTALL_SCRIPT" --install-root "$AC_SCRATCH/root-service2" --bin-dir "$AC_SCRATCH/bin-service2" --state-dir "$AC_SCRATCH/state-service2" --apply --approve-digest "$(jfield "$AC_RUN_OUT" plan_digest)"
    check_eq "$(jfield "$AC_RUN_OUT" outcome)" removed "uninstall reports removed"
    check_is "$(case "$AC_RUN_OUT" in *'"kind":"service-registration"'*) printf 1 ;; *) printf 0 ;; esac)" "the generated unit is named in removed"
    check_is "$(absent "$HOME/.config/systemd/user/axiom-graphd.service")" "the generated unit file is gone"
    AC_RUN_EXIT=0
    end_leg 0
else
    AC_RUN_EXIT=0
    skip_leg "this host has no systemd user manager, so no unit was generated and there is nothing to remove (L16b already proved the explicit request is refused, not faked)"
fi

# ---------------------------------------------------------------------------
# L17 - the documented path requires no Bash, Docker or elevation
# ---------------------------------------------------------------------------

begin_leg L17-no-forbidden-dependency boundary
AC_RUN_EXIT=0; AC_RUN_OUTCOME="static"
AC_DASH_OK=1; command -v dash >/dev/null 2>&1 || AC_DASH_OK=0
for ac_f in "$AC_INSTALL_SCRIPT" "$AC_UNINSTALL_SCRIPT" "$AC_BUILD_SCRIPT" "$AC_REPO_ROOT/installers/linux/AxiomCli.Linux.Common.sh"; do
    ac_n="$(basename -- "$ac_f")"
    check_eq "$(head -n 1 "$ac_f")" '#!/bin/sh' "$ac_n shebang is /bin/sh"
    check_eq "$(grep -c -E '^[[:space:]]*(sudo|doas|su)[[:space:]]' "$ac_f")" 0 "$ac_n never invokes sudo/doas/su"
    check_eq "$(grep -c -E '^[[:space:]]*(docker|curl|wget|bash)[[:space:]]' "$ac_f")" 0 "$ac_n never invokes docker/curl/wget/bash"
    check_eq "$(grep -c -F 'ln -s' "$ac_f")" 0 "$ac_n never creates a symlink"
    if [ "$AC_DASH_OK" = "1" ]; then
        check_is "$(dash -n "$ac_f" >/dev/null 2>&1 && printf 1 || printf 0)" "$ac_n parses under dash (no bashism)"
    fi
done
check_is "$(test "$(id -u)" != "0" && printf 1 || printf 0)" "the whole harness ran unelevated"
end_leg 0

# ---------------------------------------------------------------------------
# L18 - host facts are recorded, not guessed
# ---------------------------------------------------------------------------

begin_leg L18-host-facts-recorded positive
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_MAIN_SET" --install-root "$AC_SCRATCH/root-host" --bin-dir "$AC_SCRATCH/bin-host" --state-dir "$AC_SCRATCH/state-host" --plan
check_eq "$(jfield "$AC_RUN_OUT" os)" linux "host.os is linux"
check_eq "$(jfield "$AC_RUN_OUT" arch)" x86_64 "host.arch is x86_64"
check_eq "$(jbool "$AC_RUN_OUT" wsl)" "$(as_bool "$AC_HOST_WSL_EXPECT")" "host.wsl matches the real environment"
check_eq "$(jbool "$AC_RUN_OUT" systemd_user_available)" "$(as_bool "$AC_HOST_SYSTEMD_EXPECT")" "host.systemd_user_available matches reality"
check_is "$(test -n "$(jfield "$AC_RUN_OUT" kernel)" && printf 1 || printf 0)" "host.kernel is recorded"
check_is "$(case "$(jfield "$AC_RUN_OUT" libc)" in *glibc*) printf 1 ;; *) printf 0 ;; esac)" "host.libc reports glibc"
check_is "$(test -n "$(jfield "$AC_RUN_OUT" distro_id)" && printf 1 || printf 0)" "host.distro_id is recorded"
check_is "$(test -n "$(jfield "$AC_RUN_OUT" distro_version)" && printf 1 || printf 0)" "host.distro_version is recorded"
if [ "$AC_HOST_WSL_EXPECT" = "1" ]; then
    check_is "$(test -n "$(jfield "$AC_RUN_OUT" wsl_distro_name)" && printf 1 || printf 0)" "host.wsl_distro_name names the distro under WSL"
    check_eq "$(jfield "$AC_RUN_OUT" platform)" linux-x64 "a WSL2 run reports platform linux-x64, never windows-x64"
fi
end_leg 0

# ---------------------------------------------------------------------------
# L19 - the envelope carries the canonical key set
# ---------------------------------------------------------------------------

begin_leg L19-envelope-canonical-keys positive
AC_RUN_EXIT=0; AC_RUN_OUTCOME="shape"
AC_MISSING=""
for ac_k in $AC_ENVELOPE_KEYS; do
    case "$AC_RUN_OUT" in
        *"\"$ac_k\":"*) ;;
        *) AC_MISSING="$AC_MISSING $ac_k" ;;
    esac
done
check_eq "$AC_MISSING" "" "every canonical install-result key is present"
check_eq "$(jfield "$AC_RUN_OUT" spec_version)" 2.0.0-draft.1 "spec_version is the pinned draft"
check_eq "$(jnum "$AC_RUN_OUT" schema_version)" 1 "schema_version is 1"
end_leg 0

# ---------------------------------------------------------------------------
# L20 - the installed entrypoint actually runs
# ---------------------------------------------------------------------------

R20="$AC_SCRATCH/root-run"; B20="$AC_SCRATCH/bin-run"; S20="$AC_SCRATCH/state-run"
begin_leg L20-installed-entrypoint-runs positive
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_MAIN_SET" --install-root "$R20" --bin-dir "$B20" --state-dir "$S20" --plan
invoke "$AC_INSTALL_SCRIPT" --release-set "$AC_MAIN_SET" --install-root "$R20" --bin-dir "$B20" --state-dir "$S20" --apply --approve-digest "$(jfield "$AC_RUN_OUT" plan_digest)"
check_eq "$(jfield "$AC_RUN_OUT" outcome)" installed "the run fixture installed"
AC_HELP_OUT="$("$B20/axiom-cli" --help 2>&1)"; AC_HELP_EXIT=$?
check_eq "$AC_HELP_EXIT" 0 "the installed entrypoint answers --help with exit 0"
check_is "$(case "$AC_HELP_OUT" in *axiom-cli*) printf 1 ;; *) printf 0 ;; esac)" "the installed entrypoint identifies itself"
AC_VER_OUT="$("$B20/axiom-cli" version 2>&1)"; AC_VER_EXIT=$?
check_eq "$AC_VER_EXIT" 4 "an unbuilt verb answers NotReady with exit 4 (never a faked success)"
check_is "$(case "$AC_VER_OUT" in *NotReady*) printf 1 ;; *) printf 0 ;; esac)" "the NotReady reason is stated"
end_leg 0

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

printf '\n%-40s %-10s %6s %6s %6s %s\n' leg class expect actual status outcome
awk -F'\t' 'NF>=5 {printf "%-40s %-10s %6s %6s %6s %s\n", $1, $2, $3, $4, $5, $6}' "$AC_RESULTS"
AC_SKIPS="$(awk -F'\t' '$5=="SKIP"{n++} END{print n+0}' "$AC_RESULTS")"
printf '\nlegs: %s   failures: %s   skipped: %s\n' "$AC_TOTAL" "$AC_FAILURES" "$AC_SKIPS"

if [ -n "$AC_JSON_OUT" ]; then
    {
        printf '{\n'
        printf '  "harness": "tests/linux/Invoke-AxiomCliLinuxDistributionTests.sh",\n'
        printf '  "task": "J-008",\n'
        printf '  "total_legs": %s,\n' "$AC_TOTAL"
        printf '  "failures": %s,\n' "$AC_FAILURES"
        printf '  "skipped": %s,\n' "$AC_SKIPS"
        printf '  "kernel": "%s",\n' "$(printf '%s' "$AC_HOST_KERNEL" | sed 's/"/\\"/g')"
        printf '  "wsl": %s,\n' "$([ "$AC_HOST_WSL_EXPECT" = 1 ] && printf true || printf false)"
        printf '  "systemd_user_available": %s,\n' "$([ "$AC_HOST_SYSTEMD_EXPECT" = 1 ] && printf true || printf false)"
        printf '  "artifact_sha256": "%s",\n' "$AC_MAIN_ART_SHA"
        printf '  "artifact_size_bytes": %s\n' "$AC_MAIN_ART_SIZE"
        printf '}\n'
    } > "$AC_JSON_OUT"
fi

if [ "$AC_FAILURES" != "0" ]; then
    printf 'RESULT: FAIL (%s failing leg/assertion)\n' "$AC_FAILURES"
    exit 1
fi
printf 'RESULT: PASS (%s legs met their expected exit code and every assertion held)\n' "$AC_TOTAL"
exit 0
