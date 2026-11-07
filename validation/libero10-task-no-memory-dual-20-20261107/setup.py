"""Prepare the explicitly approved two-lane experiment; never edit core source."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import urllib.request

ROOT = Path('/home/zwy/work/embodied_harness/experiments/libero10-task-no-memory-dual-20-20261107')
BASE = Path('/home/zwy/work/embodied_harness')
SOURCE = Path('/home/zwy/work/harnessvla')
assert not ROOT.exists(), 'Do not overwrite an existing batch'
ROOT.mkdir()
def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    path.chmod(0o600)
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
def api(path):
    return json.load(urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:8092'+path, timeout=15))
original_state = api('/api/session/state')
assert original_state['session_state']=='ready'
original_config = api('/api/session/config')
original_wb_path = BASE/'native-rpent/workbench.json'
original = json.loads(original_wb_path.read_text())
old_materials = BASE/'language-materials/v1'
manifest_old = json.loads((old_materials/'manifest.json').read_text())
assert all(sha(old_materials/n)==h for n,h in manifest_old['files'].items())
materials = BASE/'language-materials/v1-empty-memory'
assert not materials.exists()
(materials/'memory').mkdir(parents=True)
for name in ['system.md','user.md','guide.md']:
    shutil.copyfile(old_materials/name, materials/name)
(materials/'memory/MEMORY.md').write_text('# Experience index\n\nNo experience entries are available in this experiment.\n')
files = {p.relative_to(materials).as_posix():sha(p) for p in sorted(materials.rglob('*')) if p.is_file()}
version = 'v1-empty-memory-'+hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:12]
save(materials/'manifest.json', {'version':version,'files':files})
for p in materials.rglob('*'):
    if p.is_file():p.chmod(0o444)
pid = subprocess.check_output(['systemctl','--user','show','embodied-manual-workbench.service','-p','MainPID','--value'],text=True).strip()
environ = dict(x.split(b'=',1) for x in Path('/proc/'+pid+'/environ').read_bytes().split(b'\0') if b'=' in x)
network_keys = ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy','NO_PROXY','no_proxy']
network = {k:environ[k.encode()].decode() for k in network_keys if k.encode() in environ}
protected = [p for folder in [SOURCE/'robots/libero',SOURCE/'rpent',old_materials,materials] for p in folder.rglob('*') if p.is_file() and (p.suffix in ['.py','.md','.json'] or folder in [old_materials,materials]) and '__pycache__' not in str(p)]
protected += [original_wb_path,BASE/'native-rpent/start-workbench.sh',BASE/'tool-catalog.json']
save(ROOT/'invariants.json',{'source_hashes':{str(p):sha(p) for p in protected},'original_config':original_config,'original_server_id':original_state['server_id'],'original_network':network})
plan={'approved':True,'approval':'User: 开始实验, after reviewing empty-library dual-lane proposal','suite':'libero_10_task','tasks':list(range(10)),'seed':0,'total':20,'materials':str(materials),'material_version':version,'baseline_material_version':manifest_old['version'],'system_user_guide_byte_identical':True,'budget':{'max_turns':30,'max_tokens':16384,'planner_timeout_s':1500},'tools':original_config['tools'],'memory_profile':'local','planners_differ':'Astra Codex SDK; Qwen API. Tool-request counts are common metric, model-request counts are not interchangeable.','unexpected':'Preserve and exclude; stop affected lane, diagnose/fix before retry same task/seed. Full budget timeout counts as failure.','lanes':{}}
assert len(plan['tools'])==17
ports=[]
for name,profile in [('qwen','qwen3.8-flash'),('astra','gpt-6-astra')]:
    lane=ROOT/name;lane.mkdir();(lane/'libero-config').mkdir()
    shutil.copyfile(SOURCE/'local-setup/libero-config/config.yaml',lane/'libero-config/config.yaml')
    with socket.socket() as s:
        s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    assert port not in ports;ports.append(port)
    chosen=next(m for m in original['models'] if m['id']==profile)
    wb={**original,'runs_root':str(lane/'runs'),'language_materials':str(materials),'models':[chosen]}
    save(lane/'workbench.json',wb)
    config={**plan['budget'],'tools':plan['tools'],'model_profile':profile,'planner':chosen['planner'],'model':chosen['model'],'reasoning_effort':chosen.get('reasoning_effort','none')}
    unit='rpent-no-memory-'+name+'-20261107.service'
    lane_network=dict(network)
    if name=='qwen':
        for k in ['NO_PROXY','no_proxy']:
            lane_network[k]=','.join(filter(None,[lane_network.get(k,''),'llm-mcmnmslm9fd9hzmt.cn-beijing.maas.aliyuncs.com']))
    script=['#!/usr/bin/env bash','set -euo pipefail','cd '+shlex.quote(str(BASE)),'source '+str(SOURCE/'local-setup/activate.sh'),'export PYTHONPATH='+str(SOURCE)+' HF_HUB_OFFLINE=1','export LIBERO_CONFIG_PATH='+str(lane/'libero-config'),'export RPENT_WORKBENCH='+str(lane/'workbench.json'),'export RPENT_TOOL_CATALOG='+str(BASE/'tool-catalog.json')]
    script += ['export '+k+'='+shlex.quote(v) for k,v in lane_network.items()]
    cmd=['python','-m','rpent.cli.main','--robot','libero','--libero-type','pro','--dashboard','--dashboard-host','127.0.0.1','--dashboard-port',str(port),'--dashboard-language','zh-cn','--planner',chosen['planner'],'--model',chosen['model'],'--memory-profile','local','--memory-dir',str(materials/'memory'),'--vla-endpoint','http://127.0.0.1:49337','--sam3-endpoint','http://127.0.0.1:37867','--max-turns','30','--max-tokens','16384','--planner-timeout-s','1500','--output-dir',str(lane/'runs/session')]
    script+=['exec '+shlex.join(cmd)]
    (lane/'start.sh').write_text('\n'.join(script)+'\n')
    plan['lanes'][name]={'unit':unit,'port':port,'config':config,'network':lane_network}
save(ROOT/'plan.json',plan)
save(ROOT/'status.json',{'phase':'prepared','completed':0,'planned':20})
print(json.dumps({'root':str(ROOT),'version':version,'protected_files':len(protected),'ports':ports}))
