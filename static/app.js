"use strict";

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const DEFAULT_SETTINGS = {rate:1,syllable_ms:210,comma_pause_ms:180,sentence_pause_ms:420,paragraph_pause_ms:700,base_pitch:61,range_scale:1,smoothing_ms:10,bpm:120};
const SAMPLE_TEXT = "今天，我们一起回家吧。\n路灯亮了，晚风穿过树梢。\n别着急，我会等你。";
const LANGUAGES = {
  zh:{name:"中文",unit:"字",edit:"逐字",reading:"拼音",sample:"今天，我们一起回家吧。",placeholder:"输入中文文稿，可用标点和换行分句。",readingHelp:"留空使用自动值；读音用带声调数字的拼音。"},
  ja:{name:"日语",unit:"拍",edit:"逐拍",reading:"假名",sample:"今日は、一緒に帰りましょう。",placeholder:"输入日语文稿，汉字由本机词典转换为假名拍。",readingHelp:"每行一拍；读音填单个假名拍，0 低 / 1 高。专名读音不对时，先保存原文，再在正文把该词改写为假名并重新生成。"},
  en:{name:"英语",unit:"词",edit:"逐词",reading:"ARPAbet",sample:"Let's go home together today.",placeholder:"输入英语文稿，按单词编辑读音和重音。",readingHelp:"读音用 ARPAbet，元音后带 0/1/2。音节重音如 0 1 会覆盖读音中的数字；留空使用词典值。"}
};
const TARGET_HELP = {ace:"导出一个保留连续音高的 ACEP 工程。",synthv:"导出一个 SVP 工程，在 Studio 2 Pro 中加载。",vocaloid5:"导出一个 VSQX 工程，在 VOCALOID 5 中导入。",vocaloid6:"导出一个 VSQX 工程，在 VOCALOID 6 中导入。"};
const state = {info:null,draft:{title:"回家的路",text:SAMPLE_TEXT,language:"zh",settings:{...DEFAULT_SETTINGS}},document:null,result:null,originalReference:null,selected:null,fullText:true,reference:false,source:null,stale:true,busy:false,previewBusy:false,revision:0,audioRevision:null,folder:null,saved:false,history:[],historyIndex:-1,historyTimer:null,pendingLanguage:null};
const recorder = {active:false,pending:false,request:0,stream:null,context:null,processor:null,source:null,gain:null,chunks:[],samples:0,started:0,timer:null,file:null,url:null};

function clone(value) { return JSON.parse(JSON.stringify(value)); }
function checkedLanguage(language) {
  const value = language ?? "zh";
  if (!Object.hasOwn(LANGUAGES,value)) throw new Error("工程语言不受支持，请使用中文、日语或英语工程。");
  return value;
}
function languageConfig() { return LANGUAGES[checkedLanguage(state.draft.language)]; }
function textLength(text,language = state.draft.language) {
  if (language === "en") return (text.match(/[A-Za-z]+(?:['’][A-Za-z]+)*/g) || []).length;
  if (language === "ja") return null;
  return (text.match(/[\u3400-\u4dbf\u4e00-\u9fff]/g) || []).length;
}
function unitSummary(text,knownCount) {
  const count = knownCount ?? textLength(text);
  return count === null ? (text.trim() ? "生成后显示拍数" : "0 拍") : `${count} ${languageConfig().unit}`;
}
function seconds(value) { return Number.isFinite(Number(value)) ? `${Number(value).toFixed(2)} 秒` : "— 秒"; }
function compactDocument(doc) {
  const language = checkedLanguage(doc.language);
  const out = {title:doc.title || "未命名文稿",text:doc.text || "",language,settings:{...DEFAULT_SETTINGS,...doc.settings}};
  if (doc.id) out.id = doc.id;
  if (doc.word_readings) out.word_readings = clone(doc.word_readings);
  if (Array.isArray(doc.sections) && doc.sections.length) out.sections = doc.sections.map(section => {
    if (checkedLanguage(section.language ?? language) !== language) throw new Error("句子语言与工程语言不一致，请打开对应语言工程，或新建文稿。");
    return {id:section.id,text:section.text,language,paragraph:section.paragraph,settings:section.settings || {},...(section.word_readings ? {word_readings:clone(section.word_readings)} : {}),characters:(section.characters || []).map(char => {
      if (checkedLanguage(char.language ?? language) !== language) throw new Error("发音单元语言与文稿语言不一致，当前编辑已保留。");
      return {lyric:char.lyric,language,pinyin_override:char.pinyin_override ?? null,pronunciation_override:char.pronunciation_override ?? null,stress_override:char.stress_override ?? null,accent_override:char.accent_override ?? null,duration_override_ms:char.duration_override_ms ?? null,pause_override_ms:char.pause_override_ms ?? null};
    })};
  });
  return out;
}
function copyResult(result) { return result ? {...result,notes:clone(result.notes || [])} : null; }
function snapshot() { return {draft:clone(state.draft),reference:state.reference,result:state.reference ? copyResult(state.result) : null,source:state.source,selected:state.selected,fullText:state.fullText}; }
function historyValue(value) { return JSON.stringify({draft:value.draft,reference:value.reference,result:value.result}); }
function persist() {
  try { localStorage.setItem("vvtalk-studio-draft-v1",JSON.stringify({...snapshot(),saved_at:new Date().toISOString()})); }
  catch (_) { setStatus("浏览器草稿空间不足，请保存文稿到本机。",true); }
}
function checkpoint() {
  clearTimeout(state.historyTimer); state.historyTimer = null;
  const next = snapshot();
  if (state.historyIndex >= 0 && historyValue(state.history[state.historyIndex]) === historyValue(next)) return;
  state.history = state.history.slice(0,state.historyIndex + 1);
  state.history.push(next); if (state.history.length > 30) state.history.shift();
  state.historyIndex = state.history.length - 1; persist(); updateButtons();
}
function changed(immediate = false) {
  state.stale = !state.reference; state.saved = false; state.revision++;
  if (!state.reference) $("#curveState").textContent = state.result ? "待重新生成" : "等待生成";
  $("#curveState").classList.toggle("stale",Boolean(state.result) && !state.reference);
  $("#saveState").textContent = "未保存的修改";
  $("#audioStale").hidden = state.audioRevision === null || state.audioRevision === state.revision;
  clearTimeout(state.historyTimer);
  if (immediate) checkpoint(); else state.historyTimer = setTimeout(checkpoint,600);
  updateSummary(); updateButtons();
}
async function api(path,payload) {
  const response = await fetch(path,payload === undefined ? {} : {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
  let data;
  try { data = await response.json(); } catch (_) { throw new Error("本地服务没有返回有效结果，请检查工作台是否仍在运行。"); }
  if (!response.ok || data.error) throw new Error(typeof data.error === "string" ? data.error : data.error?.message || data.message || `请求失败（${response.status}）`);
  return data;
}
function setStatus(message,error = false,busy = false) {
  $("#status").textContent = message; $("#status").classList.toggle("error",error);
  $("#statusDot").classList.toggle("error",error); $("#statusDot").classList.toggle("busy",busy);
}
async function perform(message,action) {
  if (state.busy) return;
  state.busy = true; updateButtons(); setStatus(message,false,true);
  try { return await action(); } catch (error) { setStatus(error.message || "操作失败，请重试。",true); return null; }
  finally { state.busy = false; updateButtons(); }
}
function sectionDraft() { return state.draft.sections?.find(section => section.id === state.selected); }
function selectedSection() { return state.document?.sections?.find(section => section.id === state.selected) || null; }
function currentResult() { return state.reference ? state.result : (!state.fullText && selectedSection() ? selectedSection().result : state.result); }
function renderAlignmentStatus(reset = false) {
  const code = checkedLanguage($("#referenceLanguage").value || state.draft.language), config = LANGUAGES[code];
  const resources = state.info?.alignment_by_language?.[code] || (code === "zh" ? state.info?.alignment : null);
  const available = Boolean(resources?.available);
  $("#automaticAlignment").disabled = !available || state.busy;
  if (reset || !available) $("#automaticAlignment").checked = available;
  $("#automaticAlignmentLabel").textContent = available ? `使用本机 MFA 自动${config.edit}对齐（需复核）` : `${config.name}自动${config.edit}对齐（本机资源尚未就绪）`;
  $("#automaticAlignmentLabel").title = resources?.message || "";
  $("#alignmentHelp").textContent = available && $("#automaticAlignment").checked ? `使用本机 MFA 估计${config.edit}时间，仍需复核；上传标注时优先使用标注。` : `没有${config.edit}标注时生成均分草稿，需要核对${config.unit}数与起止时间。${resources?.message || ""}`;
  $("#referenceText").placeholder = `输入录音中读出的${config.name}；标注需与${config.edit}单元一一对应。`;
  $("#referenceUnitHelp").textContent = `${config.name}按${config.unit}对齐；CSV 的 start/end/lyric 行数与生成单元数一致，不能直接沿用另一语言的字界。`;
}
function validateResultLanguage(result, expected) {
  const language = checkedLanguage(result.language);
  if (expected && language !== expected) throw new Error("参考结果语言与所选语言不一致。请选择原工程语言，或重新导入对应语言录音。");
  if ((result.notes || []).some(note => note.language && checkedLanguage(note.language) !== language)) throw new Error("参考音符语言与结果语言不一致，不能静默重新解释原曲线。");
  return language;
}
function updateSummary() {
  const sections = state.reference ? [] : state.draft.sections || [];
  const known = state.reference ? state.result?.notes?.length : state.document?.text === state.draft.text && checkedLanguage(state.document.language) === state.draft.language ? state.document.character_count : undefined;
  $("#sectionCount").textContent = `${sections.length} 句`;
  $("#characterCount").textContent = unitSummary(state.draft.text,known);
  $("#totalDuration").textContent = state.result ? seconds(state.result.duration) : "— 秒";
  const section = selectedSection();
  const selectedCount = !state.fullText && section?.text === $("#textEditor").value ? section.characters?.length : known;
  $("#textCount").textContent = unitSummary($("#textEditor").value,selectedCount);
}
function updateButtons() {
  const editing = state.busy;
  ["#newButton","#openButton","#saveButton","#referenceButton","#fullTextButton","#analyzeButton","#exportButton","#copySv2Button","#installScript","#resetSettings","#resetCharacters"].forEach(id => $(id).disabled = editing);
  $("#analyzeButton").disabled = editing || state.reference;
  $("#analyzeButton").textContent = state.busy ? "处理中…" : state.result ? "重新生成语调" : "生成语调";
  $("#exportButton").disabled = editing || !state.result;
  $("#copySv2Button").disabled = editing || !state.result;
  $("#resetCharacters").disabled = editing || (state.reference ? !state.originalReference : state.fullText || !selectedSection());
  $("#undoButton").disabled = editing || state.historyIndex <= 0;
  $("#redoButton").disabled = editing || state.historyIndex >= state.history.length - 1;
  $("#previewButton").disabled = editing || state.previewBusy || !state.result;
  $("#previewButton").textContent = state.previewBusy ? "合成中…" : "试听";
  $("#globalSettings").disabled = editing || state.reference;
  $$("#characterRows input, #characterRows select").forEach(input => input.disabled = editing);
  $("#language").disabled = editing || state.reference;
  $("#language").title = state.reference ? "参考结果的语言已锁定；要改变语言，请新建文稿或重新导入对应语言录音。" : "非空文稿切换语言时需确认新建，当前内容不会被自动按另一语言解释。";
  $("#sampleButton").disabled = editing || state.reference || Boolean(state.draft.text.trim());
  $("#documentTitle").disabled = editing;
  $("#targetEngine").disabled = editing;
  $$("[data-local]").forEach(input => input.disabled = editing || state.reference || state.fullText || !sectionDraft());
  $("#textEditor").readOnly = state.reference || editing;
  $("#referenceSubmit").disabled = editing || recorder.active || recorder.pending;
  $("#recordStart").disabled = editing || recorder.active || recorder.pending;
  $("#referenceAudioFile").disabled = editing || recorder.active || recorder.pending;
  $("#referenceAlignmentFile").disabled = editing || recorder.active || recorder.pending;
  $("#referenceLanguage").disabled = editing || recorder.active || recorder.pending;
  $("#fullTextButton").textContent = state.reference ? "返回文稿编辑" : state.fullText && state.draft.sections?.length ? "查看当前句" : "编辑全文";
  $("#installScript").disabled = editing;
}
function renderNavigation() {
  const list = $("#sectionList"); list.replaceChildren();
  if (state.reference) {
    const item = document.createElement("div"); item.className = "nav-empty";
    item.textContent = `已加载${languageConfig().name}参考曲线。可以调整${languageConfig().edit}起止时间和基准音高，原始音高曲线保持在录音时间轴。`; list.append(item); return;
  }
  const sections = state.draft.sections || [];
  if (!sections.length) { const item = document.createElement("div"); item.className = "nav-empty"; item.textContent = "生成语调后，句子会出现在这里。点击句子，分别调整读音、时长和停顿。"; list.append(item); return; }
  sections.forEach((section,index) => {
    const item = document.createElement("button"); item.className = "section-item"; item.classList.toggle("active",section.id === state.selected && !state.fullText); item.type = "button"; item.setAttribute("role","listitem"); item.setAttribute("aria-current",section.id === state.selected && !state.fullText ? "true" : "false");
    const num = document.createElement("span"); num.className = "section-number"; num.textContent = String(index+1).padStart(2,"0");
    const body = document.createElement("span"); const words = document.createElement("span"); words.className = "section-text"; words.textContent = section.text.trim(); body.append(words);
    const known = state.document?.sections?.find(s => s.id === section.id); if (known) { const time = document.createElement("span"); time.className = "section-time"; time.textContent = seconds(known.duration); body.append(time); }
    item.append(num,body); item.addEventListener("click",() => { state.selected = section.id; state.fullText = false; render(); }); list.append(item);
  });
}
function renderEditor() {
  const section = sectionDraft();
  const config = languageConfig();
  $("#language").value = state.draft.language;
  $("#textEditor").placeholder = config.placeholder;
  $("#textEditor").lang = state.draft.language === "zh" ? "zh-CN" : state.draft.language;
  $("#sampleButton").textContent = `${config.name}示例`;
  $("#syllableDurationLabel").textContent = `单${config.unit}时长`;
  $("#characterLabel").textContent = `${config.edit}调整`;
  $("#documentTitle").value = state.draft.title;
  $("#textEditor").value = !state.reference && !state.fullText && section ? section.text : state.draft.text;
  const index = state.draft.sections?.findIndex(s => s.id === state.selected) ?? -1;
  $("#editorEyebrow").textContent = state.reference ? "参考曲线" : state.fullText ? "全文编辑" : `第 ${index+1} 句`;
  $("#editorTitle").textContent = state.reference ? "保留原始声音的语调" : state.fullText ? "把文字变成自然的语调" : "让每一句话更自然";
  $("#textHelp").textContent = state.reference ? `参考结果语言锁定为${config.name}，原曲线保持时间轴；改变语言需重新导入。` : state.fullText && state.draft.sections?.length ? `改写全文后会重新分句，并重新生成${config.edit}时长。` : `${config.name}${config.edit}处理；标点决定停顿，换行划分段落。`;
  $$("[data-setting]").forEach(input => { input.value = state.draft.settings[input.dataset.setting]; });
  $$("[data-range]").forEach(input => { input.value = state.draft.settings[input.dataset.range]; });
  $$("[data-local]").forEach(input => { input.value = section?.settings?.[input.dataset.local] ?? ""; });
  $("#sentenceSettings").hidden = state.reference || state.fullText || !section;
  $("#curveState").textContent = state.reference ? state.result?.alignment_source==="equal_initial" ? "均分草稿" : "参考曲线" : state.stale && state.result ? "待重新生成" : state.result ? "已生成" : "等待生成";
  $("#curveState").classList.toggle("stale",state.stale && !state.reference && Boolean(state.result));
  $("#saveState").textContent = state.saved ? "已保存到本机" : state.stale ? "未保存的修改" : "本机草稿";
  $("#audioStale").hidden=state.audioRevision===null || state.audioRevision===state.revision;
  $("#resetCharacters").textContent = state.reference ? "恢复原导入" : "重置本句";
  $("#referencePlayback").hidden = !state.reference || !state.source?.audio_id;
  const sourceUrl=state.source?.audio_url;
  $("#sourceAudioStale").hidden = Boolean(sourceUrl);
  $("#referenceSourceAudio").hidden = !sourceUrl;
  if (sourceUrl && $("#referenceSourceAudio").getAttribute("src")!==sourceUrl) $("#referenceSourceAudio").src=sourceUrl;
  updateSummary(); renderCharacters(); renderCurve(); renderWarnings();
}
function renderCharacters() {
  const rows = $("#characterRows"); rows.replaceChildren();
  const config = languageConfig(), language = state.draft.language;
  const extraHeader = language === "zh" ? "" : `<th scope='col'>${config.reading}</th><th scope='col'>${language === "ja" ? "拍音高 0/1" : "音节重音 0/1/2"}</th>`;
  $("#characterHead").innerHTML=state.reference ? `<tr><th scope='col'>${config.unit}</th><th scope='col'>开始 <span>s</span></th><th scope='col'>结束 <span>s</span></th><th scope='col'>基准音高 <span>MIDI</span></th>${extraHeader}</tr>` : `<tr><th scope='col'>${config.unit}</th><th scope='col'>${config.reading}</th>${language === "zh" ? "" : `<th scope='col'>${language === "ja" ? "拍音高 0/1" : "音节重音 0/1/2"}</th>`}<th scope='col'>时长 <span>ms</span></th><th scope='col'>${config.unit}后停顿 <span>ms</span></th></tr>`;
  $("#characterHelp").textContent=state.reference ? `修改时间不会拉伸原参考音高；${state.result?.alignment_source==="equal_initial" ? `均分草稿需核对${config.unit}数与起止时间。` : "音符需保持有序、无重叠。"}${language === "zh" ? "" : "读音与重音仅更新工程元数据。"}` : config.readingHelp;
  rows.closest("table").classList.toggle("multilingual-table",language !== "zh");
  if (state.reference) {
    (state.result?.notes || []).forEach((note,index) => {
      const tr=document.createElement("tr"),lyric=document.createElement("td"); lyric.textContent=note.lyric; tr.append(lyric);
      [{field:"start",label:"开始秒",min:0,max:state.result.duration,step:"0.001"},{field:"end",label:"结束秒",min:0,max:state.result.duration,step:"0.001"},{field:"key",label:"基准音高MIDI",min:0,max:127,step:"1"}].forEach(spec => {
        const td=document.createElement("td"),input=document.createElement("input"); input.type="number"; input.value=spec.field==="key" ? note[spec.field] : Number(note[spec.field]).toFixed(3); input.min=spec.min; input.max=spec.max; input.step=spec.step; input.required=true; input.setAttribute("aria-label",`第${index+1}${config.unit}「${note.lyric}」${spec.label}`);
        input.addEventListener("input",() => { note[spec.field]=input.value==="" ? null : Number(input.value); changed(); renderCurve(); renderWarnings(); const issues=referenceNoteErrors(); $$("#characterRows tr").forEach((row,rowIndex)=>row.classList.toggle("invalid",issues.some(issue=>issue.index===rowIndex))); setStatus(issues.length ? issues[0].message : "参考音符已修改，原录音音高曲线保持在原时间轴。",Boolean(issues.length)); });
        input.addEventListener("change",checkpoint);
        td.append(input);tr.append(td);
      });
      if (language !== "zh") readingSpecs(note).forEach(spec => appendUnitField(tr,note,index,spec,note,true));
      rows.append(tr);
    }); return;
  }
  const section = selectedSection(), edits = sectionDraft()?.characters;
  if (state.fullText || !section) {
    const tr = document.createElement("tr"), td = document.createElement("td"); td.colSpan = language === "zh" ? 4 : 5; td.className = "empty-table";
    td.textContent = state.document ? `在左侧选择一句话，${config.edit}调整读音与时长。` : `生成语调后，可在这里${config.edit}精修。`; tr.append(td); rows.append(tr); return;
  }
  section.characters.forEach((char,index) => {
    const tr = document.createElement("tr"), lyric = document.createElement("td"); lyric.textContent = char.lyric; lyric.title = char.source_text ? `原词：${char.source_text}${char.word_accent != null ? `；词典重音核：${char.word_accent}` : ""}` : char.lyric; tr.append(lyric);
    const specs = [...readingSpecs(char),{field:"duration_override_ms",value:Math.round(char.duration_ms),aria:"时长毫秒",type:"number",min:20,max:30000},{field:"pause_override_ms",value:Math.round(char.pause_after_ms),aria:`${config.unit}后停顿毫秒`,type:"number",min:0,max:30000}];
    specs.forEach(spec => appendUnitField(tr,char,index,spec,edits?.[index],false)); rows.append(tr);
  });
}
function readingSpecs(unit) {
  const language = state.draft.language;
  const reading = {field:language === "zh" ? "pinyin_override" : "pronunciation_override",value:language === "en" && unit.reading_source === "unknown" ? "" : unit.auto_reading || unit.reading || unit.pinyin || "",aria:languageConfig().reading,type:"text"};
  if (language === "zh") return [reading];
  return [reading,language === "ja" ? {field:"accent_override",value:unit.auto_accent ?? unit.accent ?? "",aria:"拍音高低0高1",type:"number",min:0,max:1} : {field:"stress_override",value:unit.stress || [],aria:"音节重音0弱1主2次",type:"text",array:true}];
}
function appendUnitField(tr,unit,index,spec,edit,reference) {
  const td=document.createElement("td"),input=document.createElement("input"); input.type=spec.type;input.spellcheck=false;
  const current=edit?.[spec.field]; input.value=Array.isArray(current) ? current.join(" ") : current ?? "";
  input.placeholder=Array.isArray(spec.value) ? spec.value.join(" ") : String(spec.value);
  input.setAttribute("aria-label",`第${index+1}${languageConfig().unit}「${unit.lyric}」${spec.aria}`);input.title=`自动值：${input.placeholder}`;
  if(state.draft.language==="en" && spec.field==="pronunciation_override" && (unit.reading_source==="unknown" || !spec.value)){input.placeholder="未收录 · 填 ARPAbet";input.title="本机词典未收录该词，请填写带重音数字的 ARPAbet 读音。";}
  input.classList.toggle("edited",input.value!=="");input.disabled=state.busy;
  if(spec.type==="number"){input.min=spec.min;input.max=spec.max;input.step=1;}
  input.addEventListener("input",()=>{
    input.setCustomValidity("");delete input.dataset.validationError;const raw=input.value.trim();
    if(spec.array && raw && !/^[012](?:[\s,]+[012])*$/.test(raw)){input.dataset.validationError="重音请按音节填写0、1或2，例如0 1。";input.setCustomValidity(input.dataset.validationError);setStatus(input.dataset.validationError,true);return;}
    const value=raw==="" ? null : spec.array ? raw.split(/[\s,]+/).map(Number) : spec.type==="number" ? Number(raw) : raw;
    const target=reference ? unit : sectionDraft()?.characters[index];if(!target)return;target[spec.field]=value;
    input.classList.toggle("edited",raw!=="");changed();setStatus(reference ? "参考读音元数据已修改，原录音音高曲线保持原时间轴。" : `${languageConfig().edit}修改已保留，重新生成后更新曲线和工程。`);
  });
  input.addEventListener("change",checkpoint);td.append(input);tr.append(td);
}
function svgElement(name,attrs,text) { const el = document.createElementNS("http://www.w3.org/2000/svg",name); Object.entries(attrs).forEach(([key,value]) => el.setAttribute(key,String(value))); if (text !== undefined) el.textContent = text; return el; }
function pitchName(value) { const names = ["C","C♯","D","D♯","E","F","F♯","G","G♯","A","A♯","B"]; const rounded = Math.round(value); return `${names[(rounded%12+12)%12]}${Math.floor(rounded/12)-1}`; }
function renderCurve() {
  const svg = $("#pitchChart"), result = currentResult(); svg.replaceChildren();
  if (!result?.curve?.length) { svg.append(svgElement("text",{x:360,y:110,"text-anchor":"middle",class:"chart-empty"},"生成语调后，音高曲线会显示在这里"));svg.setAttribute("aria-label","等待生成连续音高曲线");$("#curveSummary").textContent="音高遵循语音声调与句子语气。";$(".unvoiced-key").hidden=true;$("#unvoicedLabel").hidden=true; $("#selectedDuration").textContent = "— 秒"; return; }
  const points = result.curve, voiced = points.filter(p => Number.isFinite(p.pitch));
  const pitches = voiced.map(p => p.pitch); let low = pitches.length ? Math.floor(pitches.reduce((a,b) => Math.min(a,b),108)-2) : 56, high = pitches.length ? Math.ceil(pitches.reduce((a,b) => Math.max(a,b),0)+2) : 68;
  if (high-low < 8) { const middle = (high+low)/2; low = middle-4; high = middle+4; }
  const duration = Math.max(Number(result.duration) || 0,0.01), left=44,right=704,top=15,bottom=185;
  const x = time => left+(Math.max(0,Math.min(duration,time))/duration)*(right-left), y = pitch => bottom-(pitch-low)/(high-low)*(bottom-top);
  let unvoicedStart=null,unvoicedCount=0,unvoicedDuration=0;
  points.forEach((point,index) => {
    if (!Number.isFinite(point.pitch) && unvoicedStart===null) unvoicedStart=point.time;
    if (unvoicedStart!==null && (Number.isFinite(point.pitch) || index===points.length-1)) {
      const end=index===points.length-1 ? duration : point.time;
      if (end-unvoicedStart>.008) { unvoicedCount++;unvoicedDuration+=end-unvoicedStart;if (state.reference) svg.append(svgElement("rect",{x:x(unvoicedStart),y:top,width:Math.max(1,x(end)-x(unvoicedStart)),height:bottom-top,class:"chart-unvoiced"})); }
      unvoicedStart=null;
    }
  });
  for (let i=0;i<5;i++) { const value = low+(high-low)*i/4; svg.append(svgElement("line",{x1:left,x2:right,y1:y(value),y2:y(value),class:"chart-grid"})); svg.append(svgElement("text",{x:34,y:y(value)+4,"text-anchor":"end",class:"chart-label"},pitchName(value))); }
  for (let i=0;i<=4;i++) { const time = duration*i/4; svg.append(svgElement("line",{x1:x(time),x2:x(time),y1:top,y2:bottom,class:"chart-grid"})); svg.append(svgElement("text",{x:x(time),y:223,"text-anchor":"middle",class:"chart-label"},`${time.toFixed(duration<10?1:0)}s`)); }
  const notes = result.notes || []; const lyricStride = Math.max(1,Math.ceil(notes.length/30));
  notes.forEach((note,index) => {
    if (notes.length <= 70) svg.append(svgElement("rect",{x:x(note.start),y:bottom+8,width:Math.max(1,x(note.end)-x(note.start)),height:19,rx:3,class:"chart-note"}));
    if (index%lyricStride===0) svg.append(svgElement("text",{x:(x(note.start)+x(note.end))/2,y:bottom+22,"text-anchor":"middle",class:"chart-lyric"},note.lyric || ""));
  });
  let path="", pen=false; const stride = Math.max(1,Math.floor(points.length/2200));
  points.forEach((point,index) => {
    if (!Number.isFinite(point.pitch)) { pen=false; return; }
    const edge = !pen || index===points.length-1 || !Number.isFinite(points[index+1]?.pitch);
    if (index%stride !== 0 && !edge) return;
    path += `${pen?"L":"M"}${x(point.time).toFixed(2)},${y(point.pitch).toFixed(2)} `; pen=true;
  });
  svg.append(svgElement("path",{d:path,class:"chart-path"})); svg.setAttribute("aria-label",`${state.fullText?"全文":"当前句"}连续音高曲线，${notes.length} 个音符，${seconds(duration)}`);
  $("#selectedDuration").textContent = seconds(duration);
  $(".unvoiced-key").hidden=!state.reference; $("#unvoicedLabel").hidden=!state.reference;
  $("#curveSummary").textContent = state.reference ? `有声 ${Math.round((1-unvoicedDuration/duration)*100)}% · 无声 / 清音 ${unvoicedCount} 段 · 原始时间轴` : `${notes.length} 个音符 · 基准音符与连续音高分离`;
}
function showWarnings(element,warnings) { element.replaceChildren(); const list = [...new Set((warnings || []).filter(Boolean))]; element.hidden = !list.length; list.slice(0,8).forEach(warning => { const p=document.createElement("p"); p.textContent=warning; element.append(p); }); }
function referenceNoteErrors() {
  if (!state.reference) return [];
  return (state.result?.notes || []).flatMap((note,index,notes)=> {
    const badTime=!Number.isFinite(note.start)||!Number.isFinite(note.end)||note.start<0||note.end<=note.start||note.end>state.result.duration||(index>0&&note.start<notes[index-1].end-1e-7);
    const badKey=!Number.isInteger(note.key)||note.key<0||note.key>127;
    return badTime ? [{index,message:`第 ${index+1} ${languageConfig().unit}「${note.lyric}」的时间无效或与上一项重叠，请在保存 / 导出前修正。`}] : badKey ? [{index,message:`第 ${index+1} ${languageConfig().unit}「${note.lyric}」需使用 0–127 范围的整数 MIDI 音高。`}] : [];
  });
}
function renderWarnings() { showWarnings($("#warnings"),[...referenceNoteErrors().map(issue=>issue.message),...(state.document?.warnings || []),...(state.result?.warnings || [])]); }
function render() { renderNavigation(); renderEditor(); updateButtons(); }
async function generate() {
  if (state.reference) return;
  validateEditorInputs();
  const expectedLanguage = checkedLanguage(state.draft.language);
  checkpoint();
  const data = await api("/api/analyze",state.draft);
  const draft = compactDocument(data.document);
  if (draft.language !== expectedLanguage) throw new Error("生成结果语言与文稿不一致，当前文稿已保留。");
  validateResultLanguage(data.result,expectedLanguage);
  state.document = data.document; state.result = data.result; state.draft = draft;
  if (!state.draft.sections?.some(s => s.id === state.selected)) state.selected = state.draft.sections?.[0]?.id || null;
  state.stale = false; state.saved = false;
  if (!state.draft.sections?.length) state.fullText = true;
  checkpoint(); render(); setStatus(`语调已生成：${state.document.section_count || state.draft.sections.length} 句，${unitSummary(state.draft.text,state.document.character_count ?? state.result.notes.length)}，${seconds(state.result.duration)}。`);
  return data;
}
function validateEditorInputs() {
  const invalid = $$("#characterRows input").find(input => !input.validity.valid);
  if (invalid) { invalid.focus(); throw new Error(`${invalid.getAttribute("aria-label")}：${invalid.validationMessage || invalid.dataset?.validationError || "请检查数值范围和读音格式。"}`); }
}
async function ensureCurrent() {
  validateEditorInputs();
  if (!state.reference && state.stale) await generate();
  if (state.result) validateResultLanguage(state.result,state.draft.language);
  const issue = referenceNoteErrors()[0];
  if (issue) throw new Error(issue.message);
}
function newDocument(language = state.draft.language) {
  language = typeof language === "string" ? checkedLanguage(language) : checkedLanguage(state.draft.language);
  $("#confirmDialog").close(); clearTimeout(state.historyTimer);
  Object.assign(state,{draft:{title:"未命名文稿",text:"",language,settings:{...DEFAULT_SETTINGS}},document:null,result:null,originalReference:null,selected:null,fullText:true,reference:false,source:null,stale:true,saved:false,history:[],historyIndex:-1,audioRevision:null,folder:null});
  state.revision++;$("#previewAudio").pause();$("#previewAudio").removeAttribute("src"); $("#previewAudio").hidden=true; $("#audioStale").hidden=true;$("#outputFolderButton").hidden=true; checkpoint(); render(); setStatus(`新${LANGUAGES[language].name}文稿已准备好，可输入文字或填入示例。`); $("#textEditor").focus();
}
async function loadDocument(file) {
  const content = await file.text();
  if (file.name.toLowerCase().endsWith(".txt")) {
    state.draft = {title:file.name.replace(/\.txt$/i,""),text:content.replace(/^\uFEFF/,""),language:checkedLanguage(state.draft.language),settings:{...DEFAULT_SETTINGS}}; state.reference=false; state.source=null; state.result=null; state.document=null; state.fullText=true; state.selected=null; changed(true); render(); setStatus(`文本按当前${languageConfig().name}语言导入。点击生成语调，按句子开始编辑。`); return;
  }
  let doc; try { doc=JSON.parse(content.replace(/^\uFEFF/,"")); } catch (_) { throw new Error("无法读取 JSON，请选择工作台保存的文稿或参考结果。"); }
  const envelope = doc;
  if (doc.document) {
    if (doc.language && checkedLanguage(doc.language) !== checkedLanguage(doc.document.language)) throw new Error("工程封装语言与文稿语言不一致，当前文稿已保留。");
    doc=doc.document;
  }
  if (doc.format === "ace-tts-workbench" || (typeof doc.text === "string" && Array.isArray(doc.sections))) {
    const draft = compactDocument(doc);
    state.draft = draft; state.reference=false; state.source=null; state.document=null; state.result=null; state.fullText=false; state.selected=state.draft.sections?.[0]?.id || null; changed(true); await generate(); setStatus(`文稿已打开，${languageConfig().edit}调整与句子设置已恢复。`);
  } else if (Array.isArray(doc.result?.curve) || Array.isArray(doc.curve)) {
    const result=doc.result || doc; useReference({result,source:doc.source || {type:"saved"}},doc.title || file.name.replace(/\.json$/i,""),result.text || doc.text || "",envelope.language);
    setStatus("参考结果已打开。原曲线可以导出，原录音需重新选取。");
  } else { throw new Error("不是受支持的文稿。请选择本工具保存的 JSON，或先导入 TXT 文本。"); }
}
function useReference(data,title,text,expectedLanguage) {
  const language=validateResultLanguage(data.result,expectedLanguage);
  state.reference=true; state.result=data.result; state.originalReference=copyResult(data.result); state.document=null; state.source=data.source || null; state.fullText=true; state.selected=null;
  state.draft={title:title || "参考语调",text:text || data.result?.text || "",language,settings:{...state.draft.settings}};
  state.stale=false; state.saved=false; state.revision++; checkpoint(); render();
}
async function fileBase64(file) {
  if (file.size > 64*1024*1024) throw new Error("参考文件最大 64 MB，请先截取需要处理的片段。");
  return new Promise((resolve,reject) => { const reader=new FileReader(); reader.onload=() => resolve(String(reader.result).split(",")[1]); reader.onerror=() => reject(new Error(`无法读取文件：${file.name}`)); reader.readAsDataURL(file); });
}
async function upload(file,kind,language = $("#referenceLanguage").value) { return api("/api/upload",{name:file.name,data:await fileBase64(file),kind,language:checkedLanguage(language)}); }
async function importReference() {
  const audio=$("#referenceAudioFile").files[0] || recorder.file, alignment=$("#referenceAlignmentFile").files[0];
  const text=$("#referenceText").value.trim();
  const language=checkedLanguage($("#referenceLanguage").value),config=LANGUAGES[language];
  if (!audio && !alignment) throw new Error("请选择 WAV 录音或 VSQX 工程。");
  const isVsqx=alignment?.name.toLowerCase().endsWith(".vsqx");
  if (!audio && !isVsqx) throw new Error("TextGrid / CSV 需要与 WAV 录音一起导入。");
  if (audio && !text) throw new Error(`请输入录音对应的${config.name}文字，用来与音高对齐。`);
  let audioData=null,alignmentData=null;
  if (alignment) alignmentData=await upload(alignment,isVsqx?"vsqx":"alignment");
  if (audio && isVsqx && alignmentData.result) {
    validateResultLanguage(alignmentData.result,language);
    const csvValue=value=>`"${String(value).replace(/"/g,'""')}"`;
    const rows=["start,end,lyric",...alignmentData.result.notes.map(note=>`${note.start},${note.end},${csvValue(note.lyric)}`)].join("\n");
    alignmentData=await upload(new File([rows],`工程${config.edit}对齐.csv`,{type:"text/csv"}),"alignment");
  }
  if (!audio && isVsqx && alignmentData.result) {
    useReference({result:alignmentData.result,source:{type:"vsqx",name:alignment.name,language}},alignment.name.replace(/\.vsqx$/i,""),alignmentData.text || alignmentData.result.text,language);
  } else {
    audioData=await upload(audio,"audio");
    const fmin=Number($("#fmin").value),fmax=Number($("#fmax").value);
    if (!Number.isFinite(fmin) || !Number.isFinite(fmax) || fmin>=fmax) throw new Error("最低频率需要小于最高频率。");
    const data=await api("/api/reference",{text,language,title:state.draft.title,settings:state.draft.settings,audio_id:audioData.id,alignment_id:alignmentData?.id,fmin,fmax,alignment_mode:$("#automaticAlignment").checked ? "auto" : "equal"});
    data.source={...data.source,audio_id:audioData.id,audio_url:audioData.url,audio_name:audio.name};
    useReference(data,audio.name.replace(/\.[^.]+$/,""),text,language);
  }
  $("#referenceDialog").close(); setStatus(`参考语调已导入，${seconds(state.result.duration)}。可试听或导出到目标引擎。`);
}
function pcmWav(chunks,sampleCount,sampleRate) {
  const buffer=new ArrayBuffer(44+sampleCount*2),view=new DataView(buffer);
  const tag=(offset,value)=>[...value].forEach((char,index)=>view.setUint8(offset+index,char.charCodeAt(0)));
  tag(0,"RIFF");view.setUint32(4,36+sampleCount*2,true);tag(8,"WAVE");tag(12,"fmt ");view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,sampleRate,true);view.setUint32(28,sampleRate*2,true);view.setUint16(32,2,true);view.setUint16(34,16,true);tag(36,"data");view.setUint32(40,sampleCount*2,true);
  let offset=44,written=0;
  for (const chunk of chunks) for (const sample of chunk) { if (written>=sampleCount) break; const value=Math.max(-1,Math.min(1,sample));view.setInt16(offset,Math.round(value*(value<0?32768:32767)),true);offset+=2;written++; }
  return new Blob([buffer],{type:"audio/wav"});
}
async function startRecording() {
  if (recorder.active || recorder.pending || state.busy) return;
  if (!navigator.mediaDevices?.getUserMedia || !(window.AudioContext || window.webkitAudioContext)) { $("#referenceError").textContent="当前窗口无法访问麦克风，请用本机浏览器打开工作台，或上传 PCM WAV 录音。";$("#referenceError").hidden=false;return; }
  recorder.pending=true;const request=++recorder.request;updateButtons();$("#referenceError").hidden=true;$("#recordStatus").textContent="正在请求麦克风访问…";
  let stream=null;
  try {
    stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:false,noiseSuppression:false,autoGainControl:false}});
    if (request!==recorder.request || !$("#referenceDialog").open) {stream.getTracks().forEach(track=>track.stop());return;}
    const AudioContextClass=window.AudioContext || window.webkitAudioContext;const context=new AudioContextClass();await context.resume();
    const source=context.createMediaStreamSource(stream),processor=context.createScriptProcessor(4096,1,1),gain=context.createGain();gain.gain.value=0;
    Object.assign(recorder,{active:true,pending:false,stream,context,source,processor,gain,chunks:[],samples:0,started:Date.now()});
    processor.onaudioprocess=event => {
      if (!recorder.active) return;
      const remaining=Math.floor(context.sampleRate*180)-recorder.samples;
      const data=event.inputBuffer.getChannelData(0);const chunk=new Float32Array(data.subarray(0,Math.max(0,remaining)));
      if (chunk.length) {recorder.chunks.push(chunk);recorder.samples+=chunk.length;}
      if (remaining<=data.length) queueMicrotask(()=>stopRecording(true));
    };
    source.connect(processor);processor.connect(gain);gain.connect(context.destination);
    $("#referenceAudioFile").value="";$("#recordPlayback").hidden=true;$("#recordStop").hidden=false;$(".microphone-section").classList.add("recording");
    const tick=()=> {$("#recordStatus").textContent=`录音中 · ${Math.min(180,Math.floor((Date.now()-recorder.started)/1000))} / 180 秒`;if (Date.now()-recorder.started>=180000) stopRecording(true);};tick();recorder.timer=setInterval(tick,500);updateButtons();
  } catch (error) {
    stream?.getTracks().forEach(track=>track.stop());
    const denied=["NotAllowedError","PermissionDeniedError"].includes(error.name),missing=["NotFoundError","DevicesNotFoundError"].includes(error.name);
    const message=denied?"麦克风权限被拒绝。请在窗口或浏览器权限中允许麦克风，或上传录音文件。":missing?"没有检测到可用麦克风。请连接录音设备，或上传录音文件。":`无法开始录音：${error.message}`;
    $("#referenceError").textContent=message;$("#referenceError").hidden=false;$("#recordStatus").textContent="录音未开始。";
  } finally {recorder.pending=false;updateButtons();}
}
function stopRecording(limitReached=false) {
  recorder.request++;recorder.pending=false;
  if (!recorder.active) {updateButtons();return;}
  recorder.active=false;clearInterval(recorder.timer);recorder.timer=null;
  const context=recorder.context,sampleRate=context.sampleRate;
  recorder.processor.onaudioprocess=null;recorder.processor.disconnect();recorder.source.disconnect();recorder.gain.disconnect();recorder.stream.getTracks().forEach(track=>track.stop());context.close().catch(()=>{});
  $("#recordStop").hidden=true;$(".microphone-section").classList.remove("recording");
  if (recorder.samples<sampleRate*.1) {$("#recordStatus").textContent="录音太短，请至少录制 0.1 秒。";updateButtons();return;}
  const blob=pcmWav(recorder.chunks,recorder.samples,sampleRate);
  recorder.file=new File([blob],`麦克风示读_${new Date().toISOString().replace(/[:.]/g,"-")}.wav`,{type:"audio/wav"});
  if (recorder.url) URL.revokeObjectURL(recorder.url);recorder.url=URL.createObjectURL(blob);$("#recordPlayback").src=recorder.url;$("#recordPlayback").hidden=false;
  $("#recordStatus").textContent=`${limitReached?"已到录音上限，":""}录音已保留 · ${seconds(recorder.samples/sampleRate)}。`;
  recorder.chunks=[];updateButtons();
}
async function saveDocument() {
  await ensureCurrent();
  const payload=state.reference ? {result:state.result,title:state.draft.title,source:state.source,language:state.draft.language} : {document:state.document,title:state.draft.title,language:state.draft.language};
  const data=await api("/api/save-document",payload); state.folder=data.folder; state.saved=true; $("#saveState").textContent="已保存到本机"; $("#outputFolderButton").hidden=!state.folder;
  setStatus(`工作台已保存：${data.path}`); persist();
}
async function exportDocument() {
  await ensureCurrent();
  const target=$("#targetEngine").value;
  if (!Object.hasOwn(TARGET_HELP,target)) throw new Error("请选择一个目标引擎后导出工程。");
  const data=await api("/api/export",state.reference ? {result:state.result,target,title:state.draft.title,language:state.draft.language} : {document:state.document,target,language:state.draft.language});
  if (data.files?.length !== 1) throw new Error("本地服务应只返回一个引擎工程文件，请更新工作台后重试。");
  const file=data.files[0], extension={ace:".acep",synthv:".svp",vocaloid5:".vsqx",vocaloid6:".vsqx"}[target];
  if (typeof file.name !== "string" || !file.name.toLowerCase().endsWith(extension) || !file.url) throw new Error("本地服务没有返回所选引擎的工程与下载链接，请重试。");
  state.folder=data.folder; $("#outputFolderButton").hidden=!state.folder; $("#exportFolder").textContent=data.folder || "";
  const container=$("#exportFiles"); container.replaceChildren();
  const row=document.createElement("div"); row.className="export-file";
  const label=document.createElement("div"); label.className="export-file-label"; label.textContent=file.name; row.append(label);
  const link=document.createElement("a"); link.className="button outline"; link.href=file.url; link.download=file.name; link.textContent="下载工程"; row.append(link);
  container.append(row);
  showWarnings($("#exportWarnings"),data.warnings); $("#exportDialog").showModal(); setStatus(`已导出 ${file.name}，可下载或打开输出位置。`);
}
async function copySv2() {
  await ensureCurrent();
  const data=await api("/api/synthv-script",state.reference ? {result:state.result,title:state.draft.title,language:state.draft.language} : {document:state.document,language:state.draft.language});
  if (!data.data || typeof data.data !== "object" || Array.isArray(data.data)) throw new Error("本地服务没有返回有效的 SV2 脚本数据，请重试。");
  const content=JSON.stringify(data.data,null,2);$("#copyData").value=content;
  try {if(!navigator.clipboard?.writeText)throw new Error("clipboard unavailable");await navigator.clipboard.writeText(content);setStatus("SV2 数据已复制。在 Studio 2 Pro 运行「脚本 → VvTalk Studio → 导入剪贴板语调」。");}
  catch (_) {$("#copyHelp").textContent="当前窗口不允许自动写入剪贴板，可点击复制全部，或按 Ctrl+C。";$("#copyDialog").showModal();$("#copyData").focus();$("#copyData").select();setStatus("SV2 数据已生成，请在弹窗中复制后运行导入脚本。");}
}
async function copyFallback() {
  const field=$("#copyData");field.focus();field.select();
  let copied=false;try {if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(field.value);copied=true;}} catch (_) {}
  if (!copied) {try {copied=document.execCommand("copy");} catch (_) {}}
  $("#copyHelp").textContent=copied?"已复制，可以切换到 Synthesizer V 运行导入脚本。":"数据已全选，请按 Ctrl+C 复制。";
  if(copied)setStatus("SV2 数据已复制，可以运行 Synthesizer V 导入脚本。");
}
async function preview() {
  if (state.busy || state.previewBusy) return;
  state.previewBusy=true; updateButtons();
  try {
    if (!state.reference && state.stale) { await perform("正在更新语调…",generate); if (state.stale) return; }
    await ensureCurrent();
    const revision=state.revision;
    const scope=$("#previewScope").value;
    const payload=state.reference ? {result:state.result,title:state.draft.title,language:state.draft.language} : {document:state.document,language:state.draft.language,section_id:scope==="section" && !state.fullText ? state.selected : undefined};
    setStatus("正在调用 ACE Studio 合成试听…",false,true); $("#previewHelp").textContent="真实合成任务运行中，长文可能需要几分钟。";
    let job=await api("/api/preview",payload);
    if (job.id && !job.audio_url && !job.url) {
      const deadline=Date.now()+30*60*1000;
      while (!["succeeded","failed","cancelled","canceled","completed"].includes(job.status)) {
        if (Date.now()>deadline) throw new Error("试听等待超过 30 分钟，请在 ACE Studio 中检查合成任务。");
        await new Promise(resolve => setTimeout(resolve,1500)); job=await api(`/api/job?id=${encodeURIComponent(job.id)}`);
        $("#previewHelp").textContent=job.message || "ACE Studio 正在合成试听…";
      }
    }
    if (["failed","cancelled","canceled"].includes(job.status)) throw new Error(job.error || job.message || "ACE 合成失败，请检查当前工程和歌手设置。");
    const url=job.audio_url || job.url;
    if (!url) throw new Error("ACE 任务已返回，但没有生成可播放音频。");
    const player=$("#previewAudio"); player.src=url; player.hidden=false; state.audioRevision=revision;
    $("#audioStale").hidden=revision===state.revision; $("#previewHelp").textContent="ACE Studio 合成已完成，可播放检查。";
    const warnings=(job.warnings || []).join(" "); setStatus(warnings ? `试听已生成。${warnings}` : "ACE 试听已生成。点击播放器播放，修改文稿后请重新合成。");
  } catch (error) { $("#previewHelp").textContent=error.message; setStatus(error.message,true); }
  finally { state.previewBusy=false; updateButtons(); }
}
async function openFolder() { if (!state.folder) return; await perform("正在打开输出文件夹…",async () => { await api("/api/open-folder",{folder:state.folder}); setStatus(`已打开：${state.folder}`); }); }
async function undo(direction) {
  if (state.busy) return; checkpoint(); const next=state.historyIndex+direction;
  if (next<0 || next>=state.history.length) return;
  const view={selected:state.selected,fullText:state.fullText,reference:state.reference};
  state.historyIndex=next; const saved=state.history[next]; const snap={...saved,draft:clone(saved.draft),result:copyResult(saved.result)}; Object.assign(state,snap); if(state.reference===view.reference){state.selected=view.selected;state.fullText=view.fullText;} state.document=null; state.stale=!state.reference; state.saved=false; state.revision++; render(); persist();
  if (!state.reference && state.draft.text.trim()) {
    await perform(direction<0?"正在恢复上一步…":"正在恢复下一步…",async () => {
      const data=await api("/api/analyze",state.draft),draft=compactDocument(data.document); validateResultLanguage(data.result,state.draft.language); if(draft.language!==state.draft.language)throw new Error("恢复结果的语言与文稿不一致。"); state.document=data.document; state.result=data.result; state.draft=draft; if(!state.draft.sections?.some(section=>section.id===state.selected))state.selected=state.draft.sections?.[0]?.id || null; state.stale=false; render(); setStatus(direction<0?"已撤销修改。":"已重做修改。");
    });
  } else { state.result=state.reference?state.result:null; render(); setStatus(direction<0?"已撤销修改。":"已重做修改。"); }
}

$("#textEditor").addEventListener("input",event => {
  if (state.reference) return;
  const value=event.target.value;
  if (state.fullText || !sectionDraft()) { if (value!==state.draft.text) delete state.draft.sections; state.draft.text=value; }
  else { sectionDraft().text=value; state.draft.text=state.draft.sections.map(s=>s.text).join(""); }
  changed();
});
$("#textEditor").addEventListener("blur",() => renderNavigation());
$("#documentTitle").addEventListener("input",event => { state.draft.title=event.target.value; if (state.document) state.document.title=event.target.value; state.saved=false; $("#saveState").textContent="未保存的修改"; clearTimeout(state.historyTimer); state.historyTimer=setTimeout(checkpoint,600); });
$$("[data-setting]").forEach(input => { input.addEventListener("input",() => { state.draft.settings[input.dataset.setting]=input.value==="" ? null : Number(input.value); const range=$(`[data-range="${input.dataset.setting}"]`); if (range) range.value=input.value; changed(); }); input.addEventListener("change",checkpoint); });
$$("[data-range]").forEach(input => { input.addEventListener("input",() => { const field=$(`[data-setting="${input.dataset.range}"]`); field.value=input.value; state.draft.settings[input.dataset.range]=Number(input.value); changed(); }); input.addEventListener("change",checkpoint); });
$$("[data-local]").forEach(input => { input.addEventListener("input",() => { const section=sectionDraft(); if (!section) return; section.settings ||= {}; if (input.value==="") delete section.settings[input.dataset.local]; else section.settings[input.dataset.local]=Number(input.value); changed(); }); input.addEventListener("change",checkpoint); });
$("#analyzeButton").addEventListener("click",() => perform("正在生成语调…",async () => { await generate(); if (state.fullText && state.draft.sections?.length) { state.fullText=false; render(); } }));
$("#fullTextButton").addEventListener("click",() => {
  if (state.reference) { state.reference=false; state.result=null; state.document=null; state.source=null; state.fullText=true; changed(true); }
  else if (state.fullText && state.draft.sections?.length) state.fullText=false; else state.fullText=true;
  render();
});
$("#resetSettings").addEventListener("click",() => { state.draft.settings={...DEFAULT_SETTINGS}; changed(true); renderEditor(); setStatus("全局设置已恢复，重新生成后更新语调。"); });
$("#resetCharacters").addEventListener("click",() => { if (state.reference && state.originalReference) { state.result=copyResult(state.originalReference); changed(true); render(); setStatus("已恢复原导入音符与音高曲线。"); return; } const section=sectionDraft(); if (!section) return; section.characters.forEach(char => { char.pinyin_override=null; char.pronunciation_override=null; char.accent_override=null; char.stress_override=null; char.duration_override_ms=null; char.pause_override_ms=null; }); changed(true); renderCharacters(); setStatus(`本句${languageConfig().edit}调整已重置，重新生成后更新曲线。`); });
$("#targetEngine").addEventListener("change",event => { $("#targetDescription").textContent=TARGET_HELP[event.target.value]; });
$("#newButton").addEventListener("click",() => state.draft.text.trim()?$("#confirmDialog").showModal():newDocument());
$("#confirmNew").addEventListener("click",newDocument);
$("#language").addEventListener("change",event => {
  const language=checkedLanguage(event.target.value);
  if(state.reference){event.target.value=state.draft.language;return;}
  if(language===state.draft.language)return;
  if(state.draft.text.trim()) {
    state.pendingLanguage=language;event.target.value=state.draft.language;
    $("#languageDialogTitle").textContent=`新建${LANGUAGES[language].name}文稿`;
    $("#languageDialogHelp").textContent=`当前${languageConfig().name}文稿不会自动按${LANGUAGES[language].name}解释。确认将新建空文稿；需要保留当前内容，请先保存。`;
    $("#languageDialog").showModal();return;
  }
  state.draft.language=language;delete state.draft.sections;state.document=null;state.result=null;state.originalReference=null;state.source=null;state.selected=null;state.fullText=true;changed(true);render();
  setStatus(`已选择${LANGUAGES[language].name}，可输入文稿或填入示例。`);
});
$("#confirmLanguage").addEventListener("click",()=> { const language=state.pendingLanguage;$("#languageDialog").close();if(language)newDocument(language); });
$("#languageDialog").addEventListener("close",()=> {state.pendingLanguage=null;});
$("#sampleButton").addEventListener("click",()=> {if(state.reference||state.draft.text.trim())return;state.draft.text=languageConfig().sample;changed(true);render();$("#textEditor").focus();setStatus(`${languageConfig().name}示例已填入，点击生成语调。`);});
$("#openButton").addEventListener("click",() => $("#openFile").click());
$("#openFile").addEventListener("change",async event => { const file=event.target.files[0]; if (file) await perform("正在打开文稿…",() => loadDocument(file)); event.target.value=""; });
$("#saveButton").addEventListener("click",() => perform("正在保存文稿…",saveDocument));
$("#exportButton").addEventListener("click",() => perform("正在导出工程…",exportDocument));
$("#copySv2Button").addEventListener("click",() => perform("正在生成 SV2 脚本数据…",copySv2));$("#copyFallback").addEventListener("click",copyFallback);
$("#outputFolderButton").addEventListener("click",openFolder); $("#exportOpenFolder").addEventListener("click",openFolder);
$("#undoButton").addEventListener("click",() => undo(-1)); $("#redoButton").addEventListener("click",() => undo(1));
$("#previewButton").addEventListener("click",preview);
$("#referenceButton").addEventListener("click",() => { $("#referenceLanguage").value=state.draft.language;$("#referenceText").value=state.draft.text;renderAlignmentStatus(true); $("#referenceError").hidden=true; $("#referenceDialog").showModal(); });
$("#referenceLanguage").addEventListener("change",()=> {if($("#referenceLanguage").value!==state.draft.language && $("#referenceText").value===state.draft.text)$("#referenceText").value="";renderAlignmentStatus(true);});
$("#referenceForm").addEventListener("submit",async event => { event.preventDefault(); if (state.busy) return; $("#referenceError").hidden=true; await perform("正在分析参考声音…",async () => { try { await importReference(); } catch (error) { $("#referenceError").textContent=error.message; $("#referenceError").hidden=false; throw error; } }); });
$("#recordStart").addEventListener("click",startRecording);$("#recordStop").addEventListener("click",()=>stopRecording());
$("#referenceDialog").addEventListener("close",()=>stopRecording());
$("#referenceAudioFile").addEventListener("change",()=> {if ($("#referenceAudioFile").files.length) {recorder.file=null;if(recorder.url) URL.revokeObjectURL(recorder.url);recorder.url=null;$("#recordPlayback").hidden=true;$("#recordStatus").textContent="已选择录音文件，也可以重新录制示读。";}});
$("#automaticAlignment").addEventListener("change",()=> renderAlignmentStatus());
$("#referenceSourceAudio").addEventListener("error",()=> {$("#sourceAudioStale").hidden=false;$("#referenceSourceAudio").hidden=true;});
$("#installScript").addEventListener("click",() => perform("正在安装 Synthesizer V 脚本…",async () => { const data=await api("/api/install-script",{}); state.folder=data.folder || null; $("#outputFolderButton").hidden=!state.folder; setStatus(`脚本已安装：${data.path}。${data.message || "在 Synthesizer V 的「脚本」菜单中刷新后加载。"}`); }));
$$(".close-dialog").forEach(button => button.addEventListener("click",() => button.closest("dialog").close()));
$(".brand").addEventListener("click",event=>event.preventDefault());
document.addEventListener("keydown",event => {
  if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
  if (event.key.toLowerCase()==="s") { event.preventDefault(); if (!state.busy) perform("正在保存文稿…",saveDocument); }
  if (event.key.toLowerCase()==="z" && !["INPUT","TEXTAREA"].includes(document.activeElement?.tagName)) { event.preventDefault(); undo(event.shiftKey?1:-1); }
});
window.addEventListener("beforeunload",() => { clearTimeout(state.historyTimer);if(recorder.active)stopRecording();persist(); });

async function initialize() {
  let restored=false,restoreError=null;
  try { const raw=localStorage.getItem("vvtalk-studio-draft-v1"); if (raw) { const draft=JSON.parse(raw); if (draft.draft && typeof draft.draft.text==="string" && typeof draft.draft.title==="string") { const compact=compactDocument(draft.draft),reference=Boolean(draft.reference && draft.result?.curve); if(reference)validateResultLanguage(draft.result,compact.language); state.draft=compact; state.selected=draft.selected || null; state.fullText=draft.fullText!==false; state.reference=reference; state.result=state.reference?draft.result:null; state.originalReference=copyResult(state.result); state.source=draft.source ? {...draft.source,audio_url:null} : null; state.stale=!state.reference; restored=true; } } } catch (error) {restoreError=error.message;try {localStorage.setItem("vvtalk-studio-draft-recovery",localStorage.getItem("vvtalk-studio-draft-v1"));}catch(_){} }
  checkpoint(); render();
  try {
    state.info=await api("/api/info");
    const ace=state.info.ace || {}; $("#aceConnection").classList.toggle("connected",Boolean(ace.connected)); $("#aceConnection").replaceChildren(); const dot=document.createElement("span"); $("#aceConnection").append(dot,document.createTextNode(ace.connected?"已连接":"未连接"));
    $("#previewHelp").textContent=ace.connected ? "使用 ACE Studio 中的真实歌手合成。" : "启动 ACE Studio 并开启外部智能体访问后可试听。";
    $("#referenceLanguage").value=state.draft.language;renderAlignmentStatus(true);
    setStatus(restored ? "已恢复本机草稿。文稿修改会自动暂存，保存后可在其他电脑打开。" : "本地工作台已就绪。输入文稿，生成语调后导出到歌声合成引擎。");
    if (!state.reference && state.draft.text.trim()) await perform("正在恢复语调…",async () => { await generate(); if (!restored) { state.fullText=false; render(); } setStatus(restored?`本机草稿与${languageConfig().edit}调整已恢复。`:"示例已生成，点击左侧句子开始调整。"); });
    if(restoreError)setStatus(`旧草稿无法恢复：${restoreError} 原数据已保留在本机恢复备份。`,true);
    updateButtons();
  } catch (error) { setStatus(error.message,true); $("#aceConnection").textContent="服务未连接"; }
}
initialize();
