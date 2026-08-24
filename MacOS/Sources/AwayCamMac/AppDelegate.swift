import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    private let store = SettingsStore.shared
    private let idleMonitor: IdleTimeProviding = IdleMonitor()
    private let mediaMonitor = MediaExceptionMonitor()
    private let evaluator = AwayDecisionEvaluator()
    private let blackoutController = BlackoutController()

    private var settings = AppSettings()
    private var timer: Timer?
    private var statusItem: NSStatusItem?
    private var toggleItem: NSMenuItem?
    private var stateItem: NSMenuItem?
    private var settingsWindowController: SettingsWindowController?

    func applicationDidFinishLaunching(_ notification: Notification) {
        settings = store.load()
        configureMenuBar()
        observeScreenChanges()
        evaluateState()
        timer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] _ in
            self?.evaluateState()
        }
        DispatchQueue.main.async {
            WindowInspectionPermission.offerInitialRequest()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        timer?.invalidate()
        blackoutController.hide()
    }

    private func configureMenuBar() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        item.button?.image = NSImage(systemSymbolName: "display", accessibilityDescription: "AwayCam")

        let menu = NSMenu()
        let stateItem = NSMenuItem(title: "監視中", action: nil, keyEquivalent: "")
        stateItem.isEnabled = false
        menu.addItem(stateItem)

        let toggleItem = NSMenuItem(title: "有効", action: #selector(toggleEnabled), keyEquivalent: "")
        toggleItem.target = self
        menu.addItem(toggleItem)
        menu.addItem(.separator())

        let settingsItem = NSMenuItem(title: "設定…", action: #selector(showSettings), keyEquivalent: ",")
        settingsItem.target = self
        menu.addItem(settingsItem)

        let permissionItem = NSMenuItem(
            title: "動画判定の権限…",
            action: #selector(showWindowInspectionPermission),
            keyEquivalent: ""
        )
        permissionItem.target = self
        menu.addItem(permissionItem)

        let quitItem = NSMenuItem(title: "AwayCamを終了", action: #selector(quit), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)

        item.menu = menu
        self.statusItem = item
        self.stateItem = stateItem
        self.toggleItem = toggleItem
        updateMenu(enabled: settings.isEnabled, status: settings.isEnabled ? "監視中" : "停止中")
    }

    private func observeScreenChanges() {
        NotificationCenter.default.addObserver(
            forName: NSApplication.didChangeScreenParametersNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            self?.blackoutController.screensChanged()
        }
    }

    private func evaluateState() {
        let idleSeconds = idleMonitor.idleSeconds
        // しきい値前は例外を調べる必要がなく、通常時のウィンドウ一覧取得を避けられる。
        let exception = idleSeconds >= TimeInterval(settings.idleSeconds)
            ? mediaMonitor.currentException(settings: settings)
            : nil
        let decision = evaluator.evaluate(
            settings: settings,
            idleSeconds: idleSeconds,
            exception: exception
        )

        switch decision {
        case .active:
            blackoutController.hide()
            updateMenu(enabled: settings.isEnabled, status: settings.isEnabled ? "監視中" : "停止中")
        case .blackout:
            blackoutController.show()
            updateMenu(enabled: true, status: "暗転中（入力で解除）")
        case .exempt(let reason):
            blackoutController.hide()
            updateMenu(enabled: true, status: "例外: \(reason)")
        }
    }

    private func updateMenu(enabled: Bool, status: String) {
        toggleItem?.state = enabled ? .on : .off
        stateItem?.title = status
        statusItem?.button?.image = NSImage(
            systemSymbolName: enabled ? "display" : "display.slash",
            accessibilityDescription: status
        )
    }

    @objc private func toggleEnabled() {
        settings.isEnabled.toggle()
        store.save(settings)
        evaluateState()
    }

    @objc private func showSettings() {
        if settingsWindowController == nil {
            settingsWindowController = SettingsWindowController(
                store: store,
                settings: settings
            ) { [weak self] newSettings in
                self?.settings = newSettings
                self?.evaluateState()
            }
        }
        settingsWindowController?.update(settings: settings)
        settingsWindowController?.present()
    }

    @objc private func quit() {
        NSApp.terminate(nil)
    }

    @objc private func showWindowInspectionPermission() {
        WindowInspectionPermission.showStatusAndRequestIfNeeded()
    }
}
