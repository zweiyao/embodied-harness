import json,pathlib,urllib.request,subprocess,time,os,signal,importlib.util
ROOT=pathlib.Path(__file__).resolve().parent
OLD=pathlib.Path(json.loads((ROOT/'transition-source.json').read_text())['old_directory'])
UNIT='rpent-qwenflash-3000s-50-20261106.service'
def save(p,d):
 t=p.with_suffix('.tmp');t.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n');t.replace(p)
def api(p,d=None,timeout=30):
 req=urllib.request.Request('http://127.0.0.1:8092'+p,data=None if d is None else json.dumps(d).encode(),headers={'Content-Type':'application/json'})
 return json.load(urllib.request.urlopen(req,timeout=timeout))
def stop_old():
 pid=json.loads((ROOT/'transition-source.json').read_text())['old_pid']
 subprocess.run(['systemctl','--user','kill','--kill-whom=main','--signal=SIGTERM',UNIT],check=True)
 try:os.kill(pid,signal.SIGCONT)
 except ProcessLookupError:pass
 subprocess.run(['systemctl','--user','stop',UNIT],check=True)
def main():
 source=json.loads((ROOT/'transition-source.json').read_text());st=source['old_status'];rid=st['run_id']
 spec=importlib.util.spec_from_file_location('batch',OLD/'run_batch.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 for _ in range(420):
  state=api('/api/session/state');run=next(x for x in api('/api/runs')['runs'] if x['id']==rid)
  if run['outcome'] and state['session_state']=='ready':break
  time.sleep(10)
 else:raise TimeoutError('Current episode did not finalize; no forced experiment abort')
 o=run['outcome'];stats=o.get('stats',{});classification,success=m.classify_outcome(o,3000)
 row={k:st[k] for k in ['task','seed']};row.update(run_id=rid,path=run['path'],official_success=o.get('environment_success'),status=o.get('status'),error=o.get('error'),elapsed_s=o.get('elapsed_s'),turns=stats.get('turns_used'),input_tokens=stats.get('total_input_tokens'),cached_input_tokens=stats.get('total_cached_input_tokens'),output_tokens=stats.get('total_output_tokens'),classification=classification,evaluation_success=success,actions=o.get('actions'))
 rows=json.loads((OLD/'results.json').read_text());assert not any(r['run_id']==rid for r in rows)
 if classification=='unexpected':
  f=OLD/'incidents.json';inc=json.loads(f.read_text()) if f.exists() else [];inc.append(row);save(f,inc)
 else:
  rows.append(row);save(OLD/'results.json',rows)
 save(OLD/'summary.json',{'completed':len(rows),'planned':50,'successes':sum(r['evaluation_success'] is True for r in rows),'per_task':{str(t):{'completed':sum(r['task']==t for r in rows),'successes':sum(r['task']==t and r['evaluation_success'] is True for r in rows)} for t in range(10)}})
 save(OLD/'status.json',{'phase':'stopped','reason':'user requested subsequent episodes at 1500 seconds','completed':len(rows),'incident':classification=='unexpected'})
 stop_old()
 assert json.loads((OLD/'restoration.json').read_text())['restored']
 if classification=='unexpected':raise RuntimeError('Current 3000s episode had an incident; excluded; inspect before continuation')
 c=api('/api/session/config');assert c['planner_timeout_s']==3000
 c['planner_timeout_s']=1500;payload={k:c[k] for k in ['model_profile','tools','max_turns','max_tokens','planner_timeout_s']}
 save(ROOT/'original-config.json',c);save(ROOT/'restore-config.json',payload)
 drop=pathlib.Path((ROOT/'dropin-path.txt').read_text());assert not drop.exists()
 drop.write_text('[Service]\nExecStart=\nExecStart=/bin/bash '+str(ROOT/'start-direct.sh')+'\n')
 subprocess.run(['systemctl','--user','daemon-reload'],check=True);subprocess.run(['systemctl','--user','restart','embodied-manual-workbench.service'],check=True)
 for _ in range(60):
  try:api('/api/session/config',payload);break
  except Exception:time.sleep(2)
 else:raise RuntimeError('Dashboard restart failed')
 assert api('/api/session/config')==c
 check=api('/api/llm/check',{'model_profile':'qwen3.8-flash'},90);save(ROOT/'connectivity.json',{k:check.get(k) for k in ['ok','status','detail','checked_at','latency_s']});assert check['ok'], 'Model probe failed'
 save(ROOT/'transition-result.json',{'prior_3000s_completed':len(rows),'prior_successes':sum(r['evaluation_success'] is True for r in rows),'remaining':50-len(rows),'timeout_s':1500,'current_episode_preserved':row,'old_proxy_restored_before_new_batch':True})
 subprocess.run(['systemd-run','--user','--unit=rpent-qwenflash-1500s-continuation-20261106','--property=ExecStopPost=/usr/bin/python3 '+str(ROOT/'restore.py'),'/usr/bin/python3','-u',str(ROOT/'run_batch.py')],check=True)
if __name__=='__main__':
 try:main()
 except Exception as e:
  save(ROOT/'transition-error.json',{'error':str(e),'time':time.time()})
  raise
