import Foundation

struct AppSettings: Codable, Equatable {
    static let minimumIdleSeconds = 1
    static let maximumIdleSeconds = 86_400

    var isEnabled = true
    var idleSeconds = 60
    var exemptVideoPlayback = true
    var exemptFullscreenApps = true

    mutating func validate() {
        idleSeconds = min(max(idleSeconds, Self.minimumIdleSeconds), Self.maximumIdleSeconds)
    }
}

final class SettingsStore {
    static let shared = SettingsStore()

    private let defaults: UserDefaults
    private let key = "AwayCamMac.settings.v1"

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    func load() -> AppSettings {
        guard
            let data = defaults.data(forKey: key),
            var settings = try? JSONDecoder().decode(AppSettings.self, from: data)
        else {
            return AppSettings()
        }
        settings.validate()
        return settings
    }

    func save(_ input: AppSettings) {
        var settings = input
        settings.validate()
        guard let data = try? JSONEncoder().encode(settings) else { return }
        defaults.set(data, forKey: key)
    }
}

