"""规则引擎实现 —— 只做"能用结构化字段直接硬核对"的规则。

对照 material_set_1/checklist_rules.json。字段 key 以 parse_agent.py 实际
识别产出的为准（可能与 checklist documents 段命名略有差异），比对逻辑一致。

职责边界（重要）：
  ✅ 规则引擎（本文件）：凡能靠已识别字段做确定性比较/格式校验的，一律在此判 pass/fail/warn。
  ➡️ 专项审核 Agent（review_agent.py）：凡 checklist 的 logic 依赖外部能力的
     —— 节假日判定 is_holiday、汇率折算 fx_convert、提单真伪 verify_authenticity、
        海关联网 query_customs_website、制裁名单、法规检索、语义翻译/研判 ——
     规则引擎无法下定论，这里返回 Status.SKIP 且 why 以「[专项]」开头并给出移交说明，
     由 review_agent 读取这些 [专项] 项，转为"专项审核步骤 + 待处置项"继续处理。

维度（dimension）：
  A 授信层（提款 ↔ FOL）
  B 资金拆分（提款 ↔ 支付）
  C 贸易背景（支付 ↔ 外部单据）
  E 合规与制裁
  F 形式与完整性
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

from .base import DocBundle, Rule, RuleResult, Status, register

# 专项审核移交标记：why 以此开头的 SKIP 项会被 review_agent 识别为"需专项审核"
HANDOFF = "[专项]"

# 禁止用途清单（取自 checklist_rules.json，可在规则内直接文本匹配，属硬核对）
FORBIDDEN_PURPOSES = [
    "股东分红", "金融资产投资", "固定资产投资", "股权投资",
    "证券市场", "期货市场", "房地产市场", "转贷",
    "票据解付", "支付奖金", "绩效工资", "缴纳罚款",
    "虚增财政收入", "隐性债务", "禁止生产经营",
]


# ---------------- 辅助函数 ----------------
def _dec(v) -> Decimal:
    """从 '1500 USD/吨' / 8_000_000 / '8000 吨' 这类值里抠出数字。"""
    if v is None:
        return Decimal(0)
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v))
    m = re.search(r"[-+]?\d[\d,]*\.?\d*", str(v).replace(",", ""))
    return Decimal(m.group()) if m else Decimal(0)


def _num(v) -> Decimal:
    return _dec(v)


def _d(v) -> date | None:
    """解析 YYYY-MM-DD 日期；失败返回 None。"""
    if not v:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(str(v).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _norm(s) -> str:
    return (str(s) if s is not None else "").strip()


def _skip(rid, name, dim, why):
    return RuleResult(rid, name, dim, Status.SKIP, why=why)


def _field_row(docs: DocBundle, type_code: str, field_key: str, label: str, value, flag: str = "", idx: int = 0) -> list:
    return [label, value, flag, docs.locate(type_code, field_key, idx)]


def _handoff(rid, name, dim, why, suggestion=""):
    """移交专项审核：规则引擎做不到，交给 review_agent。"""
    return RuleResult(rid, name, dim, Status.SKIP, why=f"{HANDOFF} {why}", suggestion=suggestion)


def _term_location(docs,fact):
    sources=(fact.get('evidence') or {}).get('clause_text',{}).get('sources') or []
    if not sources:return None
    page=sources[0]['page'];boxes=[s['bbox'] for s in sources if s['page']==page]
    metas=docs.meta_by_type.get('FACILITY_LETTER') or [{}]
    return {**metas[0],'type_code':'FACILITY_LETTER','field_key':'facility_terms','page':page,
        'bbox':[min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes)]}


# ================================================================
# A 维度：授信层（提款指令 ↔ FOL）
# ================================================================
@register
class R_DrawdownCurrencyInFacilityScope(Rule):
    id = "DRAWDOWN_VS_FACILITY_LETTER__CURRENCY"
    name = "提款币种 ∈ 授信条款币种范围"
    dimension = "A"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        dd = docs.first("DRAWDOWN_INSTRUCTION")
        fol = docs.first("FACILITY_LETTER")
        if not dd or not fol:
            return _skip(self.id, self.name, self.dimension, "缺少提款指令或授信函，无法校验。")
        context=fol.get('_facility_context') or {}
        application=context.get('term_application')
        scoped=application is not None or 'facility_terms' in fol
        if scoped:
            permitted=(application or {}).get('facts',{}).get('permitted_currencies',{})
            if context.get('status')!='ready' or (application or {}).get('status')!='accepted' or permitted.get('status')!='accepted':
                return RuleResult(self.id,self.name,self.dimension,Status.WARN,
                    why="所选授信的完整条款或允许提款币种尚未核实，不能回退使用全函币种或额度计价币种。")
            allowed=(permitted.get('value') or {}).get('currencies')
        elif fol.get("utilization_currency") == "any currency agreed by lender":
            return RuleResult(self.id, self.name, self.dimension, Status.WARN,
                              why="FOL要求贷款人同意提款币种，尚须核实本次币种的同意依据。")
        dd_ccy = _norm(dd.get("currency"))
        tranche = _norm(dd.get("tranche"))
        if not scoped:allowed = fol.get("allowed_currencies") or []
        if not dd_ccy or not isinstance(allowed,list) or not allowed:
            return RuleResult(self.id,self.name,self.dimension,Status.WARN,
                why="提款币种或FOL允许币种范围尚未核实，无法判定是否超出范围。")
        # 定位信息：提款币种来自提款指令、授信段/币种范围来自 FOL
        loc_ccy = docs.locate("DRAWDOWN_INSTRUCTION", "currency")
        loc_tranche = docs.locate("DRAWDOWN_INSTRUCTION", "tranche")
        loc_allowed = _term_location(docs,permitted) if scoped else docs.locate("FACILITY_LETTER", "allowed_currencies")
        if scoped:tranche=application['facility_name']
        if dd_ccy in allowed:
            return RuleResult(
                self.id, self.name, self.dimension, Status.PASS,
                why=f"提款币种 {dd_ccy} 在授信段“{tranche}”允许范围内。",
                detail=[["提款币种", dd_ccy, "", loc_ccy], ["FOL 授信段", tranche, "", loc_tranche],
                        ["该段币种范围", "/".join(allowed), "", loc_allowed]],
            )
        return RuleResult(
            self.id, self.name, self.dimension, Status.FAIL,
            why=f"提款指令选定授信段“{tranche}”限 {'/'.join(allowed) or '—'}，提款币种填 {dd_ccy} 超出条款范围。",
            suggestion="要求客户改用允许币种提款，或改选可用该币种的授信段后重新提交。",
            detail=[["提款币种", dd_ccy, "bad", loc_ccy], ["FOL 授信段", tranche, "", loc_tranche],
                    ["该段币种范围", "/".join(allowed) or "—", "bad", loc_allowed]],
        )


@register
class R_DrawdownAmountWithinFacility(Rule):
    id = "DRAWDOWN_VS_FACILITY_LETTER__AMOUNT"
    name = "提款金额 ≤ 授信额度"
    dimension = "A"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        dd = docs.first("DRAWDOWN_INSTRUCTION")
        fol = docs.first("FACILITY_LETTER")
        if not dd or not fol:
            return _skip(self.id, self.name, self.dimension, "缺少提款指令或授信函，无法校验。")
        context=fol.get('_facility_context') or {}
        limit=context.get('nominal_limit') or {}
        nominal=limit.get('amount') if context.get('status')=='ready' else fol.get('facility_amount')
        nominal_currency=limit.get('currency') if context.get('status')=='ready' else fol.get('facility_currency')
        from ..parsing.normalization import normalize
        try:
            amt=normalize(dd.get('amount'),'money');facility=normalize(nominal,'money')
            if amt is None or facility is None:raise ValueError('missing amount')
            amt=Decimal(amt);facility=Decimal(facility)
        except (ValueError,TypeError):
            return RuleResult(self.id,self.name,self.dimension,Status.WARN,
                why="提款金额或适用名义限额尚未核实，未识别值不能作为零。")
        if not nominal_currency or nominal_currency!=dd.get('currency'):
            return RuleResult(self.id,self.name,self.dimension,Status.WARN,
                why="名义限额计价币种未明确或与提款币种不同，须核实允许币种及汇率依据，暂不比较金额大小。")
        loc_amt = docs.locate("DRAWDOWN_INSTRUCTION", "amount")
        loc_fac = docs.locate("FACILITY_LETTER", "facility_amount")
        if context.get('status')=='ready':
            sources=(limit.get('cells',{}).get('amount') or {}).get('sources') or []
            meta=(docs.meta_by_type.get('FACILITY_LETTER') or [{}])[0]
            loc_fac={**meta,'type_code':'FACILITY_LETTER','field_key':'borrower_allocations',
                'page':sources[0]['page'],'bbox':sources[0]['bbox']} if sources else None
        if amt <= facility:
            return RuleResult(
                self.id, self.name, self.dimension, Status.WARN,
                why=f"提款金额未超过同币种名义限额 {facility:,.2f} {nominal_currency}；尚缺用信、冻结及共享占用等余额依据，不能认定剩余可用额度。",
                suggestion="核实本次主体及授信的实际可用余额，再确认是否可提款。",
                detail=[["提款金额", f"{amt:,.2f}", "", loc_amt], ["名义限额", f"{facility:,.2f}", "", loc_fac],
                        ["额度口径", "名义限额；非可用余额", ""]],
            )
        return RuleResult(
            self.id, self.name, self.dimension, Status.FAIL,
            why=f"提款金额 {amt:,.2f} {nominal_currency} 超过同币种名义限额 {facility:,.2f} {nominal_currency}。",
            suggestion="要求客户下调提款金额或申请提额。",
            detail=[["提款金额", f"{amt:,.2f}", "bad", loc_amt], ["名义限额", f"{facility:,.2f}", "bad", loc_fac]],
        )


@register
class R_DrawdownBranch(Rule):
    id = "DRAWDOWN_VS_FACILITY_LETTER__BRANCH"
    name = "提款分行 == FOL 指定分行"
    dimension = "A"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        dd = docs.first("DRAWDOWN_INSTRUCTION")
        fol = docs.first("FACILITY_LETTER")
        if not dd or not fol:
            return _skip(self.id, self.name, self.dimension, "缺少提款指令或授信函，无法校验。")
        fol_branch = _norm(fol.get("lender_branch"))
        dd_branch = _norm(dd.get("branch"))
        if not fol_branch:
            return _skip(self.id, self.name, self.dimension, "FOL 未指定分行，跳过。")
        if any(k in fol_branch for k in ("任一", "多个", "任何")):
            return RuleResult(self.id, self.name, self.dimension, Status.WARN,
                              why=f"FOL 约定可通过任一/多个分支行行事（{fol_branch}），请人工确认分行。",
                              suggestion="请审核人核对本次提款分行是否属于 FOL 允许的分支行。")
        if not dd_branch:
            return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                              why=f"提款指令未单列分行，默认沿用 FOL 指定分行“{fol_branch}”。",
                              detail=[["FOL 分行", fol_branch, ""]])
        if dd_branch == fol_branch:
            return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                              why=f"提款分行与 FOL 指定分行一致（{fol_branch}）。",
                              detail=[["提款分行", dd_branch, ""], ["FOL 分行", fol_branch, ""]])
        return RuleResult(self.id, self.name, self.dimension, Status.FAIL,
                          why=f"提款分行“{dd_branch}”与 FOL 指定分行“{fol_branch}”不一致。",
                          suggestion="核实提款分行，须与 FOL 指定分行一致。",
                          detail=[["提款分行", dd_branch, "bad"], ["FOL 分行", fol_branch, "bad"]])


@register
class R_DrawdownTranche(Rule):
    id = "DRAWDOWN_VS_FACILITY_LETTER__TRANCHE"
    name = "授信段存在于 FOL"
    dimension = "A"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        dd = docs.first("DRAWDOWN_INSTRUCTION")
        fol = docs.first("FACILITY_LETTER")
        if not dd or not fol:
            return _skip(self.id, self.name, self.dimension, "缺少提款指令或授信函，无法校验。")
        tranche = _norm(dd.get("tranche"))
        context=fol.get('_facility_context') or {}
        if context.get('status')=='ready' and context.get('nominal_limit'):
            return RuleResult(self.id,self.name,self.dimension,Status.PASS,
                why="本次授信品种已由服务器原件凭据及登记主体分配唯一关联；对应说明不改写原文字段。",
                detail=[["所选授信品种",context['nominal_limit']['facility_name'],""],
                        ["对应方式",context.get('association_method') or '待核实',""]])
        if not tranche:
            return _skip(self.id, self.name, self.dimension, "提款指令未填授信段，跳过。")
        fol_facility = _norm(fol.get("facility"))
        if not fol_facility:
            return RuleResult(self.id,self.name,self.dimension,Status.WARN,
                why="FOL适用授信品种尚未核实，不能因空字符串包含关系判定授信段存在。")
        if tranche == fol_facility or tranche in fol_facility or fol_facility in tranche:
            return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                              why=f"提款所选授信段“{tranche}”在 FOL 授信品种中存在。",
                              detail=[["提款授信段", tranche, ""], ["FOL 授信品种", fol_facility, ""]])
        return RuleResult(self.id, self.name, self.dimension, Status.FAIL,
                          why=f"提款授信段“{tranche}”未在 FOL 授信品种“{fol_facility}”中找到。",
                          suggestion="核实授信段名称，须与 FOL 对应授信品种一致。",
                          detail=[["提款授信段", tranche, "bad"], ["FOL 授信品种", fol_facility, "bad"]])


@register
class R_DrawdownPurpose(Rule):
    id = "DRAWDOWN_VS_FACILITY_LETTER__PURPOSE"
    name = "提款用途非禁止用途"
    dimension = "A"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        dd = docs.first("DRAWDOWN_INSTRUCTION")
        fol = docs.first("FACILITY_LETTER")
        if not dd or not fol:
            return _skip(self.id, self.name, self.dimension, "缺少提款指令或授信函，无法校验。")
        purpose = _norm(dd.get("purpose"))
        if not purpose:
            return RuleResult(self.id, self.name, self.dimension, Status.FAIL,
                              why="提款用途为空，无法确认资金投向合规性。",
                              suggestion="要求补填提款用途。")
        hit = [p for p in FORBIDDEN_PURPOSES if p in purpose]
        if hit:
            return RuleResult(self.id, self.name, self.dimension, Status.FAIL,
                              why=f"提款用途“{purpose}”命中禁止用途：{'、'.join(hit)}。",
                              suggestion="资金不得用于禁止用途，要求更正用途或驳回。",
                              detail=[["提款用途", purpose, "bad"], ["命中禁止项", "、".join(hit), "bad"]])
        # 禁止清单硬核对通过；但"是否落在 FOL 用途范围内"属语义包含判断 → 由专项审核兜底
        return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                          why=f"提款用途“{purpose}”未命中禁止用途清单；与 FOL 用途范围的语义包含关系由专项审核进一步研判。",
                          detail=[["提款用途", purpose, ""], ["FOL 用途范围", _norm(fol.get("purpose")), ""]])


@register
class R_DrawdownDisbursementThreshold(Rule):
    id = "DRAWDOWN_VS_FACILITY_LETTER__DISBURSEMENT"
    name = "大额提款须银行受托支付"
    dimension = "A"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        dd = docs.first("DRAWDOWN_INSTRUCTION")
        fol = docs.first("FACILITY_LETTER")
        if not dd or not fol:
            return _skip(self.id, self.name, self.dimension, "缺少提款指令或授信函，无法校验。")
        threshold = fol.get("disbursement_threshold")
        if threshold is None:
            return _skip(self.id, self.name, self.dimension, "FOL 未设放款方式阈值，跳过。")
        amt = _dec(dd.get("amount"))
        method = _norm(dd.get("disbursement_method"))
        if amt > _dec(threshold):
            if "受托" in method:
                return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                                  why=f"提款金额 {amt:,.2f} 超阈值，已勾选“银行受托支付”。",
                                  detail=[["提款金额", f"{amt:,.2f}", ""], ["放款方式", method, ""]])
            return RuleResult(self.id, self.name, self.dimension, Status.FAIL,
                              why=f"提款金额 {amt:,.2f} 超过阈值 {_dec(threshold):,.2f}，但放款方式为“{method}”而非银行受托支付。",
                              suggestion="大额放款须采用银行受托支付。",
                              detail=[["提款金额", f"{amt:,.2f}", "bad"], ["放款方式", method or "—", "bad"]])
        return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                          why=f"提款金额 {amt:,.2f} 未超阈值，放款方式“{method}”无强制要求。",
                          detail=[["提款金额", f"{amt:,.2f}", ""], ["放款方式", method, ""]])


@register
class R_DrawdownLoanTenor(Rule):
    id = "DRAWDOWN_VS_FACILITY_LETTER__TENOR"
    name = "本次贷款期限符合所选授信条款"
    dimension = "A"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        dd=docs.first('DRAWDOWN_INSTRUCTION');fol=docs.first('FACILITY_LETTER')
        if not dd or not fol:return _skip(self.id,self.name,self.dimension,'缺少提款指令或授信函，无法核对期限。')
        context=fol.get('_facility_context') or {};application=context.get('term_application')
        if application is None and 'facility_terms' not in fol:
            return _skip(self.id,self.name,self.dimension,'未提供逐授信条款，期限仍须专项审核。')
        fact=(application or {}).get('facts',{}).get('loan_tenor') or {}
        if context.get('status')!='ready' or (application or {}).get('status')!='accepted' or fact.get('status')!='accepted':
            return RuleResult(self.id,self.name,self.dimension,Status.WARN,
                why='所选授信的完整期限条款或关联尚未核实，不能借用其他授信期限或以利息期替代。')
        policy=fact.get('value') or {}
        def period(p):return f"{p['count']}{'个月' if p['unit']=='months' else '天'}"
        conditions=[]
        if policy.get('standard_periods'):conditions.append('标准期限：'+' / '.join(period(p) for p in policy['standard_periods']))
        if policy.get('other_period_requires_lender_agreement') is True:conditions.append('其他期限须贷款人同意')
        if policy.get('absolute_maximum'):
            conditions.append(('包括延期和展期的绝对上限：' if policy.get('maximum_includes_extensions_and_rollovers') is True else '每次用信上限：')+period(policy['absolute_maximum']))
        for kind,maximum in policy.get('instrument_maxima',{}).items():
            conditions.append({'paper':'纸质票据','electronic':'电子票据'}.get(kind,kind)+'上限：'+period(maximum))
        from ..parsing.term_facts import date_span_observation
        observation=date_span_observation(dd.get('drawdown_date'),dd.get('maturity_date'))
        elapsed=observation.get('elapsed_days')
        # No calendar-month/rollover/origin convention or lender approval is
        # inferred from dates or the independently extracted interest period.
        return RuleResult(self.id,self.name,self.dimension,Status.WARN,
            why='已取得所选授信期限条件；起讫日、月期限、展期起点及适用同意依据仍须核实，不能仅凭日期差或利息期判定通过。',
            suggestion='按完整期限条款核实本次期限、适用日历及展期/贷款人同意依据。',
            detail=[['所选授信',application['facility_name'],''],
                    ['期限条件','；'.join(conditions) or '待核实','',_term_location(docs,fact)],
                    ['提款日',_norm(dd.get('drawdown_date')) or '待核实','',docs.locate('DRAWDOWN_INSTRUCTION','drawdown_date')],
                    ['到期日',_norm(dd.get('maturity_date')) or '待核实','',docs.locate('DRAWDOWN_INSTRUCTION','maturity_date')],
                    ['日期差观察值',f'{elapsed}天；不是已核实贷款期限' if elapsed is not None else '日期待核实','']])


@register
class R_DrawdownDates(Rule):
    id = "DRAWDOWN__DRAWDOWN_DATE"
    name = "提款日/到期日节假日与时效校验"
    dimension = "A"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        dd = docs.first("DRAWDOWN_INSTRUCTION")
        if not dd:
            return _skip(self.id, self.name, self.dimension, "缺少提款指令，无法校验。")
        # 节假日判定依赖外部节假日/货币假期日历 → 移交专项审核
        return _handoff(
            self.id, self.name, self.dimension,
            why=f"拟提款日 {_norm(dd.get('drawdown_date')) or '—'}、到期日 {_norm(dd.get('maturity_date')) or '—'} "
                f"是否为中国及 {_norm(dd.get('currency')) or '对应币种'} 节假日，需联网节假日日历判定；提款日不应早于当前日期。",
            suggestion="由专项审核调用节假日日历核验提款日/到期日，并校验期限是否超出 FOL 要求。",
        )


# ================================================================
# B 维度：资金拆分（提款 ↔ 支付）
# ================================================================
@register
class R_RemitterEqualsBorrower(Rule):
    id = "FACILITY_LETTER_VS_PAYMENT__REMITTER"
    name = "借款人 == 支付指令汇款人"
    dimension = "B"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        fol = docs.first("FACILITY_LETTER")
        payments = docs.all("PAYMENT_INSTRUCTION")
        if not fol or not payments:
            return _skip(self.id, self.name, self.dimension, "缺少授信函或支付指令，无法校验。")
        borrower = _norm(fol.get("borrower"))
        mismatched = [p for p in payments if _norm(p.get("remitter_name")) != borrower]
        if not mismatched:
            return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                              why=f"全部 {len(payments)} 笔支付指令汇款人均与借款人“{borrower}”一致。",
                              detail=[["FOL 借款人", borrower, ""], ["支付指令笔数", str(len(payments)), ""]])
        return RuleResult(self.id, self.name, self.dimension, Status.FAIL,
                          why=f"{len(mismatched)} 笔支付指令汇款人与借款人不一致。",
                          suggestion="核实汇款主体，要求更正为借款人本人账户汇出。",
                          detail=[["FOL 借款人", borrower, ""]]
                                 + [[f"{p.get('payee','?')} 汇款人", _norm(p.get("remitter_name")), "bad"]
                                    for p in mismatched])


@register
class R_PaymentSumCoversDrawdown(Rule):
    id = "DRAWDOWN_VS_PAYMENT__AMOUNT"
    name = "支付指令加总 ≥ 提款金额"
    dimension = "B"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        dd = docs.first("DRAWDOWN_INSTRUCTION")
        payments = docs.all("PAYMENT_INSTRUCTION")
        if not dd or not payments:
            return _skip(self.id, self.name, self.dimension, "缺少提款指令或支付指令，无法校验。")
        dd_amt = _dec(dd.get("amount"))
        dd_ccy = _norm(dd.get("currency"))
        pay_ccys = {_norm(p.get("currency")) for p in payments}
        total = sum((_dec(p.get("amount")) for p in payments), Decimal(0))
        same_ccy = pay_ccys == {dd_ccy}
        if not same_ccy:
            # 跨币种需按提款日汇率折算 → 规则引擎做不到，移交专项审核
            return _handoff(
                self.id, self.name, self.dimension,
                why=f"支付指令币种 {'/'.join(sorted(pay_ccys))} 与提款币种 {dd_ccy} 不一致，"
                    f"需按提款日汇率折算后再比较（支付合计 {total:,.2f}，提款 {dd_amt:,.2f}）。",
                suggestion="由专项审核按提款日汇率折算支付合计，确认是否 ≥ 提款金额。",
            )
        if total >= dd_amt:
            return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                              why=f"{len(payments)} 笔支付合计 {total:,.2f} ≥ 提款金额 {dd_amt:,.2f}（同币种）。",
                              detail=[["支付合计", f"{total:,.2f}", ""], ["提款金额", f"{dd_amt:,.2f}", ""]])
        return RuleResult(self.id, self.name, self.dimension, Status.FAIL,
                          why=f"支付合计 {total:,.2f} 小于提款金额 {dd_amt:,.2f}，存在资金缺口 {dd_amt - total:,.2f}。",
                          suggestion="核实支付指令是否齐全，或下调提款金额。",
                          detail=[["支付合计", f"{total:,.2f}", "bad"], ["提款金额", f"{dd_amt:,.2f}", "bad"],
                                  ["缺口", f"{dd_amt - total:,.2f}", "bad"]])


@register
class R_PaymentAccountMatchesDrawdown(Rule):
    id = "DRAWDOWN_VS_PAYMENT__ACCOUNT"
    name = "放款账号 == 支付收款账号"
    dimension = "B"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        dd = docs.first("DRAWDOWN_INSTRUCTION")
        payments = docs.all("PAYMENT_INSTRUCTION")
        if not dd or not payments:
            return _skip(self.id, self.name, self.dimension, "缺少提款指令或支付指令，无法校验。")
        dd_acc = _norm(dd.get("payment_account"))
        if not dd_acc:
            return _skip(self.id, self.name, self.dimension, "提款指令未填放款账号，跳过。")
        pay_accs = [_norm(p.get("payee_account")) for p in payments]
        if dd_acc in pay_accs:
            return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                              why=f"放款账号与支付指令收款账号匹配（{dd_acc}）。",
                              detail=[["放款账号", dd_acc, ""]])
        return RuleResult(self.id, self.name, self.dimension, Status.WARN,
                          why="放款账号与各支付指令收款账号不完全一致，可能为先入借款人账户再对外支付，需人工确认资金路径。",
                          suggestion="确认放款是否直付收款人，或经借款人账户二次支付。",
                          detail=[["放款账号", dd_acc, ""]]
                                 + [[f"{p.get('payee','?')} 收款账号", a, ""] for p, a in zip(payments, pay_accs)])


# ================================================================
# C 维度：贸易背景（支付 ↔ 外部单据：合同/订单/发票/运单/报关）
# ================================================================
@register
class R_SupportingContractNo(Rule):
    id = "SUPPORTING__CONTRACT_NO"
    name = "合同号 / 订单号勾稽一致"
    dimension = "C"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        ct = docs.first("COMMERCIAL_CONTRACT")
        if not ct:
            return _skip(self.id, self.name, self.dimension, "缺少商业合同，无法勾稽。")
        base = _norm(ct.get("contract_no"))
        if not base:
            return _skip(self.id, self.name, self.dimension, "商业合同合同号缺失，无法勾稽。")

        order = docs.first("COMMERCIAL_ORDER")
        invoice_docs = docs.all("PROFORMA_INVOICE")
        candidates = {base}
        order_no = _norm((order or {}).get("order_no"))
        if order_no:
            candidates.add(order_no)
        candidates.update(_norm(item.get("invoice_no")) for item in invoice_docs if _norm(item.get("invoice_no")))

        rows = [_field_row(docs, "COMMERCIAL_CONTRACT", "contract_no", "商业合同 合同号", base)]
        mismatches = []
        missing = []

        for tcode, label in [
            ("COMMERCIAL_ORDER", "商业订单"),
            ("WAYBILL", "运单"),
            ("PROFORMA_INVOICE", "形式发票"),
        ]:
            for idx, doc in enumerate(docs.all(tcode)):
                cn = _norm(doc.get("contract_no"))
                if cn and cn != base:
                    mismatches.append((f"{label} 合同号", cn))
                elif not cn:
                    missing.append(f"{label}合同号")
                rows.append(_field_row(docs, tcode, "contract_no", f"{label} 合同号", cn or "—",
                                       "" if cn == base else "bad", idx))

        if order:
            if not order_no:
                missing.append("商业订单订单号")
            for tcode, label in [("WAYBILL", "运单"), ("PROFORMA_INVOICE", "形式发票")]:
                for idx, doc in enumerate(docs.all(tcode)):
                    ref = _norm(doc.get("order_no"))
                    if ref and order_no and ref != order_no:
                        mismatches.append((f"{label} 订单号", ref))
                    elif ref and not order_no:
                        missing.append("商业订单订单号")
                    elif not ref:
                        missing.append(f"{label}订单号")
                    rows.append(_field_row(docs, tcode, "order_no", f"{label} 订单号", ref or "—",
                                           "" if ref == order_no and order_no else "bad", idx))
        elif any(_norm(doc.get("order_no")) for tcode in ("WAYBILL", "PROFORMA_INVOICE") for doc in docs.all(tcode)):
            missing.append("商业订单（用于核对单据订单号）")

        for idx, doc in enumerate(docs.all("CUSTOMS_DECLARATION")):
            protocol_no = _norm(doc.get("contract_no"))
            if protocol_no and protocol_no not in candidates:
                mismatches.append(("报关单 协议号", protocol_no))
            elif not protocol_no:
                missing.append("报关单协议号")
            rows.append(_field_row(docs, "CUSTOMS_DECLARATION", "contract_no", "报关单 协议号",
                                   protocol_no or "—", "" if protocol_no in candidates and protocol_no else "bad", idx))

        if mismatches:
            return RuleResult(self.id, self.name, self.dimension, Status.FAIL,
                              why="支持性文件合同/订单编号与对应主单不一致，贸易背景勾稽存在断点。",
                              suggestion="核实合同号、订单号及报关协议号是否指向同一笔贸易；报关协议号可按规则与合同号、订单号或形式发票号关联。",
                              detail=rows)
        if missing:
            return RuleResult(self.id, self.name, self.dimension, Status.WARN,
                              why=f"编号字段或对应订单缺失，无法完成全部勾稽：{'、'.join(dict.fromkeys(missing))}。",
                              suggestion="审核人查看原文并确认缺失字段是否适用；必要时补件。", detail=rows)
        return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                          why=f"合同号、可用订单号及报关协议号均按允许关联关系勾稽一致。", detail=rows)


@register
class R_SupportingBillOfLading(Rule):
    id = "SUPPORTING__BILL_OF_LADING_NO"
    name = "提单号相符（运单 == 报关单）"
    dimension = "C"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        wb = docs.first("WAYBILL")
        cd = docs.first("CUSTOMS_DECLARATION")
        if not wb or not cd:
            return _skip(self.id, self.name, self.dimension, "缺少运单或报关单，无法校验提单号。")
        wb_bl = _norm(wb.get("bill_of_lading_no"))
        cd_bl = _norm(cd.get("bill_of_lading_no"))
        if not wb_bl or wb_bl != cd_bl:
            return RuleResult(self.id, self.name, self.dimension, Status.FAIL,
                              why=f"运单提单号“{wb_bl}”与报关单“{cd_bl}”不一致。",
                              suggestion="核实提单号，并做真伪验证（海关网站/船公司/FIATA）。",
                              detail=[
                                  _field_row(docs, "WAYBILL", "bill_of_lading_no", "运单 提单号", wb_bl, "bad"),
                                  _field_row(docs, "CUSTOMS_DECLARATION", "bill_of_lading_no", "报关单 提单号", cd_bl, "bad"),
                              ])
        # 号码一致（硬核对通过）；真伪验证依赖海关/船司/FIATA → 移交专项审核
        return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                          why=f"运单与报关单提单号一致（{wb_bl}）；提单真伪由专项审核联网核验。",
                          detail=[
                              _field_row(docs, "WAYBILL", "bill_of_lading_no", "运单 提单号", wb_bl),
                              _field_row(docs, "CUSTOMS_DECLARATION", "bill_of_lading_no", "报关单 提单号", cd_bl),
                          ])


@register
class R_SupportingGoods(Rule):
    id = "SUPPORTING__GOODS_OR_SERVICE"
    name = "采购标的物各单据一致"
    dimension = "C"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        goods: list[tuple[str, str]] = []
        for tcode, label in [("COMMERCIAL_CONTRACT", "商业合同"), ("COMMERCIAL_ORDER", "商业订单"),
                             ("PROFORMA_INVOICE", "形式发票"), ("WAYBILL", "运单"),
                             ("CUSTOMS_DECLARATION", "报关单")]:
            for doc in docs.all(tcode):
                g = _norm(doc.get("goods_or_service"))
                if g:
                    goods.append((label, g))
        if len(goods) < 2:
            return _skip(self.id, self.name, self.dimension, "标的物信息不足，无法比对。")
        base = goods[0][1]
        mismatched = [(lab, g) for lab, g in goods if base not in g and g not in base]
        rows = [[lab, g, "bad" if (lab, g) in mismatched else ""] for lab, g in goods]
        if mismatched:
            return RuleResult(self.id, self.name, self.dimension, Status.FAIL,
                              why="各单据采购标的物描述不一致，贸易真实性存疑。",
                              suggestion="核实标的物，须在合同→订单→发票→运单→报关单间保持一致（允许包含关系）。",
                              detail=rows)
        return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                          why=f"各单据采购标的物一致（{base}）；跨语种/监管受限品名由专项审核翻译研判。", detail=rows)


@register
class R_SupportingAmountChain(Rule):
    id = "SUPPORTING__AMOUNT"
    name = "金额链：支付 ≤ 发票 ≤ 订单 ≤ 合同"
    dimension = "C"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        ct_doc = docs.first("COMMERCIAL_CONTRACT")
        po_doc = docs.first("COMMERCIAL_ORDER")
        invoice_docs = docs.all("PROFORMA_INVOICE")
        customs_docs = docs.all("CUSTOMS_DECLARATION")
        waybill_docs = docs.all("WAYBILL")
        ct = _dec((ct_doc or {}).get("amount"))
        po = _dec((po_doc or {}).get("amount"))
        iv = sum((_dec(item.get("amount")) for item in invoice_docs), Decimal(0))
        payments = docs.all("PAYMENT_INSTRUCTION")
        pay = sum((_dec(p.get("amount")) for p in payments), Decimal(0)) if payments else Decimal(0)
        if not (ct or po or iv) and payments:
            return _skip(self.id, self.name, self.dimension, "缺少合同/订单/发票金额，无法校验金额链。")
        rows = []
        if ct_doc is not None:
            rows.append(_field_row(docs, "COMMERCIAL_CONTRACT", "amount", "商业合同金额",
                                   _norm(ct_doc.get("amount")) or "—"))
        if po_doc is not None:
            rows.append(_field_row(docs, "COMMERCIAL_ORDER", "amount", "商业订单金额",
                                   _norm(po_doc.get("amount")) or "—"))
        for idx, item in enumerate(invoice_docs):
            rows.append(_field_row(docs, "PROFORMA_INVOICE", "amount", f"形式发票金额 {idx + 1}",
                                   _norm(item.get("amount")) or "—", idx=idx))
        for idx, item in enumerate(customs_docs):
            rows.append(_field_row(docs, "CUSTOMS_DECLARATION", "amount", f"报关金额 {idx + 1}",
                                   _norm(item.get("amount")) or "—", idx=idx))
        for idx, item in enumerate(waybill_docs):
            rows.append(_field_row(docs, "WAYBILL", "amount", f"运单金额 {idx + 1}",
                                   _norm(item.get("amount")) or "—", idx=idx))
        for idx, item in enumerate(payments):
            rows.append(_field_row(docs, "PAYMENT_INSTRUCTION", "amount", f"支付金额 {idx + 1}",
                                   _norm(item.get("amount")) or "—", idx=idx))
        missing = []
        for doc, label in [(ct_doc, "商业合同金额"), (po_doc, "商业订单金额")]:
            if doc is not None and not doc.get("amount"):
                missing.append(label)
        if invoice_docs and any(not item.get("amount") for item in invoice_docs):
            missing.append("形式发票金额")
        if customs_docs and any(not item.get("amount") for item in customs_docs):
            missing.append("报关金额")
        if waybill_docs and any(not item.get("amount") for item in waybill_docs):
            missing.append("运单金额")
        if payments and any(not item.get("amount") for item in payments):
            missing.append("支付金额")
        if not payments:
            missing.append("支付指令（必需文件）")
        chain = [("合同金额", ct), ("订单金额", po), ("发票金额", iv), ("支付合计", pay)]
        present = [(lab, v) for lab, v in chain if v > 0]
        bad = any(present[i][1] < present[i + 1][1] for i in range(len(present) - 1))
        rows.extend([[lab, f"{v:,.2f}", "bad" if bad else "", None] for lab, v in present])
        if bad:
            return RuleResult(self.id, self.name, self.dimension, Status.FAIL,
                              why="金额链出现下游大于上游的情况（应满足 合同 ≥ 订单 ≥ 发票 ≥ 支付）。",
                              suggestion="核实各单据金额，排查超付/拆单异常。", detail=rows)
        if missing:
            reason_prefix = "缺少必需支付指令；" if not payments else ""
            return RuleResult(self.id, self.name, self.dimension, Status.WARN,
                              why=f"{reason_prefix}金额字段或必需文件不完整，不能判定金额链：{'、'.join(missing)}。",
                              suggestion="补交缺失单据并核实原文金额与币种；有分货或多单据时按货品和编号拆分后复核。",
                              detail=rows)
        return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                          why="金额链满足 合同 ≥ 订单 ≥ 发票 ≥ 支付。", detail=rows)


@register
class R_SupportingQuantity(Rule):
    id = "SUPPORTING__QUANTITY"
    name = "发票数量 ≤ 订单/合同数量"
    dimension = "C"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        iv = docs.first("PROFORMA_INVOICE")
        if not iv:
            return _skip(self.id, self.name, self.dimension, "缺少形式发票，无法校验数量。")
        iv_q = _num(iv.get("quantity"))
        if iv_q <= 0:
            return _skip(self.id, self.name, self.dimension, "发票数量缺失，跳过。")
        rows = [["发票数量", _norm(iv.get("quantity")), ""]]
        bad = False
        for tcode, label in [("COMMERCIAL_ORDER", "订单数量"), ("COMMERCIAL_CONTRACT", "合同数量"),
                             ("CUSTOMS_DECLARATION", "报关数量"), ("WAYBILL", "运单数量")]:
            doc = docs.first(tcode)
            if doc and doc.get("quantity"):
                q = _num(doc.get("quantity"))
                ok = iv_q <= q
                bad = bad or not ok
                rows.append([label, _norm(doc.get("quantity")), "" if ok else "bad"])
        if bad:
            return RuleResult(self.id, self.name, self.dimension, Status.FAIL,
                              why="形式发票数量超过订单/合同/报关/运单数量，存在超量开票。",
                              suggestion="核实货物数量一致性。", detail=rows)
        return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                          why="形式发票数量未超过上游单据数量。", detail=rows)


@register
class R_SupportingUnitPrice(Rule):
    id = "SUPPORTING__UNIT_PRICE"
    name = "发票单价 == 报关/订单/合同单价"
    dimension = "C"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        iv = docs.first("PROFORMA_INVOICE")
        if not iv or not iv.get("unit_price"):
            return _skip(self.id, self.name, self.dimension, "缺少发票单价，无法校验。")
        iv_p = _num(iv.get("unit_price"))
        rows = [["发票单价", _norm(iv.get("unit_price")), ""]]
        bad = False
        for tcode, label in [("CUSTOMS_DECLARATION", "报关单价"), ("COMMERCIAL_ORDER", "订单单价"),
                             ("COMMERCIAL_CONTRACT", "合同单价")]:
            doc = docs.first(tcode)
            if doc and doc.get("unit_price"):
                p = _num(doc.get("unit_price"))
                ok = iv_p == p
                bad = bad or not ok
                rows.append([label, _norm(doc.get("unit_price")), "" if ok else "bad"])
        if len(rows) == 1:
            return _skip(self.id, self.name, self.dimension, "无可比对的单价字段，跳过。")
        if bad:
            return RuleResult(self.id, self.name, self.dimension, Status.WARN,
                              why="发票单价与报关/订单/合同单价存在差异，若无浮动价条款需人工确认。",
                              suggestion="确认是否存在浮动价条款或含税/不含税差异。", detail=rows)
        return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                          why="发票单价与上游单据单价一致。", detail=rows)


@register
class R_SupportingDate(Rule):
    id = "SUPPORTING__DATE_AND_TERM"
    name = "日期逻辑：合同最早 / 付款不晚于提款"
    dimension = "C"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        ct = docs.first("COMMERCIAL_CONTRACT")
        if not ct or not _d(ct.get("date")):
            return _skip(self.id, self.name, self.dimension, "缺少合同日期，无法校验日期逻辑。")
        ct_date = _d(ct.get("date"))
        rows = [["合同日期", _norm(ct.get("date")), ""]]
        bad = False
        for tcode, label, key in [("COMMERCIAL_ORDER", "订单日期", "date"),
                                  ("PROFORMA_INVOICE", "发票日期", "date"),
                                  ("WAYBILL", "装运日", "shipment_date"),
                                  ("CUSTOMS_DECLARATION", "申报日期", "date")]:
            doc = docs.first(tcode)
            if doc and _d(doc.get(key)):
                dt = _d(doc.get(key))
                ok = dt >= ct_date
                bad = bad or not ok
                rows.append([label, _norm(doc.get(key)), "" if ok else "bad"])
        dd = docs.first("DRAWDOWN_INSTRUCTION")
        dd_date = _d(dd.get("drawdown_date")) if dd else None
        if dd_date:
            rows.append(["提款日", _norm(dd.get("drawdown_date")), ""])
            for p in docs.all("PAYMENT_INSTRUCTION"):
                pd = _d(p.get("payment_date"))
                if pd and pd > dd_date:
                    bad = True
                    rows.append([f"{p.get('payee','?')} 付款日", _norm(p.get("payment_date")), "bad"])
        if bad:
            return RuleResult(self.id, self.name, self.dimension, Status.FAIL,
                              why="单据日期逻辑异常（合同应最早，支付日不应晚于提款日）。",
                              suggestion="核实各单据日期先后关系。", detail=rows)
        return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                          why="单据日期逻辑正常：合同日期最早，支付日不晚于提款日。", detail=rows)


@register
class R_SupportingSeller(Rule):
    id = "SUPPORTING__SELLER"
    name = "卖方一致且 == 支付收款人"
    dimension = "C"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        sellers: list[tuple[str, str, str]] = []
        for tcode, label in [("COMMERCIAL_CONTRACT", "合同卖方"), ("COMMERCIAL_ORDER", "订单卖方"),
                             ("PROFORMA_INVOICE", "发票卖方"), ("WAYBILL", "运单发货方")]:
            doc = docs.first(tcode)
            if doc and doc.get("seller"):
                sellers.append((label, _norm(doc.get("seller")), tcode))
        if not sellers:
            return _skip(self.id, self.name, self.dimension, "缺少卖方信息，无法校验。")
        base = sellers[0][1]
        rows = [_field_row(docs, tcode, "seller", label, seller, "" if seller == base else "bad")
                for label, seller, tcode in sellers]
        seller_bad = any(seller != base for _, seller, _ in sellers)
        payees = [_norm(p.get("payee")) for p in docs.all("PAYMENT_INSTRUCTION")]
        payee_bad = bool(payees) and base not in payees
        for idx, payee in enumerate(payees):
            rows.append(_field_row(docs, "PAYMENT_INSTRUCTION", "payee", "支付收款人", payee,
                                   "" if payee == base else "", idx))
        if seller_bad:
            return RuleResult(self.id, self.name, self.dimension, Status.FAIL,
                              why="各单据卖方不一致，贸易对手存在矛盾。",
                              suggestion="核实卖方主体一致性。", detail=rows)
        if payee_bad:
            return RuleResult(self.id, self.name, self.dimension, Status.WARN,
                              why=f"卖方“{base}”与支付收款人不完全匹配，需人工确认收款主体。",
                              suggestion="确认收款人是否为贸易卖方。", detail=rows)
        return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                          why=f"卖方一致（{base}）且与支付收款人相符；是否为借款人关联方由专项审核研判。", detail=rows)


@register
class R_SupportingBuyer(Rule):
    id = "SUPPORTING__BUYER"
    name = "买方一致且 == 借款人"
    dimension = "C"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        fol = docs.first("FACILITY_LETTER")
        borrower = _norm(fol.get("borrower")) if fol else ""
        buyers: list[tuple[str, str, str]] = []
        for tcode, label in [("COMMERCIAL_CONTRACT", "合同买方"), ("COMMERCIAL_ORDER", "订单买方"),
                             ("PROFORMA_INVOICE", "发票买方"), ("WAYBILL", "运单收货方")]:
            doc = docs.first(tcode)
            if doc and doc.get("buyer"):
                buyers.append((label, _norm(doc.get("buyer")), tcode))
        if not buyers:
            return _skip(self.id, self.name, self.dimension, "缺少买方信息，无法校验。")
        rows = [_field_row(docs, "FACILITY_LETTER", "borrower", "FOL 借款人", borrower)] if borrower else []
        names_differ = len({buyer for _, buyer, _ in buyers}) > 1
        for label, buyer, tcode in buyers:
            ok = not borrower or buyer == borrower
            rows.append(_field_row(docs, tcode, "buyer", label, buyer, "" if ok else "bad"))
        if names_differ:
            return RuleResult(self.id, self.name, self.dimension, Status.FAIL,
                              why="商业合同、订单、发票或运单之间的买方/收货方名称不一致。",
                              suggestion="核对同一笔贸易下买方、收货人及服务接收方的原文名称。", detail=rows)
        if not borrower:
            return RuleResult(self.id, self.name, self.dimension, Status.WARN,
                              why="缺少可比对的借款人名称，无法判断买方/收货方与借款人的关系。",
                              suggestion="核对授信函借款人字段；字段梳理工作簿与 V2 对该关系存在表述冲突。", detail=rows)
        if any(buyer != borrower for _, buyer, _ in buyers):
            return RuleResult(self.id, self.name, self.dimension, Status.WARN,
                              why="单据买方/收货方与借款人名称不一致，但 V2 与字段梳理表的该项口径存在冲突，转人工和 AI 参考。",
                              suggestion="查阅冲突原文并结合交易关系核实；不得由 AI 自动放行或自动判退。", detail=rows)
        return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                          why=f"各单据买方一致且与借款人“{borrower}”相符。", detail=rows)


@register
class R_SupportingPayeeAccount(Rule):
    id = "SUPPORTING__PAYEE_ACCOUNT"
    name = "支付收款账号 == 合同/订单约定账号"
    dimension = "C"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        payments = docs.all("PAYMENT_INSTRUCTION")
        if not payments:
            return _skip(self.id, self.name, self.dimension, "缺少支付指令，无法校验。")
        ct = docs.first("COMMERCIAL_CONTRACT") or {}
        po = docs.first("COMMERCIAL_ORDER") or {}
        agreed = _norm(ct.get("payee_account")) or _norm(po.get("payee_account"))
        if not agreed:
            return _skip(self.id, self.name, self.dimension, "合同/订单未提供收款账号信息，跳过。")
        pay_accs = [_norm(p.get("payee_account")) for p in payments]
        bad = [a for a in pay_accs if a != agreed]
        rows = [["合同/订单约定账号", agreed, ""]] + \
               [[f"{p.get('payee','?')} 收款账号", a, "" if a == agreed else "bad"]
                for p, a in zip(payments, pay_accs)]
        if bad:
            return RuleResult(self.id, self.name, self.dimension, Status.FAIL,
                              why="支付指令收款账号与合同/订单约定账号不一致。",
                              suggestion="核实收款账号，须与贸易合同约定一致。", detail=rows)
        return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                          why="支付收款账号与合同/订单约定账号一致。", detail=rows)


@register
class R_SupportingPaymentMethod(Rule):
    id = "SUPPORTING__PAYMENT_METHOD"
    name = "支付方式为转账/TT/现金"
    dimension = "C"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        ct = docs.first("COMMERCIAL_CONTRACT") or {}
        po = docs.first("COMMERCIAL_ORDER") or {}
        method = _norm(ct.get("payment_method")) or _norm(po.get("payment_method"))
        if not method:
            return _skip(self.id, self.name, self.dimension, "合同/订单未明确支付方式，跳过。")
        allowed = ["转账", "TT", "T/T", "现金"]
        if any(a.lower() in method.lower() for a in allowed):
            return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                              why=f"合同约定支付方式“{method}”属允许范围（转账/TT/现金）。",
                              detail=[["支付方式", method, ""]])
        return RuleResult(self.id, self.name, self.dimension, Status.WARN,
                          why=f"合同约定支付方式“{method}”不属常规转账/TT/现金，需人工确认。",
                          suggestion="确认支付方式合规性。", detail=[["支付方式", method, "bad"]])


# ================================================================
# E 维度：合规与制裁（制裁名单/法规检索依赖外部库 → 移交专项审核）
# ================================================================
@register
class R_FundFlowCountry(Rule):
    id = "SUPPORTING__FUND_FLOW"
    name = "收款行国别 == 启运国"
    dimension = "E"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        payments = docs.all("PAYMENT_INSTRUCTION")
        if not payments:
            return _skip(self.id, self.name, self.dimension, "缺少支付指令，无法校验资金流向。")
        wb = docs.first("WAYBILL")
        cd = docs.first("CUSTOMS_DECLARATION")
        departure = _norm((wb or {}).get("country_of_departure")) or _norm((cd or {}).get("country_of_departure"))
        rows = []
        mismatch = []
        for p in payments:
            c = _norm(p.get("payee_bank_country"))
            ok = (not departure) or c == departure
            rows.append([f"{p.get('payee','?')} 收款行国", c, "" if ok else "bad"])
            if departure and c and c != departure:
                mismatch.append((p.get("payee", "?"), c))
        if departure:
            rows.append(["启运国", departure, ""])
        if mismatch:
            # 国别不一致→硬核对可判异常；但"是否制裁国/三角贸易合规"需名单库→专项审核补充
            return RuleResult(self.id, self.name, self.dimension, Status.FAIL,
                              why="部分收款行所在国与货物启运国不一致，存在三角贸易/转手风险。",
                              suggestion="核实资金流向与启运国匹配；制裁名单筛查由专项审核完成。", detail=rows)
        return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                          why=f"收款行所在国与启运国一致（{departure or '—'}）；制裁名单筛查由专项审核完成。", detail=rows)


@register
class R_SanctionScreening(Rule):
    id = "COMPLIANCE__SANCTION_SCREENING"
    name = "制裁名单 / 反洗钱筛查"
    dimension = "E"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        payments = docs.all("PAYMENT_INSTRUCTION")
        fol = docs.first("FACILITY_LETTER")
        if not payments and not fol:
            return _skip(self.id, self.name, self.dimension, "缺少可筛查主体，跳过。")
        parties = []
        for p in payments:
            if p.get("payee"):
                parties.append(_norm(p.get("payee")))
            if p.get("payee_bank_country"):
                parties.append(_norm(p.get("payee_bank_country")))
        return _handoff(
            self.id, self.name, self.dimension,
            why=f"收款人/收款行国家（{'、'.join(dict.fromkeys(parties)) or '—'}）需对照制裁与反洗钱名单实时筛查，规则引擎无法下定论。",
            suggestion="由专项审核调用制裁/反洗钱名单库核验相关主体与国家。",
        )


@register
class R_RegulationCheck(Rule):
    id = "COMPLIANCE__REGULATION"
    name = "标的物监管/法规符合性"
    dimension = "E"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        goods = _norm((docs.first("COMMERCIAL_CONTRACT") or {}).get("goods_or_service")) \
            or _norm((docs.first("PROFORMA_INVOICE") or {}).get("goods_or_service"))
        if not goods:
            return _skip(self.id, self.name, self.dimension, "缺少标的物信息，跳过。")
        return _handoff(
            self.id, self.name, self.dimension,
            why=f"采购标的物“{goods}”是否涉及进出口监管/许可或禁止领域，需检索法规库（如北大法宝）判定。",
            suggestion="由专项审核检索法规库，确认标的物监管与许可要求。",
        )


# ================================================================
# F 维度：形式与完整性
# ================================================================
@register
class R_PaymentAmountInWords(Rule):
    id = "PAYMENT__AMOUNT_IN_WORDS"
    name = "支付指令金额大写完整"
    dimension = "F"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        payments = docs.all("PAYMENT_INSTRUCTION")
        if not payments:
            return _skip(self.id, self.name, self.dimension, "缺少支付指令，无法校验。")
        missing = [p for p in payments if not _norm(p.get("amount_in_words"))]
        if not missing:
            return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                              why="各支付指令均已填写金额大写。")
        return RuleResult(self.id, self.name, self.dimension, Status.WARN,
                          why=f"{len(missing)} 笔支付指令金额大写为空或识别不全，需人工补充核对。",
                          suggestion="补齐金额大写并与小写金额核对一致。",
                          detail=[[f"{p.get('payee','?')}", "大写缺失", "bad"] for p in missing])


@register
class R_DrawdownPaymentAccountFormat(Rule):
    id = "DRAWDOWN__PAYMENT_ACCOUNT"
    name = "放款账号格式合法（12 位）"
    dimension = "F"
    _pat = re.compile(r"^(\d{3}-\d{6}-\d{3}|\d{12})$")

    def evaluate(self, docs: DocBundle) -> RuleResult:
        dd = docs.first("DRAWDOWN_INSTRUCTION")
        if not dd:
            return _skip(self.id, self.name, self.dimension, "缺少提款指令，无法校验。")
        acc = _norm(dd.get("payment_account"))
        if not acc:
            return RuleResult(self.id, self.name, self.dimension, Status.FAIL,
                              why="放款账号为空。", suggestion="补填我行 12 位放款账号。")
        if self._pat.match(acc):
            return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                              why=f"放款账号“{acc}”符合 12 位格式（xxx-xxxxxx-xxx 或 xxxxxxxxxxxx）。",
                              detail=[["放款账号", acc, ""]])
        return RuleResult(self.id, self.name, self.dimension, Status.FAIL,
                          why=f"放款账号“{acc}”不符合我行 12 位账号格式。",
                          suggestion="核对账号格式：xxx-xxxxxx-xxx 或 12 位纯数字。",
                          detail=[["放款账号", acc, "bad"]])


@register
class R_SupportingValidity(Rule):
    id = "SUPPORTING__VALIDITY"
    name = "合同/发票盖章签字有效性"
    dimension = "F"

    def evaluate(self, docs: DocBundle) -> RuleResult:
        checked = []
        missing = []
        for tcode, label in [("COMMERCIAL_CONTRACT", "商业合同"), ("COMMERCIAL_ORDER", "商业订单"),
                             ("PROFORMA_INVOICE", "形式发票")]:
            doc = docs.first(tcode)
            if doc is not None:
                v = doc.get("validity_seal_signature")
                checked.append(label)
                if v in (None, "", False, "否", "缺失", "无"):
                    missing.append(label)
        if not checked:
            return _skip(self.id, self.name, self.dimension, "无合同/订单/发票，无法校验有效性。")
        if missing:
            return RuleResult(self.id, self.name, self.dimension, Status.WARN,
                              why=f"{'、'.join(missing)} 的盖章/签字有效性未识别到，需人工核验。",
                              suggestion="核验合同/发票盖章签字是否齐备、是否过期失效。",
                              detail=[[m, "盖章签字待确认", "bad"] for m in missing])
        return RuleResult(self.id, self.name, self.dimension, Status.PASS,
                          why=f"{'、'.join(checked)} 盖章签字齐备。")
