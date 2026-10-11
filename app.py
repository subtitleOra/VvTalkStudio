"""Double-click desktop entry point; the bundle includes its Python runtime."""
from __future__ import annotations
import argparse
import json
import os
import sys
import threading
import webbrowser
import urllib.request
import socket
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def instance_lock(server, port):
    handle = None
    owned = True
    if os.name == 'nt' and port:
        import msvcrt
        server.initialize()
        handle = (server.DATA / f'instance-{port}.lock').open('a+b')
        handle.seek(0, 2)
        if not handle.tell():
            handle.write(b'\0')
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            owned = False
            handle.close()
            handle = None
    try:
        yield owned
    finally:
        if handle is not None:
            handle.close()


def port_is_open(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=.5):
            return True
    except OSError:
        return False


def reuse_instance(args, server):
    existing_url = 'http://127.0.0.1:' + str(args.port)
    try:
        with urllib.request.urlopen(existing_url + '/api/info', timeout=8) as response:
            existing = json.load(response)
        if existing.get('version') != server.VERSION or existing.get('targets') != ['synthv', 'ace', 'vocaloid5', 'vocaloid6']:
            raise ValueError('目标端口由其他应用占用。')
    except Exception as error:
        raise RuntimeError(f'端口 {args.port} 已占用；请关闭其他服务或使用 --port 指定端口。') from error
    if args.status_file:
        server.write_json(args.status_file, {'url': existing_url, 'pid': existing.get('pid'),
                          'version': existing['version'], 'data_dir': existing['data_dir'], 'reused': True})
    if not args.serve:
        webbrowser.open(existing_url)
    return 0


def main():
    parser = argparse.ArgumentParser(description='VvTalk Studio 中文、日语、英语语音调教工作台')
    parser.add_argument('--browser', action='store_true', help='在浏览器中使用')
    parser.add_argument('--serve', action='store_true', help='只启动本机 API 与页面')
    # Keep 1.1 drafts at a stable origin while the preserved 1.0 app uses 8776.
    parser.add_argument('--port', type=int, default=8777)
    parser.add_argument('--self-test', action='store_true', help='验证打包后的引擎和全部导出')
    parser.add_argument('--status-file', type=Path, help='写入实际监听端口，供本机验证使用')
    args = parser.parse_args()
    import server
    if args.self_test:
        from selfcheck import run
        report = run()
        server.initialize()
        output = server.DATA / 'bundle-self-test.json'
        server.write_json(output, report)
        if sys.stdout:
            print(json.dumps(report, ensure_ascii=False))
        return 0
    with instance_lock(server, args.port) as owned:
        if not owned:
            deadline = time.monotonic() + 8
            while not port_is_open(args.port) and time.monotonic() < deadline:
                time.sleep(.1)
            return reuse_instance(args, server)
        if args.port and port_is_open(args.port):
            return reuse_instance(args, server)
        return run_app(args, server)


def run_app(args, server):
    try:
        httpd = server.create_server(args.port)
    except OSError as error:
        if not args.port or (getattr(error, 'winerror', None) != 10048 and error.errno not in (48, 98, 10048)):
            raise
        return reuse_instance(args, server)
    url = 'http://127.0.0.1:' + str(httpd.server_port)
    status = {'url': url, 'pid': os.getpid(), 'version': server.VERSION, 'data_dir': str(server.DATA)}
    server.write_json(server.DATA / 'runtime.json', status)
    if args.status_file:
        server.write_json(args.status_file, status)
    if args.serve:
        httpd.serve_forever()
        return 0
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        if not args.browser:
            try:
                import webview
                profile = server.DATA / 'webview-storage'
                profile.mkdir(parents=True, exist_ok=True)
                webview.create_window('VvTalk Studio · 语音调教', url, width=1320, height=900,
                                      min_size=(980, 680), text_select=True)
                webview.start(gui='edgechromium', debug=False,
                              private_mode=False, storage_path=str(profile))
                return 0
            except Exception as error:
                with (server.DATA / 'desktop.log').open('a', encoding='utf-8') as log:
                    log.write(str(error) + '\n')
        webbrowser.open(url)
        # Browser mode ends with Ctrl+C / Stop-VvTalk.cmd; desktop mode ends with its window.
        thread.join()
    finally:
        httpd.shutdown()
        httpd.server_close()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        import traceback
        root = Path(os.environ.get('USERPROFILE', Path.home())) / 'AppData' / 'Local' / 'VvTalkStudio'
        root.mkdir(parents=True, exist_ok=True)
        (root / 'startup-error.log').write_text(traceback.format_exc(), encoding='utf-8')
        if os.name == 'nt' and sys.stdout is None and not any(a in sys.argv for a in ('--serve', '--self-test')):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, f'启动失败：{error}\n日志：{root / "startup-error.log"}', 'VvTalk Studio', 16)
        raise
