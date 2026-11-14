// Task fields supplied by the environment; command order comes from RobotSpec.
export function renderTaskFields(root, fields, taskSpec, changed) {
  const controls = new Map();
  if (fields.map(f => f.name).join() !== taskSpec.fields.map(f => f.name).join()) {
    throw new Error('任务字段与服务器命令不一致');
  }
  const choices = field => field.depends_on
    ? field.options_by[controls.get(field.depends_on).value] || [] : field.options;
  function populate(field, value) {
    const select = controls.get(field.name), values = choices(field);
    if (!values.length) throw new Error(`任务字段没有选项：${field.name}`);
    select.replaceChildren(...values.map(([v, label]) => new Option(label, v)));
    if (value != null) {
      if (!values.some(([v]) => String(v) === String(value))) throw new Error(`历史任务字段不可用：${field.name}=${value}`);
      select.value = String(value);
    }
  }
  root.replaceChildren();
  fields.forEach((field, i) => {
    const label = document.createElement('label');
    label.textContent = field.label;
    const select = document.createElement('select');
    controls.set(field.name, select);
    label.append(select); root.append(label); populate(field);
    select.addEventListener('change', () => {
      for (const next of fields.slice(i + 1)) populate(next);
      changed();
    });
  });
  const quote = value => /^[a-zA-Z0-9_.:-]+$/.test(value) ? value : "'" + value.replaceAll("'", "'\\''") + "'";
  return {
    command: () => [taskSpec.command, ...fields.map(f => quote(controls.get(f.name).value))].join(' '),
    restore(prior) { for (const field of fields) populate(field, prior[field.name]); changed(); },
  };
}
