//! Build script fixture: parsed as text only, never compiled or run.

use std::env;
use std::path::PathBuf;

fn out_dir() -> PathBuf {
    PathBuf::from(env::var_os("OUT_DIR").expect("OUT_DIR is set by cargo"))
}

fn emit_rerun(paths: &[&str]) {
    for path in paths {
        println!("cargo:rerun-if-changed={path}");
    }
}

fn main() {
    emit_rerun(&["schema/events.txt", "build.rs"]);
    let target = out_dir().join("events.rs");
    std::fs::write(target, "pub const EVENTS: &[&str] = &[];\n").expect("write generated table");
}
