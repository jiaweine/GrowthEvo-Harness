from __future__ import annotations

import copy
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from growthevo._version import __version__

UTC = timezone.utc
_lock = threading.Lock()
MAX_REFERENCE_CAMPAIGNS = 1_000

KPI = [
    {"id":"incremental_revenue","label":"增量收入","value":2846320,"formatted":"¥ 2,846,320","delta":"+23.4%","spark":[18,22,21,29,32,28,39,43,41,51,47,62]},
    {"id":"incremental_profit","label":"增量利润","value":1284610,"formatted":"¥ 1,284,610","delta":"+26.1%","spark":[12,15,16,21,24,22,30,31,36,39,44,52]},
    {"id":"incremental_roi","label":"Incremental ROI","value":4.42,"formatted":"4.42x","delta":"+0.8x","spark":[20,24,23,30,29,38,42,40,49,47,54,61]},
    {"id":"waste_avoided","label":"无效触达节省","value":843210,"formatted":"¥ 843,210","delta":"+31.8%","spark":[8,10,14,13,19,22,27,26,31,39,37,48]},
]
TREND = [108,104,98,112,128,126,139,135,148,153,146,160,172,185,181,190,208,212,224,236,231,246,252,260,257,269,278,281,286,287,302]
CHANNELS = [{"name":n,"share":s} for n,s in [("App Push",32),("站内消息",24),("Email",18),("短信",12),("广告",9),("微信",4),("其他",1)]]

OPPORTUNITIES = [
    {"id":"opp_new_7d","segment":"新用户 0–7 天未首购","population":864210,"natural_conversion":.118,"best_action":"首单免邮","incremental_lift_pp":8.4,"incremental_value":1840000,"confidence":.94,"support":.91,"evidence_tier":"A","freshness":"3 分钟前"},
    {"id":"opp_dormant_30_60","segment":"沉默 30–60 天会员","population":320510,"natural_conversion":.041,"best_action":"召回 Push + 商品卡","incremental_lift_pp":4.7,"incremental_value":612000,"confidence":.87,"support":.89,"evidence_tier":"A","freshness":"7 分钟前"},
    {"id":"opp_cart_high","segment":"高意向加购未支付","population":86210,"natural_conversion":.287,"best_action":"NO_TREATMENT / 免邮择优","incremental_lift_pp":5.3,"incremental_value":438000,"confidence":.82,"support":.84,"evidence_tier":"B","freshness":"2 分钟前"},
    {"id":"opp_coupon_decay","segment":"¥10 券历史敏感人群","population":178420,"natural_conversion":.153,"best_action":"重新实验","incremental_lift_pp":3.4,"incremental_value":214000,"confidence":.68,"support":.74,"evidence_tier":"C","freshness":"14 分钟前"},
]

CAMPAIGNS = [
    {"id":"cmp_101","name":"新用户首购提升计划","type":"Campaign","status":"运行中","goal":"首购率","population":128421,"started_at":"09-18","expected_lift":"+12.1%","evidence_tier":"A","mode":"5% Canary"},
    {"id":"exp_208","name":"沉默用户召回","type":"Experiment","status":"5% Canary","goal":"7日活跃","population":320510,"started_at":"09-16","expected_lift":"+8.7%","evidence_tier":"A","mode":"Canary"},
    {"id":"cmp_312","name":"高价值用户加购","type":"Campaign","status":"运行中","goal":"加购率","population":86210,"started_at":"09-12","expected_lift":"+5.3%","evidence_tier":"B","mode":"Batch"},
    {"id":"exp_511","name":"节日礼品推荐","type":"Experiment","status":"分析中","goal":"GMV","population":520331,"started_at":"09-10","expected_lift":"-1.2%","evidence_tier":"A","mode":"A/B/n"},
    {"id":"cmp_618","name":"会员升级激励","type":"Campaign","status":"已暂停","goal":"会员转化","population":72881,"started_at":"09-08","expected_lift":"+9.4%","evidence_tier":"B","mode":"Batch"},
]
_campaign_state = copy.deepcopy(CAMPAIGNS)

EXPERIMENTS = [
    {"id":"exp_208","name":"沉默用户召回","hypothesis":"轻量提醒对高支持度沉默会员产生正向增量活跃","primary_metric":"active_7d","assignment":"user_id","variants":["NO_TREATMENT","push_reminder_v4"],"allocation":"50/50 within 5% canary","maturity":"7d","status":"running","estimate":"+4.7pp","ci":"+3.2 ~ +6.1pp","guardrails":["unsubscribe_rate","complaint_rate"]},
    {"id":"exp_511","name":"节日礼品推荐","hypothesis":"推荐型创意可以提升礼品购买增量利润","primary_metric":"incremental_profit","assignment":"user_id","variants":["NO_TREATMENT","creative_A","creative_B"],"allocation":"34/33/33","maturity":"3d","status":"analyzing","estimate":"-1.2%","ci":"-3.4 ~ +0.9%","guardrails":["return_rate"]},
]

APPROVALS = [
    {"id":"apr_281","title":"新用户首购计划扩大至 25%","campaign":"新用户首购提升计划","affected_users":186421,"budget":286000,"max_risk":"Push unsubscribe +0.08pp","incremental_value":724000,"evidence_tier":"A","uncertainty":"95% CI +5.9 ~ +10.7pp","agent_version":"growth-agent-0.3","harness_version":"harness-0.2","policy_version":"pv_42","status":"pending"},
    {"id":"apr_404","title":"Creative Set #12 发布到 Email","campaign":"会员升级激励","affected_users":72881,"budget":62000,"max_risk":"brand claim review","incremental_value":134000,"evidence_tier":"B","uncertainty":"OPE SE 0.0041","agent_version":"growth-agent-0.3","harness_version":"harness-0.2","policy_version":"pv_37","status":"pending"},
]
_approval_state = copy.deepcopy(APPROVALS)

HARNESS_RUNS = [
    {"id":"run_9081","task":"Create 5% canary for dormant users","agent_version":"growth-agent-0.3","harness_version":"harness-0.2","success":True,"policy":"pass","evidence":"A","tool_calls":8,"cost":.84,"latency_ms":8240,"outcome":"approval_requested"},
    {"id":"run_9078","task":"Analyze coupon uplift decay","agent_version":"growth-agent-0.3","harness_version":"harness-0.2","success":True,"policy":"pass","evidence":"C","tool_calls":5,"cost":.42,"latency_ms":5120,"outcome":"experiment_draft"},
    {"id":"run_9064","task":"Publish unreviewed claim","agent_version":"growth-agent-0.2","harness_version":"harness-0.2","success":False,"policy":"blocked","evidence":"D","tool_calls":3,"cost":.19,"latency_ms":2810,"outcome":"guardrail_block"},
]
EVOLUTION = [{"id":"EV-281","source_runs":387,"problem":"18% 的 Campaign Creation Run 过早创建 Audience，之后才发现 frequency eligibility 不满足。","candidate":"create_audience 前新增 check_eligibility_distribution skill。","offline_replay":{"task_success":"+6.4%","tool_calls":"-8.2%","policy_violation":"0%","cost":"-4.1%"},"shadow":"PASS","status":"ready_for_canary"}]
AGENT_ACTIVITY = [
    {"label":"正在分析新用户行为数据","state":"done"},{"label":"查询历史实验与可用优惠券","state":"done"},{"label":"识别高增量机会人群","state":"done"},{"label":"生成策略候选方案","state":"active"},{"label":"评估因果效果与预算","state":"queued"},{"label":"生成创意内容","state":"queued"},{"label":"创建实验方案","state":"queued"},{"label":"等待你的确认","state":"queued"},
]
CAPABILITIES = [
    {"id":"causal","name":"Causal effect estimation","detail":"Cross-fitted DR CATE with support-aware decisioning.","module":"growthevo.causal"},
    {"id":"ope","name":"Off-policy evaluation","detail":"IPS/SNIPS/DR/SWITCH-DR/DR-OS/β*-IPS.","module":"growthevo.rl.ope"},
    {"id":"locked","name":"Locked evidence","detail":"Pre-registration, frozen validation winner and final holdout.","module":"growthevo.bench"},
    {"id":"harness","name":"Agent harness","detail":"Context, memory, tool, trace, eval and approval boundaries.","module":"growthevo.web"},
]
EVIDENCE = [
    {"id":"criteo","name":"Criteo Uplift v2.1","kind":"Locked targeting","winner":"S-Learner","commit":"7ac26a5aebde2c70e1b43264b89f08dddcff0245","metrics":[{"label":"Source rows","value":"13,979,592"},{"label":"Population increment","value":"+0.93791 pp"},{"label":"Selected top-10% increment","value":"+9.37910 pp"}]},
    {"id":"obd","name":"Open Bandit Dataset","kind":"Locked OPE","winner":"IPS","commit":"7d538cea9698b5f0a48c585eed85e3ae526e5af6","metrics":[{"label":"Random-policy rows","value":"1,374,327"},{"label":"Final estimate","value":"0.00452954"},{"label":"Support coverage","value":"1.0000"}]},
]


def campaigns() -> list[dict[str, Any]]:
    with _lock:
        return copy.deepcopy(_campaign_state)


def approvals() -> list[dict[str, Any]]:
    with _lock:
        return copy.deepcopy(_approval_state)


def opportunities() -> list[dict[str, Any]]:
    return copy.deepcopy(OPPORTUNITIES)


def experiments() -> list[dict[str, Any]]:
    return copy.deepcopy(EXPERIMENTS)


def harness_runs() -> list[dict[str, Any]]:
    return copy.deepcopy(HARNESS_RUNS)


def evolution_candidates() -> list[dict[str, Any]]:
    return copy.deepcopy(EVOLUTION)


def reference_state_stats() -> dict[str, int]:
    with _lock:
        return {
            "campaigns": len(_campaign_state),
            "max_campaigns": MAX_REFERENCE_CAMPAIGNS,
            "approvals": len(_approval_state),
        }


def dashboard_payload() -> dict[str, Any]:
    return {"project":{"name":"GrowthEvo","version":__version__,"tagline":"因果驱动的增长操作系统","status":"operational-demo","surface":"growth-os"},"summary":{"online_decisions":18420831,"running_campaigns":12,"agent_automation":.68,"no_treatment_rate":.31},"kpis":copy.deepcopy(KPI),"trend":TREND[:],"channels":copy.deepcopy(CHANNELS),"campaigns":campaigns(),"approvals":approvals(),"agent_activity":copy.deepcopy(AGENT_ACTIVITY),"capabilities":copy.deepcopy(CAPABILITIES),"evidence":copy.deepcopy(EVIDENCE)}


def decide_approval(approval_id: str, decision: str, note: str) -> dict[str, Any] | None:
    with _lock:
        for item in _approval_state:
            if item["id"] == approval_id:
                item["status"] = decision
                item["decision_note"] = note
                item["decided_at"] = datetime.now(UTC).isoformat()
                return copy.deepcopy(item)
    return None


def create_campaign_draft(name: str, goal: str, audience: str, budget: float, candidate_action_ids: list[str]) -> dict[str, Any]:
    item = {"id":f"cmp_{uuid.uuid4().hex[:8]}","name":name,"type":"Campaign","status":"Draft","goal":goal,"audience":audience,"budget":budget,"candidate_action_ids":candidate_action_ids,"population":None,"started_at":None,"expected_lift":"pending causal evaluation","evidence_tier":"D","mode":"Draft"}
    with _lock:
        _campaign_state.insert(0, item)
        # This is a reference/demo state store, not durable production storage.
        # Keep it bounded so soak tests and long-running demos cannot grow memory
        # without limit while preserving the newest drafts for the UI.
        del _campaign_state[MAX_REFERENCE_CAMPAIGNS:]
    return copy.deepcopy(item)


def agent_plan(goal: str, budget_limit: float | None, primary_metric: str, guardrails: list[str]) -> dict[str, Any]:
    budget_text = f"¥{budget_limit:,.0f}" if budget_limit is not None else "未设置"
    return {
        "run_id":f"run_{uuid.uuid4().hex[:10]}","status":"proposal_ready","goal":goal,
        "claims":[
            {"type":"FACT","text":"当前工作区存在 Tier A 的新用户首购增量证据。","source":"Evidence Store / locked bundle"},
            {"type":"ESTIMATE","text":"高支持度新用户人群的首单免邮候选可进入 Shadow/Canary 评估。","source":"Opportunity Map / opp_new_7d"},
            {"type":"HYPOTHESIS","text":"首单配送成本可能是高意向未首购用户的主要摩擦之一。","source":"Agent inference; requires experiment"},
            {"type":"IDEA","text":"以 NO_TREATMENT 为 control，测试免邮与轻量提醒的受控组合。","source":"Growth Agent"},
        ],
        "artifacts":[
            {"type":"StrategyProposal","title":"新用户 7 日首购增量策略","status":"draft"},{"type":"AudienceDraft","title":"高意向 · 0–7 天 · 未首购 · 频控可用","status":"draft"},{"type":"ExperimentDraft","title":"NO_TREATMENT vs 首单免邮","status":"draft"},{"type":"CreativeSet","title":"4 个免邮表达变体","status":"draft"},{"type":"CampaignDraft","title":"5% Canary","status":"awaiting_shadow"},{"type":"ApprovalRequest","title":f"预算上限 {budget_text}","status":"not_submitted"},
        ],
        "compiled_goal":{"primary_metric":primary_metric,"budget_limit":budget_limit,"guardrails":guardrails or ["unsubscribe_rate","complaint_rate"]},"next_gate":"Shadow preflight",
    }
