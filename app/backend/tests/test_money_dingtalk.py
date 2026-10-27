"""money 格式化与解析；钉钉网关白名单、通知内容白名单、发件箱失败重试（AC-F11-05、NFR-005、FLOW-30）。"""
from datetime import datetime, timedelta
from decimal import Decimal as D

import httpx
import pytest
from sqlalchemy import select

from app.core.clock import TZ
from app.core.money import (MoneyError, dec_str, fmt_cny, fmt_foreign, fmt_percent, percent_to_ratio,
                            ratio_to_percent, to_decimal)
from app.dingtalk.gateway import AllowlistTransport, DingTalkClient, HostNotAllowed
from app.dingtalk.outbox import NoticeContentError, build_notice, enqueue_notice, process_outbox
from app.models import Alert, RuleVersion
from app.models.enums import NotifyStatus, OutboxStatus
from tests.conftest import make_settings


def test_money_parse_and_format():
    assert to_decimal("1,234.56") == D("1234.56") and to_decimal("") == D(0) and to_decimal("−5") == D(-5)
    with pytest.raises(MoneyError):
        to_decimal(1.5)
    with pytest.raises(MoneyError):
        to_decimal("abc")
    assert percent_to_ratio("12.5") == D("0.125")
    assert ratio_to_percent(D("0.123456")) == "12.3456"
    assert ratio_to_percent(D("0.100000")) == "10"
    assert dec_str(D("615168.000000")) == "615168"
    assert fmt_cny(D("1234.565")) == "¥ 1,234.57"
    assert fmt_cny(D("-60768")) == "¥ −60,768.00"
    assert fmt_foreign(D("1543820"), "USD") == "$ 1,543,820.00 USD"
    assert fmt_foreign(D("34214.4"), "EUR") == "€ 34,214.40 EUR"
    assert fmt_percent(D("0.036261"), signed=True) == "+3.63%"
    assert fmt_cny(None) == "—"


def test_gateway_rejects_non_dingtalk_host():
    settings = make_settings(DINGTALK_BASE_URL="https://api.dingtalk.com")
    assert settings.dingtalk_allowed_hosts == {"api.dingtalk.com", "oapi.dingtalk.com"}
    transport = AllowlistTransport(settings.dingtalk_allowed_hosts, httpx.MockTransport(lambda r: httpx.Response(200)))
    with httpx.Client(transport=transport) as c:
        with pytest.raises(HostNotAllowed):
            c.get("https://open.bigmodel.example.com/v1/chat")
        assert c.get("https://oapi.dingtalk.com/topapi/x").status_code == 200


def test_notice_content_rejects_amounts():
    ok = build_notice(title="预算预警", name="新渠道连续 2 个月收入达成率低于 70%", object_name="TikTok-US-01",
                      period="2027-04", link="http://localhost:8000/alerts")
    assert ok.text() == "新渠道连续 2 个月收入达成率低于 70%｜TikTok-US-01｜2027-04"
    for bad in ({"object_name": D("615168.00")}, {"object_name": 615168}, {"period": "¥ 615,168.00"},
                {"name": "超出 12,000.00"}, {"name": "实际 554400.00 元"}):
        with pytest.raises(NoticeContentError):
            build_notice(**{"title": "预算预警", "name": "规则", "link": "/alerts", **bad})


def _alert(db, object_id: str) -> Alert:
    rv = db.scalar(select(RuleVersion).order_by(RuleVersion.id).limit(1))
    a = Alert(rule_version_id=rv.id, object_type="store", object_id=object_id, object_name="TikTok-US-01",
              period=datetime(2027, 4, 1).date(), metric_value=D("0.62"), threshold=D("0.70"))
    db.add(a)
    db.flush()
    return a


def test_outbox_retries_every_5_minutes_then_marks_failed(seeded, stub, dingtalk):
    db = seeded
    t0 = datetime(2027, 5, 12, 10, 0, tzinfo=TZ)
    ok_alert, bad_alert = _alert(db, "10"), _alert(db, "11")
    content = build_notice(title="预算预警", name="新渠道连续 2 个月收入达成率低于 70%", object_name="TikTok-US-01",
                           period="2027-04", link="http://localhost:8000/alerts")
    ok = enqueue_notice(db, biz_type="alert", biz_id=ok_alert.id, receivers=["hejianguo", "linxiao", "zhoumingyuan"],
                        content=content, now=t0)
    bad = enqueue_notice(db, biz_type="alert", biz_id=bad_alert.id, receivers=["tangyue", "zhaolei", "linxiao"],
                         content=content, now=t0)
    stub.put("/_stub/fail-receivers", json={"userids": ["tangyue"]})

    process_outbox(db, dingtalk, t0)
    assert ok.status == OutboxStatus.SENT and ok_alert.notify_status == NotifyStatus.SENT
    assert bad.attempts == 1 and bad_alert.notify_status == NotifyStatus.RETRYING
    process_outbox(db, dingtalk, t0 + timedelta(minutes=4))  # 未到 5 分钟不重试
    assert bad.attempts == 1
    for minutes in (5, 10, 15, 20):
        process_outbox(db, dingtalk, t0 + timedelta(minutes=minutes))
    assert bad.attempts == 4 and bad.status == OutboxStatus.FAILED
    assert bad_alert.notify_status == NotifyStatus.FAILED

    messages = stub.get("/_stub/messages").json()
    assert len(messages) == 5  # 第一条 1 次 + 第二条 4 次
    sent = messages[0]
    assert sent["userid_list"] == ["hejianguo", "linxiao", "zhoumingyuan"] and sent["errcode"] == 0
    assert sent["msg"]["link"]["text"] == "新渠道连续 2 个月收入达成率低于 70%｜TikTok-US-01｜2027-04"
    assert [m["errcode"] != 0 for m in messages[1:]] == [True] * 4


def test_dingtalk_client_against_stub(stub, dingtalk):
    assert dingtalk.userid_from_qr_code("qr-wanghao") == "wanghao"
    assert dingtalk.userid_from_h5_code("h5-linxiao") == "linxiao"
    assert dingtalk.get_user("zhaoyiming").name == "赵一鸣"
    assert dingtalk.get_user("nobody") is None
    users = {u.userid for u in dingtalk.list_users()}
    assert {"wanghao", "linxiao", "zhaoyiming"} <= users
    assert isinstance(dingtalk, DingTalkClient)
