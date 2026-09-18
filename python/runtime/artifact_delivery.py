"""可信 Runtime 上传交付物；身份来自 Run，目标来自部署配置，模型只提交文件快照。"""

import asyncio
import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from data_access.connections import config_path
from runtime.event_display import with_display_name

ARTIFACT_ID = re.compile(r'artifact_[0-9a-f]{32}\Z')
UPLOAD_PATH = '/fwk_manage_service/sys_attachment/ai/upload/'
PUBLIC_FIELDS = ('artifactId', 'fileId', 'name', 'size', 'suffix', 'status', 'error')
RETRY_DELAYS = (2, 5)
LOGGER = logging.getLogger('ccsdk.artifacts')


class DeliveryError(ValueError):
    def __init__(self, code, status='failed'):
        self.code, self.status = code, status
        super().__init__(code)


def public_artifact(record):
    return {key: record[key] for key in PUBLIC_FIELDS if key in record}


def file_service_config(env):
    """与数据源共用配置文件，独立校验 fileService，禁止隐式默认上传主机。"""
    try:
        value = json.loads(config_path(env).read_text(encoding='utf-8'))
        config = value.get('fileService')
    except (OSError, ValueError, AttributeError):
        raise DeliveryError('file_service_not_configured') from None
    if not config:
        raise DeliveryError('file_service_not_configured')
    try:
        config = dict(config)
        for key in ('baseUrl', 'remoteUrl'):
            url = config[key]
            if not isinstance(url, str) or url != url.strip() or any(c.isspace() for c in url):
                raise ValueError()
            parsed = urlsplit(url)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError()
            if parsed.path not in ('', '/'):
                raise ValueError()
            config[key] = url.rstrip('/')
        domain = config['domainName']
        if not isinstance(domain, str) or not domain or any(c.isspace() for c in domain) or '/' in domain:
            raise ValueError()
        domain.encode('ascii')
        for key, default, maximum in (('timeoutSeconds', 600, 3600), ('maxFileBytes', 1073741824, 10737418240)):
            config.setdefault(key, default)
            if type(config[key]) is not int or not 1 <= config[key] <= maximum:
                raise ValueError()
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise DeliveryError('file_service_config_invalid') from None
    return config


class ArtifactDelivery:
    def __init__(self, store, root, notify, *, env=None, transport=None):
        self.store, self.root, self.notify = store, Path(root), notify
        self.env = dict(os.environ if env is None else env)
        self.transport = transport
        self.tasks = {}
        self.lock = asyncio.Lock()

    def list(self, run_id):
        return [public_artifact(record) for record in self.store.artifacts(run_id)]

    def path(self, run_id, artifact_id):
        if not isinstance(artifact_id, str) or not ARTIFACT_ID.fullmatch(artifact_id):
            return None
        record = self.store.artifact(artifact_id)
        if not record or record['runId'] != run_id:
            return None
        folder = self.root / artifact_id
        path = folder / 'content'
        if folder.is_symlink() or path.is_symlink() or not path.is_file() or path.resolve().parent != folder.resolve():
            return None
        return path

    async def _state(self, record, status, **fields):
        record.update(status=status, **fields)
        event = self.store.save_artifact(record, with_display_name({
            'protocolVersion': 'agent-events/v1', 'runId': record['runId'],
            'type': 'artifact.' + status, 'payload': public_artifact(record),
        }))
        # 订阅者断开不能回滚已提交的上传结果；客户端可按序回放或查询状态。
        try:
            await self.notify(event)
        except Exception:
            LOGGER.warning('文件事件通知失败：artifact=%s', record['artifactId'])

    def _snapshot(self, run_id, spool, artifact_id):
        from tools.artifacts import _safe_name
        folder = Path(spool) / artifact_id
        source, manifest = folder / 'content', folder / 'manifest.json'
        if folder.is_symlink() or source.is_symlink() or manifest.is_symlink() or not source.is_file():
            raise ValueError('artifact_snapshot_invalid')
        if manifest.stat().st_size > 65536:
            raise ValueError('artifact_snapshot_invalid')
        value = json.loads(manifest.read_text(encoding='utf-8'))
        name = _safe_name(value['name'])
        if value['artifactId'] != artifact_id or type(value['size']) is not int or value['size'] < 0:
            raise ValueError('artifact_snapshot_invalid')
        self.root.mkdir(parents=True, exist_ok=True)
        staging = self.root / ('.' + artifact_id + uuid.uuid4().hex)
        staging.mkdir()
        try:
            digest, size = hashlib.sha256(), 0
            with source.open('rb') as reader, (staging / 'content').open('xb') as writer:
                while chunk := reader.read(1024 * 1024):
                    size += len(chunk)
                    if size > value['size']:
                        raise ValueError('artifact_snapshot_invalid')
                    digest.update(chunk)
                    writer.write(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            if size != value['size'] or digest.hexdigest() != value['sha256']:
                raise ValueError('artifact_snapshot_invalid')
            destination = self.root / artifact_id
            # 上次可能在快照落盘后、SQLite登记前中断；同一ID只接受相同字节。
            if destination.exists():
                saved = destination / 'content'
                if destination.is_symlink() or saved.is_symlink() or not saved.is_file():
                    raise ValueError('artifact_snapshot_invalid')
                with saved.open('rb') as reader:
                    saved_hash = hashlib.file_digest(reader, 'sha256').hexdigest()
                if saved.stat().st_size != size or saved_hash != digest.hexdigest():
                    raise ValueError('artifact_snapshot_invalid')
                shutil.rmtree(staging)
            else:
                staging.replace(destination)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return {'artifactId': artifact_id, 'runId': run_id, 'name': name, 'size': size,
                'suffix': Path(name).suffix.lstrip('.'), 'sha256': digest.hexdigest()}

    async def accept(self, run_id, spool, artifact_id):
        """仅从当前执行的可信目录接收；Run 由父 Runtime 绑定，不采信 Worker 身份字段。"""
        if not isinstance(artifact_id, str) or not ARTIFACT_ID.fullmatch(artifact_id):
            raise ValueError('artifact_id_invalid')
        async with self.lock:
            existing = self.store.artifact(artifact_id)
            if existing:
                if existing['runId'] != run_id:
                    raise ValueError('artifact_owner_mismatch')
                return
            task = asyncio.create_task(asyncio.to_thread(self._snapshot, run_id, spool, artifact_id))
            try:
                record = await asyncio.shield(task)
            except asyncio.CancelledError:
                await asyncio.gather(task, return_exceptions=True)
                raise
            await self._state(record, 'pending')
            self._start(record)

    def _start(self, record):
        artifact_id = record['artifactId']
        task = asyncio.create_task(self._upload(record), name='upload:' + artifact_id)
        self.tasks[artifact_id] = task
        def completed(done):
            if self.tasks.get(artifact_id) is done:
                self.tasks.pop(artifact_id, None)
            if not done.cancelled() and done.exception() is not None:
                LOGGER.error('文件上传任务异常：artifact=%s', artifact_id)
        task.add_done_callback(completed)

    async def _send(self, record, config):
        path = self.path(record['runId'], record['artifactId'])
        if path is None:
            raise DeliveryError('artifact_snapshot_missing')
        if record['size'] > config['maxFileBytes']:
            raise DeliveryError('artifact_too_large')
        # httpx multipart 按块读取文件，边界由库生成；不跟随重定向，不转发 Run JWT。
        headers = {'domain-name': config['domainName'], 'remote-url': config['remoteUrl']}
        timeout = httpx.Timeout(config['timeoutSeconds'], connect=10, pool=10)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False, transport=self.transport) as client:
            with path.open('rb') as stream:
                mime = mimetypes.guess_type(record['name'])[0] or 'application/octet-stream'
                async with client.stream('POST', config['baseUrl'] + UPLOAD_PATH, headers=headers,
                                         files={'file': (record['name'], stream, mime)}) as response:
                    # 现有文件服务约定500表示上传失败；网关等其他5xx仍按结果不确定处理。
                    if response.status_code == 500:
                        raise DeliveryError('file_upload_server_error')
                    if response.status_code >= 500:
                        raise DeliveryError('file_upload_http_error', 'unknown')
                    if not 200 <= response.status_code < 300:
                        raise DeliveryError('file_upload_rejected')
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 65536:
                            raise DeliveryError('file_upload_response_invalid', 'unknown')
        try:
            value = json.loads(body)
            if not isinstance(value, dict):
                raise ValueError()
            if value.get('state') == 500:
                raise DeliveryError('file_upload_server_error')
            if value.get('state') != 200 or value.get('success') is not True:
                raise DeliveryError('file_upload_rejected')
            data = value['data']
            if not isinstance(data['id'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,255}', data['id']):
                raise ValueError()
            if type(data['fileSize']) is not int or data['fileSize'] != record['size']:
                raise ValueError()
            if not isinstance(data['fileName'], str) or not data['fileName'].strip():
                raise ValueError()
            if not isinstance(data['url'], str) or not data['url'] or not isinstance(data['fileSuffix'], str):
                raise ValueError()
            return {'fileId': data['id'], 'storagePath': data['url'], 'remoteName': data['fileName'],
                    'suffix': data['fileSuffix']}
        except DeliveryError:
            raise
        except (ValueError, KeyError, TypeError):
            raise DeliveryError('file_upload_response_invalid', 'unknown') from None

    async def _upload(self, record):
        """同一快照最多上传三次，所有尝试共用时限，仅落库一次最终结果。"""
        in_flight = False
        last_failure = None
        try:
            config = file_service_config(self.env)
            await self._state(record, 'uploading')
            async with asyncio.timeout(config['timeoutSeconds']):
                for attempt in range(len(RETRY_DELAYS) + 1):
                    in_flight = True
                    try:
                        fields = await self._send(record, config)
                    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
                        last_failure = DeliveryError('file_service_unreachable')
                    except DeliveryError as error:
                        if error.code != 'file_upload_server_error':
                            raise
                        last_failure = error
                    else:
                        in_flight = False
                        break
                    # 收到明确失败才等待重试；等待中取消或超时不误报为远端结果不确定。
                    in_flight = False
                    if attempt == len(RETRY_DELAYS):
                        raise last_failure
                    LOGGER.info('文件上传重试：artifact=%s attempt=%s code=%s',
                                record['artifactId'], attempt + 2, last_failure.code)
                    await asyncio.sleep(RETRY_DELAYS[attempt])
            await self._state(record, 'ready', **fields)
        except DeliveryError as error:
            await self._state(record, error.status, error=error.code)
        except (httpx.HTTPError, TimeoutError):
            if not in_flight and last_failure is not None:
                await self._state(record, 'failed', error=last_failure.code)
            else:
                await self._state(record, 'unknown', error='file_upload_uncertain')
        except asyncio.CancelledError:
            if record.get('status') not in {'ready', 'failed', 'unknown'}:
                await self._state(record, 'unknown' if in_flight else 'failed', error='file_upload_interrupted')
            raise
        except Exception:
            await self._state(record, 'unknown' if in_flight else 'failed', error='file_upload_error')

    async def wait(self, run_id):
        # 重试包含在上传任务内；Run终态前等待本Run所有已登记文件收尾。
        while tasks := [self.tasks[r['artifactId']] for r in self.store.artifacts(run_id) if r['artifactId'] in self.tasks]:
            await asyncio.shield(asyncio.gather(*tasks, return_exceptions=True))

    async def recover(self):
        """只有未发送的 pending 可恢复；进程中断时的 uploading 不自动重传。"""
        for record in self.store.artifacts():
            if record['status'] == 'pending':
                self._start(record)
            elif record['status'] == 'uploading':
                await self._state(record, 'unknown', error='file_upload_interrupted')

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
