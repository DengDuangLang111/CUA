"""Pause native processes only after a recorded model reply; keep VM/process state.

Run on the eval host. Calls are bounded single checks; resume only after service
readiness. The durable receipt identifies exact process start times and requests.
"""
import argparse
import os
from pathlib import Path
import signal
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from sft.scripts.eval import run_eval as run
_BOUNDARIES = {}


def boundary(task):
    try:
        events=task/'capture/events.jsonl'
        with events.open('rb') as stream:
            stream.seek(max(0,events.stat().st_size-65536))
            lines=stream.read().splitlines()
        import json
        last=json.loads(lines[-1])
        if last['type']!='decision_start':return None
        matches=list((task/'capture/requests').glob('cua-{}-{}-*.json'.format(last['session'],last['step_num'])))
        if not matches:return None
        source=max(matches,key=lambda p:p.stat().st_mtime_ns)
        responses=list((task/'capture/assets').glob('*.response.json'))
        wire=max(responses,key=lambda p:p.stat().st_mtime_ns) if responses else None
        key=(str(source),source.stat().st_mtime_ns,last['decision_id'],str(wire),wire.stat().st_mtime_ns if wire else None)
        previous=_BOUNDARIES.get(str(task))
        if previous and previous[0]==key:return previous[1]
        record=run.read_json(source)
        result=None
        if record.get('decision_id')==last['decision_id'] and record.get('response_sha256'):
            result={k:record[k] for k in ['decision_id','request_id','response_sha256']}
        elif record.get('decision_id')==last['decision_id'] and wire and wire.stat().st_mtime_ns>source.stat().st_mtime_ns:
            # Older synchronous clients may still be downloading attention after
            # the complete model reply has already been archived by the HTTP hook.
            raw=wire.read_bytes();body=json.loads(raw)
            if run.hashlib.sha256(raw).hexdigest()==wire.name[:64] and body.get('choices') and body.get('cua_signals'):
                result=dict(decision_id=record['decision_id'],request_id=record['request_id'],response_sha256=wire.name[:64],boundary='api_reply_saved')
        _BOUNDARIES[str(task)]=(key,result)
        return result
    except (OSError,ValueError,KeyError,IndexError):return None


def maintain(plan,host,action,teachers):
    effective,_,folder=run.paths(plan,host)
    routes=run.read_json(folder/'service-routes.json',{})
    path=folder/'maintenance-calls.json'
    receipt=run.read_json(path,{'plan_sha256':plan['plan_sha256'],'processes':{}})
    run.require(receipt['plan_sha256']==plan['plan_sha256'],'Wrong maintenance run')
    if action=='resume':
        for item in receipt['processes'].values():
            if item['teacher'] not in teachers or item.get('resumed_at'):continue
            if run.alive(item['process']):
                run.require(os.getpgid(item['process']['pid'])==item['process']['pid'],'Wrong process group')
                os.killpg(item['process']['pid'],signal.SIGCONT)
            item['resumed_at']=time.time()
        run.write_json(path,receipt)
        return receipt
    pending=[]
    for state_path in (folder/'task-state').glob('*.json'):
        state=run.read_json(state_path);proc=state.get('process');teacher=state.get('teacher_id')
        if teacher not in teachers or not run.alive(proc):continue
        execution=run.read_json(Path(state['attempt'])/'execution.json',{})
        desired=effective.get('endpoints',{}).get(teacher,{}).get('url')
        # Already migrated tasks are not paused again by a repeated check.
        if routes and teacher not in routes.get('pause_teachers',[]) and execution.get('teacher_url')==desired:continue
        key=str(proc['pid']);previous=receipt['processes'].get(key)
        if previous and previous['process']==proc and not previous.get('resumed_at'):continue
        if previous and previous['process']==proc and previous.get('revision',routes.get('revision'))==routes.get('revision'):continue
        task=Path(state['attempt'])/state['task'][0]/state['task'][1]
        before=boundary(task)
        if before is None:
            pending.append(dict(task=state['task'],teacher=teacher,reason='waiting_for_model_reply'));continue
        run.require(os.getpgid(proc['pid'])==proc['pid'],'Wrong native process group')
        # Record intent before SIGSTOP so recovery can always issue SIGCONT.
        if previous:receipt.setdefault('history',[]).append(previous)
        item=dict(process=proc,teacher=teacher,task=state['task'],boundary=before,pausing_at=time.time(),revision=routes.get('revision'))
        receipt['processes'][key]=item;run.write_json(path,receipt)
        os.killpg(proc['pid'],signal.SIGSTOP)
        if not run.alive(proc) or boundary(task)!=before:
            if run.alive(proc):os.killpg(proc['pid'],signal.SIGCONT)
            item['resumed_at']=time.time();pending.append(dict(task=state['task'],teacher=teacher,reason='boundary_changed'))
        else:item['paused_at']=time.time()
        run.write_json(path,receipt)
    return dict(receipt=receipt,pending=pending)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['pause','resume']);p.add_argument('--plan',type=Path,required=True);p.add_argument('--host',required=True);p.add_argument('--teachers',nargs='+',required=True)
    args=p.parse_args();plan=run.validate_plan(run.read_json(args.plan))
    import json
    print(json.dumps(maintain(plan,args.host,args.action,args.teachers)))

if __name__=='__main__':main()
