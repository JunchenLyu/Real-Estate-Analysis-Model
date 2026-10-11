# -*- coding: utf-8 -*-
"""模式×方向 全组合回归测试：在线(auto)/离线(offline) × 供给侧/需求侧/未定义"""
import json
import urllib.request
import os

BASE = os.environ.get('FINANCIAL_TEST_BASE', 'http://localhost:8000')
FAILS = []


def post(path, payload, timeout=180):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def set_mode(mode):
    post('/api/agent/mode', {'mode': mode}, timeout=10)


def ask(q):
    return post('/api/chat', {'question': q})


def check(name, cond, detail=''):
    tag = 'PASS' if cond else 'FAIL'
    print(f"   [{tag}] {name}" + (f" | {detail}" if detail else ''))
    if not cond:
        FAILS.append(f"{name} {detail}")


Q_SUPPLY = '钢铁减产10%对哪些行业影响最大'
Q_DEMAND = '分析房地产投资下降15%的影响'
Q_UNDEF_MAG = '钢铁减产会有什么影响'          # 未定义：有冲击语义但无幅度
Q_UNDEF_SECTOR = '光伏组件减产15%会有什么影响？'  # 未定义：行业超出13部门口径

for mode in ('auto', 'offline'):
    set_mode(mode)
    print(f"\n===== 模式: {mode} =====")
    r_mode = json.load(urllib.request.urlopen(BASE + '/api/agent/mode', timeout=10))
    print(f"   mode_setting={r_mode['mode']} | LLM可用={r_mode['llm_available']}")
    mode_is_llm = (mode == 'auto')

    # ---- 供给侧 → Ghosh ----
    r = ask(Q_SUPPLY)
    st = r.get('analysis_status')
    model = (r.get('impact') or {}).get('model', '')
    print(f" A 供给侧「{Q_SUPPLY}」 status={st} | model={model[:30]}")
    check('模式标注正确', r.get('agent_mode') is not None, r.get('agent_mode', ''))
    check('执行路径可追踪', r.get('execution_mode') in (
        'offline', 'rule_fallback', 'llm', 'llm_with_rule_completion'),
          r.get('execution_mode', ''))
    check('status=quantified_ghosh', st == 'quantified_ghosh', st)
    check('Ghosh模型', model.startswith('Ghosh'), model[:40])
    check('有综合评分', isinstance(r.get('risk_score'), (int, float)), str(r.get('risk_score')))
    check('影响表≥3行业', len(r.get('affected_industries', [])) >= 3,
          f"{len(r.get('affected_industries', []))}个")
    check('摘要含供给侧口径', '供给侧' in r.get('summary', ''))

    # ---- 需求侧 → Leontief ----
    r = ask(Q_DEMAND)
    st = r.get('analysis_status')
    model = (r.get('impact') or {}).get('model', '')
    print(f" B 需求侧「{Q_DEMAND}」 status={st} | model={model[:30]}")
    check('status=quantified_leontief', st == 'quantified_leontief', st)
    check('Leontief模型', model.startswith('Leontief'), model[:40])
    check('有综合评分', isinstance(r.get('risk_score'), (int, float)), str(r.get('risk_score')))
    check('影响表≥3行业', len(r.get('affected_industries', [])) >= 3,
          f"{len(r.get('affected_industries', []))}个")
    stages = (r.get('impact') or {}).get('transmission_stages', {}).get('stages', [])
    check('三阶段=3', len(stages) == 3, f"{len(stages)}个")

    # ---- 未定义幅度 → 定性（不进数量模型） ----
    r = ask(Q_UNDEF_MAG)
    st = r.get('analysis_status')
    has_quant = r.get('risk_score') is not None or bool(r.get('affected_industries'))
    print(f" C 未定义幅度「{Q_UNDEF_MAG}」 status={st}")
    check('无量化评分/影响表', not has_quant, f"score={r.get('risk_score')} 表={len(r.get('affected_industries', []))}")
    check('status=missing_magnitude', st == 'missing_magnitude', str(st))

    # ---- 未定义行业（超出口径） → 拒绝量化 ----
    r = ask(Q_UNDEF_SECTOR)
    st = r.get('analysis_status')
    has_quant = r.get('risk_score') is not None or bool(r.get('affected_industries'))
    print(f" D 未定义行业「{Q_UNDEF_SECTOR}」 status={st}")
    check('无量化评分/影响表', not has_quant, f"score={r.get('risk_score')}")
    check('status=sector_unresolved', st == 'sector_unresolved', str(st))
    check('摘要提示明确口径', ('口径' in r.get('summary', '')) or ('模型状态' in r.get('summary', '')))

set_mode('auto')  # 恢复默认
print('\n' + ('=' * 40))
if FAILS:
    print(f"共 {len(FAILS)} 项 FAIL:")
    for f in FAILS:
        print('  -', f)
    raise SystemExit(1)
else:
    print('ALL PASS: 在线/离线 × 供给侧/需求侧/未定义 全部通过')
