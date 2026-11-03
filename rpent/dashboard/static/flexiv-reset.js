export function resetControl(button, message, refresh, allowed = () => true) {
  let busy = false;
  let hardware;
  function update(data) {
    hardware = data;
    button.hidden = data.control_backend !== 'rdk';
    button.disabled = busy || !allowed() || !data.reset_available;
    button.title = !allowed() ? '请选择 RDK 真机实验' : data.reset_reason || '回到保存的关节参考位，到位后完全张开夹爪';
  }
  button.onclick = async () => {
    if (busy || button.disabled) return;
    busy = true;
    button.disabled = true;
    message.textContent = '正在读取参考位…';
    try {
      const response = await fetch('/api/flexiv/home-preview');
      const preview = await response.json();
      if (!response.ok) throw new Error(preview.error || `请求失败 (${response.status})`);
      if (!preview.available) throw new Error(preview.reason || '未配置保存的参考位');
      const state = preview.current.state || preview.current;
      const target = preview.target_tcp_pose.slice(0, 3).map(v => (v * 1000).toFixed(1)).join(', ');
      const force = state.ext_wrench_in_world?.slice(0, 3);
      const forceText = force ? `${Math.hypot(...force).toFixed(1)} N` : '未记录';
      const width = Number.isFinite(state.gripper_width_m) ? `${(state.gripper_width_m * 1000).toFixed(1)} mm` : '未记录';
      if (!confirm(`原生 MoveJ 回保存的关节参考位，到位后完全张开夹爪。\n参考 TCP（基座，mm）：${target}\n关节速度比例：${preview.joint_velocity_scale}%\n当前夹爪：${width}；末端合力：${forceText}\n请确认工件已脱离槽口、整个回程无障碍。执行复位？`)) {
        message.textContent = '已取消复位';
        return;
      }
      message.textContent = '正在复位…可随时点击停止机械臂和夹爪';
      const resultResponse = await fetch('/api/flexiv/reset-home', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
      const result = await resultResponse.json();
      if (!resultResponse.ok || !result.reached || !result.gripper?.reached) throw new Error(result.error || result.reason || '未确认回参考位并张开夹爪');
      message.textContent = `复位完成，夹爪已张开${Number.isFinite(result.elapsed_s) ? ` · ${result.elapsed_s.toFixed(1)} 秒` : ''}`;
    } catch (error) {
      message.textContent = `复位未完成：${error.message}。请查看状态；不会自动重试。`;
    } finally {
      busy = false;
      if (hardware) update(hardware);
      try { await refresh(); }
      catch (error) {
        button.disabled = true;
        message.textContent += ` 状态刷新失败：${error.message}`;
      }
    }
  };
  return {update};
}
