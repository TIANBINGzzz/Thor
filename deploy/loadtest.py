"""真实 Runtime 会话压测；在 Linux 主机运行，凭据从独立 JSON 文件读取且不输出。"""

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--concurrency', type=int, required=True)
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--base-url', default='http://127.0.0.1:4310')
    parser.add_argument('--docker-host', required=True)
    parser.add_argument('--container', default='ccagentsdk-loadtest')
    args = parser.parse_args()
    if args.concurrency < 1 or args.rounds < 1:
        parser.error('concurrency and rounds must be positive')
    config = json.loads(Path(args.config).read_text())
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'requests.jsonl').exists():
        parser.error('output already contains a run; choose a new directory')
    docker = ['docker', '-H', args.docker_host]
    pid = subprocess.check_output(docker + ['inspect', '-f', '{{.State.Pid}}', args.container], text=True).strip()
    cgroup = next(line.split(':', 2)[2] for line in Path('/proc', pid, 'cgroup').read_text().splitlines() if line.startswith('0::'))
    cgroup = Path('/sys/fs/cgroup') / cgroup.lstrip('/')
    stop = threading.Event()
    unsafe = threading.Event()
    samples = []
    requests = []
    batch = uuid.uuid4().hex
    phase = {'round': 0}

    def sample():
        while not stop.is_set():
            mem = {line.split(':')[0]: int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines()}
            cpu = [int(value) for value in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
            try:
                stats = {line.split()[0]: int(line.split()[1]) for line in (cgroup / 'cpu.stat').read_text().splitlines()}
                row = {'time': time.time(), 'round': phase['round'], 'host_cpu_ticks': cpu,
                       'host_available_bytes': mem['MemAvailable'], 'host_used_bytes': mem['MemTotal'] - mem['MemAvailable'],
                       'container_memory_bytes': int((cgroup / 'memory.current').read_text()),
                       'container_cpu_usec': stats['usage_usec'], 'container_pids': int((cgroup / 'pids.current').read_text()),
                       'disk_free_bytes': shutil.disk_usage(output).free, 'loadavg': os.getloadavg(),
                       'memory_events': (cgroup / 'memory.events').read_text()}
                samples.append(row)
                if mem['MemAvailable'] < 1536 * 1024**2 or row['disk_free_bytes'] < 512 * 1024**2:
                    unsafe.set()
            except OSError:
                unsafe.set()
            stop.wait(1)

    def headers(body, scope):
        now = int(time.time())
        claims = {'iss': config.get('CCSDK_RUNTIME_JWT_ISSUER', 'string-ai-center-service'),
                  'aud': config.get('CCSDK_RUNTIME_JWT_AUDIENCE', 'ccsdk-runtime'),
                  'iat': now, 'exp': now + 600, 'jti': uuid.uuid4().hex,
                  'tenant': 'loadtest', 'sub': 'loadtest', 'scope': scope,
                  **{key: body[key] for key in ('runId', 'messageId', 'businessSessionId', 'capabilityRef')}}
        def encode(value):
            return base64.urlsafe_b64encode(value).rstrip(b'=')
        signing = b'.'.join(encode(json.dumps(value).encode()) for value in ({'alg': 'HS256', 'typ': 'JWT'}, claims))
        token = signing + b'.' + encode(hmac.new(config['CCSDK_RUNTIME_JWT_SECRET'].encode(), signing, hashlib.sha256).digest())
        return {'Authorization': 'Bearer ' + token.decode(), 'Content-Type': 'application/json'}

    def request(method, path, body, scope, data=None):
        req = urllib.request.Request(args.base_url + path, data=None if data is None else json.dumps(data).encode(),
                                     headers=headers(body, scope), method=method)
        return urllib.request.urlopen(req, timeout=360)

    def run(index, round_number, barrier):
        suffix = uuid.uuid4().hex
        body = {'protocol': 'agent-run/v1', 'runId': 'load-' + suffix, 'messageId': 'msg-' + suffix,
                'businessSessionId': f'load-{batch}-{index}', 'capabilityRef': 'conversation',
                'input': {'text': 'Compute 17 * 23. Reply only with the number. Do not use tools.'}}
        row = {'index': index, 'round': round_number, 'runId': body['runId'], 'success': False, 'response': '', 'ttft_s': None}
        route = '/internal/v1/runs/' + body['runId']
        barrier.wait()
        start = time.monotonic()
        row['started_at'] = time.time()
        try:
            if unsafe.is_set():
                raise RuntimeError('resource_guard')
            with request('POST', '/internal/v1/runs', body, 'run.execute', body) as response:
                row['http_status'] = response.status
                row['accepted_s'] = time.monotonic() - start
                response.read()
            terminal = None
            with request('GET', route + '/events', body, 'run.read') as response:
                for line in response:
                    if unsafe.is_set():
                        raise RuntimeError('resource_guard')
                    if not line.startswith(b'data:'):
                        continue
                    event = json.loads(line[5:])
                    payload = event.get('payload', {})
                    delta = payload.get('textDelta', '')
                    if delta:
                        if row['ttft_s'] is None:
                            row['ttft_s'] = time.monotonic() - start
                        row['response'] += delta
                    if event['type'] in ('run.completed', 'run.failed', 'run.cancelled'):
                        terminal = event['type']
                        row['terminal_payload'] = payload
            row['terminal'] = terminal
            row['success'] = terminal == 'run.completed' and row['response'].strip() == '391'
        except Exception as error:
            row['error'] = type(error).__name__ + ': ' + str(error)
            try:
                with request('POST', route + '/cancel', body, 'run.cancel') as response:
                    response.read()
            except Exception:
                pass
        row['elapsed_s'] = time.monotonic() - start
        return row

    monitor = threading.Thread(target=sample, daemon=True)
    monitor.start()
    time.sleep(3)
    started = time.monotonic()
    try:
        for number in range(1, args.rounds + 1):
            phase['round'] = number
            barrier = threading.Barrier(args.concurrency)
            with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                futures = [pool.submit(run, index, number, barrier) for index in range(args.concurrency)]
                for future in futures:
                    row = future.result()
                    requests.append(row)
                    with (output / 'requests.jsonl').open('a') as stream:
                        stream.write(json.dumps(row) + '\n')
            print(json.dumps({'round': number, 'completed': len(requests), 'success': sum(row['success'] for row in requests)}), flush=True)
            if unsafe.is_set():
                break
    finally:
        duration = time.monotonic() - started
        stop.set()
        monitor.join()
        (output / 'samples.json').write_text(json.dumps(samples))
    elapsed = sorted(row['elapsed_s'] for row in requests)
    summary = {'concurrency': args.concurrency, 'rounds': args.rounds, 'requests': len(requests),
               'success': sum(row['success'] for row in requests), 'duration_s': duration,
               'throughput_rps': len(requests) / duration, 'mean_s': statistics.mean(elapsed),
               'p95_s': elapsed[max(0, math.ceil(len(elapsed) * .95) - 1)],
               'max_s': max(elapsed), 'resource_guard': unsafe.is_set()}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)
    if unsafe.is_set():
        raise SystemExit(3)


if __name__ == '__main__':
    main()
