import AppKit
import CoreGraphics
import Foundation

struct MediaException: Equatable {
    let reason: String
}

struct FrontmostContext {
    let bundleIdentifier: String
    let applicationName: String
    let windowTitle: String
    let isFullscreen: Bool
}

struct MediaExceptionMatcher {
    // 動画視聴ページの一般的なウィンドウタイトルを、大小文字を区別せず照合する。
    static let videoTitleKeywords = [
        "dアニメ", "danime", "d anime", "youtube", "netflix", "prime video",
        "amazonプライム", "disney+", "ディズニープラス", "u-next", "unext",
        "hulu", "abema", "ニコニコ", "niconico", "tver", "fod",
    ]

    static let videoAppBundleIdentifiers: Set<String> = [
        "com.apple.TV",
        "com.apple.QuickTimePlayerX",
        "org.videolan.vlc",
        "com.colliderli.iina",
        "io.mpv",
        "tv.plex.desktop",
    ]

    func match(
        context: FrontmostContext,
        exemptVideoPlayback: Bool,
        exemptFullscreenApps: Bool
    ) -> MediaException? {
        if exemptFullscreenApps && context.isFullscreen {
            return MediaException(reason: "全画面アプリを使用中")
        }
        guard exemptVideoPlayback else { return nil }

        if Self.videoAppBundleIdentifiers.contains(context.bundleIdentifier) {
            return MediaException(reason: "動画アプリを使用中")
        }

        let searchable = "\(context.applicationName) \(context.windowTitle)"
            .folding(options: [.caseInsensitive, .diacriticInsensitive], locale: .current)
            .lowercased()
        if Self.videoTitleKeywords.contains(where: { searchable.contains($0.lowercased()) }) {
            return MediaException(reason: "動画を視聴中")
        }
        return nil
    }
}

final class MediaExceptionMonitor {
    private let matcher = MediaExceptionMatcher()
    private var lastCheckedAt: TimeInterval = -.infinity
    private var cachedException: MediaException?

    func currentException(settings: AppSettings) -> MediaException? {
        guard settings.exemptVideoPlayback || settings.exemptFullscreenApps else {
            return nil
        }
        // ウィンドウ一覧の取得は比較的高コストなので、1秒間は結果を再利用する。
        let now = ProcessInfo.processInfo.systemUptime
        if now - lastCheckedAt < 1 {
            return cachedException
        }
        lastCheckedAt = now
        guard let application = NSWorkspace.shared.frontmostApplication else {
            cachedException = nil
            return nil
        }

        let window = frontmostWindow(for: application.processIdentifier)
        let context = FrontmostContext(
            bundleIdentifier: application.bundleIdentifier ?? "",
            applicationName: application.localizedName ?? "",
            windowTitle: window?.title ?? "",
            isFullscreen: window.map(isFullscreen) ?? false
        )
        cachedException = matcher.match(
            context: context,
            exemptVideoPlayback: settings.exemptVideoPlayback,
            exemptFullscreenApps: settings.exemptFullscreenApps
        )
        return cachedException
    }

    // 前面プロセスが所有する通常レイヤーの最上位ウィンドウだけを見る。
    private func frontmostWindow(for processIdentifier: pid_t) -> WindowSnapshot? {
        let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
        guard let rows = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] else {
            return nil
        }

        for row in rows {
            guard
                (row[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value == processIdentifier,
                (row[kCGWindowLayer as String] as? NSNumber)?.intValue == 0,
                let boundsDictionary = row[kCGWindowBounds as String] as? CFDictionary,
                let bounds = CGRect(dictionaryRepresentation: boundsDictionary),
                bounds.width > 100,
                bounds.height > 100
            else { continue }

            return WindowSnapshot(
                title: row[kCGWindowName as String] as? String ?? "",
                bounds: bounds
            )
        }
        return nil
    }

    private func isFullscreen(_ window: WindowSnapshot) -> Bool {
        NSScreen.screens.contains { screen in
            let sizeMatches = abs(window.bounds.width - screen.frame.width) <= 2
                && abs(window.bounds.height - screen.frame.height) <= 2
            return sizeMatches
        }
    }
}

private struct WindowSnapshot {
    let title: String
    let bounds: CGRect
}
