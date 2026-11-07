"""Execute the user-requested 50 Qwen Flash trials via the existing dashboard API."""
import hashlib
import json
from pathlib import Path
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:8092'
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def api(path, data=None):
    req = urllib.request.Request(BASE + path, data=None if data is None else json.dumps(data).encode(), headers={'Content-Type': 'application/json'})
    with opener.open(req, timeout=30) as response:
        return json.load(response)

def save(name, value):
    p = ROOT / name
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(p)

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def classify_outcome(outcome, timeout_s):
    """Keep unexpected incidents separate from valid task/budget results."""
    expected_timeout = (
        outcome.get('status') == 'timeout'
        and outcome.get('error') in {
            f'Codex SDK timed out after {timeout_s:g}s',
            f'planner timed out after {timeout_s:g}s',
        }
        and (outcome.get('elapsed_s') or 0) >= timeout_s
    )
    if expected_timeout:
        return 'budget_timeout', False
    if (
        outcome.get('error')
        or outcome.get('status') not in ('completed', 'budget_exhausted')
        or type(outcome.get('environment_success')) is not bool
    ):
        return 'unexpected', None
    return 'task_result', outcome['environment_success']


def main():
    assert not (ROOT / 'protocol.json').exists(), 'Never restart or overwrite a batch'
    config = api('/api/session/config')
    previous = json.loads(Path('/home/zwy/work/embodied_harness/experiments/libero10-task-astra-50-20261105/continuation/protocol.json').read_text())
    expected = {**previous['config'], 'planner': 'api', 'model': 'openai-chat:qwen3.8-flash', 'model_profile': 'qwen3.8-flash', 'reasoning_effort': 'none', 'planner_timeout_s': 3000}
    assert config == expected, 'Unexpected configuration change beyond model profile'
    assert all(digest(Path(p)) == h for p, h in previous['source_hashes'].items()), 'Original source or memory changed'
    assert config['model'] == 'openai-chat:qwen3.8-flash'
    assert config['reasoning_effort'] == 'none'
    assert config['max_turns'] == 30 and config['planner_timeout_s'] == 3000
    assert len(config['tools']) == 17 and all(t.startswith('native:') for t in config['tools'])
    initial = api('/api/session/state')
    assert initial['session_state'] == 'ready'
    source = Path('/home/zwy/work/harnessvla')
    monitored = [p for folder in ('robots/libero', 'rpent/planner', 'rpent/session', 'rpent/prompt', 'rpent/tools', 'rpent/dashboard') for p in (source / folder).rglob('*.py')]
    materials = Path('/home/zwy/work/embodied_harness/language-materials/v1')
    monitored += [p for p in materials.rglob('*') if p.is_file()]
    package = Path('/home/zwy/work/harnessvla/.venv/lib/python3.11/site-packages/liberopro/liberopro')
    name = 'KITCHEN_SCENE3_turn_on_the_stove_and_put_the_moka_pot_on_it'
    monitored += [package / 'init_files/libero_10_task' / (name + '.pruned_init'), package / 'bddl_files/libero_10_task' / (name + '.bddl')]
    hashes = {str(p): digest(p) for p in monitored}
    trials = [{'task': t, 'seed': s} for t in range(10) for s in range(5)]
    save('protocol.json', {'comparison_to': '/home/zwy/work/embodied_harness/experiments/libero10-task-astra-50-20261105', 'approved_data_repair': 'task 2 official init states and BDDL, revision c86fc3b8293185a6f373677018ff3e37f8391602; prior zero-action infrastructure failure retained', 'suite': 'libero_10_task', 'config': config, 'trials': trials, 'task_failure_retries': 0, 'unexpected_recovery': 'Stop, diagnose/fix, then rerun the same task/seed; preserve incident separately', 'prior_manual_runs_included': False, 'source_hashes': hashes, 'memory_version': 'language-c592f23a3a324c08', 'success': 'official task success except full-planner budget timeout counts as failure; unexpected incidents excluded from valid results', 'limits': 'Current workbench evaluation, not an exact paper reproduction. Qwen uses API while Astra uses Codex SDK. Profile reasoning_effort=none does not independently establish provider-side reasoning behavior. Stop on configuration/source changes or infrastructure errors.'})
    results = []
    try:
        for trial in trials:
            assert api('/api/session/config') == config, 'Configuration changed'
            assert all(digest(Path(p)) == h for p, h in hashes.items()), 'Source or memory changed'
            state = api('/api/session/state')
            assert state['server_id'] == initial['server_id'], 'Dashboard restarted'
            assert state['session_state'] == 'ready', 'Another run is active'
            known = {r['id'] for r in api('/api/runs')['runs']}
            started = time.monotonic()
            save('status.json', {'phase': 'starting', **trial, 'completed': len(results)})
            api('/api/session/messages', {'text': f"/rpent-task libero_10_task {trial['task']} {trial['seed']}"})
            while time.monotonic() - started < 4200:
                time.sleep(10)
                state = api('/api/session/state')
                assert state['server_id'] == initial['server_id'], 'Dashboard restarted'
                fresh = [r for r in api('/api/runs')['runs'] if r['id'] not in known]
                assert len(fresh) <= 1, 'Unexpected concurrent run'
                run = fresh[0] if fresh else None
                save('status.json', {'phase': 'running', **trial, 'completed': len(results), 'run_id': run['id'] if run else None, 'elapsed_s': round(time.monotonic()-started, 1)})
                if run:
                    task = run['config']['task']
                    assert (task['suite'], task['task'], task['seed']) == ('libero_10_task', trial['task'], trial['seed']), 'Unexpected task'
                    if run['outcome'] and state['session_state'] == 'ready':
                        break
                if not run and state.get('error'):
                    raise RuntimeError(state['error'])
            else:
                raise TimeoutError('Run did not finalize; no abort or retry sent')
            outcome = run['outcome']
            stats = outcome.get('stats', {})
            result = {**trial, 'run_id': run['id'], 'path': run['path'], 'official_success': outcome.get('environment_success'), 'status': outcome.get('status'), 'error': outcome.get('error'), 'elapsed_s': outcome.get('elapsed_s'), 'turns': stats.get('turns_used'), 'input_tokens': stats.get('total_input_tokens'), 'cached_input_tokens': stats.get('total_cached_input_tokens'), 'output_tokens': stats.get('total_output_tokens')}
            classification, evaluation_success = classify_outcome(outcome, config['planner_timeout_s'])
            result.update(classification=classification, evaluation_success=evaluation_success, actions=outcome.get('actions'))
            if classification == 'unexpected':
                incidents_file = ROOT / 'incidents.json'
                incidents = json.loads(incidents_file.read_text()) if incidents_file.exists() else []
                incidents.append(result)
                save('incidents.json', incidents)
                raise RuntimeError(f"Unexpected incident at task {trial['task']} seed {trial['seed']}; excluded from results, repair before retry")
            results.append(result)
            save('results.json', results)
            save('summary.json', {'completed': len(results), 'planned': 50, 'successes': sum(r['evaluation_success'] is True for r in results), 'per_task': {str(t): {'completed': sum(r['task']==t for r in results), 'successes': sum(r['task']==t and r['evaluation_success'] is True for r in results)} for t in range(10)}})
            print(json.dumps(result), flush=True)
        save('status.json', {'phase': 'completed', 'completed': len(results)})
    except Exception as exc:
        save('status.json', {'phase': 'stopped', 'completed': len(results), 'error': str(exc)})
        raise

if __name__ == '__main__':
    main()
