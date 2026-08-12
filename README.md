# SupplierEvidence

供应商准入与采购证据核验 RAG 平台。系统面向采购准入复核场景：根据供应商、采购品类和地区，在合同、资质、质量材料、历史评审与经人工确认的公开采购公告中检索证据，识别材料缺口、时效风险和跨文档字段冲突，并输出可追溯的核验结果。

> 这是一个辅助人工复核的证据系统，不对企业作自动信用、法律或制裁判断。

## 核心能力

- **Hybrid Retrieval**：供应商/品类/地区硬过滤后，BM25 与 Qdrant 向量召回通过 RRF 融合；向量服务不可用时明确降级为 BM25。
- **证据门禁（Evidence Gate）**：用确定性规则检查必备材料、证照有效期、来源权威性和注册地址/认证范围等跨文档冲突。
- **输出门禁（Output Gate）**：无检索证据、引用不属于当前结果、或冲突结论缺少证据时，阻止生成确定性 AI 说明；模型生成的引用 ID 还会二次校验。
- **可解释检索**：展示 BM25 排名、向量排名、RRF 融合排名；可查看来源元数据、原始材料和 Qdrant 中真实写入的分片文本。
- **冲突工作台**：展示冲突字段、不同取值和对应证据；支持记录待确认/已确认/已解决状态及人工备注，并保留审计事件。
- **受控知识运营**：材料先暂存，完成隐私确认和人工批准后才允许显式重建索引；支持 Markdown、TXT、CSV、PDF、DOCX。
- **TED 公开采购连接器**：小批量拉取公开公告并进入人工确认队列，不会自动成为知识源。
- **固定回归评测**：7 条项目内固定用例，覆盖证据召回、材料缺失、冲突、有效期、规则决策和输出门禁。
- **交付与运行**：Markdown 报告导出，Docker Compose 启动 Web、FastAPI 与 Qdrant，并提供健康/就绪检查。

## 工作流

```text
供应商 + 品类 + 地区 + 核验问题
             │
             ▼
范围过滤 → BM25 + 向量召回 → RRF 融合 → 证据门禁
                                             │
                       可追溯证据、材料缺口、冲突与评分
                                             │
                                             ▼
                                  输出门禁 → 带引用的 AI 说明（可选）
```

## 技术栈

- 后端：Python、FastAPI、Pydantic
- RAG：Hybrid Retrieval、BM25、Qdrant、OpenAI-compatible Embedding/Chat API
- 前端：React、Vite、Tailwind CSS
- 运行：Docker Compose、Nginx、Qdrant

## 快速启动（Docker）

### 1. 配置环境变量

复制 `.env.example` 为 `.env`，并填写模型服务凭据。`.env` 已被 Git 忽略，**不要提交密钥**。

```powershell
Copy-Item .env.example .env
```

至少配置：

```dotenv
OPENAI_API_KEY=your-key
OPENAI_BASE_URL=https://your-openai-compatible-endpoint/
```

### 2. 启动

```powershell
docker compose up -d --build
```

访问：

- 工作台：<http://localhost:5172>
- API 存活检查：<http://localhost:8002/health>
- API 就绪检查（包含 Qdrant）：<http://localhost:8002/ready>
- Qdrant：<http://localhost:6333>

```powershell
docker compose ps
```

三个服务均显示 `healthy` 后即可使用。完整说明见 [docs/RUN_WITH_DOCKER.md](docs/RUN_WITH_DOCKER.md)。

## 演示路径

1. 打开工作台，使用 `Northstar Components GmbH`、`industrial_components`、`EU` 发起核验。
2. 查看缺失的质量检验材料和注册地址冲突。
3. 在“风险与冲突”中查看字段两侧取值和证据 ID，并记录人工处置状态。
4. 点击检索证据，查看原始材料、结构化元数据和 Qdrant 真实分片。
5. 可选择生成带引用的 AI 核验说明，或导出 Markdown 报告。

## 数据边界

仓库仅包含项目自建的模拟供应商材料。公开 TED 数据必须先经过人工确认；真实企业材料应在脱敏、授权和人工标注后再导入。上传文件不会自动加入检索或发送给模型。

## 项目结构

```text
supplier_evidence/      领域逻辑：检索、规则门禁、报告、上传、TED、审计
app/backend/            FastAPI 入口
app/frontend/           React 工作台
data/supplier_evidence/ 模拟证据与运行期数据目录
evals/                  固定回归用例
configs/                Qdrant 与模型配置
compose.yaml            Docker 编排
```

## 验证

```powershell
docker compose ps
Invoke-RestMethod http://localhost:8002/ready
```

固定评测入口：`GET /supplier-evidence/evaluations/latest`。

## 后续生产化方向

- 将本地 JSON/文件状态迁移至 PostgreSQL 和对象存储
- 为 TED 同步加入定时调度、去重与变更提醒
- 接入真实企业材料的批量脱敏、标注与审批流
- 增加线上部署、错误告警和检索质量监控
