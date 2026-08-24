import AppKit
import CoreGraphics

enum WindowInspectionPermission {
    private static let explanation = "dアニメストアなどをウィンドウ表示で判別するため、macOSの「画面収録」権限を使用します。画面映像は取得・保存・送信せず、前面ウィンドウの名前だけを確認します。"

    static func offerInitialRequest() {
        guard !CGPreflightScreenCaptureAccess() else { return }
        let defaults = UserDefaults.standard
        let key = "AwayCamMac.didExplainWindowPermission"
        guard !defaults.bool(forKey: key) else { return }
        defaults.set(true, forKey: key)
        presentRequestAlert()
    }

    static func showStatusAndRequestIfNeeded() {
        if CGPreflightScreenCaptureAccess() {
            let alert = NSAlert()
            alert.messageText = "動画判定の権限は有効です"
            alert.informativeText = "前面ウィンドウ名を使って動画サイトを判定できます。"
            alert.runModal()
        } else {
            presentRequestAlert()
        }
    }

    private static func presentRequestAlert() {
        NSApp.activate()
        let alert = NSAlert()
        alert.messageText = "動画サイトの例外判定"
        alert.informativeText = explanation
        alert.addButton(withTitle: "権限を許可")
        alert.addButton(withTitle: "後で")

        guard alert.runModal() == .alertFirstButtonReturn else { return }
        if CGRequestScreenCaptureAccess() {
            let completion = NSAlert()
            completion.messageText = "権限を反映するため再起動してください"
            completion.informativeText = "メニューバーからAwayCamを終了し、もう一度起動すると動画判定が有効になります。"
            completion.runModal()
        }
    }
}

