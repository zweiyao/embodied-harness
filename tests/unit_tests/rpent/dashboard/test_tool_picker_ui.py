# Copyright 2026 The RPent Authors.
# Licensed under the Apache License, Version 2.0.
"""Exercise component visibility and selection without a server or hardware."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_catalog_filter_keeps_selection_and_excludes_incompatible_tools():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the browser module contract check")
    source = (
        Path(__file__).resolve().parents[4] / "rpent/dashboard/static/tool-picker.js"
    )
    script = r"""
import assert from 'node:assert/strict';
import fs from 'node:fs';
const source = fs.readFileSync(process.argv[1], 'utf8');
const {renderTools} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
class Element {
  constructor(tag) { this.tag=tag;this.children=[];this.hidden=false; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes; }
}
globalThis.document={createElement:tag=>new Element(tag)};
globalThis.Option=class extends Element {
  constructor(text,value) { super('option');this.textContent=text;this.value=value; }
};
const all=node=>[node,...node.children.flatMap(all)];
const tool=(id,properties={})=>({id,name:id,category:'perception',origin:'native',version:'12345678',description:'Measure observation',validation:'native',selectable:true,...properties});
const catalog=[
  tool('finish',{category:'auxiliary',required:true,source_robot:'shared',supported_environments:['flexiv','univtac']}),
  tool('move_tcp',{category:'control',source_robot:'flexiv',supported_environments:['flexiv']}),
  tool('sensor_v1',{name:'sensor_test',origin:'generated'}),
  tool('sensor_v2',{name:'sensor_test',origin:'generated'}),
  tool('foreign:univtac:move_tcp',{category:'control',name:'move_tcp',selectable:false,source_robot:'univtac',supported_environments:['univtac'],incompatibility_reason:'Requires a simulator controller',availability_note:'Requires a simulator controller'}),
  tool('foreign:univtac:required',{category:'auxiliary',required:true,selectable:false}),
  tool('candidate',{origin:'generated',availability:'candidate'}),
];
const root=new Element('main');
const picker=renderTools(root,catalog,['move_tcp','foreign:univtac:move_tcp','candidate']);
const inputs=all(root).filter(n=>n.tag==='input');
assert.deepEqual(inputs.map(n=>n.value),['move_tcp','sensor_v1','sensor_v2','finish']);
assert.deepEqual(picker.selected(),['move_tcp','finish']);
assert.equal(all(root).filter(n=>n.tag==='article').length,7);
const texts=all(root).map(n=>n.textContent||'').join('\n');
assert.match(texts,/来源：Flexiv 真机/);
assert.match(texts,/来源：UniVTAC/);
assert.match(texts,/本环境不可选：Requires a simulator controller/);
assert.equal(texts.split('Requires a simulator controller').length,2);
picker.select('all');
assert.deepEqual(picker.selected(),['move_tcp','sensor_v2','finish']);
const filter=all(root).find(n=>n.tag==='select');
filter.value='compatible';filter.onchange();
assert.equal(all(root).filter(n=>n.tag==='article'&&!n.hidden).length,4);
assert.deepEqual(picker.selected(),['move_tcp','sensor_v2','finish']);
filter.value='all';filter.onchange();
assert.equal(all(root).filter(n=>n.tag==='article'&&!n.hidden).length,7);
picker.select('none');
assert.deepEqual(picker.selected(),['finish']);
picker.select('native');
assert.deepEqual(picker.selected(),['move_tcp','finish']);
const first=inputs.find(n=>n.value==='sensor_v1');
const second=inputs.find(n=>n.value==='sensor_v2');
first.checked=true;first.onchange();
second.checked=true;second.onchange();
assert.equal(first.checked,false);
assert.equal(second.checked,true);
renderTools(root,catalog,[],false);
assert.equal(all(root).filter(n=>n.tag==='input').length,0);
assert.equal(all(root).filter(n=>n.tag==='article').length,7);
"""
    result = subprocess.run(
        [node, "--input-type=module", "-e", script, str(source)],
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
