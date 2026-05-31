import sys, time, json, threading
sys.path.insert(0, 'src')

from app import app

def run_server():
    app.run(host='127.0.0.1', port=5556, debug=False, use_reloader=False, threaded=True)

t = threading.Thread(target=run_server, daemon=True)
t.start()
time.sleep(2)

import urllib.request

# First initialize
req = urllib.request.Request(
    'http://127.0.0.1:5556/api/initialize',
    data=json.dumps({'nodes': 10, 'resources': 20, 'm': 16, 'seed': 61, 'replication_count': 1}).encode(),
    headers={'Content-Type': 'application/json'},
    method='POST'
)
with urllib.request.urlopen(req, timeout=10) as resp:
    data = json.loads(resp.read())
    print('Initialize:', data.get('ok'), '- nodes:', data['state']['active_node_count'], '- resources:', data['state']['resource_count'])

time.sleep(0.5)

# Then metrics
req2 = urllib.request.Request(
    'http://127.0.0.1:5556/api/metrics',
    data=json.dumps({'trials': 1, 'lookups': 10}).encode(),
    headers={'Content-Type': 'application/json'},
    method='POST'
)
try:
    with urllib.request.urlopen(req2, timeout=15) as resp:
        data = json.loads(resp.read())
        print('Metrics status:', resp.status)
        print('OK:', data.get('ok'))
        print('Message:', data.get('message'))
        points = data.get('sweep_points', [])
        print('Sweep points count:', len(points))
        for p in points[:3]:
            print('  - nodes:', p.get('nodes'), 'avg_hops:', p.get('average_hops'))
        charts = data.get('charts', {})
        print('Charts:', list(charts.keys()))
except Exception as e:
    print(f'Error: {e}')
