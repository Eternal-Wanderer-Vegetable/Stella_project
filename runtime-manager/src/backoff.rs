// SPDX-License-Identifier: AGPL-3.0
// Copyright (c) 2026 Stella Project Contributors

//! Bounded restart backoff shared by component supervisors.

use std::time::Duration;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Backoff {
    initial: Duration,
    maximum: Duration,
    factor: f64,
    attempts: u32,
}

impl Backoff {
    pub fn new(initial: Duration, maximum: Duration, factor: f64) -> anyhow::Result<Self> {
        anyhow::ensure!(!initial.is_zero(), "backoff initial must be positive");
        anyhow::ensure!(maximum >= initial, "backoff maximum must be >= initial");
        anyhow::ensure!(factor >= 1.0, "backoff factor must be >= 1");
        Ok(Self {
            initial,
            maximum,
            factor,
            attempts: 0,
        })
    }

    pub fn next_delay(&mut self) -> Duration {
        let multiplier = self.factor.powi(self.attempts.min(31) as i32);
        let seconds = self.initial.as_secs_f64() * multiplier;
        self.attempts = self.attempts.saturating_add(1);
        Duration::from_secs_f64(seconds.min(self.maximum.as_secs_f64()))
    }

    pub fn reset(&mut self) {
        self.attempts = 0;
    }

    pub fn attempts(&self) -> u32 {
        self.attempts
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn delay_is_bounded_and_resettable() {
        let mut backoff =
            Backoff::new(Duration::from_secs(2), Duration::from_secs(5), 2.0).unwrap();
        assert_eq!(backoff.next_delay(), Duration::from_secs(2));
        assert_eq!(backoff.next_delay(), Duration::from_secs(4));
        assert_eq!(backoff.next_delay(), Duration::from_secs(5));
        assert_eq!(backoff.next_delay(), Duration::from_secs(5));
        assert_eq!(backoff.attempts(), 4);
        backoff.reset();
        assert_eq!(backoff.next_delay(), Duration::from_secs(2));
    }
}
