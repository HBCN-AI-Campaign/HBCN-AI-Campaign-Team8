"""Versioned business vocabulary. Keys preserve the existing rule-engine contract."""
SCHEMA_VERSION = "loan-fields/1.3"
TYPE_LABELS = {
    "FACILITY_LETTER": "授信函 / 贷款合同 (FOL)",
    "DRAWDOWN_INSTRUCTION": "授信使用申请书（提款指令）",
    "PAYMENT_INSTRUCTION": "支付指令（境外汇款申请书）",
    "COMMERCIAL_CONTRACT": "商业合同", "COMMERCIAL_ORDER": "商业订单",
    "WAYBILL": "运单 / 提单", "CUSTOMS_DECLARATION": "报关单",
    "PROFORMA_INVOICE": "形式发票",
}
HINTS = [
    (("贷款合同", "授信函", "facility", "fol"), "FACILITY_LETTER"),
    (("授信请求", "提款", "使用申请", "drawdown", "utilization"), "DRAWDOWN_INSTRUCTION"),
    (("支付", "汇款", "payment", "remittance"), "PAYMENT_INSTRUCTION"),
    (("商务合同", "商业合同", "contract"), "COMMERCIAL_CONTRACT"),
    (("订单", "order"), "COMMERCIAL_ORDER"),
    (("运单", "提单", "waybill", "lading"), "WAYBILL"),
    (("报关", "customs"), "CUSTOMS_DECLARATION"),
    (("发票", "invoice", "proforma"), "PROFORMA_INVOICE"),
]


def guess_type(filename: str) -> str | None:
    return next((code for names, code in HINTS if any(n in filename.lower() for n in names)), None)


def spec(key, label, data_type="text", aliases=(), required=False, visual=False, note="", choices=None):
    result=dict(key=key, label=label, data_type=data_type, aliases=list(aliases),
                required=required, visual=visual, note=note)
    if choices is not None:result['choices']=choices
    return result


B = spec("borrower", "借款人", aliases=("借款人", "Borrower"), required=True,
         note="FOL正文法律主体，不能把封面Customer Name、担保人、集团其他成员直接当作借款人；多个适用借款人未明确时置空。")
C = spec("currency", "币种", "currency_code", ("币种", "Currency", "汇款币种"), True)
A = spec("amount", "金额", "money", ("金额", "Amount", "总金额", "总价", "数额", "金额数额"), True,
         note="本单据总金额；不得选单价、授信额度、税额或其他文件金额。保留精确十进制。")
D = spec("date", "单据日期", "date", ("日期", "Date", "签约日期", "申报日期"))
CN = spec("contract_no", "合同号", aliases=("合同号", "合同编号", "合同协议号", "Contract No", "Contract Number"))
ON = spec("order_no", "订单号", aliases=("订单号", "Order No", "Purchase Order"))
GOODS = spec("goods_or_service", "标的货物/服务", aliases=("货物", "品名", "Description of Goods"))
SELLER = spec("seller", "卖方/发货人", aliases=("卖方", "销售方", "服务提供方", "Seller", "Shipper"))
BUYER = spec("buyer", "买方/收货人", aliases=("买方", "收货方", "服务接收方", "Buyer", "Consignee"))
QTY = spec("quantity", "数量", "decimal", ("数量", "Quantity"), note="货品多行时不得只取第一行；返回line_items并把汇总依据明确，单位不同不可相加。")
UNIT = spec("unit_price", "单价", "decimal", ("单价", "Unit Price"), note="明确计价单位、含税口径。只有一行实际商品时提取该行单价；G-TOTAL/TOTAL合计不是商品行，不能因存在合计就拒绝单行单价。多商品不同单价时置空并保留line_items，不取平均。")
QTY['measurement']='quantity'
UNIT['measurement']='unit_price'
QUNIT=spec('quantity_unit','数量单位','unit',note='与quantity对应的原始单位；MT/公吨/吨→MT，千克/kg→kg，卷→COILS。不得根据金额或其他文件反推。')
PUNIT=spec('price_unit','计价单位','unit',note='本字段定义为商品行Unit Price对应的数量分母单位。原件明确写元/吨等时直接取；同一商品行数量列有单位且与单价列关联清晰时，可按本表行列关系取数量单位，证据须同时包含数量单位及单价列表头/对应行。这不是通过金额计算反推。raw_value只取原件真实单位词，例如MT/千克，不拼接原件不存在的CNY/MT。单位或行列关系不明则置空，不借其他文件单位。')
WAYQTY=dict(QTY,note='用于货物比对的净数量，重量货物取Net Weight净重，不取Gross Weight毛重或卷/件数；件数单独放package_count。多个不同单位不汇总。')
ITEMS = spec("line_items", "货物明细", "rows", visual=True,
             note="逐行保留description/quantity/unit/unit_price/amount/currency/tax_basis；不能把页脚合计并入商品行。每行附block_ids。")
COUNTRY = spec("country_of_departure", "启运国", aliases=("启运国", "Country of Departure"))
PAYCOUNTRY = spec("payee_bank_country", "收款行国家", aliases=("收款行国家", "Beneficiary Bank Country"))
FIELDS = {
    "FACILITY_LETTER": [B, spec("lender_branch", "贷款人分行", aliases=("贷款人", "Lender")),
        spec("facility", "授信品种", required=True), spec("facility_amount", "授信额度", "money", required=True),
        spec("allowed_currencies", "允许币种", "list", required=True), spec("utilization_currency", "可提用币种"),
        spec("term", "授信期限"), spec("purpose", "资金用途范围"), spec("date", "授信函日期", "date"),
        spec("tranches", "授信段明细", "rows", visual=True,
             note="按授信段保留额度/币种/用途/期限/利率/受托支付门槛及block_ids；有多个适用段时汇总标量置空，不跨段拼接。")],
    "DRAWDOWN_INSTRUCTION": [B, spec("date", "申请日期", "date", ("日期", "Date")),
        spec("lender_branch", "贷款人分行"), spec("facility_letter_date", "授信函日期", "date"), C, A,
        spec("tranche", "拟使用授信段"), spec("facility", "拟使用授信", required=True),
        spec("drawdown_date", "拟提款日", "date", ("拟授信使用日", "拟提款日", "Proposed Utilization Date"), True),
        spec("maturity_date", "到期日", "date", ("到期日", "Maturity Date"), True),
        spec("interest_period", "利息期", visual=True,
             choices={"1个月":["1 month"],"2个月":["2 months"],"3个月":["3 months"],"6个月":["6 months"]}), spec("interest_rate", "贷款利率", visual=True),
        spec("purpose", "提款用途", required=True, visual=True),
        spec("payment_account", "放款账号", "account", ("放款账号", "放款指示", "Payment Instructions"), True),
        spec("disbursement_method", "放款方式", required=True, visual=True,
             choices={"银行受托支付":["Bank entrusted payment"],"借款人自主支付":["Borrower autonomous payment"]},
             note="勾选、叉号、划线删除必须结合填表说明及同组选项判断；叉号不恒等于否，横线不恒等于未选，不确定置空。")],
    "PAYMENT_INSTRUCTION": [C, A, spec("amount_in_words", "金额大写"),
        spec("payee", "收款人", required=True), spec("payee_account", "收款账号", "account", required=True),
        spec("payment_account", "汇款人账号", "account"), spec("remitter_name", "汇款人", required=True),
        PAYCOUNTRY, spec("payment_date", "付款日期", "date"), spec("purpose", "汇款附言")],
    "COMMERCIAL_CONTRACT": [CN, GOODS, D, SELLER, BUYER, A, C, QTY, QUNIT, UNIT, PUNIT, ITEMS,
        spec("payment_terms", "付款条款", aliases=("Payment", "Payment Terms", "Terms of Payment")), spec("payee_account", "收款账号", "account"), PAYCOUNTRY],
    "COMMERCIAL_ORDER": [ON, CN, GOODS, D, SELLER, BUYER, A, C, QTY, QUNIT, UNIT, PUNIT, ITEMS],
    "WAYBILL": [CN, ON, spec("bill_of_lading_no", "提单号"), GOODS,
        spec("shipment_date", "装运日", "date"), SELLER, BUYER, COUNTRY, WAYQTY, QUNIT,
        dict(QTY,key='net_weight',label='净重',aliases=['Net Weight','TOTAL NET WEIGHT'],note='仅Net Weight净重，单位放weight_unit。'),
        dict(QTY,key='gross_weight',label='毛重',aliases=['Gross Weight','TOTAL GROSS WEIGHT'],note='仅Gross Weight毛重，单位放weight_unit。'),
        spec('weight_unit','重量单位','unit'),
        dict(QTY,key='package_count',label='包装件数',aliases=['TOTAL NO OF COILS','No of Packages','Package Count'],note='只取卷/件/包装数量，不取净重毛重。'),
        spec('package_unit','包装单位','unit'), ITEMS],
    "CUSTOMS_DECLARATION": [CN, spec("bill_of_lading_no", "提单号"),
        spec("proforma_invoice_no", "形式发票号"), GOODS, D, A, C, QTY, QUNIT, UNIT, PUNIT, COUNTRY, ITEMS],
    "PROFORMA_INVOICE": [spec("invoice_no", "发票号"), CN, ON, GOODS, D, SELLER, BUYER, A, C,
        QTY, QUNIT, UNIT, PUNIT, ITEMS, PAYCOUNTRY, spec("payment_terms", "付款条款", aliases=("Payment", "Payment Terms", "Terms of Payment"))],
}
