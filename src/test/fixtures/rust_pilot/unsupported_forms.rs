#![no_std]

extern crate alloc;

use alloc::vec::Vec;
use core::{fmt, mem};

pub const LIMIT: usize = 64;
pub static GREETING: &str = "hello";
static mut SCRATCH: [u8; 4] = [0; 4];

extern "C" {
    fn abs(input: i32) -> i32;
    static errno: i32;
}

pub struct Buffer {
    bytes: Vec<u8>,
}

impl Buffer {
    const CHUNK: usize = 16;

    pub fn chunk() -> usize {
        Self::CHUNK
    }
}

impl fmt::Debug for Buffer {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Buffer({})", self.bytes.len())
    }
}

pub fn swap_halves(pair: &mut (u32, u32)) {
    mem::swap(&mut pair.0, &mut pair.1);
}

pub trait Codec {
    const TAG: u8;
    type Error;

    fn encode(&self, out: &mut Vec<u8>) -> Result<(), Self::Error>;
}
