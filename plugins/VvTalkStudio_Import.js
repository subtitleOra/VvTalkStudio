/* VvTalk Studio: ES5.1, official SV2 Pro 2.1.0+ host APIs, no filesystem API. */
var EMBEDDED_DATA = null;

function getClientInfo() {
    return {name: "导入剪贴板语调", category: "VvTalk Studio", author: "VvTalk Studio",
            versionNumber: 2, minEditorVersion: 0x020100};
}

function languageCode(value) {
    if (value === undefined || value === null) { return "zh"; }
    if (value === "zh" || value === "ja" || value === "en") { return value; }
    throw new Error("工程语言必须是 zh、ja 或 en；未修改当前工程。");
}

function hostLanguage(value) {
    return {zh: "mandarin", ja: "japanese", en: "english"}[languageCode(value)];
}

function finiteNumber(value, lower, upper) {
    return typeof value === "number" && isFinite(value) && value >= lower && value <= upper;
}

function validateData(data) {
    if (!data || data.format !== "vvtalkstudio-sv2" || data.version !== 1 ||
        !finiteNumber(data.duration, 0, 3600) || !Array.isArray(data.notes) ||
        !data.notes.length || data.notes.length > 10000 || !Array.isArray(data.segments)) {
        throw new Error("请复制 VvTalk Studio 导出的 SV2 数据 JSON，再运行本脚本。");
    }
    var i, j, n, previous = 0, count = 0, segment, point, lastTime = -1;
    var language = languageCode(data.language), noteLanguage;
    for (i = 0; i < data.notes.length; i += 1) {
        n = data.notes[i];
        if (!n || !finiteNumber(n.start, previous, data.duration) ||
            !finiteNumber(n.end, n.start, data.duration) || n.end <= n.start ||
            !finiteNumber(n.pitch, 0, 127) || Math.floor(n.pitch) !== n.pitch ||
            typeof n.lyrics !== "string" || !n.lyrics.length || n.lyrics.length > 128) {
            throw new Error("音符数据无效；未修改当前工程。");
        }
        noteLanguage = languageCode(n.language === undefined ? data.language : n.language);
        if (noteLanguage !== language || (noteLanguage !== "zh" && n.pinyinOverride)) {
            throw new Error("音符语言与工程语言不一致，或非中文使用了拼音；未修改当前工程。");
        }
        previous = n.end;
    }
    for (i = 0; i < data.segments.length; i += 1) {
        segment = data.segments[i];
        if (!Array.isArray(segment) || !segment.length) {
            throw new Error("音高分段无效；未修改当前工程。");
        }
        for (j = 0; j < segment.length; j += 1) {
            point = segment[j];
            if (!Array.isArray(point) || point.length !== 2 ||
                !finiteNumber(point[0], lastTime, data.duration) ||
                !finiteNumber(point[1], 0, 127)) {
                throw new Error("音高曲线无效；未修改当前工程。");
            }
            lastTime = point[0];
            count += 1;
        }
    }
    if (count > 1500000) { throw new Error("曲线点过多；未修改当前工程。"); }
}

function prepareImport(data, axis) {
    var group = SV.create("NoteGroup"), track = SV.create("Track");
    var ref = SV.create("NoteGroupReference"), i, j, note, source, start, end;
    var curve, segment, anchorTime, anchorPitch, points, lastEnd = 0;
    group.setName(data.title || "VvTalk 语音调教");
    track.setName(data.title || "VvTalk 语音调教");
    for (i = 0; i < data.notes.length; i += 1) {
        source = data.notes[i];
        start = Math.round(axis.getBlickFromSeconds(source.start));
        end = Math.round(axis.getBlickFromSeconds(source.end));
        if (start < lastEnd || end <= start) {
            throw new Error("当前工程速度下音符量化发生重叠；未修改当前工程。");
        }
        note = SV.create("Note");
        note.setOnset(start);
        note.setDuration(end - start);
        note.setPitch(source.pitch);
        note.setLyrics(source.lyrics);
        note.setLanguageOverride(hostLanguage(source.language === undefined ? data.language : source.language));
        note.setScriptData("vvtalkstudio.sourceLyrics", source.sourceLyrics || source.lyrics);
        if (source.pinyinOverride) { note.setScriptData("vvtalkstudio.pinyinOverride", source.pinyinOverride); }
        if (source.pronunciationOverride) { note.setScriptData("vvtalkstudio.pronunciationOverride", source.pronunciationOverride); }
        if (source.reading) { note.setScriptData("vvtalkstudio.reading", source.reading); }
        if (source.phonemes) { note.setScriptData("vvtalkstudio.phonemes", source.phonemes); }
        if (source.stressOverride) { note.setScriptData("vvtalkstudio.stressOverride", source.stressOverride); }
        note.setScriptData("vvtalkstudio.language", languageCode(data.language));
        group.addNote(note);
        lastEnd = end;
    }
    for (i = 0; i < data.segments.length; i += 1) {
        segment = data.segments[i];
        anchorTime = Math.round(axis.getBlickFromSeconds(segment[0][0]));
        anchorPitch = segment[0][1];
        if (segment.length === 1) {
            curve = SV.create("PitchControlPoint");
        } else {
            curve = SV.create("PitchControlCurve");
            points = [];
            for (j = 0; j < segment.length; j += 1) {
                points.push([Math.round(axis.getBlickFromSeconds(segment[j][0])) - anchorTime,
                             segment[j][1] - anchorPitch]);
            }
            curve.setPoints(points);
        }
        curve.setPosition(anchorTime);
        curve.setPitch(anchorPitch);
        group.addPitchControl(curve);
    }
    ref.setTarget(group);
    ref.setTimeOffset(0);
    ref.setPitchOffset(0);
    track.addGroupReference(ref);
    return {group: group, track: track};
}

function main() {
    var data, prepared, project, mutated = false;
    try {
        data = EMBEDDED_DATA;
        if (data === null) {
            var text = SV.getHostClipboard();
            if (typeof text !== "string" || text.length > 100000000) {
                throw new Error("剪贴板内容为空或过大。");
            }
            data = JSON.parse(text.replace(/^\uFEFF/, ""));
        }
        validateData(data);
        project = SV.getProject();
        prepared = prepareImport(data, project.getTimeAxis());
        project.newUndoRecord();
        mutated = true;
        project.addNoteGroup(prepared.group);
        project.addTrack(prepared.track);
        var languageName = {zh: "普通话", ja: "日语", en: "英语"}[languageCode(data.language)];
        SV.showMessageBox("VvTalk Studio", "已新建独立轨道并导入语调。请选择支持" + languageName + "的声库。原轨道保持不变；可撤销本次导入。");
    } catch (error) {
        SV.showMessageBox("VvTalk Studio", String(error.message || error) +
            (mutated ? "\n宿主写入未完成，请撤销本次导入。" : ""));
    }
    SV.finish();
}
