# P4：空间 Agent 与有限搜索恢复

## 目标和前置条件

在 Mac 本地运行 Agent 编排，调用 DeepSeek 官方 API 理解文本、查询空间记忆、选择观察点和有限恢复，复用 P3 的执行与核验。

硬件验收需要 P1～P3 通过、Mac 同时可达机器人与互联网、有效 DeepSeek 凭据与模型配置。缺凭据时完成 provider mock，不阻塞本地接口开发，但 api-live 门槛不可通过。

## 按顺序执行

1. **P4.1 Provider 适配**：实现统一 planner 接口、DeepSeek 文本工具调用适配器、mock provider。从本项目环境读 key，首次 live probe 核对 model_id、工具返回和 usage，保存脱敏元数据。
2. **P4.2 工具白名单**：按接口契约实现状态/对象/观察点查询、观察、复合导航、核验、停止和询问。所有导航目标只能引用验证过的 ID；工具不提供 shell/原始速度/arm。
3. **P4.3 上下文构建**：仅提供任务、地图身份、支持对象类别、必要观测/记忆、当前状态和最近错误；处理 token 预算，保留关键限制和证据。
4. **P4.4 规划执行**：模型提议 → schema/状态/ID 校验 → 确定性执行器 → 结构化结果 → 后续规划。模型文本不能直接把 task 写成 SUCCEEDED。
5. **P4.5 有限搜索**：未知目标在已建图区域的预设观察点中搜索；最多访问3个不同观察点，禁止无界循环。每次观察更新记忆；已访问且无新增信息的点不得重复绕行。
6. **P4.6 记忆时效与恢复**：可移动椅子默认 last_verified 超过60秒视为需复查，不直接当可靠最新坐标。目标移走、路径受阻、暂时看不到分别处理；最多重规划2次，总任务300秒，超过预算给出明确失败。
7. **P4.7 歧义与范围**：用户“一把椅子”允许确定性选择；“门旁那把”但证据不足则询问/观察。未支持的物体类、地点或功能返回范围说明，不能编造对象。
8. **P4.8 API故障**：只对幂等推理请求做至多2次有退避的重试，30秒单次超时；重试计入8次调用总预算。工具执行按本地幂等键防重复；401/403不盲目重试。
9. **P4.9 评测**：冻结30条语言任务和12条场景脚本，先 mock robot 的 api-live，再实车。比较 P3 基线，并报告工具使用、token、耗时和失败分类。

## 必须交付

- Planner 接口、DeepSeek adapter、mock provider、固定模型/提示词版本。
- P4 工具 schema 与运行时验证；拒绝测试覆盖越权、提示注入、无效ID、重复调用和虚假成功。
- 预设观察点 manifest，候选点必须由 P1 实车验证可到达。
- 有限搜索、记忆时效、用户追问/回复、失败恢复与任务日志。
- API 使用报告和模型能力探测结果，不能只记录聊天回答截图。

## 部署与验收

1. Mac 配置 `DEEPSEEK_API_KEY`，选择已探测的模型；默认只开文本 API。无需在车上放 key 或在服务器部署 LLM。
2. 使用小请求完成 capability probe，确认项目预算与 token 计数可生效。
3. 执行：

```bash
./scripts/project test --level unit
./scripts/project test --level integration --profile mock
./scripts/project accept --phase P4 --mode api-live
./scripts/project accept --phase P4 --mode hardware --session <session_id>
```

api-live 验收连接 mock robot，只调用真实模型；hardware suite 才实际导航，两者 profile 不能混淆。P4-PROVIDER～P4-CONTROL 详见 [验收规范](../acceptance.md)。

## 失败处理与退出条件

API 不可用时返回 MODEL_UNAVAILABLE、禁止新增动作；默认不静默换本地小模型。正在导航的任务是否取消由本地任务状态机明确决定，stop 始终可用且不等待模型返回。

首次训练类别之外的目标不纳入首版成功承诺。未来增加视觉 API/本地 VLM 必须走 perception adapter，以深度/TF验证几何，并重新运行相关 P2/P3/P4 测试。

P4 PASS 后提供统一文字任务入口、追问机制与可播报事件，供 P5 复用。
