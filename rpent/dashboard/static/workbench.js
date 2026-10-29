import {el,renderTools} from './tool-picker.js';
const $=id=>document.getElementById(id);
const request=async url=>{const r=await fetch(url);if(!r.ok)throw Error(`请求失败 ${r.status}`);return r.json();};
const link=(title,url)=>{const a=el('a',title);a.href=url;return a;};
const jsonSection=(title,value)=>{const d=el('details');d.append(el('summary',title),el('pre',value==null?'未记录':JSON.stringify(value,null,2)));return d;};
const asset=(id,path)=>`/api/runs/${id}/artifact/${path.split('/').map(encodeURIComponent).join('/')}`;
function eventView(record){const d=el('details');const p=record.payload||record;d.append(el('summary',`${record.time||''} ${record.kind||p.type||'记录'} ${p.name||p.tool||''}`),el('pre',JSON.stringify(p,null,2)));return d;}
async function showRun(id){
  const run=await request(`/api/runs/${id}`),root=$('content');root.replaceChildren();
  const h=el('section');h.append(el('h2',`${run.config.model} · ${id}`));
  const outcome=run.outcome;h.append(el('p',`官方成功：${outcome.environment_success==null?'未记录':outcome.environment_success?'是':'否'} · ${outcome.status||'旧记录 / 未记录结束状态'} · 放置稳定性：${outcome.stable_placement||'未独立验证'}`));
  if(outcome.error)h.append(el('pre',outcome.error));
  h.append(el('p',`远程目录：${run.path}`,'evidence-line'));
  const copy=el('button',run.config.task?.tools?'复制配置到下一次实验':'旧记录未保存工具名单，请从开始页配置');copy.disabled=!run.config.task?.tools;copy.onclick=()=>{sessionStorage.setItem('rpent.copyRun',JSON.stringify({...run.config,...run.config.task}));location.assign('/');};h.append(copy, jsonSection('本轮实际配置与工具版本',run.manifest.tools?run.manifest:run.config),jsonSection('结束状态与用量',run.outcome));root.append(h);
  const video=el('video');video.controls=true;video.preload='metadata';if(run.files.includes('episode.mp4')){video.src=asset(id,'episode.mp4');root.append(video);}else{root.append(el('p','未记录动作录像；无动作的实验请查看初始观测。','note'));}
  if(run.files.includes('states.json')){
    const states=await request(asset(id,'states.json')),section=el('section');section.append(el('h2','动作与观测'));
    const buttons=el('div',null,'step-list'),body=el('div');section.append(buttons,body);root.append(section);
    const select=step=>{body.replaceChildren();const n=step.step_idx;body.append(el('h3',`第 ${n} 步 · ${step.command?.action||'初始状态'}`),jsonSection('参数、结果和状态',step));
      const images=el('div',null,'images');for(const path of run.files.filter(p=>/\.png\/\d+\.png$/.test(p)&&Number(p.split('/').at(-1).split('.')[0])===n)){const figure=el('figure'),img=el('img');img.src=asset(id,path);img.alt=`第 ${n} 步 ${path.split('/').at(-2)}`;img.loading='lazy';figure.append(img,el('figcaption',img.alt));images.append(figure);}body.append(images);
      const clip=run.files.find(p=>p.includes('.mp4/')&&Number(p.split('/').at(-1).split('.')[0])===n);if(clip){const v=el('video');v.controls=true;v.preload='metadata';v.src=asset(id,clip);body.append(v);}
    };
    for(const step of states.steps||[]){const b=el('button',`${step.step_idx} ${step.command?.action||'初始'}`,'quiet');b.onclick=()=>select(step);buttons.append(b);}if(states.steps?.length)select(states.steps.at(-1));
  }
  const logs=el('section');logs.append(el('h2','模型与工具过程'));root.append(logs);
  if(run.files.includes('events.jsonl')){
    const response=await fetch(asset(id,'events.jsonl')),text=await response.text(),events=[];for(const line of text.split('\n')){try{if(line)events.push(JSON.parse(line));}catch{}}
    const counts={};for(const e of events)if(e.kind==='tool_request')counts[e.payload.name]=(counts[e.payload.name]||0)+1;logs.append(jsonSection('实际工具调用次数',counts));
    const mode=el('select');for(const [v,t] of [['tools','工具调用与完整返回'],['model','模型请求和响应'],['all','全部事件']])mode.append(new Option(t,v));const rows=el('div');
    const render=()=>{rows.replaceChildren();for(const e of events.filter(e=>mode.value==='all'||(mode.value==='tools'?e.kind.startsWith('tool_'):e.kind.startsWith('model_')||e.kind.startsWith('sdk_'))))rows.append(eventView(e));};mode.onchange=render;logs.append(mode,rows);render();
  }else{logs.append(el('p','旧实验没有增量事件日志，可查看原生 transcript。'));}
  const files=el('details');files.append(el('summary',`全部留档文件 · ${run.files.length}`));for(const name of run.files){const p=el('p');p.append(link(name,asset(id,name)));files.append(p);}root.append(files);
}
async function load(){
  if(location.pathname==='/tools'){
    $('title').textContent='工具库';$('intro').textContent='查看原生与新增感知工具。制作与修改在 Codex 对话中进行；新版本不会自动启用。';
    const {tools}=await request('/api/tools');renderTools($('content'),tools,[],false);$('status').textContent=`${tools.length} 个工具版本 · 新工具效果需由实验验证`;
  }else{
    $('title').textContent='实验记录';$('intro').textContent='保留每轮实际配置、动作、观测和模型过程。成功标志与实际放置证据分开记录。';
    const id=new URLSearchParams(location.search).get('id');if(id){await showRun(id);$('status').textContent='历史实验 · 只读查看';return;}
    const {runs}=await request('/api/runs');$('content').replaceChildren();for(const run of runs){const card=el('article',null,'run-card'),left=el('div');left.append(el('h3',run.config.model||'模型未记录'),el('p',JSON.stringify(run.config.task)),el('p',`${new Date(run.updated*1000).toLocaleString()} · ${run.outcome.status||'旧记录 / 状态未记录'}`,'note'));card.append(left,link('查看过程 →',`/runs?id=${run.id}`));$('content').append(card);}$('status').textContent=`${runs.length} 次实验 · 按创建时间排序`;
  }
}
load().catch(e=>{$('status').textContent=e.message;$('status').classList.add('error');});
