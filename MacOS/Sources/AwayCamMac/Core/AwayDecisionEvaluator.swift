import Foundation

enum AwayDecision: Equatable {
    case active
    case blackout
    case exempt(String)
}

struct AwayDecisionEvaluator {
    func evaluate(
        settings: AppSettings,
        idleSeconds: TimeInterval,
        exception: MediaException?
    ) -> AwayDecision {
        guard settings.isEnabled else { return .active }
        if let exception {
            return .exempt(exception.reason)
        }
        return idleSeconds >= TimeInterval(settings.idleSeconds) ? .blackout : .active
    }
}

