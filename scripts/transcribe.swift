// Transcribe an audio file with Apple's on-device SpeechAnalyzer (macOS 26+).
//
// Replaces `hear` (SFSpeechRecognizer) for Telegram voice messages: hear
// returned only fragments of longer messages ("Bom dia obrigado" for a
// three-sentence note), while SpeechTranscriber keeps the whole text, adds
// punctuation, runs offline and reads OGG/Opus directly (no ffmpeg step).
//
// Build (the bot does this on its own when swiftc is available):
//   swiftc -O -parse-as-library scripts/transcribe.swift -o ~/.claude-bot/bin/transcribe
// Usage:
//   transcribe <audio-file> [locale]      (default locale pt-BR)
// Prints the transcription on stdout. Exit codes: 0 ok, 1 error,
// 2 usage, 3 locale not supported.
import AVFoundation
import Foundation
import Speech

@main
struct Transcribe {
    static func fail(_ message: String, _ code: Int32) -> Never {
        FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
        exit(code)
    }

    static func main() async {
        let args = CommandLine.arguments
        guard args.count >= 2 else { fail("usage: transcribe <audio-file> [locale]", 2) }
        let url = URL(fileURLWithPath: args[1])
        let wanted = Locale(identifier: args.count > 2 ? args[2] : "pt-BR")
        do {
            guard let locale = await SpeechTranscriber.supportedLocale(equivalentTo: wanted) else {
                fail("locale not supported: \(wanted.identifier)", 3)
            }
            let transcriber = SpeechTranscriber(locale: locale, transcriptionOptions: [],
                                                reportingOptions: [], attributeOptions: [])
            // First use of a language downloads its on-device model.
            if let request = try await AssetInventory.assetInstallationRequest(supporting: [transcriber]) {
                try await request.downloadAndInstall()
            }
            let analyzer = SpeechAnalyzer(modules: [transcriber])
            let file = try AVAudioFile(forReading: url)
            async let text: String = {
                var out = ""
                for try await result in transcriber.results { out += String(result.text.characters) }
                return out
            }()
            if let last = try await analyzer.analyzeSequence(from: file) {
                try await analyzer.finalizeAndFinish(through: last)
            } else {
                await analyzer.cancelAndFinishNow()
            }
            print(try await text.trimmingCharacters(in: .whitespacesAndNewlines))
        } catch {
            fail("error: \(error)", 1)
        }
    }
}
