#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! FreeLLM Studio — desktop shell around the local FreeLLM gateway.
//!
//! On startup we spawn the bundled gateway sidecar (a PyInstaller build of
//! `freellm_gateway.desktop_entry`) with tokens persisted in app data, then open a
//! webview that shows a splash page. The splash polls the gateway health
//! endpoint and redirects to the bundled admin UI once it is up. An
//! initialization script seeds the admin token into sessionStorage so the UI
//! connects without prompting, and routes every external link to the system
//! browser instead of navigating the webview away.

use std::{path::Path, sync::Mutex};

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, WindowEvent,
};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

const GATEWAY_ORIGIN_HOST: &str = "127.0.0.1";
const GATEWAY_PORT: u16 = 18900;

struct GatewayChild(Mutex<Option<CommandChild>>);

fn random_token() -> String {
    use rand::Rng;
    let mut rng = rand::thread_rng();
    (0..24).map(|_| format!("{:02x}", rng.gen::<u8>())).collect()
}

fn load_or_create_token(path: &Path) -> std::io::Result<String> {
    if let Ok(contents) = std::fs::read_to_string(path) {
        let token = contents.trim();
        if !token.is_empty() {
            return Ok(token.to_string());
        }
    }
    let token = random_token();
    std::fs::write(path, &token)?;
    Ok(token)
}

/// Keep the OpenAI-compatible base URL stable for external clients.
fn gateway_port() -> u16 {
    GATEWAY_PORT
}

fn gateway_port_up(port: u16) -> bool {
    std::net::TcpStream::connect((GATEWAY_ORIGIN_HOST, port)).is_ok()
}

/// Spawn (or respawn) the gateway sidecar and bind it to this process's job
/// object so it can never outlive the app. Sidecar stdout/stderr is appended
/// to app_data/gateway-sidecar.log so start-up failures are diagnosable.
fn spawn_gateway(
    app: &tauri::AppHandle,
    port: u16,
    admin_token: &str,
    api_token: &str,
) -> CommandChild {
    let data_dir = app.path().app_data_dir().expect("app data dir");
    std::fs::create_dir_all(&data_dir).ok();
    let log_path = data_dir.join("gateway-sidecar.log");
    let gateway_exe = resolve_gateway_exe(app).expect("bundled gateway sidecar not found");
    let (mut rx, child) = app
        .shell()
        .command(gateway_exe)
        .env("FREELLM_GATEWAY_HOST", GATEWAY_ORIGIN_HOST)
        .env("FREELLM_GATEWAY_PORT", port.to_string())
        .env("FREELLM_GATEWAY_DB", data_dir.join("gateway.sqlite3"))
        .env("FREELLM_GATEWAY_CATALOG_OUTPUT", data_dir.join("catalog-export.json"))
        .env("FREELLM_GATEWAY_API_TOKEN", api_token)
        .env("FREELLM_GATEWAY_ADMIN_TOKEN", admin_token)
        .env(
            "FREELLM_GATEWAY_LOG",
            data_dir.join("gateway-uvicorn.log").display().to_string(),
        )
        .spawn()
        .expect("failed to spawn gateway sidecar");
    bind_child_to_app_job(child.pid());

    let mut log = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .ok();
    if let Some(file) = log.as_mut() {
        use std::io::Write;
        let _ = writeln!(
            file,
            "\n=== sidecar spawned at {} (pid {}, port {}) ===",
            chrono_like_now(),
            child.pid(),
            port
        );
    }
    std::thread::spawn(move || {
        use tauri_plugin_shell::process::CommandEvent;
        use std::io::Write;
        tauri::async_runtime::block_on(async move {
            while let Some(event) = rx.recv().await {
                if let Some(file) = log.as_mut() {
                    let _ = match event {
                        CommandEvent::Stdout(line) => {
                            writeln!(file, "{}", String::from_utf8_lossy(&line))
                        }
                        CommandEvent::Stderr(line) => {
                            writeln!(file, "{}", String::from_utf8_lossy(&line))
                        }
                        CommandEvent::Error(line) => writeln!(file, "[error] {}", line),
                        CommandEvent::Terminated(payload) => writeln!(
                            file,
                            "[terminated] code {:?} signal {:?}",
                            payload.code, payload.signal
                        ),
                        _ => Ok(()),
                    };
                } else {
                    break;
                }
            }
        });
    });
    child
}

fn chrono_like_now() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    format!("epoch {}s", secs)
}

/// Background watchdog: if the gateway port stops accepting connections while
/// the app is alive, restart the sidecar (bounded retries). This is what makes
/// the splash page's "Retry" button actually able to recover.
fn gateway_watchdog(app: tauri::AppHandle, port: u16, admin_token: String, api_token: String) {
    std::thread::sleep(std::time::Duration::from_secs(3));
    let mut down_streak = 0u32;
    let mut respawns = 0u32;
    loop {
        if gateway_port_up(port) {
            down_streak = 0;
        } else {
            down_streak += 1;
            if down_streak >= 2 && respawns < 10 {
                down_streak = 0;
                respawns += 1;
                let state = app.state::<GatewayChild>();
                let mut guard = state.0.lock().unwrap();
                if !gateway_port_up(port) {
                    if let Some(old) = guard.take() {
                        let _ = old.kill();
                    }
                    *guard = Some(spawn_gateway(&app, port, &admin_token, &api_token));
                }
            }
        }
        std::thread::sleep(std::time::Duration::from_secs(2));
    }
}

/// Put the gateway child (and everything it spawns — the PyInstaller onefile
/// bootloader runs the real server as an inner process) into a Windows job
/// object with kill-on-close. The job handle is intentionally leaked: it is
/// closed by the OS when this process dies for ANY reason (graceful exit,
/// crash, force kill), taking the whole gateway process tree with it.
#[cfg(windows)]
fn bind_child_to_app_job(pid: u32) {
    use std::mem::size_of;
    use windows_sys::Win32::Foundation::CloseHandle;
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };
    use windows_sys::Win32::System::Threading::{OpenProcess, PROCESS_SET_QUOTA, PROCESS_TERMINATE};

    unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job.is_null() {
            return;
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const core::ffi::c_void,
            size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        ) == 0
        {
            return;
        }
        let process = OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, 0, pid);
        if process.is_null() {
            return;
        }
        AssignProcessToJobObject(job, process);
        CloseHandle(process);
    }
}

#[cfg(not(windows))]
fn bind_child_to_app_job(_pid: u32) {}

fn allow_navigation(url: &tauri::Url) -> bool {
    let s = url.as_str();
    s.starts_with("http://tauri.localhost")
        || s.starts_with("tauri://localhost")
        || s.starts_with("http://127.0.0.1:")
        || s.starts_with("http://localhost:")
        || s.starts_with("about:")
}

fn init_script(admin_token: &str, api_token: &str, port: u16, ga_measurement_id: &str) -> String {
    // __ADMIN_TOKEN__ / __API_TOKEN__ / __PORT__ / __GA_MEASUREMENT_ID__ are replaced below
    // instead of format! so the JS braces never fight the Rust formatter.
    r#"(function () {
      try {
        sessionStorage.setItem('freellm_gateway_admin_token', '__ADMIN_TOKEN__');
        sessionStorage.setItem('freellm_admin_token', '__ADMIN_TOKEN__');
      } catch (e) {}
      try { sessionStorage.setItem('freellm_api_token', '__API_TOKEN__'); } catch (e) {}
      window.__FREELLM_GATEWAY_PORT__ = __PORT__;
      window.__FREELLM_GA_MEASUREMENT_ID__ = '__GA_MEASUREMENT_ID__';
      document.addEventListener('click', function (event) {
        var el = event.target;
        while (el && el.tagName !== 'A') { el = el.parentElement; }
        if (!el) return;
        var href = el.getAttribute('href') || '';
        if (/^https?:\/\//i.test(href) && href.indexOf('127.0.0.1') === -1 && href.indexOf('localhost') === -1) {
          event.preventDefault();
          el.removeAttribute('target');
          window.location.href = href;
        }
      }, true);
    })();"#
        .replace("__ADMIN_TOKEN__", admin_token)
        .replace("__API_TOKEN__", api_token)
        .replace("__PORT__", &port.to_string())
        .replace("__GA_MEASUREMENT_ID__", ga_measurement_id)
}

fn resolve_gateway_exe(app: &tauri::AppHandle) -> Option<std::path::PathBuf> {
    // The gateway sidecar is an onedir build (exe + _internal/ copied into the
    // app's "sidecar" resource directory), so startup skips the ~200MB onefile
    // self-extraction that cost 10s+.
    let mut candidates = Vec::new();
    if let Ok(dir) = app.path().resource_dir() {
        candidates.push(dir.join("sidecar").join("freellm-gateway.exe"));
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            candidates.push(dir.join("sidecar").join("freellm-gateway.exe"));
            candidates.push(dir.join("freellm-gateway").join("freellm-gateway.exe"));
        }
    }
    candidates.into_iter().find(|p| p.exists())
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            // Second launch: focus the existing window instead of spawning a
            // duplicate app (and a duplicate gateway).
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_shell::init())
        .manage(GatewayChild(Mutex::new(None)))
        .setup(move |app| {
            let data_dir = app.path().app_data_dir()?;
            std::fs::create_dir_all(&data_dir)?;
            let admin_token = load_or_create_token(&data_dir.join("gateway-admin.token"))?;
            let api_token = load_or_create_token(&data_dir.join("gateway-api.token"))?;
            let ga_measurement_id = std::env::var("FREELLM_GA_MEASUREMENT_ID").unwrap_or_default();

            let port = gateway_port();
            std::fs::write(data_dir.join("gateway.port"), port.to_string()).ok();
            let child = spawn_gateway(app.handle(), port, &admin_token, &api_token);
            *app.state::<GatewayChild>().0.lock().unwrap() = Some(child);

            // Keep-alive watchdog: restarts the sidecar if the port stops
            // accepting connections, which is what makes the splash page's
            // "Retry" button able to recover from a dead gateway.
            {
                let handle = app.handle().clone();
                let admin = admin_token.clone();
                let api = api_token.clone();
                std::thread::spawn(move || gateway_watchdog(handle, port, admin, api));
            }

            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("FreeLLM Studio")
                .inner_size(1320.0, 880.0)
                .min_inner_size(980.0, 640.0)
                .initialization_script(&init_script(
                    &admin_token,
                    &api_token,
                    port,
                    &ga_measurement_id,
                ))
                .on_navigation(|url| {
                    if allow_navigation(url) {
                        return true;
                    }
                    let _ = open::that(url.as_str());
                    false
                });
            window.build()?;

            // Closing the window only hides it — the gateway keeps serving in
            // the background. The tray menu (or a tray click) brings it back;
            // "退出 Quit" is the only way to actually stop the app.
            let show = MenuItem::with_id(app, "show", "显示主界面 Show", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "退出 Quit", true, None::<&str>)?;
            let tray_menu = Menu::with_items(app, &[&show, &quit])?;
            TrayIconBuilder::with_id("freellm-tray")
                .icon(tauri::include_image!("icons/32x32.png"))
                .tooltip("FreeLLM Studio")
                .menu(&tray_menu)
                .show_menu_on_left_click(false)
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        if let Some(window) = tray.app_handle().get_webview_window("main") {
                            let _ = window.unminimize();
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "show" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.unminimize();
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(child) = app.state::<GatewayChild>().0.lock().unwrap().take() {
                    let _ = child.kill();
                }
            }
        });}

#[cfg(test)]
mod tests {
    use super::load_or_create_token;
    use std::fs;

    #[test]
    fn gateway_uses_stable_port_for_external_clients() {
        assert_eq!(super::gateway_port(), 18900);
    }

    #[test]
    fn token_is_reused_after_first_creation() {
        let path = std::env::temp_dir().join(format!("freellm-token-test-{}.txt", std::process::id()));
        let _ = fs::remove_file(&path);

        let first = load_or_create_token(&path).expect("first token should be created");
        let second = load_or_create_token(&path).expect("existing token should be loaded");

        assert_eq!(first, second);
        let _ = fs::remove_file(path);
    }

    #[test]
    fn init_script_exposes_api_token_to_the_local_ui() {
        let script = super::init_script("admin-token", "api-token", 1234, "");

        assert!(script.contains("freellm_admin_token"));
        assert!(script.contains("freellm_api_token"));
        assert!(script.contains("api-token"));
        assert!(script.contains("1234"));
    }

    #[test]
    fn init_script_injects_ga_measurement_id() {
        let script = super::init_script("admin-token", "api-token", 1234, "G-TEST123");

        assert!(script.contains("__FREELLM_GA_MEASUREMENT_ID__"));
        assert!(script.contains("G-TEST123"));
    }
}
