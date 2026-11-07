//! Inventory of every item form the Rust pilot records.

pub mod geometry {
    pub mod units {
        pub type Meters = f64;

        #[derive(Debug, Clone, Copy, PartialEq)]
        pub struct Point {
            pub x: Meters,
            pub y: Meters,
        }

        pub enum Axis {
            Horizontal,
            Vertical,
        }

        #[repr(C)]
        pub union Bits {
            pub word: u32,
            pub halves: [u16; 2],
        }
    }

    pub trait Measure {
        fn length(&self) -> units::Meters;

        fn describe(&self) -> String {
            format!("{:.2}", self.length())
        }
    }

    pub struct Segment {
        pub start: units::Point,
        pub end: units::Point,
    }

    impl Segment {
        pub const fn new(start: units::Point, end: units::Point) -> Self {
            Self { start, end }
        }

        pub fn axis(&self) -> Option<units::Axis> {
            if self.start.y == self.end.y {
                Some(units::Axis::Horizontal)
            } else if self.start.x == self.end.x {
                Some(units::Axis::Vertical)
            } else {
                None
            }
        }
    }

    impl Measure for Segment {
        fn length(&self) -> units::Meters {
            let dx = self.end.x - self.start.x;
            let dy = self.end.y - self.start.y;
            (dx * dx + dy * dy).sqrt()
        }
    }
}

macro_rules! square {
    ($value:expr) => {
        $value * $value
    };
}

pub(crate) async fn fetch_scale(factor: u32) -> u32 {
    square!(factor)
}

pub unsafe fn read_word(bits: &geometry::units::Bits) -> u32 {
    bits.word
}

extern "C" fn exported_callback(code: i32) -> i32 {
    code + 1
}

pub trait Visitor<T: ?Sized> {
    type Output;

    fn visit(&mut self, value: &T) -> Self::Output;
    fn finish(self) -> Vec<Self::Output>
    where
        Self: Sized;
}

pub struct Collector<T> {
    items: Vec<T>,
}

impl<T: Clone> Visitor<T> for Collector<T> {
    type Output = T;

    fn visit(&mut self, value: &T) -> T {
        self.items.push(value.clone());
        value.clone()
    }

    fn finish(self) -> Vec<T> {
        self.items
    }
}

pub struct Unit;

pub struct Pair(pub u8, pub u8);

pub type Callback = fn(i32) -> i32;
