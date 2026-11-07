"""Two approved independent workbenches; each lane runs ten fresh episodes."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import threading
import time
import urllib.request
from metrics import analyze, summarize

ROOT = Path(__file__).resolve().parent
PLAN = json.loads((ROOT/'plan.json').read_text())
INVARIANTS = json.loads((ROOT/'invariants.json').read_text())
LOCK = threading.Lock()

def save(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    tmp.replace(path)

def api(port, path, data=None, timeout=30):
    req = urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req,timeout=timeout) as response:
        return json.load(response)

def unchanged():
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in INVARIANTS['source_hashes'].items()), 'Protected source or material changed'

def aggregate():
    with LOCK:
        rows = []
        states = {}
        for name in PLAN['lanes']:
            lane = ROOT/name
            if (lane/'results.json').exists():rows += json.loads((lane/'results.json').read_text())
            if (lane/'status.json').exists():states[name] = json.loads((lane/'status.json').read_text())
        save(ROOT/'results.json',rows)
        summaries = {}
        for name in PLAN['lanes']:
            lane_rows = [r for r in rows if r['lane']==name]
            budgets = sorted({r['planner_timeout_s'] for r in lane_rows})
            summaries[name] = {**summarize(lane_rows), 'budgets_s':budgets, 'mixed_budget':len(budgets)>1, 'cohorts':{str(b):summarize([r for r in lane_rows if r['planner_timeout_s']==b]) for b in budgets}}
        save(ROOT/'summary.json',summaries)
        phases = [v['phase'] for v in states.values()]
        phase = 'completed' if len(phases)==2 and all(p=='completed' for p in phases) else 'stopped' if len(phases)==2 and all(p in ['completed','stopped'] for p in phases) else 'running'
        save(ROOT/'status.json',{'phase':phase,'completed':len(rows),'planned':20,'lanes':states})

def classify(outcome, timeout=None):
    if timeout is None:
        timeout = PLAN['budget']['planner_timeout_s']
    if outcome.get('status')=='timeout' and outcome.get('error') in {f'planner timed out after {timeout:g}s',f'Codex SDK timed out after {timeout:g}s'} and (outcome.get('elapsed_s') or 0)>=timeout:
        return 'budget_timeout',False
    if outcome.get('error') or outcome.get('status') not in ['completed','budget_exhausted'] or type(outcome.get('environment_success')) is not bool:
        return 'unexpected',None
    return 'task_result',outcome['environment_success']

def validate_run(run):
    path = Path(run['path']).resolve()
    assert path.is_relative_to(ROOT), 'Wrong run root'
    manifest = json.loads((path/'language-materials/manifest.json').read_text())
    expected = json.loads((Path(PLAN['materials'])/'manifest.json').read_text())
    assert manifest==expected
    assert all(hashlib.sha256((path/'language-materials'/n).read_bytes()).hexdigest()==h for n,h in manifest['files'].items())
    assert [p.relative_to(path/'language-materials/memory').as_posix() for p in (path/'language-materials/memory').rglob('*') if p.is_file()]==['MEMORY.md']
    return analyze(path)

def run_lane(name):
    lane = ROOT/name
    settings = PLAN['lanes'][name]
    port, config = settings['port'], settings['config']
    rows = json.loads((lane/'results.json').read_text()) if (lane/'results.json').exists() else []
    assert [r['task'] for r in rows]==PLAN['tasks'][:len(rows)], 'Resume must match completed prefix'
    initial = api(port,'/api/session/state')
    try:
        for task in PLAN['tasks'][len(rows):]:
            unchanged()
            override = PLAN.get('budget_overrides', {}).get(name, {})
            config = dict(settings['config'])
            if override and task >= override['from_task']:
                config['planner_timeout_s'] = override['planner_timeout_s']
            state = api(port,'/api/session/state')
            assert state['server_id']==initial['server_id']
            existing = api(port,'/api/runs')['runs']
            recorded = {r['path'] for r in rows}
            pending = [r for r in existing if r['path'] not in recorded]
            assert len(pending)<=1, 'Multiple unrecorded runs; inspect before continuing'
            if pending:
                adopted = pending[0]
                t = adopted['config']['task']
                assert (t['suite'],t['task'],t['seed'])==('libero_10_task',task,0)
                assert adopted['config']['planner_timeout_s']==config['planner_timeout_s'], 'Pending episode budget mismatch'
                assert api(port,'/api/session/config')==config, 'Do not change an active episode configuration'
                known = {r['id'] for r in existing if r['id']!=adopted['id']}
                previous = json.loads((lane/'status.json').read_text()) if (lane/'status.json').exists() else {}
                elapsed = previous.get('elapsed_s',0) if previous.get('task')==task else 0
                started = time.monotonic()-elapsed
                save(lane/'status.json',{'phase':'running','task':task,'seed':0,'completed':len(rows),'run_id':adopted['id'],'elapsed_s':elapsed,'adopted_existing':True,'planner_timeout_s':config['planner_timeout_s']})
            else:
                assert state['session_state']=='ready'
                payload = {k:v for k,v in config.items() if k in ['model_profile','tools','max_turns','max_tokens','planner_timeout_s']}
                api(port,'/api/session/config',payload)
                assert api(port,'/api/session/config')==config
                known = {r['id'] for r in existing}
                started = time.monotonic()
                save(lane/'status.json',{'phase':'starting','task':task,'seed':0,'completed':len(rows),'planner_timeout_s':config['planner_timeout_s']})
                api(port,'/api/session/messages',{'text':f'/rpent-task libero_10_task {task} 0'})
            aggregate()
            while time.monotonic()-started<2400:
                time.sleep(10)
                state = api(port,'/api/session/state')
                assert state['server_id']==initial['server_id'], 'Dashboard restarted'
                fresh = [r for r in api(port,'/api/runs')['runs'] if r['id'] not in known]
                assert len(fresh)<=1, 'Concurrent run on same lane'
                run = fresh[0] if fresh else None
                save(lane/'status.json',{'phase':'running','task':task,'seed':0,'completed':len(rows),'run_id':run['id'] if run else None,'elapsed_s':round(time.monotonic()-started,1),'planner_timeout_s':config['planner_timeout_s']})
                aggregate()
                if run:
                    t = run['config']['task']
                    assert (t['suite'],t['task'],t['seed'])==('libero_10_task',task,0)
                    if run['outcome'] and state['session_state']=='ready':break
                if not run and state.get('error'):raise RuntimeError(state['error'])
            else:raise TimeoutError('Episode did not finalize; no blind retry or kill')
            outcome = run['outcome']
            classification, success = classify(outcome, config['planner_timeout_s'])
            row = {'lane':name,'task':task,'seed':0,'run_id':run['id'],'path':run['path'],'classification':classification,'evaluation_success':success,'official_success':outcome.get('environment_success'),'status':outcome.get('status'),'error':outcome.get('error'),'elapsed_s':outcome.get('elapsed_s'),'stats':outcome.get('stats',{}),'actions':outcome.get('actions'),'material_version':PLAN['material_version'],'planner_timeout_s':config['planner_timeout_s']}
            if classification!='unexpected':
                try:
                    row['metrics']=validate_run(run)
                    assert row['metrics']['memory_audit_passed'], 'Read outside current run; empty-memory contamination or unsupported access'
                except Exception as exc:
                    row.update(classification='unexpected',evaluation_success=None,audit_error=str(exc))
            if row['classification']=='unexpected':
                p=lane/'incidents.json'
                incidents=json.loads(p.read_text()) if p.exists() else []
                save(p,incidents+[row])
                raise RuntimeError(f'Task {task} unexpected incident excluded; diagnose before retry')
            rows.append(row)
            save(lane/'results.json',rows)
            unchanged()
            aggregate()
        save(lane/'status.json',{'phase':'completed','completed':len(rows)})
    except Exception as exc:
        previous = json.loads((lane/'status.json').read_text()) if (lane/'status.json').exists() else {}
        save(lane/'status.json',{**previous,'phase':'stopped','completed':len(rows),'error':str(exc)})
    finally:
        aggregate()

if __name__=='__main__':
    assert (ROOT/'preflight.json').exists(), 'Preflight required'
    preflight=json.loads((ROOT/'preflight.json').read_text())
    assert preflight['passed']
    if PLAN.get('budget_overrides'):
        assert json.loads((ROOT/'budget-change-validation.json').read_text())['passed']
    unchanged()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(run_lane,name) for name in PLAN['lanes']]
        for future in futures:future.result()
    aggregate()
