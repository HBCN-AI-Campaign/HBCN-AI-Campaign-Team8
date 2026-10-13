import test from 'node:test';
import assert from 'node:assert/strict';
import { loadDemoData, recomputeCase, applyCorrection, canPass, createAssistantDemo } from '../web/workflow.mjs';

const data=loadDemoData();
test('all five source cases independently produce findings',async()=>{
  for(const source of data.cases){const result=await recomputeCase(source);assert.equal(result.caseId,source.id);assert.ok(result.findings.length>=8);assert.equal(result.run.steps.length,11);}
});
test('typed amount and date rules recompute source fields',async()=>{
  const result=await recomputeCase(data.cases[1]);const over=result.findings.find(f=>f.id.endsWith('F02'));
  assert.equal(over.severity,'error');assert.match(over.actual,/2,200,000/);assert.match(over.expected,/2,000,000/);
  assert.equal(result.rules.find(r=>r.row===12).expected,'≤ 2027-01-15');
});
test('all-green core checks still require human confirmation',()=>{
  const result={findings:[{severity:'ok',reviewState:'unreviewed'}],attachments:[]};
  assert.equal(canPass(result),false);assert.equal(canPass(result,{humanConfirmed:true}),true);
});
test('a hard amount violation cannot be overridden by a human decision',async()=>{
  const result=await recomputeCase(data.cases[1]);assert.equal(canPass(result,{humanConfirmed:true}),false);
});
test('field correction creates a local rerun and preserves unrelated findings',async()=>{
  const source=data.cases[1],before=await recomputeCase(source),changed=await applyCorrection(source,before,{findingId:source.id+'-F02',field:'amount',value:1800000,explanation:'修正提款金额字段'});
  assert.equal(changed.run.version,2);assert.equal(changed.run.rerunScope,'local');
  assert.equal(changed.findings.find(f=>f.id.endsWith('F02')).severity,'ok');
  assert.equal(changed.findings.find(f=>f.id.endsWith('F03')).severity,'error');
  assert.equal(changed.findings.find(f=>f.id.endsWith('F03')).evaluatedInRun,before.findings.find(f=>f.id.endsWith('F03')).evaluatedInRun);
});
test('third-party explanation alone is insufficient; readable evidence becomes human review',async()=>{
  const source=data.cases[2],before=await recomputeCase(source),unsupported=await applyCorrection(source,before,{findingId:source.id+'-TRADE',explanation:'集团代收，无需担心'});
  assert.equal(unsupported.findings.find(f=>f.id.endsWith('TRADE')).severity,'error');
  const evidenced=await applyCorrection(source,unsupported,{findingId:source.id+'-TRADE',explanation:'附协议第2页',attachment:{name:'代收协议.txt',text:'卖方授权该收款方代收本合同货款。',status:'readable'}});
  assert.equal(evidenced.findings.find(f=>f.id.endsWith('TRADE')).severity,'warning');assert.equal(evidenced.findings.find(f=>f.id.endsWith('TRADE')).reviewState,'unreviewed');
});
test('cross currency and own funds are calculated without a false amount error',async()=>{
  const result=await recomputeCase(data.cases[3]);assert.notEqual(result.findings.find(f=>f.id.endsWith('F05')).severity,'error');
  assert.match(result.findings.find(f=>f.id.endsWith('FX')).actual,/864,000/);
});
test('over-allocation of invoice usage is a computed hard error',async()=>{
  const source=data.cases[4],before=await recomputeCase(source),changed=await applyCorrection(source,before,{findingId:source.id+'-HISTORY',documentType:'invoice',field:'currentProposedUsedAmount',value:900000,explanation:'核对本次使用金额'});
  assert.equal(changed.findings.find(f=>f.id.endsWith('HISTORY')).severity,'error');
});
test('unknown attachment creates a full rerun, pending state and removes prior pass',async()=>{
  const source=data.cases[0],before=await recomputeCase(source),changed=await applyCorrection(source,before,{findingId:source.id+'-F01',explanation:'新增材料待解析',attachment:{name:'new-evidence.pdf',status:'pending',pending:true}});
  assert.equal(changed.run.rerunScope,'full');assert.equal(changed.findings.some(f=>f.severity==='pending'),true);assert.equal(canPass(changed),false);
});
test('assistant answers are read-only and identify local mode',()=>{
  const session=createAssistantDemo(data.cases[0].id),snapshot=JSON.stringify(data.cases[0]);
  assert.match(session.reply('解释差异',{findings:[]}),/本地演示/);assert.equal(JSON.stringify(data.cases[0]),snapshot);
});
