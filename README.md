# iphone-get — 从安卓手机 (Termux) 读取 USB 连接的 iPhone 照片

记录日期：2026-11-17

## 目标

通过 USB 线把 iPhone 插到安卓手机上，用 Termux 列出 iPhone 里的照片并下载。

## 当前状态（中断时）

- **中断原因**：安卓手机没电需要充电，iPhone 已拔出。
- iPhone 拔出前已到达的阶段：**打通了 USB 原始访问通道，PTP 客户端代码已写好，但 bulk 传输遇到 EBUSY 尚未跑通**。
- 下次继续：按 [恢复工作步骤](#恢复工作步骤) 走。

---

## 一、环境

| 项目 | 值 |
|---|---|
| 运行环境 | Termux on Android（无 root） |
| SELinux 域 | `u:r:untrusted_app_27:s0:c87,c257,c512,c768`（targetSdk ≤ 27 的老 Termux） |
| 架构 | aarch64 |
| Termux 来源 | GitHub 构建（`com.termux`，shared user） |
| iPhone | USB id `05ac:12a8`，sysfs 路径 `1-1`，devnode `/dev/bus/usb/001/002`（重插后会变） |
| iPhone 初始状态 | 配置 1 = 仅 PTP 相机接口（class 0x06，1 个接口）；usbmux 接口在配置 4 |

关键约束（无 root 决定一切方案）：
- 不能直接 open `/dev/bus/usb/*`（权限拒绝）
- 唯一 USB 通道 = `termux-usb`（依赖 **Termux:API 安卓应用**）
- Android 给应用的 fd 上有 SELinux ioctl 白名单：**传输类（CONTROL/BULK/SUBMITURB 等）允许，配置类（SETCONFIGURATION/CLAIM/DISCONNECT 等部分受限）**
- 一个设备同一时间只能被一个应用"打开"

## 二、已完成的安装与配置

1. **apt 源换成清华 TUNA**（原 Cloudflare 源仅 2.5 KB/s，TUNA 140+ KB/s）：
   `/data/data/com.termux/files/usr/etc/apt/sources.list`
   ```
   deb https://mirrors.tuna.tsinghua.edu.cn/termux/apt/termux-main stable main
   ```
   （原 packages-cf.termux.dev 行已注释保留）

2. **Termux:API 应用已安装**：`v0.53.0+github.debug`（GitHub 构建，SHA256 校验通过）。
   - 注意：**Termux 和 Termux:API 共享 `sharedUserId="com.termux"`，必须同一渠道签名**。
     F-Droid 的 API 应用装不上（`INSTALL_FAILED_SHARED_USER_INCOMPATIBLE`）。
   - APK 备份在 `/sdcard/Download/termux-api-app_v0.53.0+github.debug.apk`

3. **已安装软件包**（全部来自 termux-main）：
   - `usbmuxd 1.1.1-p20250201-3`（Termux 魔改版：socket 在 `$PREFIX/var/run/usbmuxd`，配合 `TERMUX_USB_FD`）
   - `libimobiledevice 1.4.0-1`（idevice_id/ideviceinfo/idevicepair/afcclient 等）
   - `libusbmuxd / libplist / libusb 1.0.30 / libimobiledevice-glue / libtatsu`
   - `tur-repo`（TUR 第三方仓库，无 gphoto2，已放弃该路线）
   - Termux 自带 `python`、`clang`

4. **验证过的机制**：
   - Termux 的 `libusb-1.0.so` 支持 `TERMUX_USB_FD` 环境变量（strings 里有 `invalid usb fd in TERMUX_USB_FD`）
   - `termux-usb -E -e "<命令>" <devnode>`：给命令传 USB fd（env 变量方式）；不带 `-E` 则作为命令行参数
   - USB 权限对话框：`termux-usb -r <dev>`（只弹一次，"一律允许"可持久化）

## 三、连接过程记录（时间线）

1. `lsusb`/sysfs 发现 iPhone `05ac:12a8` ✅
2. 装 Termux:API（GitHub 版）✅
3. `termux-usb -l` → `["/dev/bus/usb/001/002"]` ✅
4. `termux-usb -r` 授权 ✅
5. `termux-usb -E -e "usbmuxd -f" <dev>` 启动 usbmuxd：
   - 能看到设备（"Found usbmux interface for device 1-2: 1"）
   - **但切换配置 1→4 失败：`LIBUSB_ERROR_BUSY`（三个配置都 BUSY）**
   - 声明接口 1 失败：`LIBUSB_ERROR_NOT_FOUND`（内核视图里当前配置只有接口 0）
6. sysfs 检查：`1-1:1.0` 被 **usbfs 驱动绑定**（某个进程持有声明）
7. 杀掉 `com.termux.api` 进程（同 UID 可杀，pid 曾为 28667）→ **声明仍存在** → 占用者不是 API 应用
8. 扫描本 UID 所有进程的 fd → **没有任何进程持有设备 fd** → 占用者在系统 UID（安卓系统服务，疑似 MTP host / USB 用途选择导致的组件，iPhone 的 PTP 接口会触发）
9. 转向直接 ioctl 方案，发现并修复了 usbdevfs ioctl 编号陷阱（见下）
10. 用**原始控制传输 SET_CONFIGURATION(9) 成功把 iPhone 切到配置 4** ✅（内核不拦截该请求）
11. 但 SETCONFIGURATION ioctl 仍 EBUSY（外部声明在）、CLAIM(0) EBUSY —— 内核视图与硬件脱节
12. `ptp.py` 切回配置 1 + 尝试 PTP OpenSession：**bulk_out 返回 EBUSY**（端点状态不同步/声明占用，未确诊）
13. 再次运行时 termux-usb 报 "No such device" —— iPhone 已被拔出（手机没电），流程中断

## 四、踩过的坑（重要技术细节）

### 1. usbdevfs ioctl 编号的"方向位陷阱"

`linux/usbdevice_fs.h` 里很多 ioctl 声明方向位与直觉相反（历史原因），**内核按完整 cmd 值匹配，方向位错了返回 ENOTTY（不是 EINVAL）**：

| 命令 | 正确宏 | 值 (aarch64) |
|---|---|---|
| CONTROL | `_IOWR('U',0,struct)` 24字节 | 0xC0055500 |
| BULK | `_IOWR('U',2,struct)` 24字节 | 0xC0055502 |
| SETCONFIGURATION | **`_IOR`**('U',5,uint) | 0x80045505 |
| GETDRIVER | `_IOW('U',8,struct)` 272字节 | 0x40045508 |
| CLAIMINTERFACE | **`_IOR`**('U',15,uint) | 0x8004550F |
| RELEASEINTERFACE | **`_IOR`**('U',16,uint) | 0x80045510 |
| RESET | `_IO('U',20)` | 0x00005514 |
| CLEAR_HALT | **`_IOR`**('U',21,uint) | 0x80045515 |
| DISCONNECT | `_IO('U',22)` | 0x00005516 |
| DISCONNECT_CLAIM | `_IOW('U',27,struct)` 8字节 | 0x4004551B |

实测结果（内核 4.14）：
- CONTROL/BULK/CLAIMINTERFACE/SETCONFIGURATION 都被内核识别 ✅
- **DISCONNECT（三种编码）与 DISCONNECT_CLAIM 全部 ENOTTY** —— 本内核不支持/被过滤，无法抢断外部声明 ❌

### 2. 控制传输可以绕过一切

- `USBDEVFS_CONTROL` 不要求声明接口，且在安卓应用白名单内
- **原始控制传输 `SET_CONFIGURATION`（bmRequestType=0x00, bRequest=0x09, wValue=N）内核直接放行** —— 已实测成功切换硬件配置
- 副作用：绕过内核的配置管理 → **内核视图与硬件实际状态脱节**（sysfs 的 `bConfigurationValue` 不再可信），后续用内核 ioctls 可能错乱

### 3. usbfs bulk 的疑点（未解决）

bulk_out 首包 EBUSY。可能原因（按可能性）：
- 外部声明者占着接口，其 fd 的传输与新传输冲突
- 我们绕过内核切配置导致 xHCI 端点上下文/数据 toggle 失同步
- 已尝试：原始控制传输 SET_INTERFACE(0x0B) 重置端点 → 未及验证结果设备被拔出

### 4. 其他

- `pkill -f 'libexec/termux-api'` 会匹配到自己的命令行把 shell 杀掉（exit 144）——用 `pkill -f 'com[.]termux[.]api'` 这种断字符技巧或按 pid
- `ps -A -o PID,UID,NAME` 在此环境 grep 不到东西，用纯 `ps -A` 或扫 `/proc/*/cmdline`
- 不同 UID 的进程 fd 无法扫描（hidepid），系统服务的声明"看不见凶手"
- apt 索引下载慢时换镜像立竿见影
- iPhone sysfs 用端口路径（`1-1`），usbmuxd 日志用 busnum-devnum（`1-2`），指同一设备，别搞混
- termux-api 的 APK 在 `/sdcard/Download` 有备份； Termux 存储可直接读写 `/sdcard/Download`

## 五、文件说明（本目录）

| 文件 | 作用 |
|---|---|
| `README.md` | 本文档 |
| `ptp.py` | **主程序**：Python 直连 PTP 客户端（usbfs 传输层 + PTP 协议层）。子命令：`setcfg1`（切配置1）/ `probe`（GetDeviceInfo）/ `list`（开 session、枚举对象、写 `objects.json`） |
| `usb_fix.py` | ioctl 诊断脚本（含修正后的常量表、GET_DRIVER、DISCONNECT 尝试） |
| `usb_steal.py` | 抢断声明 + 控制传输切配置实验（SET_CONFIGURATION 控制传输在此验证成功） |
| `usb_probe.py` | 查看 termux-usb 传入的 fd 指向（确认 fd 是真 usbfs 节点） |
| `usb_try2.py` | SET_INTERFACE 重置 + bulk 通道存活测试 |

## 六、恢复工作步骤

iPhone 重新插上后：

1. **先做一件关键的事**：看安卓的通知栏/设置里 USB 用途选项（插上 iPhone 后可能弹"将此 USB 设备用于…"或常驻通知）。
   **选"仅充电"（No data transfer）** —— 疑似系统 MTP host 因此占用接口 0，这一步可能一举解决声明冲突（usbmuxd 路线和 PTP 路线都能受益）。
2. 找到新设备节点（devnum 会变）：
   ```bash
   termux-usb -l
   ```
3. 授权（如果换了节点）：
   ```bash
   termux-usb -r /dev/bus/usb/001/00X
   ```
4. 检查外部声明是否还在：
   ```bash
   ls -l /sys/bus/usb/devices/1-1:*/driver   # usbfs = 还被占；无输出 = 干净
   ```
5a. **如果干净了 → 先试 usbmuxd 正规路线**：
   ```bash
   termux-usb -E -e "usbmuxd -f" /dev/bus/usb/001/00X   # 后台挂着
   idevice_id -l
   idevicepair pair        # iPhone 上点"信任"
   ideviceinfo             # 看 ProductVersion（iOS 版本）
   afcclient ls /DCIM      # iOS ≤12 可直读；iOS 13+ DCIM 大概率被屏蔽
   ```
5b. **如果声明还在 → 走 PTP 路线**（已写好 90%）：
   ```bash
   termux-usb -E -e "python ~/pypro/iphone-get/ptp.py setcfg1" /dev/bus/usb/001/00X
   termux-usb -E -e "python ~/pypro/iphone-get/ptp.py probe"   /dev/bus/usb/001/00X
   termux-usb -E -e "python ~/pypro/iphone-get/ptp.py list"    /dev/bus/usb/001/00X
   ```
   - `probe` 成功 = 传输层+协议层通了
   - `list` 产出 `objects.json`（全部对象的名称/大小/日期/格式/父对象）
   - 若 bulk 仍 EBUSY：先跑 `usb_try2.py`；无效则**拔掉重插 iPhone 后立即重试**（重插让内核和硬件重新对齐；若声明者每次插上自动占用，只能靠第 1 步的"仅充电"）
6. 后续待做（代码已留好接口）：下载子命令（GetObject 流式写盘）、按 `objects.json` 批量导出照片到 `/sdcard/Download` 或本目录。

## 七、两条路线对比（截至中断时）

| | usbmuxd + libimobiledevice | 直连 PTP（ptp.py） |
|---|---|---|
| 依赖 | 外部声明必须让路 | 不需要声明（bulk 无接口校验） |
| iOS 限制 | iOS 13+ DCIM 经 AFC 被屏蔽，照片可能要靠完整备份提取 | 标准 PTP，iOS 全版本照片导入通道 |
| 配对 | 需要 iPhone 点"信任"+配对 | **不需要**（当普通数码相机） |
| 现状 | 被 usbfs 声明挡住 | bulk EBUSY 待排查（可能同根源） |
