import Foundation

/// Watches a file or directory for changes using DispatchSource.
final class FileWatcher: @unchecked Sendable {
    private var sources: [DispatchSourceFileSystemObject] = []
    private var pendingWorkItems: [String: DispatchWorkItem] = [:]
    private let debounceInterval: TimeInterval = 1.0

    func watch(path: String, queue: DispatchQueue = .main, onChange: @escaping @Sendable () -> Void) {
        let fd = open(path, O_EVTONLY)
        guard fd >= 0 else { return }

        let src = DispatchSource.makeFileSystemObjectSource(
            fileDescriptor: fd,
            eventMask: [.write, .rename, .delete, .attrib],
            queue: queue
        )
        src.setEventHandler { [weak self] in
            guard let self else { return }
            // Cancel any pending callback for this path
            self.pendingWorkItems[path]?.cancel()
            // Schedule a new debounced callback
            let workItem = DispatchWorkItem(block: onChange)
            self.pendingWorkItems[path] = workItem
            queue.asyncAfter(deadline: .now() + self.debounceInterval, execute: workItem)
        }
        src.setCancelHandler { close(fd) }
        src.resume()
        sources.append(src)
    }

    func stopAll() {
        for (_, item) in pendingWorkItems { item.cancel() }
        pendingWorkItems.removeAll()
        for src in sources { src.cancel() }
        sources.removeAll()
    }

    deinit { stopAll() }
}
