# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Native task fields preserve IDs, dependencies and copied configurations."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_native_task_picker():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the browser contract check")
    source = (
        Path(__file__).resolve().parents[4] / "rpent/dashboard/static/task-picker.js"
    )
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
class Element {
  constructor() { this.children=[]; this.value=''; this.listeners={}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; this.value=String(nodes[0]?.value??''); }
  addEventListener(name, handler) { this.listeners[name]=handler; }
}
global.document={createElement:()=>new Element()};
global.Option=class {constructor(label,value){this.label=label;this.value=String(value);}};
(async()=>{
  const {renderTaskFields}=await import('data:text/javascript;base64,'+Buffer.from(fs.readFileSync(process.argv[1],'utf8')).toString('base64'));
  const root=new Element(), fields=[
    {name:'task',label:'Task',options:[['task_a','Task A'],['task_b','Task B']]},
    {name:'layout',label:'Layout',depends_on:'task',options_by:{task_a:[[0,'0'],[1,'1']],task_b:[[0,'0'],[34,'34']]}}
  ], spec={command:'/rpent-task',fields:[{name:'task'},{name:'layout'}]};
  let changes=0;
  const picker=renderTaskFields(root,fields,spec,()=>changes++);
  assert.equal(picker.command(),'/rpent-task task_a 0');
  const task=root.children[0].children[0], layout=root.children[1].children[0];
  task.value='task_b';task.listeners.change();
  assert.deepEqual(layout.children.map(o=>o.value),['0','34']);
  picker.restore({task:'task_b',layout:34});
  assert.equal(picker.command(),'/rpent-task task_b 34');
  assert.throws(()=>picker.restore({task:'task_b',layout:1}),/历史任务字段不可用/);
  assert.throws(()=>renderTaskFields(new Element(),fields,{...spec,fields:[{name:'seed'}]},()=>{}),/任务字段与服务器命令不一致/);
  assert.ok(changes>=2);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        [node, "-e", script, str(source)], text=True, capture_output=True, timeout=20
    )
    assert result.returncode == 0, result.stdout + result.stderr
