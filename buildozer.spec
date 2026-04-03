[app]

title = 水滴2控制台
package.name = waterdrop2controller
package.domain = com.waterdrop2

version = 1.0.0

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,txt

main.py = src/main.py

requirements = python3,kivy==2.3.0,kivymd==1.2.0,pillow

orientation = portrait

fullscreen = 0

# Android权限配置
android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE,CHANGE_WIFI_MULTICAST_STATE

# Android架构
android.archs = arm64-v8a,armeabi-v7a

# Bootstrap
p4a.bootstrap = sdl2

# 启用Android API 21+
android.minapi = 21

# Android API版本
android.api = 33

# 开启Android log
android.log_enable = 1

[buildozer]

log_level = 2

warn_on_root = 1

build_dir = ./.buildozer

bin_dir = ./.bin

# 显示编译输出
show_build_output = True
