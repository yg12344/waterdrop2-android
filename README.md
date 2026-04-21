# 水滴2机器人控制台 - Android APK

基于KivyMD构建的Android应用，用于控制水滴2服务机器人。

## 功能特性

- 🔗 **网络连接** - 通过TCP/IP连接机器人底盘
- 🎮 **遥控控制** - 虚拟摇杆直接控制机器人移动
- 📍 **导航功能** - 支持坐标导航和目标点(Marker)导航
- ⚡ **急停控制** - 一键紧急停止
- 💡 **灯光控制** - RGB灯带颜色和亮度调节
- 🔧 **系统设置** - 机器人信息、自诊断、关机重启等
- 📊 **状态监控** - 实时显示电量、位置、运动状态

## 项目结构

```
Waterdrop2APK/
├── buildozer.spec       # Buildozer配置文件
├── requirements.txt     # Python依赖
├── README.md           # 说明文档
└── src/
    ├── __init__.py
    ├── main.py         # 主应用入口
    └── waterdrop2_client.py  # 机器人通信客户端
```

## GitHub Actions 自动构建

项目已配置 GitHub Actions，每次推送到 main 分支会自动构建 APK。

### 自动构建流程

1. 推送代码到 GitHub
2. GitHub Actions 自动：
   - 安装 Linux 环境
   - 安装 Python 和 Android SDK
   - 构建 Debug APK
   - 生成 Release（可选）
3. 在 Actions 页面下载 APK

### 手动触发构建

在 GitHub 仓库页面：
- 点击 **Actions** 标签
- 选择 **Build Android APK** 工作流
- 点击 **Run workflow**

### 下载构建产物

- Debug APK: 点击 workflow 运行 → Artifacts
- Release APK: 点击对应 Release 页面下载

## 本地构建

### 环境要求

1. **Linux系统** (推荐Ubuntu 20.04+)
2. **Python 3.8+**
3. **Android SDK**
4. **Buildozer**

### 安装构建工具

```bash
# 安装buildozer
pip install buildozer

# 安装Android SDK (如未安装)
# 参考: https://buildozer.readthedocs.io/en/latest/installation.html
```

### 构建步骤

1. **准备项目**
```bash
cd Waterdrop2APK
```

2. **初始化buildozer**
```bash
buildozer init
```

3. **构建Debug APK**
```bash
buildozer android debug
```

4. **构建Release APK**
```bash
buildozer android release
```

### 使用USB安装APK

```bash
# 查看已连接的设备
adb devices

# 安装APK
adb install bin/*.apk
```

### WiFi调试

确保手机和机器人在同一网络：

```bash
adb connect <手机IP>:5555
adb install bin/*.apk
```

## 使用说明

1. **连接机器人**
   - 启动APP后，在连接界面输入机器人IP地址
   - 默认端口: 31001
   - 点击"连接"按钮

2. **控制机器人**
   - 连接成功后进入控制面板
   - 使用方向键控制机器人移动
   - 红色"急停"按钮用于紧急停止

3. **导航功能**
   - 输入目标坐标(X, Y, θ)
   - 点击"前往坐标"开始导航
   - 支持Marker目标点导航

4. **设置**
   - 查看机器人信息
   - 调节LED灯带颜色
   - 执行自诊断
   - 关机/重启

## API接口

本应用基于水滴2 API开发手册实现，完整支持以下功能：

- `/api/move` - 移动控制
- `/api/cancel_move` - 取消导航
- `/api/robot_status` - 状态查询
- `/api/joy_control` - 遥控控制
- `/api/estop` - 急停
- `/api/markers/*` - 目标点管理
- `/api/map/*` - 地图接口
- `/api/LED/*` - 灯光控制
- `/api/wifi/*` - 网络接口
- `/api/diagnosis/*` - 自诊断
- `/api/shutdown` - 关机重启

## 注意事项

- 确保手机与机器人网络互通
- 急停功能仅限紧急情况使用
- 导航前请确保地图已正确加载

## 许可证

MIT License

## 作者

Waterdrop2 Team
