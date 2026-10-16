import pytest

from sales_pipeline.config import Settings
from sales_pipeline.models import Attachment, EmailMessage, EmailThread

# Same layout as the internal order-form emails (headers, then the value row);
# names, customer and amounts are made up.
FORM_BODY = (
    "年月日 报价号 包裹类型 备注 产品/定制/服务 目录号 业务类别 产品名称 Qty PO 产品报价 S H Dry Ice "
    "5%信用卡手续费 sales 销售人员 销售指导岗 销售助手 供货指导岗 供货助手 供货人员 查货人员 跟单人员 收账 "
    "询价类别 新客户/老客户/分销商 五级业务代码 五级姓名 引荐客户的部门/人员 是否大项目上报订单 "
    "基建3年内新业务/新供货商1年内订单 新业务类别/发现人/基建人 是否实验室订单 客户类型 是否提供免税证明 "
    "2026/10/2 CBSRX09242501B-2 服务 Custom PFAS Analysis in Serum Samples 1*1 无 $12,500.00 $0.00 "
    "$0.00 $0.00 $0.00 $12,500.00 王小明 无 无 无 无 李四 无 赵六 孙七 B 老客户 BS01 周八 否 否 FALSE I N/A "
    "客户样品已到美国办。\n空白对照的数量，待供货商确认。"
)

REPLY_BODY = "先稍等发预付invoice\nformal quote 见附件\nJane Doe\njane.doe@acme-health.com\n"


@pytest.fixture
def settings(tmp_path):
    s = Settings()
    s.db_path = str(tmp_path / "t.db")
    s.use_llm = False
    s.skip_weekends = False      # dates in tests are exact; weekends have their own test
    return s


@pytest.fixture
def order_thread():
    return EmailThread(
        id="t1",
        subject="Order_CBSRX09242501B-2",
        url="https://mail.google.com/mail/u/0/#all/t1",
        messages=[
            EmailMessage("m1", "sales.rep@pr-abacebiology.com", ["xinyan.zhang@creative-biostructure.com"], [],
                         "Order_CBSRX09242501B-2", "2026-10-02T23:25:09Z", FORM_BODY),
            EmailMessage("m2", "sales.rep@pr-abacebiology.com", ["xinyan.zhang@creative-biostructure.com"], [],
                         "Re:Order_CBSRX09242501B-2", "2026-10-02T23:27:05Z", REPLY_BODY,
                         [Attachment("Quotation_CBSRX09242501B-2.pdf", "application/pdf", b"%PDF-1.4 fake")]),
        ],
    )
