import AppKit
import SwiftUI
import UniformTypeIdentifiers

@MainActor
final class StudioModel: ObservableObject {
    @Published private(set) var draft: JSON = StudioModel.empty(.zh)
    @Published private(set) var result: JSON?
    @Published private(set) var isReference = false
    @Published private(set) var stale = true
    @Published private(set) var dirty = false
    @Published private(set) var busy = false
    @Published private(set) var previewing = false
    @Published private(set) var status = "输入文稿，或载入示例开始。"
    @Published private(set) var hasError = false
    @Published private(set) var info: JSON = [:]
    @Published private(set) var projectURL: URL?
    @Published private(set) var outputURL: URL?
    @Published private(set) var sourceAudio: URL?
    @Published private(set) var previewAudio: URL?
    @Published private(set) var previewRevision: Int?
    @Published private(set) var previewScope: String?
    @Published private(set) var revision = 0
    @Published private(set) var timeline: PitchTimeline?
    @Published private var aceVoice = ""
    @Published private(set) var aceVoices: [ACEVoice] = []
    @Published private(set) var loadingVoices = false
    @Published var selection: String = StudioModel.full {
        didSet { updateTimeline() }
    }
    @Published var target: Target = .ace
    @Published var showReference = false
    weak var undo: UndoManager?

    static let full = "@full"
    let engine = Engine()
    private var started = false
    private var original: JSON?
    private var sectionResults: [String: JSON] = [:]
    private var autosave: Task<Void, Never>?
    private let draftWriter = DispatchQueue(label: "studio.vvtalk.draft")
    let draftURL: URL = {
        let files = FileManager.default
        let support = files.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let override = ProcessInfo.processInfo.environment["VVTALK_DATA_DIR"].flatMap { $0.isEmpty ? nil : $0 }
        let root = override.map { URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath, isDirectory: true) }
            ?? support.appendingPathComponent("VvTalkStudio", isDirectory: true)
        return root.appendingPathComponent("native-draft.json")
    }()

    var language: Language { Language(rawValue: draft["language"] as? String ?? "") ?? .zh }
    var title: String { draft["title"] as? String ?? "" }
    var text: String { draft["text"] as? String ?? "" }
    var hasText: Bool { !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    var selectedText: String { currentSection?["text"] as? String ?? text }
    var selectedResult: JSON? { sectionResults[selection] ?? result }
    var canGenerate: Bool { !busy && !isReference && hasText }
    var canSave: Bool { !busy && (hasText || result != nil) }
    var sentences: [Sentence] { sectionsMatch ? sections.compactMap(Sentence.init) : [] }
    var units: [JSON] {
        isReference ? (result?["notes"] as? [JSON] ?? []) : (currentSection?["characters"] as? [JSON] ?? [])
    }
    var warnings: [String] { (result?["warnings"] as? [String] ?? []) }
    var previewStale: Bool { previewRevision != nil && previewRevision != revision }
    var appVersion: String { info["version"] as? String ?? "" }
    var hosts: [String: JSON] { info["hosts"] as? [String: JSON] ?? [:] }
    var aceConnected: Bool { (info["ace"] as? JSON)?["connected"] as? Bool == true }
    var selectedACEVoice: String { (aceVoices.first { $0.id == aceVoice } ?? aceVoices.first)?.id ?? "" }
    var selectedSentence: Sentence? { currentSection.flatMap(Sentence.init) }

    private var sections: [JSON] { draft["sections"] as? [JSON] ?? [] }
    private var sectionsMatch: Bool { sections.map { $0["text"] as? String ?? "" }.joined() == text }
    private var currentSection: JSON? {
        guard sectionsMatch else { return nil }
        return sections.first { $0["id"] as? String == selection }
    }

    private static func empty(_ language: Language) -> JSON {
        ["title": "未命名文稿", "text": "", "language": language.rawValue, "settings": JSON()]
    }

    func bootstrap() async {
        guard !started else { return }
        started = true
        if let data = try? Data(contentsOf: draftURL),
           let previous = (try? JSONSerialization.jsonObject(with: data)) as? JSON,
           let recovered = previous["draft"] as? JSON {
            draft = recovered
            if let reference = previous["result"] as? JSON {
                applyReference(reference, title: title, source: nil)
            } else {
                stale = true
            }
            aceVoice = previous["ace_voice"] as? String ?? ""
            dirty = hasText || result != nil
            if dirty { status = "已恢复上次草稿。" }
        }
        await refreshHosts()
    }

    func refreshHosts() async {
        do {
            if aceVoices.isEmpty { await loadACEVoices() }
            info = try await engine.call("info")
        }
        catch { report(error.localizedDescription, error: true) }
    }

    private func loadACEVoices() async {
        guard !loadingVoices else { return }
        loadingVoices = true
        defer { loadingVoices = false }
        do {
            let response = try await engine.call("voices")
            aceVoices = (response["voices"] as? [JSON] ?? []).compactMap(ACEVoice.init)
        } catch {
            report(error.localizedDescription, error: true)
        }
    }

    func selectACEVoice(_ key: String) {
        guard key != selectedACEVoice, aceVoices.contains(where: { $0.id == key }) else { return }
        aceVoice = key
        edited(rebuild: false)
        report("ACE 声库已更改，重新试听后生效。")
    }

    func report(_ message: String, error: Bool = false) {
        status = message
        hasError = error
    }

    private func run(_ message: String, _ operation: () async throws -> Void) async -> Bool {
        guard !busy else { return false }
        busy = true
        report(message)
        defer { busy = false }
        do { try await operation(); return true }
        catch { report(error.localizedDescription, error: true); return false }
    }

    private func edited(rebuild: Bool = true) {
        if rebuild && !isReference { stale = true }
        dirty = true
        revision += 1
        scheduleAutosave()
    }

    private func scheduleAutosave() {
        autosave?.cancel()
        autosave = Task {
            do {
                try await Task.sleep(for: .milliseconds(550))
                persistDraft()
            } catch { }
        }
    }

    func persistDraft(flush: Bool = false) {
        let file = draftURL
        var value: JSON = ["draft": draft]
        if isReference { value["result"] = result }
        if !selectedACEVoice.isEmpty { value["ace_voice"] = selectedACEVoice }
        let snapshot = value
        let write: @Sendable () -> Void = {
            do {
                try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
                let data = try JSONSerialization.data(withJSONObject: snapshot, options: [.sortedKeys])
                try data.write(to: file, options: .atomic)
            } catch {
                Task { @MainActor in self.report("自动保存草稿失败：\(error.localizedDescription)", error: true) }
            }
        }
        if flush { autosave?.cancel(); draftWriter.sync(execute: write) }
        else { draftWriter.async(execute: write) }
    }

    func setTitle(_ value: String) {
        guard value != title else { return }
        draft["title"] = value
        edited(rebuild: false)
    }

    func setText(_ value: String) {
        guard !isReference, value != selectedText else { return }
        if let index = sections.firstIndex(where: { $0["id"] as? String == selection }), sectionsMatch {
            var revised = sections
            revised[index]["text"] = value
            draft["sections"] = revised
            draft["text"] = revised.compactMap { $0["text"] as? String }.joined()
        } else {
            draft["text"] = value
            // Whole-text edits retain previous sections so the engine can match unchanged sentences.
        }
        edited()
    }

    func setLanguage(_ value: Language) {
        guard value != language, !isReference else { return }
        newProject(value)
    }

    func fillSample() {
        guard !hasText else { return }
        draft["title"] = "回家的路"
        setText(language.sample)
    }

    func newProject(_ language: Language? = nil) {
        guard !busy, canReplace() else { return }
        draft = Self.empty(language ?? self.language)
        resetContent()
        undo?.removeAllActions()
        dirty = false
        scheduleAutosave()
        report("新文稿已准备好。")
    }

    private func canReplace() -> Bool {
        guard dirty, hasText || result != nil else { return true }
        let dialog = NSAlert()
        dialog.messageText = "替换当前文稿？"
        dialog.informativeText = "当前文稿有未保存到工程文件的更改。可先取消，再按 ⌘S 保存。"
        dialog.addButton(withTitle: "取消")
        dialog.addButton(withTitle: "替换")
        dialog.buttons[1].hasDestructiveAction = true
        return dialog.runModal() == .alertSecondButtonReturn
    }

    private func resetContent() {
        aceVoice = ""
        result = nil
        original = nil
        sectionResults = [:]
        isReference = false
        stale = true
        selection = Self.full
        projectURL = nil
        outputURL = nil
        sourceAudio = nil
        previewAudio = nil
        previewScope = nil
        previewRevision = nil
        revision += 1
    }

    func value(_ parameter: Parameter, local: Bool = false) -> Double? {
        let settings = (local ? currentSection?["settings"] : draft["settings"]) as? JSON ?? [:]
        return settings[parameter.id] as? Double ?? (local ? nil : parameter.initial)
    }

    func setParameter(_ parameter: Parameter, value: Double?, local: Bool) {
        guard value != self.value(parameter, local: local) else { return }
        let prior = self.value(parameter, local: local)
        if local {
            guard let index = sections.firstIndex(where: { $0["id"] as? String == selection }), sectionsMatch else { return }
            var updated = sections
            var settings = updated[index]["settings"] as? JSON ?? [:]
            settings[parameter.id] = value
            updated[index]["settings"] = settings
            replaceSections(updated)
        } else {
            var settings = draft["settings"] as? JSON ?? [:]
            settings[parameter.id] = value
            draft["settings"] = settings
        }
        let section = selection
        undo?.registerUndo(withTarget: self) { model in
            MainActor.assumeIsolated {
                if local { model.selection = section }
                model.setParameter(parameter, value: prior, local: local)
            }
        }
        undo?.setActionName(parameter.label)
        edited()
    }

    private func replaceSections(_ updated: [JSON]) { draft["sections"] = updated }

    func setUnit(at index: Int, key: String, value: Any?) {
        if isReference {
            guard var notes = result?["notes"] as? [JSON], notes.indices.contains(index) else { return }
            let previous = notes[index][key]
            notes[index][key] = value
            result?["notes"] = notes
            if ["start", "end", "key"].contains(key) { updateTimeline(keeping: timeline?.limits) }
            registerUnitUndo(index: index, key: key, previous: previous)
        } else {
            guard let section = sections.firstIndex(where: { $0["id"] as? String == selection }),
                  var chars = sections[section]["characters"] as? [JSON], chars.indices.contains(index) else { return }
            let previous = chars[index][key]
            chars[index][key] = value
            var revised = sections
            revised[section]["characters"] = chars
            replaceSections(revised)
            registerUnitUndo(index: index, key: key, previous: previous)
        }
        edited()
    }

    private func registerUnitUndo(index: Int, key: String, previous: Any?) {
        let section = selection
        undo?.registerUndo(withTarget: self) { model in
            MainActor.assumeIsolated {
                model.selection = section
                model.setUnit(at: index, key: key, value: previous)
            }
        }
        undo?.setActionName("编辑发音单元")
    }

    func resetUnits() {
        if isReference, let original {
            result = original
            updateTimeline()
        } else if let index = sections.firstIndex(where: { $0["id"] as? String == selection }),
                  var chars = sections[index]["characters"] as? [JSON] {
            for row in chars.indices {
                for key in ["pinyin_override", "pronunciation_override", "accent_override", "stress_override",
                            "duration_override_ms", "pause_override_ms"] { chars[row].removeValue(forKey: key) }
            }
            var updated = sections
            updated[index]["characters"] = chars
            replaceSections(updated)
        }
        edited()
    }

    private func applyGenerated(_ response: JSON, keeping limits: ClosedRange<Double>? = nil) throws {
        guard var document = response["document"] as? JSON, let result = response["result"] as? JSON,
              var sections = document["sections"] as? [JSON] else { throw StudioError("没有收到完整的文稿和曲线。") }
        sectionResults = [:]
        for index in sections.indices {
            if let id = sections[index]["id"] as? String {
                sectionResults[id] = sections[index].removeValue(forKey: "result") as? JSON
            }
        }
        document["sections"] = sections
        draft = document
        self.result = result
        isReference = false
        stale = false
        if selection != Self.full && !sentences.contains(where: { $0.id == selection }) { selection = Self.full }
        else { updateTimeline(keeping: limits) }
        scheduleAutosave()
    }


    var pitchEditing: PitchEditing? {
        guard let timeline, !stale, !timeline.notes.isEmpty else { return nil }
        if isReference {
            guard timeline.notes.count == units.count,
                  let first = timeline.notes.first, let last = timeline.notes.last,
                  first.start >= 0, last.end <= timeline.duration + 0.000001,
                  zip(timeline.notes, timeline.notes.dropFirst()).allSatisfy({ $0.end <= $1.start + 0.0000001 }) else {
                return nil
            }
            return PitchEditing(timeline: timeline, sections: [], reference: true, documentDuration: timeline.duration)
        }
        let visible = selection == Self.full ? sections : currentSection.map { [$0] } ?? []
        let globalBase = value(.pitch) ?? Parameter.pitch.initial
        let globalAmplitude = value(.amplitude) ?? Parameter.amplitude.initial
        var firstNote = 0
        let pitchSections = visible.compactMap { raw -> PitchSection? in
            guard let sentence = Sentence(raw), let characters = raw["characters"] as? [JSON] else { return nil }
            let local = raw["settings"] as? JSON ?? [:]
            let section = PitchSection(id: sentence.id, offset: selection == Self.full ? sentence.offset : 0,
                                       duration: sentence.duration, firstNote: firstNote,
                                       base: local[Parameter.pitch.id] as? Double ?? globalBase,
                                       amplitude: local[Parameter.amplitude.id] as? Double ?? globalAmplitude)
            firstNote += characters.count
            return section
        }
        guard !pitchSections.isEmpty, firstNote == timeline.notes.count else { return nil }
        return PitchEditing(timeline: timeline, sections: pitchSections, reference: false,
                            documentDuration: result?["duration"] as? Double ?? timeline.duration)
    }

    func applyPitchEdit(_ edit: PitchEdit, from revision: Int, selection: String) async {
        guard !busy, self.revision == revision, self.selection == selection, let editing = pitchEditing else { return }
        if isReference {
            applyReferencePitchEdit(edit, editing: editing)
            return
        }
        let writes: [PitchWrite]
        switch edit {
        case .duration(let index, let seconds):
            guard let note = editing.timeline.notes.first(where: { $0.index == index }),
                  let section = editing.section(for: index) else { return }
            let length = editing.duration(seconds, for: note)
            guard abs(length - (note.end - note.start)) >= 0.0005 else { return }
            writes = [.init(field: .duration(section.id, index - section.firstNote), value: length * 1000)]
        case .transpose(let delta):
            writes = pitchSettings(.pitch, delta: delta)
        case .amplitude(let delta):
            writes = pitchSettings(.amplitude, delta: delta)
        }
        guard let (proposed, inverse) = patchPitchDraft(writes), !inverse.isEmpty else { return }
        _ = await run("正在\(edit.action)…") {
            let response = try await engine.call("analyze", proposed)
            guard self.revision == revision else { return }
            try applyGenerated(response, keeping: editing.timeline.limits)
            edited(rebuild: false)
            registerPitchUndo(inverse, name: edit.action)
            report("已\(edit.action)。")
        }
    }

    private struct PitchWrite {
        enum Field {
            case duration(String, Int)
            case setting(String?, Parameter)
        }
        let field: Field
        let value: Double?
    }

    private func pitchSettings(_ parameter: Parameter, delta: Double) -> [PitchWrite] {
        let global = value(parameter) ?? parameter.initial
        if let sentence = selectedSentence {
            let effective = value(parameter, local: true) ?? global
            let next = parameter.adjusted(effective, by: delta)
            return next == effective ? [] : [.init(field: .setting(sentence.id, parameter), value: next)]
        }
        var writes: [PitchWrite] = []
        let next = parameter.adjusted(global, by: delta)
        if next != global { writes.append(.init(field: .setting(nil, parameter), value: next)) }
        for section in sections {
            guard let id = section["id"] as? String, let settings = section["settings"] as? JSON,
                  let prior = settings[parameter.id] as? Double else { continue }
            let next = parameter.adjusted(prior, by: delta)
            if next != prior { writes.append(.init(field: .setting(id, parameter), value: next)) }
        }
        return writes
    }

    private func patchPitchDraft(_ writes: [PitchWrite]) -> (JSON, [PitchWrite])? {
        guard !isReference, sectionsMatch else { return nil }
        var revised = draft
        var updated = sections
        let indices = Dictionary(uniqueKeysWithValues: updated.enumerated().compactMap { index, section in
            (section["id"] as? String).map { ($0, index) }
        })
        var inverse: [PitchWrite] = []
        for write in writes {
            switch write.field {
            case .duration(let section, let unit):
                guard let index = indices[section], var characters = updated[index]["characters"] as? [JSON],
                      characters.indices.contains(unit) else { return nil }
                let key = "duration_override_ms"
                let prior = characters[unit][key] as? Double
                guard write.value != prior else { continue }
                characters[unit][key] = write.value
                updated[index]["characters"] = characters
                inverse.append(.init(field: write.field, value: prior))
            case .setting(let section, let parameter):
                let index = section.flatMap { indices[$0] }
                if section != nil && index == nil { return nil }
                var settings = (index.map { updated[$0]["settings"] } ?? revised["settings"]) as? JSON ?? [:]
                let prior = settings[parameter.id] as? Double
                guard write.value != prior else { continue }
                settings[parameter.id] = write.value
                if let index { updated[index]["settings"] = settings }
                else { revised["settings"] = settings }
                inverse.append(.init(field: write.field, value: prior))
            }
        }
        revised["sections"] = updated
        return (revised, inverse)
    }

    private func registerPitchUndo(_ writes: [PitchWrite], name: String) {
        undo?.registerUndo(withTarget: self) { model in
            MainActor.assumeIsolated { model.restorePitchDraft(writes, name: name) }
        }
        undo?.setActionName(name)
    }

    private func restorePitchDraft(_ writes: [PitchWrite], name: String) {
        guard let (proposed, inverse) = patchPitchDraft(writes), !inverse.isEmpty else { return }
        draft = proposed
        edited()
        registerPitchUndo(inverse, name: name)
        let revision = revision
        let limits = timeline?.limits
        Task {
            guard self.revision == revision, canGenerate else { return }
            _ = await run("正在更新音高曲线…") {
                try await generateCurrent(keeping: limits)
                report("已更新音高曲线。")
            }
        }
    }

    private func applyReferencePitchEdit(_ edit: PitchEdit, editing: PitchEditing) {
        if case .duration(let index, let seconds) = edit {
            guard let note = editing.timeline.notes.first(where: { $0.index == index }) else { return }
            let end = note.start + editing.duration(seconds, for: note)
            guard abs(end - note.end) >= 0.0005 else { return }
            setUnit(at: index, key: "end", value: end)
            undo?.setActionName(edit.action)
            report("已\(edit.action)。")
            return
        }
        let transform = editing.referenceTransform(edit)
        guard transform.shift != 0 || transform.scale != 1,
              let result, let curve = result["curve"] as? [JSON], let notes = result["notes"] as? [JSON] else { return }
        var stats = result["stats"] as? JSON
        for key in ["pitch_min", "pitch_max", "pitch_median"] {
            if let pitch = stats?[key] as? Double { stats?[key] = (transform.pitch(pitch) * 1000).rounded() / 1000 }
        }
        if let base = (stats?["baseline_pitch"] as? NSNumber)?.doubleValue {
            stats?["baseline_pitch"] = Int(transform.key(base))
        }
        let pitches = curve.map { ($0["pitch"] as? Double).map { min(175, max(-48, transform.pitch($0))) } }
        let keys = notes.map { Int(transform.key(($0["key"] as? NSNumber)?.doubleValue ?? 60)) }
        replaceReferencePitches(pitches, keys: keys, stats: stats, name: edit.action)
        report("已\(edit.action)。")
    }

    private func replaceReferencePitches(_ pitches: [Double?], keys: [Int], stats: JSON?, name: String) {
        guard isReference, var updated = result, var curve = updated["curve"] as? [JSON],
              var notes = updated["notes"] as? [JSON], pitches.count == curve.count, keys.count == notes.count else { return }
        let priorPitches = curve.map { $0["pitch"] as? Double }
        let priorKeys = notes.map { $0["key"] as? Int ?? 60 }
        let priorStats = updated["stats"] as? JSON
        for index in curve.indices { curve[index]["pitch"] = pitches[index] as Any? ?? NSNull() }
        for index in notes.indices { notes[index]["key"] = keys[index] }
        updated["curve"] = curve
        updated["notes"] = notes
        updated["stats"] = stats
        result = updated
        updateTimeline(keeping: timeline?.limits)
        edited(rebuild: false)
        undo?.registerUndo(withTarget: self) { model in
            MainActor.assumeIsolated { model.replaceReferencePitches(priorPitches, keys: priorKeys, stats: priorStats, name: name) }
        }
        undo?.setActionName(name)
    }

    private func updateTimeline(keeping limits: ClosedRange<Double>? = nil) {
        timeline = PitchTimeline(selectedResult, keeping: limits)
    }

    private func generateCurrent(keeping limits: ClosedRange<Double>? = nil) async throws {
        let response = try await engine.call("analyze", draft)
        try applyGenerated(response, keeping: limits)
    }

    func generate() async {
        guard canGenerate else { return }
        _ = await run("正在生成语调…") {
            try await generateCurrent()
            report("已生成 \(sentences.count) 句 · \((result?["notes"] as? [JSON] ?? []).count) \(language.unit)。")
        }
    }

    func open() async {
        guard !busy else { return }
        let panel = NSOpenPanel()
        panel.message = "打开 VvTalk 工程或 UTF-8 文本。"
        panel.allowedContentTypes = [.json, .plainText]
        guard panel.runModal() == .OK, let url = panel.url, canReplace() else { return }
        _ = await run("正在打开文稿…") {
            if url.pathExtension.lowercased() == "txt" {
                let data = try Data(contentsOf: url)
                guard let content = String(data: data, encoding: .utf8) else { throw StudioError("请选择 UTF-8 文本。") }
                draft = Self.empty(language)
                draft["text"] = String(content.drop(while: { $0 == "\u{FEFF}" }))
                draft["title"] = url.deletingPathExtension().lastPathComponent
                resetContent()
                dirty = true
                report("文本已导入，点击「生成语调」分句。")
            } else {
                let name = url.deletingPathExtension().lastPathComponent
                let response = try await engine.call("open", ["path": url.path, "title": name])
                if response["document"] is JSON {
                    resetContent()
                    try applyGenerated(response)
                } else if let result = response["result"] as? JSON {
                    applyReference(result, title: response["title"] as? String ?? name, source: nil)
                } else { throw StudioError("工程中没有可用的文稿或参考曲线。") }
                aceVoice = response["ace_voice"] as? String ?? ""
                projectURL = url
                dirty = false
                report(isReference ? "参考曲线已恢复。原始录音请重新选择。" : "工程已打开。")
            }
            undo?.removeAllActions()
            scheduleAutosave()
        }
    }

    private func payload() async throws -> JSON {
        var content: JSON
        if isReference, let result { content = ["title": title, "result": result] }
        else {
            if stale || result == nil { try await generateCurrent() }
            content = ["title": title, "document": draft]
        }
        if !selectedACEVoice.isEmpty { content["ace_voice"] = selectedACEVoice }
        return content
    }

    func save(asNew: Bool = false) async {
        guard canSave else { return }
        let destination: URL
        if let existing = projectURL, !asNew { destination = existing }
        else {
            guard let url = chooseOutput(title: "保存工作台工程", name: fileName + ".vvtalk.json", type: .json) else { return }
            destination = url
        }
        _ = await run("正在保存工程…") {
            let response = try await engine.call("save", try await payload())
            let data = try JSONSerialization.data(withJSONObject: response, options: [.sortedKeys])
            try data.write(to: destination, options: .atomic)
            projectURL = destination
            dirty = false
            report("已保存 \(destination.lastPathComponent)。")
        }
    }

    private var fileName: String {
        let safe = title.trimmingCharacters(in: .whitespacesAndNewlines).replacingOccurrences(of: "/", with: "／")
        return safe.isEmpty ? "语调工程" : safe
    }

    private func chooseOutput(title: String, name: String, type: UTType) -> URL? {
        let panel = NSSavePanel()
        panel.title = title
        panel.nameFieldStringValue = name
        panel.allowedContentTypes = [type]
        panel.canCreateDirectories = true
        return panel.runModal() == .OK ? panel.url : nil
    }

    func export() async {
        guard canSave else { return }
        let engineTarget = target
        if engineTarget == .ace && selectedACEVoice.isEmpty {
            report("请等待 ACE 声库列表载入。", error: true)
            return
        }
        guard let url = chooseOutput(title: "导出 \(engineTarget.title) 工程",
                                     name: fileName + "." + engineTarget.ext,
                                     type: UTType(filenameExtension: engineTarget.ext) ?? .data) else { return }
        _ = await run("正在导出工程…") {
            var request = try await payload()
            request["target"] = engineTarget.rawValue
            let response = try await engine.call("export", request)
            guard let files = response["files"] as? [JSON], files.count == 1, let path = files[0]["path"] as? String else {
                throw StudioError("导出没有返回所选引擎的工程。")
            }
            try Data(contentsOf: URL(fileURLWithPath: path)).write(to: url, options: .atomic)
            outputURL = url
            let warning = (response["warnings"] as? [String])?.first.map { " \($0)" } ?? ""
            report("已导出 \(url.lastPathComponent)。" + warning)
        }
    }

    func copySynthV() async {
        guard canSave else { return }
        _ = await run("正在准备 SV2 脚本数据…") {
            let response = try await engine.call("synthv", try await payload())
            guard let value = response["data"] as? JSON else { throw StudioError("没有收到 SV2 脚本数据。") }
            let data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(String(decoding: data, as: UTF8.self), forType: .string)
            report("已复制。请在 SV2 运行「VvTalk Studio → 导入剪贴板语调」。")
        }
    }

    func installSynthV() async {
        _ = await run("正在安装 SV2 脚本…") {
            let response = try await engine.call("install")
            report("已安装 SV2 脚本。请在 Synthesizer V 中刷新脚本菜单。")
            if let path = response["path"] as? String { outputURL = URL(fileURLWithPath: path) }
        }
    }

    func alignment(_ language: Language) -> JSON { (info["alignment_by_language"] as? [String: JSON])?[language.rawValue] ?? [:] }

    func beginReference() {
        guard !busy else { return }
        showReference = true
    }

    private func applyReference(_ result: JSON, title: String, source: URL?) {
        resetContent()
        let language = Language(rawValue: result["language"] as? String ?? "") ?? .zh
        draft = Self.empty(language)
        draft["title"] = title
        draft["text"] = result["text"] as? String ?? ""
        self.result = result
        original = result
        sourceAudio = source
        isReference = true
        stale = false
        updateTimeline()
    }

    func importReference(audio: URL?, alignment: URL?, vsqx: URL?, text: String, language: Language,
                         automatic: Bool, fmin: Double, fmax: Double, pitchMode: String) async -> Bool {
        guard canReplace() else { return false }
        return await run("正在分析参考素材…") {
            if let vsqx {
                let response = try await engine.call("import", ["kind": "vsqx", "path": vsqx.path, "language": language.rawValue])
                guard let result = response["result"] as? JSON else { throw StudioError("VSQX 中没有可用音符。") }
                applyReference(result, title: vsqx.deletingPathExtension().lastPathComponent, source: nil)
            } else if let audio {
                let input = try await engine.call("import", ["kind": "audio", "path": audio.path])
                guard let id = input["id"] as? String, let path = input["path"] as? String else { throw StudioError("参考音频读取失败。") }
                var request: JSON = ["audio_id": id, "text": text, "language": language.rawValue,
                                     "alignment_mode": automatic ? "auto" : "equal", "fmin": fmin, "fmax": fmax,
                                     "pitch_mode": pitchMode, "settings": draft["settings"] ?? JSON()]
                if let alignment {
                    let mark = try await engine.call("import", ["kind": "alignment", "path": alignment.path])
                    request["alignment_id"] = mark["id"]
                }
                let response = try await engine.call("reference", request)
                guard let result = response["result"] as? JSON else { throw StudioError("没有提取到参考曲线。") }
                applyReference(result, title: audio.deletingPathExtension().lastPathComponent, source: URL(fileURLWithPath: path))
            } else { throw StudioError("请选择录音或 VSQX。") }
            undo?.removeAllActions()
            edited(rebuild: false)
            report("参考语调已导入。请在「发音单元」核对时间和读音。")
        }
    }

    func renderPreview() async {
        guard canSave, !previewing else { return }
        guard !selectedACEVoice.isEmpty else {
            report("请等待 ACE 声库列表载入。", error: true)
            return
        }
        previewing = true
        defer { previewing = false }
        let currentRevision = revision
        let scope = selection
        var job: JSON = [:]
        let queued = await run("正在提交 ACE 试听…") {
            var request = try await payload()
            if !isReference && scope != Self.full { request["section_id"] = scope }
            job = try await engine.call("preview", request)
        }
        guard queued, let id = job["id"] as? String else { return }
        do {
            let deadline = Date().addingTimeInterval(30 * 60)
            while job["status"] as? String == "running" {
                guard Date() < deadline else { throw StudioError("等待已超过 30 分钟，请在 ACE Studio 检查进度。") }
                if !busy { report(job["message"] as? String ?? "正在合成试听…") }
                try await Task.sleep(for: .seconds(1.5))
                job = try await engine.call("job", ["id": id])
            }
            guard job["status"] as? String == "succeeded", let path = job["path"] as? String else {
                throw StudioError(job["message"] as? String ?? "ACE 试听失败。")
            }
            guard currentRevision == revision else {
                if !busy { report("试听已完成；文稿已变更，可重新合成。") }
                return
            }
            previewAudio = URL(fileURLWithPath: path)
            previewRevision = currentRevision
            previewScope = scope
            if !busy { report("ACE 试听已生成。") }
        } catch { report(error.localizedDescription, error: true) }
    }
}
