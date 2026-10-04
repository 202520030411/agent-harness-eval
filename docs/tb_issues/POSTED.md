# 已发布到 harbor-framework/terminal-bench-2-1（2026-09-26，账号 202520030411）

## 新 issue（我们首次报告的缺陷）

| 题 | issue | 要点 |
|---|---|---|
| cancel-async-tasks | [#238](https://github.com/harbor-framework/terminal-bench-2-1/issues/238) | 题面没写验证器检查的三条取消语义；基线 10 次失败里 8 次只挂那一个测试；改题后 3/3 |
| sanitize-git-repo | [#239](https://github.com/harbor-framework/terminal-bench-2-1/issues/239) | 验证器写死提交 SHA，重写历史后报 `missing`；25 次失败里 17 次是这个（含 gpt-6-sol 一次） |
| build-cython-ext | [#240](https://github.com/harbor-framework/terminal-bench-2-1/issues/240) | 验证器跑未钉版本的上游测试；参考解自己都过不了（`test_reconstructed_space_curve`，`KeyError: 'pos'`，planarity 1.0.0 / networkx 3.7） |

## 在已有讨论下补的复现数据

| 题 | 线程 | 我们补的证据 |
|---|---|---|
| extract-elf | [#194](https://github.com/harbor-framework/terminal-bench-2-1/issues/194#issuecomment-5840761413) | 0/6 → 加约定后 3/3 |
| dna-insert | [#100](https://github.com/harbor-framework/terminal-bench-2-1/issues/100#issuecomment-5840761627) | 边界写明后仍 0/3（oligotm 版本差 58.04 vs 55.86 °C），两者都修后 3/3 |
| configure-git-webserver | [#133](https://github.com/harbor-framework/terminal-bench-2-1/issues/133#issuecomment-5840761815) | 同一句话也造成假阴性（`id user` → 不建账号 → 404） |
| fix-code-vulnerability | [#134](https://github.com/harbor-framework/terminal-bench-2-1/issues/134#issuecomment-5840762007) | 弱模型 9 次通过里 2 次靠 `git checkout bottle.py` 还原答案 |
| raman-fitting | [PR #1](https://github.com/harbor-framework/terminal-bench-2-1/pull/1#issuecomment-5840762150) | 只加 1e7/x 换算峰位对了仍 0/3，PR 里三句都是必要的 |
| pytorch-model-cli | [PR #6](https://github.com/harbor-framework/terminal-bench-2-1/pull/6#issuecomment-5840762286) | 28 次里用均值方差归一化的 2 次一失一过，是非模型 bug 失败的一半 |
| count-dataset-tokens | [PR #2](https://github.com/harbor-framework/terminal-bench-2-1/pull/2#issuecomment-5840762420) | 5 次失败里模型同时算出 79586 和 79566 无法取舍，4 次超时 |

草稿原文：同目录下各 `.md`；`comments_on_existing_threads.md` 是七条评论。
