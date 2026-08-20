// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

#[cfg(windows)]
#[link(name = "user32")]
extern "system" {
    fn MessageBoxW(
        window: *mut std::ffi::c_void,
        text: *const u16,
        title: *const u16,
        flags: u32,
    ) -> i32;
}

fn main() {
    #[cfg(windows)]
    if !webview2_installed() {
        show_webview2_warning();
        return;
    }
    stella_installer_lib::run()
}

#[cfg(windows)]
fn webview2_installed() -> bool {
    const CLIENT: &str = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}";
    [
        format!(r"HKCU\Software\Microsoft\EdgeUpdate\Clients\{CLIENT}"),
        format!(r"HKLM\Software\Microsoft\EdgeUpdate\Clients\{CLIENT}"),
        format!(r"HKLM\Software\WOW6432Node\Microsoft\EdgeUpdate\Clients\{CLIENT}"),
    ]
    .iter()
    .any(|key| {
        std::process::Command::new("reg.exe")
            .args(["query", key, "/v", "pv"])
            .output()
            .map(|output| output.status.success())
            .unwrap_or(false)
    })
}

#[cfg(windows)]
fn show_webview2_warning() {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;

    let text: Vec<u16> = OsStr::new(
        "Microsoft Edge WebView2 Runtime is missing.\n\nInstall WebView2 Evergreen Runtime, then start Stella again.",
    )
    .encode_wide()
    .chain(std::iter::once(0))
    .collect();
    let title: Vec<u16> = OsStr::new("Stella").encode_wide().chain(std::iter::once(0)).collect();
    unsafe {
        MessageBoxW(std::ptr::null_mut(), text.as_ptr(), title.as_ptr(), 0x10);
    }
}
