import {renderTools} from './tool-picker.js';
const $ = (id) => document.getElementById(id);
let setup, profile, config, picker;
let checksPassed = false;
async function request(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `请求失败 (${response.status})`);
  return data;
}
function options(id, values, selected) {
  $(id).replaceChildren(...values.map(([value, label]) => new Option(label, value)));
  if (selected != null) $(id).value = String(selected);
}
function tasks() {
  const values = profile.suites[$('suite').value];
  options('task', values.map((name, i) => [i, `${i} · ${name}`]), 0);
  command();
}
function command() {
  $('command').textContent = profile.suites
    ? `/rpent-task ${$('suite').value} ${$('task').value} ${$('seed').value}`
    : `/rpent-task ${JSON.stringify($('physicalInstruction').value.trim())}`;
}
function budget(id, values, label) {
  const current = config[id];
  if (current != null && !values.includes(current)) values.push(current);
  options(id, values.sort((a,b) => a-b).map(v => [v, label(v)]), current);
}
async function status() {
  const state = await request('/api/session/state');
  const ready = state.session_state === 'ready';
  $('status').classList.remove('error');
  $('status').textContent = ready ? '服务已就绪 · 请选择下一次实验的配置'
    : `当前服务：${state.session_state}。可通过右上角查看控制台，待服务就绪后配置。`;
  $('enter').disabled = !ready || (setup.workbench && !checksPassed);
}
$('robot').addEventListener('change', () => {
  const target = setup.profiles.find(p => p.robot === $('robot').value);
  const forwarded = setup.profiles.some(p => String(p.forwarded_port) === location.port);
  const url = new URL('/', location.href);
  url.port = forwarded ? target.forwarded_port : target.port;
  location.assign(url);
});
$('suite').addEventListener('change', tasks);
for (const id of ['task', 'seed']) $(id).addEventListener('change', command);
$('inspection').addEventListener('change', () => { $('physicalInstruction').value = $('inspection').value; command(); });
$('physicalInstruction').addEventListener('input', command);
async function physicalStatus() {
  const data = await request('/api/flexiv/status');
  $('physicalStatus').textContent = `${data.armed ? '受限动作已启用' : '动作未启用'} · ${data.state.mode} · TCP Z ${data.state.tcp_pose[2].toFixed(4)} m · 夹爪 ${data.gripper_ready ? (data.state.gripper_width_m*1000).toFixed(1)+' mm' : '待操作员连接'}`;
  $('armPhysical').disabled = $('physicalMode').value !== 'supervised' || data.armed || data.lease_active;
  return data;
}
async function physicalAction(action) {
  try {
    await request(`/api/flexiv/${action}`, {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    await physicalStatus();
    return true;
  } catch(error) { $('physicalStatus').textContent = `操作失败：${error.message}`; return false; }
}
$('armPhysical').addEventListener('click', () => physicalAction('arm'));
$('stopPhysical').addEventListener('click', () => physicalAction('stop'));
$('physicalMode').addEventListener('change', async () => {
  if ($('physicalMode').value === 'readonly') await physicalAction('stop');
  else await physicalStatus();
});
$('setupForm').addEventListener('submit', async event => {
  event.preventDefault();
  $('enter').disabled = true;
  try {
    const state = await request('/api/session/state');
    if (state.session_state !== 'ready') throw new Error('当前服务尚未空闲，请先查看控制台。');
    if (!profile.suites) {
      if (!$('physicalInstruction').value.trim()) throw new Error('请输入实验指令');
      const hardware = await physicalStatus();
      if ($('physicalMode').value === 'supervised' && !hardware.armed) throw new Error('请先点击“启用受限动作”，核对状态后再进入控制台');
      if ($('physicalMode').value === 'readonly' && hardware.armed && !await physicalAction('stop')) throw new Error('停止未确认，无法进入只读实验');
    }
    const payload = setup.workbench ? {model_profile: $('model').value, tools: picker.selected()} : {model: $('model').value};
    for (const id of ['max_turns', 'max_tokens', 'planner_timeout_s']) payload[id] = Number($(id).value);
    await request('/api/session/config', {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload),
    });
    sessionStorage.setItem('rpent.preparedTask', $('command').textContent);
    location.assign('/console');
  } catch(error) {
    $('status').classList.add('error');
    $('status').textContent = `未保存：${error.message}`;
    $('enter').disabled = false;
  }
});
try {
  [setup, config] = await Promise.all([request('/api/setup'), request('/api/session/config')]);
  profile = setup.profiles.find(p => p.robot === setup.robot);
  if (!profile) throw new Error('服务器未配置当前环境的开始页');
  options('robot', setup.profiles.map(p => [p.robot, p.label]), setup.robot);
  $('environmentNote').textContent = profile.note;
  $('simulation').hidden = !profile.suites;
  $('physical').hidden = !!profile.suites;
  if (profile.suites) {
    const suites = Object.keys(profile.suites);
    options('suite', suites.map(s => [s,s]), suites.includes('libero_object') ? 'libero_object' : suites[0]);
    const seeds = Array.from({length:10}, (_,i) => i);
    if (setup.robot === 'univtac') seeds.push(100, 101, 102);
    options('seed', seeds.map(i => [i, i]), 0);
    tasks();
  } else {
    options('inspection', profile.inspections.map(s => [s,s]));
    $('physicalInstruction').value = $('inspection').value;
    await physicalStatus();
    setInterval(() => physicalStatus().catch(error => { $('physicalStatus').textContent = `状态不可用：${error.message}`; }), 3000);
  }
  const models = [...(setup.models || [])];
  if (config.model && !models.includes(config.model)) models.push(config.model);
  options('model', setup.workbench ? setup.model_profiles.map(p => [p.id, `${p.label} · ${p.planner}`]) : models.map(m => [m,m.replace('openai-chat:', '')]), setup.workbench ? config.model_profile : config.model);
  if (setup.workbench) {
    $('workbenchTools').hidden = false;
    const catalog = (await request('/api/tools')).tools;
    const copied = sessionStorage.getItem('rpent.copyRun');
    let selection = config.tools;
    if (copied) {
      const prior = JSON.parse(copied);
      selection = prior.tools;
      const missing = (selection || []).filter(id => !catalog.some(t => t.id === id));
      if (missing.length) throw new Error(`历史工具版本不存在：${missing.join(', ')}`);
      if (prior.model_profile) $('model').value = prior.model_profile;
      for (const id of ['max_turns', 'max_tokens', 'planner_timeout_s']) if (prior[id] != null) config[id] = prior[id];
      if (prior.suite) { $('suite').value = prior.suite; tasks(); }
      if (prior.task != null) $('task').value = prior.task;
      if (prior.seed != null) $('seed').value = prior.seed;
      sessionStorage.removeItem('rpent.copyRun');
    }
    picker = renderTools($('toolPicker'), catalog, selection);
    for (const [id, mode] of [['allTools','all'],['clearTools','none'],['nativeTools','native']]) $(id).onclick = () => picker.select(mode);
    const health = await request('/api/models/status');
    const selectedHealth = () => {
      checksPassed = Boolean(health[$('model').value]?.ok);
      $('modelCheck').textContent = checksPassed ? '所选模型连接检查已通过' : '请检查所选模型连接。';
    };
    $('model').addEventListener('change', () => { selectedHealth(); status(); });
    $('checkModels').onclick = async () => {
      $('checkModels').disabled = true;
      $('model').disabled = true;
      checksPassed = false;
      const p = setup.model_profiles.find(p => p.id === $('model').value);
      health[p.id] = {ok:false};
      try {
        $('modelCheck').textContent = `正在检查 ${p.label}…`;
        const result = await request('/api/llm/check', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model_profile:p.id})});
        health[p.id] = result;
        if (!result.ok) throw new Error(JSON.stringify(result));
        checksPassed = true;
        $('modelCheck').textContent = `${p.label}：通过`;
      } catch(error) { $('modelCheck').textContent = `连接未通过：${error.message}`; }
      finally { $('checkModels').disabled = false; $('model').disabled = false; await status(); }
    };
    selectedHealth();
  }
  budget('max_turns', [12, 25, 30, 50, 80, 120, 200], v => `${v} 轮`);
  budget('max_tokens', [2048, 4096, 8192, 16384], v => `${v} Token`);
  budget('planner_timeout_s', [180, 600, 1200, 1800, 3600], v => `${v/60} 分钟`);
  command();
  await status();
  $('fields').disabled = false;
  setInterval(() => status().catch(error => {
    $('enter').disabled = true;
    $('status').classList.add('error');
    $('status').textContent = `连接失败：${error.message}。请检查 SSH 转发与服务。`;
  }), 5000);
} catch(error) {
  $('status').classList.add('error');
  $('status').textContent = `无法加载开始页：${error.message}`;
}
