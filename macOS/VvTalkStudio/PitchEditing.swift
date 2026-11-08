import Foundation

enum PitchEdit {
    case duration(note: Int, seconds: Double)
    case transpose(Double)
    case amplitude(Double)

    var action: String {
        switch self {
        case .duration: "调整发音时长"
        case .transpose: "调整整体音高"
        case .amplitude: "调整语调幅度"
        }
    }
}

struct PitchSection {
    let id: String
    let offset: Double
    let duration: Double
    let firstNote: Int
    let base: Double
    let amplitude: Double
}

struct CurveTransform {
    var center: Double = 0
    var scale: Double = 1
    var shift: Double = 0

    func pitch(_ pitch: Double) -> Double { center + (pitch - center) * scale + shift }
    func key(_ key: Double) -> Double { key + shift }
}

struct PitchEditing {
    let timeline: PitchTimeline
    let sections: [PitchSection]
    let reference: Bool
    let documentDuration: Double

    func section(for note: Int) -> PitchSection? { sections.last { $0.firstNote <= note } }

    func duration(_ seconds: Double, for note: PitchTimeline.Note) -> Double {
        let current = note.end - note.start
        if reference {
            let nextStart = timeline.notes.first { $0.index == note.index + 1 }?.start ?? timeline.duration
            let maximum = nextStart - note.start
            guard maximum > 0 else { return current }
            return min(maximum, max(min(current, 0.001), seconds))
        }
        guard let section = section(for: note.index) else { return current }
        let maximum = min(30, current + 599.999 - section.duration, current + 3600 - documentDuration)
        guard maximum >= 0.02 else { return current }
        return min(maximum, max(0.02, seconds))
    }

    func referenceTransform(_ edit: PitchEdit) -> CurveTransform {
        guard let pitches = timeline.voicedRange else { return CurveTransform() }
        switch edit {
        case .transpose(let delta):
            let keys = timeline.notes.map(\.key)
            let low = ceil(max(-(keys.min() ?? 0), -48 - pitches.lowerBound))
            let high = floor(min(127 - (keys.max() ?? 127), 175 - pitches.upperBound))
            return CurveTransform(shift: min(high, max(low, delta)))
        case .amplitude(let delta):
            let radius = (pitches.upperBound - pitches.lowerBound) / 2
            guard radius > 0 else { return CurveTransform() }
            let center = pitches.lowerBound + radius
            let maximum = min((175 - center) / radius, (center + 48) / radius)
            return CurveTransform(center: center, scale: min(maximum, max(0.125, pow(2, delta))))
        case .duration:
            return CurveTransform()
        }
    }

    func preview(_ edit: PitchEdit) -> PitchTimeline {
        switch edit {
        case .duration(let index, let length):
            guard let note = timeline.notes.first(where: { $0.index == index }) else { return timeline }
            let oldLength = note.end - note.start
            let delta = length - oldLength
            func time(_ time: Double) -> Double {
                if reference || time <= note.start { return time }
                if time >= note.end { return time + delta }
                return note.start + (time - note.start) * length / oldLength
            }
            let notes = timeline.notes.map {
                PitchTimeline.Note(index: $0.index, lyric: $0.lyric, start: time($0.start),
                                   end: $0.index == index ? $0.start + length : time($0.end), key: $0.key)
            }
            let points = reference ? timeline.points : timeline.points.map {
                PitchTimeline.Point(time: time($0.time), pitch: $0.pitch)
            }
            let duration = reference ? timeline.duration : timeline.duration + delta
            return PitchTimeline(points: points, notes: notes, duration: duration, keeping: timeline.limits)
        case .transpose, .amplitude:
            let transforms = reference ? [referenceTransform(edit)] : sections.map { section in
                switch edit {
                case .transpose(let delta):
                    let base = Parameter.pitch.adjusted(section.base, by: delta)
                    return CurveTransform(shift: base - section.base)
                case .amplitude(let delta):
                    let amplitude = Parameter.amplitude.adjusted(section.amplitude, by: delta)
                    let scale = section.amplitude > 0 ? amplitude / section.amplitude : 1
                    return CurveTransform(center: section.base, scale: scale)
                case .duration:
                    return CurveTransform()
                }
            }
            guard !transforms.isEmpty else { return timeline }
            var index = 0
            let points = timeline.points.map { point in
                while index + 1 < sections.count && point.time >= sections[index + 1].offset { index += 1 }
                return PitchTimeline.Point(time: point.time, pitch: point.pitch.map { transforms[index].pitch($0) })
            }
            index = 0
            let notes = timeline.notes.map { note in
                while index + 1 < sections.count && note.index >= sections[index + 1].firstNote { index += 1 }
                let key = reference ? transforms[index].key(note.key)
                    : (sections[index].base + transforms[index].shift).rounded(.toNearestOrEven)
                return PitchTimeline.Note(index: note.index, lyric: note.lyric, start: note.start, end: note.end, key: key)
            }
            return PitchTimeline(points: points, notes: notes, duration: timeline.duration, keeping: timeline.limits)
        }
    }
}
