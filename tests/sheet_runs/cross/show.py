import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
for k, r in d.items():
    print(f"\n##### {k} [{r['kind']}] schemes={r.get('schemes')} rule={r.get('rule')} {r['ms']}ms\nQ: {r['q']}")
    print((r.get('answer') or '')[:int(sys.argv[2]) if len(sys.argv) > 2 else 2500])
    if r['kind'] == 'pause': print("OPTIONS:", r.get('options'))
