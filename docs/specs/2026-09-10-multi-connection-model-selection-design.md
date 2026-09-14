# 多连接与多模型选择设计

## 目标

当目录或 Provider 返回多个可用连接时，管理台必须完整展示候选项，由用户选择连接和模型；系统不根据 Provider 名称、区域或 URL 静默替用户决定。用户可在一次操作中选择多个连接，并为每个连接选择多个模型。

## 现状与问题

- 目录管理台的 `buildCatalogProviders()` 当前按 Provider 名称去重，同名 Provider 的不同 Base URL 只保留第一个。
- Provider 模型发现接口已经可以返回多个模型，添加模型弹窗也有批量模型勾选能力，但一次只处理一个连接。
- 数据库中的 `Provider` 实际包含一组连接信息（协议、Base URL），现有路由通过 `provider_id` 关联 Provider，凭据保存在本机 keyring 中。

## 方案

采用“连接候选 + 模型选择 + 批量保存”三阶段流程，保持现有数据库结构和 OpenAI 兼容接口不变。

AtomGit CodingPlan 作为特殊的本地 sidecar 连接接入：FreeLLM Gateway 只连接本机 sidecar 暴露的 OpenAI 兼容地址，不直接读取或签名 AtomCode OAuth Token，也不绕过 AtomCode 的官方登录流程。

### 1. 连接候选

目录数据按 `provider + normalized_base_url` 去重，而不是只按 Provider 名称去重。每个候选显示：

- Provider 名称和稳定 ID
- Base URL、区域/线路标识（目录有提供时显示）
- 注册页和文档页
- 当前本地是否已配置、是否有已启用路由
- 最近一次探测结果；密钥只显示“已配置/未配置”，不显示值

相同 Provider 的不同 Base URL 必须作为不同候选保留。已存在的本地 Provider 与目录候选同时显示，精确匹配 `provider + base_url` 时标记为已配置。

### 2. 模型选择

用户勾选一个或多个连接后，逐个输入对应凭据并点击“获取模型/验证连接”。成功后展示该连接返回的完整模型列表，支持搜索、全选、全不选和逐项勾选。不同连接的模型列表、错误和选择状态相互隔离；一个连接鉴权失败不能隐藏或禁用其他候选。

如果目录已有明确模型，则该模型默认勾选，但不阻止用户继续选择同一连接返回的其他模型。模型名称以 Provider `/models` 返回值为准；目录中的模型仅作为初始建议。

### 3. 批量保存与路由

点击保存后，对每个选中的连接：

1. 创建或复用对应的本地 Provider（同一 Base URL 复用，不同 Base URL 使用不同稳定 ID）。
2. 使用该连接的凭据为选中模型创建路由。
3. 路由按连接内的模型生成稳定 ID，并沿用现有优先级顺序。
4. 已存在的 `provider + remote_model` 不重复创建，返回“已跳过”明细。

现有手工添加单连接、编辑路由、模型池排序和自动故障切换保持兼容。多个连接保存后，用户可以调整优先级；系统只在用户明确保存为多个启用路由后才进行故障切换。

## AtomGit CodingPlan sidecar

管理台提供“AtomGit CodingPlan（本机 sidecar）”连接预设，默认地址为用户本机 sidecar 的 OpenAI 兼容地址（例如 `http://127.0.0.1:8080/v1`）。用户先在本机按 AtomGit/sidecar 的官方或已审核流程完成 OAuth 和 CodingPlan 配置，再将 sidecar 发放给外部客户端的 API Key 填入网关的安全凭据字段。

本地 loopback HTTP 地址只允许用于 Provider Base URL，不能用于公开注册地址、文档地址或公网连接。网关不直接解析 `auth.toml`、不保存 AtomCode OAuth Token、不实现 `X-AtomCode-*` 签名；sidecar 不可用时提示启动/地址/Key 问题，并保留其他连接候选。

该方案仅面向用户本人本机使用。CodingPlan 的调用次数、有效期和可用模型以 AtomGit 账号实际返回值为准；不实现账号轮换、额度规避或公网共享。

## 接口与数据流

```mermaid
flowchart LR
    A[加载目录] --> B[保留全部连接候选]
    B --> C[用户勾选连接]
    C --> D[分别输入凭据并验证]
    D --> E[分别获取模型列表]
    E --> F[用户勾选模型]
    F --> G[批量创建/复用 Provider]
    G --> H[批量创建模型路由]
```

新增两个管理接口：

- `POST /api/admin/connection/models`：接收一个尚未保存的 `provider` 和临时 `credential`，只在内存中调用 `/models`，返回 `{ "data": ["model-a"] }`；不写 Provider、不写 keyring，失败只返回分类错误。
- `POST /api/admin/routes/bulk-connections`：接收 `connections[]`，每项包含 `provider`、可选 `credential` 和 `models[]`；按连接返回 `created`、`skipped`、`failed`，错误类型包括 `validation_error`、`provider_identity_conflict`、`secret_storage_unavailable` 和 `persistence_error`，不返回凭据、keyring 引用或完整请求正文。现有单连接接口继续保留给手工流程。

批量接口按 `(protocol, normalized_base_url)` 复用本地 Provider；如果提交的 Provider ID 已属于另一条 Base URL，则该连接失败且不覆盖旧记录。路由按 `(provider_id, remote_model)` 幂等跳过。

## 错误处理

- 401/403：只标记当前连接为鉴权失败，提示重新输入对应服务的 Key；不自动切换区域线路。
- 404/模型不可用：只标记当前连接中的该模型，其他模型继续可选。
- 网络超时/5xx/429：显示为可重试状态，允许单独重试该连接。
- 保存部分成功：保留成功项，逐连接展示失败原因，不能回滚已成功创建的无关连接。
- 探测错误继续遵循现有健康状态和故障切换规则；错误日志只保存分类、状态、耗时和路由元数据。

## 安全与兼容性

- 凭据只通过本地管理页面的短暂请求提交，再写入 keyring；前端不持久化凭据，不放入目录、日志或响应。
- 远程 Base URL 必须使用 HTTPS；本地 sidecar 仅允许 `http://127.0.0.1`、`http://localhost` 或 IPv6 loopback，并禁止 URL 内嵌凭据。公开注册地址、文档地址、route endpoint 仍只允许 HTTPS。
- 现有数据库无需迁移；新连接通过唯一 Provider ID 表示，旧 Provider/route 数据继续可读。
- 不自动尝试用户未选择的区域线路，也不轮换不同账户来规避限额。

## 测试与验收

1. 同名 Provider 的两个不同 Base URL 在目录中都显示，且可分别勾选。
2. 同一连接返回多个模型时全部显示，并可选择任意子集。
3. 两个连接各自选择不同模型和凭据时，批量保存生成正确的 Provider/route 关联。
4. 一个连接返回 401 时，其他连接仍可验证、选择和保存。
5. 重复保存不会重复创建 Provider 或模型路由，并返回 skipped 明细。
6. 现有单连接添加、模型发现、排序、探测、故障切换和密钥不泄露测试全部通过。
7. UI 不显示任何明文 API Key、`credential_ref` 或 keyring URI。

## 不在本次范围

- 自动选择最快线路。
- 自动在多个未选择的区域线路之间切换。
- 多用户权限、远程密钥托管和凭据共享服务。
