"""D-072 PSP 式 GRPO 的纯函数。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from train.rl.grpo import (HINTED, PLAIN, group_advantages, next_mode, pick_tasks, trial_example,  # noqa: E402
                           trial_reward)


def test_group_advantages_standardizes_and_skips_no_signal():
    adv = group_advantages([1, 0, 0, 0])
    assert adv[0] == pytest.approx(3 ** 0.5) and adv[1] == pytest.approx(-1 / 3 ** 0.5)
    assert sum(adv) == pytest.approx(0)
    assert group_advantages([0] * 8) is None and group_advantages([1] * 8) is None and group_advantages([1]) is None


def test_next_mode_follows_psp_gate():
    assert next_mode(PLAIN, 0, 8) == (HINTED, True)       # 不带提示全挂 → 下次带规则（用这组失败写）
    assert next_mode(PLAIN, 3, 8) == (PLAIN, False)
    assert next_mode(HINTED, 0, 8) == (HINTED, True)      # 带规则仍全挂 → 重写
    assert next_mode(HINTED, 2, 8) == (HINTED, False)
    assert next_mode(HINTED, 4, 8) == (PLAIN, False)      # 过了一半 → 去掉规则再试


def test_pick_tasks_cycles_evenly():
    order = list("abcde")
    got, cur = pick_tasks(order, 0, 3)
    got2, cur2 = pick_tasks(order, cur, 3)
    assert got == ["a", "b", "c"] and got2 == ["d", "e", "a"] and cur2 == 1


def _result(reward=1.0, exc=None, gate_turns=(), summarized=0, n_turns=3):
    msgs = [{"role": "user", "content": "task"}]
    for k in range(1, n_turns + 1):
        msgs += [{"role": "assistant", "content": f"a{k}"}, {"role": "user", "content": f"o{k}"}]
    return {"task_name": "synth/t1", "exception_info": {"exception_type": exc} if exc else None,
            "verifier_result": {"rewards": {"reward": reward}},
            "agent_result": {"metadata": {"all_messages": msgs, "summarization_count": summarized,
                                          "patched": {"completion_gate": [{"turn": t, "reasons": ["x"]} for t in gate_turns]}}}}


def test_trial_reward_counts_timeouts_as_failures_and_drops_infra():
    assert trial_reward(_result(1.0)) == 1.0 and trial_reward(_result(0.0, exc="AgentTimeoutError")) == 0.0
    assert trial_reward(_result(0.0, exc="DockerError")) is None


def test_trial_example_masks_gated_claim_only_when_rewarded():
    ex, why = trial_example(_result(1.0, gate_turns=(2,)), 1.2)
    assert why == "ok" and ex["messages"][3] == {"role": "assistant", "content": "a2", "train": False}
    assert "train" not in ex["messages"][1] and "train" not in ex["messages"][5]
    ex, _ = trial_example(_result(0.0, gate_turns=(2,)), -0.8)
    assert all("train" not in m for m in ex["messages"])  # 做错的轨迹：错的交卷正该被罚


def test_trial_example_skips_summarized_and_misaligned():
    assert trial_example(_result(summarized=1), 1.0)[1] == "summarized"
    assert trial_example(_result(1.0, gate_turns=(9,)), 1.0)[1] == "claim_turn_misaligned"


# ---------------------------------------------------------------- 一次更新的方向（极小的随机模型，CPU）
def _tiny():
    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers"); pytest.importorskip("peft")
    from peft import LoraConfig, get_peft_model
    from transformers import LlamaConfig, LlamaForCausalLM
    torch.manual_seed(0)
    m = LlamaForCausalLM(LlamaConfig(vocab_size=40, hidden_size=32, intermediate_size=64, num_hidden_layers=2, num_attention_heads=2,
                                     num_key_value_heads=2, max_position_embeddings=64))
    m = get_peft_model(m, LoraConfig(r=4, lora_alpha=8, lora_dropout=0.0, target_modules=["q_proj", "k_proj", "v_proj", "o_proj"]))
    params = [p for p in m.parameters() if p.requires_grad]
    return torch, m, params, torch.optim.AdamW(params, lr=5e-2)


def _nll(torch, m, ex):
    with torch.no_grad():
        return m(input_ids=torch.tensor([ex["input_ids"]]), labels=torch.tensor([ex["labels"]])).loss.item()


@pytest.mark.parametrize("adv", [1.0, -1.0])
def test_step_on_batch_moves_logprob_in_the_sign_of_the_advantage(adv):
    from train.rl.grpo_step import step_on_batch
    torch, m, params, opt = _tiny()
    ids = [3, 5, 7, 9, 11, 13, 15, 17]
    ex = {"input_ids": ids, "labels": [-100, -100, -100] + ids[3:]}      # 前 3 个 token 是“开场”，不算 loss
    before = _nll(torch, m, ex)
    for _ in range(3):
        stats = step_on_batch(m, [(ex, adv, 5)], opt, params, 1.0, "cpu")
    after = _nll(torch, m, ex)
    assert (after < before) if adv > 0 else (after > before)            # 正 advantage → log-prob 变高（NLL 变低），负的相反
    assert stats["examples"] == 1 and stats["trainable_tokens"] == 5


def test_load_batch_masks_like_sft_and_drops_long(tmp_path):
    pytest.importorskip("transformers")
    from train.rl.grpo_step import load_batch

    class Tok:   # 极简分词器：每条消息 → [角色码, 内容长度个 1]，前缀稳定（同 test_teacher_hint 里的 SFT 掩码测试）
        def apply_chat_template(self, messages, tokenize=True, add_generation_prompt=False, **kw):
            ids = []
            for mm in messages:
                ids += [7 if mm["role"] == "user" else 9] + [1] * len(mm["content"])
            return ids + ([9] if add_generation_prompt else [])
    rows = [{"messages": [{"role": "user", "content": "ab"}, {"role": "assistant", "content": "cde", "train": False},
                          {"role": "user", "content": "f"}, {"role": "assistant", "content": "gh"}], "advantage": 0.5},
            {"messages": [{"role": "user", "content": "x" * 50}, {"role": "assistant", "content": "y"}], "advantage": -1.0},
            {"messages": [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b", "train": False}], "advantage": 1.0}]
    f = tmp_path / "batch.jsonl"; f.write_text("\n".join(json.dumps(r) for r in rows))
    kept, why = load_batch(Tok(), str(f), max_len=20)
    assert len(kept) == 1 and kept[0][1] == 0.5 and kept[0][2] == 2 and why == {"too_long": 1, "no_trainable_tokens": 1}


# ---------------------------------------------------------------- 主循环里的纯函数
def test_write_config_changes_only_the_step_fields():
    from train.rl.grpo_loop import write_config
    tpl = (Path(__file__).resolve().parent.parent / "experiments/configs/qroll-h2-synth-train.resolved.yaml").read_text()
    y = write_config(tpl, "rl-step03", Path("/root/work/rl/step03/tasks"), "rlpolicy02", 8, 32, None)
    assert "job_name: rl-step03" in y and "n_attempts: 8" in y and "n_concurrent_trials: 32" in y
    assert "model_name: openai/rlpolicy02" in y and "- path: /root/work/rl/step03/tasks" in y and "teacher_hint" not in y
    assert "completion_gate: true" in y and "interface_fixes: true" in y and "store_all_messages: true" in y   # H2，存完整对话
    yt = write_config(tpl, "rl-step03t", Path("/x"), "rlpolicy02", 8, 32, "/root/work/rl/knowledge.json")
    assert "teacher_hint: true\n    teacher_knowledge: /root/work/rl/knowledge.json" in yt


def test_build_batch_and_stop_rules():
    from train.rl.grpo_loop import build_batch, stop_reason
    groups = {"t1": [(_result(1.0), 1.0), (_result(0.0), 0.0)], "t2": [(_result(0.0), 0.0), (_result(0.0), 0.0)]}
    rows, st = build_batch(groups)
    assert len(rows) == 2 and st["signal_groups"] == 1 and st["group_without_signal"] == 1
    assert sorted(r["advantage"] for r in rows) == [-1.0, 1.0]
    def h(p, tok=100, sig=5, by=None, hinted=()):
        return {"pass_rate": p, "mean_out_tokens": tok, "batch": {"signal_groups": sig}, "passes_by_task": by or {}, "hinted": list(hinted)}
    assert stop_reason([h(0.3, sig=2)], 4, 10, 120).startswith("NO_SIGNAL")
    first = [h(0.75, by={f"t{i}": [6, 8] for i in range(j, j + 4)}) for j in (0, 4, 8)]
    worse = [h(0.1, by={f"t{i}": [1, 8] for i in range(j, j + 4)}) for j in (0, 4, 8)]
    assert stop_reason(first + worse, 4, 10, 120).startswith("PASS_RATE_DROP")        # 同一批题、同一模式真的变差 → 停
    hinted_first = [h(0.75, by={f"t{i}": [6, 8] for i in range(j, j + 4)}, hinted=[f"t{i}" for i in range(j, j + 4)]) for j in (0, 4, 8)]
    plain_later = [h(0.0, by={f"t{i}": [0, 8] for i in range(j, j + 4)}) for j in (0, 4, 8)]
    assert stop_reason(hinted_first + plain_later, 4, 10, 120) is None                # 只是去掉了提示（策略没变）→ 不停
    assert stop_reason([h(0.3), h(0.3, tok=250)], 4, 10, 120).startswith("LENGTH_BLOWUP")
    assert stop_reason([h(0.3)], 4, 130, 120).startswith("BUDGET") and stop_reason([h(0.3)] * 2, 4, 10, 120) is None


def test_chunked_nll_matches_the_standard_loss():
    from train.rl.grpo_step import nll_sum
    torch, m, _, _ = _tiny()
    ids = list(range(3, 30))
    labels = [-100] * 5 + ids[5:12] + [-100] * 4 + ids[16:]              # 两段 assistant，中间一段观察
    n = sum(1 for x in labels if x != -100)
    ref = m(input_ids=torch.tensor([ids]), labels=torch.tensor([labels])).loss.item() * n
    got = nll_sum(m, torch.tensor([ids]), torch.tensor([labels]), chunk=4).item()   # 分块比序列短，走到分块逻辑
    assert abs(got - ref) < 1e-4 * max(1.0, abs(ref))


def test_hint_transfer_pairs_hinted_success_with_later_plain_attempt():
    from tools.rl_eval_report import hint_transfer
    hist = [{"step": 1, "hinted": ["a", "b"], "passes_by_task": {"a": [5, 8], "b": [0, 8], "c": [2, 8]}},
            {"step": 5, "hinted": ["b"], "passes_by_task": {"a": [3, 8], "b": [1, 8]}},
            {"step": 9, "hinted": [], "passes_by_task": {"b": [0, 8]}}]
    assert hint_transfer(hist) == [("a", 1, 5, 3, 8), ("b", 5, 9, 0, 8)]


# ---------------------------------------------------------------- D-075：不带提示的试做 + 提示依赖度
def test_next_mode_probe_success_drops_the_hint():
    assert next_mode(HINTED, 1, 8, probe_passes=1) == (PLAIN, False)
    assert next_mode(HINTED, 0, 8, probe_passes=0) == (HINTED, True)
    assert next_mode(PLAIN, 0, 8, probe_passes=0) == (HINTED, True)   # 不带提示的题没有试做，规则不变


def test_without_hints_removes_rules_block_or_teacher_notes():
    from train.rl.grpo import without_hints
    from terminus2_patches.teacher import MARK
    block = "Notes from a reviewer ...:\n<skills>\n1. Keep zero groups.\n</skills>\n\n"
    msgs = [{"role": "user", "content": "Task Description:\n" + block + "Write /app/out.tsv"},
            {"role": "assistant", "content": "a1", "train": False}, {"role": "user", "content": "o1\n\n" + MARK + "Zero groups missing."},
            {"role": "assistant", "content": "a2"}]
    nr = without_hints(msgs, block, [])
    assert nr[0]["content"] == "Task Description:\nWrite /app/out.tsv" and nr[1]["train"] is False and nr[2] == msgs[2]
    nt = without_hints(msgs, None, [{"turn": 1, "text": "Zero groups missing.", "at_claim": False}])
    assert nt[2]["content"] == "o1" and nt[0] == msgs[0]
    assert without_hints(msgs, "not there", []) is None and msgs[0]["content"].startswith("Task Description:\nNotes")   # 不改原对话


def test_trial_example_keeps_nohint_copy_only_for_rewarded_hinted_trials():
    block = "RULES\n\n"
    r = _result(1.0); r["agent_result"]["metadata"]["all_messages"][0]["content"] = block + "task"
    ex, _ = trial_example(r, 1.0, block)
    assert ex["messages_nohint"][0]["content"] == "task" and ex["messages"][0]["content"] == block + "task"
    assert "messages_nohint" not in trial_example(r, -1.0, block)[0]
    assert "messages_nohint" not in trial_example(_result(1.0), 1.0, None)[0]


def test_share_concurrency_caps_total():
    from train.rl.grpo_loop import share_concurrency
    c = share_concurrency({"": 5 * 8, "t": 11 * 8, "p": 11 * 2}, 32)
    assert sum(c.values()) <= 32 and c["t"] > c[""] > c["p"] >= 1
    assert share_concurrency({"": 16 * 8}, 32) == {"": 32}


def test_step_on_batch_reports_hint_reliance():
    from train.rl.grpo_step import step_on_batch
    torch, m, params, opt = _tiny()
    ids = [3, 5, 7, 9, 11, 13, 15, 17]
    ex = {"input_ids": [30, 31] + ids, "labels": [-100] * 5 + ids[3:]}        # 带“提示”（30, 31）的版本
    ex0 = {"input_ids": ids, "labels": [-100] * 3 + ids[3:]}                 # 去掉提示，同一批要学的 token
    st = step_on_batch(m, [(ex, 1.0, 5, ex0), (ex, -1.0, 5, None)], opt, params, 1.0, "cpu")
    hr = st["hint_reliance"]
    assert hr["n"] == 1 and isinstance(hr["mean"], float)


def test_teacher_failures_stop_the_loop():
    from train.rl.grpo_loop import stop_reason, teacher_health
    r = _result(0.0)
    r["agent_result"]["metadata"]["patched"]["teacher"] = {"calls": [{"drop_reason": "teacher_error: 429 insufficient_quota"}] * 7
                                                            + [{"drop_reason": None, "usage": {}}] * 5}
    assert teacher_health({"t1": [(r, 0.0)]}) == (12, 7)
    h = {"pass_rate": 0.2, "mean_out_tokens": 100, "batch": {"signal_groups": 5}}
    assert stop_reason([dict(h, teacher_calls=12, teacher_errors=7)], 4, 10, 120).startswith("TEACHER_FAILING")
    assert stop_reason([dict(h, teacher_calls=12, teacher_errors=2)], 4, 10, 120) is None


def test_background_launch_does_not_hold_the_ssh_session():
    from train.rl.grpo_loop import bg
    c = bg("python x.py --a 1", "/w/t.log", "/w/done.txt")
    assert "&&" not in c and c.startswith("cd /workspace/code; setsid nohup bash -c '")
    assert c.endswith("< /dev/null > /dev/null 2>&1 &") and "echo rc=$? > /w/done.txt" in c and "> /w/t.log 2>&1" in c
    import subprocess, tempfile, time, os
    d = tempfile.mkdtemp()   # 本地真跑一次：外层 bash 必须立刻返回，不等后台任务
    t0 = time.time()
    import shutil
    cmd = bg("sleep 3", f"{d}/l", f"{d}/m").replace("cd /workspace/code", f"cd {d}")
    if not shutil.which("setsid"):          # macOS 没有 setsid；Linux（服务器、Pod）上按原样测
        cmd = cmd.replace("setsid nohup", "nohup")
    subprocess.run(["bash", "-c", cmd], check=True, timeout=10,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert time.time() - t0 < 2
    time.sleep(4); assert open(f"{d}/m").read().strip() == "rc=0"
