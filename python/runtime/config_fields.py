"""数据库列到 Runtime 契约的固定映射；不提供配置默认值。"""

SETTING_PATHS = {
    **{'runtime_' + key.replace('-', '_'): ('runtime', 'timeouts', key) for key in (
        'client-queue-ms', 'client-idle-ms', 'file-prepare-ms', 'file-download-ms',
        'file-upload-connect-ms', 'worker-start-ms', 'worker-send-ms', 'worker-close-ms',
        'worker-control-ms', 'document-render-ms', 'document-start-ms', 'image-ms', 'web-search-ms')},
    **{'runtime_' + key.replace('-', '_'): ('runtime', 'limits', key) for key in (
        'file-max-bytes', 'sdk-buffer-bytes', 'http-body-bytes', 'prompt-bytes',
        'web-search-max-tokens', 'web-search-thinking-max-tokens')},
    'runtime_sse_heartbeat_ms': ('runtime', 'sse-heartbeat-ms'),
    **{'runtime_pool_' + key.replace('-', '_'): ('runtime', 'worker-pool', key) for key in (
        'max-idle', 'max-starting', 'max-live', 'min-available-memory-mib')},
    **{'runtime_observation_' + key.replace('-', '_'): ('runtime', 'observability', key) for key in (
        'enabled', 'storage', 'max-records', 'retention-seconds', 'queue-size')},
    'file_base_url': ('fileService', 'baseUrl'),
    'file_remote_url': ('fileService', 'remoteUrl'),
    'file_download_path': ('fileService', 'downloadPath'),
    'file_timeout_seconds': ('fileService', 'timeoutSeconds'),
    'file_max_bytes': ('fileService', 'maxFileBytes'),
    'image_enabled': ('images', 'enabled'),
    'image_base_url': ('images', 'baseUrl'),
    'image_api_key': ('images', 'apiKey'),
    'image_model': ('images', 'model'),
    'auth_runtime_jwt_secret': ('security', 'runtimeJwtSecret'),
    'auth_runtime_jwt_issuer': ('security', 'runtimeJwtIssuer'),
    'auth_runtime_jwt_audience': ('security', 'runtimeJwtAudience'),
    'auth_observation_jwt_secret': ('security', 'observationJwtSecret'),
    'auth_configuration_jwt_secret': ('security', 'configurationJwtSecret'),
}

CAPABILITY_ASSETS = {
    'instructions': 'instructions', 'instruction_refs': 'instructionRefs',
    'required_tool_refs': 'requiredToolRefs', 'operation_refs': 'operationRefs',
    'service_refs': 'serviceRefs', 'tool_config': 'toolConfig',
    'prompt_variables': 'promptVariables', 'templates': 'templates',
}


class ConfigurationError(ValueError):
    """只携带字段和错误码，避免秘密进入管理错误响应。"""
    def __init__(self, resource, ref, field, code):
        self.detail = {'resource': resource, 'ref': ref, 'field': field, 'code': code}
        super().__init__(code)


class ConfigurationNotFound(KeyError):
    """区分记录不存在和配置内容缺字段。"""
