# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Browser accounting keeps missing usage distinct from zero and avoids double counting."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_run_metrics_accounting():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the browser contract check")
    source = (
        Path(__file__).resolve().parents[4] / "rpent/dashboard/static/run-metrics.js"
    )
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
(async () => {
  const source = fs.readFileSync(process.argv[1], 'utf8');
  const {formatRunMetrics: metrics, formatRunTimes: times} = await import(
    'data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
  const outcome = {elapsed_s:146.8, stats:{turns_used:17, tool_calls:40,
    total_input_tokens:1000,total_output_tokens:200,total_cached_input_tokens:800}};
  assert.match(metrics(outcome), /耗时 146.8 秒 · 交互 17 轮 · 总 token 1,200/);
  assert.match(metrics(outcome), /缓存输入 800，已含在输入中/);
  assert.match(metrics(outcome, 'en'), /Model responses 17 · Total tokens 1,200/);
  assert.match(metrics({...outcome,status:'timeout'}), /总 token 1,200/);
  assert.match(metrics({elapsed_s:0,stats:{turns_used:0,total_input_tokens:0,total_output_tokens:0}}),
    /耗时 0.0 秒 · 交互 0 轮 · 总 token 0/);
  assert.match(metrics(null), /耗时 未记录 · 交互 未记录 轮 · 总 token 未记录/);
  assert.match(metrics({stats:{total_input_tokens:100}}), /总 token 未记录/);
  assert.match(metrics({stats:{total_input_tokens:-1,total_output_tokens:200}}), /总 token 未记录/);
  assert.equal(times({}), '开始：未记录 · 结束：未记录');
  assert.equal(times({manifest:{started_at:'bad'}}), '开始：未记录 · 结束：未记录');
  const start = '2026-11-03T00:00:00Z', end = '2026-11-03T00:01:00Z';
  assert.equal(times({manifest:{started_at:start},outcome:{ended_at:end}}),
    `开始：${new Date(start).toLocaleString()} · 结束：${new Date(end).toLocaleString()}`);
})().catch(error => {console.error(error); process.exitCode=1;});
"""
    result = subprocess.run(
        [node, "-e", script, str(source)], text=True, capture_output=True, timeout=20
    )
    assert result.returncode == 0, result.stdout + result.stderr
