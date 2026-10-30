export const labels = {control:'控制工具', perception:'感知工具', auxiliary:'运行辅助'};
export const validation = {native:'原生', unverified:'未验证', replay_passed:'回放通过', invoked:'实验中已调用'};
const availability = {conditional:'按任务启动状态注册', registered:'当前任务已注册', not_registered:'当前任务未注册', candidate:'候选，尚未接入调用'};
export function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}
export function detail(tool, catalog) {
  const modal = el('dialog');
  const heading=el('h2',tool.name);heading.tabIndex=-1;
  modal.append(heading, el('p', `${tool.origin === 'native' ? 'RPent 原生' : '新增感知工具'} · ${tool.version.slice(0,12)} · ${validation[tool.validation] || tool.validation}`));
  if (availability[tool.availability]) modal.append(el('p', availability[tool.availability], 'tag'));
  if (tool.availability_note) modal.append(el('p', tool.availability_note, 'note'));
  for (const [title, value] of [['用途',tool.description],['输入',tool.input_contract],['依赖',tool.dependencies],['参数',tool.parameters],['返回示例',tool.example],['来源实验',tool.source_run],['修改原因',tool.reason],['完整源码',tool.source]]) {
    modal.append(el('h3',title),el('pre', value == null ? '未记录' : typeof value === 'string' ? value : JSON.stringify(value,null,2)));
  }
  if (tool.source_run && tool.availability !== 'candidate') {
    const runLink=el('a','查看来源实验 →');runLink.href=`/runs?id=${encodeURIComponent(tool.source_run)}`;modal.append(runLink);
  }
  if (tool.previous_version) {
    const prev = catalog.find(t=>t.version===tool.previous_version);
    modal.append(el('h3','版本差异'),el('pre',tool.diff || (prev ? `旧版 ${prev.version}\n${prev.source}\n\n新版 ${tool.version}\n${tool.source}` : '旧版未找到')));
  }
  const close=el('button','关闭'); close.type='button'; close.onclick=()=>modal.close(); modal.append(close);
  document.body.append(modal); modal.addEventListener('close',()=>modal.remove()); modal.showModal();heading.focus({preventScroll:true});modal.scrollTop=0;
}
export function renderTools(root, catalog, selected, selectable=true) {
  root.replaceChildren();
  const checks = [];
  for (const category of Object.keys(labels)) {
    const group=el(category==='auxiliary'?'details':'section');
    group.append(el(category==='auxiliary'?'summary':'h2',labels[category]));
    const list=el('div',null,'tool-grid');
    for (const tool of catalog.filter(t=>t.category===category)) {
      const card=el('article',null,'tool-card');
      const label=el('label');
      if (selectable && tool.availability !== 'candidate') {
        const check=el('input'); check.type='checkbox'; check.value=tool.id; check.checked=tool.required||selected.includes(tool.id); check.disabled=tool.required;
        checks.push({check,tool}); label.append(check);
        check.onchange=()=>{if(check.checked) for(const other of checks) if(other.tool.name===tool.name && other.check!==check) other.check.checked=false;};
      }
      label.append(el('span',tool.name)); card.append(label);
      card.append(el('p',`${tool.origin==='native'?'RPent 原生':'新增'} · ${tool.version.slice(0,8)}${tool.required?' · 必需':''}`, 'tag'));
      if (availability[tool.availability]) card.append(el('p', availability[tool.availability], 'tag'));
      card.append(el('p',tool.description.split('\n')[0],'tool-description'));
      if (tool.availability_note) card.append(el('p', tool.availability_note, 'note'));
      const link=el('button',`详情 · ${validation[tool.validation] || '未验证'}${tool.invoked?' / 实验中已调用':''}`,'quiet');link.type='button';link.onclick=()=>detail(tool,catalog);card.append(link); list.append(card);
    }
    if(!list.children.length)list.append(el('p','暂无工具','note'));
    group.append(list);root.append(group);
  }
  return {
    selected:()=>checks.filter(x=>x.check.checked).map(x=>x.tool.id),
    select:mode=>{for(const {check,tool} of checks)check.checked=tool.required||(mode==='native'&&tool.origin==='native')||(mode==='all');
      if(mode==='all') { const seen=new Set(); for(const {check,tool} of [...checks].reverse()){if(seen.has(tool.name))check.checked=false;else seen.add(tool.name);} }
    }
  };
}
