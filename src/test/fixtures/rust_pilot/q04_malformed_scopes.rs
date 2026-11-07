//! Malformed on purpose: some scopes stay usable and others do not.

pub struct Healthy {
    pub id: u32,
}

impl Healthy {
    pub fn new(id: u32) -> Self {
        Self { id }
    }
}

pub fn broken_body(values: &[u32]) -> u32 {
    let total = values.iter().sum::<u32>();
    let scaled = total * ;
    scaled
}

pub mod damaged {
    pub fn fine_inside() -> u8 {
        1
    }

    pub struct Partial {
        pub a: u8,
        pub b: ,
    }
}

pub mod intact {
    pub enum Mode {
        Fast,
        Slow,
    }

    pub fn choose(fast: bool) -> Mode {
        if fast { Mode::Fast } else { Mode::Slow }
    }
}

pub trait Shape {
    fn area(&self) -> f64;
}
