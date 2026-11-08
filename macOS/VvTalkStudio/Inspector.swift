import SwiftUI

struct Inspector: View {
    enum Tab: String, CaseIterable { case settings = "语调参数", units = "发音单元" }
    @ObservedObject var model: StudioModel
    @State private var tab: Tab = .settings
    @State private var index: Int? = 0

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Label("检查器", systemImage: "slider.horizontal.3").font(.headline)
                Spacer()
                Text(model.language.name).font(.caption).foregroundStyle(.secondary)
            }
            Picker("检查器", selection: $tab) {
                ForEach(Tab.allCases, id: \.self) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            switch tab {
            case .settings: settings
            case .units: units
            }
        }
        .padding(14)
        .onChange(of: model.isReference) { _, reference in
            tab = reference ? .units : .settings
            index = 0
        }
        .onChange(of: model.selection) { _, selection in
            index = 0
            if selection != StudioModel.full { tab = .units }
        }
    }

    private var settings: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                GroupBox("ACE 试听与导出") {
                    VStack(alignment: .leading, spacing: 9) {
                        if model.aceVoices.isEmpty {
                            Text(model.loadingVoices ? "正在读取声库…" : "声库列表未载入")
                                .foregroundStyle(.secondary)
                        } else {
                            Picker("声库", selection: Binding(get: { model.selectedACEVoice }, set: model.selectACEVoice)) {
                                ForEach(model.aceVoices) { voice in
                                    Text(voice.name).tag(voice.id)
                                }
                            }
                            .disabled(model.busy)
                        }
                        Text("使用 Verse23 模型。试听需要在 ACE Studio 解锁所选声库。")
                            .foregroundStyle(.secondary)
                    }
                    .font(.caption)
                    .padding(.vertical, 6)
                }
                if model.isReference {
                    Text("可在音高图调整参考曲线的音高和幅度，在「发音单元」精确设置音符时间与基准音高。")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                } else {
                    GroupBox("全文 · 声音") {
                        VStack(spacing: 9) {
                            ForEach(Parameter.voice) { parameter in parameterRow(parameter) }
                        }
                        .padding(.vertical, 6)
                    }
                    GroupBox("全文 · 停顿") {
                        VStack(spacing: 9) {
                            ForEach(Parameter.pauses) { parameter in parameterRow(parameter) }
                        }
                        .padding(.vertical, 6)
                    }
                    if model.selectedSentence != nil {
                        GroupBox("本句覆盖") {
                            VStack(alignment: .leading, spacing: 9) {
                                Text("留空使用全文参数。语速与全文倍率相乘。")
                                    .font(.caption).foregroundStyle(.secondary)
                                ForEach(Parameter.voice.filter { $0.id != "bpm" } + Parameter.pauses + [Parameter.tail]) {
                                    parameterRow($0, local: true)
                                }
                            }
                            .padding(.vertical, 6)
                        }
                        .id(model.selection)
                    }
                }
                GroupBox("引擎") {
                    VStack(alignment: .leading, spacing: 9) {
                        Label(model.aceConnected ? "ACE 试听已连接" : "ACE 试听未连接",
                              systemImage: model.aceConnected ? "checkmark.circle.fill" : "circle")
                            .foregroundStyle(model.aceConnected ? Color.green : Color.secondary)
                        ForEach(Target.allCases.filter { $0 != .vocaloid5 }) { target in
                            let host = model.hosts[target.rawValue]
                            LabeledContent(target.title) {
                                Text(host == nil ? "检测中" : host?["installed"] as? Bool == true ? "已安装" : "未检测到")
                                    .foregroundStyle(.secondary)
                            }
                            .help(host?["path"] as? String ?? "")
                        }
                        Button("刷新引擎状态") { Task { await model.refreshHosts() } }
                    }
                    .font(.caption)
                    .padding(.vertical, 6)
                }
            }
        }
    }

    private func parameterRow(_ parameter: Parameter, local: Bool = false) -> some View {
        HStack {
            Text(parameter.label)
            Spacer(minLength: 8)
            let value = model.value(parameter, local: local)
            let digits = parameter.step < 1 ? 2 : 0
            EditableField(value: value.map { fixed($0, digits: digits) } ?? "", placeholder: local ? "自动" : "",
                          label: parameter.label) { raw in
                if raw.isEmpty && local { model.setParameter(parameter, value: nil, local: true); return }
                model.setParameter(parameter, value: try numeric(raw, range: parameter.range), local: local)
            } onError: { model.report($0, error: true) }
                .frame(width: 56)
            Stepper(parameter.label, onIncrement: {
                let current = value ?? parameter.initial
                model.setParameter(parameter, value: min(parameter.range.upperBound, current + parameter.step), local: local)
            }, onDecrement: {
                let current = value ?? parameter.initial
                model.setParameter(parameter, value: max(parameter.range.lowerBound, current - parameter.step), local: local)
            }).labelsHidden()
            Text(parameter.unit).font(.caption).foregroundStyle(.secondary).frame(width: 32, alignment: .leading)
        }
        .font(.callout)
    }

    private var units: some View {
        let rows = model.units
        return Group {
            if rows.isEmpty {
                VStack(spacing: 8) {
                    Image(systemName: "textformat").font(.title2)
                    Text("未选择发音单元").font(.callout.weight(.medium))
                    Text("生成后，从侧边栏选一句编辑读音、时长和停顿。")
                        .font(.caption).multilineTextAlignment(.center)
                }
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                List(selection: $index) {
                    ForEach(rows.indices, id: \.self) { row in
                        let unit = rows[row]
                        HStack(spacing: 8) {
                            Text("\(row + 1)").monospacedDigit().foregroundStyle(.secondary)
                                .frame(minWidth: 18, alignment: .trailing)
                            Text(unit["lyric"] as? String ?? "").fontWeight(.medium).lineLimit(1)
                            Spacer()
                            Text(unit["reading"] as? String ?? unit["pinyin"] as? String ?? "")
                                .foregroundStyle(.secondary).lineLimit(1)
                        }
                        .font(.callout)
                        .tag(row)
                    }
                }
                .listStyle(.inset(alternatesRowBackgrounds: true))
                .frame(minHeight: 95, maxHeight: .infinity)
                if let row = index, rows.indices.contains(row) {
                    ScrollView { unitDetail(rows[row], row: row) }
                        .frame(minHeight: 150, maxHeight: 280)
                        .id("\(model.selection)-\(row)")
                }
                Button(model.isReference ? "恢复原参考音符" : "重置本句单元") { model.resetUnits() }
                    .controlSize(.small)
            }
        }
    }

    private func unitDetail(_ unit: JSON, row: Int) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(unit["lyric"] as? String ?? "").font(.title3.bold())
            if model.isReference {
                Text("调整音符时间时，参考曲线保留在录音时间轴上。").font(.caption).foregroundStyle(.secondary)
                unitNumber(unit, row: row, key: "start", label: "开始 (s)", range: 0...(model.timeline?.duration ?? 3600), digits: 3)
                unitNumber(unit, row: row, key: "end", label: "结束 (s)", range: 0...(model.timeline?.duration ?? 3600), digits: 3)
                unitNumber(unit, row: row, key: "key", label: "基准音高 (MIDI)", range: 0...127, integer: true)
            }
            if !model.isReference || model.language != .zh {
                let key = model.language == .zh ? "pinyin_override" : "pronunciation_override"
                let automatic = unit["auto_reading"] as? String ?? unit["reading"] as? String ?? unit["pinyin"] as? String ?? "自动"
                unitRow(model.language.reading, value: unit[key] as? String ?? "", placeholder: automatic) { raw in
                    model.setUnit(at: row, key: key, value: raw.isEmpty ? nil : raw)
                }
            }
            if model.language == .ja {
                unitNumber(unit, row: row, key: "accent_override", label: "拍音高 (0 / 1)", range: 0...1,
                           placeholder: (unit["auto_accent"] as? Int).map(String.init) ?? "自动", integer: true)
            } else if model.language == .en {
                let format: ([Int]?) -> String = { $0?.map(String.init).joined(separator: " ") ?? "" }
                unitRow("音节重音", value: format(unit["stress_override"] as? [Int]),
                        placeholder: format(unit["stress"] as? [Int])) { raw in
                    let tokens = raw.split(whereSeparator: { $0.isWhitespace || $0 == "," })
                    let values = tokens.compactMap { Int($0) }
                    if !raw.isEmpty && (values.isEmpty || values.count != tokens.count || values.contains(where: { !(0...2).contains($0) })) {
                        throw StudioError("音节重音请用 0、1、2，例如 0 1。")
                    }
                    model.setUnit(at: row, key: "stress_override", value: raw.isEmpty ? nil : values)
                }
            }
            if !model.isReference {
                unitNumber(unit, row: row, key: "duration_override_ms", label: "时长 (ms)", range: 20...30000,
                           placeholder: (unit["duration_ms"] as? Double).map { fixed($0, digits: 0) } ?? "自动")
                unitNumber(unit, row: row, key: "pause_override_ms", label: "后续停顿 (ms)", range: 0...30000,
                           placeholder: (unit["pause_after_ms"] as? Double).map { fixed($0, digits: 0) } ?? "自动")
                Text("留空使用自动值；修改后重新生成曲线。").font(.caption).foregroundStyle(.secondary)
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary.opacity(0.3), in: RoundedRectangle(cornerRadius: 8))
    }

    private func unitNumber(_ unit: JSON, row: Int, key: String, label: String, range: ClosedRange<Double>,
                            placeholder: String = "", digits: Int = 0, integer: Bool = false) -> some View {
        unitRow(label, value: (unit[key] as? NSNumber).map { fixed($0.doubleValue, digits: digits) } ?? "", placeholder: placeholder) { raw in
            if raw.isEmpty && key.hasSuffix("_override") { model.setUnit(at: row, key: key, value: nil); return }
            let number = try numeric(raw, range: range)
            if integer {
                guard number.rounded() == number else { throw StudioError("\(label)需要整数。") }
                model.setUnit(at: row, key: key, value: Int(number))
            } else { model.setUnit(at: row, key: key, value: number) }
        }
    }

    private func unitRow(_ label: String, value: String, placeholder: String, commit: @escaping (String) throws -> Void) -> some View {
        HStack(spacing: 8) {
            Text(label)
            Spacer(minLength: 0)
            EditableField(value: value, placeholder: placeholder, label: label, commit: commit) {
                model.report($0, error: true)
            }
            .frame(width: 124)
        }
        .font(.callout)
    }

    private func numeric(_ raw: String, range: ClosedRange<Double>) throws -> Double {
        if let value = Double(raw.replacingOccurrences(of: ",", with: ".")), value.isFinite, range.contains(value) { return value }
        throw StudioError("请输入 \(range.lowerBound) 至 \(range.upperBound) 之间的数值。")
    }
}

private struct EditableField: View {
    let value: String
    let placeholder: String
    let label: String
    let commit: (String) throws -> Void
    let onError: (String) -> Void
    @State private var text: String
    @FocusState private var focused: Bool

    init(value: String, placeholder: String, label: String, commit: @escaping (String) throws -> Void,
         onError: @escaping (String) -> Void) {
        self.value = value
        self.placeholder = placeholder
        self.label = label
        self.commit = commit
        self.onError = onError
        _text = State(initialValue: value)
    }

    var body: some View {
        TextField(label, text: $text, prompt: Text(placeholder))
            .labelsHidden()
            .accessibilityLabel(label)
            .textFieldStyle(.roundedBorder)
            .focused($focused)
            .onSubmit { focused = false }
            .onChange(of: focused) { _, active in if !active { apply() } }
            .onChange(of: value) { _, newValue in if !focused { text = newValue } }
    }

    private func apply() {
        let raw = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard raw != value else { return }
        do { try commit(raw) }
        catch { onError(error.localizedDescription); text = value }
    }
}
