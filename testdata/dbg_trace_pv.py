# -*- coding: utf-8 -*-
import json
import urllib.request

req = urllib.request.Request(
    'http://localhost:8000/api/chat',
    data=json.dumps({'question': '光伏组件减产15%会有什么影响？'}).encode(),
    headers={'Content-Type': 'application/json'})
r = json.load(urllib.request.urlopen(req, timeout=180))
print('status:', r['analysis_status'])
for t in r['tool_trace']:
    print(' -', t['tool'], '->', str(t.get('result_preview', ''))[:90])
