"""Replay one saved request with explicit image perturbations; never execute actions."""
import argparse
import base64
import copy
import io
import json
import os
from pathlib import Path
import uuid

from .capture import ACTIVE, Recorder, append, install_openai_hook, reconstruct_request
from .visual_signals import read_json, write_json


def perturb(request, spec):
    """Image index is the occurrence in the final request, not a source filename."""
    from PIL import Image, ImageDraw, ImageFilter
    changed=copy.deepcopy(request)
    occurrences=[]
    for message in changed['messages']:
        content=message.get('content')
        if isinstance(content,list):
            for part in content:
                if part.get('type')=='image_url':occurrences.append((content,part))
    operation=spec['operation']
    if operation=='baseline':return changed
    content,part=occurrences[spec['image_index']]
    if operation=='remove':
        content.remove(part)
        return changed
    uri=part['image_url']['url']
    if not uri.startswith('data:image/'):
        raise ValueError('Intervention requires archived image bytes, not a mutable remote URL')
    with Image.open(io.BytesIO(base64.b64decode(uri.split(',',1)[1]))) as raw:
        image=raw.convert('RGB')
    if operation=='replace':
        with Image.open(spec['path']) as raw:image=raw.convert('RGB')
    elif operation in ('occlude','blur'):
        box=spec['box']
        if len(box)!=4 or not (0<=box[0]<box[2]<=1 and 0<=box[1]<box[3]<=1):
            raise ValueError('box must be normalized [left,top,right,bottom]')
        pixels=(round(box[0]*image.width),round(box[1]*image.height),round(box[2]*image.width),round(box[3]*image.height))
        if pixels[0]>=pixels[2] or pixels[1]>=pixels[3]:raise ValueError('Region has no pixels')
        if operation=='occlude':
            # PIL rectangle includes its right/bottom edges; crop/paste gives an exact half-open region.
            image.paste(Image.new('RGB',(pixels[2]-pixels[0],pixels[3]-pixels[1]),tuple(spec.get('color',[127,127,127]))),pixels)
        else:
            image.paste(image.crop(pixels).filter(ImageFilter.GaussianBlur(float(spec.get('radius',8)))),pixels)
    else:raise ValueError('Supported operations: baseline, remove, replace, occlude, blur')
    output=io.BytesIO();image.save(output,format='PNG')
    part['image_url']['url']='data:image/png;base64,'+base64.b64encode(output.getvalue()).decode()
    return changed


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('record',type=Path,help='capture/requests/<id>.json')
    parser.add_argument('--spec',type=Path,required=True,help='JSON list of explicit perturbations; baseline is added')
    parser.add_argument('--base-url',required=True)
    parser.add_argument('--api-key-env',default='OPENAI_API_KEY')
    parser.add_argument('--inspection-config',type=Path)
    parser.add_argument('--run-dir',type=Path)
    args=parser.parse_args()
    from openai import OpenAI
    record=read_json(args.record);task=args.record.resolve().parents[2]
    original=reconstruct_request(record,task)
    specs=read_json(args.spec)
    if not isinstance(specs,list):raise ValueError('Expected a list of intervention specs')
    specs=[{'operation':'baseline'}]+[s for s in specs if s['operation']!='baseline']
    group=uuid.uuid4().hex
    install_openai_hook()
    client=OpenAI(base_url=args.base_url,api_key=os.environ[args.api_key_env],timeout=600)
    for index,spec in enumerate(specs):
        directory=task/'capture'/'interventions'/group/str(index)
        recorder=Recorder(directory,{'backend':'vllm'},{'model_path':record.get('checkpoint')})
        recorder.step=1;recorder.decision=f'counterfactual-{group}-{index}'
        token=ACTIVE.set(recorder)
        try:
            response=client.chat.completions.create(**perturb(original,spec))
            message=response.choices[0].message
            reasoning=getattr(message,'reasoning',None) or getattr(message,'reasoning_content',None)
            text=(f'<think>\n{reasoning}\n</think>\n\n' if reasoning else '')+(message.content or '')
            recorder.finish_response(text)
        finally:ACTIVE.reset(token)
        result=dict(parent_request_id=record['request_id'],comparison_group=group,spec=spec,
            origin='counterfactual_request_only',actions_executed=False,response=text,
            request_path=(directory/'capture/requests'/(recorder.last_request['request_id']+'.json')).relative_to(task).as_posix(),
            api_response=recorder.last_request['api_response'])
        append(task/'capture/interventions.jsonl',result)
        print(json.dumps({'operation':spec['operation'],'request':result['request_path']}))
    if args.inspection_config:
        if not args.run_dir:parser.error('--run-dir is required to rebuild the page')
        from sft.scripts.eval.after_task import render_task
        render_task(task,args.run_dir,read_json(args.inspection_config))


if __name__=='__main__':main()
