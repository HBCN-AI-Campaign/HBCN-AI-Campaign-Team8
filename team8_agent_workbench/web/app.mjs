import { loadDemoData, recomputeCase, applyCorrection, canPass, reportFor, createAssistantDemo, docOf, RULE_VERSION, RULES } from "./workflow.mjs";

export const escapeHTML = value => String(value ?? "").replace(/[&<>"']/g, ch => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[ch]));
export function renderTermParagraph(text, term, open = false) {
  return "<div class=\"document-paragraph\"><p>" + escapeHTML(text) + "</p>" +
    (open ? "<div class=\"term-explanation\"><strong>" + escapeHTML(term?.title || term?.term || "术语") +
      "</strong><p>" + escapeHTML(term?.definition || "") + "</p></div>" : "") + "</div>";
}

const data = loadDemoData();
const state = { caseId:null, result:null, history:[], assistant:null, assistantOpen:false, terms:false, status:"offline", models:[], variant:"", serverBase:"", controller:null };
const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];
const esc = value => escapeHTML(String(value ?? '').replace(/（模拟）|\(模拟\)|模拟|虚构/g, '').replace(/\s{2,}/g, ' ').trim());
const label = type => ({facility:"授信函",drawdown:"提款指令",trade_contract:"贸易合同",invoice:"发票",payment:"境外支付指令",support:"支持材料",history:"历史使用台账"})[type] || type;
const severityText = value => ({error:"需补正",pending:"待核验",warning:"待确认",ok:"一致"})[value] || "待确认";
const timeText = value => new Intl.DateTimeFormat("zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"}).format(new Date(value));
export const modelVariants = model => Array.isArray(model?.variants) ? model.variants : [];

function shell() {
  document.body.innerHTML = "<header class=\"topbar\"><a class=\"brand\" href=\"#\">HSBC <span>跨境业务审查</span></a><nav><button class=\"nav-button active\" data-page=\"cases\">申请审查</button><button class=\"nav-button\" data-page=\"knowledge\">规则与知识</button><button class=\"nav-button\" data-page=\"assistant\">AI 助手</button></nav><button class=\"connection\" id=\"connection\"><i></i>查看连接</button></header><main id=\"main\"></main><dialog id=\"pdf-dialog\"><header><strong id=\"pdf-title\"></strong><button data-close>关闭</button></header><iframe title=\"PDF 原件\" id=\"pdf-frame\"></iframe></dialog><div id=\"toast\" class=\"toast\" role=\"status\"></div>";
  $("#connection").onclick = inspectConnection;
  $$("[data-page]").forEach(button => button.onclick = () => navigate(button.dataset.page));
  renderCaseList();
}
function navigate(page) {
  $$(".nav-button").forEach(button => button.classList.toggle("active", button.dataset.page === page));
  if(page === "knowledge") return renderKnowledge();
  if(page === "assistant") { state.assistantOpen = true; return renderAssistantPage(); }
  state.caseId ? renderCase() : renderCaseList();
}
function toast(message) {
  const target=$("#toast"); target.textContent=message; target.classList.add("visible");
  setTimeout(()=>target.classList.remove("visible"),2800);
}
function renderCaseList() {
  const old=$("#case-search")?.value || "";
  const matches=data.cases.filter(c=>(c.id+" "+c.company+" "+c.submittedBy+" "+c.currency+" "+c.scenario+" "+c.identity).toLowerCase().includes(old.toLowerCase()));
  $("#main").innerHTML="<section class=\"page-head\"><div><p class=\"eyebrow\">跨境业务审查</p><h1>申请</h1><p class=\"subhead\">按编号、企业、提交人、币种或案件类型查找</p></div><span class=\"case-count\">"+matches.length+" 件申请</span></section><label class=\"search-field\"><span>搜索申请</span><input id=\"case-search\" type=\"search\" placeholder=\"申请编号、借款人、币种…\" value=\""+esc(old)+"\"></label><section class=\"case-list\">"+
    (matches.length?matches.map(c=>"<button class=\"case-row\" data-case=\""+esc(c.id)+"\"><span class=\"case-number\">"+esc(c.id)+"</span><strong>"+esc(c.company)+"</strong><span>"+esc(c.scenario)+"</span><span class=\"case-meta\">"+esc(c.currency)+" · "+new Intl.NumberFormat("zh-CN").format(c.loanAmount)+" · "+esc(c.identity)+"</span><span>›</span></button>").join(""):"<p class=\"empty-state\">没有找到匹配申请。</p>")+"</section>";
  $("#case-search").oninput=renderCaseList;
  $$("[data-case]").forEach(button=>button.onclick=()=>selectCase(button.dataset.case));
}
async function selectCase(id) {
  state.caseId=id; state.history=[]; state.assistantOpen=false; state.sessionId=null;
  state.result=await recomputeCase(currentCase()); state.history.push(reportFor(state.result)); state.assistant=createAssistantDemo(id); renderCase();
}
function currentCase(){return data.cases.find(c=>c.id===state.caseId);}
function countSeverity(severity){return state.result.findings.filter(f=>f.severity===severity).length;}
function renderCase() {
  if(!state.result)return renderCaseList();
  const c=currentCase(),r=state.result,blocked=r.findings.some(f=>["error","pending"].includes(f.severity)),critical=r.findings.filter(f=>f.severity!=="ok").slice(0,3),company=String(c.company).replace(/[（(]模拟[）)]/g,"");
  const docs=c.documents.map(doc=>"<details class=\"document-entry\"><summary><span>"+esc(label(doc.type))+"</span><strong>"+esc(doc.name)+"</strong><span>"+doc.pages+" 页</span></summary><div class=\"document-detail\">"+(doc.assetPath?"<button class=\"text-button\" data-pdf=\""+esc(doc.id)+"\">打开 PDF 原件</button> <a href=\""+(window.__TEAM8_ASSETS__?.[doc.assetPath]||("/data/"+esc(doc.assetPath)))+"\" download=\""+esc(doc.name)+"\">下载原件</a>":"")+
    (doc.pageTexts||[]).map(page=>renderPage(page)).join("")+"</div></details>").join("");
  const byStage=["materials","facility","payment","cross_border","history","applicability"];
  const stages=byStage.map(stage=>renderStage(stage,r)).join("");
  $("#main").innerHTML="<button class=\"back-link\" id=\"back\">← 返回申请</button><section class=\"page-head case-title\"><div><p class=\"eyebrow\">"+esc(c.id)+" · "+esc(c.currency)+" · 跨境支付</p><h1>"+esc(company)+"</h1><p class=\"subhead\">"+esc(c.scenario)+" · "+new Date(c.submittedAt).toLocaleDateString("zh-CN")+"</p></div><label class=\"version-select\">报告版本<select id=\"versions\">"+state.history.map((item,i)=>"<option value=\""+i+"\" "+(i===state.history.length-1?"selected":"")+">v"+item.version+" · "+(item.status==="reviewed"?"已复核":"草稿")+"</option>").join("")+"</select></label></section>"+
    "<section class=\"conclusion "+(blocked?"critical":"calm")+"\"><p class=\"eyebrow\">本次结论 · v"+r.run.version+"</p><h2>"+(blocked?"需补正":countSeverity("warning")?"需人工核实":"等待人工确认")+"</h2><p>"+(critical.length?critical.map(f=>esc(f.title)).join(" · "):"核心字段比对一致，仍需人工确认。")+"</p><div class=\"summary-stats\"><span>"+countSeverity("error")+" 项差异</span><span>"+countSeverity("pending")+" 项缺证</span><span>"+countSeverity("warning")+" 项待确认</span><span>"+RULE_VERSION+"</span></div></section>"+
    "<section class=\"flow-index\">"+byStage.map((stage,i)=>"<div><span class=\"flow-mark\"></span>"+["材料读取","授信与提款","支付与贸易","跨币种金额","历史使用","规则适用"][i]+"<small>"+(r.findings.some(f=>f.stage===stage&&f.severity!=="ok")?"需查看":"已完成")+"</small></div>").join("")+"</section>"+
    "<section class=\"section-block\"><div class=\"section-heading\"><div><p class=\"eyebrow\">案件材料</p><h2>证据与原文</h2></div><button id=\"terms-toggle\" class=\"quiet-button\">段落解释 "+(state.terms?"开":"关")+"</button></div><div class=\"document-list\">"+docs+"</div></section>"+
    "<section class=\"section-block agent-flow\"><div class=\"section-heading\"><div><p class=\"eyebrow\">核心业务 Agent</p><h2>核对任务流</h2></div><span class=\"run-meta\">"+esc(r.run.runId)+" · "+timeText(r.run.startedAt)+"</span></div>"+stages+"</section>"+
    "<section class=\"section-block human-gate\"><div class=\"section-heading\"><div><p class=\"eyebrow\">人工复核</p><h2>记录处理意见</h2></div><span>"+(canPass(r)?"可提交":"仍有项目待处理")+"</span></div><div class=\"gate-grid\"><label>复核人<input id=\"reviewer\" maxlength=\"80\" value=\""+esc(r.review.reviewer)+"\" placeholder=\"姓名\"></label><label>处理意见<select id=\"decision\"><option value=\"pending\">继续核实</option><option value=\"pass\">可继续</option><option value=\"return\">退回补正</option></select></label></div><label class=\"review-note\">说明<textarea id=\"review-note\" maxlength=\"500\" rows=\"3\" placeholder=\"核对依据或退回原因\">"+esc(r.review.note)+"</textarea></label><div class=\"gate-actions\"><button id=\"save-review\" class=\"primary-button\">保存并生成报告</button><button id=\"download\" class=\"quiet-button\">下载 JSON</button></div><p class=\"gate-hint\">"+(blocked?"差异或待解析证据未处理，不能记录为通过。":"自动比对仅检查材料字段，提交前仍需审核人员确认。")+"</p></section>"+
    "<section class=\"section-block report-section\"><div class=\"section-heading\"><div><p class=\"eyebrow\">审查记录</p><h2>短报告</h2></div><span id=\"report-version\">v"+r.run.version+" · 草稿</span></div><div id=\"report-preview\">"+renderReport(reportFor(r))+"</div><details class=\"audit-steps\"><summary>可审计步骤 · "+r.run.steps.length+"</summary>"+r.run.steps.map(step=>"<div class=\"audit-step\"><span>✓</span><div><strong>"+esc(step.label)+"</strong><p>"+esc(step.inputSummary)+" · "+esc(step.outputSummary)+"</p><small>"+esc(step.runId)+" · "+(step.status==="needs_human"?"等待人工":"完成")+"</small></div></div>").join("")+"</details></section>"+
    "<button id=\"assistant-open\" class=\"assistant-open\"><span>✳</span><span><strong>AI 助手</strong><small>独立问答 · 当前案件只读上下文</small></span><span>"+(state.assistantOpen?"收起":"打开")+"</span></button>"+(state.assistantOpen?assistantHTML():"");
  $("#back").onclick=()=>{state.caseId=null;state.result=null;state.history=[];state.assistantOpen=false;renderCaseList();};
  $("#versions").onchange=e=>showVersion(Number(e.target.value));
  $("#terms-toggle").onclick=()=>{state.terms=!state.terms;renderCase();};
  $("#save-review").onclick=saveReview; $("#download").onclick=downloadReport;
  $("#assistant-open").onclick=()=>{state.assistantOpen=!state.assistantOpen;renderCase();};
  $$("[data-pdf]").forEach(b=>b.onclick=()=>openPdf(b.dataset.pdf));
  $$("[data-correct]").forEach(b=>b.onclick=()=>{const form=$("#correction-"+CSS.escape(b.dataset.correct));form.hidden=!form.hidden;});
  $$("[data-correction-form]").forEach(form=>form.onsubmit=submitCorrection);
  $$("[data-confirm-finding]").forEach(form=>form.onsubmit=confirmFinding);
  if(state.assistantOpen)wireAssistant();
}
function renderPage(page){
  const terms=data.terms||[],paragraphs=page.text.split(/\n\s*\n|(?<=。)\n/).map(x=>x.trim()).filter(Boolean);
  const rows=paragraphs.length>1?paragraphs:page.text.split("\n").filter(Boolean);
  return "<article class=\"evidence-page\"><h4>"+esc(page.title)+" <span>第 "+page.page+" 页</span></h4>"+rows.map(text=>{const term=terms.find(item=>text.includes(item.term)||item.aliases?.some(a=>text.includes(a)));return renderTermParagraph(text,term,state.terms&&!!term);}).join("")+"</article>";
}
function renderStage(stage,result){
  const list=result.findings.filter(f=>f.stage===stage),urgent=list.some(f=>["error","pending"].includes(f.severity));
  const name=({materials:"材料与依据",facility:"授信与提款",payment:"支付与贸易",cross_border:"跨币种与金额",history:"发票历史使用",applicability:"规则适用性"})[stage];
  const expanded=urgent||document.documentElement.dataset.variant==="e";
  return "<details class=\"stage-row "+(urgent?"stage-urgent":"")+"\" "+(expanded?"open":"")+"><summary><span class=\"stage-status\"></span><strong>"+name+"</strong><span>"+(list.some(f=>f.severity!=="ok")?list.filter(f=>f.severity!=="ok").length+" 项需查看":"已完成")+"</span></summary><div class=\"stage-findings\">"+list.map(renderFinding).join("")+
    result.run.steps.filter(s=>stage==="facility"?s.toolName==="compare_facility_drawdown":stage==="payment"?s.toolName==="match_payment_trade":stage==="cross_border"?s.toolName==="check_cross_border":stage==="history"?s.toolName==="check_history":stage==="materials"?["load_case","extract_fields","retrieve_evidence"].includes(s.toolName):s.toolName==="load_rules").map(s=>"<div class=\"tool-step\"><span>✓</span><div><strong>"+esc(s.label)+"</strong><small>"+esc(s.outputSummary)+"</small><code>"+esc(s.runId)+"</code></div></div>").join("")+"</div></details>";
}
function renderFinding(f){
  const refs=(f.sources||[]).map(ref=>{const doc=currentCase().documents.find(d=>d.id===ref.documentId);return "<blockquote>"+esc(ref.quote)+"<cite>"+esc(doc?.name||ref.documentId)+" · 第 "+ref.page+" 页</cite></blockquote>";}).join("");
  const edits=(f.fields||[]).map(field=>"<label>"+esc(field.label)+"<input data-field=\""+esc(field.field)+"\" data-type=\""+esc(field.type)+"\" type=\""+esc(field.inputType)+"\" value=\""+esc(docOf(state.result.caseSnapshot,field.type)?.fields?.[field.field]??"")+"\" required></label>").join("");
  const terms=(data.terms||[]).find(term=>f.reason.includes(term.term));
  const confirm=f.severity==="warning"&&f.reviewState!=="confirmed"?"<form class=\"finding-confirm\" data-confirm-finding=\""+esc(f.id)+"\"><label>核实说明<textarea name=\"reviewNote\" maxlength=\"400\" rows=\"2\" required placeholder=\"记录已查看的原文或确认依据\"></textarea></label><button class=\"quiet-button\">记录本项已核实</button></form>":"";
  return "<article class=\"finding finding-"+esc(f.severity)+"\"><div class=\"finding-head\"><span>"+severityText(f.severity)+"</span><strong>"+esc(f.title)+"</strong></div><div class=\"finding-values\"><div><small>材料内容</small><p>"+esc(f.actual)+"</p></div><div><small>核对条件</small><p>"+esc(f.expected)+"</p></div></div><p class=\"finding-reason\">"+esc(f.reason)+"</p><details class=\"evidence-disclosure\"><summary>规则与原文 · "+(f.rows||[]).map(n=>"第 "+n+" 行").join("、")+"</summary><p>贷款文件比对要求.xlsx · Sheet1 · "+RULE_VERSION+"</p>"+refs+"</details>"+
    (state.terms&&terms?"<div class=\"term-explanation\"><strong>"+esc(terms.title)+"</strong><p>"+esc(terms.definition)+"</p></div>":"")+confirm+
    (["error","pending","warning"].includes(f.severity)?"<button class=\"text-button\" data-correct=\""+esc(f.id)+"\">"+(f.fields?.length?"纠正字段或补充说明":"补充说明")+" · 重新核对</button><div class=\"correction-form\" id=\"correction-"+esc(f.id)+"\" hidden><form data-correction-form=\""+esc(f.id)+"\"><div class=\"correction-fields\">"+edits+"</div><label>补充说明<textarea name=\"explanation\" maxlength=\"600\" rows=\"2\" placeholder=\"记录原页信息或待核实说明\" "+(f.fields?.length?"":"required")+"\"></textarea></label><label class=\"file-drop\">添加证据文件<input name=\"evidence\" type=\"file\" multiple accept=\".txt,.md,.csv,.json,.pdf\"></label><button class=\"primary-button\">提交并重新核对</button></form></div>":"")+"</article>";
}
function confirmFinding(event){
  event.preventDefault();const form=event.currentTarget,id=form.dataset.confirmFinding,finding=state.result.findings.find(item=>item.id===id),note=form.elements.reviewNote.value.trim();
  if(!note)return toast("请填写本项核实说明");
  finding.reviewState="confirmed";finding.reviewNote=note;
  const report=reportFor(state.result);state.history[state.history.length-1]=report;toast("已记录本项人工核实");renderCase();
}
async function submitCorrection(event){
  event.preventDefault();const form=event.currentTarget,findingId=form.dataset.correctionForm,spec=form.querySelector("[data-field]"),files=[...form.querySelector("[name=evidence]").files];
  try{
    if(files.length>5)throw new Error("最多添加 5 个文件");
    let total=0,loaded=[];
    for(const file of files){total+=file.size;if(file.size>65536&&/\.(txt|md|csv|json)$/i.test(file.name))throw new Error("单个文本材料最大 64 KiB");if(/\.(txt|md|csv|json)$/i.test(file.name)){const ext=file.name.split(".").at(-1).toLowerCase(),types={txt:"text/plain",md:"text/markdown",csv:"text/csv",json:"application/json"};loaded.push({name:file.name,type:types[ext],text:await file.text(),size:file.size,status:"readable"});}else if(/\.pdf$/i.test(file.name)||file.type==="application/pdf"){if(file.size>5*1024*1024)throw new Error("PDF 文件最大 5 MiB");loaded.push({name:file.name,type:"application/pdf",size:file.size,status:"pending",pending:true});}else throw new Error("当前支持 txt、md、csv、json、pdf");}
    if(new TextEncoder().encode(loaded.map(file=>file.text||"").join("\n")).length>204800)throw new Error("文本附件总大小最大 200 KiB");
    const attachment=loaded.length?{name:loaded.map(x=>x.name).join("、"),status:loaded.every(x=>x.status==="readable")?"readable":"pending",text:loaded.map(x=>x.text||"").join("\n\n"),files:loaded}:undefined;
    const value=spec?.value;
    state.result=await applyCorrection(currentCase(),state.result,{findingId,field:spec?.dataset.field,value,documentType:spec?.dataset.type,explanation:form.elements.explanation.value,attachment});
    state.history.push(reportFor(state.result));toast("已生成 v"+state.result.run.version+" · "+(state.result.run.rerunScope==="local"?"按依赖范围核对":"全量重新核对"));renderCase();
  }catch(error){toast(error.message);}
}
function saveReview(){
  const r=state.result;r.review={reviewer:$("#reviewer").value.trim(),decision:$("#decision").value,note:$("#review-note").value.trim()};
  if(!r.review.reviewer||!r.review.note)return toast("请填写复核人和处理说明");
  if(r.review.decision==="pass"){
    if(r.findings.some(f=>f.severity==="warning"&&f.reviewState!=="confirmed"))return toast("请逐项记录待确认项目");
    if(!canPass(r))return toast("差异或待解析材料未处理，不能记录为可继续");
    r.humanConfirmed=true;
  }
  if(r.review.decision==="return")r.humanConfirmed=true;
  const report=reportFor(r);state.history[state.history.length-1]=report;toast("已保存 v"+report.version+" "+(report.status==="reviewed"?"人工复核记录":"草稿"));renderCase();
}
function renderReport(report){
  return "<div class=\"report-top\"><span>"+esc(report.status==="reviewed"?"人工复核":"草稿")+" · v"+report.version+"</span><strong>"+esc(report.conclusion)+"</strong><p>"+esc(report.caseId)+" · "+esc(report.company)+" · "+esc(report.currency)+" "+new Intl.NumberFormat("zh-CN").format(report.amount||0)+"</p></div><div class=\"report-reasons\"><strong>关键原因</strong>"+(report.reasons.length?report.reasons.map(x=>"<p>"+esc(x)+"</p>").join(""):"<p>暂无需突出显示的差异。</p>")+"</div><p class=\"report-next\"><strong>下一步</strong> "+esc(report.nextAction)+"</p><details class=\"report-detail\"><summary>来源及人工意见</summary><p>复核人："+esc(report.review?.reviewer||"未填写")+" · "+esc(report.review?.decision||"继续核实")+"</p><p>"+esc(report.review?.note||"尚无人工记录")+"</p>"+report.findings.map(f=>"<p>"+esc(f.title)+" · "+severityText(f.severity)+" · "+esc(f.sources.map(s=>s.documentId+" 第"+s.page+"页").join("；"))+"</p>").join("")+"</details>";
}
function showVersion(index){const report=state.history[index];if(!report)return;$("#report-preview").innerHTML=renderReport(report);$("#report-version").textContent="v"+report.version+" · "+(report.status==="reviewed"?"已复核":"草稿");}
function downloadReport(){const report=reportFor(state.result),url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:"application/json"})),a=document.createElement("a");a.href=url;a.download=report.caseId+"-v"+report.version+".json";a.click();URL.revokeObjectURL(url);}
function openPdf(id){const doc=currentCase().documents.find(d=>d.id===id);if(!doc)return;$("#pdf-title").textContent=doc.name;$("#pdf-frame").src=window.__TEAM8_ASSETS__?.[doc.assetPath]||("/data/"+doc.assetPath);$("#pdf-dialog").showModal();$("#pdf-dialog [data-close]").onclick=()=>$("#pdf-dialog").close();}
function assistantHTML(){
  return "<section class=\"assistant-module\" id=\"assistant-module\"><div class=\"assistant-header\"><div><p class=\"eyebrow\">独立会话 · "+esc(state.caseId||"全站授权范围")+"</p><h2>AI 助手</h2></div><span class=\"local-badge\"><i></i>本地演示</span></div><p class=\"assistant-boundary\">可读取当前授权案件的材料、核对结果和报告版本。问答只读，不会修改差异或提交人工意见。</p><div class=\"assistant-settings\"><label>模型<select id=\"model-picker\"><option value=\"\">本地规则式演示</option></select></label><label>推理强度<select id=\"variant-picker\"><option value=\"demo-brief\">简要回复</option><option value=\"demo-standard\" selected>标准回复</option><option value=\"demo-detail\">展开说明</option></select></label><button id=\"load-models\" class=\"quiet-button\">刷新模型</button></div><div class=\"assistant-timeline\" id=\"assistant-timeline\" aria-live=\"polite\"><p class=\"timeline-note\">按时间显示用户消息、可审计步骤和助手回复，不显示私有思维链。</p></div><form id=\"assistant-form\" class=\"assistant-form\"><label class=\"composer-label\" for=\"assistant-message\">发送消息</label><textarea id=\"assistant-message\" rows=\"3\" maxlength=\"5000\" placeholder=\"询问本案字段、证据或历史版本\"></textarea><div class=\"composer-actions\"><label class=\"attach-button\">添加文件<input type=\"file\" id=\"assistant-files\" multiple accept=\".txt,.md,.csv,.json,.pdf\"></label><span id=\"assistant-file-state\">可上传文本或 PDF</span><button type=\"button\" id=\"assistant-stop\" class=\"quiet-button\" disabled>停止</button><button type=\"submit\" class=\"primary-button\">发送</button></div></form></section>";
}
function renderAssistantPage(){
  $("#main").innerHTML="<button class=\"back-link\" data-return>← 返回申请</button>"+assistantHTML();
  $("[data-return]").onclick=()=>navigate("cases");
  wireAssistant();
}
function assistantContext(){
  const result=state.result;
  return {caseId:state.caseId,version:result?.run.version||null,case:result?.caseSnapshot||null,currentFindings:result?.findings||[],findings:result?.findings||[],currentRun:result?.run||null,run:result?.run||null,runHistory:state.history,reports:state.history,report:state.history.at(-1)||null,corrections:result?.corrections||[],knowledge:data.knowledge.filter(item=>!item.applicableCaseIds||!state.caseId||item.applicableCaseIds.includes(state.caseId)),pages:currentCase()?.documents.flatMap(doc=>doc.pageTexts||[])||[],terms:data.terms,ruleVersion:RULE_VERSION};
}
function wireAssistant(){
  const form=$("#assistant-form");if(!form)return;
  form.onsubmit=sendAssistant;
  $("#assistant-stop").onclick=stopAssistant;
  $("#assistant-files").onchange=()=>$("#assistant-file-state").textContent=[...$("#assistant-files").files].map(f=>f.name).join("、")||"仅文本材料可直接读取";
  $("#load-models").onclick=loadModels;
  $("#model-picker").onchange=syncVariants;
  loadModels();
  $("#assistant-message").onkeydown=event=>{if(event.key==="Enter"&&!event.shiftKey){event.preventDefault();form.requestSubmit();}};
}
async function loadModels(){
  const picker=$("#model-picker"),badge=$(".local-badge");if(!picker)return;
  try{
    const response=await fetch("/api/models",{headers:{"Accept":"application/json"}});
    if(!response.ok)throw new Error("gateway unavailable");
    const payload=await response.json(),models=Array.isArray(payload)?payload:(payload.models||payload.data||[]);
    if(!models.length)throw new Error("no configured models");
    state.models=models;
    picker.innerHTML="<option value=\"\">选择服务端允许的模型</option>"+models.map(model=>{const providerID=model.providerID||model.providerId||model.provider?.id,modelID=model.modelID||model.modelId||model.id;return "<option value=\""+esc(JSON.stringify({providerID,modelID}))+"\">"+esc(model.name||modelID)+"</option>";}).join("");
    if(models.length===1)picker.selectedIndex=1;
    state.status="connected";badge.innerHTML="<i></i>服务端已连接";syncVariants();
  }catch{state.models=[];state.status="offline";picker.innerHTML="<option value=\"\">本地规则式演示</option>";if(badge)badge.innerHTML="<i></i>本地演示";syncVariants();}
}
function syncVariants(){
  const selected=$("#model-picker")?.value||"",selector=$("#variant-picker");if(!selector)return;
  if(!selected){selector.innerHTML="<option value=\"demo-brief\">简要回复</option><option value=\"demo-standard\" selected>标准回复</option><option value=\"demo-detail\">展开说明</option>";selector.disabled=false;return;}
  const choice=JSON.parse(selected),model=state.models.find(item=>(item.providerID||item.providerId||item.provider?.id)===choice.providerID&&(item.modelID||item.modelId||item.id)===choice.modelID),variants=modelVariants(model);
  const labels={minimal:"最简",low:"较少",medium:"标准",high:"较多",xhigh:"最高"};
  selector.innerHTML=variants.length?variants.map((variant,index)=>"<option value=\""+esc(variant)+"\" "+(index===0?"selected":"")+">"+esc(labels[variant]||variant)+"</option>").join(""):"<option value=\"\">模型默认</option>";
  selector.disabled=variants.length===0;
}
function addTimeline(kind,title,body,meta=""){
  const timeline=$("#assistant-timeline");if(!timeline)return;
  const item=document.createElement("article");item.className="timeline-item timeline-"+kind;
  const heading=document.createElement("strong");heading.textContent=title;item.append(heading);
  if(body){const paragraph=document.createElement("p");paragraph.textContent=body;item.append(paragraph);}
  if(meta){const small=document.createElement("small");small.textContent=meta;item.append(small);}
  timeline.append(item);item.scrollIntoView({block:"nearest"});
}
async function fileAttachments(files){
  const picked=[...files];if(picked.length>5)throw new Error("最多上传 5 个文件");
  let textTotal=0;const output=[];
  for(const file of picked){
    if(["text/plain","text/markdown","text/csv","application/json"].includes(file.type)||/\.(txt|md|csv|json)$/i.test(file.name)){
      if(file.size>65536)throw new Error("单个文本文件最大 64 KiB");
      const extension=file.name.split(".").at(-1).toLowerCase();
      const type=file.type||({md:"text/markdown",csv:"text/csv",json:"application/json"}[extension]||"text/plain");
      const text=await file.text();textTotal+=new TextEncoder().encode(text).length;
      output.push({name:file.name,type,size:file.size,text});
    }else if(file.type==="application/pdf"||/\.pdf$/i.test(file.name)){
      if(file.size>5*1024*1024)throw new Error("PDF 文件最大 5 MiB");
      output.push({name:file.name,type:"application/pdf",size:file.size,pending:true});
    }else throw new Error("当前支持 txt、md、csv、json、pdf");
  }
  if(textTotal>204800)throw new Error("文本附件总大小最大 200 KiB");
  return output;
}
async function sendAssistant(event){
  event.preventDefault();const input=$("#assistant-message"),message=input.value.trim();if(!message)return toast("先输入问题");
  const submit=$('#assistant-form button[type="submit"]'),files=$('#assistant-files').files;
  try{
    const attachments=await fileAttachments(files);addTimeline("user","你",message,attachments.map(f=>f.name).join("、"));
    input.value="";state.controller=new AbortController();submit.disabled=true;$("#assistant-stop").disabled=false;
    const selected=$("#model-picker").value;
    if(!selected||state.status!=="connected"){
      await new Promise(resolve=>{const timer=setTimeout(resolve,220);state.controller.signal.addEventListener("abort",()=>{clearTimeout(timer);resolve();},{once:true});});
      if(state.controller.signal.aborted)return;
      addTimeline("assistant","AI 助手",state.assistant.reply(message,{...assistantContext(),documents:currentCase()?.documents}),"本地规则式演示 · 业务状态保持不变");
    }else{
      let sessionId=state.sessionId;
      if(!sessionId){const created=await fetch("/api/assistant/session",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({caseId:state.caseId})});if(!created.ok)throw new Error("无法创建助手会话");sessionId=(await created.json()).sessionId;state.sessionId=sessionId;}
      const choice=JSON.parse(selected),payload={sessionId,caseId:state.caseId,message,model:choice,variant:$("#variant-picker").value,context:assistantContext(),attachments};
      const response=await fetch("/api/assistant/message",{method:"POST",headers:{"Content-Type":"application/json","Accept":"text/event-stream"},body:JSON.stringify(payload),signal:state.controller.signal});
      if(!response.ok||!response.body)throw new Error("助手服务暂不可用");
      await consumeSSE(response.body);
    }
  }catch(error){if(error.name!=="AbortError")addTimeline("error","无法完成请求",error.message,"审核状态未更改");}
  finally{state.controller=null;if($("#assistant-form"))submit.disabled=false;if($("#assistant-stop"))$("#assistant-stop").disabled=true;}
}
async function consumeSSE(stream){
  const reader=stream.getReader(),decoder=new TextDecoder();let buffer="",answer="",steps=0;
  while(true){
    const {value,done}=await reader.read();buffer+=decoder.decode(value||new Uint8Array(),{stream:!done});
    const events=buffer.split(/\r?\n\r?\n/);buffer=events.pop()||"";
    for(const eventText of events){
      const line=eventText.split(/\r?\n/).find(row=>row.startsWith("data:"));if(!line)continue;
      let event;try{event=JSON.parse(line.slice(5).trim());}catch{continue;}
      if(event.type==="step"){steps++;addTimeline("step",event.label||event.toolName||"工作步骤",event.outputSummary||event.inputSummary||"",event.runId||"可审计工具事件");}
      else if(event.type==="text"){answer+=event.text||event.delta||"";}
      else if(event.type==="error")addTimeline("error","助手服务报错",event.message||"请求未完成","业务状态未更改");
      else if(event.type==="done"&&answer)addTimeline("assistant","AI 助手",answer,steps+" 个可审计步骤");
    }
    if(done)break;
  }
  if(buffer.startsWith("data:")){try{const event=JSON.parse(buffer.slice(5).trim());if(event.type==="text")answer+=event.text||"";}catch{}}
  if(answer&&!steps)addTimeline("assistant","AI 助手",answer,"服务端回复 · 只读上下文");
}
async function stopAssistant(){
  if(state.controller){state.controller.abort();state.controller=null;}
  if(state.sessionId)try{await fetch("/api/assistant/abort",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({sessionId:state.sessionId})});}catch{}
  toast("已停止本次助手回复");
}
function renderKnowledge(){
  const items=data.knowledge||[];
  $("#main").innerHTML="<button class=\"back-link\" data-return>← 返回申请</button><section class=\"page-head\"><div><p class=\"eyebrow\">全站核对依据</p><h1>规则与知识</h1><p class=\"subhead\">来源、适用范围及复核状态</p></div></section><section class=\"knowledge-list\">"+items.map(item=>"<details class=\"knowledge-item\"><summary><span>"+esc(item.category)+"</span><strong>"+esc(item.title)+"</strong><span>"+esc(item.article)+"</span></summary><p>"+esc(item.summary)+"</p><p>"+esc(item.authority)+" · "+esc(item.status)+"</p><small>相关度 "+Math.round(item.relevance*100)+"% · 仅表示演示关联程度</small></details>").join("")+"</section><section class=\"section-block\"><h2>当前核对清单</h2><p>每条规则保留原表 Sheet1 行号与版本。法域及产品适用性需审核人员确认。</p><div class=\"rule-table\">"+RULES.map(item=>"<div><strong>"+item.row+" · "+esc(item.fieldA)+"</strong><span>"+esc(item.explain)+"</span></div>").join("")+"</div></section>";
  $("[data-return]").onclick=()=>navigate("cases");
}
async function inspectConnection(){
  try{
    const response=await fetch("/api/status",{headers:{"Accept":"application/json"}});
    if(!response.ok)throw new Error();
    const status=await response.json();state.status="connected";toast(status.connected||status.opencode?.connected?"已连接助手服务":"网关在线，模型状态待确认");
  }catch{state.status="offline";toast("当前使用本地演示 · 没有调用真实模型");}
}
if(typeof document!=="undefined")shell();
