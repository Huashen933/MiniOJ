# Mini OJ (Flask + SQLite)

这是一个最小可运行的在线评测系统（原型），功能包括：

- 支持 C++/Python/Java 提交（本地编译运行，注意安全风险）
- 管理员可以创建/编辑/删除题目与测试点
- 提交评测记录与测试点下载
- 使用 SQLite 存储数据

运行方法：

1. 创建虚拟环境并安装依赖：

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

2. 运行应用：

```bash
python app.py
```

3. 管理员初始账号: `admin` / `admin`。

注意：此实现为教学原型，执行用户代码没有隔离（只用 subprocess + timeout），请勿在不受信任的环境中对外开放。生产环境请使用容器/沙箱和更严格的资源限制。
