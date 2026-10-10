"""Rich school/alias queries plus broad comparative queries for school attribution."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'python_service'))
from gradheat_python import bootstrap
from gradheat_python.collection_plan import known_units
from gradheat_core.intelligence import ALIASES, UCAS_COLLEGES, unique_units

BROAD = ['2027 11408 计算机考研 择校', '27考研 408 985 211 择校', '计算机考研 双非 上岸 院校推荐',
    '408 考研 复试线 录取最低分', '计算机考研 冷门 捡漏 大小年', '11408 软件工程 人工智能 网络安全 择校',
    '计算机考研 跨考 复试 机试', '2027 408 改考 扩招 缩招', '计算机考研 华东 华南 华中 院校对比',
    '计算机考研 北京 上海 江苏 浙江 四川 院校', '408 考研 统考名额 推免比例', '计算机考研 复录比 录取均分']
TEMPLATES = ['2027 11408 考研', '27考研 408 择校', '计算机 考研 复试线', '2026 计算机 录取最低分',
    '2025 计算机 拟录取', '计算机 统考名额 招生计划', '计算机 双非 复试 上岸', '计算机 跨考 复试 机试',
    '408 改考 扩招 缩招', '软件工程 考研', '人工智能 考研', '网络空间安全 考研',
    '计算机 考研 就业 导师', '计算机 考研 报录比 复录比']

def build(units, platforms=('bili','xhs','zhihu','dy')):
    tasks=[]
    for query in BROAD:
        for platform in platforms:
            tasks.append(dict(platform=platform,query=query,sort='general',limit=20 if platform=='dy' else 60,pages=1 if platform=='dy' else 3))
    for unit in unique_units(units):
        search_name='中国科学院大学 '+unit if unit in UCAS_COLLEGES else unit
        for word in TEMPLATES:
            for platform in platforms:
                tasks.append(dict(platform=platform,unit=unit,query=f'{search_name} {word}',sort='general' if platform=='dy' else 'latest',limit=20 if platform=='dy' else 60,pages=1 if platform=='dy' else 3))
        for alias in ALIASES.get(unit,[])[:1]:
            for platform in platforms:
                tasks.append(dict(platform=platform,unit=unit,query=f'{alias} 27考研 408',sort='general',limit=20,pages=1))
    return dict(schema_version=1,note='大类结果按正文识别院校，多校帖分别归档；首次有限采集后按冻结队列续跑。',
        settings={'execution':{'default_hours':8},'social':{'detail_limit':20,'image_limit':0,'query_interval_seconds':30}},tasks=tasks)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--platform',action='append');p.add_argument('--unit-limit',type=int);args=p.parse_args()
    units=[u.get('name') or u.get('unit') for u in known_units(ROOT)];units=list(dict.fromkeys(units))
    if args.unit_limit:units=units[:args.unit_limit]
    source=build(units,args.platform or ('bili','xhs','zhihu','dy'));args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(source,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'units':len(units),'tasks':len(source['tasks']),'output':str(args.output)},ensure_ascii=False))
