# 提议（花费 $0.224，上限 $1.50）

## 进入版本记录的候选
- **v0+c01**：{'wait_cap_sec': 30.0, 'adaptive_wait': True, 'wait_stable_sec': 3.0}；目标 budget_exhausted；机制指标 tokens_in（Input tokens down roughly 10–16%; empty-wait turns down roughly 15–30%.）；通过率预测 -4 to +4 pp；证伪：Input tokens fall less than 10%, polling turns do not fall, the pass-rate CI lower bound is below -8 pp, or timeouts or wall-clock cost rise without a pass-rate gain.（proposer:gpt-6-sol#0）
- **v0+c02**：{'completion_gate': False}；目标 turn_cap；机制指标 turn_cap（2–5 pp fewer turn-cap hits, from 18.9% under v0）；通过率预测 -4 to +2 pp；证伪：Turn-cap hits do not decrease, neither turns nor input tokens improve by at least 10%, or the paired pass-rate CI lower bound is below -8 pp.（proposer:gpt-6-sol#1）
- **v0+c03**：{'wait_cap_sec': 30.0, 'completion_gate': False, 'adaptive_wait': True, 'wait_stable_sec': 3.0}；目标 budget_exhausted；机制指标 turns（mean turns per trial down 10-15% from current 49.8）；通过率预测 0 to +4 pp；证伪：mean turns does not fall by at least 5%, or pass rate CI lower bound is below -8pp, or either single-change candidate above falsifies its own mechanism (making the combination uninterpretable)（proposer:claude-sonnet-5#0）

## 被拒的候选（范围 / 预注册 / 重复）
- gpt-6-sol#1 {'adaptive_wait': True}：['duplicate of existing version v0+c01 (status proposed)']
- claude-sonnet-5#0 {'adaptive_wait': True}：['duplicate of existing version v0+c01 (status proposed)']
- claude-sonnet-5#0 {'completion_gate': False}：['duplicate of existing version v0+c02 (status proposed)']

## 需要人审的提案（不会自动生效）
- [gpt-6-sol#0] **Distinguish echo-only commands from verification in tool feedback**（echo_theater）：Instrument executed commands to flag echo-only success claims in the existing tool result; do not count those commands as a post-edit check in the existing one-bounce completion gate. Avoid extra model calls or a second bounce.
- [gpt-6-sol#0] **Assess a native-tool bridge for the Terminus agent**（echo_theater）：Determine whether vLLM native tool calls can be bridged into Terminus while retaining the evaluation's turn limit, summarization, and terminal semantics. Do not build it if the JSON keystroke protocol is mandatory.
- [gpt-6-sol#1] **Native tool-call adapter for Terminus**（echo_theater）：A human-reviewed adapter that accepts native tool calls in place of the JSON keystroke protocol while preserving the evaluation limits and logging.
- [claude-sonnet-5#0] **Harness-side automatic post-claim test re-run (no model turn)**（echo_theater）：When the model claims completion, have the harness itself re-execute the last known test/validation command (or a task-declared check command) server-side and compare output, without spending an agent turn asking the model to verify. Only if this silent check fails does the harness send one corrective message back with the failing output.
- [claude-sonnet-5#0] **Automatic truncated-output continuation**（truncated_read）：Detect truncation markers/heuristics in command output server-side and automatically issue a continuation read (e.g. further pagination) and append it to context, instead of relying on the model to notice and re-request.
- [claude-sonnet-5#0] **Deliverable-conditioned completion_gate**（premature_completion）：Only trigger the completion-gate bounce when a concrete declared deliverable file is missing or unchanged since the last run, instead of gating every first completion claim; skip the gate when the deliverable looks present and tested.

## 记录
- gpt-6-sol sample 0: $0.045; 1 auto, 2 review, 5 rejected-by-model
- gpt-6-sol sample 1: $0.043; 2 auto, 1 review, 4 rejected-by-model
- claude-sonnet-5 sample 0: $0.136; 3 auto, 3 review, 4 rejected-by-model
