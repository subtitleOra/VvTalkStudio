import AppKit
import SwiftUI

struct StudioView: View {
    @ObservedObject var model: StudioModel
    @StateObject private var player = Playback()
    @State private var inspectorVisible = true
    @State private var showWarnings = false
    @Environment(\.undoManager) private var undo

    var body: some View {
        NavigationSplitView {
            sidebar
                .navigationSplitViewColumnWidth(min: 185, ideal: 214, max: 300)
        } detail: {
            VStack(spacing: 0) {
                HSplitView {
                    workspace
                        .frame(minWidth: 490, maxWidth: .infinity, maxHeight: .infinity)
                    if inspectorVisible {
                        Inspector(model: model)
                            .frame(minWidth: 264, idealWidth: 305, maxWidth: 405, maxHeight: .infinity)
                            .background(.regularMaterial)
                    }
                }
                .disabled(model.busy)
                Divider()
                statusBar
            }
            .navigationTitle("VvTalk Studio")
            .toolbar { toolbar }
        }
        .frame(minWidth: 965, minHeight: 625)
        .sheet(isPresented: $model.showReference) { ReferenceSheet(model: model) }
        .task { model.undo = undo; await model.bootstrap() }
        .onChange(of: model.sourceAudio) { stopIfUnavailable() }
        .onChange(of: model.previewAudio) { stopIfUnavailable() }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.willTerminateNotification)) { _ in
            model.persistDraft(flush: true)
        }
    }

    private func stopIfUnavailable() {
        if let url = player.url, url != model.sourceAudio, url != model.previewAudio { player.clear() }
    }

    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 0) {
            List(selection: Binding<String?>(get: { model.selection }, set: { model.selection = $0 ?? StudioModel.full })) {
                Section("工作台") {
                    Label(model.isReference ? "参考语调" : "全文", systemImage: model.isReference ? "waveform" : "doc.text")
                        .tag(StudioModel.full)
                }
                if !model.sentences.isEmpty {
                    Section("句子 · \(model.sentences.count)") {
                        ForEach(Array(model.sentences.enumerated()), id: \.element.id) { index, sentence in
                            HStack(alignment: .top, spacing: 8) {
                                Text(String(format: "%02d", index + 1))
                                    .font(.caption.monospacedDigit())
                                    .foregroundStyle(.secondary)
                                    .padding(.top, 2)
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(sentence.text.trimmingCharacters(in: .whitespacesAndNewlines))
                                        .lineLimit(2)
                                    Text("\(fixed(sentence.offset))s  ·  \(fixed(sentence.duration))s")
                                        .font(.caption2.monospacedDigit())
                                        .foregroundStyle(.secondary)
                                }
                            }
                            .padding(.vertical, 3)
                            .tag(sentence.id)
                        }
                    }
                }
            }
            .listStyle(.sidebar)
            .disabled(model.busy)
            if !model.isReference && model.sentences.isEmpty {
                Text("生成语调后，句子会列在这里。")
                    .font(.caption).foregroundStyle(.secondary)
                    .padding(.horizontal, 16).padding(.bottom, 10)
            }
            Divider().padding(.horizontal, 12)
            HStack {
                Button { model.newProject() } label: {
                    Label("新建", systemImage: "plus").labelStyle(.iconOnly)
                }.help("新建文稿")
                Button { Task { await model.open() } } label: {
                    Label("打开", systemImage: "folder").labelStyle(.iconOnly)
                }.help("打开文稿")
                Spacer()
                if !model.appVersion.isEmpty {
                    Text("VvTalk \(model.appVersion)").font(.caption2).foregroundStyle(.secondary)
                }
            }
            .buttonStyle(.borderless)
            .padding(12)
            .disabled(model.busy)
        }
    }

    private var workspace: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .center, spacing: 12) {
                VStack(alignment: .leading, spacing: 3) {
                    TextField("未命名文稿", text: Binding(get: { model.title }, set: model.setTitle))
                        .textFieldStyle(.plain)
                        .font(.system(size: 24, weight: .semibold))
                        .accessibilityLabel("文稿标题")
                    HStack(spacing: 5) {
                        Circle().fill(model.dirty ? Color.orange : Color.secondary.opacity(0.65))
                            .frame(width: 6, height: 6)
                        Text(model.dirty ? "有未保存的修改" : model.projectURL == nil ? "本地工作台" : "已保存")
                    }
                    .font(.caption).foregroundStyle(.secondary)
                }
                Spacer(minLength: 10)
                Picker("文稿语言", selection: Binding(get: { model.language }, set: model.setLanguage)) {
                    ForEach(Language.allCases) { Text($0.name).tag($0) }
                }
                .labelsHidden()
                .fixedSize()
                .disabled(model.isReference)
                .help(model.isReference ? "参考曲线使用导入时的语言" : "更换文稿语言")
            }
            .padding(.bottom, 16)
            VSplitView {
                editor.frame(minHeight: 155, idealHeight: 220, maxHeight: .infinity)
                PitchView(model: model, player: player)
                    .padding(.top, 10)
                    .frame(minHeight: 230, idealHeight: 335, maxHeight: .infinity)
            }
        }
        .padding(18)
        .background(Color(nsColor: .controlBackgroundColor))
    }

    private var editor: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label(model.isReference ? "参考文稿" : model.selectedSentence == nil ? "全文文稿" : "当前句子",
                      systemImage: model.isReference ? "text.quote" : "doc.plaintext")
                    .font(.headline)
                Spacer()
                if !model.hasText && !model.isReference {
                    Button("载入示例") { model.fillSample() }.controlSize(.small)
                } else if model.isReference {
                    Text("跟随参考素材").font(.caption).foregroundStyle(.secondary)
                } else if let sentence = model.selectedSentence {
                    Text("起点 \(fixed(sentence.offset)) 秒").font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                }
                if !model.isReference {
                    Button("生成语调") { Task { await model.generate() } }
                        .buttonStyle(.borderedProminent)
                        .controlSize(.small)
                        .disabled(!model.canGenerate)
                        .help("生成语调 (⌘↩)")
                }
            }
            Group {
                if model.isReference {
                    ScrollView {
                        Text(model.text).textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(10)
                    }
                } else {
                    ZStack(alignment: .topLeading) {
                        TextEditor(text: Binding(get: { model.selectedText }, set: model.setText))
                            .font(.system(size: 15))
                            .scrollContentBackground(.hidden)
                            .padding(6)
                            .accessibilityLabel("文稿正文")
                        if model.selectedText.isEmpty {
                            Text("在这里输入\(model.language.name)文稿，使用标点或换行分句。")
                                .foregroundStyle(.tertiary)
                                .padding(.horizontal, 12).padding(.vertical, 14)
                                .allowsHitTesting(false)
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(.quaternary))
        }
        .padding(.bottom, 10)
    }

    @ToolbarContentBuilder private var toolbar: some ToolbarContent {
        ToolbarItemGroup(placement: .primaryAction) {
            Button { model.beginReference() } label: { Label("导入参考", systemImage: "waveform.badge.plus") }
                .disabled(model.busy)
            Button { Task { await model.renderPreview() } } label: { Label("ACE 试听", systemImage: "headphones") }
                .disabled(!model.canSave || model.previewing)
                .help("使用 ACE Studio 合成当前范围的试听")
        }
        ToolbarItemGroup(placement: .automatic) {
            Button { Task { await model.save() } } label: { Label("保存", systemImage: "square.and.arrow.down") }
                .disabled(!model.canSave)
            Menu {
                Picker("目标引擎", selection: $model.target) {
                    ForEach(Target.allCases) { Text($0.title).tag($0) }
                }
                Button("导出 \(model.target.ext.uppercased())…") { Task { await model.export() } }
                    .disabled(!model.canSave)
                Divider()
                Button("复制 SV2 脚本数据") { Task { await model.copySynthV() } }.disabled(!model.canSave)
                Button("安装 SV2 导入脚本") { Task { await model.installSynthV() } }
            } label: { Label("导出", systemImage: "square.and.arrow.up") }
                .disabled(model.busy)
            Button { inspectorVisible.toggle() } label: {
                Label("检查器", systemImage: "sidebar.right")
            }.help(inspectorVisible ? "隐藏检查器" : "显示检查器")
        }
    }

    private var statusBar: some View {
        HStack(spacing: 8) {
            if model.busy { ProgressView().controlSize(.small) }
            else {
                Image(systemName: model.hasError ? "exclamationmark.circle.fill" : "circle.fill")
                    .font(.system(size: model.hasError ? 12 : 7))
                    .foregroundStyle(model.hasError ? Color.red : Color.accentColor)
            }
            Text(model.status)
                .font(.caption)
                .foregroundStyle(model.hasError ? Color.red : Color.secondary)
                .lineLimit(1)
                .help(model.status)
            Spacer()
            if !model.warnings.isEmpty {
                Button { showWarnings.toggle() } label: {
                    Label("\(model.warnings.count) 条提示", systemImage: "exclamationmark.triangle")
                }
                .controlSize(.small)
                .popover(isPresented: $showWarnings, arrowEdge: .top) {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 8) {
                            ForEach(Array(model.warnings.enumerated()), id: \.offset) { _, warning in
                                Text(warning).font(.callout).textSelection(.enabled)
                            }
                        }
                        .padding()
                    }
                    .frame(width: 350, height: min(250, CGFloat(model.warnings.count * 48 + 26)))
                }
            }
            if let url = model.outputURL {
                Button { NSWorkspace.shared.activateFileViewerSelecting([url]) } label: {
                    Label("显示输出", systemImage: "folder")
                }.controlSize(.small)
            }
        }
        .padding(.horizontal, 13)
        .frame(minHeight: 34)
        .background(.bar)
    }
}
