"""Independent VSQX4 decoder for generated numerical regression fixtures.

This helper uses only the standard library. It does not load the original
VvTalk writer, speech generator, project caches, or any private QA directory.
"""
from __future__ import annotations

import bisect
import hashlib
import math
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def decode_vsqx(path):
    """Decode a constant-tempo, single-part VSQX4 test fixture independently."""
    root = ET.parse(path).getroot()
    for element in root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]
    if root.tag != "vsq4":
        raise ValueError("This comparison requires a VSQX4 source.")
    master = root.find("masterTrack")
    tempos = [(int(x.findtext("t")), int(x.findtext("v"))) for x in master.findall("tempo")]
    if len(tempos) != 1 or tempos[0][0] != 0:
        raise ValueError("The fixture must have one constant tempo at tick zero.")
    bpm = tempos[0][1] / 100
    resolution = int(master.findtext("resolution"))
    pre_measure = int(master.findtext("preMeasure"))
    signature = master.find("timeSig")
    numerator, denominator = int(signature.findtext("nu")), int(signature.findtext("de"))
    rate = bpm * resolution / 60
    parts = root.findall("vsTrack/vsPart")
    if len(parts) != 1:
        raise ValueError("The fixture must contain exactly one part.")
    part = parts[0]
    part_tick = int(part.findtext("t"))
    notes = []
    for note in part.findall("note"):
        onset, duration = int(note.findtext("t")), int(note.findtext("dur"))
        notes.append({"tick_on": onset, "tick_off": onset + duration,
                      "start": onset / rate, "end": (onset + duration) / rate,
                      "key": int(note.findtext("n")), "lyric": note.findtext("y", "")})
    notes.sort(key=lambda note: note["tick_on"])
    changes, raw = {}, []
    for controller in part.findall("cc"):
        value = controller.find("v")
        if value is None or value.get("id") not in ("P", "S"):
            continue
        tick, name, amount = int(controller.findtext("t")), value.get("id"), int(value.text)
        changes.setdefault(tick, {})[name] = amount
        raw.append({"tick": tick, "parameter": name, "value": amount})
    timeline, pbs, pit = [], 2, 0
    for tick, change in sorted(changes.items()):
        pbs, pit = change.get("S", pbs), change.get("P", pit)
        timeline.append({"tick": tick, "pbs": pbs, "pit": pit})
    prefix = pre_measure * resolution * numerator * 4 / denominator
    return {"path": str(Path(path).resolve()), "sha256": digest(path),
            "resolution": resolution, "bpm": bpm, "tick_rate": rate,
            "pre_measure": pre_measure, "time_signature": [numerator, denominator],
            "part_tick": part_tick, "project_offset_seconds": (part_tick - prefix) / rate,
            "notes": notes, "controllers": raw, "timeline": timeline,
            "note_starts": [note["tick_on"] for note in notes],
            "controller_ticks": [event["tick"] for event in timeline]}


def pitch_at(decoded, seconds):
    tick = seconds * decoded["tick_rate"]
    index = bisect.bisect_right(decoded["note_starts"], tick + 1e-7) - 1
    if index < 0 or tick >= decoded["notes"][index]["tick_off"] - 1e-7:
        return None
    event_index = bisect.bisect_right(decoded["controller_ticks"], tick + 1e-7) - 1
    pbs, pit = (2, 0) if event_index < 0 else (
        decoded["timeline"][event_index]["pbs"], decoded["timeline"][event_index]["pit"])
    return decoded["notes"][index]["key"] + pit * pbs / 8192


def error_stats(errors):
    if not errors:
        return {"count": 0, "max_abs_cents": None, "rms_cents": None}
    return {"count": len(errors), "max_abs_cents": max(abs(x) for x in errors) * 100,
            "rms_cents": math.sqrt(statistics.mean(x * x for x in errors)) * 100}


def summary(decoded):
    return {key: value for key, value in decoded.items()
            if key not in {"timeline", "note_starts", "controller_ticks", "controllers"}} | {
        "pit_count": sum(x["parameter"] == "P" for x in decoded["controllers"]),
        "pbs_events": [x for x in decoded["controllers"] if x["parameter"] == "S"]}


def roundtrip_actual(path, target, importer, exporter):
    before = decode_vsqx(path)
    imported = importer(path)
    exporter(imported, target)
    after = decode_vsqx(target)
    shift = before["notes"][0]["start"]
    sample_times = {event["tick"] / before["tick_rate"] - shift for event in before["timeline"]}
    sample_times.update(event["tick"] / after["tick_rate"] for event in after["timeline"])
    sample_times.update((note["start"] + note["end"]) / 2 for note in after["notes"])
    errors, differences = [], []
    for time in sorted(sample_times):
        original, studio = pitch_at(before, time + shift), pitch_at(after, time)
        if original is not None and studio is not None:
            errors.append(studio - original)
            differences.append({"time": time, "original_midi": original, "studio_midi": studio,
                                "difference_cents": (studio - original) * 100})
    geometry_equal = len(before["notes"]) == len(after["notes"]) and all(
        abs((old["start"] - shift) - new["start"]) < 1e-6 and
        abs((old["end"] - shift) - new["end"]) < 1e-6 and
        old["key"] == new["key"] and old["lyric"] == new["lyric"]
        for old, new in zip(before["notes"], after["notes"]))
    pbs = max(event["pbs"] for event in after["timeline"])
    tolerance = pbs / 8192 / 2 + 1e-6
    source_hash_unchanged = digest(path) == before["sha256"]
    return {"original": summary(before), "studio": summary(after),
            "original_file_unchanged": source_hash_unchanged, "geometry_equal": geometry_equal,
            "source_offset_seconds_reported_by_importer": imported["source_offset_seconds"],
            "comparison_origin_shift_seconds": shift, "error": error_stats(errors),
            "allowed_quantization_cents": tolerance * 100,
            "worst_points": sorted(differences, key=lambda x: abs(x["difference_cents"]), reverse=True)[:5],
            "passed": geometry_equal and source_hash_unchanged and bool(errors) and max(map(abs, errors)) <= tolerance}
