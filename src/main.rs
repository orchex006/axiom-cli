//! `axiom-cli` process entry.
//!
//! Thin on purpose: collect argv, hand it to [`cli::run`], exit with the code `cli`
//! returns. All parsing, the exit vocabulary and the `NotReady` contract live in
//! `src/cli.rs`.
//!
//! Invocation is program plus argv. Nothing here builds a shell string, reads a shell
//! profile or mutates `PATH`.

mod cli;
mod update;

fn main() {
    let code = cli::run(std::env::args_os());
    std::process::exit(code);
}
