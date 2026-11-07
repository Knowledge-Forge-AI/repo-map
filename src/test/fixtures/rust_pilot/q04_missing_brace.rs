//! The final module is never closed; recovery must not invent a usable scope.

pub fn before() -> bool {
    true
}

pub enum Signal {
    Go,
    Stop,
}

pub mod unfinished {
    pub fn inside() -> bool {
        false
    }

    pub struct Pending;
