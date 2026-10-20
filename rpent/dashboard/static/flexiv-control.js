const panel = document.createElement('div');
panel.style.cssText = 'display:flex;align-items:center;flex-wrap:wrap;gap:8px;width:100%;background:#fff7ed;color:#222;border:1px solid #d6b589;border-radius:8px;padding:8px;box-shadow:0 2px 8px #0002;font:13px sans-serif';
const status = document.createElement('span');
const stop = document.createElement('button');
stop.textContent = '停止机械臂和夹爪';
stop.style.cssText = 'background:#a71919;color:white;border:0;border-radius:4px;padding:8px;margin-left:8px;cursor:pointer';
const link = document.createElement('a');
link.href = '/'; link.textContent = ' 开始页 / 原地恢复';
const note = document.createElement('span');
note.textContent = '无环境自动成功判定；抓放结果需看实测记录';
note.style.cssText = 'font-size:12px;color:#665';
panel.append(status, stop, link, note); document.querySelector('header').append(panel);
const style = document.createElement('style');
style.textContent = '#resultBadge{display:none!important}';
document.head.append(style);
async function update() {
  try {
    const response = await fetch('/api/flexiv/status');
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    status.textContent = data.armed ? '真机动作已启用' : `真机已停用 · ${data.state.mode}`;
  } catch { status.textContent = '真机状态不可用，请检查连接'; }
}
stop.onclick = async () => {
  status.textContent = '正在停止…';
  try {
    const response = await fetch('/api/flexiv/stop', {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    if (!response.ok) throw new Error(await response.text());
    await update();
  } catch(error) { status.textContent = `停止未确认：${error.message}`; }
};
update(); setInterval(update, 3000);
