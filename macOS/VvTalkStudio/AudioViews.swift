import AppKit
import AVFoundation
import SwiftUI
import UniformTypeIdentifiers

@MainActor
final class Playback: NSObject, ObservableObject, AVAudioPlayerDelegate {
    @Published private(set) var url: URL?
    @Published private(set) var time: Double = 0
    @Published private(set) var duration: Double = 0
    @Published private(set) var playing = false
    private var player: AVAudioPlayer?
    private var timer: Timer?

    func toggle(_ url: URL) throws {
        if self.url != url {
            clear()
            player = try AVAudioPlayer(contentsOf: url)
            player?.delegate = self
            self.url = url
            duration = player?.duration ?? 0
        }
        guard let player else { return }
        if player.isPlaying { pause() }
        else {
            if player.currentTime >= player.duration - 0.02 { player.currentTime = 0 }
            guard player.play() else { throw StudioError("无法播放这段音频。") }
            playing = true
            timer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { [weak self] _ in
                MainActor.assumeIsolated { self?.tick() }
            }
        }
    }

    private func tick() { time = player?.currentTime ?? 0 }

    func pause() {
        player?.pause()
        timer?.invalidate()
        timer = nil
        playing = false
        tick()
    }

    func clear() {
        pause()
        player = nil
        url = nil
        time = 0
        duration = 0
    }

    func seek(_ seconds: Double) {
        player?.currentTime = min(max(seconds, 0), duration)
        tick()
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in
            guard self.player === player else { return }
            pause()
            seek(0)
        }
    }
}

@MainActor
final class Recording: NSObject, ObservableObject, AVAudioRecorderDelegate {
    @Published private(set) var url: URL?
    @Published private(set) var active = false
    @Published private(set) var requesting = false
    @Published var error: String?
    private var recorder: AVAudioRecorder?
    private var folder: URL?
    private var closed = false

    func start() async {
        guard !requesting, !active else { return }
        requesting = true
        defer { requesting = false }
        error = nil
        let allowed = await AVCaptureDevice.requestAccess(for: .audio)
        guard !closed else { return }
        guard allowed else {
            error = "没有麦克风权限。可在系统设置的「隐私与安全性 → 麦克风」中授权，或导入音频。"
            return
        }
        do {
            let target = FileManager.default.temporaryDirectory.appendingPathComponent("vvtalk-\(UUID().uuidString)")
            try FileManager.default.createDirectory(at: target, withIntermediateDirectories: true)
            if let folder { try? FileManager.default.removeItem(at: folder) }
            folder = target
            url = nil
            let path = target.appendingPathComponent("麦克风录音.wav")
            let settings: [String: Any] = [
                AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: 44100, AVNumberOfChannelsKey: 1,
                AVLinearPCMBitDepthKey: 16, AVLinearPCMIsFloatKey: false
            ]
            let recorder = try AVAudioRecorder(url: path, settings: settings)
            recorder.delegate = self
            self.recorder = recorder
            guard recorder.record(forDuration: 180) else { throw StudioError("无法开始录音。请检查麦克风输入。") }
            active = true
        } catch { self.error = error.localizedDescription }
    }

    func stop() { recorder?.stop() }

    func clear() {
        guard !active, !requesting else { return }
        if let folder { try? FileManager.default.removeItem(at: folder) }
        folder = nil
        url = nil
    }

    func discard() {
        closed = true
        stop()
        if let folder { try? FileManager.default.removeItem(at: folder) }
    }

    nonisolated func audioRecorderDidFinishRecording(_ recorder: AVAudioRecorder, successfully flag: Bool) {
        Task { @MainActor in
            guard self.recorder === recorder, !closed else { return }
            self.recorder = nil
            active = false
            if flag { url = recorder.url }
            else { error = "录音未能保存，请重新录制。" }
        }
    }
}

struct ReferenceSheet: View {
    @ObservedObject var model: StudioModel
    @Environment(\.dismiss) private var dismiss
    @StateObject private var recording = Recording()
    @StateObject private var playback = Playback()
    @State private var language: Language
    @State private var text: String
    @State private var audio: URL?
    @State private var alignment: URL?
    @State private var vsqx: URL?
    @State private var fromVSQX = false
    @State private var automatic: Bool
    @State private var fmin = 65.0
    @State private var fmax = 650.0
    @State private var pitchMode = "absolute"

    init(model: StudioModel) {
        self.model = model
        _language = State(initialValue: model.language)
        _text = State(initialValue: model.text)
        _automatic = State(initialValue: model.alignment(model.language)["available"] as? Bool == true)
    }

    private var resources: JSON { model.alignment(language) }
    private var canAlign: Bool { resources["available"] as? Bool == true }
    private var selectedAudio: URL? { recording.url ?? audio }
    private var canSubmit: Bool {
        !model.busy && !recording.active && !recording.requesting &&
        (fromVSQX ? vsqx != nil : (selectedAudio != nil && !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Label("导入参考素材", systemImage: "waveform.badge.plus")
                .font(.title2.weight(.semibold))
            Text("从录音提取连续音高，或从 VSQX4 读取已有语调。")
                .foregroundStyle(.secondary)
            Form {
                Picker("来源", selection: $fromVSQX) {
                    Text("参考音频").tag(false)
                    Text("VSQX4 工程").tag(true)
                }
                .pickerStyle(.segmented)
                Picker("语言", selection: $language) {
                    ForEach(Language.allCases) { Text($0.name).tag($0) }
                }
                if fromVSQX {
                    LabeledContent("工程文件") {
                        Button(vsqx?.lastPathComponent ?? "选择 VSQX…") { vsqx = choose(["vsqx"]) ?? vsqx }
                    }
                    Text("VSQX 使用工程歌词，并按所选语言解释发音单元。")
                        .foregroundStyle(.secondary)
                } else {
                    LabeledContent("音频文件") {
                        Button(audio?.lastPathComponent ?? "选择 WAV / FLAC / AIFF…") { audio = choose(["wav", "flac", "aif", "aiff"]) ?? audio }
                            .disabled(recording.active || recording.url != nil)
                    }
                    LabeledContent("麦克风") {
                        HStack {
                            if recording.active {
                                Label("录音中", systemImage: "record.circle.fill").foregroundStyle(.red)
                                Button("停止") { recording.stop() }
                            } else {
                                Button(recording.url == nil ? "开始录音" : "重新录音") {
                                    playback.clear()
                                    Task { await recording.start() }
                                }.disabled(recording.requesting)
                                if let url = recording.url {
                                    Button(playback.playing ? "暂停" : "播放录音") {
                                        do { try playback.toggle(url) }
                                        catch { recording.error = error.localizedDescription }
                                    }
                                    Button("移除录音") { playback.clear(); recording.clear() }
                                }
                            }
                        }
                    }
                    if let error = recording.error { Text(error).foregroundStyle(.red) }
                    LabeledContent("时间标注") {
                        HStack {
                            Button(alignment?.lastPathComponent ?? "选择 CSV / TextGrid…") { alignment = choose(["csv", "textgrid"]) ?? alignment }
                            if alignment != nil { Button("清除") { alignment = nil } }
                        }
                    }
                    if alignment == nil {
                        Picker("无标注时", selection: $automatic) {
                            Text("均分草稿（需手动核对）").tag(false)
                            if canAlign { Text("使用本机 MFA 自动对齐").tag(true) }
                        }
                        if !canAlign { Text("本机 MFA 未就绪。均分只估算时间，不代表真实对齐。").foregroundStyle(.secondary) }
                    }
                    Text("请填入录音中的原文，(language.name)标注须与每(language.unit)一一对应。")
                        .foregroundStyle(.secondary)
                    TextEditor(text: $text)
                        .font(.body)
                        .frame(minHeight: 78)
                        .accessibilityLabel("录音原文")
                        .overlay(RoundedRectangle(cornerRadius: 5).strokeBorder(.quaternary))
                    DisclosureGroup("音高提取设置") {
                        Picker("音高", selection: $pitchMode) {
                            Text("保留原录音音高").tag("absolute")
                            Text("移到文稿基准音高").tag("relative")
                        }
                        TextField("最低基频 (Hz)", value: $fmin, format: .number)
                        TextField("最高基频 (Hz)", value: $fmax, format: .number)
                    }
                }
            }
            .disabled(model.busy)
            .onChange(of: language) {
                if text == model.text { text = "" }
                automatic = canAlign
            }
            .onChange(of: fromVSQX) { playback.clear() }
            if model.busy || model.hasError {
                HStack {
                    if model.busy { ProgressView().controlSize(.small) }
                    Text(model.status).foregroundStyle(model.hasError ? Color.red : Color.secondary)
                }
            }
            HStack {
                Spacer()
                Button("取消") { dismiss() }
                    .keyboardShortcut(.cancelAction)
                    .disabled(model.busy)
                Button("导入并分析") {
                    playback.clear()
                    Task {
                        if await model.importReference(audio: fromVSQX ? nil : selectedAudio,
                                                       alignment: alignment, vsqx: fromVSQX ? vsqx : nil,
                                                       text: text, language: language, automatic: automatic,
                                                       fmin: fmin, fmax: fmax, pitchMode: pitchMode) { dismiss() }
                    }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(!canSubmit)
            }
        }
        .padding(22)
        .frame(width: 580)
        .interactiveDismissDisabled(model.busy)
        .onDisappear { playback.clear(); recording.discard() }
    }

    private func choose(_ extensions: [String]) -> URL? {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = extensions.compactMap { UTType(filenameExtension: $0) }
        return panel.runModal() == .OK ? panel.url : nil
    }
}
