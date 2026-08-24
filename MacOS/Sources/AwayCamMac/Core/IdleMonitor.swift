import CoreGraphics
import Foundation

protocol IdleTimeProviding {
    var idleSeconds: TimeInterval { get }
}

/// 入力内容には触れず、macOSが持つ最終HIDイベントからの経過時間だけを読む。
struct IdleMonitor: IdleTimeProviding {
    var idleSeconds: TimeInterval {
        // UInt32.max はQuartzの kCGAnyInputEventType。キー、マウス、タブレットをまとめて扱う。
        let anyInputEvent = CGEventType(rawValue: UInt32.max)!
        let value = CGEventSource.secondsSinceLastEventType(
            .hidSystemState,
            eventType: anyInputEvent
        )
        return value.isFinite && value >= 0 ? value : 0
    }
}
