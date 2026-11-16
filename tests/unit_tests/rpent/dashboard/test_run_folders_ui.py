# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Run folders preserve records and separate environments and task suites."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_run_folders():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the browser contract check")
    source = (
        Path(__file__).resolve().parents[4] / "rpent/dashboard/static/run-folders.js"
    )
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
(async () => {
  const {groupRuns} = await import('data:text/javascript;base64,' +
    Buffer.from(fs.readFileSync(process.argv[1], 'utf8')).toString('base64'));
  const run = (id, robot, task, updated) => ({id, config:{robot,task}, updated});
  const profiles = [{robot:'robodojo',label:'RoboDojo',task_fields:[
    {name:'task',options:[['align_blocks','align_blocks'],['arrange_numbers','arrange_numbers']]}]}];
  const runs = [
    run('older','robodojo',{task:'align_blocks',layout:0},1),
    run('other-task','robodojo',{task:'arrange_numbers'},3),
    run('newer','robodojo',{task:'align_blocks',layout:1},4),
    run('libero-a','libero',{suite:'object',task:0},2),
    run('libero-b','libero',{suite:'spatial',task:0},2),
    run('task10','libero',{suite:'object',task:10},2),
    run('task2','libero',{suite:'object',task:2},2),
    run('legacy',null,{},2),
    run('missing',null,null,2),
    run('physical','flexiv',{instruction:'Insert USB'},2),
  ];
  const original = JSON.stringify(runs);
  const folders = groupRuns(runs, profiles, 'robodojo');
  const dojo = folders.find(f => f.label === 'RoboDojo');
  assert.equal(dojo.tasks[0].label, 'task 0 · align_blocks');
  assert.deepEqual(dojo.tasks[0].runs.map(r => r.id), ['newer','older']);
  assert.equal(dojo.tasks[1].label, 'task 1 · arrange_numbers');
  assert.deepEqual(dojo.tasks.find(t => t.label === '未记录任务').runs.map(r=>r.id), ['legacy','missing']);
  const libero = folders.find(f => f.label === 'libero');
  assert.deepEqual(libero.tasks.map(t => t.label), [
    'object / task 0','object / task 2','object / task 10','spatial / task 0']);
  assert.equal(folders.find(f => f.label === 'flexiv').tasks[0].label, 'Insert USB');
  assert.deepEqual(folders.flatMap(f=>f.tasks.flatMap(t=>t.runs.map(r=>r.id))).sort(), runs.map(r=>r.id).sort());
  assert.equal(JSON.stringify(runs), original);
  assert.deepEqual(groupRuns([], profiles), []);
  assert.equal(groupRuns([run('old',null,0,0)])[0].tasks[0].label, 'task 0');
  assert.equal(groupRuns([run('old',null,0,0)])[0].label, '未记录环境');
})().catch(error => {console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        [node, "-e", script, str(source)], text=True, capture_output=True, timeout=20
    )
    assert result.returncode == 0, result.stdout + result.stderr
