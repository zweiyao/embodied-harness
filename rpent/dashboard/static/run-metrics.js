// Display persisted experiment accounting; missing provider data is not zero.
export function formatRunMetrics(outcome = {}, language = 'zh-cn') {
  outcome = outcome || {};
  const zh = language.toLowerCase().startsWith('zh');
  const unknown = zh ? '未记录' : 'not recorded';
  const number = value => Number.isFinite(value) && value >= 0;
  const show = value => number(value) ? value.toLocaleString(zh ? 'zh-CN' : 'en-US') : unknown;
  const stats = outcome.stats || {};
  const input = stats.total_input_tokens, output = stats.total_output_tokens;
  const total = number(input) && number(output) ? input + output : null;
  const duration = number(outcome.elapsed_s) ? `${outcome.elapsed_s.toFixed(1)} ${zh ? '秒' : 's'}` : unknown;
  return zh
    ? `耗时 ${duration} · 交互 ${show(stats.turns_used)} 轮 · 总 token ${show(total)}（输入 ${show(input)} / 输出 ${show(output)}；缓存输入 ${show(stats.total_cached_input_tokens)}，已含在输入中）`
    : `Elapsed ${duration} · Model responses ${show(stats.turns_used)} · Total tokens ${show(total)} (input ${show(input)} / output ${show(output)}; cached input ${show(stats.total_cached_input_tokens)}, included in input)`;
}

export function formatRunTimes(run) {
  const show = value => {
    const date = new Date(value);
    return value && Number.isFinite(date.getTime()) ? date.toLocaleString() : '未记录';
  };
  return `开始：${show(run.manifest?.started_at)} · 结束：${show(run.outcome?.ended_at)}`;
}
