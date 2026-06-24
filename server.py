#!/usr/bin/env python3
# 明爸分類股價 — 線上伺服器（可在本機，也可部署到 Render）
#   ① 提供網頁
#   ② /proxy?url=...  由伺服器端代抓官方股價（無瀏覽器 CORS 限制，最可靠）
#   ③ /__save         寫回 kline_data.js（注意：Render 免費版檔案不會永久保存）
import http.server, socketserver, os, ssl, urllib.parse, urllib.request, json, time, datetime

# Render 會設定 PORT 環境變數；本機則用 8910
PORT = int(os.environ.get("PORT", "8910"))
# 在 Render（有 PORT 環境變數）對外綁定 0.0.0.0；純本機時只綁 127.0.0.1
HOST = "0.0.0.0" if "PORT" in os.environ else "127.0.0.1"
DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(DIR)

# 預設首頁
DEFAULT_PAGE = "1.html"

# 只允許代抓這些官方網域
ALLOW_HOSTS = (
    'openapi.twse.com.tw', 'www.twse.com.tw', 'www.tpex.org.tw',
    'query1.finance.yahoo.com', 'query2.finance.yahoo.com',
)


def fetch_url(target):
    req = urllib.request.Request(target, headers={'User-Agent': 'Mozilla/5.0', 'Accept': '*/*'})
    try:
        return urllib.request.urlopen(req, timeout=25, context=ssl.create_default_context()).read()
    except ssl.SSLError:
        return urllib.request.urlopen(req, timeout=25, context=ssl._create_unverified_context()).read()


# ===== 伺服器端動態快照（最新收盤價，記憶體快取） =====
SNAP_TTL = 300  # 秒；每 5 分鐘重抓一次
_SNAP = {'ts': 0, 'body': None}


def _num(v):
    try:
        return float(str(v).replace(',', '').strip())
    except Exception:
        return None


def _extract(x, suffix, snap):
    if not isinstance(x, dict):
        return
    code = x.get('Code') or x.get('SecuritiesCompanyCode') or x.get('CompanyCode') or x.get('StockNo') or x.get('SecuritiesCode')
    if not code:
        return
    code = str(code).strip()
    close = None
    for k in ('ClosingPrice', 'Close', 'LatestPrice', 'LastPrice', 'AveragePrice', 'WeightedAvg'):
        if x.get(k) not in (None, ''):
            close = _num(x.get(k))
            if close is not None:
                break
    if close is None:
        return
    chg = None
    for k in ('Change', 'Chg'):
        if x.get(k) not in (None, ''):
            chg = _num(x.get(k))
            break
    name = x.get('Name') or x.get('CompanyName') or x.get('SecuritiesCompanyName') or x.get('CompanyName ') or ''
    if code not in snap:
        snap[code] = [close, chg, suffix, str(name).strip()]


def build_snapshot():
    snap = {}
    for url, suf in (
        ('https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL', '.TW'),
        ('https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes', '.TWO'),
        ('https://www.tpex.org.tw/openapi/v1/tpex_esb_latest_statistics', '.TWO'),
    ):
        try:
            arr = json.loads(fetch_url(url))
            if isinstance(arr, list):
                for x in arr:
                    _extract(x, suf, snap)
        except Exception:
            pass
    # 交易日期：用 2330 的 STOCK_DAY 最後一筆
    date = ''
    try:
        tw = datetime.datetime.utcnow() + datetime.timedelta(hours=8)
        j = json.loads(fetch_url('https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY?date=%s&stockNo=2330&response=json' % tw.strftime('%Y%m%d')))
        rows = j.get('data') or []
        if rows:
            p = str(rows[-1][0]).split('/')
            if len(p) == 3:
                date = '%d/%s/%s' % (int(p[0]) + 1911, p[1], p[2])
    except Exception:
        pass
    return 'var SRV_SNAP=' + json.dumps(snap, ensure_ascii=False) + ';var SRV_SNAP_DATE="' + date + '";'


def get_snapshot():
    now = time.time()
    if _SNAP['body'] is None or now - _SNAP['ts'] > SNAP_TTL:
        try:
            b = build_snapshot()
            _SNAP['body'] = b
            _SNAP['ts'] = now
        except Exception:
            if _SNAP['body'] is None:
                _SNAP['body'] = 'var SRV_SNAP={};var SRV_SNAP_DATE="";'
    return _SNAP['body']


# ===== 共用儲存：優先存到 GitHub Gist（跨重啟/部署永久保留），否則退回本機 store.json =====
GH_TOKEN = os.environ.get('GITHUB_TOKEN', '')
GIST_ID = os.environ.get('GIST_ID', '')
GIST_FILE = os.environ.get('GIST_FILENAME', 'store.json')
GIST_TTL = 15
_GIST = {'ts': 0, 'body': None}
LOCAL_STORE = os.path.join(DIR, 'store.json')


def _gh(url, method='GET', data=None):
    headers = {'Authorization': 'Bearer ' + GH_TOKEN, 'Accept': 'application/vnd.github+json',
               'User-Agent': 'ming-stock', 'X-GitHub-Api-Version': '2022-11-28'}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    return urllib.request.urlopen(req, timeout=20, context=ssl.create_default_context()).read()


def gist_read():
    j = json.loads(_gh('https://api.github.com/gists/' + GIST_ID))
    f = (j.get('files') or {}).get(GIST_FILE)
    if f and f.get('content') is not None:
        return f['content']
    return '{}'


def gist_write(text):
    body = json.dumps({'files': {GIST_FILE: {'content': text}}}).encode('utf-8')
    _gh('https://api.github.com/gists/' + GIST_ID, method='PATCH', data=body)


def store_get():
    if GH_TOKEN and GIST_ID:
        now = time.time()
        if _GIST['body'] is None or now - _GIST['ts'] > GIST_TTL:
            try:
                c = gist_read()
                _GIST['body'] = c
                _GIST['ts'] = now
                try:
                    with open(LOCAL_STORE, 'w', encoding='utf-8') as f:
                        f.write(c)
                except Exception:
                    pass
            except Exception:
                pass
        if _GIST['body'] is not None:
            return _GIST['body']
    try:
        with open(LOCAL_STORE, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return '{}'


def store_put(data_bytes):
    try:
        with open(LOCAL_STORE, 'wb') as f:
            f.write(data_bytes)
    except Exception:
        pass
    if GH_TOKEN and GIST_ID:
        try:
            text = data_bytes.decode('utf-8')
            gist_write(text)
            _GIST['body'] = text
            _GIST['ts'] = time.time()
        except Exception:
            pass


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def _send(self, code, body, ctype='text/plain; charset=utf-8'):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/' :
            self.send_response(302)
            self.send_header('Location', '/' + urllib.parse.quote(DEFAULT_PAGE))
            self.end_headers()
            return
        if parsed.path == '/snapshot.js':
            self._send(200, get_snapshot(), 'application/javascript; charset=utf-8')
            return
        if parsed.path == '/store':
            self._send(200, store_get(), 'application/json; charset=utf-8')
            return
        if parsed.path == '/proxy':
            target = urllib.parse.parse_qs(parsed.query).get('url', [''])[0]
            host = urllib.parse.urlparse(target).hostname or ''
            if host not in ALLOW_HOSTS:
                self._send(403, 'host not allowed: ' + host); return
            try:
                self._send(200, fetch_url(target), 'application/json; charset=utf-8')
            except Exception as e:
                self._send(502, 'fetch failed: ' + str(e))
            return
        return super().do_GET()

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path == '/__save':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                data = self.rfile.read(length)
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                fn = os.path.basename(qs.get('file', ['kline_data.js'])[0])
                if not fn.endswith('.js'):
                    fn = 'kline_data.js'
                with open(os.path.join(DIR, fn), 'wb') as f:
                    f.write(data)
                self._send(200, '已寫回 ' + fn)
            except Exception as e:
                self._send(500, str(e))
        elif urllib.parse.urlparse(self.path).path == '/store':
            try:
                length = int(self.headers.get('Content-Length', '0'))
                data = self.rfile.read(length)
                json.loads(data.decode('utf-8'))  # 驗證是合法 JSON
                store_put(data)
                self._send(200, 'ok')
            except Exception as e:
                self._send(500, str(e))
        else:
            self._send(404, 'not found')


def main():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer((HOST, PORT), Handler) as httpd:
        print("伺服器執行中 %s:%d（含代抓股價）" % (HOST, PORT))
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已關閉。")


if __name__ == '__main__':
    main()
