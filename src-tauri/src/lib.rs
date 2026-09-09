// 智作台桌面端核心：Tauri 窗口 + 本机执行层（瘦客户端）
//
// 架构（瘦客户端 + 远程服务器）：
//   Vue 前端 (WebView) ──HTTP/WS──► 远程服务器（多副本 backend + db/redis/chroma）
//   Rust 本机执行层（随 .app 打包）──本地 subprocess──► open / osascript（用户授权后）
//
// 后端不随 .app 启动（用户零安装依赖）。所有业务/数据/逻辑在服务器。
// 仅「操控用户本机电脑」这类动作必须由客户端执行层完成（授权后），属 app 自带能力。
//
// 本机控制授权：
//   - 已用 Developer ID 签名并公证：macOS 在首次/新增目标 App 时自动弹 TCC 授权框。
//   - 未签名（ad_hoc/unsigned）：TCC 不稳或弹不出来；客户端检测签名状态后上报服务端，
//     由服务端 logger.warning 提醒配置 Developer ID（见 get_signature_status）。

use std::process::Command;
use tauri_plugin_dialog;
// TODO: 等后端上 HTTPS 后取消注释，恢复更新功能
// use tauri_plugin_updater;

/// 在用户本机执行一个动作（仅 macOS 真正执行；其它平台返回友好提示）。
/// action: open_application | open_webpage | run_apple_script | find_local_files
/// payload: JSON 字符串，字段对应各动作参数。
#[tauri::command]
fn execute_local_action(action: String, payload: String) -> Result<String, String> {
    let value: serde_json::Value =
        serde_json::from_str(&payload).map_err(|e| format!("[ERROR] 参数解析失败: {e}"))?;

    match action.as_str() {
        "open_application" => {
            let name = value
                .get("app_name")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .trim();
            if name.is_empty() {
                return Err("[ERROR] 应用名称不能为空".into());
            }
            #[cfg(target_os = "macos")]
            {
                match Command::new("open").args(["-a", name]).output() {
                    Ok(o) if o.status.success() => return Ok(format!("✅ 已为你打开应用：{name}")),
                    Ok(_) => {
                        // 退一步：当作路径直接打开
                        match Command::new("open").arg(name).output() {
                            Ok(o2) if o2.status.success() => {
                                return Ok(format!("✅ 已为你打开：{name}"))
                            }
                            Ok(o2) => {
                                let err = String::from_utf8_lossy(&o2.stderr);
                                return Err(format!("⚠️ 无法打开应用「{name}」：{}", err.trim()));
                            }
                            Err(e) => return Err(format!("[ERROR] 打开应用时出错: {e}")),
                        }
                    }
                    Err(e) => return Err(format!("[ERROR] 打开应用时出错: {e}")),
                }
            }
            #[cfg(not(target_os = "macos"))]
            {
                return Err("[ERROR] 打开应用目前仅支持 macOS".into());
            }
        }

        "open_webpage" => {
            let url = value.get("url").and_then(|v| v.as_str()).unwrap_or("");
            if !url.starts_with("http://") && !url.starts_with("https://") {
                return Err(format!(
                    "[ERROR] 无效的网址: {url}，请提供完整地址（以 https:// 开头）"
                ));
            }
            #[cfg(target_os = "macos")]
            {
                // 优先使用 Google Chrome；若本机未安装则回退到系统默认浏览器。
                // 这样不会同时打开 Chrome + Safari，也不会与 open_application 重复触发。
                let chrome_try = Command::new("open")
                    .args(["-a", "Google Chrome", "--args", "--new-tab", url])
                    .output();
                match chrome_try {
                    Ok(o) if o.status.success() => {
                        return Ok(format!("✅ 已在 Google Chrome 打开: {url}"))
                    }
                    _ => match Command::new("open").arg(url).output() {
                        Ok(o) if o.status.success() => {
                            return Ok(format!("✅ 已在默认浏览器打开: {url}"))
                        }
                        Ok(o) => {
                            let err = String::from_utf8_lossy(&o.stderr);
                            return Err(format!("⚠️ 无法自动打开浏览器: {err}"));
                        }
                        Err(e) => return Err(format!("[ERROR] 打开网页出错: {e}")),
                    },
                }
            }
            #[cfg(not(target_os = "macos"))]
            {
                return Err("[ERROR] 打开网页目前仅支持 macOS".into());
            }
        }

        "run_apple_script" => {
            let script = value
                .get("script")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .trim();
            if script.is_empty() {
                return Err("[ERROR] 脚本内容不能为空".into());
            }
            #[cfg(target_os = "macos")]
            {
                match Command::new("osascript").args(["-e", script]).output() {
                    Ok(o) if o.status.success() => {
                        let out = String::from_utf8_lossy(&o.stdout).trim().to_string();
                        return Ok(format!(
                            "✅ AppleScript 执行成功。{}",
                            if out.is_empty() {
                                String::new()
                            } else {
                                format!("\n输出:\n{out}")
                            }
                        ));
                    }
                    Ok(o) => {
                        let err = String::from_utf8_lossy(&o.stderr);
                        return Err(format!(
                            "⚠️ AppleScript 执行失败:\n{err}\n（请检查 系统设置 → 隐私与安全性 → 自动化/辅助功能 是否已授权智作台）"
                        ));
                    }
                    Err(e) => return Err(format!("[ERROR] 执行 AppleScript 出错: {e}")),
                }
            }
            #[cfg(not(target_os = "macos"))]
            {
                return Err("[ERROR] AppleScript 仅支持 macOS".into());
            }
        }

        "find_local_files" => {
            let name = value
                .get("name")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .trim();
            if name.is_empty() {
                return Err("[ERROR] 请提供要搜索的文件名关键词（name）".into());
            }
            let exts: Vec<String> = value
                .get("ext")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .split(',')
                .map(|s| s.trim().trim_start_matches('.').to_lowercase())
                .filter(|s| !s.is_empty())
                .map(|s| format!(".{s}"))
                .collect();
            let max_results: usize = value
                .get("max_results")
                .and_then(|v| v.as_u64())
                .unwrap_or(10)
                .clamp(1, 50) as usize;

            #[cfg(target_os = "macos")]
            {
                let raw = match Command::new("mdfind").args(["-name", name]).output() {
                    Ok(o) if o.status.success() => String::from_utf8_lossy(&o.stdout).to_string(),
                    Ok(o) => {
                        let e = String::from_utf8_lossy(&o.stderr);
                        return Err(format!("[ERROR] 搜索文件出错: {e}"));
                    }
                    Err(e) => return Err(format!("[ERROR] 搜索文件出错: {e}")),
                };
                let mut hits: Vec<(String, u64, f64)> = Vec::new();
                for p in raw.lines() {
                    let p = p.trim();
                    if p.is_empty() {
                        continue;
                    }
                    let md = match std::fs::metadata(p) {
                        Ok(m) => m,
                        Err(_) => continue,
                    };
                    if !md.is_file() {
                        continue;
                    }
                    let ext = std::path::Path::new(p)
                        .extension()
                        .and_then(|e| e.to_str())
                        .unwrap_or("")
                        .to_lowercase();
                    if !exts.is_empty() && !exts.contains(&format!(".{ext}")) {
                        continue;
                    }
                    let size = md.len();
                    let mtime = md
                        .modified()
                        .ok()
                        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                        .map(|d| d.as_secs_f64())
                        .unwrap_or(0.0);
                    hits.push((p.to_string(), size, mtime));
                }
                hits.sort_by(|a, b| b.2.partial_cmp(&a.2).unwrap_or(std::cmp::Ordering::Equal));
                hits.truncate(max_results);
                if hits.is_empty() {
                    return Ok(format!(
                        "🔍 在本地未找到包含「{name}」的文件。\n建议：1) 告诉我更完整的文件名或关键词；2) 告诉我文件所在的具体目录。"
                    ));
                }
                let mut lines = vec![format!(
                    "🔍 在本地找到 {} 个匹配「{name}」的文件（按修改时间从新到旧）：",
                    hits.len()
                )];
                for (i, (p, size, _)) in hits.iter().enumerate() {
                    let kb = *size as f64 / 1024.0;
                    let size_s = if kb < 1024.0 {
                        format!("{} KB", (kb * 10.0).round() / 10.0)
                    } else {
                        format!("{} MB", (kb / 1024.0 * 100.0).round() / 100.0)
                    };
                    lines.push(format!("{}. {p}\n   大小 {size_s}", i + 1));
                }
                lines.push("\n请把上面最匹配的那个完整路径，作为 attachments 参数传给 send_email_smtp 发送。".into());
                return Ok(lines.join("\n"));
            }
            #[cfg(not(target_os = "macos"))]
            {
                return Err("[ERROR] 本地文件搜索仅支持 macOS".into());
            }
        }

        other => Err(format!("[ERROR] 未知的本机操作: {other}")),
    }
}

/// 返回当前 .app 的代码签名状态：
///   "developer_id" —— 已用 Developer ID 签名（TCC 授权可正常持久）
///   "ad_hoc"       —— 仅本机 ad-hoc 签名（TCC 不稳/不持久）
///   "unsigned"     —— 未签名（TCC 不会弹或弹了无效）
#[tauri::command]
fn get_signature_status() -> String {
    let exe = match std::env::current_exe() {
        Ok(p) => p,
        Err(_) => return "unsigned".into(),
    };
    let path = exe.to_string_lossy().to_string();
    let output = match Command::new("codesign").args(["-dvv", &path]).output() {
        Ok(o) => {
            let mut s = String::from_utf8_lossy(&o.stdout).to_string();
            s.push_str(&String::from_utf8_lossy(&o.stderr));
            if !o.status.success() {
                return "unsigned".into();
            }
            s
        }
        Err(_) => return "unsigned".into(),
    };
    if output.contains("Authority=Developer ID Application") {
        "developer_id".into()
    } else {
        "ad_hoc".into()
    }
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        // TODO: 等后端上 HTTPS 后取消注释
        // .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            execute_local_action,
            get_signature_status
        ])
        .setup(|app| {
            // 禁用 WebView 的前进/后退导航，移除 macOS 自带的 Back / Reload 按钮
            #[cfg(target_os = "macos")]
            {
                use objc2_app_kit::NSWindow;
                use objc2_web_kit::WKWebView;
                use objc2::rc::Retained;
                use objc2::ClassType;
                use objc2::runtime::NSObjectProtocol;
                use tauri::Manager;

                if let Some(window) = app.get_webview_window("main") {
                    if let Ok(ns_win_ptr) = window.ns_window() {
                        if let Some(ns_window) =
                            unsafe { Retained::retain(ns_win_ptr as *mut NSWindow) }
                        {
                            // 移除窗口自带的 toolbar（macOS 会在 toolbar 上放 Back/Reload）
                            ns_window.setToolbar(None);
                        }
                    }
                    // 禁用 WKWebView 的前进/后退导航手势
                    if let Ok(ns_view_ptr) = window.ns_view() {
                        unsafe {
                            // ns_view 返回的是 wry 的父视图 WryWebViewParent，
                            // WKWebView 是其子视图，需要遍历查找
                            let parent_view: Retained<objc2_app_kit::NSView> =
                                Retained::retain(ns_view_ptr as *mut objc2_app_kit::NSView)
                                    .unwrap();
                            let subviews = parent_view.subviews();
                            for i in 0..subviews.count() {
                                let subview = subviews.objectAtIndex(i);
                                if subview.isKindOfClass(WKWebView::class()) {
                                    let webview: Retained<WKWebView> =
                                        Retained::cast_unchecked(subview);
                                    webview.setAllowsBackForwardNavigationGestures(false);
                                    break;
                                }
                            }
                        }
                    }
                }
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
