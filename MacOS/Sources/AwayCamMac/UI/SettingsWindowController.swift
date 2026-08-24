import AppKit

final class SettingsWindowController: NSWindowController, NSTextFieldDelegate {
    private let store: SettingsStore
    private var settings: AppSettings
    private let onSave: (AppSettings) -> Void

    private let secondsField = NSTextField()
    private let videoCheckbox = NSButton(checkboxWithTitle: "動画視聴中は暗転しない", target: nil, action: nil)
    private let fullscreenCheckbox = NSButton(checkboxWithTitle: "全画面アプリ使用中は暗転しない", target: nil, action: nil)

    init(store: SettingsStore, settings: AppSettings, onSave: @escaping (AppSettings) -> Void) {
        self.store = store
        self.settings = settings
        self.onSave = onSave

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 460, height: 270),
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        window.title = "AwayCam 設定"
        window.center()
        super.init(window: window)
        buildContent()
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) は使用しません")
    }

    func present() {
        refreshControls()
        showWindow(nil)
        NSApp.activate()
        window?.makeKeyAndOrderFront(nil)
    }

    func update(settings: AppSettings) {
        self.settings = settings
        refreshControls()
    }

    private func buildContent() {
        let title = NSTextField(labelWithString: "無操作時の暗転")
        title.font = .systemFont(ofSize: 20, weight: .semibold)

        let secondsLabel = NSTextField(labelWithString: "操作がない時間（秒）")
        secondsField.placeholderString = "60"
        secondsField.alignment = .right
        secondsField.formatter = integerFormatter()
        secondsField.delegate = self

        videoCheckbox.target = self
        videoCheckbox.action = #selector(saveControls)
        fullscreenCheckbox.target = self
        fullscreenCheckbox.action = #selector(saveControls)

        let note = NSTextField(wrappingLabelWithString:
            "dアニメストア、YouTube、Netflixなどのウィンドウタイトルと、主要な動画プレイヤーを判定します。画面は物理輝度を変更せず、黒い表示で明るさ0相当にします。"
        )
        note.textColor = .secondaryLabelColor

        let timeRow = NSStackView(views: [secondsLabel, secondsField])
        timeRow.orientation = .horizontal
        timeRow.spacing = 12
        secondsField.widthAnchor.constraint(equalToConstant: 100).isActive = true

        let stack = NSStackView(views: [title, timeRow, videoCheckbox, fullscreenCheckbox, note])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 14
        stack.translatesAutoresizingMaskIntoConstraints = false
        note.widthAnchor.constraint(equalToConstant: 404).isActive = true

        window?.contentView?.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: window!.contentView!.leadingAnchor, constant: 28),
            stack.trailingAnchor.constraint(equalTo: window!.contentView!.trailingAnchor, constant: -28),
            stack.topAnchor.constraint(equalTo: window!.contentView!.topAnchor, constant: 26),
        ])
    }

    private func refreshControls() {
        secondsField.integerValue = settings.idleSeconds
        videoCheckbox.state = settings.exemptVideoPlayback ? .on : .off
        fullscreenCheckbox.state = settings.exemptFullscreenApps ? .on : .off
    }

    @objc private func saveControls() {
        settings.idleSeconds = max(secondsField.integerValue, AppSettings.minimumIdleSeconds)
        settings.exemptVideoPlayback = videoCheckbox.state == .on
        settings.exemptFullscreenApps = fullscreenCheckbox.state == .on
        settings.validate()
        store.save(settings)
        onSave(settings)
        refreshControls()
    }

    func controlTextDidEndEditing(_ notification: Notification) {
        saveControls()
    }

    private func integerFormatter() -> NumberFormatter {
        let formatter = NumberFormatter()
        formatter.numberStyle = .none
        formatter.allowsFloats = false
        formatter.minimum = NSNumber(value: AppSettings.minimumIdleSeconds)
        formatter.maximum = NSNumber(value: AppSettings.maximumIdleSeconds)
        return formatter
    }
}
