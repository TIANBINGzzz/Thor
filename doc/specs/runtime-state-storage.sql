-- 设计提案，未实施；适用于已核对的 MySQL 8.0.45 系列。不得直接对共享环境执行。
-- 不是 Flyway 迁移。Runtime 行保存当前事实；runtime_event 只支持公开事件重放与命令账本。
-- 业务消息内容、inputs、附件关系复用既有表；文件字节留在持久文件存储。
-- SessionStore transcript 是另一种私有数据，不能混入 runtime_event 或业务 RunStore 元数据。
-- Runtime opaque ID 保留 agent-run/v1 的 256 字符，ASCII 区分大小写；业务映射 ID 是36字符。

CREATE TABLE t_ai_center_runtime_session (
    conversation_id VARCHAR(36) COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '既有业务会话ID',
    tenant_id_ VARCHAR(64) NOT NULL COMMENT 'Java校验身份；禁止以默认租户补缺',
    user_id VARCHAR(64) NOT NULL COMMENT 'Java认定主体；保留历史标识语义',
    queue_state VARCHAR(16) NOT NULL DEFAULT 'active' COMMENT 'active/paused/closed；当前Run不随队列暂停',
    active_run_id VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT '会话唯一活动Run',
    next_queue_seq BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '锁session时分配，不因移除而回退',
    last_session_seq BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '控制/会话事件的单调序号',
    revision BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '队列及控制状态CAS版本',
    sdk_project_key VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT 'SDK SessionStore project key',
    sdk_session_id VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT 'Provider会话引用，不等于businessSessionId/runId',
    workspace_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT '受控持久工作区引用，非宿主机路径',
    lease_owner VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT '当前唯一会话Worker实例',
    lease_epoch BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '每次接管递增，隔离旧Worker',
    lease_expires_at DATETIME(3) NULL COMMENT 'UTC；到期不等于进程/工具已停止',
    created_at DATETIME(3) NOT NULL,
    updated_at DATETIME(3) NOT NULL,
    PRIMARY KEY (conversation_id),
    UNIQUE KEY uk_rts_scope (conversation_id, tenant_id_, user_id),
    UNIQUE KEY uk_rts_sdk_session (sdk_project_key, sdk_session_id),
    UNIQUE KEY uk_rts_transcript_owner (conversation_id, sdk_project_key, sdk_session_id),
    UNIQUE KEY uk_rts_workspace (workspace_id),
    KEY idx_rts_dispatch (queue_state, lease_expires_at),
    CONSTRAINT fk_rts_conversation FOREIGN KEY (conversation_id) REFERENCES t_ai_center_conversation (id),
    CONSTRAINT ck_rts_state CHECK (queue_state IN ('active', 'paused', 'closed')),
    CONSTRAINT ck_rts_sdk_key CHECK ((sdk_project_key IS NULL AND sdk_session_id IS NULL) OR (sdk_project_key IS NOT NULL AND sdk_session_id IS NOT NULL)),
    CONSTRAINT ck_rts_lease CHECK ((lease_owner IS NULL AND lease_expires_at IS NULL) OR (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin COMMENT='会话级队列、SDK引用与Worker租约';

CREATE TABLE t_ai_center_runtime_run (
    run_id VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT '既有Run协议ID，同时作为入队幂等键',
    conversation_id VARCHAR(36) COLLATE utf8mb4_0900_ai_ci NOT NULL,
    user_message_id VARCHAR(36) COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '执行输入来自既有user消息及其附件关系',
    assistant_message_id VARCHAR(36) COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '本次回答；Java当前wire messageId',
    capability_ref VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    queue_seq BIGINT UNSIGNED NOT NULL COMMENT '同会话严格顺序',
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    input_revision BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '编辑CAS版本',
    input_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT 'user content+净化inputs+授权附件ID的规范化摘要',
    transcript_sync_state VARCHAR(16) NOT NULL DEFAULT 'pending' COMMENT 'pending/confirmed/unknown；镜像未确认不能跨Worker续接',
    execution_snapshot JSON NULL COMMENT '可信资产/配置版本及摘要，不含凭据；重启需据此核验',
    sdk_prompt_uuid VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT '本次user prompt在SDK transcript中的UUID（若已观察）',
    sdk_started_at DATETIME(3) NULL COMMENT 'SDK调用前先提交；非空即按可能已发送处理',
    checkpoint_stage VARCHAR(32) NOT NULL DEFAULT 'none' COMMENT 'none/input_prepared/sdk_result_saved',
    checkpoint_entry_uuid VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT '已完整镜像的Result transcript边界',
    retry_of_run_id VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT '重新回答保留原Run并指向它',
    redirected_to_run_id VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT '转引导后的活动目标Run',
    edit_owner VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT '短期编辑锁持有者标识',
    edit_expires_at DATETIME(3) NULL COMMENT '编辑锁期限；过期后不挡队首',
    projected_sequence BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'Java业务消息已原子投影的Run事件游标',
    error_code VARCHAR(64) NULL COMMENT '受控错误码，不存异常正文/凭据',
    created_at DATETIME(3) NOT NULL,
    started_at DATETIME(3) NULL COMMENT '真实取得活动位后填写',
    ended_at DATETIME(3) NULL,
    updated_at DATETIME(3) NOT NULL,
    PRIMARY KEY (run_id),
    UNIQUE KEY uk_rtr_session_run (conversation_id, run_id),
    UNIQUE KEY uk_rtr_assistant (assistant_message_id),
    UNIQUE KEY uk_rtr_order (conversation_id, queue_seq),
    KEY idx_rtr_queue (conversation_id, status, queue_seq),
    KEY idx_rtr_user_message (user_message_id),
    CONSTRAINT fk_rtr_session FOREIGN KEY (conversation_id) REFERENCES t_ai_center_runtime_session (conversation_id),
    CONSTRAINT fk_rtr_user_message FOREIGN KEY (user_message_id) REFERENCES t_ai_center_message (id),
    CONSTRAINT fk_rtr_assistant FOREIGN KEY (assistant_message_id) REFERENCES t_ai_center_message (id),
    CONSTRAINT fk_rtr_retry FOREIGN KEY (conversation_id, retry_of_run_id) REFERENCES t_ai_center_runtime_run (conversation_id, run_id),
    CONSTRAINT fk_rtr_redirect FOREIGN KEY (conversation_id, redirected_to_run_id) REFERENCES t_ai_center_runtime_run (conversation_id, run_id),
    CONSTRAINT ck_rtr_status CHECK (status IN ('queued', 'waiting', 'preparing', 'running', 'finalizing', 'completed', 'cancelled', 'failed', 'interrupted', 'redirecting', 'redirected', 'steering_unknown')),
    CONSTRAINT ck_rtr_checkpoint CHECK (checkpoint_stage IN ('none', 'input_prepared', 'sdk_result_saved')),
    CONSTRAINT ck_rtr_transcript_sync CHECK (transcript_sync_state IN ('pending', 'confirmed', 'unknown')),
    CONSTRAINT ck_rtr_checkpoint_uuid CHECK (checkpoint_stage <> 'sdk_result_saved' OR checkpoint_entry_uuid IS NOT NULL),
    CONSTRAINT ck_rtr_transcript_checkpoint CHECK (checkpoint_stage <> 'sdk_result_saved' OR transcript_sync_state = 'confirmed'),
    CONSTRAINT ck_rtr_order CHECK (queue_seq > 0 AND input_revision > 0),
    CONSTRAINT ck_rtr_edit CHECK ((edit_owner IS NULL AND edit_expires_at IS NULL) OR (edit_owner IS NOT NULL AND edit_expires_at IS NOT NULL)),
    CONSTRAINT ck_rtr_retry CHECK (retry_of_run_id IS NULL OR retry_of_run_id <> run_id),
    CONSTRAINT ck_rtr_redirect CHECK (redirected_to_run_id IS NULL OR redirected_to_run_id <> run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin COMMENT='一条回答/排队任务的当前权威状态';

ALTER TABLE t_ai_center_runtime_session
    ADD CONSTRAINT fk_rts_active_run FOREIGN KEY (conversation_id, active_run_id) REFERENCES t_ai_center_runtime_run (conversation_id, run_id);

CREATE TABLE t_ai_center_runtime_event (
    event_id VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT '公共事件ID；command.accepted时同时充当command_id',
    conversation_id VARCHAR(36) COLLATE utf8mb4_0900_ai_ci NOT NULL,
    session_sequence BIGINT UNSIGNED NOT NULL COMMENT '队列控制/Run事件在会话内总序',
    run_id VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NULL,
    run_sequence BIGINT UNSIGNED NULL COMMENT '兼容agent-events/v1的Run内重放序号',
    command_id VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT '命令接受事件ID；后续回执关联同一值',
    event_type VARCHAR(64) NOT NULL COMMENT 'public Runtime事件或command.accepted/processing/applied/rejected/unknown',
    payload_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT '规范化负载摘要；相同command_id不同负载必须冲突',
    payload_json JSON NOT NULL COMMENT '脱敏公共负载；命令只引用messageId，不重复保存引导正文',
    occurred_at DATETIME(3) NOT NULL,
    PRIMARY KEY (event_id),
    UNIQUE KEY uk_rte_session_sequence (conversation_id, session_sequence),
    UNIQUE KEY uk_rte_run_sequence (run_id, run_sequence),
    UNIQUE KEY uk_rte_command_stage (command_id, event_type),
    KEY idx_rte_session_after (conversation_id, session_sequence),
    KEY idx_rte_run_after (run_id, run_sequence),
    KEY idx_rte_command (conversation_id, command_id, session_sequence),
    CONSTRAINT fk_rte_session FOREIGN KEY (conversation_id) REFERENCES t_ai_center_runtime_session (conversation_id),
    CONSTRAINT fk_rte_run FOREIGN KEY (conversation_id, run_id) REFERENCES t_ai_center_runtime_run (conversation_id, run_id),
    CONSTRAINT ck_rte_sequence CHECK (session_sequence > 0 AND ((run_id IS NULL AND run_sequence IS NULL) OR (run_id IS NOT NULL AND run_sequence IS NOT NULL AND run_sequence > 0)))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin COMMENT='前端可重放事件和控制意图账本，不是SDK transcript';

CREATE TABLE t_ai_center_runtime_transcript (
    conversation_id VARCHAR(36) COLLATE utf8mb4_0900_ai_ci NOT NULL,
    sdk_project_key VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT 'SessionStore key的一部分；不可省略',
    sdk_session_id VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    subpath VARCHAR(512) NOT NULL DEFAULT '' COMMENT 'SDK子代理transcript key；主会话为空串',
    entry_sequence BIGINT UNSIGNED NOT NULL COMMENT 'SessionStore.append顺序，load必须按此顺序返回',
    entry_uuid VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NULL COMMENT 'SDK稳定条目UUID；无UUID的记录保留append顺序',
    entry_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL COMMENT '规范JSON摘要，用于完整性和重试核对',
    entry_json JSON NOT NULL COMMENT 'SDK不透明JSONL条目；禁止改写语义字段',
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (conversation_id, sdk_project_key, sdk_session_id, subpath, entry_sequence),
    UNIQUE KEY uk_rtt_entry_uuid (conversation_id, sdk_project_key, sdk_session_id, subpath, entry_uuid),
    CONSTRAINT fk_rtt_session FOREIGN KEY (conversation_id, sdk_project_key, sdk_session_id) REFERENCES t_ai_center_runtime_session (conversation_id, sdk_project_key, sdk_session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin COMMENT='SDK私有会话Transcript；单写者，严格控权与保留';

CREATE TABLE t_ai_center_runtime_artifact (
    artifact_id VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    run_id VARCHAR(256) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    snapshot_json JSON NOT NULL COMMENT '名称、大小、摘要及持久文件引用；不存签名URL/文件字节',
    platform_file_id VARCHAR(256) NULL COMMENT '上传成功后的既有文件服务ID',
    result_json JSON NULL COMMENT '白名单文件卡片元数据；Java幂等投影到writing_attachments',
    processing_epoch BIGINT UNSIGNED NULL COMMENT '上传启动时会话租约epoch',
    error_code VARCHAR(64) NULL,
    created_at DATETIME(3) NOT NULL,
    updated_at DATETIME(3) NOT NULL,
    PRIMARY KEY (artifact_id),
    KEY idx_rta_run (run_id, status),
    CONSTRAINT fk_rta_run FOREIGN KEY (run_id) REFERENCES t_ai_center_runtime_run (run_id),
    CONSTRAINT ck_rta_status CHECK (status IN ('pending', 'uploading', 'ready', 'failed', 'unknown')),
    CONSTRAINT ck_rta_ready CHECK (status <> 'ready' OR platform_file_id IS NOT NULL)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin COMMENT='输出文件交付状态，不复制输入附件';
