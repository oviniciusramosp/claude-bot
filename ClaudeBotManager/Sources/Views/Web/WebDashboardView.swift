import SwiftUI
import CoreImage
import CoreImage.CIFilterBuiltins
import Darwin   // getifaddrs, inet_ntop

// MARK: - Cloudflare Tunnel Service

@MainActor
final class CloudflareTunnelService: ObservableObject {
    enum TunnelState: Equatable {
        case notInstalled
        case stopped
        case starting
        case active(url: String)
        case failed(String)

        var isActive: Bool {
            if case .active = self { return true }
            return false
        }

        var activeURL: String? {
            if case .active(let url) = self { return url }
            return nil
        }
    }

    @Published var state: TunnelState = .stopped

    private var process: Process?

    init() {
        Task { await detect() }
    }

    func detect() async {
        let found = await Task.detached(priority: .utility) { () -> Bool in
            let p = Process()
            let pipe = Pipe()
            p.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            p.arguments = ["which", "cloudflared"]
            p.standardOutput = pipe
            p.standardError = Pipe()
            try? p.run()
            p.waitUntilExit()
            let out = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
            return !out.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }.value
        if case .active = state { return }  // don't clobber running tunnel
        if case .starting = state { return }
        state = found ? .stopped : .notInstalled
    }

    func start() {
        guard case .stopped = state else { return }
        state = .starting

        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        proc.arguments = ["cloudflared", "tunnel", "--url", "http://localhost:27184", "--no-autoupdate"]

        let errPipe = Pipe()
        proc.standardOutput = Pipe()
        proc.standardError = errPipe

        proc.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async { [weak self] in
                guard let self else { return }
                if case .active = self.state { return }
                self.state = .stopped
            }
        }

        do {
            try proc.run()
        } catch {
            state = .failed("Failed to start: \(error.localizedDescription)")
            return
        }

        process = proc

        errPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty else { return }
            if let str = String(data: data, encoding: .utf8) {
                DispatchQueue.main.async { [weak self] in
                    guard let self else { return }
                    if let url = CloudflareTunnelService.parseURL(from: str) {
                        self.state = .active(url: url)
                        handle.readabilityHandler = nil  // stop watching once URL found
                    }
                }
            }
        }
    }

    func stop() {
        process?.terminate()
        process = nil
        state = .stopped
    }

    static func parseURL(from text: String) -> String? {
        // cloudflared prints the HTTPS URL to stderr:
        // "Your quick Tunnel has been created! Visit it at: https://xxx.trycloudflare.com"
        let pattern = #"https://[a-z0-9\-]+\.trycloudflare\.com"#
        if let range = text.range(of: pattern, options: .regularExpression) {
            return String(text[range])
        }
        return nil
    }
}

// MARK: - Web Dashboard View

struct WebDashboardView: View {
    @EnvironmentObject var appState: AppState
    @StateObject private var tunnel = CloudflareTunnelService()
    @State private var webRunning = false
    @State private var copiedLocal = false
    @State private var copiedTunnel = false
    @State private var isBusy = false
    @State private var pin: String = ""
    @State private var pinEditing = false
    @State private var pinDraft = ""
    @State private var pinSaved = false

    private let localURL = "http://localhost:27184"
    private let timer = Timer.publish(every: 5, on: .main, in: .common).autoconnect()

    private var botEnvPath: String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        return "\(home)/claude-bot/.env"
    }

    /// URL shown in the QR code: tunnel URL when active, LAN IP otherwise.
    /// `localhost` is useless on a phone — use the machine's actual IP.
    var qrURL: String {
        if let tunnelURL = tunnel.state.activeURL { return tunnelURL }
        let ip = Self.localIPAddress() ?? "localhost"
        return "http://\(ip):27184"
    }

    /// Returns the best local IPv4 address for LAN access.
    /// Prefers RFC 1918 private ranges (192.168/10/172.16-31) on en* interfaces.
    static func localIPAddress() -> String? {
        var ifaddr: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&ifaddr) == 0 else { return nil }
        defer { freeifaddrs(ifaddr) }

        var fallback: String? = nil
        var cursor = ifaddr
        while let current = cursor {
            defer { cursor = current.pointee.ifa_next }
            let ifa = current.pointee
            guard ifa.ifa_addr.pointee.sa_family == UInt8(AF_INET) else { continue }
            let name = String(cString: ifa.ifa_name)
            guard name.hasPrefix("en") else { continue }

            // Must rebound to sockaddr_in to read sin_addr correctly —
            // passing sockaddr* to inet_ntop gives garbage bytes.
            let ip = ifa.ifa_addr.withMemoryRebound(to: sockaddr_in.self, capacity: 1) { ptr -> String in
                var sin = ptr.pointee.sin_addr
                var buf = [CChar](repeating: 0, count: Int(INET_ADDRSTRLEN))
                inet_ntop(AF_INET, &sin, &buf, socklen_t(INET_ADDRSTRLEN))
                return String(cString: buf)
            }

            // RFC 1918 private ranges → ideal for LAN access, return immediately
            if ip.hasPrefix("192.168.") || ip.hasPrefix("10.") || isPrivate172(ip) {
                return ip
            }
            if fallback == nil { fallback = ip }
        }
        return fallback
    }

    private static func isPrivate172(_ ip: String) -> Bool {
        let parts = ip.split(separator: ".").compactMap { Int($0) }
        guard parts.count >= 2, parts[0] == 172 else { return false }
        return parts[1] >= 16 && parts[1] <= 31
    }

    var body: some View {
        ScrollView {
            VStack(spacing: Spacing.xl) {
                webStatusCard
                tunnelCard
                qrCodeCard
            }
            .padding(Spacing.xl)
        }
        .background(Color(.windowBackgroundColor))
        .navigationTitle("Web Dashboard")
        .task { await checkWebHealth(); loadPin() }
        .onReceive(timer) { _ in Task { await checkWebHealth() } }
    }

    // MARK: - Web Status Card

    private var webStatusCard: some View {
        SectionCard(title: "Web Service", symbol: "globe") {
            VStack(spacing: Spacing.md) {
                // Status row
                HStack(spacing: Spacing.sm) {
                    StatusDot(isRunning: webRunning)
                    Text(webRunning ? "Running on port 27184" : "Stopped")
                        .font(.system(size: 13, weight: .medium))
                    Spacer()
                    webControlButtons
                }

                Divider()

                // Local URL row (LAN IP so it's useful from other devices)
                let lanURL = "http://\(Self.localIPAddress() ?? "localhost"):27184"
                urlRow(label: "LAN", url: lanURL, copied: $copiedLocal)

                Divider()

                // PIN row
                HStack(spacing: Spacing.sm) {
                    Text("PIN")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(.tertiary)
                        .frame(width: 36, alignment: .trailing)
                    if pinEditing {
                        TextField("6 digits", text: $pinDraft)
                            .textFieldStyle(.roundedBorder)
                            .font(.system(size: 12, design: .monospaced))
                            .frame(width: 90)
                        Button("Save") { savePin() }
                            .buttonStyle(.borderedProminent)
                            .controlSize(.small)
                            .disabled(pinDraft.count < 4)
                        Button("Cancel") { pinEditing = false; pinDraft = pin }
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                    } else {
                        Text(pin.isEmpty ? "—" : pin)
                            .font(.system(size: 12, design: .monospaced))
                            .foregroundStyle(.secondary)
                        if pinSaved {
                            Label("Saved", systemImage: "checkmark")
                                .font(.system(size: 11))
                                .foregroundStyle(Color.statusGreen)
                        }
                        Spacer()
                        Button {
                            pinDraft = pin
                            pinEditing = true
                            pinSaved = false
                        } label: {
                            Label("Change", systemImage: "pencil")
                                .font(.system(size: 11))
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var webControlButtons: some View {
        HStack(spacing: Spacing.sm) {
            if webRunning {
                Button(role: .destructive) {
                    Task {
                        isBusy = true
                        await appState.stopBot()
                        try? await Task.sleep(nanoseconds: 1_000_000_000)
                        await checkWebHealth()
                        isBusy = false
                    }
                } label: {
                    Label("Stop", systemImage: "stop.fill")
                        .font(.system(size: 11))
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .disabled(isBusy)

                Button {
                    Task {
                        isBusy = true
                        await appState.restartBot()
                        try? await Task.sleep(nanoseconds: 2_000_000_000)
                        await checkWebHealth()
                        isBusy = false
                    }
                } label: {
                    if isBusy {
                        Label("Restarting…", systemImage: "arrow.clockwise")
                            .font(.system(size: 11))
                    } else {
                        Label("Restart", systemImage: "arrow.clockwise")
                            .font(.system(size: 11))
                    }
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .disabled(isBusy)
            } else {
                Button {
                    Task {
                        isBusy = true
                        await appState.startBot()
                        try? await Task.sleep(nanoseconds: 2_000_000_000)
                        await checkWebHealth()
                        isBusy = false
                    }
                } label: {
                    if isBusy {
                        Label("Starting…", systemImage: "play.fill")
                            .font(.system(size: 11))
                    } else {
                        Label("Start", systemImage: "play.fill")
                            .font(.system(size: 11))
                    }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
                .disabled(isBusy)
            }
        }
    }

    // MARK: - Tunnel Card

    private var tunnelCard: some View {
        SectionCard(title: "Cloudflare Tunnel", symbol: "network") {
            VStack(alignment: .leading, spacing: Spacing.md) {
                tunnelContent
            }
        }
    }

    @ViewBuilder
    private var tunnelContent: some View {
        switch tunnel.state {
        case .notInstalled:
            HStack(spacing: Spacing.md) {
                Image(systemName: "xmark.circle.fill")
                    .foregroundStyle(.secondary)
                VStack(alignment: .leading, spacing: 2) {
                    Text("cloudflared not installed")
                        .font(.system(size: 13, weight: .medium))
                    Text("Install with: brew install cloudflared")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button {
                    Task { await tunnel.detect() }
                } label: {
                    Label("Recheck", systemImage: "arrow.clockwise")
                        .font(.system(size: 11))
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
            }

        case .stopped:
            HStack(spacing: Spacing.sm) {
                Image(systemName: "circle.fill")
                    .font(.system(size: 8))
                    .foregroundStyle(.secondary)
                Text("Tunnel not active")
                    .font(.system(size: 13))
                    .foregroundStyle(.secondary)
                Spacer()
                Button {
                    tunnel.start()
                } label: {
                    Label("Start Tunnel", systemImage: "play.fill")
                        .font(.system(size: 11))
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
                .disabled(!webRunning)
            }
            if !webRunning {
                Text("Start the web service first")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }

        case .starting:
            HStack(spacing: Spacing.sm) {
                ProgressView().controlSize(.small)
                Text("Starting tunnel…")
                    .font(.system(size: 13))
                    .foregroundStyle(.secondary)
                Spacer()
            }

        case .active(let url):
            VStack(spacing: Spacing.sm) {
                HStack(spacing: Spacing.sm) {
                    StatusDot(isRunning: true)
                    Text("Active")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(Color.statusGreen)
                    Spacer()
                    Button(role: .destructive) {
                        tunnel.stop()
                    } label: {
                        Label("Stop Tunnel", systemImage: "stop.fill")
                            .font(.system(size: 11))
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                }
                urlRow(label: "Public", url: url, copied: $copiedTunnel)
            }

        case .failed(let msg):
            HStack(spacing: Spacing.sm) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(Color.statusRed)
                Text(msg)
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
                Spacer()
                Button {
                    tunnel.state = .stopped
                } label: {
                    Label("Dismiss", systemImage: "xmark")
                        .font(.system(size: 11))
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
            }
        }
    }

    // MARK: - QR Code Card

    private var qrCodeCard: some View {
        SectionCard(title: "QR Code", symbol: "qrcode") {
            VStack(spacing: Spacing.md) {
                HStack {
                    Spacer()
                    if let qrImage = generateQRCode(from: qrURL) {
                        Image(nsImage: qrImage)
                            .resizable()
                            .interpolation(.none)
                            .frame(width: 192, height: 192)
                            .background(Color.white)
                            .cornerRadius(12)
                    } else {
                        RoundedRectangle(cornerRadius: 12)
                            .fill(Color.primary.opacity(0.06))
                            .frame(width: 192, height: 192)
                    }
                    Spacer()
                }

                // Hint
                HStack(spacing: 4) {
                    Image(systemName: tunnel.state.isActive ? "network" : "wifi")
                        .font(.system(size: 10))
                    Text(tunnel.state.isActive ? "Accessible from anywhere" : "Local network only — start tunnel for remote access")
                        .font(.system(size: 11))
                }
                .foregroundStyle(.secondary)

                // Open in Browser button
                Button {
                    if let url = URL(string: qrURL) {
                        NSWorkspace.shared.open(url)
                    }
                } label: {
                    Label("Open in Browser", systemImage: "arrow.up.right.square")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .controlSize(.regular)
            }
        }
    }

    // MARK: - Reusable URL Row

    private func urlRow(label: String, url: String, copied: Binding<Bool>) -> some View {
        HStack(spacing: Spacing.sm) {
            Text(label)
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(.tertiary)
                .frame(width: 36, alignment: .trailing)
            Text(url)
                .font(.system(size: 11, design: .monospaced))
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .truncationMode(.middle)
            Spacer()
            Button {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(url, forType: .string)
                copied.wrappedValue = true
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { copied.wrappedValue = false }
            } label: {
                Label(copied.wrappedValue ? "Copied!" : "Copy",
                      systemImage: copied.wrappedValue ? "checkmark" : "doc.on.doc")
                    .font(.system(size: 11))
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
        }
    }

    private func loadPin() {
        guard let content = try? String(contentsOfFile: botEnvPath, encoding: .utf8) else { return }
        for line in content.components(separatedBy: "\n") {
            let t = line.trimmingCharacters(in: .whitespaces)
            if t.hasPrefix("WEB_PIN=") {
                pin = String(t.dropFirst("WEB_PIN=".count)).trimmingCharacters(in: .whitespaces)
                return
            }
        }
    }

    private func savePin() {
        let newPin = pinDraft.trimmingCharacters(in: .whitespaces)
        guard !newPin.isEmpty else { return }
        let content = (try? String(contentsOfFile: botEnvPath, encoding: .utf8)) ?? ""
        var lines = content.components(separatedBy: "\n")
        var found = false
        for i in lines.indices {
            let t = lines[i].trimmingCharacters(in: .whitespaces)
            if t.hasPrefix("WEB_PIN=") {
                lines[i] = "WEB_PIN=\(newPin)"
                found = true
                break
            }
        }
        if !found { lines.append("WEB_PIN=\(newPin)") }
        try? lines.joined(separator: "\n").write(toFile: botEnvPath, atomically: true, encoding: .utf8)
        pin = newPin
        pinEditing = false
        pinSaved = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { pinSaved = false }
    }

    private func checkWebHealth() async {
        guard let url = URL(string: "http://127.0.0.1:27184/health") else { return }
        var req = URLRequest(url: url)
        req.timeoutInterval = 2
        do {
            let (_, resp) = try await URLSession.shared.data(for: req)
            webRunning = (resp as? HTTPURLResponse)?.statusCode == 200
        } catch {
            webRunning = false
        }
    }

    private func generateQRCode(from string: String) -> NSImage? {
        guard let data = string.data(using: .utf8) else { return nil }
        let filter = CIFilter.qrCodeGenerator()
        filter.setValue(data, forKey: "inputMessage")
        filter.setValue("M", forKey: "inputCorrectionLevel")
        guard let output = filter.outputImage else { return nil }
        let scaled = output.transformed(by: CGAffineTransform(scaleX: 8, y: 8))
        let rep = NSCIImageRep(ciImage: scaled)
        let img = NSImage(size: rep.size)
        img.addRepresentation(rep)
        return img
    }
}
