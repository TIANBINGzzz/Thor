"""Provider-facing Claude Agent SDK boundary.

Only this module imports ``claude_agent_sdk``.  The rest of the Python runtime
consumes ``SDKMessage`` values and project-owned exceptions, which keeps the
provider object model and exception hierarchy out of application code.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import inspect
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any

import claude_agent_sdk as _sdk


def build_agent_options(**kwargs: Any) -> Any:
    """接收 SDK 配置关键字参数，返回 ClaudeAgentOptions，供运行配置层统一装配。"""

    return _sdk.ClaudeAgentOptions(**kwargs)


def create_sdk_mcp_server(*args: Any, **kwargs: Any) -> Any:
    """接收服务名称、版本和工具等 SDK 参数，返回进程内 MCP 服务配置。"""

    return _sdk.create_sdk_mcp_server(*args, **kwargs)


def sdk_tool(*args: Any, **kwargs: Any) -> Any:
    """接收工具名称、描述和输入 schema，返回 SDK 工具装饰器。"""

    return _sdk.tool(*args, **kwargs)


class SDKError(RuntimeError):
    """Base error exposed by the project-owned SDK boundary."""

    code = "sdk_error"


class SDKConfigurationError(SDKError):
    code = "sdk_configuration_error"


class SDKConnectionError(SDKError):
    code = "sdk_connection_error"


class SDKExecutionError(SDKError):
    code = "sdk_execution_error"


class SDKTimeoutError(SDKError):
    code = "sdk_timeout"


class SDKCleanupError(SDKError):
    code = "sdk_cleanup_error"


class ClientState(str, Enum):
    NEW = "new"
    CONNECTING = "connecting"
    READY = "ready"
    RUNNING = "running"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"


@dataclass(frozen=True)
class SDKMessage:
    """Provider-neutral snapshot of one SDK message.

    ``data`` contains the SDK fields using their source names.  It is a plain
    JSON-compatible structure so event translation and provider-neutral
    object or calling the SDK a second time.
    """

    kind: str
    data: dict[str, Any]
    session_id: str | None = None
    parent_tool_use_id: str | None = None
    uuid: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """将当前消息序列化为普通字典，省略为空的可选字段，供 JSONL 传输。"""

        return {
            key: value
            for key, value in {
                "kind": self.kind,
                "data": self.data,
                "sessionId": self.session_id,
                "parentToolUseId": self.parent_tool_use_id,
                "uuid": self.uuid,
            }.items()
            if value is not None
        }

    @classmethod
    def from_dict(cls, value: Any) -> "SDKMessage":
        """校验输入字典并还原 SDKMessage；字段类型不合法时抛出 ValueError。"""

        if not isinstance(value, Mapping):
            raise ValueError("SDK message must be an object")
        kind = value.get("kind")
        data = value.get("data")
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("SDK message kind is required")
        if not isinstance(data, Mapping):
            raise ValueError("SDK message data must be an object")

        def optional_string(name: str) -> str | None:
            item = value.get(name)
            if item is None:
                return None
            if not isinstance(item, str):
                raise ValueError(f"SDK message {name} must be a string")
            return item

        return cls(
            kind=kind,
            data={str(key): item for key, item in data.items()},
            session_id=optional_string("sessionId"),
            parent_tool_use_id=optional_string("parentToolUseId"),
            uuid=optional_string("uuid"),
        )


def _to_jsonable(value: Any) -> Any:
    """接收任意 SDK 字段值，递归转换为可 JSON 序列化的数据。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_to_jsonable(item) for item in value]
    if is_dataclass(value):
        return {item.name: _to_jsonable(getattr(value, item.name)) for item in fields(value)}
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return _to_jsonable(value.model_dump())
    return str(value)


def _message_fields(message: Any) -> dict[str, Any]:
    """接收 SDK 消息对象，返回字段字典，并为已识别的内容块补充 type。"""
    value = _to_jsonable(message)
    if not isinstance(value, dict):
        return {"value": value}
    content = getattr(message, "content", None)
    if isinstance(content, list) and isinstance(value.get("content"), list):
        normalized_content: list[Any] = []
        for source_block, block in zip(content, value["content"], strict=False):
            if isinstance(block, dict) and "type" not in block:
                block_name = type(source_block).__name__
                block_type = {
                    "TextBlock": "text",
                    "ThinkingBlock": "thinking",
                    "ToolUseBlock": "tool_use",
                    "ToolResultBlock": "tool_result",
                    "ServerToolUseBlock": "server_tool_use",
                    "ServerToolResultBlock": "server_tool_result",
                }.get(block_name)
                if block_type:
                    block = {"type": block_type, **block}
            normalized_content.append(block)
        value["content"] = normalized_content
    return value


def normalize_message(message: Any) -> SDKMessage:
    """接收原生 SDK 消息或 SDKMessage，返回统一的 SDKMessage，保留会话及父工具引用。"""

    if isinstance(message, SDKMessage):
        return message
    data = _message_fields(message)
    if isinstance(message, _sdk.StreamEvent):
        return SDKMessage(
            kind="stream",
            data=data,
            session_id=message.session_id,
            parent_tool_use_id=message.parent_tool_use_id,
            uuid=message.uuid,
        )
    if isinstance(message, _sdk.AssistantMessage):
        return SDKMessage(
            kind="assistant",
            data=data,
            session_id=message.session_id,
            parent_tool_use_id=message.parent_tool_use_id,
            uuid=message.uuid,
        )
    if isinstance(message, _sdk.UserMessage):
        return SDKMessage(
            kind="user",
            data=data,
            parent_tool_use_id=message.parent_tool_use_id,
            uuid=message.uuid,
        )
    if isinstance(message, _sdk.SystemMessage):
        nested = message.data if isinstance(message.data, Mapping) else {}
        session_id = nested.get("session_id")
        parent = nested.get("parent_tool_use_id")
        return SDKMessage(
            kind="system",
            data=data,
            session_id=str(session_id) if session_id else None,
            parent_tool_use_id=str(parent) if parent else None,
        )
    if isinstance(message, _sdk.ResultMessage):
        return SDKMessage(
            kind="result",
            data=data,
            session_id=message.session_id,
            uuid=message.uuid,
        )
    return SDKMessage(kind="other", data=data)


def _safe_sdk_error(error: BaseException) -> SDKError:
    """接收底层异常，返回项目定义的 SDKError，避免向上层复制底层异常详情。"""

    if isinstance(error, SDKError):
        return error
    if isinstance(error, (_sdk.CLINotFoundError, _sdk.CLIConnectionError)):
        return SDKConnectionError("Claude SDK 连接失败")
    if isinstance(error, _sdk.ProcessError):
        return SDKExecutionError("Claude SDK 进程执行失败")
    if isinstance(error, _sdk.ClaudeSDKError):
        return SDKExecutionError("Claude SDK 执行失败")
    return SDKExecutionError("Claude SDK 执行失败")


async def _close_iterator(iterator: Any, timeout_ms: int = 5_000) -> None:
    """接收迭代器和关闭时限，调用其可用的 aclose；无返回值，超时或关闭失败向上抛出。"""
    close = getattr(iterator, "aclose", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await asyncio.wait_for(result, timeout_ms / 1000)


def _validate_timeout(timeout_ms: int | None, name: str) -> None:
    """检查指定名称的超时参数是否为正整数或 None；无返回值，非法值抛出配置错误。"""
    if timeout_ms is not None and (
        isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms <= 0
    ):
        raise SDKConfigurationError(f"{name} 必须是正整数")


async def _await_with_timeout(awaitable: Awaitable[Any], timeout_ms: int | None) -> Any:
    """按可选毫秒时限等待异步操作，返回操作结果，超时抛出 TimeoutError。"""
    if timeout_ms is None:
        return await awaitable
    return await asyncio.wait_for(awaitable, timeout_ms / 1000)


async def _disconnect_provider(provider: Any, timeout_ms: int) -> SDKError | None:
    """按指定时限关闭底层 Client，成功返回 None，失败返回 SDKError 供调用方处理。

    取消信号继续抛出，调用方可保留原始执行错误，避免被清理错误覆盖。
    """

    try:
        await _await_with_timeout(provider.disconnect(), timeout_ms)
    except asyncio.CancelledError:
        # Cancellation is a lifecycle signal, not a provider failure.  The
        # caller owns the final client state and must still be able to tell a
        # requested shutdown from a failed disconnect.
        raise
    except asyncio.TimeoutError as error:
        return SDKTimeoutError("Claude SDK disconnect 超时")
    except Exception as error:
        return SDKCleanupError("Claude SDK disconnect 失败")
    return None


class ClaudeSDKClient:
    """Project-owned lifecycle wrapper around ``claude_agent_sdk.ClaudeSDKClient``.

    The wrapper is intentionally single-owner: every operation must happen in
    the asyncio Task that first calls ``connect``.  A failed or timed-out
    client is not reused; callers create a new wrapper for the next request.
    """

    def __init__(
        self,
        options: Any,
        *,
        client_factory: Callable[[Any], Any] | None = None,
        connect_timeout_ms: int | None = 60_000,
        query_timeout_ms: int | None = 120_000,
        receive_timeout_ms: int | None = 120_000,
        disconnect_timeout_ms: int = 5_000,
    ) -> None:
        """接收 SDK 选项、可选 Client 工厂和各阶段时限，初始化客户端状态；此时尚未连接。"""
        for value, name in (
            (connect_timeout_ms, "connect_timeout_ms"),
            (query_timeout_ms, "query_timeout_ms"),
            (receive_timeout_ms, "receive_timeout_ms"),
            (disconnect_timeout_ms, "disconnect_timeout_ms"),
        ):
            _validate_timeout(value, name)
        self.options = options
        self._client_factory = client_factory or _sdk.ClaudeSDKClient
        self._connect_timeout_ms = connect_timeout_ms
        self._query_timeout_ms = query_timeout_ms
        self._receive_timeout_ms = receive_timeout_ms
        self._disconnect_timeout_ms = disconnect_timeout_ms
        self._provider: Any | None = None
        self._owner_task: asyncio.Task[Any] | None = None
        self._state = ClientState.NEW

    @property
    def state(self) -> ClientState:
        """返回当前 Client 生命周期状态，无额外输入。"""
        return self._state

    def _claim_owner(self) -> None:
        """绑定或校验当前 asyncio Task 的独占操作权；无返回值，跨 Task 调用时报错。"""
        current = asyncio.current_task()
        if current is None:
            raise SDKConfigurationError("Client 必须在 asyncio Task 中使用")
        if self._owner_task is None:
            self._owner_task = current
        elif self._owner_task is not current:
            raise SDKExecutionError("Claude Client 只能由创建它的 asyncio Task 操作")

    def _require_state(self, allowed: set[ClientState]) -> None:
        """接收允许的状态集合并检查当前状态；无返回值，不匹配时抛出执行错误。"""
        if self._state not in allowed:
            allowed_names = ", ".join(item.value for item in allowed)
            raise SDKExecutionError(
                f"Claude Client 状态为 {self._state.value}，需要状态：{allowed_names}"
            )

    async def connect(self, prompt: str | None = None) -> None:
        """接收可选初始提示词并连接底层 Client，成功后进入 READY；无返回值，失败时清理连接。"""
        self._claim_owner()
        self._require_state({ClientState.NEW})
        self._state = ClientState.CONNECTING
        provider: Any | None = None
        try:
            provider = self._client_factory(self.options)
            self._provider = provider
            await _await_with_timeout(provider.connect(prompt), self._connect_timeout_ms)
            self._state = ClientState.READY
        except asyncio.CancelledError:
            self._state = ClientState.FAILED
            if provider is not None:
                await _disconnect_provider(provider, self._disconnect_timeout_ms)
                self._provider = None
            raise
        except asyncio.TimeoutError as error:
            self._state = ClientState.FAILED
            if provider is not None:
                await _disconnect_provider(provider, self._disconnect_timeout_ms)
                self._provider = None
            raise SDKTimeoutError("Claude SDK connect 超时") from error
        except Exception as error:
            self._state = ClientState.FAILED
            if provider is not None:
                await _disconnect_provider(provider, self._disconnect_timeout_ms)
                self._provider = None
            raise _safe_sdk_error(error) from error

    async def query(self, prompt: str, session_id: str = "default") -> None:
        """向已连接 Client 提交提示词和 SDK 会话标识，进入 RUNNING；无返回值，回复由 receive_response 读取。"""
        self._claim_owner()
        self._require_state({ClientState.READY})
        if not isinstance(prompt, str) or not prompt.strip():
            raise SDKConfigurationError("Client query prompt 不能为空")
        provider = self._provider
        if provider is None:
            self._state = ClientState.FAILED
            raise SDKExecutionError("Claude Client provider 不存在")
        try:
            await _await_with_timeout(provider.query(prompt, session_id=session_id), self._query_timeout_ms)
            self._state = ClientState.RUNNING
        except asyncio.CancelledError:
            self._state = ClientState.FAILED
            await _disconnect_provider(provider, self._disconnect_timeout_ms)
            self._provider = None
            raise
        except asyncio.TimeoutError as error:
            self._state = ClientState.FAILED
            await _disconnect_provider(provider, self._disconnect_timeout_ms)
            self._provider = None
            raise SDKTimeoutError("Claude SDK query 超时") from error
        except Exception as error:
            self._state = ClientState.FAILED
            await _disconnect_provider(provider, self._disconnect_timeout_ms)
            self._provider = None
            raise _safe_sdk_error(error) from error

    def receive_response(self, *, timeout_ms: int | None = None) -> AsyncIterator[SDKMessage]:
        """接收可选响应总时限，返回 SDKMessage 异步迭代器；未指定时使用实例默认时限。"""
        self._claim_owner()
        self._require_state({ClientState.RUNNING})
        effective_timeout = self._receive_timeout_ms if timeout_ms is None else timeout_ms
        _validate_timeout(effective_timeout, "receive_timeout_ms")
        provider = self._provider
        if provider is None:
            self._state = ClientState.FAILED
            raise SDKExecutionError("Claude Client provider 不存在")
        return self._receive_response(provider, effective_timeout)

    async def _receive_response(self, provider: Any, timeout_ms: int | None) -> AsyncIterator[SDKMessage]:
        """按总时限消费底层 Client 的回复并逐条产出 SDKMessage，收到 result 后恢复 READY。

        提前结束、取消或失败时关闭响应流，并废弃未正常完成的连接。
        """
        iterator: Any | None = None
        completed = False
        primary_error: BaseException | None = None
        deadline = None if timeout_ms is None else time.monotonic() + timeout_ms / 1000
        try:
            iterator = provider.receive_response().__aiter__()
            while True:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise asyncio.TimeoutError
                try:
                    next_message = iterator.__anext__()
                    raw = await next_message if remaining is None else await asyncio.wait_for(next_message, remaining)
                except StopAsyncIteration as error:
                    raise SDKExecutionError("Claude SDK response stream 提前结束") from error
                message = normalize_message(raw)
                yield message
                if message.kind == "result":
                    completed = True
                    self._state = ClientState.READY
                    return
        except asyncio.TimeoutError as error:
            primary_error = SDKTimeoutError("Claude SDK response stream 超时")
            self._state = ClientState.FAILED
            raise primary_error from error
        except asyncio.CancelledError as error:
            primary_error = error
            self._state = ClientState.FAILED
            raise
        except SDKError as error:
            primary_error = error
            self._state = ClientState.FAILED
            raise
        except Exception as error:
            primary_error = _safe_sdk_error(error)
            self._state = ClientState.FAILED
            raise primary_error from error
        finally:
            if iterator is not None:
                try:
                    await _close_iterator(iterator, self._disconnect_timeout_ms)
                except asyncio.CancelledError:
                    if primary_error is None:
                        raise
                except Exception as error:
                    if primary_error is None:
                        primary_error = SDKCleanupError("Claude SDK response stream 关闭失败")
                        self._state = ClientState.FAILED
                        raise primary_error from error
            if not completed and self._provider is provider:
                cleanup_error = await _disconnect_provider(provider, self._disconnect_timeout_ms)
                self._provider = None
                self._state = ClientState.FAILED
                if cleanup_error is not None and primary_error is None:
                    raise cleanup_error

    async def interrupt(self) -> None:
        """请求底层 Client 中断当前生成，无额外输入和返回值；调用后仍需消费回复至结束。"""
        self._claim_owner()
        self._require_state({ClientState.RUNNING})
        provider = self._provider
        if provider is None:
            self._state = ClientState.FAILED
            raise SDKExecutionError("Claude Client provider 不存在")
        try:
            await _await_with_timeout(provider.interrupt(), self._query_timeout_ms)
        except asyncio.CancelledError:
            self._state = ClientState.FAILED
            await _disconnect_provider(provider, self._disconnect_timeout_ms)
            self._provider = None
            raise
        except asyncio.TimeoutError as error:
            self._state = ClientState.FAILED
            await _disconnect_provider(provider, self._disconnect_timeout_ms)
            self._provider = None
            raise SDKTimeoutError("Claude SDK interrupt 超时") from error
        except Exception as error:
            self._state = ClientState.FAILED
            await _disconnect_provider(provider, self._disconnect_timeout_ms)
            self._provider = None
            raise _safe_sdk_error(error) from error

    async def disconnect(self) -> None:
        """释放底层 Client 并更新关闭状态，无额外输入和返回值；清理失败时抛出 SDKError。"""
        self._claim_owner()
        if self._state in {ClientState.CLOSED, ClientState.NEW}:
            self._state = ClientState.CLOSED
            return
        provider = self._provider
        self._state = ClientState.CLOSING
        self._provider = None
        if provider is None:
            self._state = ClientState.CLOSED
            return
        try:
            cleanup_error = await _disconnect_provider(provider, self._disconnect_timeout_ms)
        except asyncio.CancelledError:
            self._state = ClientState.FAILED
            raise
        if cleanup_error is not None:
            self._state = ClientState.FAILED
            raise cleanup_error
        self._state = ClientState.CLOSED

    close = disconnect

    async def __aenter__(self) -> "ClaudeSDKClient":
        """进入异步上下文时建立连接，返回当前 Client。"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        """接收上下文异常信息并关闭连接，返回 False 以继续传播原异常。"""
        await self.disconnect()
        return False


class ClaudeSDKFacade:
    """Small facade for query streaming."""

    def __init__(
        self,
        *,
        query_impl: Callable[..., AsyncIterator[Any]] | None = None,
    ) -> None:
        """接收可选 query 实现并保存，默认使用原生 SDK query；不立即发起请求。"""
        self._query_impl = query_impl or _sdk.query

    async def stream_query(
        self,
        prompt: str,
        options: Any,
        *,
        timeout_ms: int | None = None,
    ) -> AsyncIterator[SDKMessage]:
        """接收提示词、SDK 选项和可选总时限，逐条产出标准化 SDKMessage。

        总时限包含无输出的等待期；取消时关闭 SDK 流并继续抛出 CancelledError，区别于执行失败。
        """

        if not isinstance(prompt, str) or not prompt.strip():
            raise SDKConfigurationError("SDK prompt 不能为空")
        if timeout_ms is not None and (
            isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms <= 0
        ):
            raise SDKConfigurationError("SDK timeout_ms 必须是正整数")

        iterator: Any | None = None
        pending_error: BaseException | None = None
        deadline = None if timeout_ms is None else time.monotonic() + timeout_ms / 1000
        try:
            stream = self._query_impl(prompt=prompt, options=options)
            iterator = stream.__aiter__()
            while True:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise asyncio.TimeoutError
                try:
                    next_message = iterator.__anext__()
                    raw = await next_message if remaining is None else await asyncio.wait_for(next_message, remaining)
                except StopAsyncIteration:
                    break
                yield normalize_message(raw)
        except asyncio.TimeoutError as error:
            pending_error = SDKTimeoutError("Claude SDK 查询超时")
            raise pending_error from error
        except asyncio.CancelledError as error:
            pending_error = error
            raise
        except Exception as error:
            pending_error = _safe_sdk_error(error)
            raise pending_error from error
        finally:
            if iterator is not None:
                try:
                    await _close_iterator(iterator)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    if pending_error is None:
                        raise SDKCleanupError("Claude SDK 流关闭失败") from error


async def stream_query(
    prompt: str,
    options: Any,
    *,
    timeout_ms: int | None = None,
) -> AsyncIterator[SDKMessage]:
    """接收提示词、SDK 选项和可选总时限，通过默认 Facade 逐条产出 SDKMessage。"""

    facade = ClaudeSDKFacade()
    async for message in facade.stream_query(prompt, options, timeout_ms=timeout_ms):
        yield message
