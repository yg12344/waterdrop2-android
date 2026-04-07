# GitHub Actions 自动构建配置

## 功能
每次推送代码到 `main` 或 `master` 分支时，自动构建 Android APK。

## 触发条件
- 推送代码到 main/master 分支（且修改了相关文件）
- 手动触发（workflow_dispatch）
- Pull Request

## 使用方法

### 1. 推送到GitHub
```bash
git add .
git commit -m "修复数据显示和直控连续运动问题"
git push origin main
```

### 2. 查看构建状态
- 进入 GitHub 仓库页面
- 点击 **Actions** 标签
- 查看构建进度和日志

### 3. 下载APK
构建成功后：
- 点击完成的 workflow 运行记录
- 找到 **Artifacts** 部分
- 下载 `waterdrop2-apk` 文件

## 构建时间
首次构建约 30-45 分钟（需要下载SDK/NDK）
后续构建约 5-10 分钟（使用缓存）

## 故障排查
如果构建失败：
1. 点击失败的 workflow
2. 查看 **build-logs** artifact 中的日志
3. 根据错误信息修复代码

## 手动触发构建
1. 进入 GitHub 仓库 Actions 页面
2. 选择 "Build Android APK" 工作流
3. 点击 "Run workflow" 按钮
