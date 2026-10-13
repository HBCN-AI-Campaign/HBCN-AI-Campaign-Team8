import ruleEngine from 'json-rules-engine';
import Decimal from 'decimal.js';
import { addMonths, format, isAfter, isBefore, isValid, parseISO } from 'date-fns';
import demoData from '../data/data.json' with { type: 'json' };
const { Engine } = ruleEngine;
export const RULE_VERSION = 'excel-20261013-v1';
export const clone = value => structuredClone(value);
export const loadDemoData = () => clone(demoData);
export const docOf = (source, type) => source.documents.find(doc => doc.type === type);
export const money = (value, currency = 'CNY') => `${currency} ${new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value || 0))}`;
export const minor = value => {
  const d = new Decimal(value ?? 0);
  if (!d.isFinite() || d.isNegative() || !d.times(100).isInteger() || !Number.isSafeInteger(d.times(100).toNumber())) throw new Error('金额须为非负数，最多两位小数且在可核对范围内');
  return d.times(100).toNumber();
};
const date = value => { const d = parseISO(value || ''); return isValid(d) ? d : null; };
const agreed = text => /agreed by|贷款人同意|由贷款人和借款人/i.test(String(text));
const sourceRef = (source, type, page = 1) => {
  const d = docOf(source, type);
  return { documentId:d?.id||'', page, quote:d?.pageTexts?.find(p=>p.page===page)?.text?.split('\n').filter(Boolean).slice(1,5).join('\n')||'原文待提供' };
};
const rule = (row, fieldA, fieldB, operator, explain, type='text') => ({ruleId:`XLS-${row}`,sourceFile:'贷款文件比对要求.xlsx',sheet:'Sheet1',row,fieldA,fieldB,operator,type,explain,version:RULE_VERSION,product:'授信使用与支付材料核对',jurisdiction:'适用范围待业务确认',evidenceRequired:true});
export const RULES = [
  rule(2,'drawdown.applicationDate','facility.originalDate / drawdown.utilizationDate','dateNotBefore','落款日期为空忽略；有值不早于授信函日期和拟授信使用日','date'),
  rule(3,'drawdown.branch','facility.branch','equal','分行必填且一致；任一或多个分支行条款需人工'),
  rule(4,'drawdown.facilityLetterDate','facility.originalDate/latestDate','in','所引日期应等于原始或最新授信函日期','date'),
  rule(5,'drawdown.utilizationDate','asOf / businessCalendar','dateNotBefore','提款日不早于当前数据日期；本地及币种节假日需人工核实','date'),
  rule(6,'drawdown.tranche','facility.tranche','equal','授信段可空，非空则匹配'),
  rule(7,'drawdown.facilityName','facility.facilityName','equal','授信名称必填且相同'),
  rule(8,'drawdown.currency','facility.allowedCurrencies','in','币种在约定范围内；同意任意币种条款需人工'),
  rule(9,'drawdown.amount','facility.amount','lessThanInclusive','提款金额不大于合同上限，不推断银行授信余额','money'),
  rule(10,'drawdown.interestPeriod','facility.interestPeriods','in','利息期可空或匹配一个允许值；协商条款需人工'),
  rule(11,'drawdown.interestRate','facility.interestRate','equal','利率必填且一致；另行约定需定价依据'),
  rule(12,'drawdown.maturityDate','drawdown.utilizationDate + facility.maxTenorMonths','lessThanInclusive','到期日不超过合同期限；日历及特殊还款计划需人工','date'),
  rule(13,'drawdown.purpose','facility.purpose / trade_contract.goods','equal','声明用途应在合同范围内，交易实质及产品适用性人工核实'),
  rule(14,'drawdown.disbursementAccount','12 digits','accountFormat','12位账号，可为xxx-xxxxxx-xxx或连续数字'),
  rule(15,'drawdown.amount / paymentMethod','facility.paymentThreshold','threshold','超过合同阈值应选择银行受托支付','money'),
  rule(16,'drawdown.commitmentStatus','approved standard','manual','承诺逐项对照正式标准文本'),
  rule(18,'drawdown.currency','payment.currency','informational','提款与支付币种允许不同'),
  rule(19,'sum(payment.amount × fxRate)','drawdown.amount','greaterThanInclusive','折算到提款币种后支付合计≥提款金额','money'),
  rule(20,'payment.amountInWords','payment.amount','manual','大写金额匹配；未接转换校验器时人工核实'),
  rule(21,'drawdown.disbursementAccount','payment.debitAccount','equal','放款指示与支付扣款账号一致'),
  rule(22,'facility.borrower','payment.payer','equal','借款人与汇款人名称一致')
];
const fields = (type, map) => Object.entries(map).map(([field,label])=>({type,field,label,inputType:/amount|Amount|Funds|Component|fxRate/.test(field)?'number':/Date/.test(field)?'date':'text'}));
const uid = label => `${label}-${Date.now()}-${Math.random().toString(36).slice(2,8)}`;
export async function recomputeCase(source, previous=null, options={}) {
  if (!source?.documents) throw new Error('申请材料缺失');
  const snapshot = clone(source), f = docOf(snapshot,'facility')?.fields||{}, u = docOf(snapshot,'drawdown')?.fields||{}, t = docOf(snapshot,'trade_contract')?.fields||{}, inv = docOf(snapshot,'invoice')?.fields||{}, pay = docOf(snapshot,'payment')?.fields||{}, sup = docOf(snapshot,'support')?.fields||{};
  const attachments = clone(options.attachments??previous?.attachments??[]), corrections = clone(options.corrections??previous?.corrections??[]);
  const version = (previous?.run.version||0)+1, runId = uid(`${source.id}-RUN-${version}`), startedAt = new Date().toISOString(), evaluation=[];
  const check = (row,actual,expected,valid,status='ok') => evaluation.push({...RULES.find(r=>r.row===row),actual,expected,passed:Boolean(valid),status:valid?status:'error'});
  const utilized=date(u.utilizationDate), original=date(f.originalDate), applied=date(u.applicationDate), maturity=date(u.maturityDate), asOf=date(snapshot.asOf||demoData.asOf), latest=utilized&&Number.isInteger(f.maxTenorMonths)?addMonths(utilized,f.maxTenorMonths):null;
  check(2,u.applicationDate||'空白',`${f.originalDate} / ${u.utilizationDate}`,!u.applicationDate||!!(applied&&original&&utilized&&!isBefore(applied,original)&&!isBefore(applied,utilized)));
  check(3,u.branch,f.branch,!!u.branch&&(/任一或多个/.test(f.branch)||u.branch===f.branch),/任一或多个/.test(f.branch)?'warning':'ok');
  check(4,u.facilityLetterDate,[f.originalDate,f.latestDate].join(' / '),[f.originalDate,f.latestDate].includes(u.facilityLetterDate));
  check(5,u.utilizationDate,`≥ ${demoData.asOf}`,!!(utilized&&asOf&&!isBefore(utilized,asOf)),'warning');
  check(6,u.tranche||'空白',f.tranche,!u.tranche||u.tranche===f.tranche);
  check(7,u.facilityName,f.facilityName,!!u.facilityName&&u.facilityName===f.facilityName);
  check(8,u.currency,f.allowedCurrencies?.join(' / '),!!u.currency&&(agreed(f.allowedCurrencies?.join(' '))||f.allowedCurrencies?.includes(u.currency)),agreed(f.allowedCurrencies?.join(' '))?'warning':'ok');
  check(9,money(u.amount,u.currency),money(f.amount,f.currency),u.currency===f.currency&&minor(u.amount)>0&&minor(u.amount)<=minor(f.amount));
  check(10,u.interestPeriod||'空白',f.interestPeriods?.join(' / '),!u.interestPeriod||agreed(f.interestPeriods?.join(' '))||f.interestPeriods?.includes(u.interestPeriod));
  check(11,u.interestRate,f.interestRate,!!u.interestRate&&(agreed(f.interestRate)||u.interestRate===f.interestRate),agreed(f.interestRate)?'warning':'ok');
  check(12,u.maturityDate,latest?`≤ ${format(latest,'yyyy-MM-dd')}`:'需期限或还款计划',!!(maturity&&latest&&utilized&&!isBefore(maturity,utilized)&&!isAfter(maturity,latest)));
  check(13,u.purpose,f.purpose,!!u.purpose&&u.purpose===f.purpose);
  check(14,u.disbursementAccount,'12位账号',/^(\d{12}|\d{3}-\d{6}-\d{3})$/.test(u.disbursementAccount||''));
  check(15,`${money(u.amount,u.currency)} · ${u.paymentMethod}`,`超过${money(f.paymentThreshold,f.thresholdCurrency)}使用银行受托支付`,minor(u.amount)<=minor(f.paymentThreshold)||u.paymentMethod==='银行受托支付');
  check(16,u.commitmentStatus,'正式承诺逐项一致',true,'warning');
  check(18,`${u.currency} → ${pay.currency}`,'币种可以不同',true);
  let equivalent=0,fxValid=true;
  for(const doc of snapshot.documents.filter(d=>d.type==='payment')) {
    const p=doc.fields,same=p.currency===u.currency,rate=new Decimal(same?1:p.fxRate||0);
    if(!same&&(!p.fxSource||!p.fxAsOf||p.loanCurrency!==u.currency)||!rate.isFinite()||rate.lte(0)) fxValid=false;
    equivalent+=new Decimal(minor(p.amount)).times(rate).toDecimalPlaces(0,Decimal.ROUND_HALF_UP).toNumber();
  }
  check(19,money(equivalent/100,u.currency),`≥ ${money(u.amount,u.currency)}`,fxValid&&equivalent>=minor(u.amount),u.currency!==pay.currency||minor(pay.ownFunds)>0?'warning':'ok');
  check(20,pay.amountInWords||'待提供',money(pay.amount,pay.currency),true,'warning');
  check(21,pay.debitAccount,u.disbursementAccount,!!pay.debitAccount&&pay.debitAccount===u.disbursementAccount);
  check(22,pay.payer,f.borrower,!!pay.payer&&pay.payer===f.borrower);
  const engine=new Engine();
  for(const e of evaluation) engine.addRule({name:e.ruleId,conditions:{all:[{fact:e.ruleId,operator:'equal',value:true}]},event:{type:e.ruleId}});
  const passed=new Set((await engine.run(Object.fromEntries(evaluation.map(e=>[e.ruleId,e.passed])))).events.map(e=>e.type));
  for(const e of evaluation) if(!passed.has(e.ruleId))e.status='error';
  const byRow=row=>evaluation.find(r=>r.row===row), findings=[];
  const add=(suffix,stage,title,severity,actual,expected,reason,rows,refs,editable=[])=>{
    const id=`${source.id}-${suffix}`,prior=previous?.findings.find(f=>f.id===id),affected=!previous||options.rerunScope!=='local'||options.affected?.some(a=>a===suffix||a===stage);
    findings.push(!affected&&prior?clone(prior):{id,stage,title,severity,actual:String(actual??''),expected:String(expected??''),reason,rows,sources:refs,fields:editable,needsHuman:true,reviewState:'unreviewed',reviewNote:'',evaluatedInRun:runId,ruleVersion:RULE_VERSION});
  };
  const ref=(type,page)=>sourceRef(snapshot,type,page);
  const missing=['facility','drawdown','trade_contract','invoice','payment'].filter(type=>!docOf(snapshot,type));
  add('F01','materials','材料收齐与关联',missing.length?'pending':'ok',`${snapshot.documents.length} 份关联材料`,'授信、提款、合同、发票、支付指令',missing.length?'存在缺件，须提供原材料。':'文件已按本案编号关联；真实性及签章由人工复核。',[],[ref('trade_contract'),ref('invoice')]);
  add('F02','facility',byRow(9).status==='error'?'提款金额超过合同上限':'提款金额在合同上限内',byRow(9).status,byRow(9).actual,byRow(9).expected,'两份材料金额以最小单位重新比较。合同上限不代表银行剩余授信。',[9],[ref('facility'),ref('drawdown')],fields('drawdown',{amount:'提款金额'}));
  const refRows=[2,3,4,6,7,8,10],refErrors=refRows.filter(row=>byRow(row).status==='error');
  add('F03','facility',refErrors.length?'授信引用字段存在差异':'授信引用字段一致',refErrors.length?'error':'ok',`${u.branch} · ${u.facilityLetterDate} · ${u.currency} · ${u.tranche}`,`${f.branch} · ${f.latestDate} · ${f.allowedCurrencies?.join('/')}`,refErrors.length?`需补正第 ${refErrors.join('、')} 行对应字段。`:'名称、分行、币种、授信段和日期已核对。',refRows,[ref('facility'),ref('drawdown')],fields('drawdown',{branch:'分行',facilityLetterDate:'授信引用日期',tranche:'授信段',facilityName:'授信名称',currency:'币种',interestPeriod:'利息期',applicationDate:'申请落款日期'}));
  const loanError=[11,12,13].some(row=>byRow(row).status==='error');
  add('F04','facility',loanError?'利率、期限或用途需要补正':'利率、期限与声明用途一致',loanError?'error':'ok',`${u.interestRate} · ${u.maturityDate} · ${u.purpose}`,`${f.interestRate} · ${byRow(12).expected} · ${f.purpose}`,'按合同月数计算日期。交易实质与产品适用性见人工核实项。',[11,12,13],[ref('facility',2),ref('drawdown',2)],fields('drawdown',{interestRate:'利率',maturityDate:'到期日',utilizationDate:'提款日',purpose:'贷款用途'}));
  add('F05','payment','支付合计与提款金额',byRow(19).status,byRow(19).actual,byRow(19).expected,'原规则第19行使用≥；跨币种按记录汇率折算，自有资金不直接视为超付。',[18,19],[ref('payment',2),ref('drawdown')],fields('payment',{amount:'支付原币金额'}));
  const mismatch=pay.beneficiary!==t.seller||inv.seller!==t.seller||inv.tradeContractNumber!==t.contractNumber||pay.tradeContractNumber!==t.contractNumber||!pay.invoiceNumbers?.includes(inv.invoiceNumber),tradeEvidence=attachments.some(a=>a.status==='readable'&&a.findingId?.endsWith('TRADE')&&a.text?.trim());
  add('TRADE','payment',mismatch?'收款人与贸易凭据需要核实':'收款人与贸易凭据对应',mismatch?(tradeEvidence?'warning':'error'):'ok',`${pay.beneficiary} · ${inv.seller}`,t.seller,mismatch?(tradeEvidence?'已读到补充证据，代收关系仍待人核验，未自动证实。':'付款对象或关联编号不同；需要补正或代收协议。口头说明不足以放行。'):'合同、发票与支付指令的卖方及关联编号一致。',[22],[ref('payment'),ref('trade_contract'),ref('invoice')],fields('payment',{beneficiary:'收款人'}));
  const closed=equivalent===minor(pay.loanComponent)+minor(pay.ownFunds);
  add('FX','cross_border','币种、汇率与资金归属',!fxValid||!closed?'error':(u.currency!==pay.currency||minor(pay.ownFunds)>0?'warning':'ok'),`${money(pay.amount,pay.currency)} × ${pay.fxRate} = ${money(equivalent/100,u.currency)}；贷款 ${money(pay.loanComponent,u.currency)} + 自有资金 ${money(pay.ownFunds,u.currency)}`,'原币、汇率时点、折算金额及资金来源可追溯',!closed?'资金归属合计未能闭合折算金额。':'金额已重算；汇率成交口径与自有资金来源须人工核实。',[18,19],[ref('payment',2),ref('support')],fields('payment',{fxRate:'汇率',ownFunds:'自有资金',loanComponent:'贷款资金'}));
  const remaining=minor(inv.amount)-minor(inv.priorUsedAmount)-minor(inv.currentProposedUsedAmount);
  add('HISTORY','history',remaining<0?'发票累计使用超过票面金额':'发票历史与本次使用',remaining<0?'error':minor(inv.priorUsedAmount)>0?'warning':'ok',`票面 ${money(inv.amount,inv.currency)} − 历史 ${money(inv.priorUsedAmount,inv.currency)} − 本次 ${money(inv.currentProposedUsedAmount,inv.currency)} = ${money(remaining/100,inv.currency)}`,'余额不为负，并核实分批使用口径','同一发票重复出现不等于重复融资。仅核对已提供台账，不代表外部银行记录。',[],[ref('invoice'),ref('history')],fields('invoice',{priorUsedAmount:'历史使用金额',currentProposedUsedAmount:'本次使用金额'}));
  const accountErrors=[14,15,21,22].filter(row=>byRow(row).status==='error');
  add('F09','payment',accountErrors.length?'支付方式或账号存在差异':'支付方式与账号一致',accountErrors.length?'error':'ok',`${u.paymentMethod} · ${u.disbursementAccount} / ${pay.debitAccount}`,byRow(15).expected,accountErrors.length?`需核对第 ${accountErrors.join('、')} 行。`:'合同阈值、12位账号、扣款账号及汇款人已核对。',[14,15,21,22],[ref('payment'),ref('drawdown',2)],[...fields('drawdown',{disbursementAccount:'放款账号',paymentMethod:'支付方式'}),...fields('payment',{debitAccount:'支付扣款账号'})]);
  if(sup.handwritten||sup.extractionStatus==='uncertain_requires_human')add('READ','materials','手写账号需确认',sup.normalizedAccount&&sup.normalizedAccount===u.disbursementAccount?'warning':'pending',sup.normalizedAccount||sup.accountCandidates?.join(' / '),u.disbursementAccount,'先核对原页后填写完整账号，重新计算后仍需人确认。',[14,21],[ref('support')],fields('support',{normalizedAccount:'确认后的完整账号'}));
  const dateError=byRow(5).status==='error',restricted=/自动贴片生产设备|固定资产|股权|股东分红/.test(inv.goods||'');
  add('SCOPE','applicability',dateError?'提款日期早于当前数据日期':restricted?'设备用途及产品适用性待确认':'法域、日历及原件需人工核实',dateError?'error':'warning',restricted?inv.goods:'法域待确认 · 日历未连接 · 签章和大写金额未核验','确认本案法域、产品及正式原件','公开国内规则仅作背景，不直接套为跨境法规结论。节假日、承诺、签章、大写金额需业务复核。',[5,16,20],[ref('drawdown',2),ref('payment',2)],fields('drawdown',{utilizationDate:'提款日'}));
  attachments.forEach((a,i)=>{if(a.status!=='readable')add(`ATT-${i}`,'materials',`新材料待解析：${a.name}`,'pending','文件已登记，内容尚未核验','提供可读文本或解析后确认字段','本轮已撤回通过状态，不能使用旧版本意见。',[],[]);});
  const labels=[['load_case','读取申请资料',`${snapshot.documents.length} 份关联文件`],['extract_fields','读取材料字段','使用已有文字层，扫描材料不猜值'],['load_rules','查找适用规则',`${RULES.length} 条规则 · ${RULE_VERSION}`],['compare_facility_drawdown','授信与提款核对',`${evaluation.filter(r=>r.row<=16&&r.status==='error').length} 处差异`],['match_payment_trade','支付与贸易凭据','收款人、合同、发票及账号核对'],['check_cross_border','币种与资金归属',money(equivalent/100,u.currency)],['check_history','历史使用核对',money(remaining/100,inv.currency)],['retrieve_evidence','汇集引用依据','原文、页码与知识依据已关联'],['draft_findings','生成核对结论',`${findings.filter(f=>f.severity!=='ok').length} 项需处理`],['human_gate','等待人工复核','不执行支付或放款'],['build_report','形成短报告草稿',`v${version}`]];
  const steps=labels.map(([toolName,label,outputSummary])=>({toolName,label,outputSummary,inputSummary:`${source.id} · ${options.rerunScope==='local'?'依赖范围':'完整材料'}`,sourceFiles:snapshot.documents.map(d=>d.id),runId,status:toolName==='human_gate'?'needs_human':'completed',startedAt,endedAt:new Date().toISOString()}));
  return {caseId:source.id,caseSnapshot:snapshot,findings,rules:evaluation,attachments,corrections,run:{runId,version,startedAt,endedAt:new Date().toISOString(),rerunScope:options.rerunScope||'full',affected:options.affected||[],steps,context:{caseId:source.id,previousRunId:previous?.run.runId||null,ruleVersion:RULE_VERSION,corrections:clone(corrections),attachments:clone(attachments)}},humanConfirmed:false,review:{reviewer:'',decision:'pending',note:''}};
}
const dependencies={amount:['F02','F05','FX','F09'],branch:['F03'],facilityLetterDate:['F03'],tranche:['F03'],facilityName:['F03'],currency:['facility','payment','cross_border'],interestPeriod:['F03'],applicationDate:['F03'],interestRate:['F04'],maturityDate:['F04'],utilizationDate:['F04','SCOPE'],purpose:['F04','SCOPE'],beneficiary:['TRADE'],disbursementAccount:['F09','READ'],debitAccount:['F09'],paymentMethod:['F09'],normalizedAccount:['READ'],ownFunds:['FX','F05'],loanComponent:['FX'],fxRate:['cross_border','payment','history'],currentProposedUsedAmount:['HISTORY'],priorUsedAmount:['HISTORY']};
export function correctionScope(input){
  if(input.scope==='full'||input.attachment&&input.attachment.status!=='readable'||input.field==='priorUsedAmount'||input.field&&!dependencies[input.field]||!input.field&&!input.findingId)return{scope:'full',affected:[]};
  return{scope:'local',affected:input.field?dependencies[input.field]:[input.findingId?.split('-').at(-1),'payment','cross_border','history']};
}
export async function applyCorrection(source,previous,input){
  if(!input.explanation?.trim()&&!input.field&&!input.attachment)throw new Error('请填写纠正字段、说明或补充材料');
  const snapshot=clone(previous.caseSnapshot||source),finding=previous.findings.find(f=>f.id===input.findingId),spec=finding?.fields.find(f=>f.field===input.field&&(!input.documentType||f.type===input.documentType)),targetType=input.documentType||spec?.type||'drawdown',target=docOf(snapshot,targetType);let oldValue=null;
  if(input.field){
    if(!target||!Object.hasOwn(target.fields,input.field))throw new Error('字段不属于本案材料');
    oldValue=target.fields[input.field];
    if(typeof oldValue==='number'||spec?.inputType==='number'){const d=new Decimal(input.value);if(!d.isFinite()||d.isNegative())throw new Error('请输入有效非负数');if(input.field!=='fxRate')minor(d);target.fields[input.field]=d.toNumber();}
    else{if(spec?.inputType==='date'&&input.value&&!date(input.value))throw new Error('请输入有效日期');target.fields[input.field]=String(input.value).trim();}
  }
  const scope=correctionScope(input),correction={correctionId:uid(`${source.id}-COR`),caseId:source.id,previousRunId:previous.run.runId,findingId:input.findingId||null,documentType:targetType,field:input.field||null,oldValue,newValue:input.field?target.fields[input.field]:null,explanation:input.explanation||'',submittedBy:input.submittedBy||'审核人员',submittedAt:new Date().toISOString(),sourcePage:input.sourcePage||null,rerunScope:scope.scope,affected:scope.affected};
  const attachments=clone(previous.attachments||[]);if(input.attachment)attachments.push({...clone(input.attachment),findingId:input.findingId,correctionId:correction.correctionId});
  return recomputeCase(snapshot,previous,{rerunScope:scope.scope,affected:scope.affected,attachments,corrections:[...previous.corrections,correction]});
}
export function canPass(result,options={}){
  if(!result?.findings?.length||result.attachments?.some(a=>a.status!=='readable')||result.findings.some(f=>['error','pending'].includes(f.severity)))return false;
  if(result.findings.some(f=>f.severity==='warning'&&(f.reviewState!=='confirmed'||!f.reviewNote?.trim())))return false;
  return Boolean(options.humanConfirmed??result.humanConfirmed);
}
export function reportFor(result){
  const reviewer=result.review?.reviewer?.trim(),note=result.review?.note?.trim(),accepted=canPass(result)&&reviewer&&note&&result.review?.decision==='pass',returned=reviewer&&note&&result.review?.decision==='return',issues=result.findings.filter(f=>f.severity!=='ok'&&f.reviewState!=='confirmed');
  return{version:result.run.version,runId:result.run.runId,caseId:result.caseId,generatedAt:new Date().toISOString(),company:result.caseSnapshot.company,amount:docOf(result.caseSnapshot,'drawdown')?.fields.amount,currency:docOf(result.caseSnapshot,'drawdown')?.fields.currency,conclusion:returned?'退回补正':accepted?'可继续':issues.some(f=>f.severity==='error')?'需补正':'待人工确认',status:returned||accepted?'reviewed':'draft',reasons:issues.slice(0,3).map(f=>f.title),nextAction:returned?'按退回意见补件并创建新版本':accepted?'提交后续授权业务处理':'核对突出项目，补证并记录人工意见',review:clone(result.review),findings:clone(result.findings),rules:clone(result.rules),corrections:clone(result.corrections),attachments:clone(result.attachments),steps:clone(result.run.steps),sourceBoundary:result.caseSnapshot.sourceBoundary};
}
export function createAssistantDemo(caseId){return{caseId,reply(message,context={}){
  const issues=(context.findings||[]).filter(f=>f.severity!=='ok');
  if(/受托支付/.test(message))return'本地演示：受托支付就是银行根据申请，把钱支付给合同约定的交易对象。是否必须采用，要看本案合同和适用规则。问答不会改变业务核对。';
  if(/历史|版本|纠正|重跑/.test(message))return`本地演示：当前 ${caseId} 有 ${context.runHistory?.length||1} 个运行版本。纠正留下字段、说明和证据，再按依赖生成新版本；原报告保留。助手回答只读，请到具体差异下提交纠正。`;
  if(/材料|文件/.test(message))return`本地演示：本案关联 ${context.documents?.length||0} 份材料。已有文字与字段可读取；新PDF及图片附件未解析前保持待核验。`;
  return`本地演示：${caseId} 有 ${issues.length} 项需处理。${issues.slice(0,3).map(f=>`${f.title}：${f.reason}`).join('\n')||'核心比对一致，仍需人工复核。'}\n建议查看原页和规则来源，再在差异下提交纠正或补证。当前未连接真实模型，助手不会修改审核结论。`;
}};}
