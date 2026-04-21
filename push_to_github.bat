@echo off
chcp 65001 > nul
echo ========================================
echo    水滴2机器人控制台 - GitHub推送工具
echo ========================================
echo.
echo 请先在GitHub上创建仓库:
echo   1. 访问 https://github.com/new
echo   2. Repository name: waterdrop2-android
echo   3. 选择 Private 或 Public
echo   4. 不要勾选任何初始化选项
echo   5. 点击 Create repository
echo.
echo 请输入你的GitHub用户名:
set /p GITHUB_USER=
echo.
echo 请输入仓库名 (直接回车使用默认 waterdrop2-android):
set /p REPO_NAME=
if "%REPO_NAME%"=="" set REPO_NAME=waterdrop2-android

cd /d "%~dp0"

echo.
echo 正在初始化Git仓库...
git init
git add .
git commit -m "Initial commit: 水滴2机器人控制台 Android APK"

echo.
echo 添加远程仓库...
git remote add origin "https://github.com/%GITHUB_USER%/%REPO_NAME%.git"
git branch -M main

echo.
echo 正在推送到GitHub (可能需要输入用户名和密码)...
git push -u origin main

echo.
echo ========================================
echo    推送完成!
echo ========================================
echo.
echo 下一步:
echo 1. 访问 https://github.com/%GITHUB_USER%/%REPO_NAME%/actions
echo 2. 查看自动构建状态
echo 3. 构建完成后下载APK
pause
