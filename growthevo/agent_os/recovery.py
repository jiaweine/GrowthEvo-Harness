"""Checkpointed execution using the existing operator's validator and typed tools."""
from __future__ import annotations

import asyncio
import json
import logging
from secrets import token_urlsafe
from typing import Any
from uuid import uuid4

from .journal import ExecutionConflict, RunJournal
from .operator import GrowthOperator, TOOL_EFFECTS


class RecoverableOperator(GrowthOperator):
    def __init__(self, *args: Any, journal: RunJournal, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.journal = journal

    @staticmethod
    def _trace(run_id: str, state: dict[str, Any], status: str, message: str) -> dict[str, Any]:
        events = state["events"]
        result = {
            "run_id": run_id, "status": status, "message": message,
            "steps": events, "tool_calls": len(events),
            "policy_fingerprint": state["policy"]["fingerprint"],
            "has_draft_write": any(e["effect"] == "draft" and e["outcome"] == "ok" for e in events),
            "navigation": state["navigation"], "ui_commands": state["ui_commands"],
            "ui_actions": state["ui_actions"], "execution_authority": "typed_first_party_tools",
        }
        for key in ("ui_receipts", "confirmation_source"):
            if key in state:
                result[key] = state[key]
        return result

    async def run(self, goal: str, *, allow_drafts: bool = False,
                  max_steps: int | None = None, run_id: str | None = None) -> dict[str, Any]:
        if run_id is None:
            if max_steps is not None and not 1 <= max_steps <= 8:
                raise ValueError("max_steps outside server limit")
            policy = self.evolution.snapshot()
            run_id = "op_" + uuid4().hex[:16]
            state = {
                "goal": goal, "allow_drafts": allow_drafts, "policy": policy,
                "max_steps": min(max_steps or policy["step_budget"], policy["step_budget"]),
                "turn": 0, "events": [], "model_history": [], "seen": [], "observed": False,
                "navigation": None, "ui_commands": [], "ui_actions": [], "pending": None,
            }
            state, lease = self.journal.start(run_id, state, self._trace(run_id, state, "running", "正在执行任务。"))
        else:
            claimed = self.journal.claim(run_id, allow_drafts=allow_drafts)
            if claimed is None:
                return self.journal.result(run_id)
            state, lease = claimed

        heartbeat = asyncio.create_task(self.journal.heartbeat(run_id, lease))

        def save(status: str, message: str, event: str) -> None:
            self.journal.checkpoint(run_id, lease, state, self._trace(run_id, state, status, message), event)

        status, message = "step_limit", "已达到本次操作步数限制，任务可能尚未完成。"
        try:
            while state["turn"] < state["max_steps"] or state["pending"] is not None:
                if state["pending"] is None:
                    context = {
                        "goal": state["goal"], "draft_creation_allowed": state["allow_drafts"],
                        "operator_policy": {"preferred_first_read": state["policy"]["preferred_first_read"]},
                        "tools": self.tools.describe(), "previous_steps": state["model_history"][-8:],
                    }
                    try:
                        response = await self.model.agenerate(
                            system=self.SYSTEM,
                            user=json.dumps(context, ensure_ascii=False, sort_keys=True), schema=self.schema(),
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        status, message = "provider_failure", "模型服务暂不可用，已保存检查点，可以稍后继续。"
                        break
                    kind, tool, args, fingerprint, proposed_message = self.validated_action(
                        response, set(state["seen"]), state["events"])
                    state["turn"] += 1
                    if kind == "finish":
                        status = "completed" if state["events"] else "unverified"
                        message = proposed_message if state["events"] else "没有执行工作区操作。" + proposed_message
                        break
                    state["seen"].append(fingerprint)
                    state["pending"] = {"tool": tool, "args": args, "fingerprint": fingerprint,
                                        "index": len(state["events"])}
                    # Write-ahead checkpoint: recovery replays this exact typed operation,
                    # never asks a model to regenerate a potentially different mutation.
                    save("running", "已保存待执行操作。", "tool_prepared")

                pending = state["pending"]
                tool, args, index = pending["tool"], pending["args"], pending["index"]
                outcome, data = self.tools.execute(
                    tool, args, allow_drafts=state["allow_drafts"], observed=state["observed"],
                    draft_writer=lambda request: self.journal.draft_once(run_id, lease, index, request),
                )
                state["observed"] |= tool == "workspace.read" and outcome == "ok"
                event = {"tool": tool, "effect": TOOL_EFFECTS[tool], "outcome": outcome,
                         "arguments_hash": pending["fingerprint"][:16]}
                if tool == "workspace.read":
                    event["section"] = data["section"]
                if "draft" in data:
                    event["draft"] = data["draft"]
                state["ui_commands"] = []
                state["ui_actions"] = []
                state.pop("ui_receipts", None)
                state.pop("confirmation_source", None)
                if "navigation" in data:
                    state["navigation"] = event["navigation"] = data["navigation"]
                    state["ui_actions"].append({"step_index": index, "kind": "navigate",
                                                "target": data["navigation"], "status": "pending"})
                if "ui_command" in data:
                    event["ui_command"] = data["ui_command"]
                    state["ui_commands"].append(data["ui_command"])
                    state["ui_actions"].append({"step_index": index, "kind": "control",
                                                "target": data["ui_command"], "status": "pending"})
                history = {"tool": tool, "outcome": outcome,
                           "feedback": json.dumps(data, ensure_ascii=False, default=str)[:10000]}
                if index < len(state["events"]):
                    # The previous entry was an authorization pause, not a completed write.
                    state["events"][index] = event
                    state["model_history"][index] = history
                else:
                    state["events"].append(event)
                    state["model_history"].append(history)
                if outcome == "needs_consent":
                    status, message = outcome, "创建草案需要当前用户明确授权；已保存待执行操作。"
                    break
                state["pending"] = None
                if outcome == "needs_approval":
                    state["ui_token"] = token_urlsafe(32)
                    status, message = outcome, "请在审批页面核对并由人决定。"
                    break
                if state["ui_actions"]:
                    # A real browser observation must arrive before another model turn.
                    state["ui_token"] = token_urlsafe(32)
                    status, message = "awaiting_ui_confirmation", "等待浏览器完成操作并反馈结果。"
                    break
                save("running", "已保存工具执行结果。", "tool_completed")
        except asyncio.CancelledError:
            try:
                save("interrupted", "执行已中断，可以从已保存的检查点继续。", "interrupted")
            except ExecutionConflict:
                pass
            raise
        except ExecutionConflict:
            raise
        except (ValueError, TypeError, KeyError) as exc:
            status, message = "blocked", str(exc)[:240]
        except Exception as exc:
            status, message = "tool_failure", "工具执行中断，已保留待核对检查点：" + type(exc).__name__
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

        save(status, message, "paused" if status != "completed" else "completed")
        try:
            self.evolution.propose(self.journal.recent(100))
        except Exception as exc:
            # Analysis is retriable from Evolution Lab. Its failure must not
            # conceal a persisted execution result or encourage duplicate work.
            logging.getLogger(__name__).warning(
                "Evolution analysis deferred after run %s (%s)", run_id, type(exc).__name__
            )
        return self.journal.result(run_id)
