fn main() {
    println!("cargo:rerun-if-env-changed=STELLA_BUILD_PROFILE");
    if let Ok(profile) = std::env::var("STELLA_BUILD_PROFILE") {
        println!("cargo:rustc-env=STELLA_BUILD_PROFILE={profile}");
    }
    tauri_build::build()
}
