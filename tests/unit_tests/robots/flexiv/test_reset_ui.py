# Copyright 2026 The RPent Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Run the shared operator button against mocked HTTP, never robot hardware."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_reset_button_confirmation_failure_and_duplicate_clicks():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the browser module contract check")
    source = (
        Path(__file__).resolve().parents[4] / "rpent/dashboard/static/flexiv-reset.js"
    )
    script = r"""
import assert from 'node:assert/strict';
import fs from 'node:fs';
const source = fs.readFileSync(process.argv[1], 'utf8');
const {resetControl} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const ready = {control_backend:'rdk',reset_available:true,reset_reason:''};
const preview = {available:true,target_tcp_pose:[.4,0,.2,1,0,0,0],joint_velocity_scale:30,current:{gripper_width_m:.003,ext_wrench_in_world:[0,0,14,0,0,0]}};
let calls = [], accepted = false, confirmations = 0, refreshes = 0;
let resetReply = {reached:true,elapsed_s:1.2}, resetOk = true;
globalThis.confirm = text => {
  confirmations++;
  assert.match(text, /MoveJ/);
  assert.match(text, /保持夹爪开度/);
  assert.match(text, /工件已脱离槽口/);
  return accepted;
};
globalThis.fetch = async (url, options) => {
  calls.push([url,options?.method || 'GET']);
  return {ok:url.endsWith('home-preview') || resetOk,json:async()=>url.endsWith('home-preview') ? preview : resetReply};
};
const button = {}, message = {};
const control = resetControl(button,message,async()=>{ refreshes++; });
control.update({...ready,reset_available:false,reset_reason:'请先启用机械臂'});
await button.onclick();
assert.equal(calls.length,0);
assert.equal(button.disabled,true);
control.update(ready);
await button.onclick();
assert.deepEqual(calls,[['/api/flexiv/home-preview','GET']]);
assert.match(message.textContent,/已取消/);
accepted = true; calls = [];
await button.onclick();
assert.deepEqual(calls,[['/api/flexiv/home-preview','GET'],['/api/flexiv/reset-home','POST']]);
assert.match(message.textContent,/复位完成/);
resetOk = false; resetReply = {error:'Robot is not armed'}; calls = [];
await button.onclick();
assert.equal(calls.length,2);
assert.match(message.textContent,/not armed/);
assert.match(message.textContent,/不会自动重试/);
let release;
globalThis.fetch = async url => {
  calls.push(url);
  return new Promise(resolve=>{ release=()=>resolve({ok:true,json:async()=>preview}); });
};
calls=[]; accepted=false;
const pending=button.onclick();
control.update(ready);
assert.equal(button.disabled,true);
await button.onclick();
assert.equal(calls.length,1);
release(); await pending;
assert.equal(confirmations,4);
assert.equal(refreshes,4);
control.update({control_backend:'collector'});
assert.equal(button.hidden,true);
"""
    result = subprocess.run(
        [node, "--input-type=module", "-e", script, str(source)],
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
