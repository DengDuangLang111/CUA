"""Opt-in vLLM 0.25.1 diagnostics: actual paged-cache attention rows and logits.

Run with eager execution, FlashAttention, no speculative decoding, no prefix or
multimodal processor cache. Unsupported modes fail at startup, not silently.
Only selected output positions/layers/heads are copied; no full T x T matrix.
"""
from contextvars import ContextVar
from functools import wraps
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import time
from .attention_store import append_row, file_hash

CURRENT = ContextVar('cua_vllm_runner', default=None)
LOG = logging.getLogger('cua.vllm_capture')
CODE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def entropy(logits, *, logp=None):
    """Full vocabulary, before temperature/penalties/top-p; compute on device."""
    import torch
    if logp is None:
        logp = torch.log_softmax(logits.float(), dim=-1)
    return -(logp.exp() * logp).nan_to_num().sum(dim=-1)


def image_projection(weights, indices):
    """Keep original full-context softmax values; never renormalize image keys."""
    import torch
    visual = weights.index_select(0, indices)
    full = weights.double()
    image = visual.double()
    mass = full.sum()
    image_mass = image.sum()
    raw_entropy = -(full * full.log()).nan_to_num().sum()
    image_entropy = -(image * image.log()).nan_to_num().sum()
    total, im, ent, im_ent = torch.stack((mass, image_mass, raw_entropy, image_entropy)).tolist()
    other = max(0., total - im)
    import math
    return visual.detach().cpu().numpy(), dict(weights_scope='image_keys', stored_key_count=indices.numel(),
        weights_sum=total, non_image_mass=other,
        full_attention_entropy_nats=ent / total + math.log(total) if total else None,
        non_image_entropy_nats=(ent-im_ent) / other + math.log(other) if other else None)


def paged_attention_row(query, cache, blocks, length, kv_head, scale):
    """FlashAttention logical layout [block, K/V, position, kv_head, dim]."""
    import torch
    if cache.ndim != 5 or cache.shape[1] != 2 or cache.dtype not in (torch.float16, torch.bfloat16, torch.float32):
        raise ValueError('Expected unquantized FlashAttention cache [blocks,2,size,heads,dim]')
    block_size = cache.shape[2]
    nblocks = (length + block_size - 1)//block_size
    ids = blocks[:nblocks].long()
    if len(ids) != nblocks or (ids < 0).any() or (ids >= cache.shape[0]).any():
        raise ValueError('Invalid paged KV block table')
    # Gather only the selected KV head. Strides may be non-contiguous; torch handles them.
    keys = cache[:, 0, :, kv_head, :].index_select(0, ids).reshape(-1, cache.shape[-1])[:length]
    return torch.softmax(torch.mv(keys.float(), query.float()) * scale, dim=-1)


def image_mapping(features, vision, grid_cache=None):
    grid_cache = {} if grid_cache is None else grid_cache
    mapped=[]
    for feature in features:
        if feature.modality != 'image':
            raise ValueError('Only screenshot/image inputs are supported by this diagnostic')
        position=feature.mm_position
        indices=[i for begin,end in position.extract_embeds_range() for i in range(begin,end+1)]
        data=feature.data
        identifier=getattr(feature,'identifier',None)
        if data is not None and 'image_grid_thw' in data:
            grid=data['image_grid_thw'].data.detach().cpu().reshape(-1).tolist()
            if identifier is not None:grid_cache[identifier]=grid
        elif identifier is not None and identifier in grid_cache:
            grid=grid_cache[identifier]
        else:
            raise ValueError('Processor grid unavailable; disable multimodal processor caching')
        if len(grid)!=3 or grid[0]!=1:
            raise ValueError('Expected one still-image grid')
        merge=int(vision.spatial_merge_size);patch=int(vision.patch_size)
        t,h,w=grid;gh,gw=h//merge,w//merge
        if h%merge or w%merge or len(indices)!=gh*gw:
            raise ValueError('Processor grid does not match actual visual key spans')
        boxes=[[x/gw,y/gh,(x+1)/gw,(y+1)/gh] for y in range(gh) for x in range(gw)]
        mapped.append(dict(id=f'image-{len(mapped)}',token_count=len(indices),key_indices=indices,
            image_grid_thw=grid,spatial_merge_size=merge,patch_size=patch,
            processed_width=w*patch,processed_height=h*patch,patch_boxes=boxes,
            mapping='vllm_mm_position_and_qwen_whole_image_resize',processor_hash=feature.mm_hash))
    return mapped


def _path(directory, request_id, rank):
    # vLLM 0.25.1 appends an eight-hex engine nonce to the API response ID.
    request_id=re.sub(r'-[0-9a-f]{8}$','',request_id)
    key=hashlib.sha256(request_id.encode()).hexdigest()
    return Path(directory)/(key+f'.rank{rank}.jsonl')


def _write(directory, request_id, rank, row):
    path=_path(directory,request_id,rank);path.parent.mkdir(parents=True,exist_ok=True)
    if row.get('type')=='metadata':
        path.with_suffix('.attn').unlink(missing_ok=True)
    if row.get('type')=='attention' and row.pop('binary_storage',False):
        blob=path.with_suffix('.attn')
        row['weights_ref']=dict(append_row(blob,row.pop('weights')),blob=blob.name)
    with path.open('w' if row.get('type')=='metadata' else 'a') as stream:
        stream.write(json.dumps(dict(request_id=request_id,rank=rank,**row),allow_nan=False)+'\n')


def install():
    """Called by the opt-in sitecustomize in API and spawned GPU worker processes."""
    config_path=os.environ.get('CUA_VLLM_CAPTURE_CONFIG')
    if not config_path:return
    import vllm
    if vllm.__version__.split('+')[0]!='0.25.1':
        raise RuntimeError('CUA collector supports the verified vLLM 0.25.1 interface only')
    config=json.loads(Path(config_path).read_text())
    directory=config['directory']
    from vllm.v1.worker.gpu_model_runner import GPUModelRunner
    if getattr(GPUModelRunner.execute_model,'_cua_capture',False):return
    original_load=GPUModelRunner.load_model
    @wraps(original_load)
    def load(runner,*a,**kw):
        if not runner.model_config.enforce_eager:
            raise RuntimeError('Attention capture requires --enforce-eager; CUDA graphs bypass Python hooks')
        if runner.speculative_config is not None:
            raise RuntimeError('Speculative decoding is not supported by this diagnostic')
        pc=runner.vllm_config.parallel_config
        if pc.pipeline_parallel_size!=1 or pc.decode_context_parallel_size!=1:
            raise RuntimeError('Only tensor parallelism is supported')
        if runner.cache_config.cache_dtype!='auto':
            raise RuntimeError('Use --kv-cache-dtype auto for exact cache interpretation')
        result=original_load(runner,*a,**kw)
        from vllm.distributed import get_tensor_model_parallel_rank
        runner._cua_rank=get_tensor_model_parallel_rank()
        runner._cua_seen=set()
        runner._cua_failed=set()
        runner._cua_grid_cache={}
        runner._cua_image_keys={}
        runner._cua_pending=[]
        hf=runner.model_config.hf_config
        text=getattr(hf,'text_config',hf)
        full=[i for i,kind in enumerate(text.layer_types) if kind=='full_attention']
        runner._cua_layers=set(config.get('layers') or [full[-1]])
        if not runner._cua_layers.issubset(full):raise ValueError('Selected layers must be decoder full_attention layers')
        runner._cua_model=dict(checkpoint=runner.model_config.model,model_config=hf.to_dict(),
            tokenizer=runner.model_config.tokenizer,revision=runner.model_config.revision,
            tokenizer_revision=runner.model_config.tokenizer_revision,vllm_version=vllm.__version__,
            tensor_parallel=pc.tensor_parallel_size,origin='evaluation_forward',
            collector_sha256=CODE_SHA256,
            capture_scope=dict(layers=sorted(runner._cua_layers),heads=config.get('heads',[0]),
                               output_indices=config.get('output_indices',[0,16,64]),attention_storage=config.get('attention_storage','json'),
                               weights_scope=config.get('weights_scope','full')),
            attention_backend='FLASH_ATTN',enforce_eager=True,kv_cache_dtype=runner.cache_config.cache_dtype,
            entropy_stage='raw_logits_before_temperature_penalties_top_p')
        compute=runner.model.compute_logits
        @wraps(compute)
        def logits(hidden,*args,**kwargs):
            values=compute(hidden,*args,**kwargs)
            if values is not None and runner._cua_rank==0:
                try:
                    for item in _selected(runner,config):
                        vec=values[item['batch_index']].float()
                        import torch
                        lp=torch.log_softmax(vec,dim=-1)
                        best,ids=torch.topk(lp,min(int(config.get('top_k',5)),len(lp)))
                        runner._cua_pending.append((item,lp,dict(type='token',output_index=item['output_index'],
                            query=item['query'],entropy_nats=float(entropy(vec,logp=lp).item()),
                            top_logprobs=[dict(token_id=int(i),logprob=float(p)) for i,p in zip(ids.tolist(),best.tolist())],
                            entropy_stage='raw_logits_before_temperature_penalties_top_p')))
                except Exception as exc:
                    _failure(runner,directory,'logits_capture',exc)
            return values
        runner.model.compute_logits=logits
        sample=runner.sampler.forward
        @wraps(sample)
        def sampled(*args,**kwargs):
            try:
                output=sample(*args,**kwargs)
                try:
                    for item,lp,row in runner._cua_pending:
                        token_id=int(output.sampled_token_ids[item['batch_index'],0].item())
                        row.update(token_id=token_id,logprob=float(lp[token_id].item()))
                        _write(directory,item['request_id'],0,row)
                except Exception as exc:
                    _failure(runner,directory,'sample_capture',exc)
                return output
            finally:
                runner._cua_pending.clear()
        runner.sampler.forward=sampled
        return result
    GPUModelRunner.load_model=load
    original_prepare=GPUModelRunner._prepare_inputs
    @wraps(original_prepare)
    def prepare(runner,*a,**kw):
        result=original_prepare(runner,*a,**kw)
        if not hasattr(runner,'_cua_seen'):return result
        try:
            for req_id in runner.input_batch.req_ids:
                req=runner.requests[req_id]
                if req_id in runner._cua_seen or not (getattr(req.sampling_params,'extra_args',None) or {}).get('cua_capture'):continue
                images=image_mapping(req.mm_features,runner.model_config.hf_config.vision_config,runner._cua_grid_cache)
                import torch
                if config.get('weights_scope','full') not in ('full','image_keys'):
                    raise ValueError('Unknown attention weights_scope')
                runner._cua_image_keys[req_id]=torch.tensor([k for image in images for k in image['key_indices']],
                                                          dtype=torch.long,device=runner.device)
                _write(directory,req_id,runner._cua_rank,dict(type='metadata',images=images,
                    prompt_token_ids=req.prompt_token_ids,**runner._cua_model))
                runner._cua_seen.add(req_id)
        except Exception as exc:
            _failure(runner,directory,'input_mapping',exc)
        return result
    GPUModelRunner._prepare_inputs=prepare
    original_execute=GPUModelRunner.execute_model
    @wraps(original_execute)
    def execute(runner,*a,**kw):
        if hasattr(runner,'_cua_seen') and a:
            finished=a[0].finished_req_ids
            runner._cua_seen.difference_update(finished)
            runner._cua_failed.difference_update(finished)
            for req_id in finished:runner._cua_image_keys.pop(req_id,None)
        token=CURRENT.set(runner)
        try:return original_execute(runner,*a,**kw)
        finally:CURRENT.reset(token)
    execute._cua_capture=True
    GPUModelRunner.execute_model=execute

    from vllm.model_executor.layers.attention import Attention
    from vllm.forward_context import get_forward_context
    forward=Attention.forward
    @wraps(forward)
    def attention(layer,query,key,value,*a,**kw):
        result=forward(layer,query,key,value,*a,**kw)
        runner=CURRENT.get()
        if runner is None or not hasattr(runner,'_cua_layers'):return result
        try:
            capture_attention(runner,layer,query,result)
        except Exception as exc:
            _failure(runner,directory,'attention',exc)
        return result
    def capture_attention(runner,layer,query,result):
        match=re.search(r'\.layers\.(\d+)\.',layer.layer_name)
        if not match or int(match[1]) not in runner._cua_layers:return
        selected=list(_selected(runner,config))
        if not selected:return
        if layer.attn_backend.get_name()!='FLASH_ATTN':
            raise ValueError('Capture requires --attention-backend FLASH_ATTN')
        metadata=get_forward_context().attn_metadata[layer.layer_name]
        if metadata.sliding_window not in (None,(-1,-1)) or metadata.mm_prefix_range_tensor is not None:
            raise ValueError('Sliding-window and bidirectional image attention are unsupported')
        if getattr(layer.impl,'alibi_slopes',None) is not None or getattr(layer.impl,'logits_soft_cap',0):
            raise ValueError('ALiBi/logit soft caps are unsupported')
        q=query.view(-1,layer.num_heads,layer.head_size)
        for item in selected:
            if not item['attention_enabled']:continue
            req=runner.requests[item['request_id']]
            i=item['batch_index'];seq_len=int(metadata.seq_lens[i].item())
            row_index=int(metadata.query_start_loc[i+1].item())-1
            if seq_len-1!=item['query']:raise ValueError('Query/sequence alignment mismatch')
            for global_head in config.get('heads',[0]):
                head=global_head-runner._cua_rank*layer.num_heads
                if not 0<=head<layer.num_heads:continue
                started=time.perf_counter()
                weights=paged_attention_row(q[row_index,head],layer.kv_cache,metadata.block_table[i],
                    seq_len,head//(layer.num_heads//layer.num_kv_heads),layer.impl.scale)
                validation={}
                if config.get('validate_kernel'):
                    import torch
                    block_size=layer.kv_cache.shape[2]
                    blocks=metadata.block_table[i][:(seq_len+block_size-1)//block_size].long()
                    kv_head=head//(layer.num_heads//layer.num_kv_heads)
                    values=layer.kv_cache[:,1,:,kv_head,:].index_select(0,blocks).reshape(-1,layer.head_size)[:seq_len]
                    reference=weights@values.float()
                    actual=result.view(-1,layer.num_heads,layer.head_size)[row_index,head].float()
                    torch.testing.assert_close(reference,actual,atol=.04,rtol=.04)
                    validation['kernel_max_abs_error']=float((reference-actual).abs().max().item())
                binary = config.get('attention_storage')=='binary'
                scope = {}
                if config.get('weights_scope','full')=='image_keys':
                    stored_weights,scope=image_projection(weights,runner._cua_image_keys[item['request_id']])
                    if not binary:stored_weights=stored_weights.tolist()
                else:
                    stored_weights = weights.detach().cpu().numpy() if binary else weights.tolist()
                _write(directory,req.req_id,runner._cua_rank,dict(type='attention',layer=int(match[1]),head=global_head,
                    query=seq_len-1,output_index=item['output_index'],key_count=seq_len,
                    dtype=str(query.dtype),weights=stored_weights,binary_storage=binary,
                    capture_seconds=time.perf_counter()-started,**validation,**scope))
    Attention.forward=attention
    _install_response_merge(directory)


def _failure(runner,directory,stage,exc):
    LOG.exception('CUA diagnostic capture failed; model output is unchanged')
    for req_id in runner.input_batch.req_ids:
        req=runner.requests[req_id]
        if not (getattr(req.sampling_params,'extra_args',None) or {}).get('cua_capture'):continue
        runner._cua_failed.add(req_id)
        try:_write(directory,req_id,runner._cua_rank,dict(type='capture_error',stage=stage,error_type=type(exc).__name__,message=str(exc)))
        except Exception:LOG.exception('Unable to write capture error')


def _selected(runner,config):
    if not hasattr(runner,'_cua_layers'):return
    indices=config.get('output_indices',[0,16,64])
    wanted=None if indices=='all' else set(indices)
    for i,req_id in enumerate(runner.input_batch.req_ids):
        req=runner.requests[req_id]
        extra=getattr(req.sampling_params,'extra_args',None) or {}
        if not extra.get('cua_capture') or req_id in runner._cua_failed:continue
        # At compute_logits/attention, positions/seq_lens are the current GPU forward's values.
        end=int(runner.optimistic_seq_lens_cpu[i].item())
        output_index=end-req.num_prompt_tokens
        if output_index >= 0 and (wanted is None or output_index in wanted):
            yield dict(request_id=req_id,batch_index=i,query=end-1,output_index=output_index,
                       attention_enabled=extra.get('cua_attention',True))


def collect(directory,response_id):
    """Called after generation, when all selected row writes have completed."""
    rows=[]
    # n=1 is the supported agent contract. vLLM workers append the choice index.
    for req_id in (response_id,response_id+'-0'):
        for path in Path(directory).glob(hashlib.sha256(req_id.encode()).hexdigest()+'.rank*.jsonl'):
            rows.extend(json.loads(line) for line in path.read_text().splitlines() if line.strip())
    metadata=[r for r in rows if r['type']=='metadata']
    errors=[r for r in rows if r['type']=='capture_error']
    if not metadata:return {'capture_errors':errors} if errors else None
    base=metadata[0]
    for other in metadata[1:]:
        if other['prompt_token_ids']!=base['prompt_token_ids'] or other['images']!=base['images']:
            raise ValueError('Tensor-parallel image/token mapping disagrees')
    blobs={}
    for row in rows:
        if 'weights_ref' in row:
            name=row['weights_ref']['blob']
            if name not in blobs:
                path=Path(directory)/name
                blobs[name]=dict(bytes=path.stat().st_size,sha256=file_hash(path))
    return {**base,'capture_errors':errors,'attention_blobs':blobs,'attention':[r for r in rows if r['type']=='attention'],
            'token_diagnostics':[r for r in rows if r['type']=='token']}


def token_counts(prompt_ids, output_ids, tokenizer):
    """Count the actual engine stream using Qwen's explicit reasoning delimiters."""
    opening=tokenizer.encode('<think>',add_special_tokens=False)
    closing=tokenizer.encode('</think>',add_special_tokens=False)
    if len(opening)!=1 or len(closing)!=1:
        return {'output':{'value':len(output_ids),'provenance':'engine_token_ids'},
                'reasoning':{'value':None,'provenance':'unsupported_reasoning_delimiters'}},[]
    op,cl=opening[0],closing[0]
    last_open=max((i for i,t in enumerate(prompt_ids) if t==op),default=-1)
    last_close=max((i for i,t in enumerate(prompt_ids) if t==cl),default=-1)
    thinking=last_open>last_close
    phases=[]
    specials=set(tokenizer.all_special_ids)
    for token in output_ids:
        phases.append('control' if token in specials else 'reasoning' if thinking else 'content')
        if token==op:thinking=True
        if token==cl:thinking=False
    counts={name:{'value':phases.count(name),'provenance':'engine_token_ids_and_reasoning_delimiters'}
            for name in ('reasoning','content','control')}
    counts.update(output={'value':len(output_ids),'provenance':'engine_token_ids'},
                  input={'value':len(prompt_ids),'provenance':'engine_token_ids'})
    return counts,phases


def _install_response_merge(directory):
    from vllm.entrypoints.openai.chat_completion.serving import OpenAIServingChat
    original=OpenAIServingChat.create_chat_completion
    @wraps(original)
    async def create(server,request,*a,**kw):
        raw=kw.get('raw_request') or (a[0] if a else None)
        if raw is not None and not getattr(raw.app.state,'cua_artifacts',False):
            from starlette.responses import FileResponse, Response
            async def artifact(name: str):
                if not re.fullmatch(r'[0-9a-f]{64}\.rank[0-9]+\.attn',name):
                    return Response(status_code=404)
                path=Path(directory)/name
                return FileResponse(path,media_type='application/octet-stream') if path.is_file() else Response(status_code=404)
            # The existing vLLM API-key middleware protects /v1 routes.
            raw.app.add_api_route('/v1/cua-attention/{name}',artifact,methods=['GET'])
            raw.app.state.cua_artifacts=True
        response=await original(server,request,*a,**kw)
        try:
            if not getattr(request,'stream',False) and hasattr(response,'id'):
                signals=await asyncio.to_thread(collect,directory,response.id)
                if signals and 'prompt_token_ids' in signals:
                    choices=response.choices
                    ids=getattr(choices[0],'token_ids',None) if len(choices)==1 else None
                    signals['output_token_ids']=ids
                    if response.prompt_token_ids!=signals['prompt_token_ids']:
                        raise ValueError('API prompt tokens differ from the captured worker input')
                    for row in signals['token_diagnostics']:
                        index=row['output_index']
                        if ids and index<len(ids) and row['token_id']!=ids[index]:
                            raise ValueError('Sampled token does not match API output position')
                    tokenizer=server.renderer.tokenizer
                    if ids is not None and tokenizer is not None:
                        signals['token_counts'],phases=token_counts(signals['prompt_token_ids'],ids,tokenizer)
                        for row in signals['token_diagnostics']:
                            index=row['output_index']
                            row.update(text=tokenizer.decode([row['token_id']]),phase=phases[index])
                    if response.__pydantic_extra__ is None:response.__pydantic_extra__={}
                    response.__pydantic_extra__['cua_signals']=signals
                elif signals:
                    if response.__pydantic_extra__ is None:response.__pydantic_extra__={}
                    response.__pydantic_extra__['cua_signals']=signals
        except Exception as exc:
            LOG.exception('CUA response enrichment failed; original response is unchanged')
            if hasattr(response,'__pydantic_extra__'):
                if response.__pydantic_extra__ is None:response.__pydantic_extra__={}
                response.__pydantic_extra__['cua_signals']={'capture_errors':[{'stage':'response_merge','message':str(exc)}]}
        return response
    OpenAIServingChat.create_chat_completion=create
