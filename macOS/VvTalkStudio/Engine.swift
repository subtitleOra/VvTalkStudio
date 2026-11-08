import Foundation

typealias JSON = [String: Any]

struct StudioError: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}

/// The helper owns the existing Python engine. Its stdin closing also ends its lifetime.
final class Engine: @unchecked Sendable {
    // All process and pipe state is confined to this queue.
    private let queue = DispatchQueue(label: "studio.vvtalk.engine")
    private var process: Process?
    private var input: FileHandle?
    private var output: FileHandle?

    func call(_ action: String, _ payload: JSON = [:]) async throws -> JSON {
        try await withCheckedThrowingContinuation { continuation in
            queue.async {
                continuation.resume(with: Result { try self.request(action, payload) })
            }
        }
    }

    private func start() throws {
        let executable = Bundle.main.bundleURL
            .appendingPathComponent("Contents/Helpers/VvTalkEngine.app/Contents/MacOS/VvTalkEngine")
        guard FileManager.default.isExecutableFile(atPath: executable.path) else {
            throw StudioError("找不到内置分析引擎。请重新在 Xcode 中构建。")
        }
        let task = Process()
        let toEngine = Pipe(), fromEngine = Pipe()
        _ = fcntl(toEngine.fileHandleForWriting.fileDescriptor, F_SETNOSIGPIPE, 1)
        task.executableURL = executable
        task.standardInput = toEngine
        task.standardOutput = fromEngine
        task.standardError = FileHandle.standardError
        try task.run()
        process = task
        input = toEngine.fileHandleForWriting
        output = fromEngine.fileHandleForReading
    }

    private func readExactly(_ size: Int, from handle: FileHandle) throws -> Data {
        var bytes = Data()
        bytes.reserveCapacity(size)
        while bytes.count < size {
            guard let part = try handle.read(upToCount: min(size - bytes.count, 1024 * 1024)), !part.isEmpty else {
                throw StudioError("分析引擎意外退出。请重试，或在 Xcode 控制台查看错误。")
            }
            bytes.append(part)
        }
        return bytes
    }

    private func request(_ action: String, _ payload: JSON) throws -> JSON {
        if process?.isRunning != true { try start() }
        guard let input, let output else { throw StudioError("无法连接分析引擎。") }
        let body = try JSONSerialization.data(withJSONObject: ["action": action, "payload": payload])
        guard body.count <= 92 * 1024 * 1024 else { throw StudioError("工程数据过大，请分段处理。") }
        var size = UInt32(body.count).bigEndian
        do {
            try input.write(contentsOf: withUnsafeBytes(of: &size) { Data($0) })
            try input.write(contentsOf: body)
        } catch {
            throw StudioError("分析引擎连接已关闭。请重试。")
        }
        let header = try readExactly(4, from: output)
        let length = header.reduce(0) { ($0 << 8) | Int($1) }
        guard (1...(384 * 1024 * 1024)).contains(length),
              let response = try JSONSerialization.jsonObject(with: readExactly(length, from: output)) as? JSON else {
            throw StudioError("分析引擎返回了无效数据。")
        }
        if let error = response["error"] as? String { throw StudioError(error) }
        guard let result = response["value"] as? JSON else { throw StudioError("分析结果为空。") }
        return result
    }
}
