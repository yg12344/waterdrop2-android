#!/bin/bash
# 水滴2APK - GitHub推送脚本

# 配置（请修改为你的信息）
GITHUB_USERNAME="你的GitHub用户名"
REPO_NAME="waterdrop2-android"

echo "=== 水滴2机器人控制台 APK项目 ==="
echo ""
echo "请先在GitHub上创建仓库:"
echo "  1. 访问 https://github.com/new"
echo "  2. Repository name: $REPO_NAME"
echo "  3. 选择 Private (私有) 或 Public (公开)"
echo "  4. 不要勾选任何初始化选项"
echo "  5. 点击 Create repository"
echo ""
read -p "创建完成后按回车继续..."

cd "$(dirname "$0")"

# 初始化Git
git init
git add .
git commit -m "Initial commit: 水滴2机器人控制台 Android APK

- 基于KivyMD构建的机器人遥控应用
- 支持TCP/IP连接、遥控控制、导航功能
- GitHub Actions自动构建APK"

# 添加远程仓库
git remote add origin "https://github.com/$GITHUB_USERNAME/$REPO_NAME.git"
git branch -M main

# 推送到GitHub
echo ""
echo "正在推送到GitHub..."
git push -u origin main

echo ""
echo "=== 推送完成! ==="
echo ""
echo "下一步:"
echo "1. 访问 https://github.com/$GITHUB_USERNAME/$REPO_NAME/actions"
echo "2. 查看自动构建状态"
echo "3. 构建完成后下载APK"
