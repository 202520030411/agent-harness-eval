"""RL 进度一览（D-072）：python3 tools/rl_status.py [/root/work/rl]
每步一行：采样用的策略、通过率（不带提示 / 带提示）、有信号的组、训练样本数、梯度范数、LoRA B 范数、平均输出 token、各阶段分钟、累计花费。"""
import json
import sys
from pathlib import Path

rl = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/work/rl")
f = rl / "log.jsonl"
if not f.exists():
    sys.exit(f"no log yet at {f}")
fmt = lambda x, d=2: "—" if x is None else f"{x:.{d}f}"   # noqa: E731
print("| 步 | 策略 | 通过率 | 不带提示 | 带提示 | 带提示的题不带提示试做 | 提示依赖度 | 有信号的组 | 样本 | 超长丢弃 | 梯度范数 | LoRA B 范数 | 输出 token | 采样 / 训练（分） | 累计 $ |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for line in open(f):
    h = json.loads(line)
    t, b = h.get("train") or {}, h["batch"]
    print(f"| {h['step']} | {h['policy_sampled']} | {fmt(h['pass_rate'])} | {fmt(h['pass_rate_plain'])} | {fmt(h['pass_rate_hinted'])} | {fmt(h.get('probe_pass_rate'))} | {fmt((t.get('hint_reliance') or {}).get('mean'), 3)} | "
          f"{b['signal_groups']}/{len(h['passes_by_task'])} | {t.get('examples', 0)} | {(t.get('dropped') or {}).get('too_long', 0)} | "
          f"{fmt(t.get('grad_norm_before_clip'), 3)} | {fmt(t.get('lora_b_norm'), 3)} | {fmt(h['mean_out_tokens'], 0)} | "
          f"{h['rollout_min']} / {h.get('train_min', '—')} | {h['spent_usd']} |")
