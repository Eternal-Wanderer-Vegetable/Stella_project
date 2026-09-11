pub fn unavailable() -> Result<(), String> {
    Err("Rust promotion is not enabled until the transaction parity gate passes".to_string())
}
