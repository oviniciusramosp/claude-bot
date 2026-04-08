// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "ClaudeBotManager",
    platforms: [
        .macOS(.v26)
    ],
    dependencies: [
        .package(url: "https://github.com/jpsim/Yams.git", from: "5.1.0"),
    ],
    targets: [
        .executableTarget(
            name: "ClaudeBotManager",
            dependencies: ["Yams"],
            path: "Sources",
            resources: [.process("Resources")]
        )
    ]
)
