"""Comic-specific generation, with pinned inputs across retries."""
from __future__ import annotations

import json
from copy import deepcopy
from uuid import uuid4

from .comic import COMIC_SYSTEM, build_prompt, final_prompt, panel_by_id, panels, recompute
from .providers import effective_image_provider, ProviderError


def rebuild_prompts(project, panel_ids, provider=None):
    recompute(project)
    for panel in panels(project):
        if panel['id'] not in panel_ids or panel.get('locks',{}).get('prompt'):
            continue
        positive, negative = build_prompt(project,panel)
        if provider:
            data = json.loads(provider.text(COMIC_SYSTEM + ' Rebuild only positive_prompt and negative_prompt for clean comic panel artwork. Preserve current user edits and separate lettering. Return these two string fields.',
                              json.dumps(dict(panel=panel, comic_context=positive, style=project.get('style')), ensure_ascii=False),purpose='comic:prompt'))
            positive, negative = data['positive_prompt'], data['negative_prompt']
            if not isinstance(positive,str) or not isinstance(negative,str):
                raise ValueError('漫画 Prompt 返回格式无效')
        panel['positive_prompt'], panel['negative_prompt'] = positive, negative


def generation_request(repository, project, panel, size):
    prompt, negative = final_prompt(project,panel)
    groups = []
    cards = {c['id']:c for c in project['characters']}
    reference_roles = []
    for character_id in panel['characters']:
        card = cards.get(character_id,{})
        paths = card.get('reference_images',[])
        if paths:
            groups.append(paths)
            reference_roles.extend([f"character identity for {card.get('name',character_id)}, use current state clothing rather than reference costume"] * len(paths))
    style = project.get('style',{})
    style_paths = style.get('reference_images',[]) if style.get('reference_mode') == 'image' else []
    scene = next((s for s in project.get('scenes',[]) if s['id'] == panel.get('scene_id')), {})
    scene_paths = scene.get('reference_images',[])
    reference_roles.extend(['style only'] * len(style_paths))
    reference_roles.extend(['scene setting only; do not copy characters or panel layout'] * len(scene_paths))
    if reference_roles:
        prompt += '\nReference image roles in delivery order: ' + '; '.join(f'{i+1}: {role}' for i,role in enumerate(reference_roles))
    return dict(strategy='comic-panel-v1',positive_prompt=prompt,negative_prompt=negative,size=size,
                states=deepcopy(panel.get('effective_states',{})),style=deepcopy(style),scene=deepcopy(scene),
                identity_groups=deepcopy(groups),style_references=deepcopy(style_paths),scene_references=deepcopy(scene_paths),
                reference_roles=reference_roles)


def generate(repository, project_id, provider, panel_ids, size, retries, reporter, retry_failed=False):
    frozen = repository.load(project_id)
    issues = recompute(frozen)
    selected = [p for p in panels(frozen) if p['id'] in panel_ids]
    if len(selected) != len(set(panel_ids)):
        raise ValueError('选中的画格不存在')
    results = []
    for index,panel in enumerate(selected):
        reporter.update('逐格生图',int(index*95/max(1,len(selected))),f'{index+1}/{len(selected)}')
        request = deepcopy(panel.get('generation_request')) if retry_failed else None
        if not request:
            errors = [i['message'] for i in issues if i['panel_id']==panel['id'] and i['severity']=='error']
            if errors:
                raise ValueError('；'.join(errors))
            request = generation_request(repository,frozen,panel,size)
        provider_identity = dict(provider=provider.config.image.provider,base_url=provider.config.image.base_url,model=provider.config.image.model,options=deepcopy(getattr(provider.config,'image_options',None) or {}))
        if retry_failed and request.get('provider') not in (None, provider_identity):
            raise ValueError('图片供应商已变化，不能作为原请求重试；请显式重新生成')
        request['provider'] = provider_identity
        # Pinned request is persisted before the first external call.
        with repository.transaction(project_id) as current:
            live = panel_by_id(current,panel['id'])
            if retry_failed and live.get('generation_request',{}).get('provider') not in (None,request['provider']):
                raise ValueError('图片供应商已变化，不能作为原请求重试；请显式重新生成')
            live['generation_request'] = deepcopy(request)
            live['generation_status'] = 'running'
        identities = [[repository.asset(project_id,p) for p in group] for group in request['identity_groups']]
        styles = [repository.asset(project_id,p) for p in request['style_references']]
        scenes = [repository.asset(project_id,p) for p in request['scene_references']]
        runtime = effective_image_provider(provider.config.image)
        if identities and runtime == 'siliconflow':
            error = '当前 SiliconFlow 适配器不支持角色参考原图；请移除参考图或切换供应商。未丢弃参考图。'
            with repository.transaction(project_id) as current:
                live = panel_by_id(current,panel['id'])
                live.update(generation_error=error,generation_status='failed')
            raise ValueError(error)
        if (styles or scenes) and runtime in {'comfyui','siliconflow'}:
            error = '当前适配器不支持独立场景/画风原图参考；请改用文字描述或切换供应商。未丢弃参考图。'
            with repository.transaction(project_id) as current:
                live = panel_by_id(current,panel['id'])
                live.update(generation_error=error,generation_status='failed')
            raise ValueError(error)
        target = repository.run_dir(project_id) / 'assets' / f'{uuid4().hex}.png'
        target.parent.mkdir(parents=True,exist_ok=True)
        error = ''
        for attempt in range(max(0,min(5,retries))+1):
            try:
                # Scene images use the existing visual-image transport, with an
                # explicit scene role; the disabled composition preset is unused.
                kwargs = dict(reference_images=[p for g in identities for p in g],reference_image_groups=identities,
                              style_reference_images=styles, composition_reference_images=scenes,
                              reference_roles_embedded=bool(styles or scenes))
                provider.image(request['positive_prompt'], target,size=request['size'],negative_prompt=request['negative_prompt'],
                               purpose=f'comic:image:{project_id}:{panel["id"]}',**kwargs)
                if not target.is_file():
                    raise ProviderError('供应商未返回图片文件')
                relative = 'assets/' + target.name
                version = dict(id='version_'+uuid4().hex,path=relative,snapshot=deepcopy(request))
                with repository.transaction(project_id) as current:
                    live = panel_by_id(current,panel['id'])
                    live['image_versions'].append(version)
                    if not live.get('current_image'):
                        live['current_image'] = relative
                    live['generation_error'] = ''
                    live['generation_status'] = 'succeeded'
                error = ''
                break
            except Exception as exc:
                from .logging_utils import redact_text
                error = redact_text(str(exc))
                reporter.log(f"{panel['id']} 第 {attempt+1} 次失败：{error}")
        if error:
            with repository.transaction(project_id) as current:
                live = panel_by_id(current,panel['id'])
                live.update(generation_error=error,generation_status='failed')
        results.append(dict(panel_id=panel['id'],ok=not bool(error),error=error))
    if any(not r['ok'] for r in results):
        raise ProviderError('部分画格生成失败：' + '；'.join(r['error'] for r in results if not r['ok']))
    return dict(results=results)
