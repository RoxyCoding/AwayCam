// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "AwayCamMac",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "AwayCamMac", targets: ["AwayCamMac"]),
    ],
    targets: [
        .executableTarget(name: "AwayCamMac"),
        .testTarget(name: "AwayCamMacTests", dependencies: ["AwayCamMac"]),
    ]
)
