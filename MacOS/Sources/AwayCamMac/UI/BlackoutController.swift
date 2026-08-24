import AppKit

/// 物理輝度には触れず、全ディスプレイを不透明な黒で安全に覆う。
final class BlackoutController {
    private var windows: [NSWindow] = []
    private(set) var isVisible = false

    func show() {
        guard !isVisible else { return }
        rebuildWindows()
        windows.forEach { $0.orderFrontRegardless() }
        isVisible = true
    }

    func hide() {
        windows.forEach { $0.orderOut(nil) }
        windows.removeAll()
        isVisible = false
    }

    func screensChanged() {
        guard isVisible else { return }
        hide()
        show()
    }

    private func rebuildWindows() {
        windows = NSScreen.screens.map { screen in
            let window = NSWindow(
                contentRect: screen.frame,
                styleMask: .borderless,
                backing: .buffered,
                defer: false,
                screen: screen
            )
            window.backgroundColor = .black
            window.isOpaque = true
            window.hasShadow = false
            window.level = .screenSaver
            window.ignoresMouseEvents = false
            window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
            window.contentView = NSView(frame: screen.frame)
            window.contentView?.wantsLayer = true
            window.contentView?.layer?.backgroundColor = NSColor.black.cgColor
            return window
        }
    }
}

