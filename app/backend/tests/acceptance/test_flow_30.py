"""FLOW-30 验收（真实路由 + 数据库 + 本地钉钉替身）：预警钉钉通知：接收人、内容不含金额、失败重试 4 次后「通知失败」（AC-F11-04、AC-F11-05、NFR-005）。

本机用开发身份与钉钉接口替身（可控时钟推进 20 分钟）；真实钉钉复验在凭据就绪后进行。
期望值逐字取自 TDD验收契约.md FLOW-30 行。
"""
import os
import re
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from app.core.clock import clock
from app.dingtalk.gateway import DingTalkClient
from app.dingtalk.outbox import process_outbox
from app.models import Alert, NotificationOutbox
from tests.g3.fixtures_g3 import KINGDEE_HEADER, kd, write_xlsx
from tests.acceptance.test_flow_29 import RULE as DEPT_RULE
from tests.acceptance.test_flow_29 import approve_http, q1_history
from tests.conftest import make_settings
from tests.g3.conftest import G3

# 设置后改用独立进程的钉钉替身（真实 HTTP，例如 E3 的 http://127.0.0.1:8023）；未设置时用进程内替身
STUB_URL = os.environ.get("E3_DINGTALK_STUB_URL")


@pytest.fixture
def stub_api(stub):
    if not STUB_URL:
        yield stub
        return
    with httpx.Client(base_url=STUB_URL) as c:
        c.post("/_stub/reset")
        yield c
        c.post("/_stub/reset")


@pytest.fixture
def g3(seeded, stub_api, dingtalk, tmp_path):
    if not STUB_URL:
        return G3(seeded, dingtalk, tmp_path)
    client = DingTalkClient(make_settings(DINGTALK_BASE_URL=STUB_URL))
    return G3(seeded, client, tmp_path)

NEW_CHANNEL_RULE = "新渠道连续 2 个月收入达成率低于 70%"


def test_flow_30_notifications(g3, stub_api):
    db = g3.db
    g3.set_now("2027-01-05 09:00")
    g3.mark_new_channel("TikTok-US-01", "2027-03")
    g3.make_version(depts={"物流物控部": 1200000, "人力资源部": 1200000},
                    stores={"TikTok-US-01": {3: (200000, 50000), 4: (200000, 50000)}})
    for name in (DEPT_RULE, NEW_CHANNEL_RULE):
        _rule, v1 = g3.preset(name)
        approve_http(g3, v1.id)
    g3.set_now("2027-04-20 10:00")
    g3.import_file(q1_history(g3, [kd("2027-03", "收入", 120000, store="TikTok-US-01", site="美国")]),
                   "kingdee-history")

    # 2027-04：物流物控部超额度（FLOW-29）+ TikTok-US-01 3 月 60%、4 月 65% 连续 2 个月低于 70%
    april = write_xlsx(g3.tmp / "金蝶_2027-04_利润表.xlsx", KINGDEE_HEADER, [
        kd("2027-04", "工资", 170000, dept="物流物控部"), kd("2027-04", "差旅", 30000, dept="物流物控部"),
        kd("2027-04", "工资", 200000, dept="人力资源部"),
        kd("2027-04", "收入", 130000, store="TikTok-US-01", site="美国")])
    g3.set_now("2027-05-12 10:00")
    stub_api.put("/_stub/fail-receivers", json={"userids": ["tangyue"]})  # 第二条通知持续返回 errcode ≠ 0
    g3.import_file(april, "kingdee")

    alerts = {a.object_name: a for a in db.scalars(select(Alert))}
    assert set(alerts) == {"物流物控部", "TikTok-US-01"}
    dept_box = db.scalar(select(NotificationOutbox).where(NotificationOutbox.biz_id == alerts["物流物控部"].id,
                                                          NotificationOutbox.biz_type == "alert"))
    tk_box = db.scalar(select(NotificationOutbox).where(NotificationOutbox.biz_id == alerts["TikTok-US-01"].id,
                                                        NotificationOutbox.biz_type == "alert"))
    # 第一条：物流物控部负责人何建国、财务负责人林晓与 CEO 周明远
    assert sorted(dept_box.receivers) == sorted(["hejianguo", "linxiao", "zhoumingyuan"])
    # 第二条：负责 TikTok-US-01 的运营（唐悦）与其部门负责人赵磊及林晓
    assert sorted(tk_box.receivers) == sorted(["tangyue", "zhaolei", "linxiao"])

    t0 = clock.now()
    for minutes in (0, 5, 10, 15, 20):
        process_outbox(db, g3.dingtalk, t0 + timedelta(minutes=minutes))
    db.expire_all()
    sent = stub_api.get("/_stub/messages").json()
    first = [m for m in sent if "hejianguo" in m["userid_list"]]
    second = [m for m in sent if "tangyue" in m["userid_list"]]
    assert len(first) == 1 and first[0]["errcode"] == 0
    assert len(second) == 4 and all(m["errcode"] != 0 for m in second)   # 首发 + 每 5 分钟重试 3 次
    assert db.get(NotificationOutbox, tk_box.id).attempts == 4

    # 通知内容只有规则名称、对象、期间与系统链接，不含金额或数字型指标值
    for m in sent:
        link = m["msg"]["link"]
        body = link["title"] + link["text"]
        assert "¥" not in body and not re.search(r"\d{1,3}(,\d{3})+", body)
        assert not re.search(r"\d+\.\d+", body)
        for value in ("13.33", "14.00", "60", "65", "120,000", "130000"):
            assert value not in body
    assert first[0]["msg"]["link"]["text"] == f"{DEPT_RULE}（v1）｜物流物控部｜2027-04"
    assert second[0]["msg"]["link"]["text"] == f"{NEW_CHANNEL_RULE}（v1）｜TikTok-US-01｜2027-03 至 2027-04"
    assert "/alerts?id=" in second[0]["msg"]["link"]["messageUrl"]

    # 预警列表：该行通知状态「通知失败」，「钉钉通知失败」计数 +1
    data = g3.client("林晓").get("/api/alerts").json()
    row = next(i for i in data["items"] if i["object_name"] == "TikTok-US-01")
    assert row["notify_status_label"] == "通知失败"
    assert data["kpis"]["notify_failed"] == 1
    assert next(i for i in data["items"] if i["object_name"] == "物流物控部")["notify_status_label"] == "已发送"
    detail = g3.client("林晓").get(f"/api/alerts/{row['id']}").json()
    assert [a["label"] for a in detail["attempts"]] == ["首次发送", "第 1 次重试", "第 2 次重试", "第 3 次重试"]
    assert detail["receivers"] == ["林晓", "唐悦", "赵磊"] or sorted(detail["receivers"]) == ["唐悦", "林晓", "赵磊"]
