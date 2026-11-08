import SwiftUI

struct PitchView: View {
    @ObservedObject var model: StudioModel
    @ObservedObject var player: Playback
    @State private var qqSettings = QQVoiceSettings.load()
    @State private var showQQVoice = false

    private var playhead: Double? {
        guard let url = player.url else { return nil }
        if url == model.sourceAudio && model.isReference { return player.time }
        if url == model.previewAudio, !model.previewStale, model.previewScope == model.selection { return player.time }
        return nil
    }

    var body: some View {
        let editing = model.pitchEditing
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                Label("音高曲线", systemImage: "waveform.path")
                    .font(.headline)
                Spacer()
                if model.stale && model.timeline != nil {
                    Label("待更新", systemImage: "clock").font(.caption).foregroundStyle(.orange)
                }
                if let timeline = model.timeline {
                    Text("\(fixed(timeline.duration)) 秒 · \(timeline.notes.count) \(model.language.unit)")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            }
            if let timeline = model.timeline {
                let revision = model.revision, selection = model.selection
                PitchPlot(timeline: timeline, editing: editing, playhead: playhead, seek: { time in
                    if playhead != nil { player.seek(time) }
                }, commit: { edit in
                    Task { await model.applyPitchEdit(edit, from: revision, selection: selection) }
                })
                .id(selection)
            } else {
                VStack(spacing: 7) {
                    Image(systemName: "waveform.path").font(.system(size: 25, weight: .light))
                    Text("还没有音高曲线").font(.callout.weight(.medium))
                    Text("生成文稿语调，或导入录音与工程。").font(.caption)
                }
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(.quaternary.opacity(0.3), in: RoundedRectangle(cornerRadius: 8))
            }
            HStack(spacing: 12) {
                if model.timeline != nil {
                    legend("连续音高", color: .accentColor)
                    legend("音符基准", color: .secondary.opacity(0.65))
                }
                Spacer(minLength: 0)
                if model.previewing { ProgressView().controlSize(.small).accessibilityLabel("ACE 正在合成") }
                if let source = model.sourceAudio { audioButton("原录音", url: source) }
                if let preview = model.previewAudio {
                    audioButton(model.previewStale ? "上次试听" : "ACE 试听", url: preview)
                    Button {
                        NSWorkspace.shared.activateFileViewerSelecting([preview])
                    } label: {
                        Image(systemName: "folder").accessibilityLabel("在 Finder 中显示试听音频")
                    }
                    .buttonStyle(.borderless)
                    Button("QQ 语音…") { showQQVoice = true }
                        .controlSize(.small)
                        .disabled(model.previewStale || model.previewing)
                        .help("把这段试听用个人 QQ 账号发到群里")
                }
            }
            if model.timeline != nil {
                Text(editing == nil
                     ? (model.stale ? "重新生成后可在图上拖动编辑。" : "请先在检查器核对音符时间。")
                     : "拖动音符右端调整时长 · 上下拖动曲线调整音高 · 右侧调整幅度")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            if player.url != nil && player.duration > 0 {
                HStack(spacing: 8) {
                    Text(fixed(player.time)).monospacedDigit()
                    Slider(value: Binding(get: { player.time }, set: { player.seek($0) }), in: 0...player.duration)
                        .accessibilityLabel("播放进度")
                    Text(fixed(player.duration)).monospacedDigit()
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }
        }
        .sheet(isPresented: $showQQVoice) {
            if let audio = model.previewAudio {
                QQVoiceSheet(audio: audio, settings: $qqSettings) { group in
                    model.report("已发送 QQ 语音到「\(group.label)」。")
                }
            }
        }
    }

    private func legend(_ text: String, color: Color) -> some View {
        HStack(spacing: 5) {
            Capsule().fill(color).frame(width: 12, height: 2)
            Text(text).font(.caption2).foregroundStyle(.secondary)
        }
    }

    private func audioButton(_ label: String, url: URL) -> some View {
        Button {
            do { try player.toggle(url) }
            catch { model.report(error.localizedDescription, error: true) }
        } label: {
            Label(label, systemImage: player.url == url && player.playing ? "pause.fill" : "play.fill")
        }
        .controlSize(.small)
    }
}

private struct PitchPlot: View {
    let timeline: PitchTimeline
    let editing: PitchEditing?
    let playhead: Double?
    let seek: (Double) -> Void
    let commit: (PitchEdit) -> Void

    private enum Target: Equatable {
        case tail(Int)
        case transpose
        case amplitude
        case seek

        var cursor: NSCursor {
            switch self {
            case .tail: .resizeLeftRight
            case .transpose, .amplitude: .resizeUpDown
            case .seek: .arrow
            }
        }
    }

    @State private var target: Target?
    @State private var hover: Target?
    @State private var edit: PitchEdit?

    var body: some View {
        GeometryReader { geometry in
            let base = PlotGeometry(size: geometry.size, timeline: timeline)
            let displayed = edit.flatMap { editing?.preview($0) } ?? timeline
            let plot = PlotGeometry(size: geometry.size, timeline: displayed,
                                    minimumDuration: edit == nil ? 0 : timeline.duration)
            Canvas { context, _ in
                drawGrid(context, plot)
                drawTimeline(context, plot, displayed)
                if editing != nil {
                    drawHandle(context, in: plot.amplitudeHandle, title: "幅度", active: target == .amplitude || hover == .amplitude)
                    drawHandle(context, in: plot.pitchHandle, title: "音高", active: target == .transpose || hover == .transpose)
                }
            }
            .background(.quaternary.opacity(0.3), in: RoundedRectangle(cornerRadius: 8))
            .overlay(alignment: .top) {
                if let edit {
                    Text(dragLabel(edit))
                        .font(.caption.monospacedDigit().weight(.medium))
                        .padding(.horizontal, 8).padding(.vertical, 4)
                        .background(.regularMaterial, in: Capsule())
                        .padding(.top, 5)
                        .allowsHitTesting(false)
                }
            }
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0)
                .onChanged { value in updateDrag(value, in: base) }
                .onEnded { value in endDrag(value, in: base) })
            .onContinuousHover { phase in
                switch phase {
                case .active(let point):
                    hover = hit(point, in: base)
                    (target ?? hover)?.cursor.set()
                case .ended:
                    hover = nil
                    if target == nil { NSCursor.arrow.set() }
                }
            }
        }
        .accessibilityLabel("音高曲线")
        .accessibilityValue("\(fixed(timeline.duration)) 秒，MIDI 音高 \(Int(timeline.limits.lowerBound)) 至 \(Int(timeline.limits.upperBound))")
        .accessibilityAction(named: Text("升高一半音")) { commit(.transpose(1)) }
        .accessibilityAction(named: Text("降低一半音")) { commit(.transpose(-1)) }
        .accessibilityAction(named: Text("增大幅度")) { commit(.amplitude(0.1)) }
        .accessibilityAction(named: Text("减小幅度")) { commit(.amplitude(-0.1)) }
        .onChange(of: editing == nil) { _, disabled in
            if disabled {
                target = nil
                edit = nil
                hover = nil
            }
        }
        .onDisappear { if hover != nil || target != nil { NSCursor.arrow.set() } }
    }

    private func hit(_ point: CGPoint, in plot: PlotGeometry) -> Target {
        guard editing != nil else { return .seek }
        if plot.amplitudeHandle.contains(point) { return .amplitude }
        if plot.pitchHandle.contains(point) { return .transpose }
        guard plot.rect.insetBy(dx: -7, dy: -4).contains(point) else { return .seek }
        let nearest = timeline.notes
            .filter {
                let width = plot.x($0.end) - plot.x($0.start)
                return abs(plot.y($0.key) - point.y) <= 9 && abs(plot.x($0.end) - point.x) <= min(7, max(2, width / 2))
            }
            .min { abs(plot.x($0.end) - point.x) < abs(plot.x($1.end) - point.x) }
        if let nearest { return .tail(nearest.index) }
        if onCurve(point, plot: plot) { return .transpose }
        return .seek
    }

    private func onCurve(_ point: CGPoint, plot: PlotGeometry) -> Bool {
        var previous: CGPoint?
        for sample in timeline.points {
            guard let pitch = sample.pitch else { previous = nil; continue }
            let current = CGPoint(x: plot.x(sample.time), y: plot.y(pitch))
            if current.x > point.x + 8 && (previous?.x ?? current.x) > point.x { break }
            if hypot(current.x - point.x, current.y - point.y) <= 8 { return true }
            if let previous, previous.x <= point.x, current.x >= point.x, current.x > previous.x {
                let position = (point.x - previous.x) / (current.x - previous.x)
                let y = previous.y + (current.y - previous.y) * position
                if abs(y - point.y) <= 8 { return true }
            }
            previous = current
        }
        return false
    }

    private func updateDrag(_ value: DragGesture.Value, in plot: PlotGeometry) {
        if target == nil { target = hit(value.startLocation, in: plot) }
        guard let target else { return }
        target.cursor.set()
        let dx = value.translation.width, dy = value.translation.height
        switch target {
        case .tail(let index):
            guard let editing, abs(dx) >= 2, let note = timeline.notes.first(where: { $0.index == index }) else {
                edit = nil
                return
            }
            let seconds = note.end - note.start + dx * timeline.duration / plot.rect.width
            let length = editing.duration((seconds * 1000).rounded() / 1000, for: note)
            edit = .duration(note: index, seconds: length)
        case .transpose:
            let semitones = (-dy / plot.pixelsPerSemitone).rounded()
            edit = semitones == 0 ? nil : .transpose(semitones)
        case .amplitude:
            let delta = (-dy / 60 * 20).rounded() / 20
            edit = delta == 0 ? nil : .amplitude(delta)
        case .seek:
            if plot.rect.contains(value.startLocation) { seek(plot.time(at: value.location.x)) }
        }
    }

    private func endDrag(_ value: DragGesture.Value, in plot: PlotGeometry) {
        updateDrag(value, in: plot)
        defer {
            edit = nil
            target = nil
            hover = hit(value.location, in: plot)
            hover?.cursor.set()
        }
        if let edit { commit(edit) }
        else if target == .transpose && abs(value.translation.height) < 2 && plot.rect.contains(value.startLocation) {
            seek(plot.time(at: value.location.x))
        }
    }

    private func dragLabel(_ edit: PitchEdit) -> String {
        switch edit {
        case .duration(let index, let seconds):
            let lyric = timeline.notes.first { $0.index == index }?.lyric ?? ""
            return "\(lyric) · \(fixed(seconds * 1000, digits: 0)) ms"
        case .transpose(let delta):
            let shift = editing?.reference == true ? editing?.referenceTransform(edit).shift ?? delta : delta
            return String(format: "音高 %+.0f 半音", shift)
        case .amplitude(let delta):
            if editing?.reference == true, let transform = editing?.referenceTransform(edit) {
                return "幅度 ×\(fixed(transform.scale))"
            }
            return String(format: "幅度 %+.2f×", delta)
        }
    }

    private func drawGrid(_ context: GraphicsContext, _ plot: PlotGeometry) {
        let rect = plot.rect
        var grid = Path()
        let pitchStep = max(1, Int(ceil((plot.limits.upperBound - plot.limits.lowerBound) / 6)))
        for pitch in stride(from: Int(ceil(plot.limits.lowerBound)), through: Int(floor(plot.limits.upperBound)), by: pitchStep) {
            let y = plot.y(Double(pitch))
            grid.move(to: CGPoint(x: rect.minX, y: y))
            grid.addLine(to: CGPoint(x: rect.maxX, y: y))
            context.draw(Text("\(pitch)").font(.system(size: 9, design: .monospaced)).foregroundColor(.secondary),
                         at: CGPoint(x: rect.minX - 7, y: y), anchor: .trailing)
        }
        let timeSteps = max(2, min(8, Int(rect.width / 74)))
        for tick in 0...timeSteps {
            let seconds = Double(tick) * plot.duration / Double(timeSteps)
            let x = plot.x(seconds)
            grid.move(to: CGPoint(x: x, y: rect.minY))
            grid.addLine(to: CGPoint(x: x, y: rect.maxY))
            context.draw(Text(fixed(seconds, digits: plot.duration < 10 ? 2 : 1) + "s")
                .font(.system(size: 9, design: .monospaced)).foregroundColor(.secondary),
                at: CGPoint(x: x, y: rect.maxY + 6), anchor: .top)
        }
        context.stroke(grid, with: .color(.secondary.opacity(0.18)), lineWidth: 1)
    }

    private func drawTimeline(_ context: GraphicsContext, _ plot: PlotGeometry, _ displayed: PitchTimeline) {
        var content = context
        content.clip(to: Path(plot.rect))
        for note in displayed.notes {
            let start = plot.x(note.start), end = plot.x(note.end), y = plot.y(note.key)
            let width = max(0.75, end - start)
            let active = target == .tail(note.index) || hover == .tail(note.index)
            let fill: Color = active ? .accentColor : .secondary.opacity(0.42)
            let bar = CGRect(x: start, y: y - 2, width: width, height: 4)
            content.fill(Path(roundedRect: bar, cornerRadius: 2), with: .color(fill))
            if editing != nil && (width >= 13 || active) {
                let handle = CGRect(x: end - 3, y: y - 5, width: 3, height: 10)
                content.fill(Path(roundedRect: handle, cornerRadius: 1.5),
                             with: .color(active ? .accentColor : .secondary.opacity(0.85)))
            }
            if width >= 24 {
                content.draw(Text(note.lyric).font(.system(size: 10)).foregroundColor(.secondary),
                             at: CGPoint(x: start + width / 2, y: y + 6), anchor: .top)
            }
        }
        var line = Path(), connected = false
        for point in displayed.points {
            guard let pitch = point.pitch else { connected = false; continue }
            let vertex = CGPoint(x: plot.x(point.time), y: plot.y(pitch))
            if connected { line.addLine(to: vertex) }
            else { line.move(to: vertex); line.addLine(to: CGPoint(x: vertex.x + 0.3, y: vertex.y)) }
            connected = true
        }
        let weight = target == .transpose || hover == .transpose ? 2.6 : 1.8
        content.stroke(line, with: .color(.accentColor), style: StrokeStyle(lineWidth: weight, lineCap: .round, lineJoin: .round))
        if let playhead {
            let x = plot.x(min(playhead, displayed.duration))
            var cursor = Path()
            cursor.move(to: CGPoint(x: x, y: plot.rect.minY))
            cursor.addLine(to: CGPoint(x: x, y: plot.rect.maxY))
            content.stroke(cursor, with: .color(.orange), lineWidth: 1.5)
        }
    }

    private func drawHandle(_ context: GraphicsContext, in rect: CGRect, title: String, active: Bool) {
        let tint: Color = active ? .accentColor : .secondary
        context.fill(Path(roundedRect: rect, cornerRadius: 6), with: .color(tint.opacity(0.14)))
        context.draw(Text(Image(systemName: "arrow.up.and.down")).font(.system(size: 11)).foregroundColor(tint),
                     at: CGPoint(x: rect.midX, y: rect.minY + 10))
        context.draw(Text(title).font(.system(size: 9)).foregroundColor(tint),
                     at: CGPoint(x: rect.midX, y: rect.maxY - 9))
    }

    private struct PlotGeometry {
        let rect: CGRect
        let limits: ClosedRange<Double>
        let duration: Double

        init(size: CGSize, timeline: PitchTimeline, minimumDuration: Double = 0) {
            rect = CGRect(x: 36, y: 14, width: max(1, size.width - 82), height: max(1, size.height - 42))
            limits = timeline.limits
            duration = max(timeline.duration, minimumDuration)
        }

        var amplitudeHandle: CGRect { CGRect(x: rect.maxX + 8, y: rect.minY + 5, width: 30, height: 33) }
        var pitchHandle: CGRect { amplitudeHandle.offsetBy(dx: 0, dy: 39) }
        var pixelsPerSemitone: Double { rect.height / (limits.upperBound - limits.lowerBound) }

        func x(_ time: Double) -> Double { rect.minX + rect.width * time / duration }
        func y(_ pitch: Double) -> Double { rect.maxY - (pitch - limits.lowerBound) * pixelsPerSemitone }
        func time(at x: Double) -> Double { min(1, max(0, (x - rect.minX) / rect.width)) * duration }
    }
}
