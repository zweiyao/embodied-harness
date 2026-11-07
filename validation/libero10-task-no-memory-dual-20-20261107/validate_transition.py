"""Check timeout cohorts and adoption without dispatching real experiments."""
import copy
import importlib.util
import json
from pathlib import Path
import py_compile
import sys
import tempfile

ROOT = Path('/home/zwy/work/embodied_harness/experiments/libero10-task-no-memory-dual-20-20261107')
sys.path.insert(0,str(ROOT))
py_compile.compile(str(ROOT/'run_batch.py'),doraise=True)
spec=importlib.util.spec_from_file_location('batch_transition',ROOT/'run_batch.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
for budget in [300,1500]:
 for prefix in ['planner','Codex SDK']:
  assert m.classify({'status':'timeout','error':f'{prefix} timed out after {budget}s','elapsed_s':budget},budget)==('budget_timeout',False)
assert m.classify({'status':'timeout','error':'planner timed out after 300s','elapsed_s':10},300)==('unexpected',None)
assert m.classify({'status':'timeout','error':'planner timed out after 300s','elapsed_s':310},1500)==('unexpected',None)
assert m.classify({'status':'completed','environment_success':True},300)==('task_result',True)
real_config=copy.deepcopy(m.PLAN['lanes']['qwen']['config'])
old_sleep=m.time.sleep
checks=[]
for mode in ['active','completed-unrecorded','new-300']:
 with tempfile.TemporaryDirectory() as directory:
  root=Path(directory);(root/'qwen').mkdir();task=5 if mode=='new-300' else 4
  m.ROOT=root;m.PLAN={'tasks':[task],'material_version':'test','budget':{'planner_timeout_s':1500},'budget_overrides':{'qwen':{'from_task':5,'planner_timeout_s':300}},'lanes':{'qwen':{'port':1,'config':copy.deepcopy(real_config)}}}
  m.unchanged=lambda:None;m.aggregate=lambda:None;m.validate_run=lambda run:{'memory_audit_passed':True};m.time.sleep=lambda seconds:None
  cfg=copy.deepcopy(real_config);calls=[];state_reads=0;runs=[]
  def completed_run():
   budget=cfg['planner_timeout_s']
   return {'id':'test','path':str(root/'run'),'config':{'planner_timeout_s':budget,'task':{'suite':'libero_10_task','task':task,'seed':0}},'outcome':{'status':'timeout','error':f'planner timed out after {budget}s','elapsed_s':budget+1,'stats':{},'environment_success':False}}
  if mode!='new-300':runs=[completed_run()]
  def api(port,path,data=None,timeout=30):
   nonlocal_placeholder=None
   global state_reads,cfg,runs
   calls.append((path,data))
   if path=='/api/session/state':
    state_reads+=1
    return {'server_id':'same','session_state':'running' if mode=='active' and state_reads<=2 else 'ready'}
   if path=='/api/session/config':
    if data:cfg.update(data)
    return copy.deepcopy(cfg)
   if path=='/api/runs':
    output=copy.deepcopy(runs)
    if mode=='active' and state_reads<=2:output[0]['outcome']=None
    return {'runs':output}
   if path=='/api/session/messages':runs=[completed_run()];return {}
   raise AssertionError(path)
  m.api=api
  m.run_lane('qwen')
  status=json.loads((root/'qwen/status.json').read_text());assert status['phase']=='completed', status
  rows=json.loads((root/'qwen/results.json').read_text());assert len(rows)==1
  assert rows[0]['planner_timeout_s']==(300 if mode=='new-300' else 1500)
  assert rows[0]['classification']=='budget_timeout'
  dispatches=sum(path=='/api/session/messages' for path,data in calls)
  assert dispatches==(1 if mode=='new-300' else 0)
  assert sum(path=='/api/session/config' and data is not None for path,data in calls)==(1 if mode=='new-300' else 0)
  checks.append({'case':mode,'passed':True,'dispatches':dispatches,'recorded_budget_s':rows[0]['planner_timeout_s']})
m.time.sleep=old_sleep
report={'passed':True,'timeout_classification_cases':7,'adoption_and_next_task_cases':checks,'runtime_harness_modified':False,'active_episode_interrupted':False}
(ROOT/'budget-change-validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
