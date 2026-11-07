#![allow(dead_code)]
#![cfg_attr(docsrs, feature(doc_cfg))]

//! Conditional alternatives, derives and item-position macros.

mod platform;

#[cfg(test)]
mod tests;

#[cfg(unix)]
pub fn separator() -> char {
    '/'
}

#[cfg(windows)]
pub fn separator() -> char {
    '\\'
}

#[cfg_attr(feature = "serde", derive(serde::Serialize))]
#[derive(Debug, Default)]
pub struct Options {
    pub depth: usize,
}

thread_local! {
    static COUNTER: std::cell::Cell<u32> = std::cell::Cell::new(0);
}

bitflags_like!(Permissions, u8);

pub mod backends {
    #[cfg(feature = "fast")]
    pub struct Engine {
        pub lanes: u16,
    }

    #[cfg(not(feature = "fast"))]
    pub struct Engine {
        pub lanes: u8,
    }

    register_backend!(Engine);

    #[cfg(feature = "fast")]
    impl Engine {
        pub fn lanes(&self) -> u32 {
            u32::from(self.lanes)
        }
    }
}

#[macro_export]
macro_rules! ensure {
    ($cond:expr, $msg:literal) => {
        if !$cond {
            panic!($msg);
        }
    };
}

#[allow(unused)]
#[inline]
pub(crate) fn helper_with_attributes() {}

#[cfg(any())]
pub enum Never {}
