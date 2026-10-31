# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Regression checks for official task results in the live console."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_live_badge_uses_official_result_and_rejects_stale_responses():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the browser contract check")
    source = Path(__file__).resolve().parents[4] / "rpent/dashboard/static/dashboard.js"
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const functions = source.slice(source.indexOf('function setResult('), source.indexOf('function renderTimeline('));
const badge = {style:{}};
let calls=0, response;
const context = vm.createContext({
  $: () => badge,
  copy: {solved:'success', notSolved:'failure', resultLoading:'loading', resultUnknown:'unknown'},
  requestJSON: async () => { calls++; return await response(); },
});
vm.runInContext(functions, context);
const update = context.updateResult;
const snapshot = {workbench:true, run_id:'passed', server_id:'server', state:'succeeded', terminated:false};
const result = (id, success) => ({id, outcome:{ended_at:'now', environment_success:success}});
(async () => {
  response = () => result('passed', true);
  await update(snapshot);
  assert.equal(badge.textContent, 'success');
  assert.equal(badge.className, 'badge b-ok');
  await update(snapshot);
  assert.equal(calls, 1); // Polling does not repeatedly load the run directory.
  response = () => result('failed', false);
  await update({...snapshot,run_id:'failed',terminated:true});
  assert.equal(badge.textContent, 'failure'); // Even when execution/termination succeeded.
  response = () => result('unknown', null);
  await update({...snapshot,run_id:'unknown'});
  assert.equal(badge.textContent, 'unknown');
  response = () => { throw new Error('offline'); };
  await update({...snapshot,run_id:'retry'});
  assert.equal(badge.textContent, 'unknown');
  response = () => result('retry', true);
  await update({...snapshot,run_id:'retry'});
  assert.equal(badge.textContent, 'success');
  let resolveOld;
  response = () => new Promise(resolve => {resolveOld=resolve;});
  const pending = update({...snapshot,run_id:'old'});
  const count = calls;
  await update({...snapshot,run_id:'old'});
  assert.equal(calls,count); // No overlapping requests for the same result.
  await update({...snapshot,run_id:'new',state:'running'});
  assert.equal(badge.style.display,'none');
  resolveOld(result('old',true));
  await pending;
  assert.equal(badge.style.display,'none'); // An old response cannot label the next run.
  response = () => result('passed',false);
  await update({...snapshot,server_id:'restarted'});
  assert.equal(badge.textContent,'failure');
  await update({...snapshot,workbench:false,terminated:true});
  assert.equal(badge.textContent,'success'); // Legacy non-workbench behavior is preserved.
})().catch(error => { console.error(error); process.exitCode=1; });
"""
    result = subprocess.run(
        [node, "-e", script, str(source)],
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
