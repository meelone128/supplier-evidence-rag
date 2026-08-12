# 用 Docker 运行 SupplierEvidence

## 前置条件

- 已安装并启动 Docker Desktop。
- 在项目根目录创建 `.env`，填写 `OPENAI_API_KEY`、`OPENAI_BASE_URL`；该文件已被 Git 忽略，绝不提交。
- 首次仅启动后，演示资料会随镜像存在；如需使用混合检索，请在工作台中通过“确认重建已批准资料”将已批准资料写入 Qdrant。

## 启动

```powershell
docker compose up --build
```

打开 <http://localhost:5172>。`/health` 仅表示 API 进程存活；`/ready` 还会检查配置的 Qdrant 集合是否可读：<http://localhost:8002/ready>。Qdrant 本地端口为 `6333`。

## 停止与重启

```powershell
docker compose down
docker compose up -d
```

`down` 不会删除 Docker volume，因此 Qdrant 索引、上传暂存区和审计记录会保留。若要清空所有容器数据，才使用：

```powershell
docker compose down -v
```

## 架构

```text
Browser → Nginx Web (5172) → FastAPI (8002) → Qdrant
                                └→ 模型 API（仅在显式索引或生成时）
```

生产环境应通过密钥管理器注入环境变量，并改用受控对象存储、PostgreSQL 和受保护的 Qdrant 服务。
