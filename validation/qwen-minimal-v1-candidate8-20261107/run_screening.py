"""Run the user-requested candidate-only screening through the existing workbench."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
PLAN = json.loads((ROOT / 'plan.json').read_text())
INVARIANTS = json.loads((ROOT / 'invariants.json').read_text())
UNIT = 'embodied-manual-workbench.service'

def save(name, value):
    p = ROOT / name
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(p)

def api(path, data=None, timeout=30):
    req = urllib.request.Request('http://127.0.0.1:8092' + path, data=None if data is None else json.dumps(data).encode(), headers={'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=timeout))

def unchanged():
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in INVARIANTS['source_hashes'].items()), 'Protected source/material/config changed'

def metrics(path):
    # Secondary diagnostics; none replace the official success predicate.
    turns = 0
    first = None
    counts = {}
    errors = 0
    residuals = []
    actions = {'move_to','move_pose','pi0_pick','pi0_doubled','set_gripper','release','rotate_pitch','rotate_wrist'}
    for line in (Path(path) / 'events.jsonl').read_text().splitlines():
        e = json.loads(line)
        p = e['payload']
        if e['kind'] == 'model_request':
            turns += 1
        if e['kind'] == 'tool_request':
            name = p['name']
            counts[name] = counts.get(name, 0) + 1
            if name in actions and first is None:
                first = turns
        if e['kind'] == 'tool_response' and isinstance(p.get('result'), dict):
            result = p['result']
            errors += bool(result.get('errors') or str(result.get('error','')).startswith('bad arguments'))
            motion = (result.get('log') or {}).get('result') or {}
            if motion.get('final_dist_m') is not None:
                residuals.append(motion['final_dist_m'])
    return {'first_action_request':first,'tool_calls':counts,'argument_errors':errors,'movement_residuals_m':residuals}

def main():
    results = json.loads((ROOT / 'results.json').read_text()) if (ROOT / 'results.json').exists() else []
    assert [(r['condition'], r['task'], r['seed']) for r in results] == [(t['condition'], t['task'], t['seed']) for t in PLAN['trials'][:len(results)]], 'Completed cells must be an exact plan prefix'
    assert api('/api/session/state')['session_state'] == 'ready'
    for index, trial in enumerate(PLAN['trials']):
        if index < len(results):
            continue
        unchanged()
        assert api('/api/session/state')['session_state'] == 'ready'
        save('status.json', {'phase':'switching','index':index,'completed':len(results),**trial})
        workbench = json.loads((ROOT / 'original-workbench.json').read_text())
        workbench['language_materials'] = PLAN['materials'][trial['condition']]
        workbench['runs_root'] = str(ROOT / 'runs')
        save('active-workbench.json', workbench)
        drop = Path((ROOT / 'dropin-path.txt').read_text())
        expected_drop = '[Service]\nExecStart=\nExecStart=/bin/bash ' + str(ROOT / 'start-experiment.sh') + '\n'
        if drop.exists():
            assert drop.read_text() == expected_drop
        else:
            drop.write_text(expected_drop)
        subprocess.run(['systemctl','--user','daemon-reload'], check=True)
        subprocess.run(['systemctl','--user','restart',UNIT], check=True)
        payload = json.loads((ROOT / 'restore-config.json').read_text())
        for _ in range(60):
            try:
                api('/api/session/config', payload)
                break
            except Exception:
                time.sleep(2)
        else:
            raise RuntimeError('Dashboard did not become ready')
        assert api('/api/session/config') == INVARIANTS['config']
        check = api('/api/llm/check', {'model_profile':'qwen3.8-flash'}, timeout=90)
        cell = ROOT / 'cells' / f'{index:02d}_{trial["condition"]}_t{trial["task"]}_s{trial["seed"]}'
        cell.mkdir(parents=True)
        (cell / 'connectivity.json').write_text(json.dumps({k:check.get(k) for k in ['ok','status','detail','checked_at','latency_s']}))
        assert check['ok'], 'Model connectivity failed; no experiment dispatched'
        (cell / 'cell.json').write_text(json.dumps({**trial,'materials':workbench['language_materials']}))
        save('status.json', {'phase':'running','index':index,'completed':len(results),'cell':str(cell),**trial})
        env = {**os.environ,'RPENT_CELL_ROOT':str(cell)}
        result = subprocess.run(['/usr/bin/python3','-u',str(ROOT / 'run_cell.py')],env=env,stdout=(cell/'batch.log').open('w'),stderr=subprocess.STDOUT)
        if result.returncode:
            if (cell / 'incidents.json').exists():
                save('incidents.json', [{**r,'condition':trial['condition']} for r in json.loads((cell/'incidents.json').read_text())])
            raise RuntimeError('Cell stopped; inspect preserved incident/log before retry: ' + str(cell))
        row, = json.loads((cell / 'results.json').read_text())
        run = Path(row['path'])
        frozen = json.loads((run/'language-materials/manifest.json').read_text())
        expected_manifest = json.loads((Path(workbench['language_materials'])/'manifest.json').read_text())
        assert frozen == expected_manifest
        assert all(hashlib.sha256((run/'language-materials'/n).read_bytes()).hexdigest()==h for n,h in frozen['files'].items())
        row.update(condition=trial['condition'],material_version=frozen['version'],diagnostics=metrics(row['path']))
        results.append(row)
        save('results.json', results)
        save('summary.json', {c:{'completed':sum(r['condition']==c for r in results),'successes':sum(r['condition']==c and r['evaluation_success'] is True for r in results)} for c in ['candidate']})
        unchanged()
    assert len(results)==len(PLAN['trials']) and len({(r['condition'],r['task'],r['seed']) for r in results})==len(PLAN['trials'])
    save('status.json', {'phase':'completed','completed':len(results)})

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        previous=json.loads((ROOT/'status.json').read_text()) if (ROOT/'status.json').exists() else {}
        save('status.json', {**previous,'phase':'stopped','error':str(e)})
        raise
