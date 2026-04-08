import Foundation

/// Watches a file or directory for changes using DispatchSource.
final class FileWatcher: @unchecked Sendable {
    private var sources: [DispatchSourceFileSystemObject] = []

    func watch(path: String, queue: DispatchQueue = .main, onChange: @escaping @Sendable () -> Void) {
        let fd = open(path, O_EVTONLY)
        guard fd >= 0 else { return }

        let src = DispatchSource.makeFileSystemObjectSource(
            fileDescriptor: fd,
            eventMask: [.write, .rename, .delete, .attrib],
            queue: queue
        )
        src.setEventHandler(handler: onChange)
        src.setCancelHandler { close(fd) }
        src.resume()
        sources.append(src)
    }

    func stopAll() {
        for src in sources { src.cancel() }
        sources.removeAll()
    }

    deinit { stopAll() }
}
