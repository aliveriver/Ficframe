"""HTTP adapter for the independent comic workspace."""
from __future__ import annotations

import io
import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, Response

from .comic import new_project, normalize_characters, operation, panels, plan_script, recompute, validate
from .comic_repository import ComicRepository, RevisionConflict
from .comic_workflow import generate, rebuild_prompts
from .run_repository import RunRepository
from .task_manager import TaskManager


def create_router(api):
    router = APIRouter()
    repositories = {}
    managers = {}

    def repository():
        root = Path(api.RUNS).parent / 'comics'
        key = str(root.resolve())
        if key not in repositories:
            repositories[key] = ComicRepository(root)
        return repositories[key]

    def manager():
        repo = repository()
        key = str(repo.root)
        if key not in managers:
            managers[key] = TaskManager(repo)
        return managers[key]

    def load(project_id):
        try:
            return repository().load(project_id)
        except (OSError, ValueError) as exc:
            raise HTTPException(404,str(exc)) from exc

    def transact(project_id, callback):
        try:
            with repository().transaction(project_id) as project:
                callback(project)
            return load(project_id)
        except (ValueError, KeyError, StopIteration, TypeError) as exc:
            raise HTTPException(400,str(exc) or '画格或页面不存在') from exc

    def copy_run_asset(repo, project_id, run_id, reference):
        prefix = f'/runs/{run_id}/'
        if not isinstance(reference,str) or not reference.startswith(prefix):
            raise ValueError('来源素材必须属于来源小说工程')
        root = api.get_run_repository().run_dir(run_id)
        source = (root / reference[len(prefix):].split('?',1)[0]).resolve()
        if root not in source.parents or not source.is_file():
            raise ValueError('来源素材缺失或路径无效')
        return repo.add_asset(project_id,source.name,source.read_bytes())

    @router.get('/comic')
    def workspace():
        return FileResponse(api.WEB / 'comic.html')

    @router.get('/api/comics')
    def listing():
        return {'projects':repository().list_projects()}

    @router.post('/api/comics')
    def create(request:dict):
        try:
            repo = repository()
            source_id = request.get('source_run_id')
            source = api.get_run_repository().load(source_id) if source_id else {}
            text = api.get_run_repository().novel_path(source_id).read_text(encoding='utf-8') if source_id else request.get('source_text','')
            project = new_project(request.get('title',''),text,source.get('characters') or request.get('characters',[]))
            if source_id:
                project['source_project'] = source_id
                for card in project['characters']:
                    card['reference_images'] = [copy_run_asset(repo,project['id'],source_id,p) for p in card.get('reference_images',[])]
                project['candidate_images'] = []
                for shot in source.get('shots',[]):
                    if shot.get('image_url'):
                        project['candidate_images'].append(dict(path=copy_run_asset(repo,project['id'],source_id,shot['image_url']),title=shot.get('title','')))
                snapshot = source.get('visual_presets',{}).get('style_snapshot',{})
                if snapshot:
                    project['style'] = deepcopy(snapshot)
                    project['style']['reference_images'] = []
                    store = api.get_visual_preset_store()
                    for relative in snapshot.get('reference_images',[]):
                        path = store.reference_path(relative)
                        project['style']['reference_images'].append(repo.add_asset(project['id'],path.name,path.read_bytes()))
            repo.save(project['id'],project)
            return project
        except (ValueError,OSError,KeyError) as exc:
            raise HTTPException(400,str(exc)) from exc

    @router.get('/api/comics/{project_id}')
    def get(project_id:str):
        return load(project_id)

    @router.put('/api/comics/{project_id}')
    def save(project_id:str, request:dict):
        load(project_id)
        try:
            return repository().replace(project_id,request)
        except RevisionConflict as exc:
            raise HTTPException(409,str(exc)) from exc
        except (ValueError,KeyError,TypeError) as exc:
            raise HTTPException(400,str(exc)) from exc

    @router.post('/api/comics/{project_id}/restore')
    def restore(project_id:str,request:dict):
        def apply(project):
            history = project.get('history',[])
            index = int(request['index'])
            if not 0 <= index < len(history):
                raise ValueError('历史版本不存在')
            snapshot = deepcopy(history[index])
            current_panels = deepcopy(project.get('panel_archive',{}))
            current_panels.update({p['id']:deepcopy(p) for p in panels(project)})
            for item in panels(snapshot):
                old = current_panels.get(item['id'],{})
                for key in ('image_versions','current_image','generation_request','generation_error'):
                    item[key] = deepcopy(old.get(key, [] if key=='image_versions' else None))
            restored_ids = {p['id'] for p in panels(snapshot)}
            retained = [p for key,p in current_panels.items() if key not in restored_ids and p.get('image_versions')]
            if retained:
                from .comic import new_page
                recovered = new_page()
                recovered['panels'] = retained
                snapshot['pages'].append(recovered)
            project.update({k:v for k,v in snapshot.items() if k not in {'id','revision','history','panel_archive'}})
        return transact(project_id,apply)

    @router.post('/api/comics/{project_id}/operation')
    def edit(project_id:str, request:dict):
        return transact(project_id,lambda p:operation(p,request))

    @router.post('/api/comics/{project_id}/style')
    def style(project_id:str, request:dict):
        def apply(project):
            preset = api.get_visual_preset_store().get(request['id']) if request.get('id') else {}
            if request.get('id') and (not preset or preset.get('type') != 'style'):
                raise ValueError('画风预设不存在')
            snapshot = deepcopy(preset or {})
            snapshot['reference_mode'] = request.get('reference_mode',snapshot.get('reference_mode','text'))
            snapshot['positive_prompt'] = snapshot.get('positive','')
            snapshot['negative_prompt'] = snapshot.get('negative','')
            snapshot['reference_images'] = []
            for relative in (preset or {}).get('reference_images',[]):
                path = api.get_visual_preset_store().reference_path(relative)
                snapshot['reference_images'].append(repository().add_asset(project_id,path.name,path.read_bytes()))
            project['style'] = snapshot
        return transact(project_id,apply)

    @router.post('/api/comics/{project_id}/assets')
    async def upload(project_id:str,file:UploadFile=File(...),role:str=Form('candidate')):
        load(project_id)
        try:
            data = await file.read(20*1024*1024+1)
            relative = repository().add_asset(project_id,file.filename or 'image.png',data,file.content_type)
            return {'path':relative,'role':role}
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from exc

    @router.get('/api/comics/{project_id}/assets/{path:path}')
    def asset(project_id:str,path:str):
        load(project_id)
        try:
            relative = path if path.startswith('assets/') else 'assets/'+path
            return FileResponse(repository().asset(project_id,relative))
        except ValueError as exc:
            raise HTTPException(404,str(exc)) from exc

    @router.post('/api/comics/{project_id}/plan-task',status_code=202)
    def plan(project_id:str,request:dict):
        load(project_id)
        provider = api.require_llm_provider() if request.get('use_llm',True) else None
        def work(reporter):
            snapshot = load(project_id)
            revision = snapshot['revision']
            reporter.update('规划漫画脚本',5,'生成页、格与独立文字层')
            plan_script(snapshot,int(request.get('pages',4)),int(request.get('panels_per_page',4)),request.get('instructions',''),provider)
            with repository()._lock_for(project_id):
                if load(project_id)['revision'] != revision:
                    raise RevisionConflict('规划期间工程已修改，已保留当前工程，请重新规划')
                repository().save(project_id,snapshot)
            return {'project_id':project_id}
        return manager().submit(project_id,'comic_plan',work)

    @router.post('/api/comics/{project_id}/prompt-task',status_code=202)
    def prompt(project_id:str,request:dict):
        snapshot = load(project_id)
        provider = api.require_llm_provider() if request.get('use_llm',True) else None
        ids = request.get('panel_ids') or [p['id'] for p in panels(snapshot)]
        def work(reporter):
            reporter.update('重建漫画 Prompt',10,'保留脚本、图片与锁定项')
            revision = snapshot['revision']
            rebuild_prompts(snapshot,ids,provider)
            with repository()._lock_for(project_id):
                if load(project_id)['revision'] != revision:
                    raise RevisionConflict('重建期间工程已修改，已保留当前工程')
                repository().save(project_id,snapshot)
            return {'project_id':project_id}
        return manager().submit(project_id,'comic_prompt',work)

    @router.post('/api/comics/{project_id}/generate-task',status_code=202)
    def images(project_id:str,request:dict):
        project = load(project_id)
        active = any(t['status'] in {'running','queued'} and t['task_id'] in manager()._futures for t in manager().list_for_run(project_id))
        if active:
            raise HTTPException(409,'工程已有生成任务正在执行，请等待完成')
        interrupted = [p for p in panels(project) if p.get('generation_status')=='running']
        if interrupted:
            with repository().transaction(project_id) as current:
                for p in panels(current):
                    if p.get('generation_status')=='running':
                        p.update(generation_status='interrupted',generation_error='服务中断，等待按原请求重试')
            project = load(project_id)
        mode = request.get('mode','selected')
        ids = request.get('panel_ids') or []
        if mode == 'missing':
            ids = [p['id'] for p in panels(project) if not p.get('current_image')]
        elif mode == 'failed':
            ids = [p['id'] for p in panels(project) if p.get('generation_error')]
        if not ids:
            raise HTTPException(400,'没有需要生成的画格')
        provider = api.OpenAICompatibleProvider()
        return manager().submit(project_id,'comic_images',lambda reporter:generate(repository(),project_id,provider,ids,
            request.get('size','1024x1024'),int(request.get('retries',0)),reporter,retry_failed=mode=='failed'))

    @router.get('/api/comics/{project_id}/tasks')
    def tasks(project_id:str):
        load(project_id)
        result = manager().list_for_run(project_id)
        for task in result:
            if task['status'] in {'running','queued'} and task['task_id'] not in manager()._futures:
                task.update(status='failed',stage='服务已重启',error='任务执行被服务重启中断，未自动恢复；请手动重试。')
        return {'tasks':result}

    @router.get('/api/comics/{project_id}/check')
    def check(project_id:str):
        project = load(project_id)
        issues = recompute(project)
        from .comic_render import inspect_text
        for page in project['pages']:
            issues.extend(inspect_text(project,page))
        return {'issues':issues}

    @router.get('/api/comics/{project_id}/preview/{page_id}')
    def preview(project_id:str,page_id:str,mode:str|None=None):
        from .comic_render import render_page
        project = load(project_id)
        page = next((p for p in project['pages'] if p['id']==page_id),None)
        if not page:
            raise HTTPException(404,'页面不存在')
        try:
            image = render_page(project,page,lambda p:repository().asset(project_id,p),mode=mode)
            buffer = io.BytesIO()
            image.save(buffer,format='PNG')
            return Response(buffer.getvalue(),media_type='image/png')
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from exc

    @router.get('/api/comics/{project_id}/export')
    def export(project_id:str,format:str='png',mode:str|None=None,page_ids:str=''):
        from .comic_render import export_project,archive_project
        project = load(project_id)
        directory = repository().run_dir(project_id) / 'exports' / uuid4().hex
        directory.mkdir(parents=True)
        resolver = lambda p:repository().asset(project_id,p)
        try:
            path = archive_project(project,directory,resolver) if format=='project' else export_project(project,directory,resolver,format,mode=mode,page_ids=page_ids.split(',') if page_ids else None)
            return FileResponse(path,filename=path.name)
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from exc

    @router.post('/api/comics/import')
    async def import_project(file:UploadFile=File(...)):
        from .comic_render import read_archive
        try:
            data = await file.read(256*1024*1024+1)
            project,assets = read_archive(data)
            validate(project)
            project['id'] = 'comic_'+uuid4().hex
            project['revision'] = 0
            project_dir = repository().run_dir(project['id'])
            project_dir.mkdir(parents=True)
            for relative,content in assets.items():
                # read_archive validates entries; recheck at the write boundary.
                if not relative.startswith('assets/') or '\\' in relative or '..' in Path(relative).parts:
                    raise ValueError('工程包素材路径无效')
                destination = (project_dir / relative).resolve()
                if project_dir not in destination.parents:
                    raise ValueError('工程包路径越界')
                destination.parent.mkdir(parents=True,exist_ok=True)
                destination.write_bytes(content)
            repository().save(project['id'],project)
            return project
        except (ValueError,OSError,KeyError,TypeError) as exc:
            raise HTTPException(400,str(exc)) from exc

    return router
