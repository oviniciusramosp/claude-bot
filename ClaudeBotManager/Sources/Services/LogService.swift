import Foundation

actor LogService {
    private let logPath: String
    private var fileHandle: FileHandle?
    private(set) var entries: [LogEntry] = []
    private var continuation: AsyncStream<LogEntry>.Continuation?

    init(dataDir: String) {
        self.logPath = URL(fileURLWithPath: dataDir).appending(component: "bot.log").path
    }

    func loadRecent(lines: Int = 500) -> [LogEntry] {
        guard let content = try? String(contentsOfFile: logPath, encoding: .utf8) else { return [] }
        let allLines = content.components(separatedBy: "\n").filter { !$0.isEmpty }
        let recent = Array(allLines.suffix(lines))
        return recent.map { LogEntry.parse($0) }
    }

    func setContinuationAndStart(_ c: AsyncStream<LogEntry>.Continuation) {
        self.continuation = c
        startTailing()
    }

    private func startTailing() {
        guard let fh = FileHandle(forReadingAtPath: logPath) else { return }
        fh.seekToEndOfFile()
        self.fileHandle = fh

        let src = DispatchSource.makeFileSystemObjectSource(
            fileDescriptor: fh.fileDescriptor,
            eventMask: .write,
            queue: DispatchQueue.global(qos: .utility)
        )
        src.setEventHandler { [weak self] in
            guard let self else { return }
            Task { await self.readNewLines() }
        }
        src.resume()
    }

    private func readNewLines() {
        guard let fh = fileHandle else { return }
        let data = fh.availableData
        guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
        for line in text.components(separatedBy: "\n") where !line.isEmpty {
            let entry = LogEntry.parse(line)
            entries.append(entry)
            continuation?.yield(entry)
        }
    }

    deinit {
        fileHandle?.closeFile()
    }
}

extension LogService {
    nonisolated func makeStream() -> AsyncStream<LogEntry> {
        AsyncStream { [self] continuation in
            Task { await self.setContinuationAndStart(continuation) }
        }
    }
}
