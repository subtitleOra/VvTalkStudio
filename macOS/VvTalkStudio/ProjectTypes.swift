import Foundation

struct ACEVoice: Identifiable {
    let id: String
    let name: String
    let model: String

    init?(_ raw: JSON) {
        guard let id = raw["key"] as? String, let name = raw["name"] as? String,
              let model = raw["model_name"] as? String else { return nil }
        self.id = id
        self.name = name
        self.model = model
    }
}

enum Language: String, CaseIterable, Identifiable {
    case zh, ja, en
    var id: Self { self }
    var name: String { switch self { case .zh: "中文"; case .ja: "日语"; case .en: "英语" } }
    var unit: String { switch self { case .zh: "字"; case .ja: "拍"; case .en: "词" } }
    var reading: String { switch self { case .zh: "拼音"; case .ja: "假名"; case .en: "ARPAbet" } }
    var sample: String {
        switch self {
        case .zh: "今天，我们一起回家吧。\n路灯亮了，晚风穿过树梢。\n别着急，我会等你。"
        case .ja: "今日は、一緒に帰りましょう。\n明日も、いい日になりますように。"
        case .en: "Let's go home together today.\nThe lights are on, and the wind is quiet.\nTake your time. I'll wait for you."
        }
    }
}

enum Target: String, CaseIterable, Identifiable {
    case ace, synthv, vocaloid5, vocaloid6
    var id: Self { self }
    var title: String {
        switch self {
        case .ace: "ACE Studio"
        case .synthv: "Synthesizer V Studio 2 Pro"
        case .vocaloid5: "VOCALOID 5"
        case .vocaloid6: "VOCALOID 6"
        }
    }
    var ext: String { switch self { case .ace: "acep"; case .synthv: "svp"; default: "vsqx" } }
}

struct Parameter: Identifiable {
    let id: String
    let label: String
    let unit: String
    let initial: Double
    let range: ClosedRange<Double>
    let step: Double

    static let pitch = Self(id: "base_pitch", label: "基准音高", unit: "MIDI", initial: 61, range: 12...108, step: 1)
    static let amplitude = Self(id: "range_scale", label: "语调幅度", unit: "×", initial: 1, range: 0...4, step: 0.05)

    static let voice: [Self] = [
        .init(id: "rate", label: "语速", unit: "×", initial: 1, range: 0.25...4, step: 0.05),
        .init(id: "syllable_ms", label: "单元时长", unit: "ms", initial: 210, range: 80...3000, step: 10),
        pitch,
        amplitude,
        .init(id: "smoothing_ms", label: "曲线平滑", unit: "ms", initial: 10, range: 0...500, step: 5),
        .init(id: "bpm", label: "工程速度", unit: "BPM", initial: 120, range: 20...400, step: 1)
    ]
    static let pauses: [Self] = [
        .init(id: "comma_pause_ms", label: "逗号后", unit: "ms", initial: 180, range: 0...10000, step: 10),
        .init(id: "sentence_pause_ms", label: "句末", unit: "ms", initial: 420, range: 0...10000, step: 10),
        .init(id: "paragraph_pause_ms", label: "段落后", unit: "ms", initial: 700, range: 0...10000, step: 10)
    ]
    static let tail = Self(id: "pause_after_ms", label: "本句尾部停顿", unit: "ms", initial: 0, range: 0...30000, step: 10)

    func adjusted(_ value: Double, by delta: Double) -> Double {
        min(range.upperBound, max(range.lowerBound, value + delta))
    }
}

struct Sentence: Identifiable {
    let id: String
    let text: String
    let offset: Double
    let duration: Double
    init?(_ raw: JSON) {
        guard let id = raw["id"] as? String, let text = raw["text"] as? String else { return nil }
        self.id = id
        self.text = text
        offset = raw["offset"] as? Double ?? 0
        duration = raw["duration"] as? Double ?? 0
    }
}

struct PitchTimeline {
    struct Point {
        let time: Double
        let pitch: Double?
    }
    struct Note {
        let index: Int
        let lyric: String
        let start: Double
        let end: Double
        let key: Double
    }
    let points: [Point]
    let notes: [Note]
    let duration: Double
    let limits: ClosedRange<Double>
    let voicedRange: ClosedRange<Double>?

    init?(_ result: JSON?, keeping limits: ClosedRange<Double>? = nil) {
        guard let duration = result?["duration"] as? Double, duration > 0,
              let curve = result?["curve"] as? [JSON] else { return nil }
        let notes: [Note] = (result?["notes"] as? [JSON] ?? []).enumerated().compactMap { index, note in
            guard let start = note["start"] as? Double, let end = note["end"] as? Double,
                  let key = (note["key"] as? NSNumber)?.doubleValue, end > start else { return nil }
            return Note(index: index, lyric: note["lyric"] as? String ?? "", start: start, end: end, key: key)
        }
        // Keep extrema and both sides of each voiced/unvoiced boundary in the drawn curve.
        var sampled: [Point] = []
        var minimum: Point?, maximum: Point?, last: Point?
        let stride = max(1, curve.count / 2400)
        func flush() {
            if let minimum, let maximum {
                if minimum.time < maximum.time { sampled += [minimum, maximum] }
                else if maximum.time < minimum.time { sampled += [maximum, minimum] }
                else { sampled.append(minimum) }
            }
            minimum = nil
            maximum = nil
        }
        for (index, raw) in curve.enumerated() {
            guard let time = raw["time"] as? Double else { continue }
            let point = Point(time: time, pitch: raw["pitch"] as? Double)
            if let pitch = point.pitch {
                if last?.pitch == nil { sampled.append(point) }
                if pitch < (minimum?.pitch ?? .infinity) { minimum = point }
                if pitch > (maximum?.pitch ?? -.infinity) { maximum = point }
                if index % stride == stride - 1 { flush() }
            } else if let last, last.pitch != nil {
                flush()
                sampled += [last, point]
            }
            last = point
        }
        flush()
        if let last { sampled.append(last) }
        self.init(points: sampled, notes: notes, duration: duration, keeping: limits)
    }

    init(points: [Point], notes: [Note], duration: Double, keeping limits: ClosedRange<Double>? = nil) {
        self.points = points
        self.notes = notes
        self.duration = duration
        let pitches = points.compactMap(\.pitch)
        if let low = pitches.min(), let high = pitches.max() { voicedRange = low...high }
        else { voicedRange = nil }
        let low = min(notes.map(\.key).min() ?? 60, voicedRange?.lowerBound ?? .infinity)
        let high = max(notes.map(\.key).max() ?? 60, voicedRange?.upperBound ?? -.infinity)
        let middle = (low + high) / 2
        let lower = min(floor(low - 1), floor(middle - 3), limits?.lowerBound ?? .infinity)
        let upper = max(ceil(high + 1), ceil(middle + 3), limits?.upperBound ?? -.infinity)
        self.limits = lower...upper
    }
}

func fixed(_ value: Double, digits: Int = 2) -> String {
    String(format: "%.*f", locale: Locale(identifier: "en_US_POSIX"), digits, value)
}
