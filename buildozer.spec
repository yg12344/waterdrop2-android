[app]

title = 三帝AI智能底盘控制系统
package.name = waterdrop2
package.domain = org.robot
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,txt
source.exclude_dirs = _local_pdfdeps,bin,.workbuddy,__pycache__,src
version = 1.0.1

# 依赖：只用 kivy/kivymd，其余全是标准库
requirements = python3,kivy==2.2.1,kivymd==1.2.0,pillow,sdl2_ttf==2.20.2

# Android 权限
android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE

# Android 版本
android.api = 33
android.minapi = 24
android.ndk_api = 24
android.ndk = 25b
android.archs = arm64-v8a

# CI 环境：直接使用系统 SDK（含 sdkmanager 和已接受的 licenses）
android.sdk_path = /usr/local/lib/android/sdk

# 方向 / 界面
orientation = portrait
fullscreen = 0

# 图标与启动画面（路径相对于 source.dir，即项目根目录）
icon.filename = %(source.dir)s/assets/sd_icon.png
presplash.filename = %(source.dir)s/assets/sd_presplash.png

# 日志级别
log_level = 2

[buildozer]
warn_on_root = 0
android.p4a_extra_args = --environment PYTHONHTTPSVERIFY=0

[p4a]
# 如需自定义 recipes，请按当前构建环境手动设置 local_recipes

