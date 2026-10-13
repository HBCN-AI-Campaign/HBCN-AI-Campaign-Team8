import test from 'node:test';
import assert from 'node:assert/strict';
import { escapeHTML, renderTermParagraph } from '../web/app.mjs';

test('user supplied text is escaped before rendering',()=>{
  assert.equal(escapeHTML('<img src=x onerror=alert(1)>'),'&lt;img src=x onerror=alert(1)&gt;');
});
test('term explanation renders beneath its source paragraph',()=>{
  const html=renderTermParagraph('受托支付金额需要核对',{term:'受托支付',definition:'银行按约定向交易对象付款。'},true);
  assert.ok(html.indexOf('受托支付金额需要核对')<html.indexOf('银行按约定向交易对象付款'));assert.match(html,/term-explanation/);
});
test('closed term mode leaves only the original paragraph',()=>{
  const html=renderTermParagraph('<script>alert(1)</script>',{term:'术语',definition:'解释'},false);
  assert.doesNotMatch(html,/term-explanation/);assert.doesNotMatch(html,/<script>/);
});
