# Flexiv 左指触觉

USB 设备 OG001506 安装在左侧指尖。独立进程通过 UVC 读取原始图像，
RPent 在初始观测及每次动作后的观测中返回左指图像，保存到对应步骤的
`tactile_left.png` 和 `tactile.json`。网页控制台可选择“左指触觉”。
目前接入一只传感器，没有右指数据。

## 启动

使用运行 RPent 的 Python 环境（已安装 OpenCV），不需要采集工作台：

```bash
python -m robots.flexiv.tactile_camera \
  --device /dev/v4l/by-id/usb-Xense_Robotics_Co_._Ltd._OG001506_OG001506-video-index0 \
  --serial OG001506 --output-dir /dev/shm/rpent-flexiv/tactile
```

给 RDK 环境服务 `robots.flexiv.env_server --backend rdk` 增加
`--tactile-dir /dev/shm/rpent-flexiv/tactile`，其余相机与控制参数保持不变。
`deploy/flexiv/flexiv-tactile.service` 提供当前主机的用户级服务模板；
部署到其他主机时核对工作目录、Python 路径和设备序列号。
采集器持续取帧，最多每秒发布十次原子快照；超过两秒的快照标为过期，
不会把旧图像当成当前观测。时间为主机接收时间，未与 RealSense、TCP 做硬件同步。
这是动作间观测；当前不保存整个动作期间的高频触觉视频。

## 可选工具

感知区的 `tactile_compare(before_step, after_step)` 对比两个已有记录帧，
返回图像特征位移、有效跟踪比例、位移分布和证据步骤。工具是固定基础统计，
不是自动生成的任务策略。现有实验选择保留，使用前手动勾选该工具。
模型即使未选择比较工具，仍能在原生观测中看到触觉图像。

例如，在一次短下压前后选择两个观测步骤，再结合实际 TCP 位移、末端力和
侧面／腕部 USB 轴线变化分析接触响应。原始图像 x 向右、y 向下；
返回的像素位移没有映射到机械臂基座，也不是牛顿力。
参考帧可能已经夹持物体，不等于无接触参考。

工具只做小位移局部跟踪和前后向一致性检查。缺帧、传感器重启、重复帧、
分辨率不匹配会返回错误；特征不足或跟踪失败返回 `insufficient_evidence`，
不报告零形变。重复点阵在大位移下可能产生匹配歧义，工具不能单独判定
USB 滑移、旋转方向、是否插到底或任务成功。

## 验证边界

首次只读检测获得 1920×1080 图像，30 帧采样约 30 FPS。
当前采用原始 UVC 图像，没有加载厂家去畸变、深度或力标定。
用合成平移检查位移计算，并检查缺失／过期输入及 RPent 留档路径；
实际 USB 插入的成功率或效率增益需要后续配对实验验证。
经验仍按需从 RPent 经验库读取，没有把 USB 经验加入系统提示词。
