import Foundation
import SwiftUI

struct QQVoiceSettings: Decodable {
    var port = 3000
    var token = ""

    static func load() -> Self {
        guard let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first,
              let data = try? Data(contentsOf: support.appendingPathComponent("VvTalkStudio/qq-onebot.json")),
              let settings = try? JSONDecoder().decode(Self.self, from: data) else { return Self() }
        return settings
    }
}

struct QQGroup: Decodable, Identifiable {
    let group_id: Int64
    let group_name: String

    var id: Int64 { group_id }
    var label: String { "\(group_name)（\(group_id)）" }
}

struct QQVoiceConnection {
    let settings: QQVoiceSettings

    struct Account: Decodable {
        let user_id: Int64
        let nickname: String
    }

    private struct Response<Payload: Decodable>: Decodable {
        let retcode: Int
        let data: Payload?
        let message: String?
        let wording: String?
    }

    private struct SentMessage: Decodable {
        let message_id: Int64
    }

    private final class LocalRequest: NSObject, URLSessionTaskDelegate {
        func urlSession(_ session: URLSession, task: URLSessionTask,
                        willPerformHTTPRedirection response: HTTPURLResponse,
                        newRequest request: URLRequest) async -> URLRequest? { nil }
    }

    private static let session = URLSession(configuration: .ephemeral)

    func destinations() async throws -> (Account, [QQGroup]) {
        let account: Account = try await call("get_login_info")
        let groups: [QQGroup] = try await call("get_group_list")
        return (account, groups.sorted { $0.label.localizedStandardCompare($1.label) == .orderedAscending })
    }

    func send(audio: URL, to group: QQGroup) async throws {
        let file = try audio.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
        guard file.isRegularFile == true, let size = file.fileSize, size > 0 else {
            throw StudioError("找不到试听音频，请重新合成。")
        }
        guard size <= 16 * 1024 * 1024 else {
            throw StudioError("试听文件超过 16 MB。请在侧栏选择较短的句子并重新合成。")
        }
        let content = try Data(contentsOf: audio).base64EncodedString()
        let record = ["type": "record", "data": ["file": "base64://\(content)"]] as JSON
        let _: SentMessage = try await call("send_group_msg", ["group_id": group.id, "message": [record]])
    }

    private func call<Payload: Decodable>(_ action: String, _ body: JSON = [:]) async throws -> Payload {
        let token = settings.token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard (1...65535).contains(settings.port), !token.isEmpty, !token.contains(where: \.isNewline),
              let url = URL(string: "http://127.0.0.1:\(settings.port)/\(action)") else {
            throw StudioError("请填写有效的 OneBot HTTP 端口和 Token。")
        }
        var request = URLRequest(url: url, timeoutInterval: action == "send_group_msg" ? 60 : 8)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await Self.session.data(for: request, delegate: LocalRequest())
        } catch let error as URLError where error.code == .cannotConnectToHost {
            throw StudioError("无法连接本机 OneBot。请启动 NapCat、登录 QQ，并检查 HTTP 端口。")
        } catch {
            if action == "send_group_msg" {
                throw StudioError("未能确认发送结果。请先在 QQ 群内检查，再决定是否重试。")
            }
            throw error
        }
        guard let http = response as? HTTPURLResponse else { throw StudioError("OneBot 返回了无效响应。") }
        if [401, 403].contains(http.statusCode) {
            throw StudioError("OneBot 拒绝访问。请核对 HTTP 服务的 Token。")
        }
        guard (200...299).contains(http.statusCode) else {
            throw StudioError("OneBot 请求失败（HTTP \(http.statusCode)）。")
        }
        guard let result = try? JSONDecoder().decode(Response<Payload>.self, from: data) else {
            throw StudioError(action == "send_group_msg"
                              ? "未能确认发送结果。请先在 QQ 群内检查，再决定是否重试。"
                              : "端口未返回 OneBot 数据。请填写 HTTP 服务端的端口。")
        }
        guard result.retcode == 0, let payload = result.data else {
            let detail = result.wording.flatMap { $0.isEmpty ? nil : $0 } ?? result.message ?? ""
            throw StudioError("OneBot 请求失败（\(result.retcode)）。\(detail.prefix(180))")
        }
        return payload
    }
}

struct QQVoiceSheet: View {
    let audio: URL
    @Binding var settings: QQVoiceSettings
    let didSend: (QQGroup) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var account: QQVoiceConnection.Account?
    @State private var groups: [QQGroup] = []
    @State private var selection: Int64?
    @State private var working = false
    @State private var error: String?

    private var group: QQGroup? { groups.first { $0.id == selection } }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Label("发送到 QQ 群", systemImage: "waveform.bubble")
                .font(.title2.weight(.semibold))
            Text("将这段 ACE 试听作为 QQ 语音消息发送。")
                .foregroundStyle(.secondary)
            Form {
                TextField("OneBot HTTP 端口", value: $settings.port, format: .number.grouping(.never))
                SecureField("OneBot Token", text: $settings.token)
                Button("连接并读取群列表") { Task { await connect() } }
                    .disabled(settings.token.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                if let account {
                    LabeledContent("发送账号", value: "\(account.nickname)（\(account.user_id)）")
                    if groups.isEmpty {
                        Text("这个账号没有可选的群聊。").foregroundStyle(.secondary)
                    } else {
                        Picker("目标群", selection: $selection) {
                            Text("请选择群聊").tag(nil as Int64?)
                            ForEach(groups) { Text($0.label).tag(Optional($0.id)) }
                        }
                    }
                }
            }
            .disabled(working)
            if let error {
                Text(error).foregroundStyle(.red).fixedSize(horizontal: false, vertical: true)
            }
            HStack {
                if working { ProgressView().controlSize(.small) }
                Spacer()
                Button("取消") { dismiss() }.keyboardShortcut(.cancelAction).disabled(working)
                Button("发送语音") {
                    if let group { Task { await send(group) } }
                }
                .buttonStyle(.borderedProminent)
                .disabled(group == nil || working)
            }
        }
        .padding(24)
        .frame(width: 475)
        .interactiveDismissDisabled(working)
        .onChange(of: settings.port) { resetDestinations() }
        .onChange(of: settings.token) { resetDestinations() }
    }

    private func resetDestinations() {
        account = nil
        groups = []
        selection = nil
        error = nil
    }

    private func connect() async {
        guard !working else { return }
        resetDestinations()
        working = true
        defer { working = false }
        do {
            let (connected, destinations) = try await QQVoiceConnection(settings: settings).destinations()
            account = connected
            groups = destinations
        } catch { self.error = error.localizedDescription }
    }

    private func send(_ group: QQGroup) async {
        guard !working else { return }
        working = true
        error = nil
        defer { working = false }
        do {
            try await QQVoiceConnection(settings: settings).send(audio: audio, to: group)
            didSend(group)
            dismiss()
        } catch { self.error = error.localizedDescription }
    }
}
