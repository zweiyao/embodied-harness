// Folder labels use the current task catalog; stored task IDs remain unchanged.
export function groupRuns(runs, profiles = [], currentRobot = '') {
  const environments = new Map();
  for (const run of [...runs].sort((a, b) => b.updated - a.updated)) {
    const config = run.config || {};
    const robot = config.robot || currentRobot || 'unknown';
    const profile = profiles.find(p => p.robot === robot);
    if (!environments.has(robot)) {
      environments.set(robot, {label: profile?.label || (robot === 'unknown' ? '未记录环境' : robot), tasks: new Map()});
    }
    const environment = environments.get(robot);
    const task = typeof config.task === 'object' && config.task !== null ? config.task : {task: config.task};
    const value = task.task ?? task.instruction;
    const id = value == null ? '' : String(value);
    const suite = String(task.suite ?? '');
    const key = JSON.stringify([suite, id]);
    if (!environment.tasks.has(key)) {
      const options = profile?.task_fields?.find(field => field.name === 'task')?.options || [];
      const index = options.findIndex(([value]) => String(value) === id);
      const name = profile?.suites?.[suite]?.[id];
      const label = !id ? '未记录任务' : index >= 0 ? `task ${index} · ${id}`
        : /^\d+$/.test(id) ? `task ${id}${name ? ` · ${name}` : ''}` : id;
      environment.tasks.set(key, {label: suite ? `${suite} / ${label}` : label, missing: !id, runs: []});
    }
    environment.tasks.get(key).runs.push(run);
  }
  const byLabel = (a, b) => a.label.localeCompare(b.label, 'zh-CN', {numeric: true});
  return [...environments.values()].sort(byLabel).map(environment => ({
    ...environment, tasks: [...environment.tasks.values()].sort((a, b) => Number(a.missing) - Number(b.missing) || byLabel(a, b)),
  }));
}
