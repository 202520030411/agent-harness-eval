# 提议（花费 $0.041，上限 $1.00）

## 进入版本记录的候选

## 被拒的候选（范围 / 预注册 / 重复）

## 需要人审的提案（不会自动生效）
- [gpt-6-sol#0] **Mismatch-aware completion gate**（premature_completion）：When the agent claims completion, inspect its most recent check for an unambiguous nonzero exit or explicit mismatch. If found, bounce the claim once with the existing evidence; do not require another check when none has failed.
- [gpt-6-sol#0] **Do not count an echoed success message as a check**（echo_theater）：Change the existing completion gate so a command that merely prints a success message does not satisfy its check requirement; retain the one-bounce limit.

## 记录
- gpt-6-sol sample 0: $0.041; 0 auto, 2 review, 4 rejected-by-model
