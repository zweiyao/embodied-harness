---
id: task-family_flexiv_manipulation_twhiteboard_writing
scope: task-family
suite: flexiv
regime: manipulation
task_id: whiteboard_writing
task_language: 用夹持的白板笔在白板上手写
title: 白板手写时判断落笔、出墨与补笔
applies_when: Flexiv 已夹持白板笔，能观察笔尖或笔迹并读取末端反馈
confidence: single-shot
evidence:
  cells:
    - d836fd3c8d4d153157f7
  attempts: 1
  outcome: completed_with_imperfect_lettering
---

# 白板手写时判断落笔、出墨与补笔

- **落笔位置以笔尖为准。** 在当前图像中辨认笔尖、板面和可写区域。板面反光、深度无效或跨视角估计不一致时，只把可信测量用于估计接近位置。若笔在指间的角度改变，重新定位笔尖。
- **分别判断接触和出墨。** 对照实测末端位姿、接触前后的受力变化，以及当前笔画是否留下连续的新墨迹。末端到位只能确认运动结果。受力上升而看不见新墨迹时，先卸载并检查笔尖接触和视野，避免继续加压。
- **遮挡解除后再决定补笔。** 笔杆或夹爪挡住笔画时，用无遮挡视角或抬笔后的图像对照预期字形，重点看端点、转折和笔画连接处。只修补已看清的缺口。动作因观测过期被拒绝时，先刷新观测，再决定下一笔。
- **按最终可见字迹报告。** 分别记录哪些字可辨、哪些位置有断笔、多余笔画或墨点；图像不清处保留不确定性。

来源为真机白板手写 YESIR，记录 ID 为 `d836fd3c8d4d153157f7`。腕部视角对白板的部分深度查询失败；抬笔后可见先前被遮住的 R 笔画，Y 修补后仍有多余短笔和墨点。仅有这一次任务的图像与动作反馈，无独立评分，跨字样、笔或板面的效果待验证。
